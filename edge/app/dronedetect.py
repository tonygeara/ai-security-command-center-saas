"""Detector drones tab: drone detectors pinned on the map, each with a detection range.

A detector sees drones in these ways:
  * Camera AI (YOLO): the PC checks the detector's camera picture every few seconds with a YOLO model trained on drones
    (an ONNX file an admin uploads: YOLOv5 / YOLOv8 / YOLO11 exports work). Run by OpenCV, no extra software.
  * Position: drones whose position the system knows (real and virtual) are detected when they come within the
    detector's range. Drones on the "my drones" list are friendly; any other drone (one added later, e.g. a new virtual
    drone, until someone marks it as theirs) is an intruder and raises the alarm.
"""
import json
import math
import os
import re
import threading
import time
import uuid

import numpy as np

from geo import _bearing_deg, _distance_m

MAX_DETECTORS = 50
SENSOR_KINDS = ("", "acoustic", "rf")  # "": an ordinary detector (camera / position); or an acoustic or RF sensor
MIN_RANGE_M, MAX_RANGE_M = 20, 10000
YOLO_SIZE = 640
_lock = threading.Lock()


# ---------- detectors (pins) and settings ----------
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


def clean_detector(d, cameras=()):
    if not isinstance(d, dict):
        raise ValueError("A detector must be an object.")
    name = re.sub(r"[\x00-\x1f<>]", "", str(d.get("name") or "")).strip()[:40]
    if not name:
        raise ValueError("Every detector needs a name.")
    lat, lon = float(d.get("lat")), float(d.get("lon"))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or math.isnan(lat) or math.isnan(lon):
        raise ValueError(f"Detector “{name}” is not at a valid place.")
    rng = int(float(d.get("range_m") or 500))
    if not MIN_RANGE_M <= rng <= MAX_RANGE_M:
        raise ValueError(f"Detector “{name}”: range must be {MIN_RANGE_M}–{MAX_RANGE_M} m.")
    cam = str(d.get("camera") or "")
    if cam and cam not in cameras:
        raise ValueError(f"Detector “{name}”: camera “{cam}” doesn't exist.")
    sensor = str(d.get("sensor") or "")
    if sensor not in SENSOR_KINDS:
        raise ValueError(f"Detector “{name}”: unknown sensor type “{sensor}”.")
    did = str(d.get("id") or "")
    if not re.fullmatch(r"[a-f0-9]{12}", did):
        did = uuid.uuid4().hex[:12]
    return {"id": did, "name": name, "lat": round(lat, 6), "lon": round(lon, 6), "range_m": rng, "camera": cam,
            "sensor": sensor, "enabled": d.get("enabled") is not False}


def load_detectors(path):
    out, raw = [], _read(path, [])
    for d in raw if isinstance(raw, list) else []:
        try:
            out.append(clean_detector(d, cameras=(d.get("camera"),) if isinstance(d, dict) else ()))
        except (TypeError, ValueError):
            pass
    return out[:MAX_DETECTORS]


def save_detectors(path, detectors, cameras):
    if not isinstance(detectors, list):
        raise ValueError("Send a list of detectors.")
    if len(detectors) > MAX_DETECTORS:
        raise ValueError(f"{MAX_DETECTORS} detectors at most.")
    clean = [clean_detector(d, cameras) for d in detectors]
    if len({d["id"] for d in clean}) != len(clean):
        raise ValueError("Two detectors have the same id.")
    with _lock:
        _write(path, clean)
    return clean


DEFAULT_SETTINGS = {"telegram": True, "min_score": 0.45, "classes": ["drone"],
                    "remoteid_udp": False, "remoteid_port": 47911, "remoteid_token": "", "sensor_min_conf": 0.6,
                    # Send our drones to an unknown drone: automatically or not, which drones (none chosen: the nearest
                    # ready one), their height and how far from the unknown drone they hold.
                    "intercept_auto": False, "intercept_drones": [], "intercept_alt_m": 50, "intercept_standoff_m": 40}


def load_settings(path):
    raw = _read(path, {}) or {}
    s = clean_settings({**DEFAULT_SETTINGS, **raw})
    if s["remoteid_token"] != raw.get("remoteid_token"):  # keep the token made for this PC
        with _lock:
            _write(path, s)
    return s


def clean_settings(s):
    classes = s.get("classes") if isinstance(s.get("classes"), list) else str(s.get("classes") or "drone").split(",")
    classes = [re.sub(r"[^\w \-]", "", str(c)).strip()[:30] for c in classes][:80]
    token = str(s.get("remoteid_token") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,64}", token):
        token = uuid.uuid4().hex + uuid.uuid4().hex[:8]  # the receivers' token (made once, kept)
    return {"telegram": bool(s.get("telegram")), "remoteid_udp": bool(s.get("remoteid_udp")),
            "remoteid_port": max(1024, min(65535, int(float(s.get("remoteid_port") or 47911)))), "remoteid_token": token,
            "min_score": max(0.1, min(0.95, float(s.get("min_score") or 0.45))),
            "sensor_min_conf": max(0.1, min(0.99, float(s.get("sensor_min_conf") or 0.6))),
            "intercept_auto": bool(s.get("intercept_auto")),
            "intercept_drones": list(dict.fromkeys(re.sub(r"[^\w\-:.]", "", str(x))[:40] for x in
                                                   (s.get("intercept_drones") if isinstance(s.get("intercept_drones"), list) else [])
                                                   if str(x).strip()))[:20],
            "intercept_alt_m": max(20, min(120, int(float(s.get("intercept_alt_m") or 50)))),
            "intercept_standoff_m": max(10, min(300, int(float(s.get("intercept_standoff_m") or 40)))),
            "classes": [c for c in classes if c] or ["drone"]}


def save_settings(path, s):
    s = clean_settings({**load_settings(path), **{k: v for k, v in (s or {}).items() if k != "remoteid_token" or v == "new"}})
    if (s or {}).get("remoteid_token") == "new":
        s["remoteid_token"] = ""
        s = clean_settings(s)
    with _lock:
        _write(path, s)
    return s


# ---------- my drones: friendly; every other drone is an intruder ----------
def load_mine(path):
    """{slot: {"since"}} of the drones that are this site's, or None before the list was first made."""
    m = _read(path, None)
    return {str(k): v for k, v in m.items()} if isinstance(m, dict) else None


def save_mine(path, mine):
    with _lock:
        _write(path, mine)
    return mine


# ---------- detection by position ----------
def in_range(detectors, drones):
    """{detector id: [drone, with distance_m / bearing], ...} for the drones within each enabled detector's range.
    drones: [{"slot", "label", "lat", "lon", "alt", "intruder"}]."""
    out = {}
    for d in detectors:
        if not d["enabled"]:
            continue
        seen = []
        for x in drones:
            dist = _distance_m(d["lat"], d["lon"], x["lat"], x["lon"])
            if dist <= d["range_m"]:
                seen.append({**x, "distance_m": round(dist), "bearing": round(_bearing_deg(d["lat"], d["lon"], x["lat"], x["lon"])) % 360})
        out[d["id"]] = sorted(seen, key=lambda x: x["distance_m"])
    return out


# ---------- detection by camera: YOLO (ONNX) through OpenCV ----------
def letterbox(img, size=YOLO_SIZE):
    """Fit the picture into size×size with grey bars, as YOLO was trained. Returns (picture, scale, pad x, pad y)."""
    import cv2
    h, w = img.shape[:2]
    r = min(size / w, size / h)
    nw, nh = int(round(w * r)), int(round(h * r))
    px, py = (size - nw) // 2, (size - nh) // 2
    out = np.full((size, size, 3), 114, dtype=np.uint8)
    out[py:py + nh, px:px + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return out, r, px, py


def decode_yolo(output, min_score, nms=0.45, scale=1.0, pad=(0, 0)):
    """YOLO output → [(class index, score, (x, y, w, h) in the original picture)].
    Takes YOLOv8/YOLO11 (1, 4+classes, N) and YOLOv5 (1, N, 5+classes) outputs."""
    import cv2
    out = np.asarray(output, dtype=np.float32)
    if out.ndim == 3:
        out = out[0]
    if out.ndim != 2 or min(out.shape) < 5:
        return []
    v5 = False
    if out.shape[0] < out.shape[1] and out.shape[0] <= 4 + 1000:  # (4+nc, N): YOLOv8/11
        rows = out.T
    else:
        rows, v5 = out, True
    if v5:
        obj = rows[:, 4:5]
        scores = rows[:, 5:] * obj if rows.shape[1] > 5 else obj
    else:
        scores = rows[:, 4:]
    cls = scores.argmax(1)
    conf = scores[np.arange(len(scores)), cls]
    keep = conf >= min_score
    if not keep.any():
        return []
    rows, cls, conf = rows[keep], cls[keep], conf[keep]
    boxes = []
    for cx, cy, w, h in rows[:, :4]:
        x = (cx - w / 2 - pad[0]) / scale
        y = (cy - h / 2 - pad[1]) / scale
        boxes.append([float(x), float(y), float(w / scale), float(h / scale)])
    idx = cv2.dnn.NMSBoxes(boxes, conf.astype(float).tolist(), min_score, nms)
    idx = np.array(idx).flatten().tolist() if len(idx) else []
    return [(int(cls[i]), float(conf[i]), tuple(round(v, 1) for v in boxes[i])) for i in idx]


class Yolo:
    """A YOLO model (ONNX) loaded once and run by OpenCV. find() returns the drones it sees in a JPEG picture."""

    def __init__(self, path):
        self.path, self.net, self.error, self.mtime = path, None, "", None
        self.lock = threading.Lock()

    def _load(self):
        import cv2
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self.net, self.error, self.mtime = None, "No YOLO model installed.", None
            return None
        if self.net is None or mtime != self.mtime:
            try:
                self.net, self.error, self.mtime = cv2.dnn.readNetFromONNX(self.path), "", mtime
            except Exception as e:  # noqa: BLE001 - a broken or unsupported file
                self.net, self.error, self.mtime = None, f"The model can't be loaded: {str(e)[:160]}", mtime
        return self.net

    def installed(self):
        return os.path.exists(self.path)

    def find(self, jpeg, classes, min_score):
        """[{"label", "score", "box"}] for the wanted classes (all classes when the model has one) in the picture."""
        import cv2
        with self.lock:
            net = self._load()
            if net is None:
                return []
            img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return []
            boxed, r, px, py = letterbox(img)
            net.setInput(cv2.dnn.blobFromImage(boxed, 1 / 255.0, (YOLO_SIZE, YOLO_SIZE), swapRB=True, crop=False))
            out = net.forward()
        found = []
        for c, score, box in decode_yolo(out, min_score, scale=r, pad=(px, py)):
            label = classes[c] if c < len(classes) else f"class {c}"
            if len(classes) == 1 or label.lower() in ("drone", "uav", "quadcopter", "multirotor"):
                found.append({"label": label, "score": round(score, 2), "box": box})
        return found


# ---------- Remote ID (drones broadcasting their ID, position and pilot position: ASTM F3411 / OpenDroneID) ----------
# A Remote ID receiver on the site network (an ESP32 / Wi-Fi + Bluetooth OpenDroneID receiver, a phone app relay, or a
# commercial sensor) sends what it hears to this PC as JSON: by UDP (port set in the Detector drones tab) or by HTTP POST
# to /api/remoteid/report with the receiver token. Flat and OpenDroneID-style nested messages are both understood.
REMOTEID_MAX_AGE_S = 20       # a drone not heard for this long is no longer shown
REMOTEID_SAME_DRONE_M = 40    # a broadcast this close to one of the site's own linked drones is that drone


def _flat(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = re.sub(r"[^a-z0-9]+", "_", str(k).lower()).strip("_")
            out.update(_flat(v, f"{prefix}{key}." if isinstance(v, dict) else f"{prefix}{key}") if isinstance(v, dict)
                       else {f"{prefix}{key}": v})
    return out


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def parse_remoteid(msg):
    """One report → {"id", "lat", "lon", "alt", "speed", "heading", "op_lat", "op_lon", "ua_type"} or None."""
    if not isinstance(msg, dict):
        return None
    f = _flat(msg)
    op_sections = ("system", "operator", "pilot")

    def pick(names, want_op=False):
        for k, v in f.items():
            last = k.rsplit(".", 1)[-1]
            section = k.rsplit(".", 1)[0] if "." in k else ""
            is_op = any(w in section for w in op_sections) or last.startswith(("operator", "pilot"))
            if last in names and is_op == want_op and v not in (None, ""):
                return v
        return None

    rid = pick(("uas_id", "basic_id", "id", "serial_number", "serialnumber", "uasid", "id_or_mac")) or pick(("mac", "mac_address"))
    lat, lon = _num(pick(("lat", "latitude"))), _num(pick(("lon", "lng", "long", "longitude")))
    op_lat = _num(pick(("operator_lat", "operator_latitude", "pilot_lat", "pilot_latitude", "lat", "latitude"), True))
    op_lon = _num(pick(("operator_lon", "operator_lng", "operator_longitude", "pilot_lon", "pilot_lng", "pilot_longitude",
                        "lon", "lng", "long", "longitude"), True))
    if rid is None or lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    rid = re.sub(r"[^\w\-.:]", "", str(rid))[:40]
    if not rid:
        return None
    alt = _num(pick(("alt", "altitude", "height", "alt_geo", "geodetic_altitude", "altitude_geo", "height_agl", "alt_baro",
                     "pressure_altitude", "altitudegeo")))
    out = {"id": rid, "lat": round(lat, 7), "lon": round(lon, 7), "alt": round(alt, 1) if alt is not None else None,
           "speed": _num(pick(("speed", "speed_horizontal", "speedhorizontal", "ground_speed"))),
           "heading": _num(pick(("heading", "direction", "track", "course"))),
           "ua_type": str(pick(("ua_type", "uatype", "type")) or "")[:30]}
    if op_lat is not None and op_lon is not None and -90 <= op_lat <= 90 and -180 <= op_lon <= 180 and (op_lat, op_lon) != (0, 0):
        out.update(op_lat=round(op_lat, 7), op_lon=round(op_lon, 7))
    return out


def parse_remoteid_payload(data):
    """A receiver's message: one report, a list, or {"drones": [...]} / {"messages": [...]}. → [reports]."""
    if isinstance(data, dict):
        for k in ("drones", "messages", "reports", "data"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
    items = data if isinstance(data, list) else [data]
    return [r for r in (parse_remoteid(x) for x in items[:200]) if r]


class RemoteIdTracks:
    """The drones heard by Remote ID receivers lately (newest report per ID)."""

    def __init__(self, now=time.time):
        self.now, self.lock, self.tracks, self.sources = now, threading.Lock(), {}, {}

    def update(self, reports, source):
        t = self.now()
        with self.lock:
            for r in reports:
                old = self.tracks.get(r["id"], {})
                self.tracks[r["id"]] = {**old, **{k: v for k, v in r.items() if v is not None}, "seen": t, "source": source}
            self.sources[source] = {"at": t, "count": len(reports)}
            for k in [k for k, v in self.tracks.items() if t - v["seen"] > 600]:
                self.tracks.pop(k, None)

    def live(self):
        t = self.now()
        with self.lock:
            return [dict(v) for v in self.tracks.values() if t - v["seen"] <= REMOTEID_MAX_AGE_S]

    def status(self):
        t = self.now()
        with self.lock:
            return {"sources": [{"source": s, "ago_s": round(t - v["at"]), "count": v["count"]}
                                for s, v in sorted(self.sources.items(), key=lambda x: -x[1]["at"])[:10]],
                    "heard": sum(1 for v in self.tracks.values() if t - v["seen"] <= REMOTEID_MAX_AGE_S)}


# ---------- acoustic and passive RF sensors ----------
# Each sensor is a detector of type "acoustic" or "rf" pinned on the map. The sensor (or a small computer next to it)
# sends what it hears to this PC as JSON, the same way as Remote ID receivers (same UDP port, or HTTP POST with the
# receiver token):
#   {"sensor": "<detector name or id>", "detected": true, "confidence": 0.82, "bearing": 210,
#    "type": "quadcopter", "protocol": "OcuSync", "freq_mhz": 2440, "rssi_dbm": -61, "distance_m": 400}
# Only "sensor" is required; "bearing" (degrees from north, where the sound or signal comes from) lets the PC draw the
# direction, and two sensors' directions crossing give the drone's estimated position. "distance_m" (if the sensor
# estimates it) gives a position from one sensor alone.
SENSOR_MAX_AGE_S = 8          # a sensor that hasn't reported a drone for this long hears nothing now
SENSOR_FIX_MAX_AGE_S = 5      # bearings combined into a position must be this recent
SENSOR_FIX_MERGE_M = 60       # estimated positions closer than this are one drone


def parse_sensor_report(msg):
    """One acoustic / RF sensor report → dict, or None if it isn't one."""
    if not isinstance(msg, dict):
        return None
    sensor = msg.get("sensor", msg.get("sensor_id", msg.get("sensor_name")))
    if sensor in (None, ""):
        return None
    sensor = re.sub(r"[\x00-\x1f<>]", "", str(sensor)).strip()[:40]
    kind = str(msg.get("kind") or msg.get("sensor_type") or "").lower()
    kind = "acoustic" if kind in ("acoustic", "audio", "sound", "microphone") else "rf" if kind in ("rf", "radio") else ""
    conf = _num(msg.get("confidence", msg.get("score", msg.get("probability"))))
    if conf is not None and conf > 1:
        conf /= 100.0  # sent as a percentage
    detected = msg.get("detected", msg.get("drone", True))
    detected = detected if isinstance(detected, bool) else str(detected).lower() not in ("0", "false", "no", "")
    bearing = _num(msg.get("bearing", msg.get("azimuth", msg.get("direction", msg.get("doa")))))
    dist = _num(msg.get("distance_m", msg.get("distance", msg.get("range_m"))))
    out = {"sensor": sensor, "kind": kind, "detected": detected,
           "confidence": round(max(0.0, min(1.0, conf if conf is not None else 1.0)), 3),
           "bearing": round(bearing % 360, 1) if bearing is not None else None,
           "distance_m": round(dist) if dist is not None and 0 < dist <= 20000 else None,
           "drone_type": re.sub(r"[\x00-\x1f<>]", "", str(msg.get("type") or msg.get("drone_type") or msg.get("label") or "")).strip()[:40],
           "protocol": re.sub(r"[\x00-\x1f<>]", "", str(msg.get("protocol") or msg.get("link") or "")).strip()[:40]}
    f, r = _num(msg.get("freq_mhz", msg.get("frequency_mhz"))), _num(msg.get("rssi_dbm", msg.get("rssi")))
    if f is not None and 1 <= f <= 100000:
        out["freq_mhz"] = round(f, 1)
    if r is not None and -150 <= r <= 30:
        out["rssi_dbm"] = round(r, 1)
    return out


def split_payload(data):
    """A message from a receiver or a sensor → (sensor reports, Remote ID reports)."""
    if isinstance(data, dict):
        for k in ("detections", "sensors", "drones", "messages", "reports", "data"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
    items = (data if isinstance(data, list) else [data])[:200]
    sensors = [r for r in (parse_sensor_report(x) for x in items) if r]
    rid = [r for r in (parse_remoteid(x) for x in items if not parse_sensor_report(x)) if r]
    return sensors, rid


class SensorHits:
    """What each acoustic / RF sensor hears now (its latest report)."""

    def __init__(self, now=time.time):
        self.now, self.lock, self.hits, self.sources, self.unknown = now, threading.Lock(), {}, {}, {}

    def update(self, reports, source, detectors):
        """Match each report to its sensor (detector id or name); returns how many were matched."""
        t, n = self.now(), 0
        by_id = {d["id"]: d for d in detectors}
        by_name = {d["name"].casefold(): d for d in detectors}
        with self.lock:
            for r in reports:
                d = by_id.get(r["sensor"]) or by_name.get(r["sensor"].casefold())
                if not d:
                    self.unknown[r["sensor"]] = t
                    continue
                self.hits[d["id"]] = {**r, "detector": d["id"], "kind": d.get("sensor") or r["kind"] or "acoustic",
                                      "seen": t, "source": source}
                n += 1
            self.sources[source] = {"at": t, "count": len(reports)}
            for k in [k for k, v in self.unknown.items() if t - v > 600]:
                self.unknown.pop(k, None)
        return n

    def live(self, max_age=SENSOR_MAX_AGE_S):
        """Sensors hearing a drone now: [hit]."""
        t = self.now()
        with self.lock:
            return [dict(v, age_s=round(t - v["seen"], 1)) for v in self.hits.values()
                    if v["detected"] and t - v["seen"] <= max_age]

    def status(self):
        t = self.now()
        with self.lock:
            return {"sources": [{"source": s, "ago_s": round(t - v["at"]), "count": v["count"]}
                                for s, v in sorted(self.sources.items(), key=lambda x: -x[1]["at"])[:10]],
                    "hearing": sum(1 for v in self.hits.values() if v["detected"] and t - v["seen"] <= SENSOR_MAX_AGE_S),
                    "unknown_sensors": sorted(self.unknown)[:10]}


_M_PER_DEG = 111320.0


def _offset(lat, lon, bearing, dist):
    """The point dist metres from (lat, lon) towards bearing (degrees from north)."""
    b = math.radians(bearing)
    return (lat + dist * math.cos(b) / _M_PER_DEG,
            lon + dist * math.sin(b) / (_M_PER_DEG * math.cos(math.radians(lat))))


def _cross(a, b):
    """Where two sensors' direction lines cross, in front of both: (lat, lon, distance from a, from b) or None."""
    lat0 = a["lat"]
    k = _M_PER_DEG * math.cos(math.radians(lat0))
    ax, ay = 0.0, 0.0
    bx, by = (b["lon"] - a["lon"]) * k, (b["lat"] - a["lat"]) * _M_PER_DEG
    da = (math.sin(math.radians(a["bearing"])), math.cos(math.radians(a["bearing"])))
    db = (math.sin(math.radians(b["bearing"])), math.cos(math.radians(b["bearing"])))
    den = da[0] * db[1] - da[1] * db[0]
    if abs(den) < math.sin(math.radians(8)):  # nearly parallel: no useful crossing
        return None
    ta = ((bx - ax) * db[1] - (by - ay) * db[0]) / den
    tb = ((bx - ax) * da[1] - (by - ay) * da[0]) / den
    if ta <= 0 or tb <= 0:
        return None
    return a["lat"] + ta * da[1] / _M_PER_DEG, a["lon"] + ta * da[0] / k, ta, tb


def locate(hits, detectors):
    """Estimated drone positions from the sensors hearing a drone now:
    two sensors' directions crossing within both ranges, or one sensor with a direction and a distance.
    → [{"lat", "lon", "sensors": [names], "kinds": [...], "method": "cross" | "distance", "confidence"}]."""
    by_id = {d["id"]: d for d in detectors if d["enabled"] and d.get("sensor")}
    pts = []
    for h in hits:
        d = by_id.get(h["detector"])
        if d and h.get("bearing") is not None:
            pts.append({**h, "lat": d["lat"], "lon": d["lon"], "range_m": d["range_m"], "name": d["name"]})
    fixes = []
    fresh = [p for p in pts if p.get("age_s", 0) <= SENSOR_FIX_MAX_AGE_S]
    for i, a in enumerate(fresh):
        for b in fresh[i + 1:]:
            c = _cross(a, b)
            if c and c[2] <= a["range_m"] * 1.1 and c[3] <= b["range_m"] * 1.1:
                fixes.append({"lat": c[0], "lon": c[1], "sensors": [a["name"], b["name"]], "kinds": sorted({a["kind"], b["kind"]}),
                              "method": "cross", "confidence": round(min(a["confidence"], b["confidence"]), 2)})
    for p in pts:
        if p.get("distance_m") and p["distance_m"] <= p["range_m"] * 1.1 and not any(p["name"] in f["sensors"] for f in fixes):
            lat, lon = _offset(p["lat"], p["lon"], p["bearing"], p["distance_m"])
            fixes.append({"lat": lat, "lon": lon, "sensors": [p["name"]], "kinds": [p["kind"]], "method": "distance",
                          "confidence": p["confidence"]})
    merged = []
    for f in fixes:
        m = next((x for x in merged if _distance_m(x["lat"], x["lon"], f["lat"], f["lon"]) <= SENSOR_FIX_MERGE_M), None)
        if m:
            n = m.get("_n", 1)
            m["lat"], m["lon"] = (m["lat"] * n + f["lat"]) / (n + 1), (m["lon"] * n + f["lon"]) / (n + 1)
            m["_n"] = n + 1
            m["sensors"] = sorted(set(m["sensors"]) | set(f["sensors"]))
            m["kinds"] = sorted(set(m["kinds"]) | set(f["kinds"]))
            m["method"] = "cross" if "cross" in (m["method"], f["method"]) else m["method"]
        else:
            merged.append(dict(f))
    for m in merged:
        m.pop("_n", None)
        m["lat"], m["lon"] = round(m["lat"], 7), round(m["lon"], 7)
    return merged
