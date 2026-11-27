"""Flying despite the weather: when only the weather stops a flight the user is asked and may fly anyway (recorded in the
audit log); crewed aircraft nearby can never be overridden. And the Fleet map's Detectors layer."""
import time

from conftest import offset, wait_until


def _bad_weather(d, monkeypatch):
    s = d.load_safety()
    s["weather"] = {**s["weather"], "enabled": True, "mode": "block"}
    monkeypatch.setattr(d, "load_safety", lambda: s)
    monkeypatch.setattr(d, "weather_status", lambda loc=None: {"enabled": True, "reading": {"wind": 19}, "issues": ["wind 19 m/s"],
                                                                "error": "", "mode": "block"})
    return s


def _aircraft(d, monkeypatch, s):
    s["traffic"] = {**s["traffic"], "enabled": True, "block_takeoff": True}
    monkeypatch.setitem(d.traffic_state, "ok", True)
    monkeypatch.setitem(d.traffic_state, "at", time.time())
    monkeypatch.setitem(d.traffic_state, "threats", [{"callsign": "TEST1", "distance_m": 900, "alt_m": 300}])
    monkeypatch.setattr(d.airtraffic, "describe", lambda t: "TEST1 900 m away")


def test_flight_conditions_weather_becomes_a_warning_only_when_chosen(d, monkeypatch):
    s = _bad_weather(d, monkeypatch)
    problem, _ = d.flight_conditions((0, 0))
    assert "wind 19 m/s" in problem
    problem, warnings = d.flight_conditions((0, 0), ignore_weather=True)
    assert problem == "" and any("wind" in w for w in warnings)
    _aircraft(d, monkeypatch, s)
    assert "Crewed aircraft" in d.flight_conditions((0, 0), ignore_weather=True)[0]


def test_route_blocked_by_weather_asks_then_flies_anyway(d, client, fleet, monkeypatch):
    (v1,) = fleet(1)
    _bad_weather(d, monkeypatch)
    logged = []
    monkeypatch.setattr(d, "audit_record", lambda action, **kw: logged.append(action))
    body = {"name": "Out", "points": [offset(60, 0)], "alt": 30, "speed": 8, "pause": 0, "end": "hover"}
    r = client.post(f"/api/routes/fly?drone={v1}", json=body).get_json()
    assert not r["ok"] and "wind" in r["error"] and r["weather_override"]
    assert not d.run_of(v1)
    r = client.post(f"/api/routes/fly?drone={v1}", json={**body, "ignore_weather": True}).get_json()
    assert r["ok"], r
    assert "drone: flight despite the weather" in logged
    run = d.run_of(v1)
    assert run and run["ignore_weather"]
    assert wait_until(lambda: d.get_link(v1)["telemetry"].get("flying"), 20)
    client.post(f"/api/routes/stop?drone={v1}")
    client.post(f"/api/drone/command?drone={v1}", json={"cmd": "land"})
    assert wait_until(lambda: not d.get_link(v1)["telemetry"].get("flying"), 90)


def test_crewed_aircraft_cannot_be_overridden(d, client, fleet, monkeypatch):
    (v1,) = fleet(1)
    s = _bad_weather(d, monkeypatch)
    _aircraft(d, monkeypatch, s)
    body = {"name": "Out", "points": [offset(60, 0)], "alt": 30, "speed": 8, "pause": 0, "end": "hover", "ignore_weather": True}
    r = client.post(f"/api/routes/fly?drone={v1}", json=body).get_json()
    assert not r["ok"] and "Crewed aircraft" in r["error"] and not r.get("weather_override")
    r = client.post(f"/api/drone/command?drone={v1}", json={"cmd": "takeoff", "args": {"force": True}})
    j = r.get_json()
    assert r.status_code == 409 and not j["ok"] and j["can_force"] is False
    assert not d.get_link(v1)["telemetry"].get("flying")


def test_takeoff_blocked_by_weather_can_be_forced(d, client, fleet, monkeypatch):
    (v1,) = fleet(1)
    _bad_weather(d, monkeypatch)
    r = client.post(f"/api/drone/command?drone={v1}", json={"cmd": "takeoff"})
    j = r.get_json()
    assert r.status_code == 409 and j["can_force"] and j["weather_override"]
    assert client.post(f"/api/drone/command?drone={v1}", json={"cmd": "takeoff", "args": {"force": True}}).get_json()["ok"]
    assert wait_until(lambda: d.get_link(v1)["telemetry"].get("flying"), 20)
    client.post(f"/api/drone/command?drone={v1}", json={"cmd": "land"})
    assert wait_until(lambda: not d.get_link(v1)["telemetry"].get("flying"), 90)


def test_pages_ask_before_flying_in_bad_weather(client):
    import pages.dialogs
    assert "window.uiFly=" in pages.dialogs.DIALOG_HTML and "ignore_weather:true" in pages.dialogs.DIALOG_HTML
    for path in ("/fleet", "/drone-control"):
        html = client.get(path).get_data(as_text=True)
        assert "uiFly(" in html and "uiWeatherOk(d)" in html


def test_fleet_detectors_layer(d, client, monkeypatch):
    html = client.get("/fleet").get_data(as_text=True)
    assert 'id="flDet"' in html and "function drawDetectors" in html
    monkeypatch.setattr(d, "tab_on", lambda k: False)
    assert client.get("/api/fleet").get_json()["detectors"] == {"on": False, "detectors": [], "unknown": []}
    monkeypatch.setattr(d, "tab_on", lambda k: True)
    det = {"id": "a1b2c3d4e5f6", "name": "Gate", "lat": offset(0, 0)["lat"], "lon": offset(0, 0)["lon"], "range_m": 300,
           "camera": "", "sensor": "rf", "enabled": True}
    monkeypatch.setattr(d.dronedetect_mod, "load_detectors", lambda f: [det])
    intruder = {"slot": "rid:X1", "label": "Remote ID X1", **offset(50, 0), "alt": 40, "flying": True, "mine": False, "intruder": True}
    monkeypatch.setattr(d, "_known_drones", lambda: [intruder])
    x = client.get("/api/fleet").get_json()["detectors"]
    assert x["on"] and x["detectors"][0]["name"] == "Gate" and x["detectors"][0]["sees"] == ["Remote ID X1"]
    assert x["unknown"] == [{"label": "Remote ID X1", "lat": intruder["lat"], "lon": intruder["lon"]}]
