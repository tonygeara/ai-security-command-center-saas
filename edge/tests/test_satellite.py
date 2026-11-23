"""Satellite tab: pins saved on the PC, NASA FIRMS fire alerts near them (the key never reaches the browser)."""
import pytest

CSV = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
       "33.95,35.55,330.1,0.4,0.4,2026-11-21,1112,N20,VIIRS,n,2.0NRT,290.1,4.2,D\n"     # ~6 km from the pin
       "34.80,36.40,331.0,0.4,0.4,2026-11-21,1113,N20,VIIRS,h,2.0NRT,291.0,9.9,D\n")    # ~125 km: outside 50 km
PIN = {"name": "Beirut site", "lat": 33.9, "lon": 35.5}


@pytest.fixture
def sat(d):
    import os
    for f in (d.SATELLITE_PINS_FILE, d.FIRMS_KEY_FILE):
        if os.path.exists(f):
            os.remove(f)
    d.satellite_mod._cache.clear()
    yield d.satellite_mod
    for f in (d.SATELLITE_PINS_FILE, d.FIRMS_KEY_FILE):
        if os.path.exists(f):
            os.remove(f)


def test_page_and_nav(d, client):
    html = client.get("/satellite").get_data(as_text=True)
    assert "gibs.earthdata.nasa.gov" in html and 'href="/satellite"' in html
    assert 'href="/satellite"' in client.get("/drone-control").get_data(as_text=True)  # in the top bar everywhere


def test_pins_saved_and_checked(d, client, sat):
    r = client.post("/api/satellite/pins", json={"pins": [PIN, {**PIN, "name": "Farm", "layer": "fires", "sat": "modis", "days_ago": 99}]}).get_json()
    assert r["ok"] and len(r["pins"]) == 2 and all(len(p["id"]) == 12 for p in r["pins"])
    farm = r["pins"][1]
    assert farm["layer"] == "fires" and farm["sat"] == "modis" and farm["days_ago"] == 30  # clamped
    got = client.get("/api/satellite/pins").get_json()["pins"]
    assert [p["name"] for p in got] == ["Beirut site", "Farm"]
    assert client.post("/api/satellite/pins", json={"pins": [{**PIN, "lat": 123}]}).status_code == 400
    assert client.post("/api/satellite/pins", json={"pins": [{**PIN, "name": " "}]}).status_code == 400
    assert client.get("/api/satellite/pins").get_json()["pins"][0]["name"] == "Beirut site"  # a refused save changes nothing


def test_fires_near_pins_key_stays_on_the_pc(d, client, sat, monkeypatch):
    client.post("/api/satellite/pins", json={"pins": [PIN]})
    assert client.get("/api/satellite/fires").get_json() == {"ok": True, "key_set": False, "fires": {}, "error": ""}
    assert client.post("/api/satellite/firms-key", json={"key": "bad key!"}).status_code == 400
    key = "a" * 32
    assert client.post("/api/satellite/firms-key", json={"key": key}).get_json()["key_set"]
    urls = []
    monkeypatch.setattr(d, "_firms_get", lambda url, timeout: (urls.append(url), (200, CSV))[1])
    r = client.get("/api/satellite/fires?days=2").get_json()
    assert r["ok"] and r["key_set"] and key not in str(r)
    (fires,) = r["fires"].values()
    assert len(fires) == 1 and fires[0]["km"] < 10 and fires[0]["frp"] == 4.2
    assert "/VIIRS_NOAA20_NRT/" in urls[0] and urls[0].endswith("/2")
    client.get("/api/satellite/fires?days=2")
    assert len(urls) == 1  # cached for 10 minutes
    monkeypatch.setattr(d, "_firms_get", lambda url, timeout: (400, "Invalid MAP_KEY."))
    sat._cache.clear()
    r = client.get("/api/satellite/fires").get_json()
    assert not r["ok"] and "not valid" in r["error"]
    assert client.post("/api/satellite/firms-key", json={"key": ""}).get_json()["key_set"] is False


def test_who_may_change_it():
    import users
    assert users.allowed("operator", "POST", "/api/satellite/pins")
    assert not users.allowed("viewer", "POST", "/api/satellite/pins")
    assert not users.allowed("operator", "POST", "/api/satellite/firms-key")  # the key: admins only
    assert users.allowed("viewer", "GET", "/satellite")


WINDY = {"total": 2, "webcams": [
    {"webcamId": 1700000001, "title": "Beirut: Corniche", "status": "active", "lastUpdatedOn": "2026-11-22T10:00:00.000Z",
     "location": {"latitude": 33.9, "longitude": 35.48, "city": "Beirut", "country": "Lebanon"},
     "images": {"current": {"icon": "https://imgproxy.windy.com/i.jpg", "thumbnail": "https://imgproxy.windy.com/t.jpg"},
                "sizes": {"icon": {"width": 48}, "thumbnail": {"width": 200}}},
     "player": {"live": "https://webcams.windy.com/webcams/public/embed/player/1700000001/live", "day": "https://webcams.windy.com/d"},
     "urls": {"detail": "https://www.windy.com/webcams/1700000001"}},
    {"webcamId": 1700000002, "title": "Old cam", "status": "inactive", "location": {"latitude": 34, "longitude": 35.6}},
    {"webcamId": 1700000003, "title": "No place", "status": "active", "location": {}},
]}


def test_public_webcams_key_stays_on_the_pc(d, client, sat, monkeypatch):
    import os
    if os.path.exists(d.WINDY_KEY_FILE):
        os.remove(d.WINDY_KEY_FILE)
    sat._cam_cache.clear()
    assert client.get("/api/satellite/webcams?bbox=34.5,36,33.5,35").get_json()["key_set"] is False
    key = "w" * 32
    assert client.post("/api/satellite/windy-key", json={"key": key}).get_json()["key_set"]
    calls = []
    monkeypatch.setattr(d, "_windy_get", lambda url, params, headers, timeout: (calls.append((params, headers)), (200, WINDY))[1])
    r = client.get("/api/satellite/webcams?bbox=34.5,36,33.5,35").get_json()
    assert r["ok"] and key not in str(r)
    (cam,) = r["webcams"]  # the inactive one and the one with no position are left out
    assert cam["title"] == "Beirut: Corniche" and cam["live"].endswith("/live") and cam["image"].endswith("/t.jpg")  # largest picture
    assert cam["page"] == "https://www.windy.com/webcams/1700000001"
    assert calls[0][0]["bbox"] == "34.5,36.0,33.5,35.0" and calls[0][1]["x-windy-api-key"] == key
    client.get("/api/satellite/webcams?bbox=34.5,36,33.5,35")
    assert len(calls) == 1  # cached (picture links expire after ~10 minutes, so 5 at most)
    assert client.get("/api/satellite/webcams?bbox=1,2,3").status_code == 400
    assert client.get("/api/satellite/webcams?bbox=10,2,20,1").status_code == 400  # south above north
    monkeypatch.setattr(d, "_windy_get", lambda *a: (401, {"message": "bad key"}))
    sat._cam_cache.clear()
    assert "refused the key" in client.get("/api/satellite/webcams?bbox=34.5,36,33.5,35").get_json()["error"]
    import users
    assert not users.allowed("operator", "POST", "/api/satellite/windy-key")  # admins only
    assert users.allowed("viewer", "GET", "/api/satellite/webcams")
    os.remove(d.WINDY_KEY_FILE)
