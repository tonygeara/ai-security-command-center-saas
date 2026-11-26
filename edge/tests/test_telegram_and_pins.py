"""Telegram "intruder warnings only" (on by default) and drones pinned on the Drone page map."""
import json

import pytest

from conftest import HOME


@pytest.fixture
def tg(d, monkeypatch):
    """What would really reach Telegram."""
    sent = []
    monkeypatch.setattr(d, "_tg", lambda method, **data: sent.append(data.get("text") or data.get("caption") or method) or {"ok": True})
    monkeypatch.setattr(d, "telegram_ready", lambda cfg=None: True)
    monkeypatch.setattr(d, "load_telegram_config", lambda: {**d.TELEGRAM_DEFAULTS, "bot_token": "x", "chat_id": "1", "cooldown_seconds": 0})
    queued = []
    monkeypatch.setattr(d.telegram_queue, "put", lambda item: queued.append(item["text"]))
    yield sent, queued
    d._save_customer_settings({**d._load_customer_settings(), "telegram_intruders_only": True})


def test_intruder_warnings_only_is_on_by_default_and_filters(d, client, tg):
    sent, queued = tg
    send = d._send_telegram_real
    assert d.DEFAULT_CUSTOMER_SETTINGS["telegram_intruders_only"] is True and d.telegram_intruders_only()
    assert send("🗺️ Route started") is None                                  # a notice: not sent
    assert send("🛸 Unknown drone at Gate", warning=True)                     # an intruder warning: sent
    assert send("Start the patrol?", buttons=[[{"text": "Yes", "callback_data": "x"}]])  # a question: sent
    d._tg_reply.on = True
    try:
        assert send("Status: all good")                                        # a reply to the owner: sent
    finally:
        d._tg_reply.on = False
    assert d.send_telegram_album([b"a", b"b"], "Patrol report") is None        # reports: not sent
    assert d.queue_telegram_alert("known_face", "Tony at the gate", "k1") is False
    assert d.queue_telegram_alert("casing", "Same plate 3 times", "k2") is False
    assert d.queue_telegram_alert("unknown_face", "Unknown person at the gate", "k3", snapshot_bytes=b"x") is True
    assert sent == ["🛸 Unknown drone at Gate", "Start the patrol?", "Status: all good"]
    assert queued == ["Unknown person at the gate"]
    # Switched off in Settings: everything goes again.
    d._save_customer_settings({**d._load_customer_settings(), "telegram_intruders_only": False})
    assert send("🗺️ Route started") and d.queue_telegram_alert("known_face", "Tony at the gate", "k4", snapshot_bytes=b"x") is True
    assert 'data-key="telegram_intruders_only"' in client.get("/settings").get_data(as_text=True)


def test_drone_pin_shows_a_drone_with_no_position(d, client):
    r = client.get("/api/drone/pin?drone=drone").get_json()
    assert r["ok"] and r["pin"] is None
    assert client.post("/api/drone/pin?drone=drone", json={"lat": 200, "lon": 0}).status_code == 400
    assert client.post("/api/drone/pin?drone=nope", json={"lat": 1, "lon": 1}).status_code == 404
    r = client.post("/api/drone/pin?drone=drone", json={"lat": HOME[0], "lon": HOME[1]}).get_json()
    assert r["pin"]["lat"] == round(HOME[0], 7) and r["pins"]["drone"]["label"]
    assert json.load(open(d.DRONE_PINS_FILE))["drone"]["lon"] == round(HOME[1], 7)
    assert client.post("/api/drone/pin?drone=drone", json={"clear": True}).get_json()["pin"] is None
    import users
    assert users.allowed("operator", "POST", "/api/drone/pin") and not users.allowed("viewer", "POST", "/api/drone/pin")
    html = client.get("/drone-control").get_data(as_text=True)
    assert "findDrone()" in html and "pinMode()" in html and "function ensureMap" in html and "const IS_VIRTUAL=false" in html
