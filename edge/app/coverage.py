"""Camera coverage: what each camera sees on the ground, where nobody looks, and where to add one.

Each located camera has a view: the compass direction it points (heading, degrees from north), how
wide it sees (fov, degrees) and how far it usefully sees a person (range, metres). Its coverage is
that slice of a circle on the ground. This is geometry only: walls, trees and hills in the way are
not taken into account, so a "covered" spot behind a wall may still be blind in reality.

The site is the outline the owner draws (or, without one, the area round the cameras). It is cut
into small squares; each square is covered by 0, 1, 2… cameras. Squares with 0 are blind spots.

Also used by the drone handoff: where a person or vehicle probably went when it left a camera's view.
"""
import math

M_LAT = 111320.0
DEFAULT_VIEW = {"heading": 0.0, "fov": 90.0, "range": 30.0}
MAX_CELLS = 6400  # grid size limit (about 80 × 80)


def clean_view(v):
    v = v if isinstance(v, dict) else {}
    out = {}
    for k, lo, hi in (("heading", 0, 360), ("fov", 10, 180), ("range", 3, 300)):
        try:
            x = float(v.get(k, DEFAULT_VIEW[k]))
        except (TypeError, ValueError):
            x = DEFAULT_VIEW[k]
        out[k] = x % 360 if k == "heading" else max(lo, min(hi, x))
    return out


class Frame:
    """Flat metres east (x) / north (y) round a centre point."""

    def __init__(self, lat, lon):
        self.lat0, self.lon0 = lat, lon
        self.m_lon = M_LAT * math.cos(math.radians(lat))

    def xy(self, lat, lon):
        return (lon - self.lon0) * self.m_lon, (lat - self.lat0) * M_LAT

    def ll(self, x, y):
        return self.lat0 + y / M_LAT, self.lon0 + x / self.m_lon


def bearing_deg(dx, dy):
    return math.degrees(math.atan2(dx, dy)) % 360


def angle_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def sees(cam_xy, view, x, y):
    dx, dy = x - cam_xy[0], y - cam_xy[1]
    d = math.hypot(dx, dy)
    if d > view["range"]:
        return False
    return d < 0.5 or angle_diff(bearing_deg(dx, dy), view["heading"]) <= view["fov"] / 2


def cone(lat, lon, view, steps=16):
    """The coverage slice as a polygon [[lat, lon], …] (for maps)."""
    f = Frame(lat, lon)
    pts = [[lat, lon]]
    for i in range(steps + 1):
        b = math.radians(view["heading"] - view["fov"] / 2 + view["fov"] * i / steps)
        pts.append(list(f.ll(view["range"] * math.sin(b), view["range"] * math.cos(b))))
    return pts


def point_in_polygon(x, y, poly):
    inside, j = False, len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def analyse(cameras, outline=None, cell=None):
    """cameras: {name: {"lat", "lon", "view"}}; outline: [[lat, lon], …] or None.
    Returns the grid (counts per square), blind-spot share and the best place for one more camera."""
    cams = {n: c for n, c in cameras.items() if c.get("lat") is not None}
    pts = [(c["lat"], c["lon"]) for c in cams.values()] + [tuple(p) for p in (outline or [])]
    if not pts:
        return {"ok": False, "error": "Set the cameras' places on the map first."}
    f = Frame(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    cxy = {n: f.xy(c["lat"], c["lon"]) for n, c in cams.items()}
    views = {n: clean_view(c.get("view")) for n, c in cams.items()}
    if outline and len(outline) >= 3:
        poly = [f.xy(p[0], p[1]) for p in outline]
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    else:  # no outline: the area round the cameras' views
        poly = None
        x0 = min(cxy[n][0] - views[n]["range"] for n in cams)
        x1 = max(cxy[n][0] + views[n]["range"] for n in cams)
        y0 = min(cxy[n][1] - views[n]["range"] for n in cams)
        y1 = max(cxy[n][1] + views[n]["range"] for n in cams)
    w, h = max(x1 - x0, 1), max(y1 - y0, 1)
    cell = cell or max(1.0, math.sqrt(w * h / MAX_CELLS))
    nx, ny = max(1, math.ceil(w / cell)), max(1, math.ceil(h / cell))
    grid, inside_n, blind = [], 0, []
    for j in range(ny):
        row = []
        for i in range(nx):
            x, y = x0 + (i + 0.5) * cell, y0 + (j + 0.5) * cell
            if poly and not point_in_polygon(x, y, poly):
                row.append(-1)  # outside the site
                continue
            n = sum(1 for k in cams if sees(cxy[k], views[k], x, y))
            row.append(n)
            inside_n += 1
            if n == 0:
                blind.append((x, y))
        grid.append(row)
    sw, ne = f.ll(x0, y0), f.ll(x0 + nx * cell, y0 + ny * cell)
    result = {"ok": True, "cell_m": round(cell, 2), "nx": nx, "ny": ny, "grid": grid,
              "bounds": [[sw[0], sw[1]], [ne[0], ne[1]]],  # south-west, north-east corners
              "squares": inside_n, "blind": len(blind),
              "blind_pct": round(100.0 * len(blind) / inside_n, 1) if inside_n else 0.0,
              "area_m2": round(inside_n * cell * cell),
              "cones": {n: cone(c["lat"], c["lon"], views[n]) for n, c in cams.items()},
              "views": views}
    sug = suggest(f, blind, poly or [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], cell)
    if sug and inside_n:
        sug["blind_pct_after"] = round(100.0 * max(0, len(blind) - sug["covers_blind"]) / inside_n, 1)
    result["suggestion"] = sug
    return result


def suggest(f, blind, poly, cell, view=None):
    """Where one more camera (90°, 30 m by default) would cover the most blind squares. Candidates
    are along the site outline (where cameras are usually mounted), facing every 15°."""
    if not blind:
        return None
    view = view or dict(DEFAULT_VIEW)
    cands = []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        seg = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) // max(cell * 3, 5)))
        for k in range(seg):
            t = k / seg
            cands.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    sample = blind if len(blind) <= 1500 else blind[::max(1, len(blind) // 1500)]
    scale = len(blind) / len(sample)
    best = None
    for c in cands[:200]:
        for hd in range(0, 360, 15):
            v = {**view, "heading": float(hd)}
            n = sum(1 for (x, y) in sample if sees(c, v, x, y))
            if not best or n > best[0]:
                best = (n, c, v)
    if not best or best[0] == 0:
        return None
    lat, lon = f.ll(*best[1])
    gain = round(best[0] * scale)
    return {"lat": lat, "lon": lon, "view": best[2], "covers_blind": gain, "cone": cone(lat, lon, best[2])}


def who_sees(cameras, lat, lon):
    out = []
    for n, c in cameras.items():
        if c.get("lat") is None:
            continue
        f = Frame(c["lat"], c["lon"])
        v = clean_view(c.get("view"))
        x, y = f.xy(lat, lon)
        if sees((0.0, 0.0), v, x, y):
            out.append({"camera": n, "distance_m": round(math.hypot(x, y), 1)})
    return sorted(out, key=lambda r: r["distance_m"])


def exit_point(cam, view, first_box, last_box, frame_w, frame_h, beyond_m=12.0):
    """Where a person or vehicle that just left this camera's view probably is.

    Boxes are [x1, y1, x2, y2] in pixels. Left/right in the picture is turned into a compass direction
    inside the camera's field of view; the bottom of the box (feet, wheels) into a distance: the
    bottom of the picture is near the camera, the top is about `range` away. The object is then
    carried on `beyond_m` the way it was moving on the ground (or straight out over the edge it left
    by). A rough estimate on purpose: the drone only needs to start looking in the right place.
    """
    v = clean_view(view)
    fw, fh = float(frame_w or 1), float(frame_h or 1)

    def place(box):
        cx = (box[0] + box[2]) / 2 / fw
        bottom = box[3] / fh
        b = v["heading"] + (cx - 0.5) * v["fov"]
        d = max(2.0, v["range"] * min(1.0, max(0.05, 1.0 - bottom)))
        return b, d, cx

    b1, d1, cx1 = place(first_box)
    b2, d2, cx2 = place(last_box)

    def xy(b, d):
        return d * math.sin(math.radians(b)), d * math.cos(math.radians(b))

    p1, p2 = xy(b1, d1), xy(b2, d2)
    if cx2 <= 0.08 or cx2 >= 0.92:  # left by a side of the picture: across, away from the view
        side = -1 if cx2 < 0.5 else 1
        r = math.radians(b2 + side * 90)
        out = (math.sin(r), math.cos(r))
        how = "left" if side < 0 else "right"
    elif d2 >= d1:  # walking away from the camera
        out = (math.sin(math.radians(b2)), math.cos(math.radians(b2)))
        how = "far side"
    else:  # coming towards the camera and out under it
        out = (-math.sin(math.radians(b2)), -math.cos(math.radians(b2)))
        how = "near side"
    move = (p2[0] - p1[0], p2[1] - p1[1])
    n = math.hypot(*move)
    if n >= 1.0 and move[0] * out[0] + move[1] * out[1] > 0:  # the way it was really going, if that leads out
        out = (move[0] / n, move[1] / n)
    x, y = p2[0] + out[0] * beyond_m, p2[1] + out[1] * beyond_m
    b, d = bearing_deg(x, y), math.hypot(x, y)
    f = Frame(cam["lat"], cam["lon"])
    lat, lon = f.ll(d * math.sin(math.radians(b)), d * math.cos(math.radians(b)))
    return {"lat": lat, "lon": lon, "bearing": round(b % 360, 1), "distance_m": round(d, 1), "exit": how}
