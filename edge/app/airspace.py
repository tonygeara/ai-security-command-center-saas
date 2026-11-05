"""Official airspace as automatic no-fly zones.

- Airports and heliports near the site, from OurAirports (public domain, worldwide): a circle around each.
  The radius per type is a cautious default, not the law: check the national rules (in Lebanon, the DGCA) and
  adjust. A zone can be marked "authorised" (switched off) when the site has permission to fly there.
- Airspace polygons from a GeoJSON file: an export from openAIP or the aviation authority. Airspace whose floor is
  above the drones' ceiling is skipped.
"""
import csv
import hashlib
import io
import math

from geo import _distance_m

OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
RADIUS_M = {"large_airport": 8000, "medium_airport": 5000, "small_airport": 3000, "heliport": 1000, "seaplane_base": 2000}
MAX_ZONES = 60
MAX_CORNERS = 40
FT = 0.3048


def circle(lat, lon, radius_m, n=24):
    """A polygon approximating a circle (corners just outside it, so the whole circle is covered)."""
    r = radius_m / math.cos(math.pi / n)
    return [{"lat": round(lat + r * math.cos(2 * math.pi * k / n) / 110540.0, 7),
             "lon": round(lon + r * math.sin(2 * math.pi * k / n) / (111320.0 * math.cos(math.radians(lat))), 7)}
            for k in range(n)]


def airports_near(lines, lat, lon, within_km=30.0, types=tuple(RADIUS_M)):
    """Airports from OurAirports' airports.csv (an iterable of text lines) within within_km, nearest first."""
    out = []
    for row in csv.DictReader(lines):
        t = row.get("type")
        if t not in types:
            continue
        try:
            alat, alon = float(row["latitude_deg"]), float(row["longitude_deg"])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(alat - lat) > within_km / 100 or abs(alon - lon) > within_km / (100 * max(0.1, math.cos(math.radians(lat)))):
            continue  # quick box check before the exact distance
        d = _distance_m(lat, lon, alat, alon)
        if d <= within_km * 1000:
            out.append({"ident": (row.get("ident") or "").strip(), "name": (row.get("name") or "").strip(), "type": t,
                        "lat": alat, "lon": alon, "dist_km": round(d / 1000, 1)})
    return sorted(out, key=lambda a: a["dist_km"])[:MAX_ZONES]


def airport_zones(airports, radius_m=None):
    radius_m = {**RADIUS_M, **(radius_m or {})}
    zones = []
    for a in airports:
        r = float(radius_m.get(a["type"], 3000))
        label = "Heliport" if a["type"] == "heliport" else "Airport"
        zones.append({"id": "ap-" + (a["ident"] or hashlib.sha1(a["name"].encode()).hexdigest()[:8]),
                      "name": f"✈ {a['name'][:28]} ({a['ident']})" if a["ident"] else f"✈ {a['name'][:34]}",
                      "points": circle(a["lat"], a["lon"], r), "source": "airport", "enabled": True,
                      "note": f"{label}, {r / 1000:g} km radius (default; check the national rules)"})
    return zones


def _floor_ft(props):
    """The airspace floor in feet above ground/sea, when the file says (openAIP or simple fields); None = unknown."""
    low = props.get("lowerLimit") or props.get("lower_limit") or props.get("floor")
    if isinstance(low, dict):
        v, unit = low.get("value"), low.get("unit")
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        # openAIP units: 0 metre, 1 feet, 6 flight level
        return v / FT if unit in (0, "m", "M") else v * 100 if unit in (6, "FL") else v
    if isinstance(low, (int, float)):
        return float(low)
    if isinstance(low, str):
        s = low.strip().upper()
        if s in ("GND", "SFC", "0"):
            return 0.0
        if s.startswith("FL"):
            try:
                return float(s[2:]) * 100
            except ValueError:
                return None
        try:
            return float(s.replace("FT", "").replace("AGL", "").replace("MSL", "").strip())
        except ValueError:
            return None
    return None


def _thin(ring):
    """At most MAX_CORNERS corners, evenly picked (zones are checked corner by corner every second)."""
    ring = ring[:-1] if len(ring) > 3 and ring[0] == ring[-1] else ring
    if len(ring) <= MAX_CORNERS:
        return ring
    step = len(ring) / MAX_CORNERS
    return [ring[int(k * step)] for k in range(MAX_CORNERS)]


def geojson_zones(data, near=None, within_km=50.0, max_floor_ft=500.0):
    """No-fly zones from a GeoJSON FeatureCollection of airspace polygons."""
    feats = data.get("features") if isinstance(data, dict) else None
    if feats is None and isinstance(data, dict) and data.get("type") == "Feature":
        feats = [data]
    if not isinstance(feats, list):
        raise ValueError("Not a GeoJSON file with airspace areas.")
    zones, skipped = [], 0
    for f in feats:
        geom, props = (f or {}).get("geometry") or {}, (f or {}).get("properties") or {}
        polys = [geom.get("coordinates")] if geom.get("type") == "Polygon" else \
            geom.get("coordinates") if geom.get("type") == "MultiPolygon" else []
        floor = _floor_ft(props)
        if floor is not None and floor > max_floor_ft:
            skipped += 1
            continue
        name = " ".join(str(props.get("name") or props.get("NAME") or "Airspace").split())[:34]
        for k, poly in enumerate(polys or []):
            try:
                ring = [(float(c[1]), float(c[0])) for c in poly[0]]
            except (TypeError, ValueError, IndexError):
                continue
            ring = _thin(ring)
            if len(ring) < 3:
                continue
            if near and min(_distance_m(near[0], near[1], la, lo) for la, lo in ring) > within_km * 1000 and \
                    not _contains(ring, near):
                continue
            digest = hashlib.sha1(f"{name}{ring[0]}{len(ring)}".encode()).hexdigest()[:10]
            kind = props.get("type") if isinstance(props.get("type"), str) else ""
            zones.append({"id": f"as-{digest}{k or ''}", "name": f"🛇 {name}", "source": "airspace", "enabled": True,
                          "points": [{"lat": la, "lon": lo} for la, lo in ring],
                          "note": "Airspace" + (f" ({kind})" if kind else "") + (f", from {floor:.0f} ft" if floor else ", from the ground")})
    return zones[:MAX_ZONES], skipped


def _contains(ring, p):
    hit = False
    for i in range(len(ring)):
        (y1, x1), (y2, x2) = ring[i], ring[i - 1]
        if (y1 > p[0]) != (y2 > p[0]) and p[1] < (x2 - x1) * (p[0] - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def text_lines(data):
    """Bytes of a CSV upload as text lines."""
    return io.StringIO(data.decode("utf-8-sig", errors="replace"))
