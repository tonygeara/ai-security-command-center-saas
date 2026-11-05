"""Flight safety: weather limits, crewed aircraft, official airspace, radio coverage and the shortest route order."""
import io
import json
import os
import sys
import time

import pytest

from conftest import APP, HOME, offset, wait_until

sys.path.insert(0, APP)
import airspace  # noqa: E402
import airtraffic  # noqa: E402
import nofly  # noqa: E402
import rf  # noqa: E402
import weather  # noqa: E402

CALM = {"current": {"time": "2026-11-05T12:00", "temperature_2m": 18.0, "precipitation": 0.0, "weather_code": 1,
                    "wind_speed_10m": 3.0, "wind_gusts_10m": 5.0, "wind_direction_10m": 200},
        "hourly": {"time": ["2026-11-05T11:00", "2026-11-05T12:00"], "visibility": [20000, 24000],
                   "wind_speed_80m": [4.0, 5.0], "wind_speed_120m": [5.0, 6.0]}}


def windy(speed=15.0, code=1):
    w = json.loads(json.dumps(CALM))
    w["current"].update(wind_speed_10m=speed, wind_gusts_10m=speed + 4, weather_code=code)
    return w


def plane(north_m, east_m, ft=800, hexid="abc123", call="HELI1"):
    p = offset(north_m, east_m)
    return {"hex": hexid, "flight": call + "  ", "lat": p["lat"], "lon": p["lon"], "alt_baro": ft, "gs": 90, "track": 180, "seen_pos": 1}


@pytest.fixture(autouse=True)
def clean(d):
    yield
    for f in (d.SAFETY_FILE, d.AIRPORTS_FILE):
        if os.path.exists(f):
            os.remove(f)
    d._weather_fetch = lambda lat, lon: None
    d._traffic_fetch = lambda settings, lat, lon: None
    d.weather_cache.items.clear()
    d.traffic_state.update(ok=False, error="", aircraft=[], threats=[], at=0.0, actions=[])
    d._traffic_alerted.clear()
    nofly.save_zones(d.NOFLY_FILE, [])


def use_weather(d, data):
    d._weather_fetch = lambda lat, lon: weather.parse(data)
    d.weather_cache.items.clear()


# ----- weather -----

def test_weather_reading_and_limits():
    w = weather.parse(CALM)
    assert w["wind_80m_ms"] == 5.0 and w["visibility_m"] == 24000 and w["text"] == "mainly clear"
    assert weather.assess(w, {}) == []
    bad = weather.parse(windy(12, code=63))
    issues = weather.assess(bad, {})
    assert any("wind 12 m/s" in i for i in issues) and any("gusts 16" in i for i in issues) and "rain" in issues
    assert weather.assess(bad, {"max_wind_ms": 15, "max_gust_ms": 20, "block_precip": False}) == []
    with pytest.raises(ValueError):
        weather.parse({"error": True, "reason": "bad"})


def test_weather_cache_keeps_a_recent_reading_when_offline():
    calls = []

    def fetch(lat, lon):
        calls.append(1)
        if len(calls) > 1:
            raise OSError("offline")
        return weather.parse(CALM)
    c = weather.Cache(fetch)
    assert c.get(1, 2)[0]["wind_ms"] == 3.0
    assert len(calls) == 1 and c.get(1, 2)[0] and len(calls) == 1  # cached
    c.items[(1.0, 2.0)] = c.items[(1.0, 2.0)][:3] + (0.0,)  # pretend the check is old
    r, err, _ = c.get(1, 2)
    assert r["wind_ms"] == 3.0 and "unavailable" in err


def test_bad_weather_holds_routes_and_takeoff(d, client, fleet):
    (v1,) = fleet(1)
    use_weather(d, windy(14))
    body = {"points": [offset(20, 0)], "alt": 20, "speed": 8, "pause": 0}
    r = client.post(f"/api/routes/fly?drone={v1}", json=body).get_json()
    assert not r["ok"] and "Weather: wind 14 m/s" in r["error"]
    t = client.post(f"/api/drone/command?drone={v1}", json={"cmd": "takeoff"})
    assert t.status_code == 409 and t.get_json()["can_force"]
    assert client.get("/api/safety").get_json()["conditions"]["problem"].startswith("Weather")
    client.post("/api/safety/settings", json={"weather": {"mode": "warn"}})
    r = client.post(f"/api/routes/fly?drone={v1}", json=body).get_json()
    assert r["ok"] and "⚠ Weather" in r["message"]
    client.post(f"/api/routes/stop?drone={v1}")
    use_weather(d, CALM)
    client.post("/api/safety/settings", json={"weather": {"mode": "block"}})
    assert client.get("/api/safety").get_json()["conditions"] == {"problem": "", "warnings": []}


def test_unknown_weather_can_be_required(d, client):
    client.post("/api/safety/settings", json={"site": {"lat": HOME[0], "lon": HOME[1]}, "weather": {"unknown": "block"}})
    assert "weather is unknown" in client.get("/api/safety").get_json()["conditions"]["problem"]


# ----- crewed aircraft -----

def test_aircraft_parsing_and_threats():
    data = {"ac": [plane(1500, 0, 900), plane(0, 6000, 3000, "def456", "ELY123"), {**plane(500, 0), "alt_baro": "ground", "hex": "g"},
                   {**plane(400, 0), "seen_pos": 300, "hex": "old"}, {"hex": "nopos", "alt_baro": 1000}, plane(40000, 0, 500, "far")]}
    ac = airtraffic.parse(data, HOME[0], HOME[1], site_elev_m=100, watch_km=10)
    assert [a["hex"] for a in ac] == ["abc123", "def456"]  # nearest first; ground, stale, no position and far are left out
    assert ac[0]["height_ft"] == pytest.approx(900 - 100 / 0.3048) and ac[0]["call"] == "HELI1"
    assert [a["hex"] for a in airtraffic.threats(ac, {})] == ["abc123"]  # the airliner is too high and too far
    assert "HELI1" in airtraffic.describe(ac[0]) and " N," in airtraffic.describe(ac[0])
    with pytest.raises(ValueError):
        airtraffic.clean_settings({"url": "ftp://x"})


def test_close_aircraft_stops_the_route_and_brings_the_drone_down(d, client, fleet):
    (v1,) = fleet(1)
    route = {"points": [offset(20, 0), offset(20, 20)], "alt": 30, "speed": 8, "pause": 0, "loop": True}
    assert client.post(f"/api/routes/fly?drone={v1}", json=route).get_json()["ok"]
    assert wait_until(lambda: d.virtual_drones[v1].alt > 25, 40)
    d._traffic_fetch = lambda s, lat, lon: {"ac": [plane(1200, 300, 700)]}
    d.traffic_check_once()
    assert d.traffic_state["threats"] and d.run_of(v1) is None
    assert wait_until(lambda: d.virtual_drones[v1].alt < 18, 30)  # descending to 15 m
    assert any("Crewed aircraft near the site" in t and "descending" in t for t in d.sent)
    n = len(d.sent)
    d.traffic_check_once()
    assert len(d.sent) == n  # the same aircraft is reported once
    r = client.post(f"/api/routes/fly?drone={v1}", json=route).get_json()
    assert not r["ok"] and "Crewed aircraft nearby" in r["error"]


# ----- official airspace -----

HELI = offset(1300, 0)
CSV = ("id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,iso_country\n"
       f"1,OLBA,large_airport,Beirut Rafic Hariri,{HOME[0] + 0.05},{HOME[1]},87,AS,LB\n"
       f"2,XHEL,heliport,Hospital Helipad,{HELI['lat']},{HELI['lon']},0,AS,LB\n"
       f"3,FAR,small_airport,Far Field,{HOME[0] + 1.5},{HOME[1]},0,AS,LB\n"
       f"4,OLD,closed,Old Strip,{HOME[0]},{HOME[1] + 0.01},0,AS,LB\n")


def test_airports_become_circles():
    found = airspace.airports_near(io.StringIO(CSV), HOME[0], HOME[1], 30)
    assert [a["ident"] for a in found] == ["XHEL", "OLBA"]  # nearest first; too far and closed ones left out
    heli, big = airspace.airport_zones(found)
    assert heli["id"] == "ap-XHEL" and heli["source"] == "airport" and len(heli["points"]) == 24
    inside, outside = offset(1300 - 990, 0), offset(1300 - 1060, 0)
    assert nofly.zone_at([heli], inside["lat"], inside["lon"]) and not nofly.zone_at([heli], outside["lat"], outside["lon"])
    assert nofly.zone_at([big], HOME[0], HOME[1])  # 5.5 km from an 8 km airport circle


def test_airspace_geojson_keeps_low_airspace_only():
    def sq(name, floor):
        a, b = offset(100, 100), offset(200, 200)
        ring = [[a["lon"], a["lat"]], [b["lon"], a["lat"]], [b["lon"], b["lat"]], [a["lon"], b["lat"]], [a["lon"], a["lat"]]]
        return {"type": "Feature", "properties": {"name": name, "lowerLimit": floor}, "geometry": {"type": "Polygon", "coordinates": [ring]}}
    data = {"type": "FeatureCollection", "features": [sq("CTR Beirut", {"value": 0, "unit": 1, "referenceDatum": 0}),
                                                      sq("TMA high", {"value": 45, "unit": 6}), sq("Danger area", "SFC")]}
    zones, skipped = airspace.geojson_zones(data, (HOME[0], HOME[1]))
    assert [z["name"] for z in zones] == ["🛇 CTR Beirut", "🛇 Danger area"] and skipped == 1
    assert len(zones[0]["points"]) == 4 and zones[0]["source"] == "airspace"
    with pytest.raises(ValueError):
        airspace.geojson_zones({"hello": 1})


def test_imported_airports_block_routes_until_authorised(d, client, fleet):
    (v1,) = fleet(1)
    r = client.post("/api/airspace/upload", data={"file": (io.BytesIO(CSV.encode()), "airports.csv")}).get_json()
    assert r["ok"] and "2 airport zones imported" in r["message"] and "inside ✈ Beirut" in r["message"]
    route = {"points": [offset(320, 0)], "alt": 20, "speed": 8, "pause": 0, "end": "hover"}
    ok = {**route, "points": [offset(200, 0)]}  # outside the helipad's circle, inside the airport's
    assert "inside no-fly zone “✈ Beirut" in client.post(f"/api/routes/fly?drone={v1}", json=ok).get_json()["error"]
    assert client.post("/api/airspace/zone", json={"id": "ap-OLBA", "enabled": False}).get_json()["ok"]  # authorised
    assert "Hospital Helipad" in client.post(f"/api/routes/fly?drone={v1}", json=route).get_json()["error"]
    assert client.post(f"/api/routes/fly?drone={v1}", json=ok).get_json()["ok"]
    client.post(f"/api/routes/stop?drone={v1}")
    # the drone page still sees only the active zones, and drawing a zone keeps the imported ones
    assert [z["id"] for z in client.get("/api/nofly").get_json()["zones"]] == ["ap-XHEL"]
    sq = [offset(-100, -100), offset(-100, -60), offset(-60, -60)]
    assert client.post("/api/nofly", json={"name": "Neighbour", "points": sq}).get_json()["ok"]
    assert {z["id"] for z in nofly.load_zones(d.NOFLY_FILE)} >= {"ap-OLBA", "ap-XHEL"}
    # re-importing keeps the authorisation
    client.post("/api/airspace/upload", data={"file": (io.BytesIO(CSV.encode()), "airports.csv")})
    assert next(z for z in nofly.load_zones(d.NOFLY_FILE) if z["id"] == "ap-OLBA")["enabled"] is False
    assert client.post("/api/airspace/zone", json={"source": "airport"}, headers={"X-HTTP-Method-Override": "DELETE"}).status_code == 404
    assert client.delete("/api/airspace/zone", json={"source": "airport"}).get_json()["ok"]
    assert [z["name"] for z in nofly.load_zones(d.NOFLY_FILE)] == ["Neighbour"]


# ----- shortest route -----

def test_best_order_shortens_a_zigzag_and_goes_round_zones():
    stops = [offset(0, 100), offset(0, 300), offset(0, 200), offset(0, 400)]
    order, before, after = nofly.best_order([], stops, start=(HOME[0], HOME[1]))
    assert order == [0, 2, 1, 3] and after == pytest.approx(400, rel=0.02) and before > after
    order, before, after = nofly.best_order([], [offset(0, 100), offset(0, 200)], start=(HOME[0], HOME[1]))
    assert order == [0, 1] and before == after
    box = {"id": "z", "name": "Z", "points": [offset(-30, 140), offset(-30, 160), offset(30, 160), offset(30, 140)]}
    assert nofly.path_m([box], (HOME[0], HOME[1] + 0), (offset(0, 300)["lat"], offset(0, 300)["lon"])) > 300
    loop = [offset(0, 100), offset(100, 100), offset(0, 0 + 5), offset(100, 0)]
    order, before, after = nofly.best_order([], loop, start=(HOME[0], HOME[1]), loop=True)
    assert after < before and order[0] == 2  # the circuit starts at the stop nearest home


def test_optimize_api(d, client):
    pts = [offset(0, 100), offset(0, 300), offset(0, 200)]
    r = client.post("/api/routes/optimize", json={"points": pts}).get_json()
    assert r["ok"] and r["after_m"] < r["before_m"] and r["points"][1] == pts[2]
    assert client.post("/api/routes/optimize", json={"points": pts[:2]}).status_code == 400


# ----- radio coverage -----

def test_link_budget_and_terrain():
    assert rf.fspl_db(1000, 2.437e9) == pytest.approx(100.2, abs=0.1)
    flat = rf.path_loss([0.0] * 25, 500, 1.5, 40, 2.437e9)
    assert flat["line_of_sight"] and flat["diffraction_db"] == 0
    hill = [0.0] * 12 + [60.0] + [0.0] * 12  # a 60 m ridge halfway
    blocked = rf.path_loss(hill, 500, 1.5, 40, 2.437e9)
    assert not blocked["line_of_sight"] and blocked["diffraction_db"] > 15
    assert rf.knife_edge_db(-1) == 0 and rf.knife_edge_db(0) == pytest.approx(6.0, abs=0.1)


def test_coverage_with_terrain_and_offline(d, client, tmp_path):
    # a ridge 40 m high running north-south, 250 m east of the controller
    def ridge(cells):
        return [40.0 if 0.0028 < c[1] - round(HOME[1], 3) < 0.0042 else 0.0 for c in cells]
    elev = rf.Elevation(str(tmp_path / "e.json"), fetcher=ridge)
    s = {"controller": {"lat": HOME[0], "lon": HOME[1]}}
    res, terrain = rf.check(s, elev, [(offset(0, 450)["lat"], offset(0, 450)["lon"]), (offset(0, -450)["lat"], offset(0, -450)["lon"])], 10)
    assert terrain and res[0]["terrain_loss_db"] > res[1]["terrain_loss_db"] and not res[0]["line_of_sight"]
    assert res[1]["quality"] == "good" and os.path.exists(tmp_path / "e.json")
    client.post("/api/safety/settings", json={"rf": {"controller": {"lat": HOME[0], "lon": HOME[1]}}})
    r = client.get("/api/rf/coverage?alt=40").get_json()
    assert r["ok"] and not r["terrain"] and len(r["results"]) > 100 and all(x["quality"] == "good" for x in r["results"])
    c = client.post("/api/rf/check", json={"points": [offset(0, 400), offset(300, 0)], "alt": 40}).get_json()
    assert c["ok"] and len(c["results"]) == 3 and "Terrain unknown" in c["summary"]
    weak = client.post("/api/safety/settings", json={"rf": {"sensitivity_dbm": -70}}).get_json()
    assert weak["ok"]
    assert client.post("/api/rf/check", json={"points": [offset(0, 450)], "alt": 40}).get_json()["worst"]["quality"] != "good"


def test_safety_page_and_roles(client):
    assert "Flight Safety" in client.get("/safety").get_data(as_text=True)
    import users
    assert users.allowed("operator", "POST", "/api/routes/optimize") and users.allowed("operator", "POST", "/api/rf/check")
    assert not users.allowed("operator", "POST", "/api/safety/settings") and not users.allowed("operator", "POST", "/api/airspace/zone")
