"""4D incident replay: the data behind it comes from a real drone response."""
from conftest import offset, wait_until


def test_replay_data_from_a_drone_response(d, client, fleet, monkeypatch):
    (v1,) = fleet(1)
    d._virtual_cfg["demo_auto"] = True
    monkeypatch.setattr(d, "_camera_snapshot", lambda camera: b"\xff\xd8cam")
    monkeypatch.setattr(d, "_drone_snapshot", lambda slot=None: b"\xff\xd8drone")
    monkeypatch.setattr(d, "_fetch_clip", lambda slot, start, end: None)
    monkeypatch.setattr(d, "CLIP_DELAY_S", 0)
    client.post("/api/response/settings", json={"camera_locations": {"rcam": offset(20, 10)}, "min_battery": 20, "hover_seconds": 5,
                                                "auto_return": True, "camera_views": {"rcam": {"heading": 45, "fov": 80, "range": 25}}})
    assert d.dispatch_drone("rcam", by="test")["ok"]
    assert wait_until(lambda: not d.drone_response["active"], 120)
    d.PIPELINE.flush()
    inc = next(i for i in client.get("/api/incidents?days=1&min=1").get_json()["incidents"] if i["camera"] == "rcam")
    assert wait_until(lambda: client.get(f"/api/incidents/{inc['id']}/replay").get_json()["events"], 20)
    r = client.get(f"/api/incidents/{inc['id']}/replay").get_json()
    assert r["ok"] and r["incident"]["camera"] == "rcam"
    assert abs(r["centre"]["lat"] - offset(20, 10)["lat"]) < 1e-9  # centred on the camera
    assert len(r["track"]) >= 3 and all({"t", "lat", "lon"} <= set(p) for p in r["track"])
    sent = [i for i in r["items"] if i["kind"] == "dispatch"]
    assert sent and abs(sent[0]["data"]["lat"] - offset(20, 10)["lat"]) < 1e-9  # where the drone was sent
    assert any(c["name"] == "rcam" and c["view"]["fov"] == 80 for c in r["cameras"])
    assert r["events"][0]["image"].startswith("/events/drone_response_")
    assert client.get(f"/incidents/{inc['id']}/replay").status_code == 200
    assert client.get("/api/incidents/999999/replay").status_code == 404
    client.post("/api/response/settings", json={"camera_views": {}})
