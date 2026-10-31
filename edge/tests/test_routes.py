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
    assert any("is taking off to continue patrol" in t for t in d.sent)


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
