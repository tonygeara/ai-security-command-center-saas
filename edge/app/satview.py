"""Satellite tab (satview): named pins over NASA satellite imagery, with optional NASA FIRMS fire alerts near them.

Imagery comes from NASA GIBS (free, no key), loaded by the browser straight from NASA: true colour from the
VIIRS (NOAA-20) or MODIS (Terra) satellites once a day, plus a clouds and a fires overlay. Near real time, not
live: a day's picture is usually complete 3 to 24 hours later.

Fire alerts (optional) come from NASA FIRMS, which needs a free "MAP_KEY" (firms.modaps.eosdis.nasa.gov/api/map_key).
The PC asks FIRMS for fires seen around each pin; the key stays on this PC and is never sent to the browser.
"""
import csv
import io
import json
import math
import os
import re
import threading
import time
import uuid

LAYERS = ("truecolor", "fires", "clouds")      # what a pin shows: picture, picture + fires, picture + clouds
SATELLITES = ("viirs", "modis")
MAX_PINS = 50
MAX_DAYS_AGO = 30
FIRE_RADIUS_KM = 50                            # fire alerts this close to a pin
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{w},{s},{e},{n}/{days}"
FIRMS_SOURCE = "VIIRS_NOAA20_NRT"
FIRMS_CACHE_S = 600
_lock = threading.Lock()


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def clean_pin(p):
    """One pin from the page: {id, name, lat, lon, layer, sat, days_ago}. Raises ValueError when it isn't valid."""
    if not isinstance(p, dict):
        raise ValueError("A pin must be an object.")
    name = re.sub(r"[\x00-\x1f<>]", "", str(p.get("name") or "")).strip()[:40]
    if not name:
        raise ValueError("Every pin needs a name.")
    lat, lon = float(p.get("lat")), float(p.get("lon"))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or math.isnan(lat) or math.isnan(lon):
        raise ValueError(f"Pin “{name}” is not at a valid place.")
    pid = str(p.get("id") or "")
    if not re.fullmatch(r"[a-f0-9]{12}", pid):
        pid = uuid.uuid4().hex[:12]
    return {"id": pid, "name": name, "lat": round(lat, 6), "lon": round(lon, 6),
            "layer": p.get("layer") if p.get("layer") in LAYERS else "truecolor",
            "sat": p.get("sat") if p.get("sat") in SATELLITES else "viirs",
            "days_ago": max(0, min(MAX_DAYS_AGO, int(float(p.get("days_ago") or 0))))}


def load_pins(path):
    pins = _read(path, [])
    out = []
    for p in pins if isinstance(pins, list) else []:
        try:
            out.append(clean_pin(p))
        except (TypeError, ValueError):
            pass
    return out[:MAX_PINS]


def save_pins(path, pins):
    if not isinstance(pins, list):
        raise ValueError("Send a list of pins.")
    if len(pins) > MAX_PINS:
        raise ValueError(f"{MAX_PINS} pins at most.")
    clean = [clean_pin(p) for p in pins]
    if len({p["id"] for p in clean}) != len(clean):
        raise ValueError("Two pins have the same id.")
    with _lock:
        _write(path, clean)
    return clean


# ---------- NASA FIRMS fire alerts ----------
def load_key(path):
    return str((_read(path, {}) or {}).get("map_key") or "")


def save_key(path, key):
    key = str(key or "").strip()
    if key and not re.fullmatch(r"[A-Za-z0-9]{16,64}", key):
        raise ValueError("That doesn't look like a FIRMS MAP_KEY (letters and digits, usually 32).")
    with _lock:
        _write(path, {"map_key": key} if key else {})
    _cache.clear()
    return bool(key)


def _km(lat1, lon1, lat2, lon2):
    r = math.radians
    a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


def box(lat, lon, km=FIRE_RADIUS_KM):
    """(west, south, east, north) around a point, about km each way."""
    dlat = km / 111.0
    dlon = km / (111.0 * max(0.05, math.cos(math.radians(lat))))
    return (round(max(-180, lon - dlon), 4), round(max(-90, lat - dlat), 4),
            round(min(180, lon + dlon), 4), round(min(90, lat + dlat), 4))


def parse_firms_csv(text):
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            rows.append({"lat": float(r["latitude"]), "lon": float(r["longitude"]),
                         "date": r.get("acq_date", ""), "time": r.get("acq_time", ""),
                         "confidence": r.get("confidence", ""), "frp": float(r.get("frp") or 0),
                         "daynight": r.get("daynight", "")})
        except (KeyError, TypeError, ValueError):
            pass
    return rows


_cache = {}


def fires_near(pins, key, days, get, now=time.time):
    """Fires seen by NOAA-20 within FIRE_RADIUS_KM of each pin in the last `days` days (1-5).
    get(url, timeout) returns (status, text). Returns {pin id: [fires, closest first]} and an error text."""
    days = max(1, min(5, int(days)))
    out, errors = {}, []
    for p in pins:
        url = FIRMS_URL.format(key=key, source=FIRMS_SOURCE, days=days, **dict(zip("wsen", box(p["lat"], p["lon"]))))
        hit = _cache.get(url)
        if hit and now() - hit[0] < FIRMS_CACHE_S:
            rows = hit[1]
        else:
            try:
                status, text = get(url, 20)
            except Exception as e:  # noqa: BLE001 - offline PC: no fire alerts, imagery still works
                errors.append(f"FIRMS can't be reached ({type(e).__name__}).")
                break
            if status != 200 or not text.lstrip().lower().startswith("latitude"):
                msg = text.strip().splitlines()[0][:120] if text.strip() else f"HTTP {status}"
                errors.append("FIRMS refused the request: " + ("the MAP_KEY is not valid." if "invalid" in msg.lower() else msg))
                break
            rows = parse_firms_csv(text)
            _cache[url] = (now(), rows)
        near = []
        for f in rows:
            d = _km(p["lat"], p["lon"], f["lat"], f["lon"])
            if d <= FIRE_RADIUS_KM:
                near.append({**f, "km": round(d, 1)})
        out[p["id"]] = sorted(near, key=lambda f: f["km"])[:200]
    return out, (errors[0] if errors else "")
