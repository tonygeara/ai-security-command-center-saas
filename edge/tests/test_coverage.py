"""Digital twin: camera views on the ground, blind spots, the suggested camera, send a drone to a spot."""
import os
import sys

from conftest import APP, HOME, offset, wait_until

sys.path.insert(0, os.path.abspath(APP))
import coverage  # noqa: E402

C = {"lat": HOME[0], "lon": HOME[1]}


def at(north, east):
    p = offset(north, east)
    return p["lat"], p["lon"]


def test_what_a_camera_sees():
    cams = {"front": {**C, "view": {"heading": 0, "fov": 90, "range": 30}}}
    assert coverage.who_sees(cams, *at(20, 0))[0]["camera"] == "front"   # straight ahead
    assert coverage.who_sees(cams, *at(20, 15)) != []                     # inside 45° to the right
    assert coverage.who_sees(cams, *at(5, 20)) == []                      # outside the slice
    assert coverage.who_sees(cams, *at(40, 0)) == []                      # too far
    assert coverage.who_sees(cams, *at(-10, 0)) == []                     # behind


def test_blind_spots_and_suggestion_inside_the_outline():
    outline = [list(at(-20, -20)), list(at(-20, 20)), list(at(20, 20)), list(at(20, -20))]  # 40 × 40 m
    one = {"front": {**C, "view": {"heading": 0, "fov": 90, "range": 30}}}
    a = coverage.analyse(one, outline)
    assert a["ok"] and 60 < a["blind_pct"] < 85  # one camera facing north sees about a quarter
    s = a["suggestion"]
    assert s and s["blind_pct_after"] < a["blind_pct"] - 15 and len(s["cone"]) > 3
    four = {f"c{h}": {**C, "view": {"heading": h, "fov": 90, "range": 30}} for h in (0, 90, 180, 270)}
    b = coverage.analyse(four, outline)
    assert b["blind_pct"] < 1 and b["suggestion"] is None
    assert coverage.analyse({}, None)["ok"] is False


def test_views_are_cleaned():
    assert coverage.clean_view({"heading": 370, "fov": 500, "range": -4}) == {"heading": 10.0, "fov": 180.0, "range": 3.0}
    assert coverage.clean_view(None) == coverage.DEFAULT_VIEW


def test_exit_point_follows_the_edge_it_left_by():
    view = {"heading": 0, "fov": 90, "range": 30}
    right = coverage.exit_point(C, view, [300, 300, 340, 400], [600, 300, 640, 400], 640, 480)
    assert right["exit"] == "right" and 45 < right["bearing"] < 135  # past the right edge, not behind the camera
    away = coverage.exit_point(C, view, [300, 300, 340, 470], [300, 100, 340, 150], 640, 480)
    assert away["exit"] == "far side" and away["distance_m"] > 25 and abs(away["bearing"]) < 10


def test_coverage_api_and_send_to_spot(d, client, fleet):
    (v1,) = fleet(1)
    d._virtual_cfg["demo_auto"] = True
    client.post("/api/response/settings", json={"camera_locations": {"front": offset(10, 0)}, "min_battery": 20,
                                                "camera_views": {"front": {"heading": 90, "fov": 60, "range": 25}},
                                                "site_outline": [list(at(-15, -15)), list(at(-15, 40)), list(at(30, 40))]})
    cfg = client.get("/api/response/settings").get_json()["settings"]
    assert cfg["camera_views"]["front"] == {"heading": 90.0, "fov": 60.0, "range": 25.0} and len(cfg["site_outline"]) == 3
    a = client.get("/api/coverage").get_json()
    assert a["ok"] and "front" in a["cones"] and a["squares"] > 0
    assert client.get("/api/coverage/at?lat=%f&lon=%f" % at(10, 15)).get_json()["cameras"][0]["camera"] == "front"
    assert client.get("/coverage").status_code == 200
    live = client.get(f"/api/live4d?drone={v1}").get_json()
    assert live["cameras"][0]["name"] == "front" and live["cameras"][0]["view"]["fov"] == 60
    far = offset(5000, 0)
    assert "more than" in client.post("/api/coverage/send", json=far).get_json()["error"]
    spot = offset(20, 30)
    r = client.post("/api/coverage/send", json=spot).get_json()
    assert r["ok"], r
    assert d.drone_response["target"] == spot and d.drone_response["camera"] == "front"
    assert wait_until(lambda: d.drone_response["phase"] == "hovering", 60)
    tel = d.get_link(v1)["telemetry"]
    assert d._distance_m(tel["lat"], tel["lon"], spot["lat"], spot["lon"]) < 8
    d.recall_drone("test over")
    assert wait_until(lambda: not d.drone_response["active"], 90)
    client.post("/api/response/settings", json={"camera_views": {}, "site_outline": []})
