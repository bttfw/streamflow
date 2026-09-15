"""
OpenStream stream monitor.

A drop-in alternative to :class:`FFmpegStreamMonitor` that sources a stream's
health from an OpenStream server's continuous swarm-health API instead of running
an ffmpeg process. It duck-types the ffmpeg monitor (``.stats``/``start``/``stop``/
``get_stats``/``get_transport_health``/``is_buffering``) so the existing monitoring
service — reliability scoring (``add_measurement``), ranking and Dispatcharr
reordering — works against it unchanged.

Used only by monitoring sessions of type ``openstream`` (AceStream channels whose
Dispatcharr stream URLs point at an OpenStream/AceStream gateway). Both the API
base URL and the 40-hex content id are derived from the stream URL, so no separate
server configuration is needed.

Mapping OpenStream health -> ffmpeg-style stats:
  * ``speed``       <- ``keepUpMargin``  (cursor advance / live-edge advance; ~1.0 = keeping up)
  * ``is_alive``    <- ``state != "dead"``
  * ``is_buffering``<- ``state in {warming, draining, stalled}``
  * ``bitrate``     <- ``trueBitrateKbps``
Only a reported ``state == "dead"`` marks the stream fatally dead; transient poll
failures never do (a down OpenStream server must not evict every source).
"""

import logging
import re
import threading
import time
from typing import Callable, Optional, Tuple
from urllib.parse import urlsplit, parse_qs

import requests

from apps.core.logging_config import setup_logging
from apps.stream.ffmpeg_stream_monitor import FFmpegStats

logger = setup_logging(__name__)

_CID_RE = re.compile(r"[0-9a-fA-F]{40}")

# How often to poll the OpenStream health API. The server recomputes health ~1 Hz;
# a 2 s client poll is light (a handful of tiny GETs per session) and responsive.
DEFAULT_POLL_INTERVAL = 2.0
_HTTP_TIMEOUT = 5.0

# health.state values that mean "connected but not cleanly keeping up".
_BUFFERING_STATES = {"warming", "draining", "stalled"}


def parse_openstream_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract ``(api_base, content_id)`` from an AceStream gateway stream URL.

    Handles both ``http://host:6878/ace/getstream?id=<40hex>`` and the short
    ``http://host:6878/<40hex>`` form. Returns ``(None, None)`` if no 40-hex
    content id or usable base can be found.
    """
    if not url:
        return None, None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None, None
    if not parts.scheme or not parts.netloc:
        return None, None
    # Prefer the ?id= query param; fall back to the first 40-hex run in the path.
    cid = None
    qs = parse_qs(parts.query)
    if "id" in qs and qs["id"]:
        m = _CID_RE.search(qs["id"][0])
        if m:
            cid = m.group(0)
    if cid is None:
        m = _CID_RE.search(parts.path)
        if m:
            cid = m.group(0)
    if cid is None:
        return None, None
    base = f"{parts.scheme}://{parts.netloc}"
    return base, cid.lower()


class OpenStreamStreamMonitor:
    """Polls an OpenStream server for one source's health. See module docstring."""

    def __init__(
        self,
        url: str,
        stream_id: Optional[int] = None,
        on_stats_update: Optional[Callable[[FFmpegStats], None]] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ):
        self.url = url
        self.stream_id = stream_id
        self.on_stats_update = on_stats_update
        self.poll_interval = poll_interval
        self.stats = FFmpegStats(url=url)
        self.base, self.content_id = parse_openstream_url(url)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._buffering = False
        self._state = "warming"
        self._error_density = 0.0
        # No UDP sidecar pipes (screenshots/CV don't apply to health monitoring);
        # present as attributes so any incidental access stays safe.
        self.port_a = None
        self.port_b = None

    # ---- lifecycle (mirrors FFmpegStreamMonitor) ----

    def start(self) -> bool:
        if not self.base or not self.content_id:
            self.stats.is_alive = False
            self.stats.error_message = "Not an OpenStream/AceStream URL (no content id)"
            return False
        self._admit()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name=f"os-mon-{self.stream_id}", daemon=True
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        t = self._thread
        # stop() may be invoked from inside the poll thread itself (the monitoring
        # service calls monitor.stop() from the on_stats_update callback when a
        # source goes dead). Never join our own thread — setting the event above is
        # enough; the loop exits on its next check.
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=self.poll_interval + 1.0)
        # Best-effort: release the warm session so an unwatched source is not
        # pulled forever. Harmless if another session still wants it (re-admitted).
        self._remove()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def is_alive(self) -> bool:
        return bool(self.stats.is_alive)

    def is_buffering(self) -> bool:
        return self._buffering

    def get_stats(self) -> FFmpegStats:
        return self.stats

    def get_transport_health(self):
        status = "healthy"
        if self._state == "dead":
            status = "dead"
        elif self._buffering:
            status = "degraded"
        return {"status": status, "summary": f"openstream:{self._state}", "error_density": self._error_density}

    # ---- OpenStream API ----

    def _admit(self):
        try:
            requests.post(
                f"{self.base}/api/streams",
                json={"ids": [self.content_id]},
                timeout=_HTTP_TIMEOUT,
            )
        except requests.RequestException as e:
            logger.debug("OpenStream admit failed for %s: %s", self.content_id, e)

    def _remove(self):
        if not self.base or not self.content_id:
            return
        try:
            requests.post(
                f"{self.base}/api/actions",
                json={"op": "remove", "ids": [self.content_id]},
                timeout=_HTTP_TIMEOUT,
            )
        except requests.RequestException:
            pass

    def _poll_loop(self):
        while not self._stop.is_set():
            self._poll_once()
            if self.on_stats_update:
                try:
                    self.on_stats_update(self.stats)
                except Exception:  # never let a callback kill the poll loop
                    logger.exception("on_stats_update raised for stream %s", self.stream_id)
            self._stop.wait(self.poll_interval)

    def _poll_once(self):
        try:
            resp = requests.get(
                f"{self.base}/api/streams/{self.content_id}", timeout=_HTTP_TIMEOUT
            )
        except requests.RequestException as e:
            # Transient: the server is unreachable. Report buffering (unknown), never
            # fatal — a down server must not mark every source dead.
            self._buffering = True
            self.stats.speed = 0.0
            self.stats.is_alive = True
            self.stats.error_message = None
            logger.debug("OpenStream poll failed for %s: %s", self.content_id, e)
            return
        if resp.status_code == 404:
            # Not admitted (or reaped) — re-admit and treat as warming.
            self._admit()
            self._apply_warming()
            return
        try:
            snap = resp.json()
        except ValueError:
            self._buffering = True
            return
        self._apply_snapshot(snap if isinstance(snap, dict) else {})

    def _apply_warming(self):
        self._state = "warming"
        self._buffering = True
        self.stats.is_alive = True
        self.stats.speed = 0.0
        self.stats.last_updated = time.time()

    def _apply_snapshot(self, snap: dict):
        health = snap.get("health") if isinstance(snap.get("health"), dict) else None
        if not health:
            # Session exists but no health yet (just started) -> warming.
            self._apply_warming()
            return
        state = str(health.get("state") or "warming")
        margin = _as_float(health.get("keepUpMargin"))
        true_bitrate = _as_float(health.get("trueBitrateKbps"))
        self._state = state
        self._error_density = max(0.0, min(1.0, 1.0 - margin))
        self.stats.last_updated = time.time()
        self.stats.bitrate = true_bitrate

        if state == "dead":
            self.stats.is_alive = False
            self.stats.is_fatal = True
            self.stats.error_message = "OpenStream: no live source (dead)"
            self._buffering = False
            return

        self.stats.is_alive = True
        self.stats.is_fatal = False
        self.stats.error_message = None
        self.stats.speed = margin
        # Buffering when the source is connected but not cleanly keeping up, so the
        # reliability window (is_healthy = is_alive and not is_buffering) credits
        # only genuinely-healthy measurements.
        self._buffering = state in _BUFFERING_STATES or margin < 0.9


def _as_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
