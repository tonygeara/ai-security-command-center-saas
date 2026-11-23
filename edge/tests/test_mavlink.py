"""PX4 / ArduPilot drones over MAVLink (mavlink_bridge.py), with a fake MAVLink aircraft standing in for the drone:
added from the Add a drone page, found by "Others", flown like any other drone, sent home, removed."""
import json
import os
import socket

import pytest

from conftest import HOME, offset, wait_until

pytest.importorskip("pymavlink")
from fake_mavlink import FakeAircraft  # noqa: E402


def _udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def licensed(d, monkeypatch):
    """The licence allows drones (test_licence_limit_applies checks a full licence)."""
    monkeypatch.setattr(d, "api_cloud_can_add_source", lambda kind: d.jsonify({"ok": True, "allowed": True, "used": 0, "limit": None}))


def cmd(client, slot, name, args=None):
    return client.post(f"/api/drone/command?drone={slot}", json={"cmd": name, "args": args or {}}).get_json()


@pytest.fixture
def mav(d, client):
    planes, slots = [], []

    def make(autopilot=3, name="Test quad"):
        port = _udp_port()
        r = client.post("/api/mavlink", json={"name": name, "connection": f"udpin:0.0.0.0:{port}"}).get_json()
        assert r["ok"], r
        plane = FakeAircraft(port, HOME, autopilot=autopilot).start()
        planes.append(plane)
        slots.append(r["drone"])
        slot = r["drone"]
        assert wait_until(lambda: d.get_link(slot)["conn"] is not None and d.get_link(slot)["telemetry"].get("lat"), 20)
        return slot, plane

    yield make
    for p in planes:
        p.stop = True
    for s in slots:
        m = d.mavlink_drones.get(s)
        if m is not None:
            m.armed = False  # the fake aircraft is gone: let it be removed
            m.tel["landed_state"] = 1
            client.delete(f"/api/mavlink/{s}")


def test_page_lists_drone_kinds_with_others_last(client):
    html = client.get("/drone-add").get_data(as_text=True)
    for kind in ("PX4", "ArduPilot", "Azur Drones", "Asylon", "Nightingale Security", "Percepto", "Sunflower Labs",
                 "Autel Robotics", "FlytBase", "ROS 2", "Others (find it automatically)"):
        assert kind in html
    kinds = html.split("const KINDS=[", 1)[1].split("];", 1)[0]
    assert kinds.rstrip().rstrip(",").splitlines()[-1].lstrip().startswith("{k:'others'")
    assert "location.href='/drone-add'" in client.get("/drone-control").get_data(as_text=True)


def test_connection_is_checked(client):
    for bad in ("", "serial:COM3", "udpin:0.0.0.0:99999", "http://x:1", "udpin:0.0.0.0:14550; rm"):
        r = client.post("/api/mavlink", json={"connection": bad}).get_json()
        assert r["ok"] is False and "Connection" in r["error"]


def test_others_scan_finds_and_names_the_drone(d, client):
    port = _udp_port()
    plane = FakeAircraft(port, HOME, autopilot=12).start()  # PX4
    try:
        r = client.post("/api/mavlink/scan", json={"ports": [port], "seconds": 3}).get_json()
    finally:
        plane.stop = True
    assert r["ok"] and len(r["found"]) == 1, r
    f = r["found"][0]
    assert f["model"] == "PX4 quadcopter" and f["connection"] == f"udpin:0.0.0.0:{port}" and f["port"] == port


def test_ardupilot_drone_flies_to_a_point_and_comes_home(d, client, mav):
    slot, plane = mav(autopilot=3, name="North quad")
    assert d.drone_label(slot) == "North quad"
    assert slot in d.drone_slots()
    summary = client.get("/api/mavlink").get_json()["drones"][0]
    assert summary["model"] == "ArduPilot quadcopter" and summary["aircraft_connected"]
    saved = json.load(open(d.MAVLINK_FILE, encoding="utf-8"))
    assert saved == [{"slot": slot, "name": "North quad", "connection": summary["connection"]}]

    spot = offset(60, 40)
    r = cmd(client, slot, "goto", {"lat": spot["lat"], "lon": spot["lon"], "alt": 20})
    assert r.get("ok") is not False, r
    assert wait_until(lambda: plane.armed and plane.alt > 5, 20)
    assert wait_until(lambda: abs(plane.lat - spot["lat"]) < 4e-5 and abs(plane.lon - spot["lon"]) < 6e-5, 40)
    t = d.get_link(slot)["telemetry"]
    assert t["flying"] and t["battery"] == 87

    assert cmd(client, slot, "go_home").get("ok") is not False
    assert wait_until(lambda: d.get_link(slot)["telemetry"].get("flight_mode") in ("GO_HOME", "AUTO_LANDING"), 10)
    assert wait_until(lambda: not plane.armed, 60)
    assert abs(plane.lat - HOME[0]) < 3e-5


def test_px4_drone_takes_off_and_lands(d, client, mav):
    slot, plane = mav(autopilot=12, name="")
    assert d.drone_label(slot).startswith("MAVLink ")
    assert cmd(client, slot, "takeoff").get("ok") is not False
    assert wait_until(lambda: plane.armed and plane.alt > 3, 20)
    assert 22 in plane.commands
    r = cmd(client, slot, "control_on")
    assert r.get("ok") is False and "PX4" in (r.get("error") or "")
    assert cmd(client, slot, "land").get("ok") is not False
    assert wait_until(lambda: not plane.armed, 30)


def test_remove_mavlink_drone(d, client, mav):
    slot, plane = mav()
    assert client.delete(f"/api/mavlink/{slot}").get_json()["ok"]
    assert slot not in d.mavlink_drones and slot not in d.drone_slots()
    assert json.load(open(d.MAVLINK_FILE, encoding="utf-8")) == []
    assert not os.path.exists(d._token_file(slot))
    assert client.delete(f"/api/mavlink/{slot}").status_code == 404


def test_integration_request_for_on_request_drones(d, client, monkeypatch):
    assert client.post("/api/drone/integration-request", json={"kind": "nope", "email": "a@b.co"}).status_code == 400
    assert client.post("/api/drone/integration-request", json={"kind": "percepto", "email": "x"}).status_code == 400
    r = client.post("/api/drone/integration-request", json={"kind": "percepto", "email": "ops@site.co"}).get_json()
    assert r["ok"] and r["sent"] is False  # on-prem in the tests: noted, not sent
    monkeypatch.setattr(d, "onprem_mode", lambda: False)
    sent = []

    class Ok:
        ok = True

        def json(self):
            return {"ok": True}
    monkeypatch.setattr(d.requests, "post", lambda url, json=None, timeout=None: sent.append((url, json)) or Ok())
    r = client.post("/api/drone/integration-request", json={"kind": "asylon", "email": "ops@site.co", "details": "2 docks"}).get_json()
    assert r["ok"] and r["sent"]
    url, body = sent[0]
    assert url.endswith("/functions/v1/demo-request") and "Asylon" in body["message"] and "2 docks" in body["message"]
    assert body["email"] == "ops@site.co" and len(body["full_name"]) >= 2


def test_licence_limit_applies(d, client, monkeypatch):
    monkeypatch.setattr(d, "api_cloud_can_add_source", lambda kind: d.jsonify({"ok": True, "allowed": False, "message": "PRO plan allows a maximum of 1 drone."}))
    r = client.post("/api/mavlink", json={"connection": "udpin:0.0.0.0:14599"})
    assert r.status_code == 409 and "maximum of 1 drone" in r.get_json()["error"]
    monkeypatch.setattr(d, "drone_control_allowed", lambda: False)
    assert client.post("/api/mavlink", json={"connection": "udpin:0.0.0.0:14599"}).status_code == 403


def test_only_admins_add_mavlink_drones():
    import users
    assert not users.allowed("operator", "POST", "/api/mavlink")
    assert not users.allowed("operator", "POST", "/api/mavlink/scan")
    assert not users.allowed("operator", "DELETE", "/api/mavlink/drone-m1")
    assert not users.allowed("operator", "POST", "/api/drone/integration-request")
    assert users.allowed("operator", "POST", "/api/drone/command")
