"""Every page loads and its inline JavaScript parses (a syntax error there would break the whole page)."""
import re
import shutil
import subprocess

import pytest

PAGES = ["/", "/drone-control", "/drone-control?drone=drone", "/drone-grid", "/virtual-drones", "/maps", "/maps-embed", "/safety", "/settings", "/license",
         "/setup/add"]
NODE = shutil.which("node")


@pytest.mark.parametrize("url", PAGES)
def test_page_loads_and_scripts_parse(client, url, tmp_path):
    r = client.get(url)
    assert r.status_code == 200, url
    html = r.get_data(as_text=True)
    scripts = re.findall(r"<script(?![^>]*\b(?:src=|type=\"importmap\"))[^>]*>(.*?)</script>", html, re.S)
    if not NODE:
        pytest.skip("node is not installed")
    for i, js in enumerate(scripts):
        f = tmp_path / f"s{i}.js"
        f.write_text(js, encoding="utf-8")
        out = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True)
        assert out.returncode == 0, f"{url} script {i}: {out.stderr[:600]}"


def test_health(client):
    assert client.get("/healthz").get_json()["ok"] is True


def test_top_bar_and_settings_hub(client):
    html = client.get("/settings").get_data(as_text=True)
    nav = html[html.index('<nav class="hud-nav">'):html.index("</nav>", html.index('<nav class="hud-nav">'))]
    assert [t for t in ("Dashboard", "Drone", "Virtual drones", "Devices", "Settings") if t in nav] == \
        ["Dashboard", "Drone", "Virtual drones", "Devices", "Settings"]
    assert "3D Maps" not in nav and "Flight safety" not in nav and "License" not in nav and "Users" not in nav
    for href in ("/settings/events", "/settings/people", "/settings/vehicles", "/license", "/users", "/safety"):
        assert f'href="{href}"' in html
    assert 'class="active"><span class="ico">⚙' in client.get("/license").get_data(as_text=True)  # Settings lit
    drone = client.get("/drone-control").get_data(as_text=True)
    assert 'id="fsStrip"' in drone and 'id="m3dOn"' in drone and 'id="l4dOn"' in drone


def test_dashboard_camera_feed_follows_the_setting(d, client):
    saved = d._load_customer_settings()
    try:
        client.post("/api/customer/settings", json={**saved, "dashboard_camera_feed": False})
        html = client.get("/").get_data(as_text=True)
        assert '<div id="cameraFeedPanel" hidden' in html and 'data-feed-switch="main"' not in html
        client.post("/api/customer/settings", json={**saved, "dashboard_camera_feed": True})
        html = client.get("/").get_data(as_text=True)
        assert '<div id="cameraFeedPanel">' in html and 'data-feed-switch="main"' in html
    finally:
        client.post("/api/customer/settings", json=saved)


def test_settings_pages_for_events_people_vehicles(client):
    for key, title in (("events", "Events"), ("people", "People"), ("vehicles", "Vehicles")):
        r = client.get(f"/settings/{key}")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert f"<h1>{title}</h1>" in html and "window.attachLiveCamera = attach" not in html  # no live player here
    assert client.get("/settings/nothing").status_code == 302
    dash = client.get("/").get_data(as_text=True)
    assert "#historyPanel,#openFaceEnroll" in dash  # moved off the dashboard
    hub = client.get("/settings").get_data(as_text=True)
    assert 'href="/settings/events"' in hub and 'href="/settings/people"' in hub and 'href="/settings/vehicles"' in hub


def test_geocode_and_map_search_script(d, client, tmp_path):
    calls = []
    d._geocode_fetch = lambda q: calls.append(q) or [{"name": "Hamra Street, Beirut", "lat": 33.8963, "lon": 35.4823}]
    try:
        r = client.get("/api/geocode?q=Hamra Beirut").get_json()
        assert r["ok"] and r["results"][0]["lat"] == 33.8963
        client.get("/api/geocode?q=hamra   beirut")
        assert len(calls) == 1  # cached
        assert client.get("/api/geocode?q=ab").status_code == 400

        def offline(q):
            raise OSError("no internet")
        d._geocode_fetch = offline
        assert "needs internet" in client.get("/api/geocode?q=Somewhere else").get_json()["error"]
    finally:
        d._geocode_cache.clear()
    js = client.get("/mapsearch.js")
    assert js.status_code == 200 and "addMapSearch" in js.get_data(as_text=True)
    for page in ("/drone-control", "/safety", "/maps", "/virtual-drones"):
        assert '<script src="/mapsearch.js"></script>' in client.get(page).get_data(as_text=True)
    if NODE:
        f = tmp_path / "mapsearch.js"
        f.write_text(js.get_data(as_text=True), encoding="utf-8")
        out = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
