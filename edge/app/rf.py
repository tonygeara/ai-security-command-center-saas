"""Radio-frequency planning: will the drone's controller link reach a point at a given height?

A link budget for the controller-to-drone radio (DJI O2/O3/O4 use 2.4 or 5.8 GHz):
    received = EIRP + receive antenna gain - free-space loss - terrain diffraction loss
    margin   = received - receiver sensitivity
Terrain comes from a 90 m elevation model (Open-Meteo elevation API, cached; flat ground when offline). The model
knows hills, not buildings, trees or interference, so treat "good" as "likely", and walk the site to confirm.
"""
import json
import math
import os
import threading

import requests

from geo import _distance_m

ELEVATION_API = "https://api.open-meteo.com/v1/elevation"
BANDS = {"2.4": 2.437e9, "5.8": 5.787e9}
DEFAULTS = {"band": "2.4", "eirp_dbm": 20.0,  # CE limit at 2.4 GHz is 20 dBm EIRP (FCC allows more)
            "rx_gain_dbi": 2.0, "sensitivity_dbm": -100.0,  # DJI-class links: about -100 dBm or better
            "good_db": 15.0, "ok_db": 6.0,
            "controller": None, "controller_height_m": 1.5}
K_EARTH = 4 / 3 * 6371000.0  # effective earth radius for radio (standard atmosphere)
SAMPLES = 24


def clean_settings(s):
    out = dict(DEFAULTS)
    for k, v in (s or {}).items():
        if k == "band" and str(v) in BANDS:
            out[k] = str(v)
        elif k == "controller":
            out[k] = {"lat": float(v["lat"]), "lon": float(v["lon"])} if v else None
        elif k in DEFAULTS and isinstance(DEFAULTS[k], float):
            out[k] = float(v)
    return out


def fspl_db(d_m, f_hz):
    return 20 * math.log10(max(d_m, 1.0)) + 20 * math.log10(f_hz) - 147.55


def knife_edge_db(v):
    """ITU-R P.526 single knife-edge diffraction loss for the Fresnel-Kirchhoff parameter v."""
    return 0.0 if v <= -0.78 else 6.9 + 20 * math.log10(math.sqrt((v - 0.1) ** 2 + 1) + v - 0.1)


def path_loss(profile, d_total, h_tx, h_rx, f_hz):
    """Losses along a terrain profile: ground heights (m above sea) at equal steps from transmitter to receiver.

    h_tx / h_rx are the antennas' heights above the ground at each end. Returns free-space loss, the loss from the
    worst obstacle (one knife edge) and the clearance of the first Fresnel zone (100% = fully clear).
    """
    lam = 3e8 / f_hz
    n = len(profile) - 1
    a, b = profile[0] + h_tx, profile[-1] + h_rx
    worst_v, clearance = -math.inf, math.inf
    for i in range(1, n):
        d1 = d_total * i / n
        d2 = d_total - d1
        if d1 < 1 or d2 < 1:
            continue
        los = a + (b - a) * d1 / d_total
        ground = profile[i] + d1 * d2 / (2 * K_EARTH)  # the earth bulges between the ends
        h = ground - los  # > 0: terrain above the line of sight
        r1 = math.sqrt(lam * d1 * d2 / d_total)
        worst_v = max(worst_v, h * math.sqrt(2 * d_total / (lam * d1 * d2)))
        clearance = min(clearance, -h / r1)
    diff = knife_edge_db(worst_v) if worst_v > -math.inf else 0.0
    return {"fspl_db": fspl_db(math.hypot(d_total, b - a), f_hz), "diffraction_db": diff,
            # share of the first Fresnel zone's radius clear of terrain at the tightest point (60%+ is a clean link)
            "fresnel_clear_pct": None if clearance == math.inf else round(max(-100.0, min(100.0, clearance * 100))),
            "line_of_sight": worst_v < 0}


def quality(margin, s):
    return "good" if margin >= s["good_db"] else "weak" if margin >= s["ok_db"] else "poor"


class Elevation:
    """Ground height above sea level, snapped to ~100 m cells (the model's own resolution), cached on disk."""

    def __init__(self, cache_file=None, fetcher=None):
        self.file, self.cells, self.lock = cache_file, {}, threading.Lock()
        self.fetcher = fetcher or self._fetch
        self.online = True
        if cache_file and os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    self.cells = {tuple(map(float, k.split(","))): v for k, v in json.load(f).items()}
            except (OSError, ValueError):
                pass

    @staticmethod
    def _key(lat, lon):
        return (round(lat, 3), round(lon, 3))

    @staticmethod
    def _fetch(cells):
        r = requests.get(ELEVATION_API, timeout=8, params={"latitude": ",".join(f"{c[0]:.3f}" for c in cells),
                                                           "longitude": ",".join(f"{c[1]:.3f}" for c in cells)})
        r.raise_for_status()
        return r.json()["elevation"]

    def heights(self, points):
        """Heights for (lat, lon) points; None for the whole list when the terrain is unknown (offline)."""
        keys = [self._key(*p) for p in points]
        with self.lock:
            missing = sorted({k for k in keys if k not in self.cells})
        try:
            for i in range(0, len(missing), 100):
                batch = missing[i:i + 100]
                vals = self.fetcher(batch)
                with self.lock:
                    self.cells.update({k: float(v) for k, v in zip(batch, vals) if v is not None})
            self.online = True
        except Exception:
            self.online = False
        with self.lock:
            if any(k not in self.cells for k in keys):
                return None
            if missing and self.file:
                try:
                    tmp = self.file + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump({f"{k[0]},{k[1]}": v for k, v in self.cells.items()}, f)
                    os.replace(tmp, self.file)
                except OSError:
                    pass
            return [self.cells[k] for k in keys]


def check(settings, elevation, targets, alt_m):
    """The link from the controller to each target (lat, lon) at alt_m above the take-off ground."""
    s = clean_settings(settings)
    c = s["controller"]
    if not c:
        raise ValueError("Set the controller (pilot) position first.")
    f = BANDS[s["band"]]
    profiles, all_pts = [], []
    for t in targets:
        pts = [(c["lat"] + (t[0] - c["lat"]) * i / SAMPLES, c["lon"] + (t[1] - c["lon"]) * i / SAMPLES) for i in range(SAMPLES + 1)]
        profiles.append(pts)
        all_pts += pts
    hs = elevation.heights(all_pts + [(c["lat"], c["lon"])])
    terrain = hs is not None
    base = hs[-1] if terrain else 0.0
    out = []
    for k, t in enumerate(targets):
        d = _distance_m(c["lat"], c["lon"], t[0], t[1])
        prof = hs[k * (SAMPLES + 1):(k + 1) * (SAMPLES + 1)] if terrain else [0.0] * (SAMPLES + 1)
        # The drone holds its height above the take-off point, so above the ground under it that varies.
        h_rx = max(1.0, base + alt_m - prof[-1])
        loss = path_loss(prof, max(d, 1.0), s["controller_height_m"], h_rx, f)
        rx = s["eirp_dbm"] + s["rx_gain_dbi"] - loss["fspl_db"] - loss["diffraction_db"]
        margin = rx - s["sensitivity_dbm"]
        out.append({"lat": t[0], "lon": t[1], "dist_m": round(d), "rx_dbm": round(rx, 1), "margin_db": round(margin, 1),
                    "quality": quality(margin, s), "line_of_sight": loss["line_of_sight"],
                    "terrain_loss_db": round(loss["diffraction_db"], 1), "height_above_ground_m": round(h_rx)})
    return out, terrain


def grid(centre, radius_m, n=13):
    """n × n points covering a circle of radius_m round centre (lat, lon)."""
    pts = []
    for j in range(n):
        for i in range(n):
            x, y = (i / (n - 1) * 2 - 1) * radius_m, (j / (n - 1) * 2 - 1) * radius_m
            if math.hypot(x, y) <= radius_m * 1.05:
                pts.append((centre[0] + y / 110540.0, centre[1] + x / (111320.0 * math.cos(math.radians(centre[0])))))
    return pts
