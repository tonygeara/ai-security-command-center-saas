"""Smart patrols: stops over blind spots and incident places, at the riskiest hour; a switch adds and removes it."""
import math
import os
import sys
import time

from conftest import APP, HOME, offset

sys.path.insert(0, os.path.abspath(APP))
import coverage  # noqa: E402
import risk_patrol  # noqa: E402


def at(n, e):
    p = offset(n, e)
    return p["lat"], p["lon"]


CAMS = {"front": {"lat": HOME[0], "lon": HOME[1], "view": {"heading": 0, "fov": 90, "range": 30}},
        "back": {"lat": at(0, 60)[0], "lon": at(0, 60)[1], "view": {"heading": 180, "fov": 90, "range": 30}}}
OUTLINE = [list(at(-40, -40)), list(at(-40, 100)), list(at(40, 100)), list(at(40, -40))]
NOW = time.mktime((2026, 11, 10, 12, 0, 0, 0, 0, -1))


def dist(a, b):
    f = coverage.Frame(*a)
    return math.hypot(*f.xy(*b))


def test_riskiest_hour_weights_severity_and_recency():
    assert risk_patrol.riskiest_hour([], NOW) == 22
    inc = lambda h, sev, days: {"started": NOW - days * 86400 - (12 - h) * 3600, "severity": sev}
    assert risk_patrol.riskiest_hour([inc(2, 3, 1), inc(23, 1, 1), inc(23, 1, 2)], NOW) == 2   # one drone response beats two activities
    assert risk_patrol.riskiest_hour([inc(2, 3, 90), inc(23, 2, 1)], NOW) == 23               # old incidents count less


def test_stops_go_to_blind_spots_near_trouble_spaced_and_safe():
    a = coverage.analyse(CAMS, OUTLINE)
    incidents = [{"camera": "back", "severity": 3, "started": NOW - 3600}] * 3
    zone = lambda lat, lon: coverage.Frame(*HOME).xy(lat, lon)[1] < -30  # a strip in the south is no-fly
    stops, s = risk_patrol.plan(a, CAMS, incidents, HOME, max_distance_m=200, stops=5, spacing=20, zone_at=zone, now=NOW)
    assert s["stops"] == 5 and not s.get("error") and s["time"] in ("11:00", "12:00")
    assert all(dist(HOME, (p[0], p[1])) <= 200 * 0.9 for p in stops)
    assert not any(zone(p[0], p[1]) for p in stops)
    assert all(dist((p[0], p[1]), (q[0], q[1])) >= 20 for i, p in enumerate(stops) for q in stops[i + 1:])
    back = (CAMS["back"]["lat"], CAMS["back"]["lon"])
    assert min(dist(back, (p[0], p[1])) for p in stops) < 45      # trouble at "back": a stop near it
    assert any("near back" in p[2] or "by back" in p[2] for p in stops)
    first = min(stops, key=lambda p: dist(HOME, (p[0], p[1])))
    assert stops[0] == first                                       # the loop starts with the nearest stop


def test_nothing_in_range_says_why():
    a = coverage.analyse(CAMS, OUTLINE)
    stops, s = risk_patrol.plan(a, CAMS, [], HOME, max_distance_m=1, stops=5)
    assert stops == [] and "Nothing to patrol" in s["error"]
    assert risk_patrol.plan({"ok": False, "error": "x"}, CAMS, [], HOME, 500)[1]["error"] == "x"


def test_switch_adds_and_removes_the_patrol(d, client, fleet):
    fleet(1)  # a drone gives the home point
    client.post("/api/response/settings", json={"camera_locations": {"front": offset(0, 0), "back": offset(0, 60)},
                                                "camera_views": {n: c["view"] for n, c in CAMS.items()}, "site_outline": OUTLINE})
    assert client.post("/api/smart-patrol/rebuild").status_code == 409  # off
    r = client.post("/api/smart-patrol", json={"smart_patrol": True, "smart_patrol_stops": 4}).get_json()
    assert r["ok"] and r["settings"]["smart_patrol"] and len(r["info"]["route"]) == 4
    assert len(d.load_routes()[risk_patrol.ROUTE_NAME]["points"]) == 4
    sched = [x for x in d.load_response_settings()["patrol_schedules"] if x["id"] == risk_patrol.SCHEDULE_ID]
    assert sched and sched[0]["days"] == list(range(7)) and sched[0]["auto_start"] is False and sched[0]["time"] == r["info"]["time"]
    assert client.post("/api/smart-patrol/rebuild").get_json()["ok"]
    r = client.post("/api/smart-patrol", json={"smart_patrol": False}).get_json()
    assert r["ok"] and r["info"] == {}
    assert risk_patrol.ROUTE_NAME not in d.load_routes()
    assert not [x for x in d.load_response_settings()["patrol_schedules"] if x["id"] == risk_patrol.SCHEDULE_ID]
    client.post("/api/response/settings", json={"camera_views": {}, "site_outline": []})
