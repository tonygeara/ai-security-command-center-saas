"""No-fly zones and lost-link behaviour, flown with virtual drones."""
import time

from conftest import HOME, offset, square, wait_until


def add_zone(client, centre, half, name="Neighbour"):
    r = client.post("/api/nofly", json=square(centre, half, name)).get_json()
    assert r["ok"], r
    return r["zone"]


def test_route_crossing_a_zone_is_refused(d, client, fleet):
    (v1,) = fleet(1)
    add_zone(client, offset(40, 0), 10)
    route = {"name": "cross", "points": [offset(10, 0), offset(70, 0)], "alt": 15, "speed": 8}
    r = client.post(f"/api/routes/fly?drone={v1}", json=route).get_json()
    assert not r["ok"] and "crosses no-fly zone" in r["error"]
    r = client.post("/api/routes", json=route)
    assert r.status_code == 400 and "crosses no-fly zone" in r.get_json()["error"]
    r = client.post(f"/api/routes/fly?drone={v1}", json={**route, "points": [offset(40, 0)]}).get_json()
    assert not r["ok"] and "inside no-fly zone" in r["error"]


def test_zone_round_home_point_is_refused(d, client, fleet):
    fleet(1)
    r = client.post("/api/nofly", json=square(offset(0, 0), 10))
    assert r.status_code == 400 and "home point" in r.get_json()["error"]


def test_auto_fly_goes_round_a_zone(d, client, fleet):
    (v1,) = fleet(1)
    zone = add_zone(client, offset(30, 0), 8)
    target = offset(60, 0)
    r = client.post(f"/api/routes/fly?drone={v1}", json={"name": "round", "points": [target], "alt": 12, "speed": 8, "end": "hover"}).get_json()
    assert r["ok"], r
    v, entered = d.virtual_drones[v1], []
    end = time.time() + 90
    while time.time() < end and d.run_of(v1):
        if d.nofly.zone_at([zone], v.lat, v.lon):
            entered.append((v.lat, v.lon))
        time.sleep(0.2)
    assert not entered, "the drone flew into the no-fly zone"
    assert d._distance_m(v.lat, v.lon, target["lat"], target["lon"]) < 10
    assert "Route round complete" in d.route_runs[next(iter(d.route_runs))]["message"]


def test_manual_goto_across_a_zone_is_refused(d, client, fleet):
    (v1,) = fleet(1)
    add_zone(client, offset(30, 0), 8)
    t = offset(60, 0)
    r = client.post(f"/api/drone/command?drone={v1}", json={"cmd": "goto", "args": {"lat": t["lat"], "lon": t["lon"]}})
    assert r.status_code == 400 and "no-fly zone" in r.get_json()["error"]


def _start_and_drop(d, client, v1, **opts):
    route = {"name": "patrol", "points": [offset(25, 0), offset(25, 25)], "alt": 12, "speed": 6, "loop": True, **opts}
    assert client.post(f"/api/routes/fly?drone={v1}", json=route).get_json()["ok"]
    v = d.virtual_drones[v1]
    assert wait_until(lambda: v.flying and v.alt > 8 and v.mission, 30)
    client.post(f"/api/virtual-drones/{v1}", json={"action": "drop_link"})
    assert wait_until(lambda: getattr(v, "last_lost_link", None), 10)
    return v


def test_lost_link_returns_home_by_default(d, client, fleet):
    (v1,) = fleet(1)
    v = _start_and_drop(d, client, v1)
    assert v.last_lost_link == "home"
    assert wait_until(lambda: v.mode in ("GO_HOME", "AUTO_LANDING") or not v.flying, 5)


def test_lost_link_land_option(d, client, fleet):
    (v1,) = fleet(1)
    v = _start_and_drop(d, client, v1, lost_link="land")
    assert v.last_lost_link == "land" and v.mode == "AUTO_LANDING"


def test_lost_link_off_hovers_and_hands_back(d, client, fleet):
    (v1,) = fleet(1)
    v = _start_and_drop(d, client, v1, lost_link_on=False)
    assert v.last_lost_link == "hover"
    assert v.mode == "GPS_NORMAL" and not v.control_pc and v.mission is None and v.flying


def test_route_settings_saved(d, client):
    r = client.post("/api/routes", json={"name": "keep", "points": [offset(10, 0)], "lost_link": "land", "ignore_battery": True}).get_json()
    assert r["route"]["lost_link"] == "land" and r["route"]["lost_link_on"] is True and r["route"]["loop"] is True
    r = client.post("/api/routes", json={"name": "off", "points": [offset(10, 0)], "lost_link_on": False}).get_json()
    assert r["route"]["lost_link_on"] is False


def test_remove_drones(d, client, fleet):
    v1, v2 = fleet(2)
    assert client.get("/drone-control").get_data(as_text=True).count("const IS_ADMIN=true") == 1  # sign-in off
    assert client.post(f"/api/routes/fly?drone={v1}", json={"points": [offset(10, 0)], "alt": 15, "speed": 8, "pause": 0, "loop": True}).get_json()["ok"]
    r = client.post("/api/drone/remove", json={"drone": v1})
    assert r.status_code == 409 and ("mission" in r.get_json()["error"] or "flying" in r.get_json()["error"])
    r = client.post("/api/drone/remove", json={"drone": v2}).get_json()
    assert r["ok"] and r["removed"] and v2 not in d.virtual_drones
    old = d.drone_link_token(slot="drone")
    r = client.post("/api/drone/remove", json={"drone": "drone"}).get_json()
    assert r["ok"] and not r["removed"] and d.drone_link_token(slot="drone") != old  # the first drone is unpaired
    assert client.post("/api/drone/remove", json={"drone": "nope"}).status_code == 404
    import users
    assert not users.allowed("operator", "POST", "/api/drone/remove") and users.allowed("operator", "POST", "/api/drone/command")
