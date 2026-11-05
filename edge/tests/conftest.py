"""Shared test setup: one sandboxed dashboard (own data folder, own drone-link port) plus virtual drones.

Run from the edge folder:  .venv-build\\Scripts\\python.exe -m pytest tests
Nothing here touches the installed app, its data, Frigate or Telegram.
"""
import os
import socket
import sys
import time

import pytest

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
HOME = (45.5048, -75.6636)  # where virtual drones take off
M = 1 / 111000.0  # about one metre of latitude, in degrees


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(fn, timeout=30.0, step=0.25):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


def offset(north_m, east_m, origin=HOME):
    """A point north_m / east_m metres from origin, as {"lat", "lon"}."""
    import math
    return {"lat": origin[0] + north_m * M, "lon": origin[1] + east_m * M / math.cos(math.radians(origin[0]))}


@pytest.fixture(scope="session")
def d(tmp_path_factory):
    home = tmp_path_factory.mktemp("ai_home")
    os.makedirs(home / "data", exist_ok=True)
    os.environ["AI_SECURITY_HOME"] = str(home)
    os.environ["AI_SECURITY_DATA"] = str(home / "data")
    sys.path.insert(0, APP)
    import dashboard
    dashboard.DRONE_LINK_PORT = _free_port()
    dashboard._frigate_camera_names = lambda: ["front", "drone"]
    dashboard.onprem_mode = lambda: True
    dashboard.drone_control_allowed = lambda: True
    dashboard._sources_over_limit = lambda names=None: set()
    dashboard.telegram_ready = lambda cfg=None: True
    dashboard.sent = []
    dashboard.send_telegram = lambda text, *a, **k: dashboard.sent.append(text) or {"ok": True}
    # No internet in tests: weather, air traffic and terrain are "unknown" unless a test supplies them.
    dashboard._weather_fetch = lambda lat, lon: None
    dashboard._traffic_fetch = lambda settings, lat, lon: None

    def _no_terrain(cells):
        raise OSError("offline")
    dashboard._elevation_fetch = _no_terrain
    dashboard.start_drone_link()
    # Only the background workers the drone tests need (not the Telegram poller).
    import threading
    for worker in (dashboard._drone_response_worker, dashboard._nofly_watch_worker):
        threading.Thread(target=worker, daemon=True).start()
    time.sleep(0.3)
    return dashboard


@pytest.fixture
def client(d):
    return d.app.test_client()


@pytest.fixture
def fleet(d, client):
    """fleet(n) adds n linked virtual drones a few metres apart; everything is cleaned up afterwards."""
    added = []

    def make(n=1):
        for k in range(n):
            p = offset(k * 3, 0)
            r = client.post("/api/virtual-drones", json={"lat": p["lat"], "lon": p["lon"]}).get_json()
            assert r.get("ok") is not False, r
        slots = sorted(d.virtual_drones)
        added.extend(slots)
        assert wait_until(lambda: all(d.get_link(s)["conn"] is not None and d.get_link(s)["telemetry"].get("lat") for s in slots), 15)
        return slots

    yield make
    for r in list(d.route_runs.values()):
        r["stop"] = True
    d.drone_response.update(active=False, phase="", routing=False)
    for slot in list(d.virtual_drones):
        client.delete(f"/api/virtual-drones/{slot}")
    wait_until(lambda: not any(r["active"] for r in d.route_runs.values()), 10)
    wait_until(lambda: all("report" in r for r in d.route_runs.values()), 10)  # reports are sent just after a run ends
    d.route_runs.clear()
    d.nofly.save_zones(d.NOFLY_FILE, [])
    d.sent.clear()
    time.sleep(0.5)


def square(centre, half_m, name="Zone"):
    """A square no-fly zone half_m metres each side of centre ({"lat", "lon"})."""
    c = (centre["lat"], centre["lon"])
    return {"name": name, "points": [offset(-half_m, -half_m, c), offset(-half_m, half_m, c), offset(half_m, half_m, c), offset(half_m, -half_m, c)]}
