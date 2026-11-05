"""Drone 3D site maps: grid planning, the mapping flight, and processing through a stand-in mapping engine."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile

import cv2
import numpy as np
import pytest
from flask import Flask, jsonify, request, send_file
from werkzeug.serving import make_server

from conftest import APP, offset, wait_until

sys.path.insert(0, APP)
import mapping  # noqa: E402

AREA = [offset(0, 0), offset(0, 120), offset(80, 120), offset(80, 0)]  # 120 m east-west × 80 m north-south
SMALL = [offset(30, 0), offset(30, 24), offset(42, 24), offset(42, 0)]  # 24 × 12 m: a quick flight for the simulator


def _jpeg(w=64, h=48):
    return cv2.imencode(".jpg", np.full((h, w, 3), 120, np.uint8))[1].tobytes()


# ----- planning -----

def test_grid_runs_along_the_longest_side_and_covers_the_area():
    p = mapping.plan_grid(AREA, alt=40, overlap=0.75, sidelap=0.7)
    width, height = mapping.footprint_m(40)
    assert p["lines"] == 5 and len(p["points"]) == 10  # 80 m across at 16.5 m spacing
    assert p["spacing_m"] == pytest.approx(width * 0.3, abs=0.1) and p["every_m"] == pytest.approx(height * 0.25, abs=0.1)
    for a, b in zip(p["points"][::2], p["points"][1::2]):
        assert a["lat"] == pytest.approx(b["lat"], abs=1e-6)  # each line runs east-west, along the 120 m side
    ref = (AREA[0]["lat"], AREA[0]["lon"])
    xs = [mapping._xy(q["lat"], q["lon"], ref) for q in p["points"]]
    assert min(x for x, _ in xs) < 0 and max(x for x, _ in xs) > 120  # lines start and end outside the area
    assert 0 < min(y for _, y in xs) and max(y for _, y in xs) < 80
    assert p["images"] > 60 and 2 < p["minutes"] < 10 and p["area_m2"] == pytest.approx(9600, rel=0.02)


def test_planning_limits():
    with pytest.raises(ValueError, match="at least 3 corners"):
        mapping.plan_grid(AREA[:2])
    with pytest.raises(ValueError, match="too small"):
        mapping.plan_grid([offset(0, 0), offset(0, 5), offset(5, 5)])
    big = [offset(0, 0), offset(0, 3000), offset(3000, 3000), offset(3000, 0)]
    with pytest.raises(ValueError, match="flight lines"):
        mapping.plan_grid(big, alt=20)
    assert mapping.plan_grid(AREA, photos=True)["speed"] <= mapping.plan_grid(AREA)["every_m"] / 2  # time for each photo


def test_frames_are_positioned_and_photos_checked(tmp_path):
    s = mapping.create(str(tmp_path), "Yard", AREA)
    for k in range(3):
        mapping.add_frame(str(tmp_path), s["id"], _jpeg(), 45.5 + k * 1e-4, -75.6, 40.0)
    with open(tmp_path / s["id"] / "geo.txt", encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[0] == "EPSG:4326" and lines[1] == "frame_00001.jpg -75.60000000 45.50000000 40.00"
    with pytest.raises(ValueError, match="not a JPEG"):
        mapping.add_photo(str(tmp_path), s["id"], "notes.txt", b"hello")
    mapping.add_photo(str(tmp_path), s["id"], "../../DJI_0001.JPG", _jpeg())
    files, geo = mapping.image_files(str(tmp_path), s["id"])
    assert len(files) == 4 and geo.endswith("geo.txt") and os.path.basename(files[-1]) == "photo_00001_DJI_0001.jpg"
    assert mapping.load(str(tmp_path), s["id"])["frames"] == 3
    with pytest.raises(KeyError):
        mapping.load(str(tmp_path), "../" + s["id"])


def _results_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("odm_texturing/odm_textured_model_geo.obj", "mtllib odm_textured_model_geo.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 1\nf 1 2 3\n")
        z.writestr("odm_texturing/odm_textured_model_geo.mtl", "newmtl m\nmap_Kd tex.png\n")
        z.writestr("odm_texturing/tex.png", _jpeg())
        z.writestr("odm_texturing/odm_textured_model_geo_labeling.vec", "x")
        z.writestr("orthophoto_tiles/18/1000/2000.png", b"\x89PNG")
        z.writestr("orthophoto_tiles/20/4000/8000.png", b"\x89PNG")
        z.writestr("odm_report/report.pdf", b"%PDF-1.4")
        z.writestr("odm_orthophoto/odm_orthophoto.tif", b"big")
        z.writestr("../evil.obj", "x")
    return buf.getvalue()


def test_results_keep_the_model_tiles_and_report(tmp_path):
    (tmp_path / "all.zip").write_bytes(_results_zip())
    found = mapping.extract_results(str(tmp_path / "all.zip"), str(tmp_path / "result"))
    assert found == {"model": "odm_textured_model_geo.obj", "tiles": True, "min_zoom": 18, "max_zoom": 20, "report": True}
    assert sorted(os.listdir(tmp_path / "result" / "model")) == ["odm_textured_model_geo.mtl", "odm_textured_model_geo.obj", "tex.png"]
    assert (tmp_path / "result" / "tiles" / "20" / "4000" / "8000.png").exists()
    assert not (tmp_path / "evil.obj").exists() and not (tmp_path / "result" / "odm_orthophoto.tif").exists()


# ----- a stand-in for NodeODM -----

class FakeEngine:
    def __init__(self):
        self.app, self.tasks, self.calls = Flask("fake-nodeodm"), {}, []
        self.mode = "complete"  # complete | fail | hang
        a = self.app

        @a.get("/info")
        def info():
            return jsonify({"version": "2.2.1", "engineVersion": "3.6.2", "taskQueueCount": 0})

        @a.post("/task/new/init")
        def init():
            tid = f"t{len(self.tasks) + 1}"
            self.tasks[tid] = {"name": request.form["name"], "options": json.loads(request.form["options"]), "files": [], "polls": 0}
            return jsonify({"uuid": tid})

        @a.post("/task/new/upload/<tid>")
        def upload(tid):
            self.tasks[tid]["files"] += [f.filename for f in request.files.getlist("images")]
            return jsonify({"success": True})

        @a.post("/task/new/commit/<tid>")
        def commit(tid):
            return jsonify({"uuid": tid})

        @a.get("/task/<tid>/info")
        def task_info(tid):
            t = self.tasks[tid]
            t["polls"] += 1
            code = 20 if self.mode == "hang" or t["polls"] < 3 else {"complete": 40, "fail": 30}[self.mode]
            return jsonify({"uuid": tid, "status": {"code": code, **({"errorMessage": "Not enough overlap"} if code == 30 else {})},
                            "progress": 50 if code == 20 else 100, "processingTime": 61000, "imagesCount": len(t["files"])})

        @a.get("/task/<tid>/download/all.zip")
        def download(tid):
            return send_file(io.BytesIO(_results_zip()), mimetype="application/zip")

        @a.post("/task/<action>")
        def action(action):
            self.calls.append((action, request.form.get("uuid")))
            return jsonify({"success": True})


@pytest.fixture(scope="module")
def engine(d):
    fake = FakeEngine()
    srv = make_server("127.0.0.1", 0, fake.app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d.save_local_settings({"mapping_engine_url": f"http://127.0.0.1:{srv.server_port}"})
    d.MAP_POLL_S = 0.05
    threading.Thread(target=d._map_worker, daemon=True).start()
    yield fake
    srv.shutdown()
    d.save_local_settings({"mapping_engine_url": ""})


def _new_map(client, name="Site", area=AREA, **kw):
    r = client.post("/api/maps", json={"name": name, "area": area, "alt": 40, **kw}).get_json()
    assert r["ok"], r
    return r["map"]["id"]


def _status(client, sid):
    return client.get(f"/api/maps/{sid}").get_json()["map"]


def test_process_builds_the_3d_map(d, client, engine):
    sid = _new_map(client, quality="fast")
    assert client.post(f"/api/maps/{sid}/process").get_json()["error"].startswith("A 3D map needs at least 5 images")
    for k in range(6):
        mapping.add_frame(d.MAPS_DIR, sid, _jpeg(), 45.5048 + k * 1e-4, -75.6636, 40)
    r = client.post(f"/api/maps/{sid}/photos", data={"photos": [(io.BytesIO(_jpeg()), "DJI_0001.JPG"), (io.BytesIO(b"no"), "x.txt")]})
    assert r.get_json()["added"] == 1 and "not a JPEG" in r.get_json()["errors"][0]
    assert client.post(f"/api/maps/{sid}/process").get_json()["ok"]
    assert wait_until(lambda: _status(client, sid)["status"] == "ready", 20), _status(client, sid)
    task = engine.tasks[max(engine.tasks)]
    assert sorted(task["files"])[:2] == ["frame_00001.jpg", "frame_00002.jpg"] and "geo.txt" in task["files"] and len(task["files"]) == 8
    names = {o["name"]: o["value"] for o in task["options"]}
    assert names["tiles"] is True and names["pc-quality"] == "low"
    assert ("remove", max(engine.tasks)) in engine.calls  # the engine's copy is cleaned up once downloaded
    m = _status(client, sid)
    assert m["result"]["model"] == "odm_textured_model_geo.obj" and m["result"]["max_zoom"] == 20
    page = client.get(f"/maps/{sid}/3d").get_data(as_text=True)
    assert "odm_textured_model_geo.obj" in page and "Site" in page
    assert client.get(f"/maps/{sid}/model/odm_textured_model_geo.obj").status_code == 200
    assert client.get(f"/maps/{sid}/tiles/20/4000/8000.png").status_code == 200
    assert client.get(f"/maps/{sid}/tiles/20/4000/8001.png").status_code == 404
    assert client.get(f"/maps/{sid}/report.pdf").status_code == 200
    assert client.get("/maps/../../etc/model/passwd").status_code == 404
    assert any("is ready" in t for t in d.sent)
    if shutil.which("node"):  # the viewer's module script parses
        js = re.search(r'<script type="module">(.*?)</script>', page, re.S).group(1)
        f = os.path.join(d.MAPS_DIR, "viewer_check.mjs")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run([shutil.which("node"), "--check", f], capture_output=True, text=True)
        os.remove(f)
        assert out.returncode == 0, out.stderr
    assert client.delete(f"/api/maps/{sid}").get_json()["ok"] and not os.path.exists(os.path.join(d.MAPS_DIR, sid))


def test_engine_failure_and_cancel(d, client, engine):
    sid = _new_map(client, "Bad")
    for k in range(5):
        mapping.add_frame(d.MAPS_DIR, sid, _jpeg(), 45.5048 + k * 1e-4, -75.6636, 40)
    engine.mode = "fail"
    client.post(f"/api/maps/{sid}/process")
    assert wait_until(lambda: _status(client, sid)["status"] == "failed", 20)
    assert "Not enough overlap" in _status(client, sid)["message"]
    engine.mode = "hang"
    client.post(f"/api/maps/{sid}/process")
    assert wait_until(lambda: _status(client, sid)["status"] == "processing", 20)
    tid = max(engine.tasks)
    assert client.post(f"/api/maps/{sid}/cancel").get_json()["ok"]
    assert wait_until(lambda: ("cancel", tid) in engine.calls, 10)
    assert _status(client, sid)["status"] == "canceled"
    engine.mode = "complete"
    client.delete(f"/api/maps/{sid}")


def test_mapping_page_and_bad_requests(d, client):
    assert client.post("/api/maps", json={"area": AREA, "alt": 5}).status_code == 400
    assert client.post("/api/maps/plan", json={"area": AREA[:2]}).get_json()["error"].startswith("Draw the area")
    r = client.post("/api/maps/plan", json={"area": AREA, "alt": 40}).get_json()
    assert r["ok"] and r["plan"]["lines"] == 5
    assert client.post("/api/maps/engine", json={"url": "file:///etc"}).status_code == 400
    assert client.get("/api/maps/abcdefabcdef").status_code == 404
    assert "3D Site Maps" in client.get("/maps").get_data(as_text=True)


# ----- the mapping flight, with a simulated drone -----

class FakeVideo:
    def __init__(self, slot):
        self.closed = False

    def jpeg(self):
        return _jpeg()

    def close(self):
        self.closed = True


def test_survey_flight_captures_positioned_images(d, client, fleet, monkeypatch):
    (v1,) = fleet(1)
    monkeypatch.setattr(d, "_map_frame_source", FakeVideo)
    r = client.post("/api/maps", json={"name": "Quick", "area": SMALL, "alt": 15, "speed": 8}).get_json()
    sid = r["map"]["id"]
    assert r["map"]["plan"]["lines"] == 2
    fly = client.post(f"/api/maps/{sid}/fly", json={"drone": v1}).get_json()
    assert fly["ok"], fly
    assert client.post(f"/api/maps/{sid}/fly", json={"drone": v1}).get_json()["ok"] is False  # already flying it
    assert wait_until(lambda: d.virtual_drones[v1].gimbal == -90, 10)  # camera straight down
    assert wait_until(lambda: _status(client, sid)["frames"] > 0, 90)
    assert _status(client, sid)["status"] == "flying"
    assert client.delete(f"/api/maps/{sid}").status_code == 409  # not while the drone flies it
    assert wait_until(lambda: d._survey_run(sid) is None, 120)
    m = _status(client, sid)
    assert m["frames"] >= 3 and m["status"] in ("captured", "planned") and len(m["flights"]) == 1
    with open(os.path.join(d.MAPS_DIR, sid, "geo.txt"), encoding="utf-8") as f:
        rows = f.read().splitlines()[1:]
    lats = [float(x.split()[2]) for x in rows]
    assert len(rows) == m["frames"] and all(SMALL[0]["lat"] - 1e-4 < lat < SMALL[2]["lat"] + 1e-4 for lat in lats)
    assert all(float(x.split()[3]) > 10 for x in rows)  # taken at the survey height, not while climbing
    assert wait_until(lambda: any("Mapping flight" in t and "map images captured" in t for t in d.sent), 10)
    client.delete(f"/api/maps/{sid}")


def test_operator_may_fly_maps_but_not_delete_them():
    import users
    assert users.allowed("operator", "POST", "/api/maps/abcdefabcdef/fly")
    assert users.allowed("operator", "POST", "/api/maps/abcdefabcdef/photos")
    assert not users.allowed("operator", "DELETE", "/api/maps/abcdefabcdef")
    assert not users.allowed("viewer", "POST", "/api/maps")
