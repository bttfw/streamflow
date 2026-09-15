"""Unit tests for the OpenStream monitoring backend (URL parsing + health mapping)."""

from apps.stream.openstream_monitor import OpenStreamStreamMonitor, parse_openstream_url

CID = "aabbccddeeff00112233445566778899aabbccdd"


def test_parse_getstream_url():
    base, cid = parse_openstream_url(f"http://host:6878/ace/getstream?id={CID}")
    assert base == "http://host:6878"
    assert cid == CID


def test_parse_short_path_url():
    base, cid = parse_openstream_url(f"http://10.0.0.5:6878/{CID}")
    assert base == "http://10.0.0.5:6878"
    assert cid == CID


def test_parse_uppercase_id_is_lowercased():
    _, cid = parse_openstream_url(f"http://h:6878/ace/getstream?id={CID.upper()}")
    assert cid == CID


def test_parse_non_acestream_url():
    assert parse_openstream_url("http://host/live/channel.m3u8") == (None, None)
    assert parse_openstream_url("") == (None, None)
    assert parse_openstream_url("not a url") == (None, None)


def _monitor():
    return OpenStreamStreamMonitor(url=f"http://host:6878/ace/getstream?id={CID}", stream_id=1)


def test_healthy_snapshot_maps_to_alive_keeping_up():
    m = _monitor()
    m._apply_snapshot({"health": {"state": "healthy", "keepUpMargin": 1.0, "trueBitrateKbps": 4200}})
    assert m.stats.is_alive is True
    assert m.stats.is_fatal is False
    assert m.is_buffering() is False
    assert m.stats.speed == 1.0
    assert m.stats.bitrate == 4200
    assert m.get_transport_health()["status"] == "healthy"


def test_draining_snapshot_is_buffering():
    m = _monitor()
    m._apply_snapshot({"health": {"state": "draining", "keepUpMargin": 0.7}})
    assert m.stats.is_alive is True
    assert m.is_buffering() is True
    assert m.get_transport_health()["status"] == "degraded"


def test_dead_snapshot_is_fatal():
    m = _monitor()
    m._apply_snapshot({"health": {"state": "dead", "keepUpMargin": 0.0}})
    assert m.stats.is_alive is False
    assert m.stats.is_fatal is True
    assert m.get_transport_health()["status"] == "dead"


def test_missing_health_is_warming():
    m = _monitor()
    m._apply_snapshot({"contentID": CID})  # session exists, no health yet
    assert m.stats.is_alive is True          # not dead — just starting
    assert m.is_buffering() is True          # warming counts as not-yet-healthy
    assert m.stats.speed == 0.0
