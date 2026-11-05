"""Flying weather from Open-Meteo (free, no key): wind at the ground and at flying height, gusts, rain, visibility.

`assess` turns a reading into problems against the owner's limits, used before any automatic flight.
"""
import threading
import time

import requests

API = "https://api.open-meteo.com/v1/forecast"
TTL_S = 600  # a reading is reused for 10 minutes
FAIL_TTL_S = 60  # after a failed lookup (offline), try again a minute later
DEFAULTS = {"enabled": True, "mode": "block",  # block: refuse automatic flights; warn: fly, but say why it is risky
            "max_wind_ms": 10.0, "max_gust_ms": 13.0, "block_precip": True, "min_visibility_m": 1000,
            "min_temp_c": -10.0, "max_temp_c": 40.0, "unknown": "allow"}  # weather unknown (offline): allow or block
CODES = {0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
         51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
         61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
         71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers", 81: "rain showers",
         82: "violent rain showers", 85: "snow showers", 86: "snow showers", 95: "thunderstorm",
         96: "thunderstorm with hail", 99: "thunderstorm with hail"}
WET = {c for c in CODES if c >= 51}


def clean_settings(s):
    out = dict(DEFAULTS)
    for k, v in (s or {}).items():
        if k not in DEFAULTS:
            continue
        if isinstance(DEFAULTS[k], bool):
            out[k] = bool(v)
        elif isinstance(DEFAULTS[k], (int, float)):
            out[k] = float(v)
        elif k == "mode" and v in ("block", "warn"):
            out[k] = v
        elif k == "unknown" and v in ("allow", "block"):
            out[k] = v
    return out


def fetch(lat, lon, timeout=5):
    """The current reading for a place, or raises requests.RequestException / ValueError."""
    r = requests.get(API, timeout=timeout, params={
        "latitude": round(lat, 4), "longitude": round(lon, 4), "timezone": "GMT", "wind_speed_unit": "ms",
        "forecast_hours": 3,
        "current": "temperature_2m,precipitation,weather_code,wind_speed_10m,wind_gusts_10m,wind_direction_10m",
        "hourly": "visibility,wind_speed_80m,wind_speed_120m"})
    r.raise_for_status()
    return parse(r.json())


def parse(data):
    cur = data.get("current") or {}
    if "wind_speed_10m" not in cur:
        raise ValueError(data.get("reason") or "no current weather in the answer")
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    hour = str(cur.get("time") or "")[:13]
    i = next((k for k, t in enumerate(times) if str(t)[:13] == hour), 0)

    def h(name):
        vals = hourly.get(name) or []
        return vals[i] if i < len(vals) else None
    code = cur.get("weather_code")
    return {"time": cur.get("time"), "temp_c": cur.get("temperature_2m"), "precip_mm": cur.get("precipitation"),
            "code": code, "text": CODES.get(code, "unknown"), "wind_ms": cur.get("wind_speed_10m"),
            "gust_ms": cur.get("wind_gusts_10m"), "wind_dir": cur.get("wind_direction_10m"),
            "wind_80m_ms": h("wind_speed_80m"), "wind_120m_ms": h("wind_speed_120m"), "visibility_m": h("visibility")}


def assess(w, s):
    """Problems with this reading for flying (empty list = fine)."""
    s = clean_settings(s)
    out = []
    winds = [(w.get("wind_ms"), "at the ground"), (w.get("wind_80m_ms"), "at 80 m")]
    for v, where in winds:
        if v is not None and v > s["max_wind_ms"]:
            out.append(f"wind {v:.0f} m/s {where} (limit {s['max_wind_ms']:.0f} m/s)")
            break
    if w.get("gust_ms") is not None and w["gust_ms"] > s["max_gust_ms"]:
        out.append(f"gusts {w['gust_ms']:.0f} m/s (limit {s['max_gust_ms']:.0f} m/s)")
    if s["block_precip"] and (w.get("code") in WET or (w.get("precip_mm") or 0) > 0.1):
        out.append(w.get("text") if w.get("code") in WET else "precipitation")
    if w.get("visibility_m") is not None and w["visibility_m"] < s["min_visibility_m"]:
        out.append(f"visibility {w['visibility_m'] / 1000:.1f} km")
    t = w.get("temp_c")
    if t is not None and (t < s["min_temp_c"] or t > s["max_temp_c"]):
        out.append(f"temperature {t:.0f} °C (allowed {s['min_temp_c']:.0f} to {s['max_temp_c']:.0f} °C)")
    return out


class Cache:
    """One reading per place (about 1 km), refreshed every 10 minutes; failures are remembered for a minute."""

    def __init__(self, fetcher=fetch):
        self.fetcher, self.items, self.lock = fetcher, {}, threading.Lock()

    def get(self, lat, lon):
        """(reading or None, error text, reading time)."""
        key, now = (round(lat, 2), round(lon, 2)), time.time()
        with self.lock:
            hit = self.items.get(key)  # (reading, error, reading time, checked at)
        if hit and now - hit[3] < (TTL_S if not hit[1] else FAIL_TTL_S):
            return hit[:3]
        try:
            reading = self.fetcher(lat, lon)
            got = (reading, "", now, now) if reading else (None, "No weather source.", now, now)
        except Exception:  # offline, blocked, or an unexpected answer: keep a reading up to 30 minutes old
            old = hit if hit and hit[0] and now - hit[2] < 3 * TTL_S else None
            got = (old[0] if old else None, "Weather unavailable (no internet?).", old[2] if old else now, now)
        with self.lock:
            self.items[key] = got
        return got[:3]
