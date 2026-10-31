"""Basic flying with a virtual drone: take off with ↑, land with the button or by holding ↓."""
import time

from conftest import wait_until


def cmd(client, slot, name, args=None):
    return client.post(f"/api/drone/command?drone={slot}", json={"cmd": name, "args": args or {}}).get_json()


def hold(client, slot, z, seconds):
    end = time.time() + seconds
    while time.time() < end:
        client.post(f"/api/drone/stick?drone={slot}", json={"z": z})
        time.sleep(0.1)


def fly_up(d, client, slot):
    assert cmd(client, slot, "control_on", {"speed": 0.3})["ok"]
    hold(client, slot, 1, 4)
    v = d.virtual_drones[slot]
    assert wait_until(lambda: v.flying and v.alt > 2, 10)
    return v


def test_hold_up_takes_off_but_a_tap_does_not(d, client, fleet):
    (v1,) = fleet(1)
    v = d.virtual_drones[v1]
    cmd(client, v1, "control_on", {"speed": 0.3})
    hold(client, v1, 1, 0.3)
    time.sleep(1)
    assert not v.flying
    hold(client, v1, 1, 4)
    assert v.flying and v.alt > 1


def test_land_button_lands_and_stops_motors(d, client, fleet):
    (v1,) = fleet(1)
    v = fly_up(d, client, v1)
    assert cmd(client, v1, "land")["ok"]
    assert wait_until(lambda: not v.flying and not v.motors, 40)


def test_holding_down_near_the_ground_lands(d, client, fleet):
    (v1,) = fleet(1)
    v = fly_up(d, client, v1)
    end = time.time() + 40
    while v.flying and time.time() < end:
        client.post(f"/api/drone/stick?drone={v1}", json={"z": -1})
        time.sleep(0.1)
    assert not v.flying


def test_down_high_up_only_descends(d, client, fleet):
    (v1,) = fleet(1)
    v = fly_up(d, client, v1)
    hold(client, v1, 1, 2)
    a0 = v.alt
    hold(client, v1, -1, 2.5)  # it is still rising for a moment after ↑ is let go
    assert v.flying and v.alt < a0 and v.mode != "AUTO_LANDING"
