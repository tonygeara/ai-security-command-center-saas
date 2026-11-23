"""Detector drones: detectors on the map with a range, drones seen by position (tested with real virtual drones flying
into range) and by camera through YOLO (tested with a small ONNX model run by OpenCV)."""
import os
import time

import numpy as np
import pytest

from conftest import HOME, offset, wait_until


@pytest.fixture
def det(d):
    for f in (d.DETECTORS_FILE, d.DETECTOR_SETTINGS_FILE, d.DETECTOR_MODEL_FILE):
        if os.path.exists(f):
            os.remove(f)
    with d._detector_lock:
        for k in d._detector:
            d._detector[k].clear() if hasattr(d._detector[k], "clear") else None
    yield d
    for f in (d.DETECTORS_FILE, d.DETECTOR_SETTINGS_FILE, d.DETECTOR_MODEL_FILE):
        if os.path.exists(f):
            os.remove(f)


def sites(client, *dets):
    return client.post("/api/detector/sites", json={"detectors": list(dets)}).get_json()


def test_page_nav_and_checks(det, client):
    html = client.get("/drone-detector").get_data(as_text=True)
    assert "Detector drones" in html and 'href="/drone-detector"' in html
    p = {"name": "Gate", "lat": HOME[0], "lon": HOME[1], "range_m": 300}
    assert sites(client, p)["detectors"][0]["range_m"] == 300
    assert client.post("/api/detector/sites", json={"detectors": [{**p, "range_m": 5}]}).status_code == 400
    assert client.post("/api/detector/sites", json={"detectors": [{**p, "camera": "nope"}]}).status_code == 400
    import users
    assert users.allowed("operator", "POST", "/api/detector/sites")
    assert not users.allowed("viewer", "POST", "/api/detector/sites")
    assert not users.allowed("operator", "POST", "/api/detector/model")  # the model: admins only


def test_new_virtual_drone_flying_into_range_raises_the_alarm(det, client, fleet):
    """The owner's test: 5 virtual drones are theirs; remove #5, add a new 5th and fly it into a detector's range."""
    d = det
    if os.path.exists(d.MY_DRONES_FILE):
        os.remove(d.MY_DRONES_FILE)
    v = fleet(5)
    d.detector_tick()  # before any detector: no list yet, nothing is an intruder
    assert d.dronedetect_mod.load_mine(d.MY_DRONES_FILE) is None and not client.get("/api/detector/alarm").get_json()["alarms"]
    far = offset(120, 0)  # a detector 120 m north seeing 60 m around it: the drones at home are outside
    sites(client, {"name": "North fence", "lat": far["lat"], "lon": far["lon"], "range_m": 60},
          {"name": "Home pad", "lat": HOME[0], "lon": HOME[1], "range_m": 50})
    assert set(v) <= set(d.my_drones())  # the first detector: every drone there is now is ours
    d.detector_tick()
    st = client.get("/api/detector").get_json()
    home_id = next(x["id"] for x in st["detectors"] if x["name"] == "Home pad")
    north_id = next(x["id"] for x in st["detectors"] if x["name"] == "North fence")
    assert len(st["seen"][home_id]) >= 4 and not any(x["intruder"] for x in st["seen"][home_id])  # ours: no alarm
    assert not client.get("/api/detector/alarm").get_json()["alarms"]
    # Remove virtual drone 5 and add a new 5th one: it is not ours.
    assert client.delete(f"/api/virtual-drones/{v[4]}").get_json()["ok"]
    assert v[4] not in d.my_drones()
    p = offset(12, 0)
    new = client.post("/api/virtual-drones", json={"lat": p["lat"], "lon": p["lon"]}).get_json()["drone"]
    assert new == v[4] and new not in d.my_drones()  # same name, still a new, unknown drone
    assert wait_until(lambda: d.get_link(new)["conn"] is not None and d.get_link(new)["telemetry"].get("lat"), 15)
    spoken = []
    real_speak = d.speak
    d.speak = lambda text, key: spoken.append(text)
    try:
        # Fly it into the North fence detector's range.
        r = client.post(f"/api/routes/fly?drone={new}", json={"name": "intrude", "points": [far], "alt": 20, "speed": 8, "pause": 60, "end": "hover"}).get_json()
        assert r["ok"], r
        assert wait_until(lambda: (d.detector_tick() or True) and client.get("/api/detector/alarm").get_json()["alarms"], 60)
    finally:
        d.speak = real_speak
    alarm = client.get("/api/detector/alarm").get_json()
    (a,) = alarm["alarms"]
    assert "North fence" in a["text"] and "unknown drone" in a["text"] and alarm["intruders_now"] == 1
    seen = client.get("/api/detector").get_json()["seen"][north_id]
    assert seen[0]["slot"] == new and seen[0]["intruder"] and seen[0]["distance_m"] <= 60
    assert any("Unknown drone detected at North fence" in t for t in spoken)  # the PC says it out loud
    assert any("🛸" in t and "North fence" in t for t in d.sent)  # and Telegram
    d.detector_tick()
    assert len(client.get("/api/detector/alarm").get_json()["alarms"]) == 1  # one alarm, not one per check
    # Every page carries the alarm screen.
    assert 'id="droneAlarm"' in client.get("/settings").get_data(as_text=True)
    # Acknowledge: the alarm stops everywhere.
    assert client.post("/api/detector/alarm/ack").get_json()["acknowledged"] == 1
    assert not client.get("/api/detector/alarm").get_json()["alarms"]
    # Mark it as ours: it no longer counts as an intruder.
    assert client.post("/api/detector/mine", json={"drone": new, "mine": True}).get_json()["ok"]
    assert not client.get("/api/detector").get_json()["seen"][north_id][0]["intruder"]


def _tiny_yolo(path):
    """A stand-in YOLOv8 model (1 class): whatever the picture, it reports a drone box at (320, 320) 40×30 in the 640
    input (plus a weak box and a duplicate that NMS removes)."""
    import onnx
    from onnx import TensorProto, helper
    boxes = np.zeros((1, 5, 8400), np.float32)
    boxes[0, :, 0] = [320, 320, 40, 30, 0.9]
    boxes[0, :, 1] = [100, 100, 20, 20, 0.2]
    boxes[0, :, 2] = [322, 321, 40, 30, 0.85]
    nodes = [helper.make_node("ReduceMean", ["images"], ["m"], keepdims=1),
             helper.make_node("Reshape", ["m", "shape"], ["m3"]),
             helper.make_node("Mul", ["m3", "zero"], ["z"]),
             helper.make_node("Add", ["z", "boxes"], ["output0"])]
    graph = helper.make_graph(nodes, "tiny", [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])],
                              [helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 5, 8400])],
                              [helper.make_tensor("shape", TensorProto.INT64, [3], [1, 1, 1]),
                               helper.make_tensor("zero", TensorProto.FLOAT, [], [0.0]),
                               helper.make_tensor("boxes", TensorProto.FLOAT, [1, 5, 8400], boxes.flatten().tolist())])
    onnx.save(helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)]), path)


def test_decode_yolo_v5_and_v8(det):
    dd = det.dronedetect_mod
    v8 = np.zeros((1, 5, 8400), np.float32)  # YOLOv8 / YOLO11 (1, 4 + classes, boxes)
    v8[0, :, 7] = [100, 100, 20, 20, 0.8]
    v8[0, :, 9] = [300, 300, 20, 20, 0.1]
    got = dd.decode_yolo(v8, 0.5)
    assert [c for c, _, _ in got] == [0] and got[0][2] == (90.0, 90.0, 20.0, 20.0)
    v5 = np.zeros((1, 25200, 7), np.float32)  # YOLOv5 (1, boxes, 5 + classes)
    v5[0, 3] = [100, 100, 20, 20, 0.9, 0.1, 0.9]
    v5[0, 4] = [300, 300, 20, 20, 0.9, 0.9, 0.1]
    got = sorted(dd.decode_yolo(v5, 0.5))
    assert [c for c, _, _ in got] == [0, 1] and got[0][2] == (290.0, 290.0, 20.0, 20.0)


def test_camera_yolo_detection(det, client, tmp_path, monkeypatch):
    pytest.importorskip("onnx")
    import cv2
    d = det
    model = tmp_path / "drone.onnx"
    _tiny_yolo(str(model))
    with open(model, "rb") as f:
        r = client.post("/api/detector/model", data={"model": (f, "drone.onnx")}, content_type="multipart/form-data")
    assert r.get_json()["ok"], r.get_json()
    assert client.post("/api/detector/model", data={"model": (open(model, "rb"), "x.txt")}, content_type="multipart/form-data").status_code == 400
    frame = cv2.imencode(".jpg", np.full((720, 1280, 3), 200, np.uint8))[1].tobytes()
    found = d.DETECTOR_YOLO.find(frame, ["drone"], 0.45)
    assert len(found) == 1 and found[0]["score"] == 0.9
    assert found[0]["box"] == (600.0, 330.0, 80.0, 60.0)  # 1280×720 picture: halved into 640, 140 px bars top and bottom
    monkeypatch.setattr(d, "_detector_cameras", lambda: ["front"])
    monkeypatch.setattr(d, "_camera_snapshot", lambda cam: frame)
    sites(client, {"name": "Roof", "lat": HOME[0], "lon": HOME[1], "range_m": 400, "camera": "front"})
    d.detector_tick()
    st = client.get("/api/detector").get_json()
    ev = next(e for e in st["events"] if e["kind"] == "camera")
    assert "camera front sees 1 drone" in ev["text"] and ev["photo"] and st["model"]["installed"]
    assert client.get(f"/api/detector/photo/{ev['id']}").data[:2] == b"\xff\xd8"
    d.detector_tick(now=time.time() + 4)
    assert len([e for e in client.get("/api/detector").get_json()["events"] if e["kind"] == "camera"]) == 1  # no repeat within 60 s
    assert client.delete("/api/detector/model").get_json()["ok"] and not os.path.exists(d.DETECTOR_MODEL_FILE)


def test_tab_licences_and_settings_switches(det, client, monkeypatch):
    """Satellite and Detector drones are licence features (off unless switched on for the client) with a Settings switch."""
    d = det
    monkeypatch.setattr(d, "feature_licensed", lambda key: key == "satellite")  # licensed: Satellite only
    html = client.get("/settings").get_data(as_text=True)
    assert '<style>a[href="/drone-detector"]{display:none!important}</style>' in html  # tab hidden
    assert 'a[href="/satellite"]{display' not in html and 'id="droneAlarm"' not in html
    r = client.get("/drone-detector")
    assert r.status_code == 403 and "isn't included in this PC's licence" in r.get_data(as_text=True)
    assert client.get("/api/detector").status_code == 403
    assert client.get("/api/detector/alarm").get_json()["alarms"] == []  # the alarm check stays quiet
    assert d.detector_tick() == {}
    assert client.get("/satellite").status_code == 200
    lic = client.get("/api/customer/settings").get_json()["_licensed"]
    assert lic == {"satellite": True, "drone_detector": False}
    # Licensed, but switched off in Settings on this PC.
    cfg = client.get("/api/customer/settings").get_json()
    try:
        client.post("/api/customer/settings", json={**cfg, "satellite_tab": False})
        assert client.get("/satellite").status_code == 403 and "switched off in Settings" in client.get("/satellite").get_data(as_text=True)
        assert client.get("/api/satellite/pins").status_code == 403
    finally:
        client.post("/api/customer/settings", json={**cfg, "satellite_tab": True})
    assert client.get("/satellite").status_code == 200
