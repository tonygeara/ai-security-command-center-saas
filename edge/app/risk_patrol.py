"""Smart patrols: a patrol route the system writes itself, from blind spots and where incidents happen.

Off until the owner turns it on (Coverage page → Smart patrol). Once a week (and when switched on or
rebuilt) it:

  1. scores every square of the site: a blind spot (no camera sees it) counts, and so does being near a
     camera that has had incidents lately, weighted by how serious (unknown face/plate, drone response)
     and how recent (half the weight every 14 days);
  2. picks the highest-scoring places, at least `spacing` metres apart, as patrol stops, leaving out
     anything inside a no-fly zone or beyond the drone's range from home;
  3. orders them as a short loop from home;
  4. flies it every day at the hour incidents happen most (22:00 when there is no history yet),
     confirm-first on Telegram unless auto-start is switched on.

It only plans: flying uses the normal routes and patrol schedules, with their preflight checks.
"""
import math
import time

import coverage

ROUTE_NAME = "Smart patrol"
SCHEDULE_ID = "smartpatrol"
HALF_LIFE_DAYS = 14
HISTORY_DAYS = 60
SEVERITY_WEIGHT = {1: 1.0, 2: 3.0, 3: 5.0}
DEFAULTS = {"smart_patrol": False, "smart_patrol_auto_start": False, "smart_patrol_stops": 6, "smart_patrol_alt": 30}


def riskiest_hour(incidents, now=None):
    """The local hour (0–23) when incidents happen most, weighted by severity; 22 with no history."""
    now = now or time.time()
    hours = [0.0] * 24
    for inc in incidents:
        age_days = max(0.0, (now - inc["started"]) / 86400)
        w = SEVERITY_WEIGHT.get(inc.get("severity", 1), 1.0) * 0.5 ** (age_days / HALF_LIFE_DAYS)
        hours[time.localtime(inc["started"]).tm_hour] += w
    return max(range(24), key=lambda h: hours[h]) if any(hours) else 22


def plan(analysis, cameras, incidents, home, max_distance_m, stops=6, spacing=20.0, zone_at=None, now=None):
    """The route's stops [(lat, lon, why)] and a summary. `analysis` is coverage.analyse();
    `cameras` {name: {"lat","lon","view"}}; `incidents` [{"camera","severity","started"}]; `home` (lat, lon)."""
    now = now or time.time()
    if not analysis.get("ok") or not home:
        return [], {"error": analysis.get("error") or "No home point: connect a drone or set the site on Flight safety."}
    (s_lat, s_lon), (n_lat, n_lon) = analysis["bounds"]
    nx, ny, grid = analysis["nx"], analysis["ny"], analysis["grid"]
    f = coverage.Frame(home[0], home[1])
    # incident weight per camera
    cam_risk = {}
    for inc in incidents:
        if inc.get("camera") in cameras:
            age_days = max(0.0, (now - inc["started"]) / 86400)
            cam_risk[inc["camera"]] = cam_risk.get(inc["camera"], 0.0) + \
                SEVERITY_WEIGHT.get(inc.get("severity", 1), 1.0) * 0.5 ** (age_days / HALF_LIFE_DAYS)
    cams_xy = {n: (f.xy(c["lat"], c["lon"]), coverage.clean_view(c.get("view"))["range"]) for n, c in cameras.items()}
    cells = []
    for j in range(ny):
        for i in range(nx):
            n = grid[j][i]
            if n < 0:
                continue  # outside the site
            lat = s_lat + (j + 0.5) * (n_lat - s_lat) / ny
            lon = s_lon + (i + 0.5) * (n_lon - s_lon) / nx
            x, y = f.xy(lat, lon)
            if math.hypot(x, y) > max_distance_m * 0.9:
                continue
            if zone_at and zone_at(lat, lon):
                continue
            blind = 1.0 if n == 0 else 0.0
            hot, hot_cam = 0.0, ""
            for name, ((cx, cy), rng) in cams_xy.items():
                r = cam_risk.get(name, 0.0)
                if r:
                    d = math.hypot(x - cx, y - cy)
                    w = r * max(0.0, 1.0 - d / (rng * 1.5))
                    if w > hot:
                        hot, hot_cam = w, name
            score = blind * (1.0 + hot) + 0.5 * hot
            if score > 0:
                cells.append((score, lat, lon, x, y, blind, hot_cam))
    cells.sort(key=lambda c: -c[0])
    chosen = []
    for score, lat, lon, x, y, blind, hot_cam in cells:
        if len(chosen) >= stops:
            break
        if all(math.hypot(x - c["x"], y - c["y"]) >= spacing for c in chosen):
            why = "blind spot" + (f" near {hot_cam}, where incidents happen" if hot_cam else "") if blind \
                else f"incident hot spot by {hot_cam}"
            chosen.append({"lat": lat, "lon": lon, "x": x, "y": y, "why": why, "score": round(score, 2)})
    # a short loop from home: nearest stop next
    route, here = [], (0.0, 0.0)
    left = list(chosen)
    while left:
        nxt = min(left, key=lambda c: math.hypot(c["x"] - here[0], c["y"] - here[1]))
        left.remove(nxt)
        route.append(nxt)
        here = (nxt["x"], nxt["y"])
    hour = riskiest_hour(incidents, now)
    summary = {"stops": len(route), "blind_stops": sum(1 for r in route if r["why"].startswith("blind")),
               "hot_stops": sum(1 for r in route if r["why"].startswith("incident")), "time": f"{hour:02d}:00",
               "incidents_used": len(incidents), "built": now}
    if not route:
        summary["error"] = "Nothing to patrol: no blind spots or incident places within the drone's range."
    return [(r["lat"], r["lon"], r["why"]) for r in route], summary
