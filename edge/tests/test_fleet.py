"""The Fleet tab: every drone with what it is doing and where it is going, its patrol route, Stop all and Return all
home (tested with real virtual drones flying)."""
from conftest import offset, wait_until


def test_fleet_shows_each_drone_its_job_target_and_patrol_route(d, client, fleet):
    v1, v2 = fleet(2)
    a, b = offset(80, 0), offset(80, 80)
    r = client.post(f"/api/routes/fly?drone={v1}", json={"name": "Perimeter", "points": [a, b], "alt": 30, "speed": 8,
                                                          "pause": 0, "loop": True, "end": "home"}).get_json()
    assert r["ok"], r
    assert wait_until(lambda: d.get_link(v1)["telemetry"].get("flying"), 20)
    f = client.get("/api/fleet").get_json()
    x = next(y for y in f["drones"] if y["slot"] == v1)
    assert x["job"] == "patrol" and x["route"]["name"] == "Perimeter" and x["route"]["total"] == 2
    i = x["route"]["index"]  # the stop it is flying to (0-based here)
    assert x["job_text"] == f"Route “Perimeter” · stop {i + 1} of 2" and x["target"]["label"] == f"stop {i + 1}"
    assert x["target"]["distance_m"] >= 0
    assert x["patrol_route"]["name"] == "Perimeter" and x["patrol_route"]["loop"]
    y = next(z for z in f["drones"] if z["slot"] == v2)
    assert y["job"] == "ready" and y["target"] is None and y["virtual"]
    assert next(z for z in f["drones"] if z["slot"] == "drone")["job"] == "offline"
    # A patrol route drawn on the Fleet page is saved as that drone's own route (what Run patrol flies).
    r = client.post(f"/api/routes?drone={v2}", json={"name": "Virtual 2 patrol", "points": [a, b, offset(0, 80)], "alt": 35,
                                                       "speed": 5, "loop": True, "end": "home"}).get_json()
    assert r["ok"]
    y = next(z for z in client.get("/api/fleet").get_json()["drones"] if z["slot"] == v2)
    assert y["patrol_route"]["name"] == "Virtual 2 patrol" and len(y["patrol_route"]["points"]) == 3
    # Return all home: patrols end and every flying drone comes home.
    r = client.post("/api/fleet/home-all").get_json()
    assert r["ok"] and r["returning"] == 1
    assert wait_until(lambda: not d.run_of(v1), 20)
    assert wait_until(lambda: not d.get_link(v1)["telemetry"].get("flying"), 90)


def test_stop_all_hovers_every_flying_drone(d, client, fleet):
    (v1,) = fleet(1)
    assert client.post(f"/api/routes/fly?drone={v1}", json={"name": "Out", "points": [offset(150, 0)], "alt": 30, "speed": 8,
                                                             "pause": 0, "end": "hover"}).get_json()["ok"]
    assert wait_until(lambda: d.get_link(v1)["telemetry"].get("flying"), 20)
    r = client.post("/api/fleet/stop-all").get_json()
    assert r["ok"] and r["stopped"] == 1 and "hovering" in r["message"]
    assert wait_until(lambda: not d.run_of(v1), 20)
    assert client.post("/api/fleet/stop-all").get_json()["stopped"] in (0, 1)
    client.post(f"/api/drone/command?drone={v1}", json={"cmd": "land"})
    assert wait_until(lambda: not d.get_link(v1)["telemetry"].get("flying"), 90)


def test_fleet_page_dashboard_card_and_permissions(client):
    html = client.get("/fleet").get_data(as_text=True)
    assert 'href="/fleet"' in html and "function editRoute" in html and "function dropDrone" in html and "homeAll()" in html
    for b in ("Take off", "Hover", "Home", "Land", "Send to", "Patrol route", "Fly patrol", "Stop route"):
        assert b in html
    import users
    assert users.allowed("operator", "POST", "/api/fleet/stop-all") and users.allowed("operator", "POST", "/api/fleet/home-all")
    assert not users.allowed("viewer", "POST", "/api/fleet/home-all") and users.allowed("viewer", "GET", "/api/fleet")
    import pages.fleet
    assert 'id="fleetCard"' in pages.fleet.CARD and "RETURN ALL HOME" in pages.fleet.CARD


def test_route_stop_is_counted_like_the_route_run(d, monkeypatch):
    """The route run counts stops from 1 (index 1 = flying to the first stop): the Fleet shows the same stop."""
    pts = [offset(10, 0), offset(20, 0), offset(30, 0)]
    for idx, want in ((1, 1), (2, 2), (3, 3)):
        fake = {"name": "R", "index": idx, "route": {"points": pts, "loop": False}}
        monkeypatch.setattr(d, "run_of", lambda s, f=fake: f if s == "drone" else None)
        x = d._fleet_drone("drone", {}, [])
        assert x["job"] == "patrol" and x["job_text"] == f"Route “R” · stop {want} of 3" and x["route"]["index"] == want - 1
        assert (x["target"]["lat"], x["target"]["lon"]) == (pts[want - 1]["lat"], pts[want - 1]["lon"])
