"""No-fly zone geometry (no drones needed)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import nofly  # noqa: E402
from conftest import HOME, offset, square  # noqa: E402

ZONE = nofly.clean_zone({**square(offset(100, 0), 20, "Neighbour"), "id": "z1"})
ZONES = [ZONE]
START = HOME
FAR = (offset(200, 0)["lat"], offset(200, 0)["lon"])


def test_inside_and_outside():
    c = offset(100, 0)
    assert nofly.zone_at(ZONES, c["lat"], c["lon"])["name"] == "Neighbour"
    assert nofly.zone_at(ZONES, *START) is None


def test_leg_through_zone_is_found():
    assert nofly.leg_zone(ZONES, START, FAR)["id"] == "z1"
    side = offset(0, 100)
    assert nofly.leg_zone(ZONES, START, (side["lat"], side["lon"])) is None


def test_detour_goes_round():
    via = nofly.detour(ZONES, START, FAR)
    assert via, "expected turning points"
    path = [START] + via + [FAR]
    assert all(nofly.leg_zone(ZONES, a, b) is None for a, b in zip(path, path[1:]))


def test_detour_clear_line_and_target_inside():
    side = offset(0, 100)
    assert nofly.detour(ZONES, START, (side["lat"], side["lon"])) == []
    c = offset(100, 0)
    assert nofly.detour(ZONES, START, (c["lat"], c["lon"])) is None


def test_detour_lets_a_drone_inside_fly_out():
    c = offset(100, 0)
    assert nofly.detour(ZONES, (c["lat"], c["lon"]), START) == []


def test_route_problem_messages():
    a, b = offset(0, 10), offset(200, 10)
    assert "crosses no-fly zone" in nofly.route_problem(ZONES, [a, b])
    assert "inside no-fly zone" in nofly.route_problem(ZONES, [offset(100, 0)])
    assert nofly.route_problem(ZONES, [offset(0, 60), offset(10, 60)]) == ""
    # The closing leg of a repeating route and the way home are checked too.
    loop = [offset(80, -60), offset(130, -60), offset(130, 60)]
    assert nofly.route_problem(ZONES, loop) == ""
    assert "crosses" in nofly.route_problem(ZONES, [offset(150, 0)], home=START, end_home=True)


def test_clean_zone_needs_three_corners():
    import pytest
    with pytest.raises(ValueError):
        nofly.clean_zone({"points": [offset(0, 0), offset(1, 1)]})
