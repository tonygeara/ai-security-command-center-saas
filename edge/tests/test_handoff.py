"""Camera-to-drone handoff: off by default; when on, someone leaving a camera's view sends a drone after them."""
import os
import sys

import pytest

from conftest import APP, HOME, offset, wait_until

sys.path.insert(0, os.path.abspath(APP))
import handoff  # noqa: E402

CAM = {"lat": HOME[0], "lon": HOME[1], "view": {"heading": 0, "fov": 90, "range": 30}}


@pytest.fixture
def h():
    cfg = {"handoff": True, "auto_person": True, "auto_vehicle": True, "auto_from": "00:00", "auto_to": "00:00",
           "auto_cooldown_min": 10}
    sent, alerts = [], []
    ho = handoff.Handoff(lambda: cfg, lambda: {"front": CAM}, lambda cam: (640, 480),
                         lambda lat, lon, by: sent.append((lat, lon, by)) or {"ok": True, "message": "Drone 1 on its way."},
                         lambda kind, **m: alerts.append(m), lambda a, b: True, lambda: True, run_async=False)
    return ho, cfg, sent, alerts


def walk(ho, oid, label="person", t0=1000.0, boxes=([300, 300, 340, 400], [450, 300, 490, 400], [610, 300, 640, 400]),
         stationary=False, camera="front"):
    for i, b in enumerate(boxes):
        ho.on_track({"kind": "track", "t": t0 + i * 1.5, "camera": camera, "type": "new" if i == 0 else "update",
                     "object_id": oid, "label": label, "box": b, "stationary": stationary, "false_positive": False})
    ho.on_track({"kind": "track", "t": t0 + len(boxes) * 1.5, "camera": camera, "type": "end", "object_id": oid,
                 "label": label, "box": boxes[-1], "stationary": stationary, "false_positive": False})


def test_leaving_by_the_right_sends_a_drone_to_the_right(h):
    ho, cfg, sent, alerts = h
    walk(ho, "p1")
    (lat, lon, by), = sent
    assert lon > HOME[1] and "handoff: person left front (right)" == by
    assert alerts[0]["alert"] == "handoff" and "left front's view" in alerts[0]["text"] and alerts[0]["buttons"]


def test_off_by_default_switch_choices_and_cooldown(h):
    ho, cfg, sent, _ = h
    cfg["handoff"] = False
    walk(ho, "a")
    cfg["handoff"] = True
    walk(ho, "b", boxes=([300, 300, 340, 400],))              # seen too briefly
    walk(ho, "c", label="car", stationary=True)               # parked car
    walk(ho, "d", label="dog")                                # not a person or vehicle
    walk(ho, "e", camera="back")                              # camera not on the Coverage page
    cfg["auto_person"] = False
    walk(ho, "f")
    assert sent == []
    cfg["auto_person"] = True
    walk(ho, "g")
    walk(ho, "h")                                              # same camera within the cooldown
    assert len(sent) == 1


def test_handoff_through_the_dashboard(d, client, fleet, monkeypatch):
    (v1,) = fleet(1)
    d._virtual_cfg["demo_auto"] = True
    monkeypatch.setattr(d, "_camera_frame_size", lambda cam: (640, 480))
    assert d.load_response_settings()["handoff"] is False  # off until switched on
    client.post("/api/response/settings", json={"camera_locations": {"hcam": offset(15, 0)}, "min_battery": 20,
                                                "camera_views": {"hcam": {"heading": 0, "fov": 90, "range": 30}},
                                                "handoff": True, "auto_from": "00:00", "auto_to": "00:00", "auto_cooldown_min": 1})
    d.HANDOFF.last_at.clear()
    boxes = ([300, 200, 340, 300], [450, 200, 490, 300], [615, 200, 640, 300])
    for i, b in enumerate(boxes + (boxes[-1],)):
        d.PIPELINE.publish("track", camera="hcam", type="end" if i == 3 else ("new" if i == 0 else "update"), object_id="hx1",
                           label="person", box=b, stationary=False, false_positive=False, t=1000 + i * 1.5)
    assert wait_until(lambda: d.drone_response["active"] and d.drone_response.get("target"), 20)
    assert d.drone_response["by"].startswith("handoff: person left hcam (right)")
    assert d.drone_response["target"]["lon"] > offset(15, 0)["lon"]  # east of the camera, where they went
    d.recall_drone("test over")
    assert wait_until(lambda: not d.drone_response["active"], 90)
    client.post("/api/response/settings", json={"handoff": False, "camera_views": {}})
