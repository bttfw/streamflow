"""Channel API handler functions extracted from web_api."""

import os
import ipaddress
import socket
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Dict
from urllib.parse import urljoin, urlsplit

import requests
from flask import jsonify, send_file

from apps.channels.service import ChannelQuery
from apps.core.api_responses import error_response
from apps.core.logging_config import setup_logging

logger = setup_logging(__name__)

MAX_LOGO_BYTES = 4 * 1024 * 1024
MAX_LOGO_CACHE_BYTES = 512 * 1024 * 1024
MAX_LOGO_REDIRECTS = 3
LOGO_DOWNLOAD_DEADLINE_SECONDS = 20
_LOGO_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
_LOGO_CACHE_LOCK = threading.Lock()


class InvalidLogoResponse(ValueError):
    """The upstream response is unsuitable for the local logo cache."""


def _logo_url_origin(url: str) -> tuple[str, str, int]:
    if not isinstance(url, str) or "\\" in url or any(ord(char) < 32 for char in url):
        raise InvalidLogoResponse("Logo URL contains invalid characters")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise InvalidLogoResponse("Logo URL is invalid") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise InvalidLogoResponse("Logo URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None or "%" in parsed.hostname:
        raise InvalidLogoResponse("Logo URL contains an invalid host or credentials")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise InvalidLogoResponse("Logo URL contains an invalid port") from exc
    return parsed.scheme.lower(), parsed.hostname.lower().rstrip("."), port


def _check_logo_url(url: str, dispatcharr_origin: tuple[str, str, int]) -> None:
    """Keep LAN provider logos while blocking local services and metadata endpoints."""
    origin = _logo_url_origin(url)
    hostname = origin[1]
    if hostname == "metadata.google.internal" or hostname == "instance-data":
        raise InvalidLogoResponse("Logo URL points to a metadata service")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        if origin != dispatcharr_origin:
            raise InvalidLogoResponse("Logo URL points to a local service")
        return

    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(address[4][0])
                for address in socket.getaddrinfo(hostname, origin[2], type=socket.SOCK_STREAM)
            ]
        except (OSError, ValueError) as exc:
            raise InvalidLogoResponse("Logo hostname could not be resolved") from exc

    for address in addresses:
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if address.is_link_local or address.is_multicast or address.is_unspecified:
            raise InvalidLogoResponse("Logo URL points to a restricted address")
        if address.is_loopback and origin != dispatcharr_origin:
            raise InvalidLogoResponse("Logo URL points to a local service")


def _download_logo(url: str, dispatcharr_origin: tuple[str, str, int]) -> tuple[bytes, str]:
    deadline = time.monotonic() + LOGO_DOWNLOAD_DEADLINE_SECONDS
    for redirect_count in range(MAX_LOGO_REDIRECTS + 1):
        _check_logo_url(url, dispatcharr_origin)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise InvalidLogoResponse("Logo download timed out")
        response = requests.get(
            url,
            timeout=(min(3, remaining), min(8, remaining)),
            verify=True,
            stream=True,
            allow_redirects=False,
        )
        try:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if not location or redirect_count >= MAX_LOGO_REDIRECTS:
                    raise InvalidLogoResponse("Logo redirected too many times")
                url = urljoin(url, location)
                continue
            response.raise_for_status()

            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    advertised_size = int(content_length)
                except ValueError as exc:
                    raise InvalidLogoResponse("Logo has an invalid Content-Length") from exc
                if advertised_size > MAX_LOGO_BYTES:
                    raise InvalidLogoResponse("Logo exceeds the download size limit")

            content = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if time.monotonic() > deadline:
                    raise InvalidLogoResponse("Logo download timed out")
                content.extend(chunk)
                if len(content) > MAX_LOGO_BYTES:
                    raise InvalidLogoResponse("Logo exceeds the download size limit")
            if not content:
                raise InvalidLogoResponse("Logo response is empty")
            return bytes(content), response.headers.get("Content-Type", "")
        finally:
            response.close()
    raise InvalidLogoResponse("Logo redirected too many times")


def _logo_extension(content: bytes, content_type: str) -> str:
    """Use image bytes for the extension; never serve arbitrary upstream HTML."""
    mime = content_type.split(";", 1)[0].strip().lower()
    mime = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg", "image/x-png": "image/png"}.get(mime, mime)
    if mime not in {"", "application/octet-stream", "text/plain", "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}:
        raise InvalidLogoResponse("Logo has an unsupported content type")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        ext, expected_mime = ".png", "image/png"
    elif content.startswith(b"\xff\xd8\xff"):
        ext, expected_mime = ".jpg", "image/jpeg"
    elif content.startswith((b"GIF87a", b"GIF89a")):
        ext, expected_mime = ".gif", "image/gif"
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        ext, expected_mime = ".webp", "image/webp"
    else:
        if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
            raise InvalidLogoResponse("Logo SVG contains a document type or entity")
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise InvalidLogoResponse("Logo is not a supported image") from exc
        if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
            raise InvalidLogoResponse("Logo is not a supported image")
        ext, expected_mime = ".svg", "image/svg+xml"
    if mime.startswith("image/") and mime != expected_mime:
        raise InvalidLogoResponse("Logo content type does not match its image bytes")
    return ext


def _send_cached_logo(path: Path, ext: str):
    mimetype = "image/svg+xml" if ext == ".svg" else f"image/{'jpeg' if ext in ('.jpg', '.jpeg') else ext[1:]}"
    response = send_file(path, mimetype=mimetype)
    response.headers["X-Content-Type-Options"] = "nosniff"
    if ext == ".svg":
        response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    return response


def _prune_logo_cache(cache_dir: Path, protected_path: Path) -> None:
    files = []
    total_bytes = 0
    for path in cache_dir.glob("logo_*"):
        if path.suffix not in _LOGO_EXTENSIONS or not path.is_file():
            continue
        stat = path.stat()
        files.append((stat.st_mtime, path, stat.st_size))
        total_bytes += stat.st_size
    for _, path, size in sorted(files):
        if total_bytes <= MAX_LOGO_CACHE_BYTES:
            break
        if path != protected_path:
            try:
                path.unlink(missing_ok=True)
                total_bytes -= size
            except OSError as exc:
                logger.warning("Could not prune cached logo %s: %s", path, exc)


def get_channels_response(
    *,
    request_args: Any,
    parse_pagination_params: Callable[..., Any],
    get_channel_service: Callable[[], Any],
):
    """Handle channel listing with filtering, sorting, and pagination."""
    try:
        search = request_args.get("search", "").strip()
        sort_by = request_args.get("sort_by", "name")
        sort_dir = request_args.get("sort_dir", "asc")
        page_param = request_args.get("page", None)
        per_page_param = request_args.get("per_page", "50")

        page, per_page, err = parse_pagination_params(page_param, per_page_param)
        if err:
            return err

        if sort_dir not in ("asc", "desc"):
            sort_dir = "asc"

        result = get_channel_service().list_channels(
            ChannelQuery(
                search=search,
                sort_by=sort_by,
                sort_dir=sort_dir,
                page=page,
                per_page=per_page,
            )
        )

        if "error" in result:
            return error_response(
                result["error"],
                status_code=result.get("status", 500),
                code="channels_fetch_failed",
            )

        if not result.get("paginated", False):
            return jsonify(result["items"])

        return jsonify(
            {
                "items": result["items"],
                "total": result["total"],
                "page": result["page"],
                "per_page": result["per_page"],
                "total_pages": result["total_pages"],
                "has_next": result["has_next"],
                "has_prev": result["has_prev"],
            }
        )
    except Exception as exc:
        logger.error(f"Error fetching channels: {exc}")
        return jsonify({"error": "Internal Server Error"}), 500


def get_channel_stats_response(
    *,
    channel_id: str,
    get_channel_service: Callable[[], Any],
):
    """Handle channel statistics lookup."""
    try:
        try:
            channel_id_int = int(channel_id)
        except (ValueError, TypeError):
            return error_response(
                "Invalid channel ID: must be a valid integer",
                status_code=400,
                code="invalid_channel_id",
            )

        result = get_channel_service().get_channel_stats(channel_id_int)
        if "error" in result:
            return error_response(
                result["error"],
                status_code=result.get("status", 500),
                code="channel_stats_failed",
            )

        return jsonify(result["data"])
    except Exception as exc:
        logger.error(f"Error fetching channel stats: {exc}")
        return jsonify({"error": "Internal Server Error"}), 500


def get_channel_groups_response(*, get_udi_manager: Callable[[], Any]):
    """Handle channel group listing."""
    try:
        udi = get_udi_manager()
        groups = udi.get_channel_groups()

        if groups is None:
            return jsonify({"error": "Failed to fetch channel groups"}), 500

        return jsonify(groups)
    except Exception as exc:
        logger.error(f"Error fetching channel groups: {exc}")
        return jsonify({"error": "Internal Server Error"}), 500


def get_channel_logo_response(*, logo_id: str, get_udi_manager: Callable[[], Any]):
    """Handle logo object lookup from UDI."""
    try:
        udi = get_udi_manager()
        logo = udi.get_logo_by_id(int(logo_id))

        if logo is None:
            return jsonify({"error": "Failed to fetch logo"}), 500

        return jsonify(logo)
    except Exception as exc:
        logger.error(f"Error fetching logo: {exc}")
        return jsonify({"error": "Internal Server Error"}), 500


def get_channel_logo_cached_response(
    *,
    logo_id: str,
    config_dir: Path,
    get_udi_manager: Callable[[], Any],
    get_dispatcharr_config: Callable[[], Any],
):
    """Download and cache channel logo locally, then serve it."""
    try:
        try:
            logo_id_int = int(logo_id)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid logo ID: must be a valid integer"}), 400

        if logo_id_int <= 0:
            return jsonify({"error": "Invalid logo ID: must be a positive integer"}), 400

        logos_cache_dir = config_dir / "logos_cache"
        logos_cache_dir.mkdir(exist_ok=True)

        logo_filename = f"logo_{logo_id_int}"
        for ext in _LOGO_EXTENSIONS:
            cached_path = logos_cache_dir / f"{logo_filename}{ext}"
            if cached_path.exists():
                if cached_path.stat().st_size <= MAX_LOGO_BYTES:
                    return _send_cached_logo(cached_path, ext)
                cached_path.unlink()

        udi = get_udi_manager()
        logo = udi.get_logo_by_id(logo_id_int)
        if not logo:
            return jsonify({"error": "Logo not found"}), 404

        dispatcharr_config = get_dispatcharr_config()
        dispatcharr_base_url = dispatcharr_config.get_base_url()
        if not dispatcharr_base_url:
            dispatcharr_base_url = os.getenv("DISPATCHARR_BASE_URL", "")
            if not dispatcharr_base_url:
                return jsonify({"error": "DISPATCHARR_BASE_URL not configured"}), 500

        logo_url = logo.get("cache_url") or logo.get("url")
        if not logo_url:
            return jsonify({"error": "Logo URL not available"}), 404
        if not isinstance(logo_url, str):
            raise InvalidLogoResponse("Logo URL is invalid")

        dispatcharr_origin = _logo_url_origin(dispatcharr_base_url)
        if logo_url.startswith("//"):
            raise InvalidLogoResponse("Logo URL must include a scheme")
        if logo_url.startswith("/"):
            logo_url = urljoin(f"{dispatcharr_base_url.rstrip('/')}/", logo_url)

        logger.debug("Downloading logo %s", logo_id_int)
        content, content_type = _download_logo(logo_url, dispatcharr_origin)
        ext = _logo_extension(content, content_type)
        cached_path = logos_cache_dir / f"{logo_filename}{ext}"
        with _LOGO_CACHE_LOCK:
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=logos_cache_dir, prefix=f".{logo_filename}_", suffix=".tmp", delete=False
                ) as file_obj:
                    temporary_path = Path(file_obj.name)
                    file_obj.write(content)
                temporary_path.replace(cached_path)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
            _prune_logo_cache(logos_cache_dir, cached_path)

        logger.debug(f"Cached logo {logo_id} to {cached_path}")

        return _send_cached_logo(cached_path, ext)

    except InvalidLogoResponse as exc:
        logger.warning("Rejected logo %s: %s", logo_id, exc)
        return jsonify({"error": str(exc)}), 422
    except requests.exceptions.RequestException as exc:
        logger.error(f"Error downloading logo {logo_id}: {exc}")
        return jsonify({"error": "Failed to download logo"}), 500
    except Exception as exc:
        logger.error(f"Error caching logo {logo_id}: {exc}")
        return jsonify({"error": "Internal Server Error"}), 500
