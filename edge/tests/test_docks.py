"""DJI Docks, Phase 1: the dock broker's passwords, the hub (topology, telemetry, replies), registration on the
Drone page with a simulated dock, the Pilot 2 setup page and who may do what."""
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

import pytest

from conftest import square, wait_until


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def dock_mod(d):
    import dock
    return dock


@pytest.fixture
def hub(dock_mod, tmp_path):
    store = dock_mod.DockStore(str(tmp_path / "docks.json"))
    return dock_mod.DockHub(store)


def topo(sn="DOCK1", drone="UAV1", dock_type=(3, 3, 0), drone_type=(0, 100, 1)):
    return {"tid": "t1", "bid": "b1", "method": "update_topo", "data": {
        "domain": dock_type[0], "type": dock_type[1], "sub_type": dock_type[2], "version": "1",
        "sub_devices": [{"sn": drone, "domain": drone_type[0], "type": drone_type[1], "sub_type": drone_type[2]}] if drone else []}}


def test_password_hash_matches_mosquitto_format(dock_mod):
    import base64
    h = dock_mod.mosquitto_hash("secret123", base64.b64decode("BnoqnfDWRXBR2ZLD"))
    # Written by mosquitto_passwd 2.0.18 for the same password and salt.
    assert h == "$7$101$BnoqnfDWRXBR2ZLD$8HFWl250YwnFzHkRkPXdrBC7MLZKuzJW2VVo7Nc/coHYplrM9QwzkkbYu6T9Nd2R0UzuOunzy0TzB2AAR/QEeg=="


def test_broker_files_made_once(dock_mod, tmp_path):
    folder = str(tmp_path / "dock-mqtt")
    a = dock_mod.ensure_broker_files(folder)
    passwd = open(os.path.join(folder, "passwd")).read()
    b = dock_mod.ensure_broker_files(folder)
    assert a == b and open(os.path.join(folder, "passwd")).read() == passwd  # same passwords, file not rewritten
    assert "allow_anonymous false" in open(os.path.join(folder, "mosquitto.conf")).read()
    assert passwd.startswith("dock:$7$101$") and "\nedge:$7$101$" in passwd
    assert a["dock_password"] not in passwd


def test_hub_topology_telemetry_and_replies(hub):
    sent = []
    hub.publish_mqtt = lambda topic, payload: sent.append((topic, payload))
    hub.handle("thing/product/DOCK1/osd", json.dumps({"data": {"cover_state": 0}}))  # before the topology: ignored
    assert hub.snapshot() == {"docks": [], "found": []}
    hub.handle("sys/product/DOCK1/status", json.dumps(topo()))
    assert sent[-1][0] == "sys/product/DOCK1/status_reply" and sent[-1][1]["data"] == {"result": 0}
    assert sent[-1][1]["tid"] == "t1" and sent[-1][1]["method"] == "update_topo"
    # Docks send their telemetry in parts; both parts are kept.
    hub.handle("thing/product/DOCK1/osd", json.dumps({"data": {"cover_state": 0, "drone_in_dock": 1, "latitude": 33.9, "longitude": 35.5}}))
    hub.handle("thing/product/DOCK1/osd", json.dumps({"data": {"environment_temperature": 21.5, "wind_speed": 2.1, "rainfall": 1,
                                                                "drone_charge_state": {"state": 1, "capacity_percent": 80}}}))
    hub.handle("thing/product/UAV1/osd", json.dumps({"data": {"battery": {"capacity_percent": 81}, "latitude": 33.9, "longitude": 35.5, "height": 0}}))
    found = hub.snapshot()["found"]
    assert len(found) == 1
    f = found[0]
    assert f["model"] == "DJI Dock 3" and f["drone_model"] == "Matrice 4TD" and f["online"] and f["drone_online"]
    assert f["cover"] == "closed" and f["drone_in_dock"] is True and f["battery"] == 81 and f["charging"]
    assert f["temperature"] == 21.5 and f["rain"] == "light" and f["lat"] == 33.9
    # An event that needs a reply gets one; the dock's config request gets the Cloud API app.
    hub.store.set_cloud("123", "key", "lic")
    hub.handle("thing/product/DOCK1/events", json.dumps({"tid": "e", "bid": "e", "method": "hms", "need_reply": 1, "data": {}}))
    assert sent[-1][0] == "thing/product/DOCK1/events_reply" and sent[-1][1]["data"]["result"] == 0
    hub.handle("thing/product/DOCK1/requests", json.dumps({"tid": "r", "bid": "r", "method": "config", "data": {}}))
    assert sent[-1][0] == "thing/product/DOCK1/requests_reply" and sent[-1][1]["data"]["app_id"] == "123"
    # Garbage is ignored.
    hub.handle("thing/product/DOCK1/osd", b"not json")
    hub.handle("weird/topic", b"{}")


def test_registered_dock_goes_offline(dock_mod, hub):
    clock = [1000.0]
    hub.now = lambda: clock[0]
    hub.handle("sys/product/DOCK1/status", topo())
    hub.store.register("DOCK1", "Roof")
    snap = hub.snapshot()
    assert snap["found"] == [] and snap["docks"][0]["name"] == "Roof" and snap["docks"][0]["slot"] == "dock1"
    assert snap["docks"][0]["online"]
    clock[0] += dock_mod.ONLINE_SECONDS + 1  # silent too long
    assert not hub.snapshot()["docks"][0]["online"]
    clock[0] += 1
    hub.handle("sys/product/DOCK1/status", topo())
    assert hub.snapshot()["docks"][0]["online"]
    hub.handle("sys/product/DOCK1/status", {"tid": "x", "bid": "x", "method": "update_topo", "data": {}})  # dock says it is going
    assert not hub.snapshot()["docks"][0]["online"]
    with pytest.raises(ValueError):
        hub.store.register("DOCK1", "Again")
    assert hub.store.register("DOCK2", "")["slot"] == "dock2"
    hub.store.unregister("DOCK1")
    assert hub.store.register("DOCK3", "")["slot"] == "dock1"  # a freed slot is reused


def test_register_simulated_dock_on_drone_page(d, client):
    page = client.get("/drone-control").get_data(as_text=True)
    assert 'id="dockPanel"' in page and "Set up a dock" in page
    assert "fleetDocks" in page and "function drawDockMap" in page  # docks in the fleet bar and on the map
    r = client.post("/api/docks/simulate", json={"lat": 45.5, "lon": -75.66}).get_json()
    assert r["ok"], r
    sn = r["sn"]
    try:
        found = wait_until(lambda: [x for x in client.get("/api/docks").get_json()["found"] if x["sn"] == sn and x["lat"]], 10)
        assert found and found[0]["model"] == "DJI Dock 3" and found[0]["simulated"] and found[0]["lat"] == 45.5
        assert d.dock_hub.local[sn].topo_acked  # the hub answered its topology
        assert client.post("/api/docks/register", json={"sn": "NOPE123", "name": "x"}).status_code == 404
        r = client.post("/api/docks/register", json={"sn": sn, "name": "Roof dock"}).get_json()
        assert r["ok"] and r["dock"]["name"] == "Roof dock" and r["dock"]["slot"].startswith("dock")
        assert client.post("/api/docks/register", json={"sn": sn, "name": "Again"}).status_code == 409
        data = client.get("/api/docks").get_json()
        mine = [x for x in data["docks"] if x["sn"] == sn][0]
        assert mine["online"] and mine["drone_model"] == "Matrice 4TD" and mine["battery"] is not None
        assert not [x for x in data["found"] if x["sn"] == sn]
        assert client.post(f"/api/docks/{sn}", json={"name": "Gate dock"}).get_json()["ok"]
        assert [x for x in client.get("/api/docks").get_json()["docks"] if x["sn"] == sn][0]["name"] == "Gate dock"
        # Survives a restart: the simulated dock is remembered.
        assert sn in json.load(open(d.dock_store.path))["simulated"]
    finally:
        assert client.delete(f"/api/docks/{sn}").get_json()["ok"]
    assert sn not in d.dock_hub.local and sn not in d.dock_store.docks()
    assert client.delete(f"/api/docks/{sn}").status_code == 404


def test_cloud_keys_are_never_sent_back(d, client):
    r = client.post("/api/docks/setup", json={"app_id": "  155000 ", "app_key": "THE-KEY", "app_license": "THE-LICENSE"}).get_json()
    assert r["ok"] and r["cloud_ready"] and r["app_id"] == "155000"
    body = client.get("/api/docks/setup").get_data(as_text=True)
    assert "THE-KEY" not in body and "THE-LICENSE" not in body and "/pilot?k=" in body
    old = d.dock_store.data["bind_token"]
    client.post("/api/docks/setup", json={"new_link": True})
    assert d.dock_store.data["bind_token"] != old
    assert client.post("/api/docks/setup", json={}).status_code == 400


def test_pilot_page_needs_the_secret_link(d, dock_mod):
    port = _free_port()
    d.dock_store.set_cloud("155000", "THE-KEY", "THE-LICENSE")
    server = dock_mod.start_pilot_server(d.dock_store, d._dock_creds, lambda: "192.168.1.20", port=port, bind="127.0.0.1")
    try:
        for path in ("/pilot", "/pilot?k=wrong", "/", "/pilot/../etc"):
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5)
            assert e.value.code == 404
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/pilot?k={d.dock_store.data['bind_token']}", timeout=5).read().decode()
        assert "tcp://192.168.1.20:1884" in html and "THE-KEY" in html and "platformLoadComponent" in html
        assert d._dock_creds()["dock_password"] in html and d._dock_creds()["edge_password"] not in html
    finally:
        server.shutdown()


def test_only_admins_set_up_docks(d):
    import users
    assert not users.allowed("viewer", "GET", "/api/docks/setup")
    assert not users.allowed("operator", "GET", "/api/docks/setup")
    assert users.allowed("viewer", "GET", "/api/docks")
    for path in ("/api/docks/simulate", "/api/docks/register", "/api/docks/setup", "/api/docks/SIMDOCK1"):
        assert not users.allowed("operator", "POST", path)
        assert users.allowed("admin", "POST", path)
    assert not users.allowed("operator", "DELETE", "/api/docks/SIMDOCK1")


def test_licence_switch(d, monkeypatch):
    """drone_dock is off unless switched on: per client in the portal (cloud) or ticked on an on-prem licence."""
    monkeypatch.setattr(d, "onprem_mode", lambda: False)
    monkeypatch.setitem(d.cloud_state, "licensed", True)
    monkeypatch.setitem(d.cloud_state, "features", {"drone_control": {"enabled": True, "limit_value": None}})
    assert not d._dock_licensed()  # never set for this client: off, even with drone control on
    monkeypatch.setitem(d.cloud_state, "features", {"drone_dock": {"enabled": True, "limit_value": None}})
    assert d._dock_licensed()
    monkeypatch.setitem(d.cloud_state, "features", {"drone_dock": {"enabled": False, "limit_value": None}})
    assert not d._dock_licensed()
    monkeypatch.setattr(d, "onprem_mode", lambda: True)
    monkeypatch.setitem(d.offline_license, "payload", {"features": ["camera_ai", "drone_control"], "feature_set": 2})
    assert not d._dock_licensed()
    monkeypatch.setitem(d.offline_license, "payload", {"features": ["camera_ai", "drone_dock"], "feature_set": 2})
    assert d._dock_licensed()
    import licensing
    assert "drone_dock" in licensing.FEATURES and "drone_dock" in licensing.OPT_IN_FEATURES
    assert licensing.features_for_dashboard({"features": ["drone_dock"]})["drone_dock"]["enabled"]


def test_not_licensed(d, client, monkeypatch):
    monkeypatch.setattr(d, "dock_allowed", lambda: False)
    assert client.post("/api/docks/simulate", json={}).status_code == 403
    assert client.post("/api/docks/register", json={"sn": "DOCK1"}).status_code == 403
    assert client.get("/api/docks").get_json()["allowed"] is False


@pytest.mark.skipif(not shutil.which("mosquitto"), reason="needs the mosquitto broker installed")
def test_real_broker_with_passwords(dock_mod, hub, tmp_path):
    """The broker files work in a real Mosquitto: right password connects, wrong or none is refused; a dock's
    topology arrives in the hub and the reply reaches the dock."""
    import paho.mqtt.client as mqtt
    creds = dock_mod.ensure_broker_files(str(tmp_path / "dock-mqtt"))
    port = _free_port()
    # The same steps as the dock-mqtt container: a private copy of the password file, owned by the broker's user.
    import pathlib
    import tempfile
    private = pathlib.Path(tempfile.mkdtemp(prefix="dock-mqtt-"))  # outside pytest's root-only folders
    shutil.copy(tmp_path / "dock-mqtt" / "passwd", private / "passwd")
    os.chmod(private / "passwd", 0o600)
    if os.name == "posix" and os.geteuid() == 0:
        import pwd
        try:
            u = pwd.getpwnam("mosquitto")
            os.chown(private, u.pw_uid, u.pw_gid)
            os.chown(private / "passwd", u.pw_uid, u.pw_gid)
        except KeyError:
            pass
    conf = tmp_path / "test.conf"
    conf.write_text(open(tmp_path / "dock-mqtt" / "mosquitto.conf").read().replace("listener 1883", f"listener {port} 127.0.0.1")
                    .replace("/mosquitto/passwd", str(private / "passwd")))
    broker = subprocess.Popen(["mosquitto", "-c", str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert wait_until(lambda: _port_open(port), 10)
        edge = dock_mod.MqttTransport(hub, "127.0.0.1", port, creds["edge_user"], creds["edge_password"])
        edge.start()
        assert wait_until(lambda: edge.connected, 10)

        def client(user, pw):
            got, state = [], {}
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            if user:
                c.username_pw_set(user, pw)
            c.on_connect = lambda cl, u, f, rc, p=None: state.update(rc=rc)
            c.on_message = lambda cl, u, m: got.append((m.topic, json.loads(m.payload)))
            c.connect("127.0.0.1", port)
            c.loop_start()
            wait_until(lambda: "rc" in state, 10)
            return c, got, state

        bad, _, st = client("dock", "wrong")
        assert st["rc"].is_failure
        bad.loop_stop()
        anon, _, st = client(None, None)
        assert st["rc"].is_failure
        anon.loop_stop()
        dk, got, st = client(creds["dock_user"], creds["dock_password"])
        assert not st["rc"].is_failure
        dk.subscribe("sys/product/DOCKX/status_reply", qos=1)
        time.sleep(0.3)
        dk.publish("sys/product/DOCKX/status", json.dumps(topo("DOCKX")), qos=1)
        assert wait_until(lambda: hub.snapshot()["found"], 10)
        assert wait_until(lambda: got, 10)[0][1]["data"] == {"result": 0}
        # A command to the dock and its answer, both over the broker (live video uses this).
        dk.on_message = lambda cl, u, m: dk.publish(m.topic + "_reply", json.dumps(
            {"tid": json.loads(m.payload)["tid"], "data": {"result": 0}}), qos=1) if m.topic.endswith("/services") else got.append(m)
        dk.subscribe("thing/product/DOCKX/services", qos=1)
        time.sleep(0.3)
        ok, msg, _ = hub.call("DOCKX", "live_stop_push", {"video_id": "x"}, timeout=5)
        assert ok, msg
        dk.loop_stop()
        edge.stop()
    finally:
        broker.terminate()
        broker.wait(5)
        shutil.rmtree(private, ignore_errors=True)


def _port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


# ---------- health alerts ----------

def _health_setup(dock_mod, hub, hms_text=None):
    clock = [5000.0]
    hub.now = lambda: clock[0]
    hub.started_at = clock[0]
    health = dock_mod.DockHealth(hub, hms_text)
    hub.handle("sys/product/DOCK1/status", topo())
    hub.store.register("DOCK1", "Roof")

    def osd(**fields):
        base = {"cover_state": 0, "drone_in_dock": 1, "environment_temperature": 22, "wind_speed": 2, "rainfall": 0,
                "drone_charge_state": {"state": 1, "capacity_percent": 70}}
        hub.handle("thing/product/DOCK1/osd", {"data": {**base, **fields}})
    return clock, health, osd


def test_health_conditions_start_and_clear(dock_mod, hub):
    clock, health, osd = _health_setup(dock_mod, hub)
    osd()
    assert health.check() == [] and health.active() == []
    osd(wind_speed=14.2)
    [a] = health.check()
    assert a["key"] == "wind" and a["active"] and a["level"] == "caution" and "14.2 m/s" in a["text"] and a["name"] == "Roof"
    assert health.check() == []  # still windy: no repeat
    osd(wind_speed=10)  # below the alert line but above "back": still on
    assert health.check() == [] and [x["key"] for x in health.active("DOCK1")] == ["wind"]
    osd(wind_speed=8)
    [c] = health.check()
    assert c["key"] == "wind" and not c["active"] and "dropped" in c["text"] and health.active() == []
    osd(cover_state=3, rainfall=3, environment_temperature=47, drone_charge_state={"state": 0, "capacity_percent": 12})
    got = {a["key"]: a for a in health.check()}
    assert set(got) == {"cover", "rain", "hot", "battery"} and got["cover"]["level"] == "warning" and "12%" in got["battery"]["text"]
    osd(cover_state=3, rainfall=3, environment_temperature=-25, drone_charge_state={"state": 0, "capacity_percent": 12})
    keys = {(a["key"], a["active"]) for a in health.check()}
    assert ("hot", False) in keys and ("cold", True) in keys
    osd()
    assert {a["key"] for a in health.check() if not a["active"]} == {"cover", "rain", "cold", "battery"}
    assert [a["key"] for a in health.recent(3)][0] in {"cover", "rain", "cold", "battery"}  # newest first


def test_health_dji_messages(dock_mod, hub):
    clock, health, osd = _health_setup(dock_mod, hub, {"0x16100083": "Dock cover motor error"})
    osd()
    hms = lambda code, level: hub.handle("thing/product/DOCK1/events", {"method": "hms", "data": {"list": [  # noqa: E731
        {"level": level, "code": code, "device_type": "3-3-0", "in_the_sky": 0}]}})
    hms("0x16100083", 2)
    hms("0x1111", 0)  # a notice: not an alert
    [a] = health.check()
    assert a["key"] == "hms:0x16100083" and a["level"] == "warning" and "Dock cover motor error" in a["text"] and "dock" in a["text"]
    hub.handle("thing/product/UAV1/events", {"method": "hms", "data": {"list": [{"level": 1, "code": "0x2222", "device_type": "0-100-1", "in_the_sky": 1}]}})
    [b] = health.check()
    assert "caution on the drone in flight" in b["text"] and "0x2222" in b["text"]
    clock[0] += dock_mod.HMS_CLEAR_SECONDS - 1
    osd()
    assert health.check() == []  # not repeated for a while yet
    clock[0] += 2
    osd()
    assert {(a["key"], a["active"]) for a in health.check()} == {("hms:0x16100083", False), ("hms:0x2222", False)}


def test_health_offline_and_back(dock_mod, hub):
    clock, health, osd = _health_setup(dock_mod, hub)
    osd()
    hub.store.register("DOCK9", "Never seen")
    clock[0] += dock_mod.OFFLINE_ALERT_SECONDS - 1
    assert health.check() == []
    clock[0] += 2
    [a] = health.check()
    assert a["sn"] == "DOCK1" and a["key"] == "offline" and "no message for 1 min" in a["text"]
    clock[0] += dock_mod.STARTUP_GRACE_SECONDS
    [b] = health.check()
    assert b["sn"] == "DOCK9" and "hasn't connected since" in b["text"]
    hub.handle("sys/product/DOCK1/status", topo())
    osd()
    [c] = health.check()
    assert c["sn"] == "DOCK1" and not c["active"] and c["text"] == "Roof is back online."
    hub.store.unregister("DOCK9")
    assert health.check() == [] and health.active() == []  # a removed dock's alert just goes (no all-clear)
    hub.handle("sys/product/DOCKX/status", topo("DOCKX"))  # found but not registered: never alerted
    clock[0] += 1000
    hub.handle("sys/product/DOCK1/status", topo())
    osd()
    assert health.check() == []


def test_simulated_dock_alert_reaches_telegram_and_page(d, client, monkeypatch):
    sent = []
    monkeypatch.setattr(d, "queue_telegram_alert", lambda kind, text, key, snapshot_bytes=None, buttons=None: sent.append((kind, text, key, snapshot_bytes)))
    sn = client.post("/api/docks/simulate", json={}).get_json()["sn"]
    try:
        assert wait_until(lambda: [x for x in client.get("/api/docks").get_json()["found"] if x["sn"] == sn and x["lat"]], 10)
        assert client.post("/api/docks/register", json={"sn": sn, "name": "Yard dock"}).get_json()["ok"]
        d.dock_health_tick()
        assert not [s for s in sent if sn in s[2]]
        assert client.post(f"/api/docks/{sn}/fault", json={"fault": "cover"}).get_json()["ok"]
        assert wait_until(lambda: d.dock_health_tick() or [s for s in sent if sn in s[2]], 10)
        kind, text, key, snap = [s for s in sent if sn in s[2]][0]
        assert kind == "dock_health" and "Yard dock" in text and "cover" in text and text.startswith("⚠️") and snap == b""
        mine = [x for x in client.get("/api/docks").get_json()["docks"] if x["sn"] == sn][0]
        assert mine["alerts"][0]["key"] == "cover" and mine["alerts"][0]["level"] == "warning"
        assert client.get("/api/docks").get_json()["health_log"][0]["sn"] == sn
        assert client.post(f"/api/docks/{sn}/fault", json={"fault": ""}).get_json()["ok"]
        assert wait_until(lambda: d.dock_health_tick() or [s for s in sent if s[1].startswith("✅") and sn in s[2]], 10)
        assert client.post(f"/api/docks/{sn}/fault", json={"fault": "explode"}).status_code == 400
        assert client.post("/api/docks/NOTSIM1/fault", json={"fault": "cover"}).status_code == 404
        import users
        assert not users.allowed("operator", "POST", f"/api/docks/{sn}/fault")
    finally:
        client.delete(f"/api/docks/{sn}")


# ---------- dock count on the licence ----------

def test_dock_limit_from_licence(d, monkeypatch):
    monkeypatch.setattr(d, "onprem_mode", lambda: False)
    monkeypatch.setitem(d.cloud_state, "features", {"drone_dock": {"enabled": True, "limit_value": 2}})
    assert d.dock_limit() == 2
    monkeypatch.setitem(d.cloud_state, "features", {"drone_dock": {"enabled": True, "limit_value": None}})
    assert d.dock_limit() is None  # no number set: no cap
    monkeypatch.setattr(d, "onprem_mode", lambda: True)
    monkeypatch.setitem(d.offline_license, "payload", {"features": ["drone_dock"], "limits": {"cameras": 4, "drones": 1, "docks": 1}})
    assert d.dock_limit() == 1
    monkeypatch.setitem(d.offline_license, "payload", {"features": ["drone_dock"], "limits": {"cameras": 4}})
    assert d.dock_limit() is None


def test_dock_count_enforced(d, client, monkeypatch):
    limit = [1]
    monkeypatch.setattr(d, "dock_limit", lambda: limit[0])
    for sn in ("REALDOCK1", "REALDOCK2"):  # two real docks have connected
        d.dock_hub.handle(f"sys/product/{sn}/status", topo(sn, drone=sn + "U"))
    sim = client.post("/api/docks/simulate", json={}).get_json()["sn"]
    try:
        assert wait_until(lambda: sim in d.dock_hub.state, 10)
        assert client.post("/api/docks/register", json={"sn": "REALDOCK1", "name": "One"}).get_json()["ok"]
        r = client.post("/api/docks/register", json={"sn": "REALDOCK2", "name": "Two"})
        assert r.status_code == 409 and "allows 1 DJI dock." in r.get_json()["error"]
        assert client.post("/api/docks/register", json={"sn": sim, "name": "Test"}).get_json()["ok"]  # simulated: not counted
        data = client.get("/api/docks").get_json()
        assert data["limit"] == 1 and data["used"] == 1
        limit[0] = 2
        assert client.post("/api/docks/register", json={"sn": "REALDOCK2", "name": "Two"}).get_json()["ok"]
        # The licence is lowered: the newest real dock is over it, shown so and no longer watched.
        limit[0] = 1
        docks = {x["sn"]: x for x in client.get("/api/docks").get_json()["docks"]}
        assert docks["REALDOCK2"]["over_limit"] and not docks["REALDOCK1"]["over_limit"] and not docks[sim]["over_limit"]
        assert d._docks_over_limit() == {"REALDOCK2"}
        d.dock_hub.started_at -= 10_000
        d.dock_hub.state["REALDOCK1"]["last_seen"] -= 10_000
        d.dock_hub.state["REALDOCK2"]["last_seen"] -= 10_000
        alerted = {a["sn"] for a in d.dock_health.check() if a["active"]}
        assert "REALDOCK1" in alerted and "REALDOCK2" not in alerted
        limit[0] = None
        assert d._docks_over_limit() == set()
    finally:
        for sn in ("REALDOCK1", "REALDOCK2", sim):
            client.delete(f"/api/docks/{sn}")
        with d.dock_hub.lock:
            for sn in ("REALDOCK1", "REALDOCK2"):
                d.dock_hub.state.pop(sn, None)
        d.dock_health.check()


# ---------- Phase 2: dock video ----------

def test_dock_video_commands(d, client, monkeypatch):
    sn = client.post("/api/docks/simulate", json={}).get_json()["sn"]
    try:
        assert wait_until(lambda: d.dock_hub.video_sources(sn), 10)
        srcs = d.dock_hub.video_sources(sn)
        assert srcs[0]["device"] == "drone" and srcs[0]["video_id"] == f"{sn}-UAV/99-0-0/normal-0"
        assert srcs[0]["lenses"] == ["wide", "zoom", "ir"] and srcs[1]["device"] == "dock"
        assert client.post(f"/api/docks/{sn}/video", json={"action": "start"}).status_code == 404  # not registered yet
        assert client.post("/api/docks/register", json={"sn": sn, "name": "Video dock"}).get_json()["ok"]
        slot = d.dock_store.docks()[sn]["slot"]
        r = client.post(f"/api/docks/{sn}/video", json={"action": "start"}).get_json()
        assert r["ok"] and r["video"]["streaming"] and r["video"]["lens"] == "wide" and r["camera"] == slot
        sim = d.dock_hub.local[sn]
        assert sim.streaming == srcs[0]["video_id"]
        push = [p for t, p in sim.replies if t.endswith("/services")][-1]
        assert push["method"] == "live_start_push" and push["data"]["url"].endswith(f":1935/{slot}") and push["data"]["url_type"] == 1
        assert client.post(f"/api/docks/{sn}/video", json={"action": "lens", "lens": "ir"}).get_json()["video"]["lens"] == "ir"
        assert [p for t, p in sim.replies if t.endswith("/services")][-1]["data"] == {"video_id": srcs[0]["video_id"], "video_type": "ir"}
        r = client.post(f"/api/docks/{sn}/video", json={"action": "lens", "lens": "night"})
        assert r.status_code == 409 and "no night lens" in r.get_json()["error"]
        mine = [x for x in client.get("/api/docks").get_json()["docks"] if x["sn"] == sn][0]
        assert mine["video"]["streaming"] and mine["video"]["lens"] == "ir" and mine["video"]["sources"] == ["drone", "dock"]
        assert client.post(f"/api/docks/{sn}/video", json={"action": "stop"}).get_json()["ok"] and sim.streaming is None
        assert client.post(f"/api/docks/{sn}/video", json={"action": "lens", "lens": "zoom"}).status_code == 409  # not streaming
        assert client.post(f"/api/docks/{sn}/video", json={"action": "start", "device": "dock"}).get_json()["video"]["device"] == "dock"
        assert client.post(f"/api/docks/{sn}/video", json={"action": "fly"}).status_code == 400
        # Offline: the stream is forgotten and new requests are refused.
        sim.set_power(False)
        assert not d.dock_hub.summary(sn)["video"]["streaming"]
        assert client.post(f"/api/docks/{sn}/video", json={"action": "start"}).status_code == 409
        import users
        assert users.allowed("operator", "POST", f"/api/docks/{sn}/video") and not users.allowed("viewer", "POST", f"/api/docks/{sn}/video")
    finally:
        client.delete(f"/api/docks/{sn}")


def test_dock_that_does_not_answer(dock_mod, hub):
    hub.handle("sys/product/DOCK1/status", topo())
    hub.publish_mqtt = lambda topic, payload: None  # a real dock that never replies
    ok, msg, _ = hub.call("DOCK1", "live_stop_push", {"video_id": "x"}, timeout=0.2)
    assert not ok and "didn't answer" in msg and hub.pending == {}
    ok, msg, _ = hub.start_video("DOCK1", "rtmp://pc:1935/dock1")
    assert not ok and "isn't reporting a camera" in msg  # no live_capacity yet

    def refuse(topic, payload):
        hub.handle(topic + "_reply", {"tid": payload["tid"], "data": {"result": 513012}})
    hub.publish_mqtt = refuse
    hub.handle("thing/product/DOCK1/state", {"data": {"live_capacity": {"device_list": [{"sn": "UAV1", "camera_list": [
        {"camera_index": "99-0-0", "video_list": [{"video_index": "normal-0", "switchable_video_types": ["wide"]}]}]}]}}})
    ok, msg, _ = hub.start_video("DOCK1", "rtmp://pc:1935/dock1")
    assert not ok and "isn't ready yet" in msg and not hub.summary("DOCK1")["video"]["streaming"]


def test_dock_cameras_in_frigate_and_counts(d, tmp_path, monkeypatch):
    import yaml
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"cameras": {"front": {"enabled": True}, "drone": {"enabled": True, "detect": {"fps": 5}}}}))
    monkeypatch.setattr(d, "LIVE_FRIGATE_CONFIG", str(cfg))
    restarts = []
    monkeypatch.setattr(d, "_restart_frigate", lambda: restarts.append(1) or (True, ""))
    assert d._dock_camera("dock1", True) is True
    c = yaml.safe_load(cfg.read_text())
    assert c["cameras"]["dock1"]["ffmpeg"]["inputs"][0]["path"] == "rtsp://127.0.0.1:8554/dock1"
    assert c["go2rtc"]["streams"]["dock1"] == ["rtsp://host.docker.internal:8556/dock1"]
    assert d._dock_camera("dock1", True) is False and len(restarts) == 1  # already there: no restart
    # Dock cameras don't use a camera or drone place on the licence.
    monkeypatch.setattr(d, "_frigate_camera_names", lambda: ["front", "drone", "dock1", "dock2"])
    assert d.local_source_usage() == {"cameras": 1, "drones": 1}
    monkeypatch.setitem(d.cloud_state, "limits", {"cameras": 1, "drones": 1})
    assert d._sources_over_limit() == set()
    assert d._is_dock_name("dock1") and d._is_dock_name("DOCK12") and not d._is_dock_name("dockyard") and not d._is_dock_name("drone")
    assert d._dock_camera("dock1", False) is True and "dock1" not in yaml.safe_load(cfg.read_text())["cameras"]
    assert d._dock_camera("dock1", False) is False


def test_registering_real_dock_adds_its_camera(d, client, monkeypatch):
    calls = []
    monkeypatch.setattr(d, "_dock_camera_async", lambda slot, add: calls.append((slot, add)))
    monkeypatch.setattr(d, "dock_limit", lambda: None)
    d.dock_hub.handle("sys/product/REALDOCK7/status", topo("REALDOCK7", drone="REALDOCK7U"))
    try:
        slot = client.post("/api/docks/register", json={"sn": "REALDOCK7", "name": "Real"}).get_json()["dock"]["slot"]
        assert calls == [(slot, True)]
        assert client.delete("/api/docks/REALDOCK7").get_json()["ok"]
        assert calls == [(slot, True), (slot, False)]
    finally:
        d.dock_store.unregister("REALDOCK7")
        with d.dock_hub.lock:
            d.dock_hub.state.pop("REALDOCK7", None)


# ---------- Phase 3a: the dock flies a route by itself ----------

def test_flight_plan_file(d):
    import zipfile, io
    import dock_wayline as w
    home = (45.5, -75.66)
    stops = [{"lat": 45.5005, "lon": -75.66}, {"lat": 45.5005, "lon": -75.659}]
    detours = {(home, (45.5005, -75.66)): [(45.5002, -75.6605)]}
    pts = w.plan_points(home, stops, lambda a, b: detours.get((a, b), []))
    assert [p["stop"] for p in pts] == [False, True, True] and pts[0]["lat"] == 45.5002
    kmz = w.build_kmz(pts, alt=300, speed=50, pause_s=5, drone_enum=(100, 1), payload_enum=99)
    names = zipfile.ZipFile(io.BytesIO(kmz)).namelist()
    assert set(names) == {"wpmz/template.kml", "wpmz/waylines.wpml"}
    wp = zipfile.ZipFile(io.BytesIO(kmz)).read("wpmz/waylines.wpml").decode()
    assert "<wpml:finishAction>goHome</wpml:finishAction>" in wp and "<wpml:executeRCLostAction>goBack</wpml:executeRCLostAction>" in wp
    assert "<wpml:droneEnumValue>100</wpml:droneEnumValue>" in wp and "<wpml:payloadEnumValue>99</wpml:payloadEnumValue>" in wp
    back = w.read_kmz(kmz)
    assert [round(p["lat"], 4) for p in back] == [45.5002, 45.5005, 45.5005]
    assert all(p["alt"] == w.MAX_ALT and p["speed"] == w.MAX_SPEED for p in back)  # clamped to 120 m and 12 m/s
    assert [p["hover"] for p in back] == [0.0, 5.0, 5.0]  # hover only at the real stops
    assert len(w.fingerprint(kmz)) == 32
    with pytest.raises(ValueError):
        w.plan_points(home, stops, lambda a, b: None)
    with pytest.raises(ValueError):
        w.build_kmz([], 30, 5)


@pytest.fixture
def flying_dock(d, client, monkeypatch):
    """A registered simulated dock with automatic flights on, a fast simulator and the flight-plan server running."""
    port = _free_port()
    monkeypatch.setattr(d, "DOCK_PILOT_PORT", port)
    monkeypatch.setattr(d, "_lan_ip", lambda: "127.0.0.1")
    server = d.dock_lib.start_pilot_server(d.dock_store, d._dock_creds, lambda: "127.0.0.1", port=port, bind="127.0.0.1")
    sent = []
    monkeypatch.setattr(d, "queue_telegram_alert", lambda kind, text, key, snapshot_bytes=None, buttons=None: sent.append(text))
    home = (45.5048, -75.6636)
    sn = client.post("/api/docks/simulate", json={"lat": home[0], "lon": home[1]}).get_json()["sn"]
    sim = d.dock_hub.local[sn]
    sim.speedup, sim.period = 40.0, 0.2
    assert wait_until(lambda: d.dock_hub.summary(sn)["lat"] and d.dock_hub.video_sources(sn), 10)
    assert client.post("/api/docks/register", json={"sn": sn, "name": "Patrol dock"}).get_json()["ok"]
    r = client.post("/api/docks/" + sn + "/settings", json={"auto_flights": True})
    assert r.status_code == 400  # the site's permission must be confirmed
    assert client.post("/api/docks/" + sn + "/settings", json={"auto_flights": True, "confirm": True}).get_json()["auto_flights"]
    stops = [{"lat": home[0] + 0.0003, "lon": home[1]}, {"lat": home[0] + 0.0003, "lon": home[1] + 0.0004}]
    assert client.post("/api/routes", json={"name": "Dock loop", "points": stops, "alt": 40, "speed": 8, "pause": 2}).get_json()["ok"]
    yield d, client, sn, sim, sent
    client.delete("/api/routes", json={"name": "Dock loop"})
    client.delete(f"/api/docks/{sn}")
    server.shutdown()


def test_dock_flies_a_route_and_lands(flying_dock):
    d, client, sn, sim, sent = flying_dock
    r = client.post(f"/api/docks/{sn}/mission", json={"action": "fly", "route": "Dock loop"}).get_json()
    assert r["ok"], r
    assert any("route Dock loop started" in t for t in sent)
    assert wait_until(lambda: d.dock_hub.summary(sn)["drone_in_dock"] is False, 10)  # took off
    m = d.dock_hub.mission(sn)
    assert m["active"] and m["name"] == "Dock loop" and len(m["points"]) == 2
    d.dock_missions_tick()
    assert d.dock_hub.summary(sn)["video"]["streaming"]  # the AI watches the patrol
    assert client.post(f"/api/docks/{sn}/mission", json={"action": "fly", "route": "Dock loop"}).status_code == 409  # busy
    seen = set()

    def landed():
        x = d.dock_hub.summary(sn)
        if x["drone_lat"]:
            seen.add((round(x["drone_lat"], 4), round(x["drone_lon"], 4)))
        return not d.dock_hub.mission(sn)["active"] and x["drone_in_dock"]
    assert wait_until(landed, 20)
    assert d.dock_hub.mission(sn)["status"] == "ok"
    assert (45.5051, -75.6636) in seen or (45.5051, -75.6632) in seen  # it went to the stops
    d.dock_missions_tick()
    assert any("route Dock loop finished and is back in the dock" in t for t in sent)
    assert not d.dock_hub.summary(sn)["video"]["streaming"]  # video stopped after landing
    page = [x for x in client.get("/api/docks").get_json()["docks"] if x["sn"] == sn][0]
    assert page["mission"]["status"] == "ok" and page["auto_flights"] and page["range_m"] == 500


def test_dock_called_back(flying_dock):
    d, client, sn, sim, sent = flying_dock
    sim.speedup = 2.0  # slow enough to call it back mid-route
    assert client.post(f"/api/docks/{sn}/mission", json={"action": "stop"}).status_code == 409  # nothing to stop
    assert client.post(f"/api/docks/{sn}/mission", json={"action": "fly", "route": "Dock loop"}).get_json()["ok"]
    assert wait_until(lambda: d.dock_hub.summary(sn)["drone_in_dock"] is False, 10)
    r = client.post(f"/api/docks/{sn}/mission", json={"action": "stop"}).get_json()
    assert r["ok"] and d.dock_hub.mission(sn)["status"] == "returning"
    sim.speedup = 40.0
    assert wait_until(lambda: not d.dock_hub.mission(sn)["active"], 20)
    assert d.dock_hub.mission(sn)["status"] == "canceled"
    d.dock_missions_tick()
    assert any("was called back and is back in the dock" in t for t in sent)


def test_dock_preflight_refusals(flying_dock, monkeypatch):
    d, client, sn, sim, sent = flying_dock
    fly = lambda: client.post(f"/api/docks/{sn}/mission", json={"action": "fly", "route": "Dock loop"})  # noqa: E731
    assert "No saved route" in client.post(f"/api/docks/{sn}/mission", json={"action": "fly", "route": "Nope"}).get_json()["error"]
    assert client.post(f"/api/docks/{sn}/settings", json={"range_m": 20}).get_json()["range_m"] == 50  # at least 50 m
    assert client.post(f"/api/docks/{sn}/settings", json={"range_m": 9000}).get_json()["range_m"] == 2000  # at most 2 km
    client.post(f"/api/docks/{sn}/settings", json={"range_m": 100})
    far = {"name": "Dock far", "points": [{"lat": 45.5048 + 0.003, "lon": -75.6636}], "alt": 40, "speed": 8}
    assert client.post("/api/routes", json=far).get_json()["ok"]
    try:
        r = client.post(f"/api/docks/{sn}/mission", json={"action": "fly", "route": "Dock far"}).get_json()
        assert "Stop 1 is 333 m from Patrol dock (its range is 100 m)" in r["error"]
    finally:
        client.delete("/api/routes", json={"name": "Dock far"})
    client.post(f"/api/docks/{sn}/settings", json={"range_m": 500})
    monkeypatch.setitem(d.load_response_settings(), "min_battery", 35)
    sim.battery = 20.0
    sim.fault = "battery"
    assert wait_until(lambda: (d.dock_hub.summary(sn)["battery"] or 99) < 35, 5)
    assert "battery" in fly().get_json()["error"]
    sim.fault = "wind"
    sim.battery = 90.0
    assert wait_until(lambda: (d.dock_hub.summary(sn)["wind"] or 0) > 12, 5)
    assert "Wind at the dock" in fly().get_json()["error"]
    sim.fault = "cover"
    assert wait_until(lambda: d.dock_hub.summary(sn)["cover"] == "cover fault", 5)
    assert "cover" in fly().get_json()["error"]
    sim.fault = ""
    assert wait_until(lambda: d.dock_hub.summary(sn)["cover"] == "closed", 5)
    d.nofly.save_zones(d.NOFLY_FILE, [square({"lat": 45.5051, "lon": -75.6636}, 10, "School")])
    try:
        assert "School" in fly().get_json()["error"]
    finally:
        d.nofly.save_zones(d.NOFLY_FILE, [])
    client.post(f"/api/docks/{sn}/settings", json={"auto_flights": False})
    assert "Automatic flights are off" in fly().get_json()["error"]
    import users
    assert users.allowed("operator", "POST", f"/api/docks/{sn}/mission") and not users.allowed("operator", "POST", f"/api/docks/{sn}/settings")
    assert not users.allowed("viewer", "POST", f"/api/docks/{sn}/mission")


def test_aircraft_sends_dock_home(flying_dock, monkeypatch):
    d, client, sn, sim, sent = flying_dock
    sim.speedup = 1.0
    assert client.post(f"/api/docks/{sn}/mission", json={"action": "fly", "route": "Dock loop"}).get_json()["ok"]
    assert wait_until(lambda: d.dock_hub.summary(sn)["drone_in_dock"] is False, 10)
    monkeypatch.setattr(d, "send_telegram", lambda *a, **k: {"ok": True})
    d._traffic_alerted.clear()
    d._traffic_respond([{"hex": "abc123", "call": "TEST1", "type": "C172", "dist_m": 1000, "bearing": 90, "height_ft": 800}],
                       {**d.load_safety()["traffic"], "action": "descend"})
    assert d.dock_hub.mission(sn)["status"] == "returning"
    sim.speedup = 40.0
    assert wait_until(lambda: not d.dock_hub.mission(sn)["active"], 20)
