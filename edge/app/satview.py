"""Satellite tab (satview): named pins over NASA satellite imagery, with optional NASA FIRMS fire alerts near them,
and public webcams worldwide (Windy Webcams).

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
            # Yesterday unless chosen: today's picture is still being filled in (and empty at night).
            "days_ago": max(0, min(MAX_DAYS_AGO, int(float(1 if p.get("days_ago") is None else p.get("days_ago")))))}


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


def save_key(path, key, what="FIRMS MAP_KEY (letters and digits, usually 32)"):
    key = str(key or "").strip()
    if key and not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
        raise ValueError(f"That doesn't look like a {what}.")
    with _lock:
        _write(path, {"map_key": key} if key else {})
    _cache.clear()
    _cam_cache.clear()
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


# ---------- Public webcams worldwide (Windy Webcams API v3) ----------
# Only webcams their owners publish (traffic, city, tourism, weather, ski): the Windy catalogue, never private CCTV
# that happens to be reachable on the internet. Needs a free Windy key (api.windy.com/keys), kept on this PC.
# Terms: link every picture to the webcam's Windy page or player and credit Windy; picture links expire after about
# 10 minutes on the free plan, so they're only cached for 5.
WINDY_URL = "https://api.windy.com/webcams/api/v3/webcams"
WINDY_CACHE_S = 300
_cam_cache = {}


def _picture(images):
    """The largest picture the plan gives (the free plan: small sizes only)."""
    cur = (images or {}).get("current") or {}
    sizes = (images or {}).get("sizes") or {}
    best = sorted(((sizes.get(k) or {}).get("width") or 0, k) for k, v in cur.items() if isinstance(v, str) and v.startswith("https://"))
    return cur[best[-1][1]] if best else ""


def clean_webcam(w):
    loc = w.get("location") or {}
    player = w.get("player") or {}
    try:
        lat, lon = float(loc["latitude"]), float(loc["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    https = lambda v: v if isinstance(v, str) and v.startswith("https://") else ""  # noqa: E731
    return {"id": str(w.get("webcamId") or ""), "title": str(w.get("title") or "Webcam")[:120],
            "lat": lat, "lon": lon, "city": str(loc.get("city") or ""), "country": str(loc.get("country") or ""),
            "status": str(w.get("status") or ""), "updated": str(w.get("lastUpdatedOn") or ""),
            "image": https(_picture(w.get("images"))), "live": https(player.get("live")),
            "player": https(player.get("day") or player.get("month") or player.get("lifetime") or ""),
            "page": https((w.get("urls") or {}).get("detail"))}


def webcams_in(bbox, key, get, now=time.time):
    """Public webcams in a map area (north, east, south, west), most popular first, 50 at most.
    get(url, params, headers, timeout) returns (status, json or None). Returns (webcams, error text)."""
    n, e, s_, w = (round(float(v), 3) for v in bbox)
    if not (-90 <= s_ < n <= 90 and -180 <= w <= 180 and -180 <= e <= 180):
        raise ValueError("That isn't a map area.")
    params = {"bbox": f"{n},{e},{s_},{w}", "limit": 50, "include": "location,images,player,urls",
              "sortKey": "popularity", "sortDirection": "desc", "lang": "en"}
    ck = json.dumps(params, sort_keys=True)
    hit = _cam_cache.get(ck)
    if hit and now() - hit[0] < WINDY_CACHE_S:
        return hit[1], ""
    try:
        status, data = get(WINDY_URL, params, {"x-windy-api-key": key}, 20)
    except Exception as e:  # noqa: BLE001 - offline PC
        return [], f"Windy can't be reached ({type(e).__name__})."
    if status in (401, 403):
        return [], "Windy refused the key: check it under Live cameras → Windy key."
    if status != 200 or not isinstance(data, dict):
        return [], f"Windy answered HTTP {status}."
    cams = [c for c in (clean_webcam(x) for x in data.get("webcams") or []) if c and c["status"] != "inactive"]
    _cam_cache[ck] = (now(), cams)
    if len(_cam_cache) > 200:
        _cam_cache.pop(next(iter(_cam_cache)))
    return cams, ""
