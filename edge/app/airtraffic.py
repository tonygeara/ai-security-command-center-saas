"""Crewed aircraft near the site, from ADS-B: planes and helicopters broadcast their position and height.

Two sources, same data format (readsb / tar1090 "aircraft.json"):
  local   a USB ADS-B receiver running readsb, dump1090 or tar1090 on this PC or a Raspberry Pi on site (works
          without internet): its aircraft.json address, e.g. http://192.168.1.50/tar1090/data/aircraft.json.
          (This dashboard uses port 8080, so give the receiver software another port on this PC.)
  online  airplanes.live (free, community receivers; coverage depends on the area)
Aircraft that send no position (or are on the ground) are not counted.
"""
import math

import requests

from geo import _bearing_deg, _distance_m

ONLINE_URL = "https://api.airplanes.live/v2/point/{lat:.4f}/{lon:.4f}/{nm}"
FT = 0.3048
DEFAULTS = {"enabled": True, "source": "online", "url": "", "watch_km": 10.0, "alert_km": 3.0,
            "alert_alt_ft": 2000.0,  # above the site: a plane higher than this is no concern for a drone at 120 m
            "action": "descend",  # warn | descend (to 15 m and hover) | land | home
            "block_takeoff": True, "unknown": "allow"}
ACTIONS = ("warn", "descend", "land", "home")


def clean_settings(s):
    out = dict(DEFAULTS)
    for k, v in (s or {}).items():
        if k not in DEFAULTS:
            continue
        if isinstance(DEFAULTS[k], bool):
            out[k] = bool(v)
        elif isinstance(DEFAULTS[k], float):
            out[k] = float(v)
        elif k == "source" and v in ("online", "local"):
            out[k] = v
        elif k == "action" and v in ACTIONS:
            out[k] = v
        elif k == "unknown" and v in ("allow", "block"):
            out[k] = v
        elif k == "url":
            v = str(v or "").strip()
            if v and not v.startswith(("http://", "https://")):
                raise ValueError("The receiver address must start with http://")
            out[k] = v[:200]
    out["watch_km"] = max(1.0, min(50.0, out["watch_km"]))
    out["alert_km"] = max(0.5, min(out["watch_km"], out["alert_km"]))
    return out


def fetch(settings, lat, lon, timeout=5):
    """Raw answer from the configured source."""
    s = clean_settings(settings)
    if s["source"] == "local":
        if not s["url"]:
            raise ValueError("No ADS-B receiver address set.")
        url = s["url"]
    else:
        url = ONLINE_URL.format(lat=lat, lon=lon, nm=max(1, int(math.ceil(s["watch_km"] / 1.852))))
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "AI-Security-Command-Center"})
    r.raise_for_status()
    return r.json()


def parse(data, lat, lon, site_elev_m=0.0, watch_km=10.0):
    """Airborne aircraft with a position within watch_km, nearest first."""
    out = []
    for a in (data.get("ac") or data.get("aircraft") or []):
        try:
            alat, alon = float(a["lat"]), float(a["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        alt = a.get("alt_baro", a.get("altitude"))
        if alt == "ground" or a.get("ground"):
            continue
        if (a.get("seen_pos") or a.get("seen") or 0) > 60:
            continue  # position more than a minute old
        d = _distance_m(lat, lon, alat, alon)
        if d > watch_km * 1000:
            continue
        alt_ft = float(alt) if isinstance(alt, (int, float)) else (float(a["alt_geom"]) if isinstance(a.get("alt_geom"), (int, float)) else None)
        out.append({"hex": str(a.get("hex") or "")[:8], "call": str(a.get("flight") or a.get("r") or "").strip()[:10],
                    "type": str(a.get("t") or "")[:6], "lat": alat, "lon": alon, "alt_ft": alt_ft,
                    "height_ft": None if alt_ft is None else alt_ft - site_elev_m / FT,  # above the site, roughly
                    "speed_kt": a.get("gs"), "track": a.get("track"), "dist_m": round(d),
                    "bearing": round(_bearing_deg(lat, lon, alat, alon) % 360)})
    return sorted(out, key=lambda x: x["dist_m"])


def threats(aircraft, settings):
    """Aircraft close and low enough to matter for the drones."""
    s = clean_settings(settings)
    return [a for a in aircraft if a["dist_m"] <= s["alert_km"] * 1000 and (a["height_ft"] is None or a["height_ft"] <= s["alert_alt_ft"])]


def describe(a):
    who = a["call"] or a["hex"].upper() or "aircraft"
    h = f"{int(round(a['height_ft'], -2))} ft above the site" if a["height_ft"] is not None else "height unknown"
    return f"{who}{' (' + a['type'] + ')' if a['type'] else ''} {a['dist_m'] / 1000:.1f} km {compass(a['bearing'])}, {h}"


def compass(deg):
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int(((deg or 0) + 22.5) // 45) % 8]
