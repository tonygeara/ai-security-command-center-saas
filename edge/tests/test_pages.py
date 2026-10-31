"""Every page loads and its inline JavaScript parses (a syntax error there would break the whole page)."""
import re
import shutil
import subprocess

import pytest

PAGES = ["/", "/drone-control", "/drone-control?drone=drone", "/drone-grid", "/virtual-drones", "/settings", "/license",
         "/setup/add"]
NODE = shutil.which("node")


@pytest.mark.parametrize("url", PAGES)
def test_page_loads_and_scripts_parse(client, url, tmp_path):
    r = client.get(url)
    assert r.status_code == 200, url
    html = r.get_data(as_text=True)
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    if not NODE:
        pytest.skip("node is not installed")
    for i, js in enumerate(scripts):
        f = tmp_path / f"s{i}.js"
        f.write_text(js, encoding="utf-8")
        out = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True)
        assert out.returncode == 0, f"{url} script {i}: {out.stderr[:600]}"


def test_health(client):
    assert client.get("/healthz").get_json()["ok"] is True
