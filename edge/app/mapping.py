"""Drone 3D site maps: survey planning, photo capture records and the OpenDroneMap (NodeODM) processing engine.

A survey is an area drawn on the map. The drone flies a lawn-mower grid over it with the camera pointing straight
down; frames from its video (and, optionally, full-resolution photos copied from its SD card) are sent to NodeODM,
which builds a 3D textured model and an orthophoto (a map-accurate aerial photo) of the site.

Everything for one survey lives in <maps dir>/<id>/:
    survey.json   the survey (area, settings, status)
    frames/       frames grabbed from the drone video during the flight, positioned by geo.txt
    photos/       photos imported from the drone's SD card (positioned by their own EXIF GPS)
    geo.txt       position of each frame, in NodeODM's GEO file format
    result/model  textured 3D model (OBJ + MTL + textures), result/tiles: orthophoto map tiles, result/report.pdf
"""
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
import zipfile

import requests

DEFAULT_ENGINE_URL = "http://127.0.0.1:3000"
MAX_CORNERS = 30
MAX_POINTS = 120  # waypoints in one survey flight (60 grid lines)
MAX_IMAGES = 2000
CAMERA_HFOV_DEG = 69.0  # DJI Mini-class camera, horizontal field of view of the 4:3 image
CAMERA_ASPECT = 3 / 4  # image height / width
QUALITY = {
    # pc-quality: point cloud density; feature-quality: how hard it looks for matching points between images.
    "fast": [{"name": "pc-quality", "value": "low"}, {"name": "feature-quality", "value": "medium"},
             {"name": "mesh-size", "value": 100000}],
    "balanced": [{"name": "pc-quality", "value": "medium"}, {"name": "feature-quality", "value": "high"}],
    "high": [{"name": "pc-quality", "value": "high"}, {"name": "feature-quality", "value": "high"},
             {"name": "mesh-size", "value": 300000}],
}
COMMON_OPTIONS = [{"name": "tiles", "value": True},  # orthophoto map tiles the dashboard shows on its map
                  {"name": "texturing-single-material", "value": True},  # one texture image: quicker to load
                  {"name": "auto-boundary", "value": True}]
STATUS = {10: "queued", 20: "running", 30: "failed", 40: "completed", 50: "canceled"}

_lock = threading.RLock()


# ----- geometry (flat local projection in metres, like the no-fly zones) -----

def _xy(lat, lon, ref):
    return ((lon - ref[1]) * 111320.0 * math.cos(math.radians(ref[0])), (lat - ref[0]) * 110540.0)


def _ll(x, y, ref):
    return ref[0] + y / 110540.0, ref[1] + x / (111320.0 * math.cos(math.radians(ref[0])))


def footprint_m(alt):
    """Ground covered by one image at this height: (width, height) in metres."""
    w = 2 * alt * math.tan(math.radians(CAMERA_HFOV_DEG / 2))
    return w, w * CAMERA_ASPECT


def area_m2(points):
    ref = (points[0]["lat"], points[0]["lon"])
    p = [_xy(q["lat"], q["lon"], ref) for q in points]
    return abs(sum(p[i - 1][0] * p[i][1] - p[i][0] * p[i - 1][1] for i in range(len(p)))) / 2


def clean_area(points):
    pts = []
    for p in points or []:
        lat, lon = float(p["lat"]), float(p["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("A corner of the area is not a valid map position.")
        pts.append({"lat": lat, "lon": lon})
    if len(pts) < 3:
        raise ValueError("Draw the area with at least 3 corners.")
    if len(pts) > MAX_CORNERS:
        raise ValueError(f"The area can have at most {MAX_CORNERS} corners.")
    if area_m2(pts) < 100:
        raise ValueError("The area is too small to map (under 100 m²).")
    return pts


def plan_grid(points, alt=40.0, overlap=0.75, sidelap=0.7, speed=4.0, photos=False):
    """A lawn-mower flight over the area. Lines run along the area's longest side, so the drone turns less.

    Returns the waypoints plus what the flight needs: capture spacing, estimated images, distance and minutes.
    `photos`: the drone also takes a full-resolution photo at each capture point, which needs about 2 s per photo.
    """
    points = clean_area(points)
    alt, overlap, sidelap = float(alt), max(0.5, min(0.9, float(overlap))), max(0.5, min(0.85, float(sidelap)))
    ref = (sum(p["lat"] for p in points) / len(points), sum(p["lon"] for p in points) / len(points))
    poly = [_xy(p["lat"], p["lon"], ref) for p in points]
    edges = [(poly[i - 1], poly[i]) for i in range(len(poly))]
    a, b = max(edges, key=lambda e: math.hypot(e[1][0] - e[0][0], e[1][1] - e[0][1]))
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    ca, sa = math.cos(-ang), math.sin(-ang)
    rot = [(x * ca - y * sa, x * sa + y * ca) for x, y in poly]  # longest side now runs along x
    width, height = footprint_m(alt)
    spacing = width * (1 - sidelap)  # between lines
    every = height * (1 - overlap)  # between captures along a line
    ys = [p[1] for p in rot]
    y0, y1 = min(ys), max(ys)
    n = max(1, int(math.ceil((y1 - y0) / spacing)))  # each image is wider than the spacing, so the edges are covered
    first = y0 + ((y1 - y0) - (n - 1) * spacing) / 2
    lines = []
    for k in range(n):
        y = first + k * spacing
        xs = []
        for (x1, ya), (x2, yb) in zip(rot, rot[1:] + rot[:1]):
            if (ya <= y < yb) or (yb <= y < ya):
                xs.append(x1 + (y - ya) * (x2 - x1) / (yb - ya))
        if len(xs) >= 2:
            ext = height / 2  # start and end a little outside the area so its edges are covered
            lines.append((min(xs) - ext, max(xs) + ext, y))
    if not lines:
        raise ValueError("Could not fit any flight lines in that area.")
    if 2 * len(lines) > MAX_POINTS:
        raise ValueError(f"The area needs {len(lines)} flight lines at {int(alt)} m; one flight can do {MAX_POINTS // 2}. "
                         "Fly higher or map it as smaller areas.")
    ca, sa = math.cos(ang), math.sin(ang)
    wps = []
    for k, (xa, xb, y) in enumerate(lines):
        for x in ((xa, xb) if k % 2 == 0 else (xb, xa)):
            lat, lon = _ll(x * ca - y * sa, x * sa + y * ca, ref)
            wps.append({"lat": round(lat, 7), "lon": round(lon, 7)})
    if photos:
        speed = min(speed, every / 2.0)
    speed = max(1.0, min(8.0, float(speed)))
    line_m = sum(xb - xa for xa, xb, _ in lines)
    length = line_m + spacing * (len(lines) - 1)
    images = int(line_m / every) + len(lines)
    minutes = (length / speed + 8 * len(lines)) / 60  # about 8 s to slow down, turn and speed up per line
    return {"points": wps, "lines": len(lines), "alt": alt, "speed": round(speed, 1), "every_m": round(every, 1),
            "spacing_m": round(spacing, 1), "footprint_m": [round(width, 1), round(height, 1)], "length_m": int(length),
            "images": images, "minutes": round(minutes, 1), "area_m2": int(area_m2(points)),
            "gsd_cm": round(width / 960 * 100, 1)}  # ground size of one pixel of the 960-wide video frame


def bounds(points):
    lats, lons = [p["lat"] for p in points], [p["lon"] for p in points]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


# ----- survey storage -----

def _safe_id(sid):
    return bool(re.fullmatch(r"[a-f0-9]{12}", str(sid or "")))


def survey_dir(root, sid):
    if not _safe_id(sid):
        raise KeyError(sid)
    return os.path.join(root, sid)


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def load(root, sid):
    path = os.path.join(survey_dir(root, sid), "survey.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        raise KeyError(sid)


def save(root, survey):
    with _lock:
        d = survey_dir(root, survey["id"])
        os.makedirs(d, exist_ok=True)
        survey["updated_at"] = time.time()
        _write_json(os.path.join(d, "survey.json"), survey)
    return survey


def update(root, sid, **fields):
    with _lock:
        s = load(root, sid)
        s.update(fields)
        return save(root, s)


def create(root, name, points, alt=40, overlap=0.75, sidelap=0.7, speed=4, photos=False, quality="balanced"):
    name = re.sub(r"[^\w \-.]", "", str(name or "")).strip()[:50] or time.strftime("Site map %Y-%m-%d %H:%M")
    plan = plan_grid(points, alt, overlap, sidelap, speed, photos)
    s = {"id": uuid.uuid4().hex[:12], "name": name, "created_at": time.time(), "area": clean_area(points),
         "settings": {"alt": plan["alt"], "overlap": float(overlap), "sidelap": float(sidelap), "speed": plan["speed"],
                      "photos": bool(photos), "quality": quality if quality in QUALITY else "balanced"},
         "plan": plan, "status": "planned", "message": "Ready to fly.", "frames": 0, "photos": 0, "flights": [],
         "task": None, "progress": 0, "result": None}
    return save(root, s)


def list_all(root):
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for sid in names:
        if _safe_id(sid):
            try:
                out.append(load(root, sid))
            except KeyError:
                pass
    return sorted(out, key=lambda s: s.get("created_at", 0), reverse=True)


def delete(root, sid):
    with _lock:
        shutil.rmtree(survey_dir(root, sid), ignore_errors=True)


def add_frame(root, sid, jpeg, lat, lon, alt):
    """Store one frame grabbed in flight and its position (geo.txt). Returns the new frame count."""
    with _lock:
        d = survey_dir(root, sid)
        os.makedirs(os.path.join(d, "frames"), exist_ok=True)
        s = load(root, sid)
        n = s.get("frames", 0) + 1
        name = f"frame_{n:05d}.jpg"
        with open(os.path.join(d, "frames", name), "wb") as f:
            f.write(jpeg)
        geo = os.path.join(d, "geo.txt")
        new = not os.path.exists(geo)
        with open(geo, "a", encoding="utf-8") as f:
            if new:
                f.write("EPSG:4326\n")
            # image_name geo_x geo_y geo_z: x is longitude. Altitude is the drone's height above its take-off point,
            # the same reference for every frame. Orientation is left to the engine (it solves it from the images).
            f.write(f"{name} {float(lon):.8f} {float(lat):.8f} {float(alt):.2f}\n")
        s["frames"] = n
        save(root, s)
        return n


def add_photo(root, sid, filename, data):
    """Store one photo imported from the drone's SD card (a JPEG with its own GPS position)."""
    if data[:2] != b"\xff\xd8":
        raise ValueError(f"{filename} is not a JPEG photo.")
    with _lock:
        d = survey_dir(root, sid)
        os.makedirs(os.path.join(d, "photos"), exist_ok=True)
        s = load(root, sid)
        if s.get("frames", 0) + s.get("photos", 0) >= MAX_IMAGES:
            raise ValueError(f"A map can use at most {MAX_IMAGES} images.")
        base = re.sub(r"[^\w\-.]", "_", os.path.splitext(os.path.basename(filename or "photo"))[0])[:60] or "photo"
        name = f"photo_{s.get('photos', 0) + 1:05d}_{base}.jpg"
        with open(os.path.join(d, "photos", name), "wb") as f:
            f.write(data)
        s["photos"] = s.get("photos", 0) + 1
        save(root, s)
        return s["photos"]


def image_files(root, sid):
    """Every image for processing, plus geo.txt when frames have positions. Photos keep their EXIF GPS."""
    d = survey_dir(root, sid)
    files = []
    for sub in ("frames", "photos"):
        folder = os.path.join(d, sub)
        if os.path.isdir(folder):
            files += [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.lower().endswith((".jpg", ".jpeg"))]
    geo = os.path.join(d, "geo.txt")
    return files, (geo if os.path.exists(geo) else None)


# ----- NodeODM (OpenDroneMap's processing engine) -----

class EngineError(Exception):
    pass


def _check(r):
    try:
        data = r.json()
    except ValueError:
        raise EngineError(f"The mapping engine answered HTTP {r.status_code}.")
    if not r.ok or (isinstance(data, dict) and data.get("error")):
        raise EngineError(str(data.get("error") if isinstance(data, dict) else data) or f"HTTP {r.status_code}")
    return data


def engine_info(base):
    """The engine's version and queue, or EngineError when it is not reachable."""
    try:
        return _check(requests.get(f"{base}/info", timeout=4))
    except requests.RequestException:
        raise EngineError(f"The mapping engine is not running at {base}.")


def submit(base, name, files, geo=None, quality="balanced", progress=None, batch=10):
    """Upload the images (in batches, so big photo sets never sit in memory) and start processing. Returns the task id."""
    if len(files) < 5:
        raise EngineError(f"A 3D map needs at least 5 images; this survey has {len(files)}.")
    options = json.dumps(QUALITY.get(quality, QUALITY["balanced"]) + COMMON_OPTIONS)
    try:
        task = _check(requests.post(f"{base}/task/new/init", data={"name": name, "options": options}, timeout=30))["uuid"]
        uploads = list(files) + ([geo] if geo else [])
        for i in range(0, len(uploads), batch):
            handles = [open(p, "rb") for p in uploads[i:i + batch]]
            try:
                _check(requests.post(f"{base}/task/new/upload/{task}", timeout=300,
                                     files=[("images", (os.path.basename(p), h)) for p, h in zip(uploads[i:i + batch], handles)]))
            finally:
                for h in handles:
                    h.close()
            if progress:
                progress(min(len(uploads), i + batch), len(uploads))
        _check(requests.post(f"{base}/task/new/commit/{task}", timeout=60))
        return task
    except requests.RequestException as e:
        raise EngineError(f"Could not reach the mapping engine: {e}")


def task_info(base, task):
    try:
        info = _check(requests.get(f"{base}/task/{task}/info", timeout=10))
    except requests.RequestException as e:
        raise EngineError(f"Could not reach the mapping engine: {e}")
    code = (info.get("status") or {}).get("code")
    return {"state": STATUS.get(code, "unknown"), "progress": float(info.get("progress") or 0),
            "error": (info.get("status") or {}).get("errorMessage") or "", "images": info.get("imagesCount"),
            "seconds": int((info.get("processingTime") or 0) / 1000)}


def cancel(base, task):
    try:
        requests.post(f"{base}/task/cancel", data={"uuid": task}, timeout=10)
    except requests.RequestException:
        pass


def remove_task(base, task):
    try:
        requests.post(f"{base}/task/remove", data={"uuid": task}, timeout=10)
    except requests.RequestException:
        pass


def download(base, task, dest):
    """Save the task's results archive (all.zip) to dest."""
    try:
        with requests.get(f"{base}/task/{task}/download/all.zip", stream=True, timeout=60) as r:
            if not r.ok:
                raise EngineError(f"The mapping engine could not give the results (HTTP {r.status_code}).")
            with open(dest + ".part", "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        os.replace(dest + ".part", dest)
    except requests.RequestException as e:
        raise EngineError(f"Download failed: {e}")


MODEL_EXT = (".obj", ".mtl", ".png", ".jpg", ".jpeg")


def extract_results(zip_path, out_dir):
    """Keep what the dashboard shows: the textured model, the orthophoto tiles and the PDF report.

    Returns {"model": obj file name or None, "tiles": True/False, "max_zoom": int, "min_zoom": int, "report": bool}.
    """
    model_dir, tile_dir = os.path.join(out_dir, "model"), os.path.join(out_dir, "tiles")
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(model_dir)
    found = {"model": None, "tiles": False, "min_zoom": None, "max_zoom": None, "report": False}
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or ".." in name.split("/") or name.startswith("/"):
                continue
            target = None
            if name.startswith("odm_texturing/") and name.count("/") == 1 and name.lower().endswith(MODEL_EXT):
                target = os.path.join(model_dir, os.path.basename(name))
                if name.lower().endswith(".obj") and (found["model"] is None or "_geo" in name):
                    found["model"] = os.path.basename(name)
            elif re.fullmatch(r"orthophoto_tiles/\d+/\d+/\d+\.png", name):
                z_, x_, y_ = name.split("/")[1:]
                target = os.path.join(tile_dir, z_, x_, y_)
                zi = int(z_)
                found["tiles"] = True
                found["min_zoom"] = zi if found["min_zoom"] is None else min(found["min_zoom"], zi)
                found["max_zoom"] = zi if found["max_zoom"] is None else max(found["max_zoom"], zi)
            elif name == "odm_report/report.pdf":
                target = os.path.join(out_dir, "report.pdf")
                found["report"] = True
            if target:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
    return found
