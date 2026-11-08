"""A drone response is saved as one event: camera snapshot + the drone's view + its video clip."""

import os
import time

from conftest import offset, wait_until

JPG_CAM, JPG_DRONE = b"\xff\xd8camera", b"\xff\xd8drone"
CLIP = b"\x00\x00\x00\x18ftypmp42" + b"0" * 4000


def test_response_event_has_both_views(d, client, fleet, monkeypatch):
    (v1,) = fleet(1)
    d._virtual_cfg["demo_auto"] = True
    monkeypatch.setattr(d, "_camera_snapshot", lambda camera: JPG_CAM)
    monkeypatch.setattr(d, "_drone_snapshot", lambda slot=None: JPG_DRONE)
    monkeypatch.setattr(d, "_fetch_clip", lambda slot, start, end: CLIP)
    monkeypatch.setattr(d, "CLIP_DELAY_S", 0)
    client.post("/api/response/settings", json={"camera_locations": {"front": offset(25, 0)}, "min_battery": 20, "hover_seconds": 10,
                                                "auto_return": True})
    d.STORE.clear_events()
    t0 = int(time.time())  # a response from an earlier test may still be saving its event: ignore it
    r = d.dispatch_drone("front", by="test")
    assert r["ok"], r
    # flies there, hovers 10 s, comes home and lands; then the event is written
    assert wait_until(lambda: d.drone_response["phase"] == "hovering", 60)
    assert wait_until(lambda: not d.drone_response["active"], 90)
    mine = lambda: [e for e in d.STORE.events() if e["Type"] == "DRONE RESPONSE" and e["t"] >= t0]
    assert wait_until(mine, 15)
    row = mine()[0]
    assert row["Type"] == "DRONE RESPONSE" and "front" in row["Name"]
    stem = os.path.splitext(row["Snapshot"])[0]
    assert open(row["Snapshot"], "rb").read() == JPG_CAM
    assert open(stem + "_drone.jpg", "rb").read() == JPG_DRONE
    assert open(stem + "_drone.mp4", "rb").read() == CLIP
    # The history shows the drone view and the clip link.
    html = client.get("/").get_data(as_text=True)
    name = os.path.basename(stem)
    assert f"/events/{name}_drone.jpg" in html and f"/events/{name}_drone.mp4" in html and "DRONE CLIP" in html
    # Deleting the event removes all three files.
    key = d.event_key(row)
    assert client.delete("/api/events/0", json={"key": key}).get_json()["ok"]
    assert not any(os.path.exists(stem + x) for x in (".jpg", "_drone.jpg", "_drone.mp4"))
