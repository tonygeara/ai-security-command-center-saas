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
    for href in ("/#history", "/#face-library", "/#vehicle-library", "/license", "/users", "/safety"):
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
