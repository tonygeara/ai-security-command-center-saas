"""Auto-send the nearest ready drone when a camera sees someone at night."""
import time

from conftest import offset, wait_until


def setup(d, client, on=True, start="00:00", end="00:00", **extra):
    d._virtual_cfg["demo_auto"] = True  # automatic picks may use virtual drones
    cam = offset(40, 60)
    client.post("/api/response/settings", json={"camera_locations": {"front": cam}, "min_battery": 20, "hover_seconds": 10,
                                                "auto_dispatch": on, "auto_from": start, "auto_to": end, "auto_cooldown_min": 5, **extra})
    d._auto_last.clear()
    d._auto_seen.clear()
    return cam


def test_in_window(d):
    assert d._in_window("19:00", "06:00", "23:30") and d._in_window("19:00", "06:00", "02:00")
    assert not d._in_window("19:00", "06:00", "12:00")
    assert d._in_window("08:00", "17:00", "09:00") and not d._in_window("08:00", "17:00", "18:00")
    assert d._in_window("00:00", "00:00", "13:37")


def test_nearest_ready_drone_is_sent(d, client, fleet):
    v1, v2 = fleet(2)
    # Move drone 2 next to the camera (it is the nearest even though drone 1 comes first in the list).
    cam = setup(d, client)
    near = offset(40, 50)
    d.virtual_drones[v2].lat, d.virtual_drones[v2].lon = near["lat"], near["lon"]
    assert wait_until(lambda: abs(d.get_link(v2)["telemetry"].get("lat", 0) - near["lat"]) < 1e-6, 5)
    r = d.auto_dispatch_check("front", "person", "obj1")
    assert r and r["ok"], r
    assert d.drone_response["drone"] == v2 and d.drone_response["active"]
    assert any("nearest ready drone" in t for t in d.sent)
    # The same object, or a second sighting while a drone is responding, sends nothing more.
    assert d.auto_dispatch_check("front", "person", "obj1") is None
    assert d.auto_dispatch_check("front", "car", "obj2") is None
    d.recall_drone("test")


def test_not_sent_when_off_outside_hours_or_cooldown(d, client, fleet):
    fleet(1)
    setup(d, client, on=False)
    assert d.auto_dispatch_check("front", "person", "a") is None
    now = time.localtime()
    later = f"{(now.tm_hour + 2) % 24:02d}:00"
    setup(d, client, start=later, end=f"{(now.tm_hour + 3) % 24:02d}:00")
    assert d.auto_dispatch_check("front", "person", "b") is None
    setup(d, client, auto_vehicle=False)
    assert d.auto_dispatch_check("front", "car", "c") is None
    assert d.auto_dispatch_check("front", "dog", "c2") is None
    assert d.auto_dispatch_check("back", "person", "d") is None  # camera without a map location
    setup(d, client)
    d._auto_last["front"] = time.time()  # sent a minute ago: cooldown
    assert d.auto_dispatch_check("front", "person", "e") is None
    assert not d.drone_response["active"]


def test_telegram_send_drone_button_uses_nearest(d, client, fleet):
    v1, v2 = fleet(2)
    setup(d, client, on=False)
    near = offset(40, 50)
    d.virtual_drones[v2].lat, d.virtual_drones[v2].lon = near["lat"], near["lon"]
    assert wait_until(lambda: abs(d.get_link(v2)["telemetry"].get("lat", 0) - near["lat"]) < 1e-6, 5)
    r = d.dispatch_drone("front", by="telegram")
    assert r["ok"] and r["drone"] == v2
    d.recall_drone("test")
