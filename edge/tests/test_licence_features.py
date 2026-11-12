"""The newer features follow the client's licence: the provider switches them on or off per client."""
import pytest


@pytest.fixture
def licence(d, monkeypatch):
    """A cloud licence with chosen features; restored afterwards."""
    saved = dict(d.cloud_state)

    def set_features(**features):
        with d.cloud_lock:
            d.cloud_state["licensed"] = True
            d.cloud_state["features"] = {k: {"enabled": v, "limit_value": None} for k, v in features.items()}
    monkeypatch.setattr(d, "onprem_mode", lambda: False)
    yield set_features
    with d.cloud_lock:
        d.cloud_state.clear()
        d.cloud_state.update(saved)


def test_features_not_set_by_the_provider_stay_available(d, licence):
    licence(camera_ai=True)  # an account from before these switches existed
    assert all(d.premium_allowed(k) for k in d.PREMIUM_FEATURES)
    with d.cloud_lock:
        d.cloud_state["organization_status"] = "suspended"  # suspended in the portal: all off
    assert not any(d.premium_allowed(k) for k in d.PREMIUM_FEATURES)


def test_switched_off_features_are_refused_and_turn_off(d, client, licence):
    licence(smart_patrol=True, handoff=True, verified_alarms=True, incident_replay=True)
    assert client.post("/api/response/settings", json={"handoff": True}).status_code == 200
    assert d.load_response_settings()["handoff"] is True
    licence(smart_patrol=False, handoff=False, verified_alarms=False, incident_replay=False, phone_access=False)
    assert d.load_response_settings()["handoff"] is False  # off as soon as the licence drops it
    r = client.post("/api/response/settings", json={"handoff": True})
    assert r.status_code == 400 and "isn't included in this PC's licence" in r.get_json()["error"]
    r = client.post("/api/smart-patrol", json={"smart_patrol": True})
    assert r.status_code == 400 and "Smart patrol" in r.get_json()["error"]
    r = client.post("/api/alarms/settings", json={"verified_alarms": True})
    assert r.status_code == 400
    assert client.get("/incidents/1/replay").status_code == 403
    assert client.get("/api/incidents/1/replay").status_code == 403
    assert d._cloud_sync_enabled() is False
    assert client.get("/api/cloud/status").get_json().get("premium", {}).get("smart_patrol") in (False, None)
    licence(handoff=True)
    assert client.post("/api/response/settings", json={"handoff": False}).status_code == 200


def test_onprem_licence_lists_the_features(d, monkeypatch):
    monkeypatch.setattr(d, "onprem_mode", lambda: True)
    monkeypatch.setitem(d.offline_license, "payload", {"features": ["camera_ai", "smart_patrol"], "feature_set": 2})
    assert d.premium_allowed("smart_patrol") and not d.premium_allowed("handoff")
    monkeypatch.setitem(d.offline_license, "payload", {"features": ["camera_ai"]})  # issued before: all included
    assert d.premium_allowed("handoff")
