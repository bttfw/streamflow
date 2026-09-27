"""OpenStream's control plane needs an API key: the monitor must send it, and a
refused key must be reported without marking sources dead."""

from unittest.mock import Mock

import pytest
import requests

from apps.config import openstream_config as cfg_module
from apps.stream import openstream_monitor as mon_module
from apps.stream.openstream_monitor import OpenStreamStreamMonitor

CID = "aabbccddeeff00112233445566778899aabbccdd"
URL = f"http://os:6878/ace/getstream?id={CID}"


def _resp(status, body=None):
    r = Mock(status_code=status)
    r.json.return_value = body if body is not None else {}
    return r


def test_stored_key_round_trip_and_env_override(monkeypatch, tmp_path):
    config = cfg_module.get_openstream_config()
    assert config.get_config()["has_api_key"] is False
    assert cfg_module.openstream_headers() == {}

    assert config.update_config(api_key=" k1 ", test_url="http://os:6878/")
    assert config.get_api_key() == "k1"
    assert config.get_test_url() == "http://os:6878"
    assert cfg_module.openstream_headers() == {"X-API-Key": "k1"}
    assert "k1" not in str(config.get_config())  # the UI never gets the key back

    config.update_config(api_key=None)  # None keeps the saved key
    assert config.get_api_key() == "k1"

    secret = tmp_path / "os_key"
    secret.write_text("from-file\n")
    monkeypatch.setenv("OPENSTREAM_API_KEY_FILE", str(secret))
    assert config.get_api_key() == "from-file"
    assert config.get_config()["api_key_managed_externally"] is True

    monkeypatch.delenv("OPENSTREAM_API_KEY_FILE")
    config.update_config(api_key="")  # clear
    assert config.get_api_key() is None


def test_monitor_sends_key_on_every_call(monkeypatch):
    cfg_module.get_openstream_config().update_config(api_key="secret")
    get = Mock(return_value=_resp(200, {"health": {"state": "healthy", "keepUpMargin": 1.0}}))
    post = Mock(return_value=_resp(200))
    monkeypatch.setattr(mon_module.requests, "get", get)
    monkeypatch.setattr(mon_module.requests, "post", post)

    m = OpenStreamStreamMonitor(url=URL, stream_id=1)
    m._admit()
    m._poll_once()
    m._remove()

    assert get.call_args.kwargs["headers"] == {"X-API-Key": "secret"}
    for call in post.call_args_list:
        assert call.kwargs["headers"] == {"X-API-Key": "secret"}
    assert m.stats.is_alive and not m.is_buffering()


@pytest.mark.parametrize("status,needle", [(401, "rejected"), (403, "requires an API key"), (428, "first-run setup")])
def test_refused_key_is_reported_but_not_fatal(monkeypatch, status, needle):
    monkeypatch.setattr(mon_module.requests, "get", Mock(return_value=_resp(status, {"error": "x"})))
    m = OpenStreamStreamMonitor(url=URL, stream_id=1)
    m._poll_once()
    assert m.stats.is_alive is True
    assert m.stats.is_fatal is False
    assert m.is_buffering() is True
    assert needle in m.stats.error_message
    assert m.get_transport_health()["status"] != "dead"


def test_recovers_once_key_is_accepted(monkeypatch):
    get = Mock(return_value=_resp(403))
    monkeypatch.setattr(mon_module.requests, "get", get)
    m = OpenStreamStreamMonitor(url=URL, stream_id=1)
    m._poll_once()
    assert m.stats.error_message

    get.return_value = _resp(200, {"health": {"state": "healthy", "keepUpMargin": 1.0}})
    m._poll_once()
    assert m.stats.error_message is None
    assert m.is_buffering() is False


def test_test_connection_endpoint(monkeypatch):
    from apps.api import openstream_handlers
    from apps.api.web_api import app

    get = Mock(return_value=_resp(200))
    monkeypatch.setattr(openstream_handlers.requests, "get", get)
    client = app.test_client()

    # A stream URL is accepted as the server address; the entered key is used.
    r = client.post("/api/openstream/test-connection", json={"test_url": URL, "api_key": "typed"})
    assert r.status_code == 200 and r.get_json()["success"] is True
    assert get.call_args.args[0] == "http://os:6878/api/fleet"
    assert get.call_args.kwargs["headers"] == {"X-API-Key": "typed"}

    get.return_value = _resp(401)
    r = client.post("/api/openstream/test-connection", json={"test_url": "http://os:6878", "api_key": "bad"})
    assert r.status_code == 400 and "rejected" in r.get_json()["error"]

    get.side_effect = requests.exceptions.ConnectionError()
    r = client.post("/api/openstream/test-connection", json={"test_url": "http://os:6878"})
    assert r.status_code == 400 and "Could not connect" in r.get_json()["error"]

    r = client.post("/api/openstream/test-connection", json={})
    assert r.status_code == 400


def test_config_endpoints_never_return_the_key():
    from apps.api.web_api import app

    client = app.test_client()
    assert client.put("/api/openstream/config", json={"api_key": "s3cret", "test_url": "http://os:6878"}).status_code == 200
    body = client.get("/api/openstream/config").get_json()
    assert body == {"has_api_key": True, "api_key_managed_externally": False, "test_url": "http://os:6878"}
    # Saving the form with an empty key field keeps the saved key.
    client.put("/api/openstream/config", json={"api_key": "", "test_url": "http://os:6878"})
    assert cfg_module.get_openstream_config().get_api_key() == "s3cret"
    client.put("/api/openstream/config", json={"clear_api_key": True})
    assert client.get("/api/openstream/config").get_json()["has_api_key"] is False
