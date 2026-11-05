"""4D live: drones in 3D over the site, live; and 3D site maps placed where they were flown."""
import io
import os
import shutil
import subprocess
import sys
import zipfile

import pytest

from conftest import APP, HOME, offset, wait_until

sys.path.insert(0, APP)
import geo  # noqa: E402
import mapping  # noqa: E402


def test_utm_round_trip_and_known_points():
    assert geo.latlon_to_utm(0, 33)[:3] == (500000.0, 0.0, 36)
    for lat, lon in [(33.8547, 35.49), (45.5048, -75.6636), (-33.9, 18.4), (60.17, 24.94)]:
        e, n, z, north = geo.latlon_to_utm(lat, lon)
        assert geo.utm_to_latlon(e, n, z, north) == pytest.approx((lat, lon), abs=1e-7)
    e, n, z, _ = geo.latlon_to_utm(*HOME)
    assert z == 18 and 440000 < e < 460000 and 5030000 < n < 5050000  # Ottawa


def test_model_origin_from_the_engine_files(tmp_path):
    e, n, _, _ = geo.latlon_to_utm(*HOME)
    o = mapping.model_origin(f"WGS84 UTM 18N\n{e:.3f} {n:.3f}\n")
    assert (o["lat"], o["lon"]) == pytest.approx(HOME, abs=1e-6) and o["utm_zone"] == "18N"
    assert mapping.model_origin(f"odd header\n{e} {n}\n", "+proj=utm +zone=18 +datum=WGS84 +units=m") ["utm_zone"] == "18N"
    assert mapping.model_origin("") is None and mapping.model_origin("WGS84 UTM 99N\n1 2") is None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("odm_texturing/odm_textured_model_geo.obj", "v 0 0 0\n")
        z.writestr("odm_georeferencing/coords.txt", f"WGS84 UTM 18N\n{e} {n}\n")
    (tmp_path / "all.zip").write_bytes(buf.getvalue())
    found = mapping.extract_results(str(tmp_path / "all.zip"), str(tmp_path / "r"))
    assert found["origin"]["lat"] == pytest.approx(HOME[0], abs=1e-6)


def test_live_view_shows_drones_trails_routes_and_site_map(d, client, fleet):
    v1, v2 = fleet(2)
    route = {"points": [offset(30, 0), offset(30, 30)], "alt": 20, "speed": 8, "pause": 0, "loop": True}
    assert client.post(f"/api/routes/fly?drone={v1}", json=route).get_json()["ok"]
    assert wait_until(lambda: d.virtual_drones[v1].alt > 10, 40)
    for _ in range(6):  # the trail worker runs once a second in the app
        d.record_trails()
        wait_until(lambda: False, 1.0)
    # a finished site map near the drones is placed in the scene
    s = mapping.create(d.MAPS_DIR, "Yard", [offset(0, 0), offset(0, 40), offset(40, 40), offset(40, 0)])
    mapping.update(d.MAPS_DIR, s["id"], status="ready", result={"model": "m.obj", "origin": {"lat": HOME[0], "lon": HOME[1]}})
    r = client.get(f"/api/live4d?drone={v1}").get_json()
    assert r["ok"] and r["centre"]["lat"] == pytest.approx(HOME[0], abs=1e-3)
    one = next(x for x in r["drones"] if x["slot"] == v1)
    two = next(x for x in r["drones"] if x["slot"] == v2)
    assert one["flying"] and one["altitude"] > 10 and one["mission"] == "route" and one["home"]
    assert len(one["trail"]) >= 2 and one["route"]["alt"] == 20 and len(one["route"]["points"]) == 2
    assert not two["flying"] and two["trail"] == [] and two["route"] is None
    assert r["maps"][0]["id"] == s["id"] and r["maps"][0]["origin"]["lat"] == HOME[0]
    client.post(f"/api/routes/stop?drone={v1}")
    mapping.delete(d.MAPS_DIR, s["id"])


def test_drone_page_has_the_switch_and_the_script_parses(client, tmp_path):
    page = client.get("/drone-control").get_data(as_text=True)
    assert 'id="l4dOn"' in page and '"three":"/vendor/three/three.module.min.js"' in page
    js = client.get("/live4d.js")
    assert js.status_code == 200 and js.mimetype == "text/javascript" and "export function start" in js.get_data(as_text=True)
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    f = tmp_path / "live4d.mjs"
    f.write_text(js.get_data(as_text=True), encoding="utf-8")
    out = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
