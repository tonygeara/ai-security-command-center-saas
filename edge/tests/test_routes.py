"""Routes: each drone its own route, backups, handovers, repeating patrols, ignoring the battery."""
import time

from conftest import offset, wait_until

A = {"name": "A", "points": [offset(20, 0), offset(20, 20)], "alt": 12, "speed": 8, "pause": 0, "loop": True}
B = {"name": "B", "points": [offset(-20, 0)], "alt": 14, "speed": 8, "pause": 0, "loop": True}


def fly(client, slot, body):
    return client.post(f"/api/routes/fly?drone={slot}", json=body).get_json()


def test_two_routes_at_once_and_backup_rules(d, client, fleet):
    v1, v2, v3 = fleet(3)
    assert fly(client, v1, {**A, "backup": v2})["ok"]
    assert fly(client, v3, B)["ok"]
    assert "backup drone for Virtual 1" in fly(client, v2, B)["error"]
    assert "already busy with route B" in fly(client, v2, {**B, "backup": v3})["error"]
    bf = client.get(f"/api/routes?drone={v2}").get_json()["backup_for"]
    assert bf["name"] == "A" and len(bf["route"]["points"]) == 2  # the backup's page shows the route it covers
    missions = {x["drone"]: x["mission"] for x in client.get("/api/drone/links").get_json()["drones"]}
    assert missions[v1] == "route" and missions[v2] == "backup" and missions[v3] == "route"
    assert client.post(f"/api/routes/stop?drone={v3}").get_json()["ok"]
    assert wait_until(lambda: d.run_of(v3) is None, 10) and d.run_of(v1) is not None


def test_low_battery_hands_over_to_the_backup(d, client, fleet):
    v1, v2 = fleet(2)
    assert fly(client, v1, {**A, "backup": v2})["ok"]
    assert wait_until(lambda: d.virtual_drones[v1].flying and d.virtual_drones[v1].alt > 8, 30)
    client.post(f"/api/virtual-drones/{v1}", json={"action": "low_battery"})
    assert wait_until(lambda: d.run_of(v2) is not None, 30)
    r = d.run_of(v2)
    assert r["name"] == "A" and r["backup"] == v1  # the tired drone becomes the backup
    assert wait_until(lambda: d.virtual_drones[v1].mode in ("GO_HOME", "AUTO_LANDING"), 10)
    # The patrol switches drone just before the Telegram message goes out: wait for it rather than race it.
    assert wait_until(lambda: any("is taking off to continue patrol" in t for t in d.sent), 10)


def test_ignore_battery_keeps_patrolling(d, client, fleet):
    v1, v2 = fleet(2)
    r = fly(client, v1, {**A, "loop": False, "ignore_battery": True, "backup": v2, "relay": True})
    assert r["ok"]
    assert d.backup_run_of(v2) is None  # nothing is swapped, so no drone is held back
    assert wait_until(lambda: d.virtual_drones[v1].flying and d.virtual_drones[v1].alt > 8, 30)
    client.post(f"/api/virtual-drones/{v1}", json={"action": "low_battery"})  # 20 %
    time.sleep(6)
    assert d.run_of(v1) is not None and d.run_of(v2) is None


def test_repeat_route_laps(d, client, fleet):
    (v1,) = fleet(1)
    assert fly(client, v1, {**A, "points": [offset(10, 0), offset(10, 10)]})["ok"]
    assert wait_until(lambda: (d.run_of(v1) or {}).get("lap", 1) >= 2, 90)


def patrol(client, on):
    return client.post("/api/routes/patrol", json={"on": on}).get_json()


def test_run_patrol_flies_each_drones_last_route(d, client, fleet):
    d._save_patrol_mode({"on": False, "last": {}})
    v1, v2, v3 = fleet(3)
    # v1's last route is the one it flew, v2's the one saved on its page; v3 has none and stays on the ground.
    assert fly(client, v1, {**A, "loop": False})["ok"]
    assert client.post(f"/api/routes/stop?drone={v1}").get_json()["ok"]
    assert wait_until(lambda: d.run_of(v1) is None, 10)
    assert client.post(f"/api/routes?drone={v2}", json={**B, "loop": False}).get_json()["ok"]
    try:
        s = patrol(client, True)
        assert s["on"]
        assert wait_until(lambda: d.run_of(v1) and d.run_of(v2), 15)
        assert d.run_of(v1)["name"] == "A" and d.run_of(v2)["name"] == "B"
        assert d.run_of(v1)["route"]["loop"] and d.run_of(v1)["by"] == d.PATROL_MODE_BY  # on repeat
        assert d.run_of(v3) is None
        st = {x["drone"]: x for x in client.get("/api/routes/patrol").get_json()["drones"]}
        assert st[v1]["patrolling"] and st[v2]["patrolling"] and "no route set yet" in st[v3]["status"]
        assert not d.last_route_of(v1)["route"]["loop"]  # the patrol's repeat doesn't change the drone's own route
        # Stop route on one drone: it is left alone, the others carry on.
        assert client.post(f"/api/routes/stop?drone={v2}").get_json()["ok"]
        assert wait_until(lambda: d.run_of(v2) is None, 10)
        d._patrol_mode["ended"].clear()
        d.patrol_mode_tick()
        assert d.run_of(v2) is None and d.run_of(v1) is not None
        off_run = d.run_of(v1)["id"]
        # Off: every patrol stops and its drone flies home.
        assert wait_until(lambda: d.virtual_drones[v1].flying, 30)
        off = patrol(client, False)
        assert not off["on"] and "Virtual 1" in off["stopped"]
        assert wait_until(lambda: d.run_of(v1) is None, 10)
        assert wait_until(lambda: d.virtual_drones[v1].mode in ("GO_HOME", "AUTO_LANDING") or not d.virtual_drones[v1].flying, 10)
        assert "returning home" in d.route_runs[off_run]["message"]
        d.patrol_mode_tick()
        assert d.run_of(v1) is None
    finally:
        d._save_patrol_mode({"on": False, "last": {}})


def test_run_patrol_needs_an_operator(d):
    import users
    assert users.allowed("operator", "POST", "/api/routes/patrol")
    assert not users.allowed("viewer", "POST", "/api/routes/patrol")
