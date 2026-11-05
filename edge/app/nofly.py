"""No-fly zones: areas drawn on the map that drones must never enter.

Zones are polygons stored as {"id", "name", "points": [{"lat", "lon"}, ...]}. The geometry works in metres on a
flat local projection, which is accurate enough for a site a few kilometres across.
"""
import heapq
import json
import math
import os
import time

MARGIN_M = 15.0  # detours keep this far outside a zone's corners
SAMPLE_M = 2.0  # legs are also checked point by point at this spacing


def _ref(points):
    return points[0][0], points[0][1]


def _xy(lat, lon, ref):
    return ((lon - ref[1]) * 111320.0 * math.cos(math.radians(ref[0])), (lat - ref[0]) * 110540.0)


def _ll(x, y, ref):
    return ref[0] + y / 110540.0, ref[1] + x / (111320.0 * math.cos(math.radians(ref[0])))


def _inside(poly, p):
    x, y, hit = p[0], p[1], False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def _cross(a, b, c, d):
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0


def _hits(poly, a, b):
    """Does the straight leg a→b enter the polygon (all in metres)?"""
    if _inside(poly, a) or _inside(poly, b):
        return True
    if any(_cross(a, b, poly[i], poly[i - 1]) for i in range(len(poly))):
        return True
    n = int(math.hypot(b[0] - a[0], b[1] - a[1]) / SAMPLE_M)
    return any(_inside(poly, (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)) for k in range(1, n))


def _grow(poly, m):
    """The polygon with each corner pushed m metres outward from its centre."""
    cx, cy = sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)
    out = []
    for x, y in poly:
        d = math.hypot(x - cx, y - cy) or 1.0
        out.append((x + (x - cx) / d * m, y + (y - cy) / d * m))
    return out


def clean_zone(z):
    pts = [{"lat": float(p["lat"]), "lon": float(p["lon"])} for p in (z.get("points") or [])
           if -90 <= float(p["lat"]) <= 90 and -180 <= float(p["lon"]) <= 180][:40]
    if len(pts) < 3:
        raise ValueError("A no-fly zone needs at least 3 corners")
    name = " ".join(str(z.get("name") or "").split())[:40] or "No-fly zone"
    out = {"id": str(z.get("id") or f"z{int(time.time() * 1000)}"), "name": name, "points": pts}
    # Imported official airspace ("airport", "airspace") can be switched off where the site is authorised to fly.
    if z.get("source") in ("airport", "airspace"):
        out.update(source=z["source"], enabled=z.get("enabled", True) is not False, note=str(z.get("note") or "")[:120])
    return out


def active(zones):
    """The zones drones must keep out of (imported airspace marked as authorised is left out)."""
    return [z for z in zones if z.get("enabled", True) is not False]


def load_zones(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [z for z in data if isinstance(z, dict) and len(z.get("points") or []) >= 3] if isinstance(data, list) else []
    except (FileNotFoundError, ValueError):
        return []


def save_zones(path, zones):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(zones, f, indent=2)
    os.replace(tmp, path)


def _poly(zone, ref):
    return [_xy(p["lat"], p["lon"], ref) for p in zone["points"]]


def zone_at(zones, lat, lon):
    """The zone containing this point, or None."""
    for z in zones:
        if _inside(_poly(z, (lat, lon)), (0.0, 0.0)):
            return z
    return None


def leg_zone(zones, a, b, skip=()):
    """The first zone the straight leg a→b (each (lat, lon)) enters, or None. Zones whose id is in skip are ignored."""
    ref = a
    pa, pb = _xy(a[0], a[1], ref), _xy(b[0], b[1], ref)
    for z in zones:
        if z["id"] not in skip and _hits(_poly(z, ref), pa, pb):
            return z
    return None


def route_problem(zones, stops, loop=False, home=None, end_home=False):
    """Why a drawn route breaks a no-fly zone ('' = fine). stops are {"lat", "lon"} dicts."""
    for i, p in enumerate(stops, 1):
        z = zone_at(zones, p["lat"], p["lon"])
        if z:
            return f"Stop {i} is inside no-fly zone “{z['name']}”."
    legs = [(i, i + 1) for i in range(1, len(stops))]
    if loop and len(stops) > 2:
        legs.append((len(stops), 1))
    for i, j in legs:
        z = leg_zone(zones, (stops[i - 1]["lat"], stops[i - 1]["lon"]), (stops[j - 1]["lat"], stops[j - 1]["lon"]))
        if z:
            return f"The leg from stop {i} to stop {j} crosses no-fly zone “{z['name']}”."
    if home and end_home and stops:
        last = stops[-1]
        z = leg_zone(zones, (last["lat"], last["lon"]), home)
        if z:
            return f"The way home from the last stop crosses no-fly zone “{z['name']}”. End the route somewhere else, or hover/land at the end."
    return ""


def detour(zones, start, end):
    """Waypoints (lat, lon) to fly from start to end around the zones: [] when the straight line is clear,
    None when there is no way round (or the target itself is inside a zone). A zone the drone is already
    inside is ignored so it can always fly out."""
    if zone_at(zones, end[0], end[1]):
        return None
    skip = {z["id"] for z in zones if zone_at([z], start[0], start[1])}
    if not leg_zone(zones, start, end, skip):
        return []
    ref = start
    nodes = [_xy(start[0], start[1], ref), _xy(end[0], end[1], ref)]
    polys = []
    for z in zones:
        if z["id"] in skip:
            continue
        poly = _poly(z, ref)
        nodes.extend(_grow(poly, MARGIN_M))  # turning points well outside each corner
        # Legs keep clear of the zone by half the margin too (a drone cuts corners a little),
        # unless the start or end itself is in that strip.
        wide = _grow(poly, MARGIN_M / 2)
        polys.append(poly if _inside(wide, nodes[0]) or _inside(wide, nodes[1]) else wide)
    ok = lambda a, b: not any(_hits(p, a, b) for p in polys)
    best, prev, todo = {0: 0.0}, {}, [(0.0, 0)]
    while todo:
        cost, i = heapq.heappop(todo)
        if i == 1:
            break
        if cost > best.get(i, math.inf):
            continue
        for j in range(len(nodes)):
            if j == i or (j > 1 and any(_inside(p, nodes[j]) for p in polys)):
                continue
            c = cost + math.hypot(nodes[j][0] - nodes[i][0], nodes[j][1] - nodes[i][1])
            if c < best.get(j, math.inf) and ok(nodes[i], nodes[j]):
                best[j], prev[j] = c, i
                heapq.heappush(todo, (c, j))
    if 1 not in prev:
        return None
    path, k = [], prev[1]
    while k != 0:
        path.append(_ll(nodes[k][0], nodes[k][1], ref))
        k = prev[k]
    return list(reversed(path))


def path_m(zones, a, b):
    """Flying distance a → b (each (lat, lon)) going round the zones; inf when there is no way."""
    via = detour(zones, a, b)
    if via is None:
        return math.inf
    pts = [a] + via + [b]
    return sum(math.hypot(*_xy(q[0], q[1], p)) for p, q in zip(pts, pts[1:]))


def best_order(zones, stops, start=None, loop=False):
    """The order of stops that flies the shortest distance (round the zones), starting from start (the home point).

    loop: the route repeats, so it is a closed circuit. Nearest-neighbour first, then 2-opt improvement: for the
    25 stops a route can have this is fast and within a few percent of the best possible.
    Returns (order as indexes into stops, metres before, metres after).
    """
    pts = [(p["lat"], p["lon"]) for p in stops]
    n = len(pts)
    nodes = pts + ([start] if start else [])
    s = n if start else None
    dist = [[0.0 if i == j else path_m(zones, nodes[i], nodes[j]) for j in range(len(nodes))] for i in range(len(nodes))]

    def length(order):
        seq = ([s] if s is not None else []) + order + ([order[0]] if loop and order else [])
        return sum(dist[i][j] for i, j in zip(seq, seq[1:]))

    original = list(range(n))
    if n < 3 and not (n == 2 and start):
        return original, length(original), length(original)
    # nearest neighbour from the start (or from the first stop)
    left, order = set(range(n)), []
    cur = s if s is not None else 0
    if s is None:
        order.append(0)
        left.discard(0)
    while left:
        cur = min(left, key=lambda j: dist[cur][j])
        order.append(cur)
        left.discard(cur)
    best = length(order)
    improved = True
    while improved:
        improved = False
        for i in range(0, n - 1):
            for k in range(i + 1, n):
                cand = order[:i] + order[i:k + 1][::-1] + order[k + 1:]
                c = length(cand)
                if c < best - 0.01:
                    order, best, improved = cand, c, True
    if loop and s is not None:  # a circuit: start at the stop nearest home, keep the direction
        first = min(range(n), key=lambda k: dist[s][order[k]])
        order = order[first:] + order[:first]
        best = length(order)
    before = length(original)
    if best >= before:
        return original, before, before
    return order, before, best
