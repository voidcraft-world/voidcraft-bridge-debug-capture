from voidcraft_bridge_debug_capture.plugin import DebugCapturePlugin
from voidcraft_bridge_debug_capture.store import CaptureStore
from voidcraft_world_bridge.testing import PluginClient


def test_capture_round_trip_and_discovery(tmp_path):
    plugin = DebugCapturePlugin(store=CaptureStore(tmp_path))
    client = PluginClient(plugin)
    assert client.request("GET", "/latest")[1]["capture"] is None
    status, saved = client.request("POST", "/capture", body={"version": 1, "kind": "example", "count": 3})
    assert status == 200
    assert client.request("GET", "/get", query={"id": [saved["id"]]})[1]["capture"]["count"] == 3
    assert client.request("GET", "/latest")[1]["id"] == saved["id"]
    assert len(client.request("GET", "/list")[1]["captures"]) == 1
    assert client.request("GET", "/state")[1]["count"] == 1
    assert plugin.operations()[0]["method"] == "POST"


def test_rejected_callers_never_write(tmp_path):
    client = PluginClient(DebugCapturePlugin(store=CaptureStore(tmp_path)))
    for headers in ({"Host": "remote.example"}, {"X-Forwarded-For": "127.0.0.1"},
                    {"Sec-Fetch-Site": "cross-site"}):
        assert client.request("POST", "/capture", body={"version": 1}, headers=headers)[0] == 403
    assert not list(tmp_path.iterdir())


def test_invalid_requests_and_wrong_methods(tmp_path):
    client = PluginClient(DebugCapturePlugin(store=CaptureStore(tmp_path)))
    assert client.request("POST", "/capture", body={"version": True})[0] == 400
    assert client.request("GET", "/capture")[0] == 405
    assert client.request("GET", "/get", query={"id": ["../../secret"]})[0] == 404
