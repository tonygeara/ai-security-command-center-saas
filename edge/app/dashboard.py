import copy
import shutil
from pathlib import Path
import ssl
import yaml
import traceback
import socket
import re
import concurrent.futures
import ipaddress
import os
import csv
import time
import cv2
import json
import queue
import threading
import winsound
import pyttsx3
import subprocess
import tempfile

# Keep background Windows commands from opening console windows.
def run_background_command(*args, **kwargs):
    if os.name == "nt":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
    return subprocess.run(*args, **kwargs)

import urllib.parse
import requests

import paho.mqtt.client as mqtt

from flask import (
    Flask,
    Response,
    jsonify,
    render_template_string,
    send_from_directory,
    request,
)


# ============================================================
# CONFIG
# ============================================================

STREAM = "rtsp://localhost:8554/tony"
DRONE_STREAM = "rtsp://localhost:8556/drone"  # direct drone RTSP source

# V7: main dashboard drone display uses go2rtc WebRTC to bypass Python MJPEG re-encoding.
# The Python drone reader remains available for enrollment and existing AI-related workflows.
# OpenCV passes these options to its FFmpeg backend when opening the RTSP stream.
DRONE_FFMPEG_CAPTURE_OPTIONS = (
    "rtsp_transport;tcp|"
    "fflags;nobuffer|"
    "flags;low_delay|"
    "probesize;32|"
    "analyzeduration;0|"
    "max_delay;0"
)
CAMERA_NAME = "tony"

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
MQTT_TOPIC = "frigate/tracked_object_update"
MQTT_EVENTS_TOPIC = "frigate/events"
DRONE_CAMERA_NAME = "drone"
DRONE_STATE_TOPIC = f"frigate/{DRONE_CAMERA_NAME}/enabled/state"
DRONE_SET_TOPIC = f"frigate/{DRONE_CAMERA_NAME}/enabled/set"
CAMERA_STATE_TOPIC = f"frigate/{CAMERA_NAME}/enabled/state"
CAMERA_SET_TOPIC = f"frigate/{CAMERA_NAME}/enabled/set"
OVERLAY_SECONDS = 5
BEEP_COOLDOWN = 2

# Unknown-event capture settings
UNKNOWN_EVENT_COOLDOWN = 120      # fallback dedupe when Frigate object ID is unavailable
UNKNOWN_EVENT_ID_TTL = 900        # remember a tracked object for 15 minutes
UNKNOWN_FACE_WAIT_SECONDS = 8     # wait for face recognition before saving person as unknown

BASE_FOLDER = os.environ.get(
    "AI_SECURITY_HOME",
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.dirname(os.path.abspath(__file__))), "AI Security Command Center")
)
os.makedirs(BASE_FOLDER, exist_ok=True)
EVENT_FOLDER = os.path.join(BASE_FOLDER, "events")
EVENT_LOG = os.path.join(BASE_FOLDER, "event_history.csv")
PLATE_FILE = os.path.join(BASE_FOLDER, "known_plates.json")
TELEGRAM_CONFIG_FILE = os.path.join(BASE_FOLDER, "telegram_config.json")
EDGE_AGENT_CONFIG_FILE = os.path.join(BASE_FOLDER, "edge_agent_config.json")
LOCAL_SETTINGS_FILE = os.path.join(BASE_FOLDER, "local_settings.json")
MANAGED_FRIGATE_DIR = os.path.join(BASE_FOLDER, "frigate")
MANAGED_FRIGATE_CONFIG = os.path.join(MANAGED_FRIGATE_DIR, "config.yml")
os.makedirs(MANAGED_FRIGATE_DIR, exist_ok=True)

def load_local_settings():
    try:
        with open(LOCAL_SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

LOCAL_SETTINGS = load_local_settings()
CAMERA_NAME = str(LOCAL_SETTINGS.get("camera_name") or CAMERA_NAME)
STREAM = str(LOCAL_SETTINGS.get("camera_stream") or f"rtsp://localhost:8554/{CAMERA_NAME}")
CAMERA_STATE_TOPIC = f"frigate/{CAMERA_NAME}/enabled/state"
CAMERA_SET_TOPIC = f"frigate/{CAMERA_NAME}/enabled/set"


# Telegram alert defaults. Secrets stay in telegram_config.json, not in this Python file.
TELEGRAM_DEFAULTS = {
    "enabled": True,
    "bot_token": "",
    "chat_id": "",
    "known_face": True,
    "unknown_face": True,
    "known_vehicle": True,
    "unknown_vehicle": True,
    "cooldown_seconds": 60,
}

PORT = int(os.environ.get("AI_SECURITY_PORT", "8080"))

DISPLAY_SECONDS = 7
SPEECH_COOLDOWN = 300
UNKNOWN_COOLDOWN = 60

JPEG_QUALITY = 60
MAIN_STREAM_FPS = 9
DRONE_STREAM_FPS = 12
DRONE_JPEG_QUALITY = 45  # lower drone-only JPEG cost for lower browser latency

# V6.4 Ultra Low Latency Drone: aggressive RTSP buffering reduction while preserving recognition.
# Recognition still comes from Frigate/MQTT, so these optimizations focus on
# lowering dashboard overhead and eliminating repeated disk work during LPR.
DRONE_FAST_RECOGNITION = True
DRONE_SCAN_LABEL_TTL = 2.5

# Faster face enrollment while still keeping center/left/right samples.
ENROLL_SAMPLES = 3

app = Flask(__name__)

try:
    cv2.setNumThreads(1)
except Exception:
    pass


# ============================================================
# GLOBAL STATE
# ============================================================

latest_frame = None
latest_jpeg = None
drone_latest_frame = None
drone_latest_jpeg = None

frame_lock = threading.Lock()
jpeg_lock = threading.Lock()
drone_frame_lock = threading.Lock()
drone_jpeg_lock = threading.Lock()
state_lock = threading.Lock()

camera_connected = False
mqtt_connected = False
drone_enabled_runtime = False
drone_source_connected = False
camera_enabled_runtime = True

# V6.2 Fast Face + Vehicle: labels standard Frigate object classes from camera + drone.
object_ai_enabled_runtime = True
object_ai_lock = threading.Lock()
recent_objects = {}
OBJECT_AI_TTL = 12
OBJECT_AI_MAX = 40
OBJECT_AI_EXCLUDE = {"person", "car", "motorcycle", "truck", "bus", "face", "lpr"}

def record_object_detection(source, label, confidence=None, object_id="", box=None):
    if not object_ai_enabled_runtime:
        return
    label = str(label or "").strip().lower()
    if not label or label in OBJECT_AI_EXCLUDE:
        return
    try:
        conf = float(confidence) if confidence is not None else None
        if conf is not None and conf <= 1.0:
            conf *= 100.0
    except Exception:
        conf = None
    key = f"{source}:{object_id or label}"
    item = {
        "source": str(source or "camera"),
        "label": label.replace("_", " ").upper(),
        "confidence": round(conf, 1) if conf is not None else None,
        "object_id": str(object_id or ""),
        "box": box,
        "updated_at": time.time(),
    }
    with object_ai_lock:
        recent_objects[key] = item
        if len(recent_objects) > OBJECT_AI_MAX:
            oldest = sorted(recent_objects, key=lambda k: recent_objects[k].get("updated_at", 0))
            for k in oldest[:len(recent_objects)-OBJECT_AI_MAX]:
                recent_objects.pop(k, None)

def object_snapshot():
    now = time.time()
    with object_ai_lock:
        for key in list(recent_objects):
            if now - float(recent_objects[key].get("updated_at", 0)) > OBJECT_AI_TTL:
                recent_objects.pop(key, None)
        items = [dict(v) for v in recent_objects.values()]
    return sorted(items, key=lambda x: x.get("updated_at", 0), reverse=True)

tracking_assist_enabled = False
drone_tracking_lock = threading.Lock()
drone_tracking = {
    "active": False, "object_id": "", "label": "", "known": False,
    "box": None, "direction": "WAITING", "updated_at": 0.0,
}
DRONE_TRACK_TIMEOUT = 3.0
DRONE_FRAME_WIDTH = 1920
DRONE_FRAME_HEIGHT = 1080

recognized_name = ""
recognized_until = 0

current_plate = ""
current_vehicle = ""
plate_until = 0

unknown_face_until = 0
unknown_vehicle_until = 0

face_count = 0
plate_count = 0

last_spoken = {}
last_unknown_alert = 0
last_detection_beep = {}

# Detection overlay state. Recognition still comes from Frigate/MQTT.
# Legacy single overlay values are preserved for compatibility, while the
# dictionaries below allow multiple people / vehicles to be shown at once.
overlay_lock = threading.Lock()
face_overlay = {"active_until": 0, "known": False, "label": "", "box": None}
plate_overlay = {"active_until": 0, "known": False, "label": "", "plate": "", "box": None}

face_overlays = {}
plate_overlays = {}
tracked_person_boxes = {}
tracked_vehicle_boxes = {}

drone_overlay_lock = threading.Lock()
drone_overlays = {}
MULTI_TARGET_TTL = 10.0
DRONE_MULTI_TARGET_TTL = 4.0
dr_recognition_stats_lock = threading.Lock()
dr_recognition_stats = {"last_face_at": 0.0, "last_plate_at": 0.0}

# Unknown-event capture / de-duplication state
event_log_lock = threading.Lock()
unknown_event_lock = threading.Lock()
seen_unknown_events = {}
pending_unknown_people = {}
recognized_person_ids = {}
recent_person_object_id = ""
recent_vehicle_object_id = ""

recent_person_box = None
recent_person_box_until = 0
recent_vehicle_box = None
recent_vehicle_box_until = 0
mqtt_message_count = 0
last_mqtt_update = ""
last_mqtt_at = 0

audio_queue = queue.Queue()
telegram_queue = queue.Queue()
telegram_last_sent = {}
telegram_lock = threading.Lock()


# ============================================================
# TELEGRAM PHONE ALERTS
# ============================================================

def load_telegram_config():
    config = dict(TELEGRAM_DEFAULTS)
    try:
        if os.path.exists(TELEGRAM_CONFIG_FILE):
            with open(TELEGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                config.update(raw)
    except Exception as e:
        print("Telegram config error:", e)
    return config


def telegram_ready(config=None):
    config = config or load_telegram_config()
    return bool(
        config.get("enabled")
        and str(config.get("bot_token") or "").strip()
        and str(config.get("chat_id") or "").strip()
    )


def queue_telegram_alert(kind, text, key, snapshot_bytes=None):
    config = load_telegram_config()
    if not telegram_ready(config):
        return False

    setting_name = {
        "known_face": "known_face",
        "unknown_face": "unknown_face",
        "known_vehicle": "known_vehicle",
        "unknown_vehicle": "unknown_vehicle",
    }.get(kind)
    if setting_name and not bool(config.get(setting_name, True)):
        return False

    try:
        cooldown = max(0, int(config.get("cooldown_seconds", 60)))
    except Exception:
        cooldown = 60

    now = time.time()
    with telegram_lock:
        last = telegram_last_sent.get(key, 0)
        if now - last < cooldown:
            return False
        telegram_last_sent[key] = now

    if snapshot_bytes is None:
        snapshot_bytes = _snapshot_bytes()

    telegram_queue.put({
        "text": str(text),
        "snapshot": snapshot_bytes,
    })
    return True


def telegram_worker():
    while True:
        item = telegram_queue.get()
        try:
            config = load_telegram_config()
            if not telegram_ready(config):
                continue

            token = str(config.get("bot_token")).strip()
            chat_id = str(config.get("chat_id")).strip()
            base = f"https://api.telegram.org/bot{token}"
            text = str(item.get("text") or "Security event")
            snapshot = item.get("snapshot")

            if snapshot:
                response = requests.post(
                    base + "/sendPhoto",
                    data={"chat_id": chat_id, "caption": text},
                    files={"photo": ("security_event.jpg", snapshot, "image/jpeg")},
                    timeout=15,
                )
            else:
                response = requests.post(
                    base + "/sendMessage",
                    data={"chat_id": chat_id, "text": text},
                    timeout=15,
                )

            if not response.ok:
                print("Telegram send error:", response.status_code, response.text[:300])
        except Exception as e:
            print("Telegram worker error:", e)
        finally:
            telegram_queue.task_done()


threading.Thread(target=telegram_worker, daemon=True).start()


# ============================================================
# FACE ENROLLMENT STATE
# ============================================================

enroll_lock = threading.Lock()

enrollment = {
    "running": False,
    "cancel": False,
    "name": "",
    "source": "camera",
    "stage": "READY",
    "message": "Ready for biometric enrollment.",
    "progress": 0,
    "sample": 0,
    "success": False,
    "error": "",
}


ENROLL_STEPS = [
    "CENTER FACE",
    "TURN SLIGHTLY LEFT",
    "TURN SLIGHTLY RIGHT",
]


# ============================================================
# FACE DETECTOR
# ============================================================

face_detector = cv2.CascadeClassifier(
    cv2.data.haarcascades
    + "haarcascade_frontalface_default.xml"
)


# ============================================================
# HELPERS
# ============================================================

# Cache the known-vehicle registry so every drone LPR hit does not reopen and
# parse known_plates.json. The cache automatically refreshes when the file changes.
_plate_cache_lock = threading.Lock()
_plate_cache_mtime = None
_plate_cache_data = {}

def load_known_plates():
    global _plate_cache_mtime, _plate_cache_data

    try:
        mtime = os.path.getmtime(PLATE_FILE) if os.path.exists(PLATE_FILE) else None
    except Exception:
        mtime = None

    with _plate_cache_lock:
        if mtime == _plate_cache_mtime:
            return dict(_plate_cache_data)

    if mtime is None:
        data = {}
    else:
        try:
            with open(PLATE_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            data = loaded if isinstance(loaded, dict) else {}
        except Exception as e:
            print("Known plate file error:", e)
            data = {}

    with _plate_cache_lock:
        _plate_cache_mtime = mtime
        _plate_cache_data = dict(data)

    return dict(data)

def save_known_plates(data):
    global _plate_cache_mtime, _plate_cache_data
    os.makedirs(
        os.path.dirname(PLATE_FILE),
        exist_ok=True
    )

    with open(
        PLATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            indent=2
        )

    # Make the next read refresh immediately.
    with _plate_cache_lock:
        _plate_cache_mtime = None
        _plate_cache_data = dict(data) if isinstance(data, dict) else {}


def is_unknown(value):
    if not value:
        return True

    return str(value).strip().lower() in {
        "unknown",
        "unknown face",
        "unknown_face",
        "unknown vehicle",
        "unknown_vehicle",
        "unrecognized",
        "unrecognised",
        "none",
    }


def clean_name(value):
    return (
        str(value)
        .replace("_", " ")
        .strip()
        .title()
    )


def normalize_known_plate_lookup(data):
    """Accept both {PLATE: vehicle} and Frigate {vehicle: [plates]} formats."""
    lookup = {}
    if not isinstance(data, dict):
        return lookup
    for key, value in data.items():
        if isinstance(value, str):
            lookup[str(key).replace(" ", "").upper()] = value
        elif isinstance(value, (list, tuple)):
            for plate in value:
                lookup[str(plate).replace(" ", "").upper()] = str(key)
    return lookup


def payload_camera(data):
    if not isinstance(data, dict):
        return ""
    camera = data.get("camera")
    if camera:
        return str(camera)
    for key in ("after", "before", "event", "data"):
        nested = data.get(key)
        if isinstance(nested, dict) and nested.get("camera"):
            return str(nested.get("camera"))
    return ""


def payload_box(data):
    """Return [x1,y1,x2,y2] when a Frigate payload exposes a bounding box."""
    if not isinstance(data, dict):
        return None
    for key in ("box", "bbox", "bounding_box"):
        value = data.get(key)
        if isinstance(value, (list, tuple)) and len(value) == 4:
            try:
                return [int(float(v)) for v in value]
            except Exception:
                pass
    for key in ("after", "event", "data"):
        nested = data.get(key)
        box = payload_box(nested) if isinstance(nested, dict) else None
        if box:
            return box
    return None


def _overlay_key(prefix, object_id="", label=""):
    object_id = str(object_id or "").strip()
    if object_id:
        return object_id
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(label or "")).strip("_")
    return f"{prefix}:{safe or 'latest'}"


def _tracked_box(store, object_id):
    object_id = str(object_id or "").strip()
    if not object_id:
        return None
    item = store.get(object_id)
    if not isinstance(item, dict):
        return None
    if time.time() - float(item.get("updated_at", 0)) > MULTI_TARGET_TTL:
        store.pop(object_id, None)
        return None
    return item.get("box")


def set_face_overlay(known, label, box=None, object_id=""):
    global face_overlay
    key = _overlay_key("face", object_id, label)
    with overlay_lock:
        if box is None:
            box = _tracked_box(tracked_person_boxes, object_id)
        if box is None and time.time() < recent_person_box_until:
            box = recent_person_box

        item = {
            "active_until": time.time() + OVERLAY_SECONDS,
            "updated_at": time.time(),
            "object_id": str(object_id or ""),
            "known": bool(known),
            "label": str(label or ("KNOWN FACE" if known else "UNKNOWN FACE")),
            "box": box,
        }
        face_overlays[key] = item
        face_overlay = dict(item)


def set_plate_overlay(known, label, plate, box=None, object_id=""):
    global plate_overlay
    key = _overlay_key("vehicle", object_id, plate or label)
    with overlay_lock:
        if box is None:
            box = _tracked_box(tracked_vehicle_boxes, object_id)
        if box is None and time.time() < recent_vehicle_box_until:
            box = recent_vehicle_box

        item = {
            "active_until": time.time() + OVERLAY_SECONDS,
            "updated_at": time.time(),
            "object_id": str(object_id or ""),
            "known": bool(known),
            "label": str(label or ("KNOWN VEHICLE" if known else "UNKNOWN VEHICLE")),
            "plate": str(plate or ""),
            "box": box,
        }
        plate_overlays[key] = item
        plate_overlay = dict(item)


def active_overlay_snapshot():
    now = time.time()
    with overlay_lock:
        for key in list(face_overlays):
            if now >= float(face_overlays[key].get("active_until", 0)):
                face_overlays.pop(key, None)
        for key in list(plate_overlays):
            if now >= float(plate_overlays[key].get("active_until", 0)):
                plate_overlays.pop(key, None)

        faces = [dict(v) for v in face_overlays.values()]
        vehicles = [dict(v) for v in plate_overlays.values()]

    faces.sort(key=lambda x: float(x.get("updated_at", 0)), reverse=True)
    vehicles.sort(key=lambda x: float(x.get("updated_at", 0)), reverse=True)
    return faces, vehicles


def update_drone_overlay(data, known=None, identity_label=None, plate=""):
    """Maintain every detected drone person/vehicle, not just the guidance target."""
    if not isinstance(data, dict):
        return

    after = data.get("after") if isinstance(data.get("after"), dict) else data
    label = str(after.get("label") or data.get("type") or "object").lower()
    if label not in {"person", "car", "motorcycle", "truck", "bus", "face", "lpr"}:
        return

    object_id = payload_object_id(after) or payload_object_id(data) or ""
    box = payload_box(after) or payload_box(data)
    key = _overlay_key("drone", object_id, plate or identity_label or label)

    with drone_overlay_lock:
        previous = dict(drone_overlays.get(key, {}))
        known_value = previous.get("known", False) if known is None else bool(known)
        display = identity_label or previous.get("label") or label.replace("_", " ").upper()
        if label in {"face", "person"}:
            object_type = "person"
        else:
            object_type = "vehicle"

        drone_overlays[key] = {
            "object_id": str(object_id or ""),
            "type": object_type,
            "known": known_value,
            "label": str(display),
            "plate": str(plate or previous.get("plate") or ""),
            "box": box or previous.get("box"),
            "updated_at": time.time(),
        }


def drone_overlay_snapshot():
    now = time.time()
    with drone_overlay_lock:
        for key in list(drone_overlays):
            if now - float(drone_overlays[key].get("updated_at", 0)) > DRONE_MULTI_TARGET_TTL:
                drone_overlays.pop(key, None)
        items = [dict(v) for v in drone_overlays.values()]
    items.sort(key=lambda x: float(x.get("updated_at", 0)), reverse=True)
    return items


# ============================================================
# UNKNOWN EVENT CAPTURE
# ============================================================

def payload_object_id(data):
    """Best-effort extraction of Frigate's tracked object/event ID."""
    if not isinstance(data, dict):
        return ""
    for key in ("id", "object_id", "event_id"):
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    for key in ("after", "before", "event", "data"):
        nested = data.get(key)
        if isinstance(nested, dict):
            value = payload_object_id(nested)
            if value:
                return value
    return ""


def _prune_unknown_tracking(now=None):
    now = now or time.time()
    with unknown_event_lock:
        for store in (seen_unknown_events, recognized_person_ids):
            stale = [key for key, ts in store.items() if now - ts > UNKNOWN_EVENT_ID_TTL]
            for key in stale:
                store.pop(key, None)
        stale_pending = [
            key for key, item in pending_unknown_people.items()
            if now - float(item.get("created", now)) > UNKNOWN_EVENT_ID_TTL
        ]
        for key in stale_pending:
            pending_unknown_people.pop(key, None)


def _snapshot_bytes():
    with jpeg_lock:
        return bytes(latest_jpeg) if latest_jpeg else None


def save_unknown_event(event_type, name, identifier="", object_id="", snapshot_bytes=None):
    """Save one unknown event and suppress repeats for the same tracked object."""
    now = time.time()
    _prune_unknown_tracking(now)
    event_type = str(event_type or "UNKNOWN").strip()
    name = str(name or "Unknown").strip()
    identifier = str(identifier or "").strip()
    object_id = str(object_id or "").strip()

    if object_id:
        dedupe_key = f"{event_type}:id:{object_id}"
        dedupe_window = UNKNOWN_EVENT_ID_TTL
    else:
        fallback = identifier or name
        dedupe_key = f"{event_type}:fallback:{fallback.lower()}"
        dedupe_window = UNKNOWN_EVENT_COOLDOWN

    with unknown_event_lock:
        last_saved = seen_unknown_events.get(dedupe_key, 0)
        if now - last_saved < dedupe_window:
            return False
        seen_unknown_events[dedupe_key] = now

    os.makedirs(EVENT_FOLDER, exist_ok=True)
    dt = time.localtime(now)
    date_text = time.strftime("%Y-%m-%d", dt)
    time_text = time.strftime("%H:%M:%S", dt)
    stamp = time.strftime("%Y%m%d_%H%M%S", dt)
    safe_kind = "".join(ch if ch.isalnum() else "_" for ch in event_type.lower()).strip("_") or "unknown"
    suffix = object_id[-8:] if object_id else str(int(now * 1000))[-8:]
    filename = f"{safe_kind}_{stamp}_{suffix}.jpg"
    snapshot_path = os.path.join(EVENT_FOLDER, filename)

    if snapshot_bytes is None:
        snapshot_bytes = _snapshot_bytes()
    if snapshot_bytes:
        try:
            with open(snapshot_path, "wb") as f:
                f.write(snapshot_bytes)
        except Exception as e:
            print("Unknown event snapshot error:", e)
            snapshot_path = ""
    else:
        snapshot_path = ""

    row = {
        "Date": date_text,
        "Time": time_text,
        "Type": event_type,
        "Name": name,
        "Identifier": identifier,
        "Snapshot": snapshot_path,
    }
    fieldnames = ["Date", "Time", "Type", "Name", "Identifier", "Snapshot"]

    try:
        with event_log_lock:
            os.makedirs(os.path.dirname(EVENT_LOG), exist_ok=True)
            file_exists = os.path.exists(EVENT_LOG) and os.path.getsize(EVENT_LOG) > 0
            if file_exists:
                with open(EVENT_LOG, "r", encoding="utf-8") as f:
                    existing_fields = csv.DictReader(f).fieldnames or []
                if existing_fields:
                    fieldnames = existing_fields
            with open(EVENT_LOG, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                if not file_exists:
                    writer.writeheader()
                writer.writerow({key: row.get(key, "") for key in fieldnames})
        print(f"Saved unknown event: {event_type} {identifier or name}")

        # Unknown alerts are queued only after the event was actually saved,
        # so the existing object-ID de-duplication also prevents Telegram spam.
        if event_type.upper() == "UNKNOWN FACE":
            queue_telegram_alert(
                "unknown_face",
                f"⚠️ UNKNOWN PERSON detected at {CAMERA_NAME}\n{date_text} {time_text}",
                f"unknown_face:{object_id or identifier or name}",
                snapshot_bytes=snapshot_bytes,
            )
        elif event_type.upper() in {"UNKNOWN PLATE", "UNKNOWN VEHICLE"}:
            plate_text = identifier or "Plate unavailable"
            queue_telegram_alert(
                "unknown_vehicle",
                f"⚠️ UNKNOWN VEHICLE detected at {CAMERA_NAME}\nPlate: {plate_text}\n{date_text} {time_text}",
                f"unknown_vehicle:{object_id or plate_text}",
                snapshot_bytes=snapshot_bytes,
            )

        return True
    except Exception as e:
        print("Unknown event log error:", e)
        return False


def mark_person_recognized(object_id=""):
    object_id = str(object_id or "").strip()
    if not object_id:
        return
    with unknown_event_lock:
        recognized_person_ids[object_id] = time.time()
        pending_unknown_people.pop(object_id, None)


def queue_unknown_person(object_id, box=None):
    object_id = str(object_id or "").strip()
    if not object_id:
        return
    now = time.time()
    with unknown_event_lock:
        if object_id in recognized_person_ids or object_id in pending_unknown_people:
            return
        if f"UNKNOWN FACE:id:{object_id}" in seen_unknown_events:
            return
        pending_unknown_people[object_id] = {
            "created": now,
            "due": now + UNKNOWN_FACE_WAIT_SECONDS,
            "box": box,
        }


def unknown_person_worker():
    global unknown_face_until
    while True:
        try:
            now = time.time()
            due = []
            with unknown_event_lock:
                for object_id, item in list(pending_unknown_people.items()):
                    if now >= float(item.get("due", now + 1)):
                        due.append((object_id, dict(item)))
                        pending_unknown_people.pop(object_id, None)
            for object_id, item in due:
                with unknown_event_lock:
                    if object_id in recognized_person_ids:
                        continue
                with state_lock:
                    unknown_face_until = time.time() + DISPLAY_SECONDS
                set_face_overlay(False, "UNKNOWN FACE", item.get("box"), object_id=object_id)
                detection_beep("unknown_person_" + object_id, False)
                warning_sound()
                save_unknown_event(
                    "UNKNOWN FACE",
                    "Unknown Person",
                    identifier=object_id,
                    object_id=object_id,
                )
            _prune_unknown_tracking(now)
        except Exception as e:
            print("Unknown person worker error:", e)
        time.sleep(0.5)


threading.Thread(target=unknown_person_worker, daemon=True).start()


# ============================================================
# AUDIO
# ============================================================

def speak(text, key):
    now = time.time()

    if (
        now
        - last_spoken.get(key, 0)
        < SPEECH_COOLDOWN
    ):
        return

    last_spoken[key] = now

    audio_queue.put(
        ("speech", text)
    )


def warning_sound():
    global last_unknown_alert

    now = time.time()

    if (
        now
        - last_unknown_alert
        < UNKNOWN_COOLDOWN
    ):
        return

    last_unknown_alert = now

    audio_queue.put(
        ("alert", None)
    )


def detection_beep(key, known):
    now = time.time()
    if now - last_detection_beep.get(key, 0) < BEEP_COOLDOWN:
        return
    last_detection_beep[key] = now
    audio_queue.put(("known_beep" if known else "unknown_beep", None))


def audio_worker():
    try:
        engine = pyttsx3.init()

        voices = engine.getProperty(
            "voices"
        )

        for voice in voices:
            info = (
                str(voice.name)
                + " "
                + str(voice.id)
            ).lower()

            if (
                "zira" in info
                or "aria" in info
                or "female" in info
            ):
                engine.setProperty(
                    "voice",
                    voice.id
                )
                break

        engine.setProperty(
            "rate",
            165
        )

        engine.setProperty(
            "volume",
            1.0
        )

    except Exception as e:
        print(
            "Voice error:",
            e
        )

        engine = None

    while True:
        action, text = (
            audio_queue.get()
        )

        try:
            if (
                action == "speech"
                and engine
            ):
                engine.say(text)

                engine.runAndWait()

            elif action == "alert":
                winsound.Beep(1000, 160)
                time.sleep(0.08)
                winsound.Beep(700, 220)

            elif action == "known_beep":
                winsound.Beep(1350, 100)
                time.sleep(0.05)
                winsound.Beep(1700, 120)

            elif action == "unknown_beep":
                winsound.Beep(900, 140)
                time.sleep(0.05)
                winsound.Beep(650, 180)

        except Exception as e:
            print(
                "Audio error:",
                e
            )

        finally:
            audio_queue.task_done()


threading.Thread(
    target=audio_worker,
    daemon=True
).start()


# ============================================================
# CAMERA
# ============================================================

def camera_worker():
    global latest_frame
    global camera_connected

    cap = None

    while True:
        try:
            # Close the local RTSP reader while Camera AI is disabled.
            if not camera_enabled_runtime:
                camera_connected = False
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = None
                with frame_lock:
                    latest_frame = None
                with jpeg_lock:
                    global latest_jpeg
                    latest_jpeg = None
                time.sleep(0.5)
                continue

            if (
                cap is None
                or not cap.isOpened()
            ):
                camera_connected = False

                print(
                    "Connecting dashboard camera..."
                )

                cap = cv2.VideoCapture(
                    STREAM
                )

                try:
                    cap.set(
                        cv2.CAP_PROP_BUFFERSIZE,
                        1
                    )
                except Exception:
                    pass

                time.sleep(1)

            ret, frame = cap.read()

            if not ret:
                camera_connected = False

                try:
                    cap.release()
                except Exception:
                    pass

                cap = None

                time.sleep(2)

                continue

            camera_connected = True

            with frame_lock:
                latest_frame = frame

        except Exception as e:
            camera_connected = False

            print(
                "Camera error:",
                e
            )

            try:
                cap.release()
            except Exception:
                pass

            cap = None

            time.sleep(2)


def encoder_worker():
    global latest_jpeg

    delay = (
        1.0
        / MAIN_STREAM_FPS
    )

    while True:
        started = time.time()

        frame = None

        with frame_lock:
            if latest_frame is not None:
                frame = (
                    latest_frame.copy()
                )

        if frame is not None:
            # Draw temporary detection cadres. Green = known, orange = unknown.
            now = time.time()
            face_states, plate_states = active_overlay_snapshot()

            def draw_detection_box(img, box, label, known, fallback_face=False):
                color = (0, 220, 80) if known else (0, 165, 255)  # BGR green / orange
                h, w = img.shape[:2]
                chosen = box

                # For face events, prefer a real local face box so the cadre surrounds the face.
                if fallback_face:
                    try:
                        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        faces = face_detector.detectMultiScale(
                            gray, scaleFactor=1.12, minNeighbors=6, minSize=(70, 70)
                        )
                        if len(faces):
                            x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
                            chosen = [x, y, x + fw, y + fh]
                    except Exception:
                        pass

                if chosen and len(chosen) == 4:
                    x1, y1, x2, y2 = [int(v) for v in chosen]
                    x1, x2 = max(0, min(w - 1, x1)), max(0, min(w - 1, x2))
                    y1, y2 = max(0, min(h - 1, y1)), max(0, min(h - 1, y2))
                    if x2 <= x1 or y2 <= y1:
                        chosen = None

                # If Frigate did not provide a useful box, show a clear alert cadre around the feed.
                if not chosen:
                    x1, y1, x2, y2 = 18, 18, w - 18, h - 18

                cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
                text = str(label or "DETECTED")
                (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
                ty = max(th + 12, y1)
                cv2.rectangle(img, (x1, ty - th - 12), (min(w - 1, x1 + tw + 16), ty + 5), color, -1)
                cv2.putText(img, text, (x1 + 7, ty - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2, cv2.LINE_AA)

            # Draw every active person/face simultaneously.
            # If only one face is active and Frigate did not provide a box,
            # retain the local Haar fallback used by the earlier working build.
            for face_state in face_states:
                draw_detection_box(
                    frame,
                    face_state.get("box"),
                    face_state.get("label"),
                    face_state.get("known", False),
                    fallback_face=(len(face_states) == 1 and not face_state.get("box")),
                )

            # Draw every active vehicle simultaneously.
            for plate_state in plate_states:
                plate_label = plate_state.get("label", "VEHICLE")
                if plate_state.get("plate"):
                    plate_label += " | " + plate_state.get("plate")
                draw_detection_box(
                    frame,
                    plate_state.get("box"),
                    plate_label,
                    plate_state.get("known", False),
                    fallback_face=False,
                )

            ok, buffer = cv2.imencode(
                ".jpg",
                frame,
                [
                    int(
                        cv2.IMWRITE_JPEG_QUALITY
                    ),
                    JPEG_QUALITY,
                ]
            )

            if ok:
                with jpeg_lock:
                    latest_jpeg = (
                        buffer.tobytes()
                    )

        remaining = (
            delay
            - (
                time.time()
                - started
            )
        )

        if remaining > 0:
            time.sleep(
                remaining
            )


threading.Thread(
    target=camera_worker,
    daemon=True
).start()

threading.Thread(
    target=encoder_worker,
    daemon=True
).start()


# ============================================================
# DRONE DASHBOARD VIDEO
# ============================================================

def drone_camera_worker():
    global drone_latest_frame, drone_source_connected
    cap = None
    while True:
        try:
            # V10.8: do not probe the RTSP drone path while Drone runtime is OFF.
            if not drone_enabled_runtime:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = None
                with drone_frame_lock:
                    drone_latest_frame = None
                drone_source_connected = False
                time.sleep(2.0)
                continue

            # Drone video is opened only when the customer enables drone runtime.
            # This lets the dashboard show the DJI/MediaMTX feed as soon as it exists.
            if cap is None or not cap.isOpened():
                try:
                    _dcfg_path = r'C:\\frigate\\config\\config.yaml' if os.path.exists(r'C:\\frigate\\config\\config.yaml') else r'C:\\frigate\\config\\config.yml'
                    if os.path.exists(_dcfg_path):
                        with open(_dcfg_path,'r',encoding='utf-8') as _df:
                            _dcfg = yaml.safe_load(_df) or {}
                        if not bool((((_dcfg.get('cameras') or {}).get('drone') or {}).get('enabled',False))):
                            time.sleep(5)
                            continue
                except Exception:
                    time.sleep(5)
                    continue
                print("Connecting dashboard drone camera...")
                # V8: use TCP because the MediaMTX service is configured for TCP RTSP transport.
                # This targets latency at the source rather than merely increasing UI FPS.
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = DRONE_FFMPEG_CAPTURE_OPTIONS
                try:
                    cap = cv2.VideoCapture(DRONE_STREAM, cv2.CAP_FFMPEG)
                except Exception:
                    cap = cv2.VideoCapture(DRONE_STREAM)
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
                        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2000)
                    if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
                        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 1500)
                except Exception:
                    pass
                # Very short settle time: avoid intentionally adding visible delay.
                time.sleep(0.03)

            ret, frame = cap.read()
            if not ret:
                try:
                    cap.release()
                except Exception:
                    pass
                cap = None
                with drone_frame_lock:
                    drone_latest_frame = None
                drone_source_connected = False
                # Retry quickly after a dropped drone frame without affecting other workers.
                time.sleep(0.12)
                continue

            with drone_frame_lock:
                drone_latest_frame = frame
            drone_source_connected = True

        except Exception as e:
            print("Drone camera error:", e)
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass
            cap = None
            drone_source_connected = False
            time.sleep(0.25)


def drone_encoder_worker():
    global drone_latest_jpeg
    # Drone-only low-latency display. 12 FPS reduces browser/JPEG CPU so the system
    # can spend more time on Frigate face/LPR inference while keeping the newest frame.
    delay = 1.0 / DRONE_STREAM_FPS
    while True:
        started = time.time()
        frame = None
        with drone_frame_lock:
            if drone_latest_frame is not None:
                frame = drone_latest_frame.copy()

        if frame is not None:
            # Draw every Frigate-detected drone person/vehicle.
            # Green = recognized/known. Orange = detected but not yet identified.
            state = drone_tracking_snapshot()
            targets = drone_overlay_snapshot()
            h, w = frame.shape[:2]

            for target in targets:
                box = target.get("box")
                if not box or len(box) != 4:
                    continue

                try:
                    x1, y1, x2, y2 = [int(float(v)) for v in box]
                    sx = w / float(DRONE_FRAME_WIDTH)
                    sy = h / float(DRONE_FRAME_HEIGHT)
                    x1, x2 = int(x1 * sx), int(x2 * sx)
                    y1, y2 = int(y1 * sy), int(y2 * sy)
                    x1, x2 = max(0, min(w - 1, x1)), max(0, min(w - 1, x2))
                    y1, y2 = max(0, min(h - 1, y1)), max(0, min(h - 1, y2))
                    if x2 <= x1 or y2 <= y1:
                        continue

                    color = (0, 220, 80) if target.get("known") else (0, 165, 255)
                    label = str(target.get("label") or target.get("type") or "TARGET")
                    if target.get("plate"):
                        label += " | " + str(target.get("plate"))

                    # Tracking-assist direction is only appended to the selected
                    # primary target; all other detected targets remain visible.
                    if (
                        state.get("enabled")
                        and state.get("active")
                        and str(state.get("object_id") or "")
                        and str(state.get("object_id") or "") == str(target.get("object_id") or "")
                    ):
                        label += " • " + str(state.get("direction") or "")

                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
                    cv2.putText(
                        frame,
                        label,
                        (x1, max(24, y1 - 9)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        color,
                        2,
                        cv2.LINE_AA,
                    )
                except Exception:
                    pass

            ok, buffer = cv2.imencode(
                ".jpg", frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), DRONE_JPEG_QUALITY]
            )
            if ok:
                with drone_jpeg_lock:
                    drone_latest_jpeg = buffer.tobytes()
        else:
            with drone_jpeg_lock:
                drone_latest_jpeg = None

        remaining = delay - (time.time() - started)
        if remaining > 0:
            time.sleep(remaining)


def generate_drone_frames():
    while True:
        jpg = None
        with drone_jpeg_lock:
            if drone_latest_jpeg is not None:
                jpg = drone_latest_jpeg
        if jpg is None:
            # Keep the browser feed responsive while waiting for the next drone frame.
            time.sleep(0.05)
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Cache-Control: no-cache, no-store, must-revalidate\r\n"
            b"Pragma: no-cache\r\n"
            b"Expires: 0\r\n\r\n" + jpg + b"\r\n"
        )
        # No extra browser-side sleep: encoder_worker already controls the rate.
        # This prevents another full frame interval from being added to latency.
        time.sleep(0.002)


threading.Thread(target=drone_camera_worker, daemon=True).start()
threading.Thread(target=drone_encoder_worker, daemon=True).start()


# ============================================================
# DRONE TRACKING ASSIST (VISUAL / MANUAL GUIDANCE ONLY)
# ============================================================

def _drone_direction(box, frame_width=DRONE_FRAME_WIDTH, frame_height=DRONE_FRAME_HEIGHT):
    if not box or len(box) != 4:
        return "TARGET DETECTED"
    x1, y1, x2, y2 = [float(v) for v in box]
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    fw, fh = max(float(frame_width or DRONE_FRAME_WIDTH), 1.0), max(float(frame_height or DRONE_FRAME_HEIGHT), 1.0)
    dx, dy = (cx - fw / 2.0) / (fw / 2.0), (cy - fh / 2.0) / (fh / 2.0)
    dead = 0.16
    horiz = "LEFT" if dx < -dead else ("RIGHT" if dx > dead else "")
    vert = "UP" if dy < -dead else ("DOWN" if dy > dead else "")
    if not horiz and not vert:
        return "CENTERED"
    return f"{horiz} + {vert}" if horiz and vert else (horiz or vert)

def update_drone_tracking(data, known=None, identity_label=None):
    global drone_tracking
    if not tracking_assist_enabled or not isinstance(data, dict):
        return
    after = data.get("after") if isinstance(data.get("after"), dict) else data
    label = str(after.get("label") or data.get("type") or "object").lower()
    if label not in {"person", "car", "motorcycle", "truck", "bus", "face", "lpr"}:
        return
    box = payload_box(after) or payload_box(data)
    object_id = payload_object_id(after) or payload_object_id(data) or ""
    frame_width = after.get("frame_width") or after.get("width") or DRONE_FRAME_WIDTH
    frame_height = after.get("frame_height") or after.get("height") or DRONE_FRAME_HEIGHT
    display = identity_label or label.replace("_", " ").upper()
    with drone_tracking_lock:
        existing_id = str(drone_tracking.get("object_id") or "")
        if object_id and existing_id and object_id != existing_id and time.time() - float(drone_tracking.get("updated_at", 0)) < DRONE_TRACK_TIMEOUT:
            return
        known_value = (bool(drone_tracking.get("known", False)) if known is None and object_id == existing_id else bool(known))
        drone_tracking = {
            "active": True, "object_id": str(object_id), "label": str(display),
            "known": known_value, "box": box,
            "direction": _drone_direction(box, frame_width, frame_height),
            "updated_at": time.time(),
        }

def drone_tracking_snapshot():
    with drone_tracking_lock:
        d = dict(drone_tracking)
    if time.time() - float(d.get("updated_at", 0)) > DRONE_TRACK_TIMEOUT:
        d["active"] = False
        d["direction"] = "WAITING"
    d["enabled"] = bool(tracking_assist_enabled)
    return d

# ============================================================
# MQTT
# ============================================================

def on_connect(
    client,
    userdata,
    flags,
    rc
):
    global mqtt_connected

    if rc == 0:
        mqtt_connected = True

        client.subscribe(MQTT_TOPIC)
        client.subscribe(MQTT_EVENTS_TOPIC)
        client.subscribe(DRONE_STATE_TOPIC)
        client.subscribe(CAMERA_STATE_TOPIC)

        print(
            "Dashboard MQTT connected"
        )

    else:
        mqtt_connected = False


def on_disconnect(
    client,
    userdata,
    rc
):
    global mqtt_connected

    mqtt_connected = False


def on_message(
    client,
    userdata,
    msg
):
    global recognized_name
    global recognized_until

    global current_plate
    global current_vehicle
    global plate_until

    global unknown_face_until
    global unknown_vehicle_until

    global face_count
    global plate_count
    global drone_enabled_runtime
    global camera_enabled_runtime

    try:
        if msg.topic == DRONE_STATE_TOPIC:
            state = msg.payload.decode("utf-8", errors="ignore").strip().upper()
            drone_enabled_runtime = (state == "ON")
            print("Drone runtime state:", state)
            return

        if msg.topic == CAMERA_STATE_TOPIC:
            state = msg.payload.decode("utf-8", errors="ignore").strip().upper()
            camera_enabled_runtime = (state == "ON")
            print("Camera runtime state:", state)
            return

        data = json.loads(msg.payload.decode("utf-8"))

        global mqtt_message_count, last_mqtt_update, last_mqtt_at
        global recent_person_box, recent_person_box_until
        global recent_vehicle_box, recent_vehicle_box_until
        global recent_person_object_id, recent_vehicle_object_id

        camera = payload_camera(data)
        if camera == DRONE_CAMERA_NAME:
            if msg.topic == MQTT_EVENTS_TOPIC:
                after_obj = data.get("after") if isinstance(data.get("after"), dict) else {}
                record_object_detection(
                    "DRONE",
                    after_obj.get("label"),
                    after_obj.get("score") or after_obj.get("top_score"),
                    payload_object_id(after_obj) or payload_object_id(data),
                    payload_box(after_obj),
                )
                update_drone_overlay(data)
                update_drone_tracking(data)

                # Immediate visual feedback while Frigate finishes face/LPR recognition.
                # This does not replace Frigate recognition; it makes the drone UI react
                # as soon as the person/vehicle tracker event arrives.
                if DRONE_FAST_RECOGNITION:
                    quick_label = str(after_obj.get("label") or "").lower()
                    if quick_label == "person":
                        update_drone_overlay(
                            data,
                            known=False,
                            identity_label="SCANNING FACE...",
                        )
                    elif quick_label in {"car", "motorcycle", "truck", "bus"}:
                        update_drone_overlay(
                            data,
                            known=False,
                            identity_label="READING PLATE...",
                        )
            elif msg.topic == MQTT_TOPIC:
                update_type_for_drone = str(data.get("type") or "").lower()
                if update_type_for_drone == "face":
                    with dr_recognition_stats_lock:
                        dr_recognition_stats["last_face_at"] = time.time()
                    drone_name = data.get("name")
                    drone_known = not is_unknown(drone_name)
                    drone_label = clean_name(drone_name) if drone_known else "UNKNOWN PERSON"
                    update_drone_overlay(
                        data,
                        known=drone_known,
                        identity_label=drone_label,
                    )
                    update_drone_tracking(
                        data,
                        known=drone_known,
                        identity_label=drone_label,
                    )
                elif update_type_for_drone == "lpr":
                    with dr_recognition_stats_lock:
                        dr_recognition_stats["last_plate_at"] = time.time()
                    drone_plate = str(data.get("plate") or "").replace(" ", "").upper()
                    drone_known_plates = normalize_known_plate_lookup(load_known_plates())
                    drone_vehicle = drone_known_plates.get(drone_plate) or data.get("name")
                    drone_known = bool(drone_vehicle and not is_unknown(drone_vehicle))
                    drone_label = (
                        str(drone_vehicle).replace("_", " ")
                        if drone_known
                        else "UNKNOWN VEHICLE"
                    )
                    update_drone_overlay(
                        data,
                        known=drone_known,
                        identity_label=drone_label,
                        plate=drone_plate,
                    )
                    update_drone_tracking(
                        data,
                        known=drone_known,
                        identity_label=drone_label,
                    )
            return
        if camera and camera != CAMERA_NAME:
            return

        mqtt_message_count += 1
        last_mqtt_at = time.time()

        # Standard Frigate events provide tracked-object boxes. Cache them so
        # face/LPR recognition updates can be drawn on the live dashboard feed.
        if msg.topic == MQTT_EVENTS_TOPIC:
            after = data.get("after") if isinstance(data.get("after"), dict) else {}
            label = str(after.get("label") or "").lower()
            box = payload_box(after)
            object_id = payload_object_id(after) or payload_object_id(data)
            record_object_detection(
                "CAMERA", label, after.get("score") or after.get("top_score"), object_id, box
            )

            if label == "person":
                if box:
                    recent_person_box = box
                    recent_person_box_until = time.time() + 10
                if object_id:
                    recent_person_object_id = object_id
                    tracked_person_boxes[object_id] = {
                        "box": box,
                        "updated_at": time.time(),
                    }
                    set_face_overlay(False, "PERSON", box, object_id=object_id)
                    queue_unknown_person(object_id, box)

            elif label in {"car", "motorcycle", "truck", "bus"}:
                if box:
                    recent_vehicle_box = box
                    recent_vehicle_box_until = time.time() + 10
                if object_id:
                    recent_vehicle_object_id = object_id
                    tracked_vehicle_boxes[object_id] = {
                        "box": box,
                        "updated_at": time.time(),
                    }
                    set_plate_overlay(False, label.upper(), "", box, object_id=object_id)

            return

        update_type = data.get("type")
        last_mqtt_update = str(update_type or "unknown")

        # ====================================================
        # FACE
        # ====================================================

        if update_type == "face":
            face_count += 1

            name = data.get(
                "name"
            )

            if is_unknown(name):
                with state_lock:
                    unknown_face_until = (
                        time.time()
                        + DISPLAY_SECONDS
                    )

                face_object_id = payload_object_id(data) or recent_person_object_id
                set_face_overlay(False, "UNKNOWN FACE", payload_box(data), object_id=face_object_id)
                detection_beep("face_unknown", False)
                warning_sound()
                save_unknown_event(
                    "UNKNOWN FACE",
                    "Unknown Person",
                    identifier=face_object_id,
                    object_id=face_object_id,
                )

                return

            display_name = clean_name(
                name
            )

            with state_lock:
                recognized_name = (
                    display_name
                )

                recognized_until = (
                    time.time()
                    + DISPLAY_SECONDS
                )

                unknown_face_until = 0

            face_object_id = payload_object_id(data) or recent_person_object_id
            mark_person_recognized(face_object_id)
            set_face_overlay(True, display_name, payload_box(data), object_id=face_object_id)
            detection_beep("face_" + display_name.lower(), True)
            queue_telegram_alert(
                "known_face",
                f"✅ {display_name} detected at {CAMERA_NAME}\n{time.strftime('%Y-%m-%d %H:%M:%S')}",
                "known_face:" + display_name.lower(),
            )

            first_name = (
                display_name
                .split()[0]
            )

            speak(
                (
                    f"Welcome, {first_name}. "
                    "Identity verified."
                ),
                (
                    "face_"
                    + display_name.lower()
                ),
            )

        # ====================================================
        # LPR
        # ====================================================

        elif update_type == "lpr":
            plate = data.get(
                "plate"
            )

            if not plate:
                return

            plate_count += 1

            plate = (
                str(plate)
                .replace(" ", "")
                .upper()
            )

            known_plates = normalize_known_plate_lookup(load_known_plates())

            mqtt_vehicle = (
                data.get("name")
            )

            if plate in known_plates:
                vehicle = (
                    known_plates[plate]
                )

                known = True

            elif (
                mqtt_vehicle
                and not is_unknown(
                    mqtt_vehicle
                )
            ):
                vehicle = (
                    mqtt_vehicle
                )

                known = True

            else:
                vehicle = (
                    "Unknown Vehicle"
                )

                known = False

            vehicle = (
                str(vehicle)
                .replace("_", " ")
                .strip()
            )

            with state_lock:
                current_plate = plate

                current_vehicle = (
                    vehicle
                )

                plate_until = (
                    time.time()
                    + DISPLAY_SECONDS
                )

                if known:
                    unknown_vehicle_until = 0

                else:
                    unknown_vehicle_until = (
                        time.time()
                        + DISPLAY_SECONDS
                    )

            vehicle_object_id = payload_object_id(data) or recent_vehicle_object_id
            set_plate_overlay(
                known,
                vehicle,
                plate,
                payload_box(data),
                object_id=vehicle_object_id,
            )
            detection_beep("plate_" + plate, known)

            if known:
                queue_telegram_alert(
                    "known_vehicle",
                    f"✅ Authorized vehicle detected at {CAMERA_NAME}\n{vehicle}\nPlate: {plate}\n{time.strftime('%Y-%m-%d %H:%M:%S')}",
                    "known_vehicle:" + plate,
                )
                speak(
                    (
                        "Authorized vehicle "
                        f"detected. {vehicle}."
                    ),
                    (
                        "plate_"
                        + plate
                    ),
                )

            else:
                vehicle_object_id = payload_object_id(data) or recent_vehicle_object_id
                save_unknown_event(
                    "UNKNOWN PLATE",
                    "Unknown Vehicle",
                    identifier=plate,
                    object_id=vehicle_object_id,
                )
                warning_sound()

    except Exception as e:
        print(
            "MQTT message error:",
            e
        )


def start_mqtt():
    try:
        client = mqtt.Client()

        client.on_connect = (
            on_connect
        )

        client.on_disconnect = (
            on_disconnect
        )

        client.on_message = (
            on_message
        )

        client.connect(
            MQTT_HOST,
            MQTT_PORT,
            60
        )

        client.loop_start()

        return client

    except Exception as e:
        print(
            "MQTT connection error:",
            e
        )

        return None


mqtt_client = start_mqtt()



PAIR_DEVICE_URL = "https://qfnxwuejfotofuxlyqjd.supabase.co/functions/v1/pair-edge-device"

def pair_windows_device(pairing_code, device_name="Windows Edge"):
    """Pair this Windows installation once, then save its device credential locally."""
    code = str(pairing_code or "").strip().upper()
    if not code:
        return {"ok": False, "error": "Pairing code required"}
    try:
        r = requests.post(PAIR_DEVICE_URL, json={
            "code": code,
            "device_name": device_name,
            "app_version": "V11.0.2"
        }, timeout=15)
        data = r.json()
        if not r.ok:
            return {"ok": False, "error": data.get("error", "Pairing failed")}
        tmp_cfg = EDGE_AGENT_CONFIG_FILE + ".tmp"
        with open(tmp_cfg, "w", encoding="utf-8") as f:
            json.dump({
                "device_name": device_name,
                "device_id": data["device_id"],
                "device_token": data["device_token"]
            }, f, indent=2)
        os.replace(tmp_cfg, EDGE_AGENT_CONFIG_FILE)
        threading.Thread(target=cloud_control_worker, daemon=True).start()
        return {"ok": True, "device_id": data["device_id"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ============================================================
# SAAS EDGE AGENT / CLOUD ENTITLEMENTS
# ============================================================

CLOUD_CONTROL_URL = "https://qfnxwuejfotofuxlyqjd.supabase.co/functions/v1/edge-agent-control"
CLOUD_POLL_SECONDS = 30
cloud_lock = threading.Lock()
cloud_state = {
    "connected": False,
    "licensed": False,
    "organization_status": "unknown",
    "plan_code": "unknown",
    "features": {},
    "usage": {"cameras": 0, "drones": 0},
    "limits": {"cameras": None, "drones": None},
    "last_success": 0.0,
    "last_error": "",
}

def load_edge_agent_config():
    try:
        with open(EDGE_AGENT_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print("Edge Agent config error:", e)
        return {}

def cloud_feature_enabled(feature_key):
    with cloud_lock:
        if not cloud_state.get("licensed"):
            return False
        feature = (cloud_state.get("features") or {}).get(feature_key) or {}
        return bool(feature.get("enabled"))

def cloud_status_snapshot():
    with cloud_lock:
        data = dict(cloud_state)
        data["features"] = dict(cloud_state.get("features") or {})
        data["usage"] = dict(cloud_state.get("usage") or {})
        data["limits"] = dict(cloud_state.get("limits") or {})
    data["drone_ai_allowed"] = cloud_feature_enabled("drone_ai")
    data["camera_ai_allowed"] = cloud_feature_enabled("camera_ai")
    data["face_ai_allowed"] = cloud_feature_enabled("face_ai")
    data["lpr_allowed"] = cloud_feature_enabled("lpr")
    data["drone_live_allowed"] = cloud_feature_enabled("drone_live")
    data["drone_tracking_allowed"] = cloud_feature_enabled("drone_tracking")
    return data

def force_drone_ai_off(reason="Cloud entitlement disabled"):
    global drone_enabled_runtime, tracking_assist_enabled, drone_tracking
    if mqtt_client is not None and mqtt_connected:
        try:
            mqtt_client.publish(DRONE_SET_TOPIC, "OFF")
        except Exception as e:
            print("Cloud Drone AI disable publish error:", e)
    drone_enabled_runtime = False
    tracking_assist_enabled = False
    with drone_tracking_lock:
        drone_tracking = {
            "active": False, "object_id": "", "label": "", "known": False,
            "box": None, "direction": "WAITING", "updated_at": 0.0,
        }
    print("Drone AI forced OFF:", reason)

def cloud_control_worker():
    config = load_edge_agent_config()
    token = str(config.get("device_token") or "").strip()
    if not token:
        with cloud_lock:
            cloud_state["last_error"] = "Missing device_token in edge_agent_config.json"
        print("Cloud Edge Agent disabled: missing device token.")
        return

    while True:
        try:
            response = requests.post(
                CLOUD_CONTROL_URL,
                headers={"x-device-token": token},
                json={"app_version": "V11.0.2"},
                timeout=12,
            )
            response.raise_for_status()
            data = response.json()
            org_active = str(data.get("organization_status") or "").lower() in {"active", "trial"}
            features = data.get("features") if isinstance(data.get("features"), dict) else {}
            with cloud_lock:
                cloud_state.update({
                    "connected": True,
                    "licensed": org_active,
                    "organization_status": str(data.get("organization_status") or "unknown"),
                    "plan_code": str(data.get("plan_code") or "unknown"),
                    "features": features,
                    "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {"cameras": 0, "drones": 0},
                    "limits": data.get("limits") if isinstance(data.get("limits"), dict) else {"cameras": None, "drones": None},
                    "last_success": time.time(),
                    "last_error": "",
                })

            # Enforce cloud subscription controls locally.
            drone_ai_allowed = org_active and bool((features.get("drone_ai") or {}).get("enabled"))
            tracking_allowed = org_active and bool((features.get("drone_tracking") or {}).get("enabled"))
            camera_ai_allowed = org_active and bool((features.get("camera_ai") or {}).get("enabled"))

            if not drone_ai_allowed and (drone_enabled_runtime or tracking_assist_enabled):
                force_drone_ai_off("SaaS Drone AI entitlement is OFF")
            elif not tracking_allowed and tracking_assist_enabled:
                force_drone_ai_off("SaaS Drone Tracking entitlement is OFF")

            if not camera_ai_allowed and camera_enabled_runtime:
                if mqtt_client is not None and mqtt_connected:
                    try:
                        mqtt_client.publish(CAMERA_SET_TOPIC, "OFF")
                    except Exception as e:
                        print("Cloud Camera AI disable publish error:", e)
                camera_enabled_runtime = False
                print("Camera AI forced OFF: SaaS entitlement is OFF")
        except Exception as e:
            with cloud_lock:
                cloud_state["connected"] = False
                cloud_state["last_error"] = str(e)
            print("Cloud Edge Agent poll error:", e)

        time.sleep(CLOUD_POLL_SECONDS)

threading.Thread(target=cloud_control_worker, daemon=True).start()


# ============================================================
# EVENT HISTORY
# ============================================================

def get_events(limit=8):
    if not os.path.exists(
        EVENT_LOG
    ):
        return []

    try:
        with open(
            EVENT_LOG,
            "r",
            encoding="utf-8"
        ) as f:
            rows = list(
                csv.DictReader(f)
            )

        rows.reverse()

        if limit is None:
            return rows

        return rows[:limit]

    except Exception as e:
        print(
            "History error:",
            e
        )

        return []


# ============================================================
# VIDEO STREAM
# ============================================================

def generate_frames():
    while True:
        jpg = None

        with jpeg_lock:
            if latest_jpeg is not None:
                jpg = latest_jpeg

        if jpg is None:
            time.sleep(0.1)

            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + jpg
            + b"\r\n"
        )

        time.sleep(
            1.0 / MAIN_STREAM_FPS
        )


# ============================================================
# BIOMETRIC ENROLLMENT HELPERS
# ============================================================

def update_enrollment(**kwargs):
    with enroll_lock:
        for key, value in (
            kwargs.items()
        ):
            enrollment[key] = value


def enrollment_cancelled():
    with enroll_lock:
        return bool(
            enrollment.get(
                "cancel"
            )
        )


def inspect_face(frame):
    """
    Returns:
        ok
        message
        face crop
    """

    if frame is None:
        return (
            False,
            "Camera frame unavailable.",
            None,
        )

    gray = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2GRAY
    )

    faces = (
        face_detector
        .detectMultiScale(
            gray,
            scaleFactor=1.12,
            minNeighbors=6,
            minSize=(90, 90),
        )
    )

    if len(faces) == 0:
        return (
            False,
            "No face detected. Move into the scanner.",
            None,
        )

    if len(faces) > 1:
        return (
            False,
            "More than one face detected. Only one person can be enrolled.",
            None,
        )

    x, y, w, h = faces[0]

    if (
        w < 100
        or h < 100
    ):
        return (
            False,
            "Move closer to the camera.",
            None,
        )

    padding_x = int(
        w * 0.45
    )

    padding_y = int(
        h * 0.55
    )

    x1 = max(
        0,
        x - padding_x
    )

    y1 = max(
        0,
        y - padding_y
    )

    x2 = min(
        frame.shape[1],
        x + w + padding_x
    )

    y2 = min(
        frame.shape[0],
        y + h + padding_y
    )

    crop = frame[
        y1:y2,
        x1:x2
    ]

    if crop.size == 0:
        return (
            False,
            "Could not capture face region.",
            None,
        )

    gray_crop = cv2.cvtColor(
        crop,
        cv2.COLOR_BGR2GRAY
    )

    brightness = float(
        gray_crop.mean()
    )

    sharpness = float(
        cv2.Laplacian(
            gray_crop,
            cv2.CV_64F
        ).var()
    )

    if brightness < 35:
        return (
            False,
            "Face is too dark. Improve lighting.",
            None,
        )

    if sharpness < 25:
        return (
            False,
            "Image is blurry. Hold still.",
            None,
        )

    return (
        True,
        "Face quality accepted.",
        crop,
    )


def register_face_sample(
    name,
    image,
    sample_number
):
    safe_file_name = (
        "face_enroll_"
        + str(
            int(
                time.time()
                * 1000
            )
        )
        + "_"
        + str(sample_number)
        + ".jpg"
    )

    host_path = os.path.join(
        tempfile.gettempdir(),
        safe_file_name
    )

    container_path = (
        "/tmp/"
        + safe_file_name
    )

    written = cv2.imwrite(
        host_path,
        image,
        [
            int(
                cv2.IMWRITE_JPEG_QUALITY
            ),
            92,
        ]
    )

    if not written:
        raise RuntimeError(
            "Could not create face sample."
        )

    try:
        copy_result = run_background_command(
            [
                "docker",
                "cp",
                host_path,
                (
                    "frigate:"
                    + container_path
                ),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        if (
            copy_result.returncode
            != 0
        ):
            raise RuntimeError(
                "Could not copy image "
                "to Frigate: "
                + copy_result.stderr
            )

        encoded_name = (
            urllib.parse.quote(
                name.strip(),
                safe=""
            )
        )

        result = run_background_command(
            [
                "docker",
                "exec",
                "frigate",
                "curl",
                "-s",
                "-S",
                "-X",
                "POST",
                "-F",
                (
                    "file=@"
                    + container_path
                ),
                (
                    "http://127.0.0.1:5000"
                    "/api/faces/"
                    + encoded_name
                    + "/register"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if (
            result.returncode
            != 0
        ):
            raise RuntimeError(
                result.stderr
                or (
                    "Frigate face "
                    "registration failed."
                )
            )

        print(
            "Face sample",
            sample_number,
            "response:",
            result.stdout
        )

    finally:
        try:
            run_background_command(
                [
                    "docker",
                    "exec",
                    "frigate",
                    "rm",
                    "-f",
                    container_path,
                ],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

        try:
            os.remove(
                host_path
            )
        except Exception:
            pass


def enrollment_worker(name, source="camera"):
    try:
        update_enrollment(
            running=True,
            cancel=False,
            name=name,
            source=source,
            stage="INITIALIZING",
            message=(
                "Initializing biometric "
                "enrollment scanner..."
            ),
            progress=2,
            sample=0,
            success=False,
            error="",
        )

        time.sleep(0.25)

        successful_samples = 0

        for index, instruction in enumerate(
            ENROLL_STEPS
        ):
            if enrollment_cancelled():
                raise RuntimeError(
                    "Enrollment cancelled."
                )

            sample_number = (
                index + 1
            )

            start_progress = int(
                (
                    index
                    / ENROLL_SAMPLES
                )
                * 100
            )

            update_enrollment(
                stage=instruction,
                message=(
                    instruction
                    + " — hold position."
                ),
                sample=sample_number,
                progress=start_progress,
            )

            # Give the user time to adjust.
            time.sleep(0.65)

            accepted_crop = None

            # Look for a good frame for several seconds.
            for attempt in range(20):
                if enrollment_cancelled():
                    raise RuntimeError(
                        "Enrollment cancelled."
                    )

                frame = None

                if source == "drone":
                    with drone_frame_lock:
                        if drone_latest_frame is not None:
                            frame = drone_latest_frame.copy()
                else:
                    with frame_lock:
                        if latest_frame is not None:
                            frame = latest_frame.copy()

                ok, message, crop = (
                    inspect_face(frame)
                )

                update_enrollment(
                    message=message
                )

                if ok:
                    accepted_crop = crop

                    break

                time.sleep(0.10)

            if accepted_crop is None:
                raise RuntimeError(
                    (
                        "Could not obtain a "
                        "clear face sample. "
                        "Try again with better "
                        "lighting and keep one "
                        "person in view."
                    )
                )

            update_enrollment(
                stage="BIOMETRIC CAPTURE",
                message=(
                    "Capturing sample "
                    f"{sample_number} "
                    f"of {ENROLL_SAMPLES}..."
                ),
                progress=min(
                    95,
                    start_progress + 10
                ),
            )

            time.sleep(0.12)

            update_enrollment(
                stage="REGISTERING",
                message=(
                    "Encrypting/registering "
                    "facial sample "
                    f"{sample_number}..."
                ),
                progress=min(
                    98,
                    start_progress + 15
                ),
            )

            register_face_sample(
                name,
                accepted_crop,
                sample_number,
            )

            successful_samples += 1

            update_enrollment(
                stage="SAMPLE ACCEPTED",
                message=(
                    f"Biometric sample "
                    f"{sample_number} accepted."
                ),
                progress=int(
                    (
                        sample_number
                        / ENROLL_SAMPLES
                    )
                    * 100
                ),
            )

            time.sleep(0.25)

        update_enrollment(
            running=False,
            cancel=False,
            stage="IDENTITY REGISTERED",
            message=(
                f"{name} enrolled successfully "
                f"with {successful_samples} "
                "face samples."
            ),
            progress=100,
            sample=successful_samples,
            success=True,
            error="",
        )

        speak(
            (
                f"{name} successfully "
                "added to face recognition."
            ),
            (
                "enrollment_"
                + name.lower()
            ),
        )

    except Exception as e:
        message = str(e)

        print(
            "Enrollment error:",
            message
        )

        update_enrollment(
            running=False,
            cancel=False,
            stage=(
                "CANCELLED"
                if "cancelled" in message.lower()
                else "ENROLLMENT FAILED"
            ),
            message=message,
            success=False,
            error=message,
        )


# ============================================================
# VEHICLE ENROLLMENT
# ============================================================

def save_vehicle(
    vehicle_name,
    plate
):
    vehicle_name = (
        str(vehicle_name)
        .strip()
    )

    plate = (
        str(plate)
        .replace(" ", "")
        .upper()
        .strip()
    )

    if len(vehicle_name) < 2:
        raise ValueError(
            "Enter a vehicle name."
        )

    if len(plate) < 2:
        raise ValueError(
            "Enter a valid plate number."
        )

    known = (
        load_known_plates()
    )

    known[plate] = (
        vehicle_name
    )

    save_known_plates(
        known
    )

    return plate


# ============================================================
# FRIGATE FACE LIBRARY
# ============================================================

def get_frigate_faces():
    """
    Tries Frigate's internal /api/faces endpoint.

    Different Frigate builds can return slightly
    different JSON structures, so this normalizes
    common formats.
    """

    try:
        result = run_background_command(
            [
                "docker",
                "exec",
                "frigate",
                "curl",
                "-s",
                "-S",
                "http://127.0.0.1:5000/api/faces",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        if (
            result.returncode
            != 0
        ):
            return {
                "ok": False,
                "faces": [],
                "error": (
                    "Could not read "
                    "Frigate face library."
                ),
            }

        raw = (
            result.stdout
            .strip()
        )

        if not raw:
            return {
                "ok": False,
                "faces": [],
                "error": (
                    "Frigate returned "
                    "an empty face library."
                ),
            }

        data = json.loads(raw)

        names = []

        if isinstance(
            data,
            list
        ):
            for item in data:
                if isinstance(
                    item,
                    str
                ):
                    names.append(
                        item
                    )

                elif isinstance(
                    item,
                    dict
                ):
                    name = (
                        item.get("name")
                        or item.get("id")
                        or item.get(
                            "label"
                        )
                    )

                    if name:
                        names.append(
                            str(name)
                        )

        elif isinstance(
            data,
            dict
        ):
            if (
                "faces" in data
                and isinstance(
                    data["faces"],
                    list
                )
            ):
                for item in data[
                    "faces"
                ]:
                    if isinstance(
                        item,
                        str
                    ):
                        names.append(
                            item
                        )

                    elif isinstance(
                        item,
                        dict
                    ):
                        name = (
                            item.get(
                                "name"
                            )
                            or item.get(
                                "id"
                            )
                        )

                        if name:
                            names.append(
                                str(name)
                            )

            else:
                for key in (
                    data.keys()
                ):
                    names.append(
                        str(key)
                    )

        names = sorted(
            set(names)
        )

        return {
            "ok": True,
            "faces": names,
            "error": "",
        }

    except Exception as e:
        return {
            "ok": False,
            "faces": [],
            "error": str(e),
        }


# ============================================================
# API ROUTES
# ============================================================

@app.route(
    "/api/status"
)
def api_status():
    now = time.time()

    with state_lock:
        face = (
            recognized_name
            if now < recognized_until
            else ""
        )

        plate = (
            current_plate
            if now < plate_until
            else ""
        )

        vehicle = (
            current_vehicle
            if now < plate_until
            else ""
        )

        unknown_face = (
            now
            < unknown_face_until
        )

        unknown_vehicle = (
            now
            < unknown_vehicle_until
        )

    active_faces, active_vehicles = active_overlay_snapshot()

    return jsonify({
        "camera": camera_connected,
        "mqtt": mqtt_connected,
        "mqtt_messages": mqtt_message_count,
        "last_mqtt_update": last_mqtt_update,
        "last_mqtt_age": (round(time.time() - last_mqtt_at, 1) if last_mqtt_at else None),

        "face": face,
        "plate": plate,
        "vehicle": vehicle,

        "unknown_face": unknown_face,
        "unknown_vehicle": unknown_vehicle,

        "active_faces": active_faces,
        "active_vehicles": active_vehicles,

        "face_count": face_count,
        "plate_count": plate_count,

        "total_events": (
            face_count
            + plate_count
        ),
    })


@app.route(
    "/api/enroll/face",
    methods=["POST"]
)
def api_enroll_face():
    if not cloud_feature_enabled("face_ai"):
        return jsonify({"ok": False, "error": "Face AI is not included in your current plan. Upgrade your plan to use face enrollment."}), 403
    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    name = (
        str(
            data.get(
                "name",
                ""
            )
        )
        .strip()
    )

    source = str(data.get("source", "camera") or "camera").strip().lower()
    if source not in {"camera", "drone"}:
        source = "camera"
    if source == "drone" and not drone_enabled_runtime:
        return jsonify({"ok": False, "error": "Turn DRONE AI ON before enrolling a face from the drone."}), 400

    if len(name) < 2:
        return jsonify({
            "ok": False,
            "error": (
                "Enter the person's name."
            ),
        }), 400

    with enroll_lock:
        if enrollment[
            "running"
        ]:
            return jsonify({
                "ok": False,
                "error": (
                    "A face enrollment "
                    "is already running."
                ),
            }), 409

    update_enrollment(
        running=True,
        cancel=False,
        name=name,
        source=source,
        stage="STARTING",
        message=(
            "Starting biometric scanner..."
        ),
        progress=1,
        sample=0,
        success=False,
        error="",
    )

    threading.Thread(
        target=enrollment_worker,
        args=(name, source),
        daemon=True,
    ).start()

    return jsonify({
        "ok": True
    })


@app.route(
    "/api/enroll/status"
)
def api_enroll_status():
    with enroll_lock:
        data = dict(
            enrollment
        )

    return jsonify(data)


@app.route(
    "/api/enroll/cancel",
    methods=["POST"]
)
def api_cancel_enrollment():
    with enroll_lock:
        if enrollment[
            "running"
        ]:
            enrollment[
                "cancel"
            ] = True

    return jsonify({
        "ok": True
    })


@app.route(
    "/api/add_vehicle",
    methods=["POST"]
)
def api_add_vehicle():
    if not cloud_feature_enabled("lpr"):
        return jsonify({"ok": False, "error": "License Plate Recognition is not included in your current plan. Upgrade your plan to add vehicles."}), 403
    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    try:
        vehicle_name = (
            data.get(
                "vehicle",
                ""
            )
        )

        plate = (
            data.get(
                "plate",
                ""
            )
        )
        source = str(data.get("source", "camera") or "camera").strip().lower()
        if source not in {"camera", "drone"}:
            source = "camera"

        # If no plate was typed, use the most recent LPR result from the selected source.
        if not str(plate or "").strip():
            if source == "drone":
                candidates = [x for x in drone_overlay_snapshot() if x.get("plate")]
                if candidates:
                    plate = candidates[0].get("plate", "")
            else:
                with state_lock:
                    plate = current_plate or ""

        if not str(plate or "").strip():
            raise ValueError(
                "No plate available from the selected source. Point the camera at the plate until LPR reads it, or type the plate manually."
            )

        normalized_plate = (
            save_vehicle(
                vehicle_name,
                plate,
            )
        )

        return jsonify({
            "ok": True,
            "plate": normalized_plate,
            "vehicle": (
                str(vehicle_name)
                .strip()
            ),
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
        }), 400


@app.route(
    "/api/known_vehicles"
)
def api_known_vehicles():
    return jsonify(
        load_known_plates()
    )


@app.route(
    "/api/face_library"
)
def api_face_library():
    return jsonify(
        get_frigate_faces()
    )


# ============================================================
# OBJECT AI CONTROL / RECENT OBJECTS
# ============================================================

@app.route("/api/object_ai/status")
def api_object_ai_status():
    return jsonify({"ok": True, "enabled": bool(object_ai_enabled_runtime), "objects": object_snapshot()})

@app.route("/api/object_ai/toggle", methods=["POST"])
def api_object_ai_toggle():
    global object_ai_enabled_runtime
    data = request.get_json(silent=True) or {}
    requested = bool(data.get("enabled"))
    if requested and not cloud_feature_enabled("camera_ai"):
        return jsonify({"ok": False, "error": "Object/Camera AI is not included in your current plan."}), 403
    object_ai_enabled_runtime = requested
    if not object_ai_enabled_runtime:
        with object_ai_lock:
            recent_objects.clear()
    return jsonify({"ok": True, "enabled": object_ai_enabled_runtime})

# ============================================================
# CAMERA RUNTIME CONTROL
# ============================================================

@app.route("/api/camera/status")
def api_camera_status():
    return jsonify({
        "ok": True,
        "enabled": bool(camera_enabled_runtime),
        "connected": bool(camera_connected),
        "mqtt": bool(mqtt_connected),
    })


@app.route("/api/camera/toggle", methods=["POST"])
def api_camera_toggle():
    global camera_enabled_runtime
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))

    if enabled and not cloud_feature_enabled("camera_ai"):
        return jsonify({"ok": False, "error": "Camera AI is disabled by the SaaS subscription."}), 403

    if not mqtt_connected or mqtt_client is None:
        return jsonify({
            "ok": False,
            "error": "MQTT is offline. Camera control is unavailable.",
        }), 503

    payload = "ON" if enabled else "OFF"
    result = mqtt_client.publish(CAMERA_SET_TOPIC, payload)
    rc = getattr(result, "rc", 0)
    if rc != 0:
        return jsonify({
            "ok": False,
            "error": f"MQTT publish failed with code {rc}.",
        }), 500

    camera_enabled_runtime = enabled
    return jsonify({
        "ok": True,
        "enabled": enabled,
        "message": "Camera AI enabled." if enabled else "Camera AI disabled.",
    })


# ============================================================
# DRONE RUNTIME CONTROL
# ============================================================

@app.route("/api/drone/status")
def api_drone_status():
    return jsonify({
        "ok": True,
        "enabled": bool(drone_enabled_runtime),
        "mqtt": bool(mqtt_connected),
        "video": bool(drone_source_connected),
        "stream": DRONE_STREAM,
        "cloud_connected": bool(cloud_status_snapshot().get("connected")),
        "licensed": bool(cloud_feature_enabled("drone_ai")),
    })


@app.route("/api/drone/toggle", methods=["POST"])
def api_drone_toggle():
    global drone_enabled_runtime

    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))

    if enabled and not cloud_feature_enabled("drone_ai"):
        cloud = cloud_status_snapshot()
        return jsonify({
            "ok": False,
            "error": "Drone AI is disabled by the SaaS subscription.",
            "cloud_connected": bool(cloud.get("connected")),
            "organization_status": cloud.get("organization_status"),
        }), 403

    if not mqtt_connected or mqtt_client is None:
        return jsonify({
            "ok": False,
            "error": "MQTT is offline. Drone control is unavailable.",
        }), 503

    payload = "ON" if enabled else "OFF"
    result = mqtt_client.publish(DRONE_SET_TOPIC, payload)
    rc = getattr(result, "rc", 0)
    if rc != 0:
        return jsonify({
            "ok": False,
            "error": f"MQTT publish failed with code {rc}.",
        }), 500

    drone_enabled_runtime = enabled
    return jsonify({
        "ok": True,
        "enabled": enabled,
        "message": "Drone AI enabled." if enabled else "Drone AI disabled.",
    })


# ============================================================
# DRONE TRACKING ASSIST API
# ============================================================
@app.route("/api/drone/tracking/status")
def api_drone_tracking_status():
    return jsonify({
        "ok": True,
        **drone_tracking_snapshot(),
        "targets": drone_overlay_snapshot(),
    })

@app.route("/api/drone/tracking/toggle", methods=["POST"])
def api_drone_tracking_toggle():
    global tracking_assist_enabled, drone_tracking
    data = request.get_json(silent=True) or {}
    requested = bool(data.get("enabled"))
    if requested and not cloud_feature_enabled("drone_ai"):
        return jsonify({"ok": False, "error": "Drone AI is disabled by the SaaS subscription."}), 403
    if requested and not cloud_feature_enabled("drone_tracking"):
        return jsonify({"ok": False, "error": "Drone Tracking is disabled by the SaaS subscription."}), 403
    tracking_assist_enabled = requested
    if not tracking_assist_enabled:
        with drone_tracking_lock:
            drone_tracking = {"active": False, "object_id": "", "label": "", "known": False, "box": None, "direction": "WAITING", "updated_at": 0.0}
    return jsonify({"ok": True, "enabled": tracking_assist_enabled, "mode": "manual_guidance"})

@app.route("/api/cloud/pair", methods=["POST"])
def api_cloud_pair():
    data = request.get_json(silent=True) or {}
    result = pair_windows_device(data.get("code"), data.get("device_name") or "Windows Edge")
    return jsonify(result), (200 if result.get("ok") else 400)


@app.route("/api/cloud/status")
def api_cloud_status():
    return jsonify({"ok": True, **cloud_status_snapshot()})

@app.route("/api/cloud/can-add-source/<source_type>")
def api_cloud_can_add_source(source_type):
    source_type = str(source_type or "").lower()
    if source_type not in {"camera", "drone"}:
        return jsonify({"ok": False, "error": "Invalid source type."}), 400
    c = cloud_status_snapshot()
    usage_key = "cameras" if source_type == "camera" else "drones"
    feature_key = "camera_ai" if source_type == "camera" else "drone_live"
    used = int((c.get("usage") or {}).get(usage_key) or 0)
    limit = (c.get("limits") or {}).get(usage_key)
    allowed = bool(c.get("licensed")) and cloud_feature_enabled(feature_key) and (limit is None or used < int(limit))
    plan = str(c.get("plan_code") or "current").upper()
    if allowed:
        message = f"{source_type.title()} can be added ({used}/{limit if limit is not None else 'unlimited'} used)."
    elif limit is not None and used >= int(limit):
        message = f"{plan} plan allows a maximum of {limit} {usage_key}. Upgrade your plan to add more."
    else:
        message = f"{source_type.title()} access is not included in the {plan} plan."
    return jsonify({"ok": True, "allowed": allowed, "plan_code": c.get("plan_code"), "used": used, "limit": limit, "message": message})



# ============================================================
# V10.5 CAMERA + DRONE AUTO DISCOVERY
# ============================================================
DISCOVERY_PORTS=(554,8554,8556,1935,80,443)

def _lan_ip():
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:s.connect(("8.8.8.8",80));return s.getsockname()[0]
    except Exception:return "127.0.0.1"
    finally:s.close()

def _port(ip,p,t=.35):
    try:
        with socket.create_connection((ip,p),timeout=t):return True
    except Exception:return False

def _windows_neighbors():
    found={}
    try:
        p=run_background_command(["arp","-a"],capture_output=True,text=True,timeout=3)
        for line in (p.stdout or "").splitlines():
            m=re.search(r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})\s+",line)
            if m:
                ip,mac=m.group(1),m.group(2).lower()
                if ipaddress.ip_address(ip).is_private and not ip.endswith(".255"):found[ip]=mac
    except Exception:pass
    return found

def _probe_neighbor(item):
    ip,mac=item; ports=[p for p in DISCOVERY_PORTS if _port(ip,p)]
    if not ports:return None
    kind="camera_candidate" if 554 in ports else ("stream_candidate" if any(p in ports for p in (8554,8556,1935)) else "network_device")
    return {"ip":ip,"mac":mac,"ports":ports,"kind":kind,"confidence":"medium" if kind!="network_device" else "low"}

@app.route("/api/discovery/scan",methods=["POST"])
def discovery_scan():
    host=_lan_ip()
    try:net=ipaddress.ip_network(host+"/24",strict=False)
    except Exception:return jsonify({"ok":False,"error":"Local IPv4 network not found","devices":[]}),400
    if ipaddress.ip_address(host).is_loopback:
        return jsonify({"ok":False,"error":"No LAN connection detected","devices":[]}),400
    known={str(v.get("mac", "")).lower():name for name,v in _load_recovery_state().get("cameras",{}).items() if v.get("mac")}
    neighbors={ip:mac for ip,mac in _windows_neighbors().items() if ipaddress.ip_address(ip) in net}
    # Probe uncached addresses too; ARP only contains recently contacted devices.
    for address in net.hosts():
        if str(address)!=host:neighbors.setdefault(str(address),None)
    found=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
        futures=[ex.submit(_probe_neighbor,x) for x in neighbors.items()]
        done,_=concurrent.futures.wait(futures,timeout=20)
        for f in done:
            try:
                x=f.result()
                if x:found.append(x)
            except Exception:pass
    # Probing populates ARP even when the camera's stream service is closed.
    refreshed=_windows_neighbors()
    by_ip={x["ip"]:x for x in found}
    for ip,mac in refreshed.items():
        if ipaddress.ip_address(ip) not in net:continue
        if ip in by_ip:by_ip[ip]["mac"]=mac
        if mac.lower() in known:
            item=by_ip.get(ip)
            if item is None:
                item={"ip":ip,"mac":mac,"ports":[]};found.append(item)
            item.update({"kind":"known_camera", "confidence":"high", "camera_name":known[mac.lower()]})
    found.sort(key=lambda x:tuple(int(v) for v in x["ip"].split(".")))
    return jsonify({"ok":True,"host_ip":host,"network":str(net),"devices":found,"scanned_neighbors":len(neighbors),"scan_mode":"local_subnet"})

@app.route("/api/discovery/drone")
def discovery_drone():
    host=_lan_ip()
    return jsonify({"ok":True,"host_ip":host,"mediamtx_ready":_port("127.0.0.1",8556) or _port("127.0.0.1",1935),
      "publish_url":f"rtmp://{host}:1935/drone","local_rtsp_url":"rtsp://127.0.0.1:8556/drone"})

@app.route("/api/discovery/drone/test")
def discovery_drone_test():
    if not _port("127.0.0.1",8556,.15):
        return jsonify({"ok":False,"state":"offline","message":"Drone offline — ready to connect."}),200
    ok=_test_rtsp("rtsp://127.0.0.1:8556/drone")
    return jsonify({"ok":ok,"state":"online" if ok else "waiting","message":"Drone stream detected." if ok else "Drone service ready — waiting for live video."}),200

@app.route("/setup/discover")
def setup_discover():
    return """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Auto Discovery</title>
<style>body{font-family:Arial;background:#071019;color:#eef8ff}.w{max-width:900px;margin:50px auto}.c{background:#0c1924;border:1px solid #1d4258;border-radius:18px;padding:25px;margin:18px}button{background:#16a8ff;color:white;border:0;border-radius:9px;padding:12px 18px;font-weight:800}.d{padding:12px;border-top:1px solid #18384b}code{color:#7dffc1}p{color:#96afbf}</style></head>
<body><div class=w><div class=c><p>AI SECURITY COMMAND CENTER · V10.5</p><h1>Automatic Device Discovery</h1><p>Scan the local network for camera and streaming candidates. Video is verified separately before onboarding.</p><button onclick=s()>Scan network</button><div id=x></div></div>
<div class=c><h2>Drone</h2><div id=z>Checking…</div><br><button onclick=t()>Test drone stream</button></div></div>
<script>async function s(){x.innerHTML='<p>Scanning nearby devices…</p>';const c=new AbortController();const timer=setTimeout(()=>c.abort(),30000);try{let r=await fetch('/api/discovery/scan',{method:'POST',signal:c.signal});let d=await r.json();x.innerHTML=`<p>Scan complete · PC: ${d.host_ip||''} · Network: ${d.network||''} · ${d.devices?.length||0} candidate(s)</p>`;(d.devices||[]).forEach(v=>x.innerHTML+=`<div class=d><b>${v.ip}</b> · ${v.kind}<br>Ports: ${v.ports.join(', ')} ${v.mac?'· '+v.mac:''}</div>`);if(!(d.devices||[]).length)x.innerHTML+='<p>No stream candidates found yet. Make sure the camera is online and RTSP is enabled.</p>'}catch(e){x.innerHTML='<p>Scan timed out safely. Try once more after confirming the camera is online.</p>'}finally{clearTimeout(timer)}}
async function q(){let d=await(await fetch('/api/discovery/drone')).json();z.innerHTML=`DJI/controller publish address: <code>${d.publish_url}</code><br>Local AI stream: <code>${d.local_rtsp_url}</code><br>${d.mediamtx_ready?'Streaming service ready.':'Streaming service not running.'}`}
async function t(){let d=await(await fetch('/api/discovery/drone/test')).json();alert(d.message)}q()</script></body></html>"""
# ============================================================
# V10.5 PROFESSIONAL CAMERA ONBOARDING
# ============================================================
def _edge_token():
    try:
        with open(EDGE_AGENT_CONFIG_FILE, "r", encoding="utf-8") as f:
            return str((json.load(f) or {}).get("device_token") or "")
    except Exception:
        return ""

def _safe_camera_slug(name):
    import re
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(name or "camera").strip()).strip("_").lower()
    return (s or "camera")[:40]

def _test_rtsp(url):
    cap = cv2.VideoCapture(str(url), cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, frame = cap.read()
        return bool(ok and frame is not None and getattr(frame, "size", 0) > 0)
    finally:
        cap.release()

def _cloud_source(method="GET", payload=None):
    token = _edge_token()
    if not token:
        return {"ok": False, "error": "Pair this Windows device to your customer account first."}
    try:
        r = requests.request(method, EDGE_SOURCE_CONTROL_URL, headers={"x-device-token": token, "content-type":"application/json"},
                             json=payload or {}, timeout=12)
        try: data=r.json()
        except Exception: data={"error": r.text[:300]}
        data["http_status"]=r.status_code
        return data
    except Exception as e:
        return {"ok": False, "error": f"Cloud source service unavailable: {e}"}

def _write_managed_frigate(camera_name, source_url):
    # Customer credentials remain on this PC. The generated file is not uploaded to the SaaS.
    import yaml
    cfg = {
      "mqtt":{"host":"host.docker.internal","port":1883},
      "go2rtc":{"streams":{camera_name: source_url}},
      "detectors":{"cpu1":{"type":"cpu"}},
      "objects":{"track":["person","car","motorcycle"]},
      "cameras":{camera_name:{
        "ffmpeg":{"inputs":[
          {"path":source_url,"roles":["detect"]},
          {"path":f"rtsp://127.0.0.1:8554/{camera_name}","input_args":"preset-rtsp-restream","roles":["record"]}
        ]},
        "detect":{"enabled":True},
        "record":{"enabled":False}
      }}
    }
    os.makedirs(MANAGED_FRIGATE_DIR, exist_ok=True)
    tmp=MANAGED_FRIGATE_CONFIG+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        yaml.safe_dump(cfg,f,sort_keys=False)
    os.replace(tmp,MANAGED_FRIGATE_CONFIG)

def _restart_frigate():
    try:
        p=run_background_command(["docker","restart","frigate"],capture_output=True,text=True,timeout=45)
        return p.returncode==0, (p.stdout or p.stderr).strip()
    except Exception as e:
        return False,str(e)

@app.route("/api/setup/cameras")
def api_setup_cameras():
    return jsonify(_cloud_source("GET"))

@app.route("/api/setup/camera/test", methods=["POST"])
def api_setup_camera_test():
    data=request.get_json(silent=True) or {}
    url=str(data.get("rtsp_url") or "").strip()
    if not url.lower().startswith(("rtsp://","rtsps://")):
        return jsonify({"ok":False,"error":"Enter a valid RTSP camera address."}),400
    ok=_test_rtsp(url)
    return jsonify({"ok":ok,"message":"Camera stream connected successfully." if ok else "Could not open the camera stream. Check the address, credentials and camera RTSP setting."}), (200 if ok else 400)

@app.route("/api/setup/camera", methods=["POST"])
def api_setup_camera():
    global CAMERA_NAME, STREAM, CAMERA_STATE_TOPIC, CAMERA_SET_TOPIC
    data=request.get_json(silent=True) or {}
    display=str(data.get("name") or "Camera").strip()[:80]
    url=str(data.get("rtsp_url") or "").strip()
    if not url.lower().startswith(("rtsp://","rtsps://")):
        return jsonify({"ok":False,"error":"A valid RTSP address is required."}),400
    allowed=requests.get("http://127.0.0.1:%d/api/cloud/can-add-source/camera"%PORT,timeout=4).json()
    if not allowed.get("allowed"):
        return jsonify({"ok":False,"error":allowed.get("message") or "Your plan does not allow another camera."}),403
    if not _test_rtsp(url):
        return jsonify({"ok":False,"error":"Camera test failed. Nothing was changed."}),400
    slug=_safe_camera_slug(display)
    cloud=_cloud_source("POST",{"source_type":"camera","name":display})
    if not cloud.get("ok"):
        return jsonify({"ok":False,"error":cloud.get("error") or "Cloud registration failed."}),409
    try:
        _write_managed_frigate(slug,url)
        settings=load_local_settings();settings.update({"camera_name":slug,"camera_stream":f"rtsp://localhost:8554/{slug}","camera_display_name":display})
        tmp=LOCAL_SETTINGS_FILE+".tmp"
        with open(tmp,"w",encoding="utf-8") as f: json.dump(settings,f,indent=2)
        os.replace(tmp,LOCAL_SETTINGS_FILE)
        CAMERA_NAME=slug;STREAM=f"rtsp://localhost:8554/{slug}"
        CAMERA_STATE_TOPIC=f"frigate/{slug}/enabled/state";CAMERA_SET_TOPIC=f"frigate/{slug}/enabled/set"
        restarted,msg=_restart_frigate()
        return jsonify({"ok":True,"source":cloud.get("source"),"camera_name":slug,"frigate_restarted":restarted,
                        "message":"Camera added. Frigate restarted." if restarted else "Camera saved. Restart Frigate to activate it.",
                        "restart_detail":msg})
    except Exception as e:
        # Roll back cloud registration if local setup fails.
        sid=((cloud.get("source") or {}).get("id"))
        if sid:_cloud_source("DELETE",{"id":sid})
        return jsonify({"ok":False,"error":f"Camera setup failed safely: {e}"}),500

@app.route("/setup/camera")
def camera_setup_page():
    return """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>Add Camera — AI Security Command Center</title><style>
body{font-family:Arial;background:#071019;color:#eaf6ff;margin:0}.w{max-width:760px;margin:55px auto;padding:28px}
.card{background:#0b1823;border:1px solid #1c4056;border-radius:18px;padding:28px;box-shadow:0 30px 80px #0007}
h1{margin-top:0}p{color:#93adbd;line-height:1.55}label{display:block;margin:18px 0 7px;font-weight:700}
input{box-sizing:border-box;width:100%;padding:14px;border-radius:9px;border:1px solid #31536a;background:#07131c;color:white}
button{margin-top:18px;padding:13px 18px;border:0;border-radius:9px;font-weight:800;cursor:pointer}
.primary{background:#18a9ff;color:white}.secondary{background:#183044;color:#dff5ff;margin-right:8px}
#msg{margin-top:18px;padding:13px;border-radius:9px;display:none}.ok{display:block!important;background:#0d392b;color:#80ffc2}.bad{display:block!important;background:#431d24;color:#ffb5bd}
small{color:#6f8d9f}</style></head><body><div class=w><div class=card>
<p>AI SECURITY COMMAND CENTER · V10.5</p><h1>Add a security camera</h1>
<p>This wizard tests the camera before changing anything, checks your subscription limit, registers the source with your account, creates a local Frigate configuration and restarts Frigate.</p>
<label>Camera name</label><input id=n placeholder="Front Door">
<label>RTSP address</label><input id=u type=password placeholder="rtsp://username:password@192.168.1.50:554/stream1">
<small>Credentials stay on this Windows PC and are not sent to the SaaS.</small><br>
<button class=secondary onclick="testCam()">Test connection</button><button class=primary onclick="addCam()">Test & Add Camera</button>
<div id=msg></div></div></div><script>
const m=(t,ok)=>{let x=document.getElementById('msg');x.className=ok?'ok':'bad';x.textContent=t}
async function call(path){let r=await fetch(path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:n.value,rtsp_url:u.value})});let d=await r.json();m(d.message||d.error||'Done',r.ok&&d.ok);return d}
function testCam(){m('Testing camera…',true);call('/api/setup/camera/test')}
function addCam(){m('Checking plan and configuring camera…',true);call('/api/setup/camera')}
</script></body></html>"""


# ============================================================
# TELEGRAM API
# ============================================================


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "ai-security-command-center", "version": "V11.0.2"})

@app.route("/api/system/readiness")
def api_system_readiness():
    """Customer-facing local readiness check for the V10 setup experience."""
    import socket
    checks = {}
    def port_open(host, port):
        try:
            with socket.create_connection((host, port), timeout=0.6):
                return True
        except Exception:
            return False
    checks["dashboard"] = True
    checks["frigate"] = port_open("127.0.0.1", 8971)
    checks["mqtt"] = port_open("127.0.0.1", 1883)
    checks["mediamtx"] = port_open("127.0.0.1", 8556) or port_open("127.0.0.1", 1935)
    cloud = cloud_status_snapshot()
    checks["cloud"] = bool(cloud.get("connected"))
    checks["paired"] = bool(cloud.get("licensed"))
    drone_required = bool((cloud.get("features") or {}).get("drone_live", {}).get("enabled"))
    required = [checks["dashboard"], checks["frigate"], checks["mqtt"], checks["cloud"], checks["paired"]]
    if drone_required:
        required.append(checks["mediamtx"])
    return jsonify({
        "ok": all(required),
        "version": "V11.0.2",
        "checks": checks,
        "plan": cloud.get("plan_code"),
        "organization_status": cloud.get("organization_status"),
        "limits": cloud.get("limits") or {},
        "usage": cloud.get("usage") or {},
        "last_cloud_error": cloud.get("last_error"),
    })

@app.route("/api/telegram/status")
def api_telegram_status():
    config = load_telegram_config()
    return jsonify({
        "enabled": bool(config.get("enabled")),
        "configured": telegram_ready(config),
        "known_face": bool(config.get("known_face", True)),
        "unknown_face": bool(config.get("unknown_face", True)),
        "known_vehicle": bool(config.get("known_vehicle", True)),
        "unknown_vehicle": bool(config.get("unknown_vehicle", True)),
        "cooldown_seconds": int(config.get("cooldown_seconds", 60) or 60),
    })


@app.route("/api/telegram/test", methods=["POST"])
def api_telegram_test():
    config = load_telegram_config()
    if not telegram_ready(config):
        return jsonify({"ok": False, "error": "Telegram is not configured."}), 400
    telegram_queue.put({
        "text": f"✅ AI Security test notification from {CAMERA_NAME}\n{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "snapshot": _snapshot_bytes(),
    })
    return jsonify({"ok": True})


# ============================================================
# EVENT DELETE API
# ============================================================

def delete_history_event(event_index):
    if not os.path.exists(EVENT_LOG):
        raise RuntimeError("Event history file does not exist.")

    with open(EVENT_LOG, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not fieldnames:
        raise RuntimeError("Event history has no headers.")

    newest_first = list(reversed(rows))
    if event_index < 0 or event_index >= len(newest_first):
        raise RuntimeError("Event could not be found.")

    event_to_delete = newest_first[event_index]
    snapshot = event_to_delete.get("Snapshot", "") or ""

    removed = False
    new_rows = []
    for row in rows:
        if not removed and row == event_to_delete:
            removed = True
            continue
        new_rows.append(row)

    if not removed:
        raise RuntimeError("Event could not be deleted.")

    with open(EVENT_LOG, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(new_rows)

    if snapshot:
        snapshot_name = os.path.basename(snapshot.replace("\\", "/"))
        snapshot_path = os.path.join(EVENT_FOLDER, snapshot_name)
        try:
            if os.path.exists(snapshot_path):
                os.remove(snapshot_path)
        except Exception as e:
            print("Could not delete snapshot:", e)

    return event_to_delete


@app.route("/api/events/<int:event_index>", methods=["DELETE"])
def api_delete_event(event_index):
    try:
        deleted = delete_history_event(event_index)
        return jsonify({"ok": True, "message": "Event deleted.", "event": deleted})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


def clear_all_history_events():
    """Remove all event-history rows and their locally saved snapshots."""
    deleted_count = 0
    snapshots = []
    fieldnames = ["Date", "Time", "Type", "Name", "Identifier", "Snapshot"]

    with event_log_lock:
        if os.path.exists(EVENT_LOG):
            with open(EVENT_LOG, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    fieldnames = reader.fieldnames
                rows = list(reader)

            deleted_count = len(rows)
            snapshots = [row.get("Snapshot", "") or "" for row in rows]

            with open(EVENT_LOG, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

    for snapshot in snapshots:
        if not snapshot:
            continue
        snapshot_name = os.path.basename(snapshot.replace("\\", "/"))
        snapshot_path = os.path.join(EVENT_FOLDER, snapshot_name)
        try:
            if os.path.exists(snapshot_path):
                os.remove(snapshot_path)
        except Exception as e:
            print("Could not delete snapshot during clear all:", e)

    # Reset the in-memory unknown dedupe state so a new object can be recorded immediately.
    with unknown_event_lock:
        seen_unknown_events.clear()
        pending_unknown_people.clear()
        recognized_person_ids.clear()

    return deleted_count


@app.route("/api/events", methods=["DELETE"])
def api_clear_all_events():
    try:
        deleted_count = clear_all_history_events()
        return jsonify({
            "ok": True,
            "message": "All security events cleared.",
            "deleted_count": deleted_count,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ============================================================
# HTML
# ============================================================

PAGE = r"""
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>
AI Security Command Center
</title>


<style>

* {
    box-sizing: border-box;
}

html,
body {
    margin: 0;
    min-height: 100%;
}

body {
    background: #02070c;
    color: #d9efff;

    font-family:
        Arial,
        Helvetica,
        sans-serif;

    overflow-x: hidden;
}


body::before {
    content: "";

    position: fixed;
    inset: 0;

    pointer-events: none;

    background-image:
        linear-gradient(
            rgba(20,135,180,.025) 1px,
            transparent 1px
        ),
        linear-gradient(
            90deg,
            rgba(20,135,180,.025) 1px,
            transparent 1px
        );

    background-size:
        40px 40px;
}


/* ==========================================================
   TOP BAR
   ========================================================== */

.topbar {
    height: 74px;

    position: relative;
    z-index: 20;

    display: grid;

    grid-template-columns:
        270px
        1fr
        200px;

    background: #03101a;

    border-bottom:
        1px solid #0876ad;

    box-shadow:
        0 0 26px
        rgba(0,153,255,.10);
}


.brand {
    display: flex;
    align-items: center;

    gap: 11px;

    padding:
        0 18px;

    border-right:
        1px solid #12405a;
}


.brand-shield {
    width: 43px;
    height: 48px;

    display: flex;

    align-items: center;
    justify-content: center;

    clip-path:
        polygon(
            50% 0,
            92% 15%,
            84% 74%,
            50% 100%,
            16% 74%,
            8% 15%
        );

    background:
        rgba(18,151,215,.20);

    color: #45d0ff;

    font-size: 19px;

    border:
        1px solid #31c6ff;
}


.brand-name {
    color: #5bd9ff;

    font-size: 18px;

    font-weight: bold;

    letter-spacing: 2px;
}


.brand-sub {
    margin-top: 2px;

    color: #4a91b2;

    font-size: 8px;

    letter-spacing: 2px;
}


.status-strip {
    display: grid;

    grid-template-columns:
        repeat(
            5,
            minmax(95px,1fr)
        )
        minmax(
            160px,
            1.6fr
        );
}


.status-box {
    position: relative;

    display: flex;

    flex-direction: column;

    justify-content: center;

    padding:
        8px 12px;

    border-right:
        1px solid #123447;

    overflow: hidden;
}


.status-box::after {
    content: "";

    position: absolute;

    bottom: 0;
    left: -100%;

    width: 100%;
    height: 1px;

    background:
        linear-gradient(
            90deg,
            transparent,
            #36cfff,
            transparent
        );

    animation:
        topSweep
        4s linear infinite;
}


@keyframes topSweep {
    to {
        left: 100%;
    }
}


.status-label {
    color: #6d8b9d;

    font-size: 8px;

    letter-spacing: 1px;
}


.status-value {
    margin-top: 5px;

    display: flex;

    align-items: center;

    gap: 6px;

    color: #24ed87;

    font-size: 9px;

    font-weight: bold;
}


.dot {
    width: 7px;
    height: 7px;

    border-radius: 50%;

    background: #26ee89;

    box-shadow:
        0 0 10px #26ee89;

    animation:
        pulseDot
        1.4s infinite;
}


.dot.blue {
    background: #25c7ff;

    box-shadow:
        0 0 10px #25c7ff;
}


@keyframes pulseDot {
    50% {
        opacity: .35;

        transform:
            scale(.7);
    }
}


/* ==========================================================
   TOP WAVE
   ========================================================== */

.wave-title {
    color: #6c8c9e;

    font-size: 8px;

    letter-spacing: 1px;
}


.wave {
    height: 34px;

    margin-top: 3px;

    display: flex;

    align-items: center;

    gap: 3px;
}


.wave span {
    width: 3px;

    border-radius: 4px;

    background:
        linear-gradient(
            #2eef88,
            #24bfff
        );

    animation:
        waveform
        1.05s
        ease-in-out
        infinite;
}


.wave span:nth-child(1){height:8px}
.wave span:nth-child(2){height:22px}
.wave span:nth-child(3){height:13px}
.wave span:nth-child(4){height:29px}
.wave span:nth-child(5){height:16px}
.wave span:nth-child(6){height:25px}
.wave span:nth-child(7){height:10px}
.wave span:nth-child(8){height:31px}
.wave span:nth-child(9){height:14px}
.wave span:nth-child(10){height:25px}
.wave span:nth-child(11){height:11px}
.wave span:nth-child(12){height:29px}
.wave span:nth-child(13){height:17px}
.wave span:nth-child(14){height:23px}
.wave span:nth-child(15){height:9px}


@keyframes waveform {
    50% {
        transform:
            scaleY(.30);

        opacity: .45;
    }
}


.clock-area {
    display: flex;

    flex-direction: column;

    justify-content: center;

    align-items: flex-end;

    padding-right: 19px;
}


.clock {
    font-size: 19px;

    color: #edf8ff;
}


.date {
    margin-top: 3px;

    color: #5d8398;

    font-size: 8px;
}


/* ==========================================================
   MAIN GRID
   ========================================================== */

.app-grid {
    position: relative;
    z-index: 5;

    display: grid;

    grid-template-columns:
        205px
        minmax(0,1fr)
        400px;

    gap: 10px;

    max-width: 1740px;

    margin: auto;

    padding: 10px;
}


/* ==========================================================
   MATRIX LEFT SIDE
   ========================================================== */

.left-column {
    position: relative;

    min-height: 900px;

    overflow: hidden;

    border-right:
        1px solid
        rgba(0,165,91,.14);
}


#matrixCanvas {
    position: absolute;

    inset: 0;

    width: 100%;
    height: 100%;

    opacity: .55;

    z-index: 0;
}


.left-content {
    position: relative;

    z-index: 2;

    padding:
        355px 8px 8px;
}


.left-card {
    margin-bottom: 10px;

    padding: 10px;

    background:
        rgba(2,13,18,.84);

    border:
        1px solid #095070;

    border-radius: 5px;

    backdrop-filter:
        blur(4px);
}


.left-title {
    color: #8eb4c6;

    font-size: 8px;

    letter-spacing: 1px;

    margin-bottom: 11px;
}


.metric {
    margin-bottom: 13px;
}


.metric-head {
    display: flex;

    justify-content:
        space-between;

    font-size: 8px;

    color: #7392a2;
}


.metric-value {
    color: #23cfff;
}


.bar {
    height: 3px;

    margin-top: 6px;

    background: #10232d;
}


.bar-fill {
    height: 100%;

    background:
        linear-gradient(
            90deg,
            #17df78,
            #23cfff
        );

    animation:
        glowBar
        2s alternate infinite;
}


@keyframes glowBar {
    to {
        filter:
            brightness(1.55);
    }
}


.network-line {
    height: 25px;

    display: flex;

    align-items: flex-end;

    gap: 2px;

    margin-top: 5px;
}


.network-line span {
    width: 3px;

    background: #21de79;

    animation:
        networkPulse
        1.2s
        ease-in-out infinite;
}


.network-line span:nth-child(1){height:5px}
.network-line span:nth-child(2){height:12px}
.network-line span:nth-child(3){height:8px}
.network-line span:nth-child(4){height:18px}
.network-line span:nth-child(5){height:10px}
.network-line span:nth-child(6){height:20px}
.network-line span:nth-child(7){height:7px}
.network-line span:nth-child(8){height:15px}
.network-line span:nth-child(9){height:11px}
.network-line span:nth-child(10){height:22px}


@keyframes networkPulse {
    50% {
        transform:
            scaleY(.4);
    }
}


/* ==========================================================
   PANELS
   ========================================================== */

.panel {
    position: relative;

    overflow: hidden;

    background: #04111b;

    border:
        1px solid #0a5480;

    border-radius: 6px;

    box-shadow:
        0 0 20px
        rgba(0,126,188,.08);
}


.panel::before {
    content: "";

    position: absolute;

    top: 0;
    left: 0;

    width: 130px;
    height: 1px;

    background:
        linear-gradient(
            90deg,
            #36cfff,
            transparent
        );
}


.panel-head {
    height: 43px;

    display: flex;

    align-items: center;

    justify-content:
        space-between;

    padding:
        0 12px;

    border-bottom:
        1px solid #123447;
}


.panel-title {
    color: #a8c7d7;

    font-size: 9px;

    letter-spacing: 1px;
}


.live {
    color: #2aea88;

    font-size: 8px;
}


/* ==========================================================
   CAMERA
   ========================================================== */

.camera-box {
    position: relative;

    background: #000;
}


.camera {
    width: 100%;

    display: block;

    min-height: 470px;

    object-fit: contain;
}


.corner {
    position: absolute;

    width: 34px;
    height: 34px;
}


.tl {
    top: 14px;
    left: 14px;

    border-top:
        2px solid #3dd8ff;

    border-left:
        2px solid #3dd8ff;
}


.tr {
    top: 14px;
    right: 14px;

    border-top:
        2px solid #3dd8ff;

    border-right:
        2px solid #3dd8ff;
}


.bl {
    bottom: 14px;
    left: 14px;

    border-bottom:
        2px solid #3dd8ff;

    border-left:
        2px solid #3dd8ff;
}


.br {
    bottom: 14px;
    right: 14px;

    border-bottom:
        2px solid #3dd8ff;

    border-right:
        2px solid #3dd8ff;
}


.camera-footer {
    height: 28px;

    display: flex;

    align-items: center;

    justify-content:
        space-between;

    padding:
        0 10px;

    color: #5d8499;

    font-size: 8px;
}


.cam-name {
    color: #35caff;
}


/* ==========================================================
   STATS
   ========================================================== */

.stats {
    display: grid;

    grid-template-columns:
        repeat(4,1fr);

    gap: 8px;

    margin-top: 9px;
}


.stat-card {
    min-height: 95px;

    position: relative;

    padding: 13px;

    overflow: hidden;

    background: #05131d;

    border:
        1px solid #10496a;

    border-radius: 5px;
}


.stat-title {
    color: #42c6f5;

    font-size: 8px;

    letter-spacing: 1px;
}


.stat-number {
    margin-top: 11px;

    font-size: 24px;

    color: #effaff;
}


.stat-sub {
    color: #607f90;

    font-size: 8px;

    margin-top: 2px;
}


.stat-line {
    position: absolute;

    left: 10px;
    right: 10px;
    bottom: 9px;

    height: 14px;

    background:
        repeating-linear-gradient(
            90deg,
            transparent 0 7px,
            #20bfff 8px 9px,
            transparent 10px 15px
        );

    opacity: .35;

    animation:
        slideLine
        4s linear infinite;
}


@keyframes slideLine {
    from {
        transform:
            translateX(-20px);
    }

    to {
        transform:
            translateX(20px);
    }
}


/* ==========================================================
   RIGHT AI SCANNERS
   ========================================================== */

.ai-body {
    padding: 9px;
}


.scanner-row {
    display: grid;

    grid-template-columns:
        175px 1fr;

    gap: 8px;

    margin-bottom: 9px;
}


.scanner {
    height: 164px;

    position: relative;

    overflow: hidden;

    background:
        radial-gradient(
            circle,
            rgba(0,143,255,.17),
            rgba(0,27,50,.3) 47%,
            rgba(0,4,9,.65) 74%
        );

    border:
        1px solid #07537d;

    border-radius: 5px;
}


.scanner-label {
    position: absolute;

    top: 8px;
    left: 9px;

    color: #6bd8ff;

    font-size: 8px;

    letter-spacing: 1px;
}


.ring {
    position: absolute;

    border-radius: 50%;

    border:
        1px solid
        rgba(50,196,255,.38);

    animation:
        rotate
        7s linear infinite;
}


.ring1 {
    inset: 25px;
}


.ring2 {
    inset: 38px;

    border-style: dashed;

    animation-direction:
        reverse;

    animation-duration: 5s;
}


.ring3 {
    inset: 53px;

    animation-duration:
        3.5s;
}


@keyframes rotate {
    to {
        transform:
            rotate(360deg);
    }
}


.scanline {
    position: absolute;

    left: 14px;
    right: 14px;

    height: 1px;

    background: #42d9ff;

    box-shadow:
        0 0 10px #42d9ff;

    animation:
        scanLine
        2.3s
        ease-in-out infinite;
}


@keyframes scanLine {
    0% {
        top: 31px;
    }

    50% {
        top: 135px;
    }

    100% {
        top: 31px;
    }
}


.face {
    position: absolute;

    left: 50%;
    top: 53%;

    transform:
        translate(-50%,-50%);

    width: 65px;
    height: 82px;

    border:
        1px solid #2acbff;

    border-radius:
        44% 44% 48% 48%;

    box-shadow:
        0 0 22px
        rgba(42,203,255,.22);
}


.face::before {
    content: "";

    position: absolute;

    left: 12px;
    right: 12px;

    top: 28px;

    height: 1px;

    background: #31cfff;

    box-shadow:
        0 15px 0
        rgba(49,207,255,.7),
        0 30px 0
        rgba(49,207,255,.4);
}


.car {
    position: absolute;

    left: 50%;
    top: 56%;

    transform:
        translate(-50%,-50%);

    width: 105px;
    height: 44px;

    border:
        2px solid #2acbff;

    border-radius:
        23px 23px 10px 10px;

    box-shadow:
        0 0 23px
        rgba(42,203,255,.20);
}


.car::before {
    content: "";

    position: absolute;

    left: 20px;
    right: 20px;

    top: -31px;

    height: 31px;

    border:
        2px solid #2acbff;

    border-bottom: 0;

    border-radius:
        25px 25px 0 0;
}


.light {
    position: absolute;

    top: 19px;

    width: 12px;
    height: 5px;

    background: #4fe0ff;

    box-shadow:
        0 0 10px #4fe0ff;
}


.left-light {
    left: 9px;
}


.right-light {
    right: 9px;
}


.scan-info {
    padding: 11px;

    background: #05131d;

    border:
        1px solid #12394f;

    border-radius: 5px;
}


.scan-title {
    color: #688a9c;

    font-size: 8px;
}


.scan-status {
    margin-top: 12px;

    display: flex;

    align-items: center;

    gap: 9px;

    color: #27ef88;

    font-size: 16px;

    font-weight: bold;
}


.shield {
    width: 31px;
    height: 36px;

    display: flex;

    align-items: center;
    justify-content: center;

    clip-path:
        polygon(
            50% 0,
            92% 16%,
            83% 74%,
            50% 100%,
            17% 74%,
            8% 16%
        );

    background:
        rgba(44,238,140,.16);

    color: #34ef92;
}


.scan-detail {
    margin-top: 13px;

    padding-top: 9px;

    border-top:
        1px solid #163345;

    color: #6b8998;

    font-size: 8px;

    line-height: 1.8;
}


.scan-plate {
    margin-top: 8px;

    display: inline-block;

    padding:
        4px 8px;

    border:
        1px solid #168bc7;

    color: #4cd4ff;

    font-size: 17px;

    letter-spacing: 2px;
}


/* ==========================================================
   CONTROL BUTTONS
   ========================================================== */

.security-controls {
    display: grid;

    grid-template-columns:
        1fr 1fr;

    gap: 7px;

    margin:
        12px 0;
}


.security-button {
    min-height: 41px;

    cursor: pointer;

    color: #75bcd9;

    background: #061722;

    border:
        1px solid #155276;

    border-radius: 5px;

    font-size: 8px;

    letter-spacing: .8px;

    transition: .18s ease;
}


.security-button:hover {
    color: #e7faff;

    border-color: #32cfff;

    background: #082131;
}


.face-button {
    color: #45d4ff;

    border-color: #1189be;
}


.vehicle-button {
    color: #49e7a0;

    border-color: #16845b;
}



/* ==========================================================
   VOICE CONTROL
   ========================================================== */

.voice-button {
    grid-column: 1 / -1;
    min-height: 48px;
    position: relative;
    overflow: hidden;
    color: #70e8ff;
    border-color: #157da7;
    background: linear-gradient(90deg, rgba(0,112,160,.16), rgba(0,204,160,.08));
}

.voice-button.listening {
    color: #eaffff;
    border-color: #31e7ff;
    box-shadow: 0 0 18px rgba(49,231,255,.24), inset 0 0 22px rgba(49,231,255,.08);
}

.voice-button.listening::after {
    content: "";
    position: absolute;
    left: -45%;
    top: 0;
    width: 45%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(80,239,255,.18), transparent);
    animation: voiceSweep 1.1s linear infinite;
}

@keyframes voiceSweep { to { left: 110%; } }

.voice-console {
    grid-column: 1 / -1;
    min-height: 58px;
    padding: 9px 10px;
    background: rgba(2,15,24,.78);
    border: 1px solid #123f58;
    border-radius: 5px;
}

.voice-console-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    color: #5f91a8;
    font-size: 7px;
    letter-spacing: 1px;
}

.voice-state { color: #32d8ff; }
.voice-state.active {
    color: #2fee91;
    text-shadow: 0 0 8px rgba(47,238,145,.45);
}

.voice-transcript {
    margin-top: 7px;
    min-height: 15px;
    color: #a9d6e8;
    font-size: 9px;
    line-height: 1.45;
}

.voice-hint {
    margin-top: 6px;
    color: #4f7283;
    font-size: 7px;
    line-height: 1.5;
}

.voice-bars {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    height: 12px;
    vertical-align: middle;
    margin-right: 5px;
}

.voice-bars span {
    width: 2px;
    height: 4px;
    background: #37dbff;
    opacity: .45;
}

.voice-button.listening .voice-bars span {
    opacity: 1;
    animation: voiceBar .65s ease-in-out infinite alternate;
}
.voice-button.listening .voice-bars span:nth-child(2) { animation-delay: .1s; }
.voice-button.listening .voice-bars span:nth-child(3) { animation-delay: .2s; }
.voice-button.listening .voice-bars span:nth-child(4) { animation-delay: .3s; }
.voice-button.listening .voice-bars span:nth-child(5) { animation-delay: .4s; }
@keyframes voiceBar { to { height: 16px; } }

/* ==========================================================
   RECOGNITION CARDS
   ========================================================== */

.rec-title {
    margin:
        12px 0 8px;

    color: #9ab6c5;

    font-size: 9px;

    letter-spacing: 1px;
}


.rec-card {
    margin-bottom: 7px;

    padding: 10px;

    border-radius: 5px;
}


.person-card {
    border:
        1px solid #0aaa61;

    background:
        linear-gradient(
            90deg,
            rgba(0,156,79,.15),
            rgba(0,45,25,.04)
        );
}


.vehicle-card {
    border:
        1px solid #0b76ae;

    background:
        linear-gradient(
            90deg,
            rgba(0,112,176,.16),
            rgba(0,37,69,.04)
        );
}


.unknown-person {
    border:
        1px solid #bf2a39;

    background:
        rgba(178,19,37,.16);
}


.unknown-vehicle {
    border:
        1px solid #a96c05;

    background:
        rgba(183,109,0,.16);
}


.rec-row {
    display: flex;

    align-items: center;

    gap: 10px;
}


.rec-icon {
    width: 43px;
    height: 43px;

    display: flex;

    align-items: center;
    justify-content: center;

    border-radius: 4px;

    font-size: 21px;
}


.person-card .rec-icon {
    border:
        1px solid #0aa862;

    color: #24ed88;
}


.vehicle-card .rec-icon {
    border:
        1px solid #0d79b0;

    color: #31caff;
}


.rec-info {
    flex: 1;
}


.rec-label {
    font-size: 8px;
}


.person-card .rec-label {
    color: #49e6a1;
}


.vehicle-card .rec-label {
    color: #3cc7ff;
}


.unknown-person .rec-label {
    color: #ff5665;
}


.unknown-vehicle .rec-label {
    color: #ffb62b;
}


.rec-name {
    margin-top: 3px;

    color: #eff9ff;

    font-size: 16px;
}


.rec-sub {
    margin-top: 2px;

    color: #708c9b;

    font-size: 8px;
}


.check {
    width: 20px;
    height: 20px;

    display: flex;

    align-items: center;
    justify-content: center;

    border-radius: 50%;

    color: #002511;

    background: #2fed91;

    font-weight: bold;
}


.plate-box {
    padding:
        4px 8px;

    border:
        1px solid #278fca;

    background:
        rgba(18,101,151,.16);

    color: #daf5ff;

    border-radius: 3px;
}


.waiting {
    padding: 15px;

    color: #557788;

    text-align: center;

    border:
        1px solid #143447;

    border-radius: 5px;
}


/* ==========================================================
   EVENT HISTORY
   ========================================================== */

.history {
    margin-top: 9px;
}


.events {
    display: grid;

    grid-template-columns:
        repeat(
            auto-fill,
            minmax(170px,1fr)
        );

    gap: 7px;

    padding: 8px;
}


.event {
    overflow: hidden;

    background: #05131d;

    border:
        1px solid #153c56;

    border-radius: 5px;
}


.event img {
    width: 100%;
    height: 92px;

    object-fit: cover;

    display: block;
}


.event-body {
    padding: 7px;
}


.event-type {
    color: #36c8ff;

    font-size: 7px;
}


.event-name {
    margin-top: 3px;

    color: #e7f5fc;

    font-size: 10px;
}


.event-meta {
    margin-top: 3px;

    color: #557486;

    font-size: 7px;
}


.delete-event-button {
    width: 100%;
    min-height: 30px;
    margin-top: 8px;
    cursor: pointer;
    color: #ff6675;
    background: rgba(130,14,30,.10);
    border: 1px solid #702935;
    border-radius: 4px;
    font-size: 7px;
    letter-spacing: 1px;
    transition: .18s ease;
}

.delete-event-button:hover {
    color: #fff;
    background: rgba(198,21,43,.30);
    border-color: #ff4c61;
    box-shadow: 0 0 12px rgba(255,62,84,.18);
}

.event-head-actions {
    display: flex;
    align-items: center;
    gap: 7px;
}

.history-action-button {
    min-height: 25px;
    padding: 0 9px;
    cursor: pointer;
    color: #66dfff;
    background: rgba(14,88,128,.12);
    border: 1px solid #155879;
    border-radius: 4px;
    font-size: 7px;
    letter-spacing: 1px;
}

.history-action-button:hover {
    color: #fff;
    border-color: #35cbff;
    box-shadow: 0 0 12px rgba(53,203,255,.16);
}

.history-action-button.danger {
    color: #ff7b86;
    border-color: #7a2935;
    background: rgba(125,12,28,.12);
}

.history-action-button.danger:hover {
    color: #fff;
    border-color: #ff4c61;
    background: rgba(190,18,40,.28);
}

.history-overlay {
    position: fixed;
    inset: 0;
    z-index: 10050;
    display: none;
    padding: 18px;
    background: rgba(0,5,10,.96);
    backdrop-filter: blur(8px);
    overflow-y: auto;
}

.history-overlay.open {
    display: block;
}

.history-window {
    width: min(1500px, 96vw);
    min-height: 78vh;
    margin: 15px auto;
    background: #04111b;
    border: 1px solid #0a6390;
    border-radius: 7px;
    box-shadow: 0 0 32px rgba(0,170,255,.12);
}

.history-window-head {
    position: sticky;
    top: 0;
    z-index: 3;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    min-height: 54px;
    padding: 10px 14px;
    background: rgba(3,16,26,.97);
    border-bottom: 1px solid #123f58;
}

.history-window-title {
    color: #62d8ff;
    font-size: 11px;
    letter-spacing: 2px;
}

.history-window-sub {
    margin-top: 3px;
    color: #66899a;
    font-size: 7px;
}

.full-history-events {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
    gap: 10px;
    padding: 12px;
}

.full-history-events .event img {
    height: 120px;
}

.unknown-event-badge {
    display: inline-block;
    margin-top: 5px;
    padding: 3px 6px;
    color: #ffb34d;
    border: 1px solid rgba(255,161,48,.55);
    background: rgba(160,83,0,.12);
    border-radius: 3px;
    font-size: 7px;
    letter-spacing: 1px;
}


/* ==========================================================
   MODALS
   ========================================================== */

.enroll-overlay {
    position: fixed;

    inset: 0;

    z-index: 9999;

    display: none;

    align-items: center;
    justify-content: center;

    padding: 20px;

    background:
        rgba(0,5,10,.92);

    backdrop-filter:
        blur(8px);
}


.enroll-overlay.open {
    display: flex;
}


.enroll-window {
    width:
        min(900px,96vw);

    overflow: hidden;

    border-radius: 8px;

    border:
        1px solid #118bc2;

    background:
        linear-gradient(
            145deg,
            #061923,
            #020a10
        );

    box-shadow:
        0 0 55px
        rgba(0,167,255,.18);
}


.enroll-header {
    height: 53px;

    display: flex;

    align-items: center;

    justify-content:
        space-between;

    padding:
        0 17px;

    color: #5cdaff;

    font-size: 10px;

    letter-spacing: 1.7px;

    border-bottom:
        1px solid #16445c;
}


.close-enroll {
    width: 35px;
    height: 35px;

    cursor: pointer;

    border: 0;

    background:
        transparent;

    color: #79aaba;

    font-size: 23px;
}


/* ==========================================================
   FACE ENROLLMENT
   ========================================================== */

.enroll-content {
    display: grid;

    grid-template-columns:
        1.35fr 1fr;

    gap: 16px;

    padding: 17px;
}


.enroll-scanner {
    min-height: 450px;

    position: relative;

    overflow: hidden;

    border:
        1px solid #087fb5;

    border-radius: 7px;

    background: #000;
}


.enroll-live-camera {
    position: absolute;

    inset: 0;

    width: 100%;
    height: 100%;

    object-fit: cover;

    opacity: .48;

    filter:
        saturate(.55)
        contrast(1.15)
        brightness(.72);
}


.enroll-blue-filter {
    position: absolute;

    inset: 0;

    background:
        radial-gradient(
            circle at center,
            rgba(0,182,255,.06),
            rgba(0,28,47,.20) 55%,
            rgba(0,5,10,.48)
        );

    pointer-events: none;
}


.enroll-grid {
    position: absolute;

    inset: 0;

    background-image:
        linear-gradient(
            rgba(37,193,255,.06) 1px,
            transparent 1px
        ),
        linear-gradient(
            90deg,
            rgba(37,193,255,.06) 1px,
            transparent 1px
        );

    background-size:
        28px 28px;
}


.enroll-ring {
    position: absolute;

    border-radius: 50%;

    border:
        1px solid
        rgba(39,200,255,.45);
}


.ring-a {
    inset:
        55px 65px;

    animation:
        enrollRotate
        8s linear infinite;
}


.ring-b {
    inset:
        85px 95px;

    border-style: dashed;

    animation:
        enrollRotateReverse
        5s linear infinite;
}


.ring-c {
    inset:
        115px 125px;

    animation:
        enrollRotate
        3s linear infinite;
}


@keyframes enrollRotate {
    to {
        transform:
            rotate(360deg);
    }
}


@keyframes enrollRotateReverse {
    to {
        transform:
            rotate(-360deg);
    }
}


.face-target {
    position: absolute;

    width: 150px;
    height: 200px;

    left: 50%;
    top: 47%;

    transform:
        translate(-50%,-50%);

    border:
        2px solid #29d1ff;

    border-radius:
        44% 44% 48% 48%;

    box-shadow:
        0 0 32px
        rgba(35,207,255,.30),
        inset 0 0 30px
        rgba(35,207,255,.05);
}


.face-landmark {
    position: absolute;

    width: 5px;
    height: 5px;

    border-radius: 50%;

    background: #54e1ff;

    box-shadow:
        0 0 7px #54e1ff;
}


.lm1 {
    left: 33px;
    top: 64px;
}

.lm2 {
    right: 33px;
    top: 64px;
}

.lm3 {
    left: 72px;
    top: 100px;
}

.lm4 {
    left: 50px;
    bottom: 46px;
}

.lm5 {
    right: 50px;
    bottom: 46px;
}


.face-target::before {
    content: "";

    position: absolute;

    left: 23px;
    right: 23px;

    top: 66px;

    height: 1px;

    background:
        rgba(65,217,255,.7);

    box-shadow:
        0 37px 0
        rgba(65,217,255,.45),
        0 70px 0
        rgba(65,217,255,.25);
}


.enroll-scan-line {
    position: absolute;

    left: 8%;
    right: 8%;

    height: 2px;

    background:
        linear-gradient(
            90deg,
            transparent,
            #55e3ff,
            transparent
        );

    box-shadow:
        0 0 18px #31cfff;

    animation:
        biometricSweep
        1.7s ease-in-out infinite;
}


@keyframes biometricSweep {
    0% {
        top: 13%;
    }

    50% {
        top: 82%;
    }

    100% {
        top: 13%;
    }
}


.scanner-corner {
    position: absolute;

    width: 46px;
    height: 46px;
}


.ec1 {
    left: 16px;
    top: 16px;

    border-left:
        2px solid #42d8ff;

    border-top:
        2px solid #42d8ff;
}


.ec2 {
    right: 16px;
    top: 16px;

    border-right:
        2px solid #42d8ff;

    border-top:
        2px solid #42d8ff;
}


.ec3 {
    left: 16px;
    bottom: 16px;

    border-left:
        2px solid #42d8ff;

    border-bottom:
        2px solid #42d8ff;
}


.ec4 {
    right: 16px;
    bottom: 16px;

    border-right:
        2px solid #42d8ff;

    border-bottom:
        2px solid #42d8ff;
}


.scanner-message {
    position: absolute;

    left: 15px;
    right: 15px;
    bottom: 22px;

    padding: 9px;

    text-align: center;

    color: #63dbff;

    background:
        rgba(1,13,20,.72);

    border:
        1px solid
        rgba(37,191,244,.30);

    font-size: 9px;

    letter-spacing: 1.3px;
}


.enroll-panel {
    padding: 9px;
}


.enroll-label {
    margin-bottom: 7px;

    color: #6f93a5;

    font-size: 8px;

    letter-spacing: 1px;
}


.enroll-input {
    width: 100%;
    height: 44px;

    padding:
        0 12px;

    outline: none;

    color: #e7f8ff;

    background: #03111a;

    border:
        1px solid #145377;

    border-radius: 5px;

    font-size: 15px;
}


.enroll-input:focus {
    border-color: #30cfff;

    box-shadow:
        0 0 15px
        rgba(48,207,255,.12);
}


.security-note {
    margin-top: 14px;

    padding: 11px;

    color: #708d9c;

    background:
        rgba(0,116,169,.055);

    border:
        1px solid #153c51;

    font-size: 9px;

    line-height: 1.6;
}


.start-scan-button {
    width: 100%;

    min-height: 48px;

    margin-top: 15px;

    cursor: pointer;

    color: #001319;

    background:
        linear-gradient(
            90deg,
            #27cfff,
            #36e3b0
        );

    border: 0;

    border-radius: 5px;

    font-weight: bold;

    letter-spacing: 1px;
}


.start-scan-button:disabled {
    cursor: default;

    opacity: .45;
}


.cancel-scan-button {
    width: 100%;

    min-height: 40px;

    margin-top: 8px;

    cursor: pointer;

    color: #ff7481;

    background:
        rgba(117,18,29,.12);

    border:
        1px solid #7e2733;

    border-radius: 5px;
}


.progress-area {
    margin-top: 21px;
}


.progress-header {
    display: flex;

    justify-content:
        space-between;

    color: #68bad9;

    font-size: 8px;
}


.progress-track {
    height: 7px;

    margin-top: 8px;

    overflow: hidden;

    background: #0a202a;

    border-radius: 10px;
}


.progress-fill {
    width: 0%;

    height: 100%;

    background:
        linear-gradient(
            90deg,
            #18bfff,
            #26ed92
        );

    box-shadow:
        0 0 12px
        rgba(37,216,255,.50);

    transition:
        width .35s ease;
}


.enroll-message {
    min-height: 36px;

    margin-top: 10px;

    color: #81a3b3;

    font-size: 9px;

    line-height: 1.5;
}


.sample-dots {
    display: flex;

    gap: 8px;

    margin-top: 15px;
}


.sample-dot {
    width: 13px;
    height: 13px;

    border-radius: 50%;

    border:
        1px solid #1b6689;

    background: #071722;
}


.sample-dot.complete {
    border-color: #31eb93;

    background: #31eb93;

    box-shadow:
        0 0 8px
        rgba(49,235,147,.65);
}


/* ==========================================================
   VEHICLE / LIBRARY MODALS
   ========================================================== */

.small-window {
    width:
        min(680px,96vw);
}


.simple-body {
    padding: 18px;
}


.vehicle-enroll-body {
    display: grid;

    grid-template-columns:
        220px 1fr;

    gap: 18px;

    padding: 18px;
}


.mini-car-scanner {
    min-height: 260px;

    position: relative;

    overflow: hidden;

    border:
        1px solid #087eb5;

    background:
        radial-gradient(
            circle,
            rgba(0,151,255,.17),
            #020b11 70%
        );

    border-radius: 6px;
}


.mini-radar {
    position: absolute;

    inset: 30px;

    border-radius: 50%;

    border:
        1px dashed
        rgba(51,206,255,.45);

    animation:
        enrollRotate
        6s linear infinite;
}


.mini-car {
    position: absolute;

    left: 50%;
    top: 50%;

    transform:
        translate(-50%,-50%);

    font-size: 70px;

    filter:
        drop-shadow(
            0 0 13px
            rgba(44,201,255,.6)
        );
}


.vehicle-sweep {
    position: absolute;

    left: 15px;
    right: 15px;

    height: 1px;

    background: #3bd9ff;

    box-shadow:
        0 0 12px #3bd9ff;

    animation:
        biometricSweep
        2s infinite;
}


.vehicle-label-space {
    margin-top: 16px;
}


.plate-input {
    text-transform: uppercase;

    letter-spacing: 2px;
}


.library-grid {
    display: grid;

    grid-template-columns:
        repeat(
            auto-fill,
            minmax(180px,1fr)
        );

    gap: 9px;
}


.library-item {
    padding: 13px;

    border:
        1px solid #164766;

    border-radius: 5px;

    background: #05151f;
}


.library-type {
    color: #52d4ff;

    font-size: 8px;

    letter-spacing: 1px;
}


.library-name {
    margin-top: 7px;

    color: #eaf9ff;

    font-size: 15px;
}


.library-sub {
    margin-top: 4px;

    color: #6c8e9f;

    font-size: 9px;
}


/* ==========================================================
   RESPONSIVE
   ========================================================== */

@media(max-width:1250px) {
    .app-grid {
        grid-template-columns:
            160px 1fr;
    }

    .right-column {
        grid-column:
            1 / -1;
    }

    .topbar {
        grid-template-columns:
            230px 1fr;
    }

    .clock-area {
        display: none;
    }

    .status-box:nth-child(6) {
        display: none;
    }

    .status-strip {
        grid-template-columns:
            repeat(5,1fr);
    }
}


@media(max-width:850px) {
    .app-grid {
        grid-template-columns:
            1fr;
    }

    .left-column {
        display: none;
    }

    .stats {
        grid-template-columns:
            repeat(2,1fr);
    }

    .enroll-content,
    .vehicle-enroll-body {
        grid-template-columns:
            1fr;
    }

    .enroll-scanner {
        min-height: 380px;
    }
}

</style>

</head>


<body>


<!-- =======================================================
     TOP BAR
     ======================================================= -->

<div class="topbar">


<div class="brand">

<div class="brand-shield">
A
</div>

<div>

<div class="brand-name">
AI SECURITY
</div>

<div class="brand-sub">
COMMAND CENTER
</div>

</div>

</div>


<div class="status-strip">


<div class="status-box">

<div class="status-label">
SYSTEM
</div>

<div
    id="topSystem"
    class="status-value"
>

<span class="dot"></span>

PROTECTED

</div>

</div>


<div class="status-box">

<div class="status-label">
CAMERA
</div>

<div
    id="topCamera"
    class="status-value"
>

<span class="dot"></span>

ONLINE

</div>

</div>


<div class="status-box">

<div class="status-label">
FACE AI
</div>

<div class="status-value">

<span class="dot blue"></span>

ACTIVE

</div>

</div>


<div class="status-box">

<div class="status-label">
LPR AI
</div>

<div class="status-value">

<span class="dot blue"></span>

ACTIVE

</div>

</div>


<div class="status-box">

<div class="status-label">
MQTT
</div>

<div
    id="topMqtt"
    class="status-value"
>

<span class="dot"></span>

CONNECTED

</div>

</div>


<div class="status-box">

<div class="wave-title">
LIVE ACTIVITY
</div>

<div class="wave">

<span></span>
<span></span>
<span></span>
<span></span>
<span></span>

<span></span>
<span></span>
<span></span>
<span></span>
<span></span>

<span></span>
<span></span>
<span></span>
<span></span>
<span></span>

</div>

</div>


</div>


<div class="clock-area">

<div
    id="clock"
    class="clock"
>
--
</div>

<div
    id="date"
    class="date"
>
--
</div>

</div>


</div>


<!-- =======================================================
     MAIN APP
     ======================================================= -->

<div class="app-grid">


<!-- =======================================================
     MATRIX LEFT COLUMN
     ======================================================= -->

<div class="left-column">

<canvas id="matrixCanvas"></canvas>


<div class="left-content">


<div class="left-card">

<div class="left-title">
SYSTEM OVERVIEW
</div>


<div class="metric">

<div class="metric-head">

<span>
AI CORE
</span>

<span class="metric-value">
ACTIVE
</span>

</div>

<div class="bar">

<div
    class="bar-fill"
    style="width:87%"
></div>

</div>

</div>


<div class="metric">

<div class="metric-head">

<span>
CAMERA LINK
</span>

<span
    id="leftCamera"
    class="metric-value"
>
ONLINE
</span>

</div>

<div class="bar">

<div
    class="bar-fill"
    style="width:96%"
></div>

</div>

</div>


<div class="metric">

<div class="metric-head">

<span>
MQTT LINK
</span>

<span
    id="leftMqtt"
    class="metric-value"
>
CONNECTED
</span>

</div>

<div class="bar">

<div
    class="bar-fill"
    style="width:93%"
></div>

</div>

</div>


</div>


<div class="left-card">

<div class="left-title">
NETWORK ACTIVITY
</div>

<div class="metric-head">

<span>
DATA STREAM
</span>

<span class="metric-value">
LIVE
</span>

</div>


<div class="network-line">

<span></span>
<span></span>
<span></span>
<span></span>
<span></span>

<span></span>
<span></span>
<span></span>
<span></span>
<span></span>

</div>


<div
    style="
        color:#597a8c;
        font-size:8px;
        margin-top:10px;
        line-height:1.8;
    "
>

FRIGATE DATA LINK

<br>

FACE AI CHANNEL

<br>

LPR AI CHANNEL

<br>

MQTT EVENT BUS

</div>

</div>


</div>

</div>


<!-- =======================================================
     CENTER CAMERA
     ======================================================= -->

<div class="center-column">


<div class="panel">

<div class="panel-head">

<div class="panel-title">
▣ LIVE CAMERA FEED
</div>

<div class="live">
● LIVE
</div>

</div>


<div class="camera-box">

<img
    class="camera"
    src="/video_feed"
>

<div class="corner tl"></div>
<div class="corner tr"></div>
<div class="corner bl"></div>
<div class="corner br"></div>

</div>


<div class="camera-footer">

<div class="cam-name">
CAM 01
</div>

<div>
FRONT CAMERA • FACE AI • LPR AI
</div>

</div>

</div>


<div class="panel" style="margin-top:9px;">
<div class="panel-head">
<div class="panel-title">✈ DRONE LIVE FEED</div>
<div class="live" id="droneFeedState">DRONE</div>
</div>
<div class="camera-box" style="min-height:280px;">
<img
id="droneCameraFeed"
class="camera"
src="/drone_video_feed"
style="width:100%;height:420px;min-height:280px;max-height:520px;object-fit:contain;background:#000;"
alt="Drone feed waiting for DJI/MediaMTX stream">
<div class="corner tl"></div><div class="corner tr"></div>
<div class="corner bl"></div><div class="corner br"></div>
</div>
<div class="camera-footer">
<div class="cam-name">DRONE 01</div>
<div id="droneTrackingReadout">TRACKING ASSIST • WAITING</div>
</div>
</div>


<div class="stats">


<div class="stat-card">

<div class="stat-title">
FACE EVENTS
</div>

<div
    id="faceCount"
    class="stat-number"
>
0
</div>

<div class="stat-sub">
SESSION
</div>

<div class="stat-line"></div>

</div>


<div class="stat-card">

<div class="stat-title">
PLATE EVENTS
</div>

<div
    id="plateCount"
    class="stat-number"
>
0
</div>

<div class="stat-sub">
SESSION
</div>

<div class="stat-line"></div>

</div>


<div class="stat-card">

<div class="stat-title">
TOTAL EVENTS
</div>

<div
    id="totalCount"
    class="stat-number"
>
0
</div>

<div class="stat-sub">
SESSION
</div>

<div class="stat-line"></div>

</div>


<div class="stat-card">

<div class="stat-title">
SYSTEM HEALTH
</div>

<div
    id="health"
    class="stat-number"
    style="color:#2fee91"
>
READY
</div>

<div class="stat-sub">
AI SERVICES
</div>

<div class="stat-line"></div>

</div>


</div>


<div
    id="historyPanel"
    class="panel history"
>

<div class="panel-head">

<div class="panel-title">
RECENT SECURITY EVENTS
</div>

<div class="event-head-actions">
<div class="live">
UNKNOWN FACE / VEHICLE CAPTURES
</div>
<button type="button" id="viewAllHistory" class="history-action-button">VIEW ALL</button>
</div>

</div>


<div class="events">

{% for event in events %}

<div class="event" id="eventCard{{ loop.index0 }}">


{% if event.image_file %}

<a
    href="/events/{{ event.image_file }}"
    target="_blank"
>

<img
    src="/events/{{ event.image_file }}"
>

</a>

{% endif %}


<div class="event-body">

<div class="event-type">
{{ event.Type }}
</div>

<div class="event-name">
{{ event.Name }}
</div>

{% if 'UNKNOWN' in (event.Type|upper) or 'UNKNOWN' in (event.Name|upper) %}
<div class="unknown-event-badge">UNKNOWN DETECTION</div>
{% endif %}

<div class="event-meta">

{{ event.Date }}

&nbsp;•&nbsp;

{{ event.Time }}

{% if event.Identifier %}

<br>

{{ event.Identifier }}

{% endif %}

</div>

<button
    type="button"
    class="delete-event-button"
    data-event-index="{{ loop.index0 }}"
>
DELETE EVENT
</button>

</div>

</div>

{% endfor %}

</div>

</div>


</div>


<!-- =======================================================
     FULL EVENT HISTORY
     ======================================================= -->

<div id="eventHistoryOverlay" class="history-overlay">
<div class="history-window">

<div class="history-window-head">
<div>
<div class="history-window-title">EVENT HISTORY</div>
<div class="history-window-sub">ALL SAVED SECURITY EVENTS • UNKNOWN FACE / VEHICLE CAPTURES INCLUDED</div>
</div>

<div class="event-head-actions">
<button type="button" id="clearAllEvents" class="history-action-button danger">CLEAR ALL</button>
<button type="button" id="closeEventHistory" class="history-action-button">CLOSE</button>
</div>
</div>

<div class="full-history-events">
{% if history_events %}
{% for event in history_events %}
<div class="event history-event-card">

{% if event.image_file %}
<a href="/events/{{ event.image_file }}" target="_blank">
<img src="/events/{{ event.image_file }}">
</a>
{% endif %}

<div class="event-body">
<div class="event-type">{{ event.Type }}</div>
<div class="event-name">{{ event.Name }}</div>

{% if 'UNKNOWN' in (event.Type|upper) or 'UNKNOWN' in (event.Name|upper) %}
<div class="unknown-event-badge">UNKNOWN DETECTION</div>
{% endif %}

<div class="event-meta">
{{ event.Date }} &nbsp;•&nbsp; {{ event.Time }}
{% if event.Identifier %}
<br>{{ event.Identifier }}
{% endif %}
</div>

<button type="button" class="delete-event-button" data-event-index="{{ loop.index0 }}">DELETE EVENT</button>
</div>
</div>
{% endfor %}
{% else %}
<div class="waiting" style="grid-column:1 / -1">NO SECURITY EVENTS SAVED</div>
{% endif %}
</div>

</div>
</div>


<!-- =======================================================
     RIGHT AI
     ======================================================= -->

<div class="right-column">


<div class="panel">

<div class="panel-head">

<div class="panel-title">
AI IDENTIFICATION
</div>

<div class="live">
REAL-TIME
</div>

</div>


<div class="ai-body">


<!-- FACE SCANNER -->

<div class="scanner-row">


<div class="scanner">

<div class="scanner-label">
FACE BIOMETRIC
</div>

<div class="ring ring1"></div>
<div class="ring ring2"></div>
<div class="ring ring3"></div>

<div class="face"></div>

<div class="scanline"></div>

</div>


<div class="scan-info">

<div class="scan-title">
CURRENT STATUS
</div>

<div class="scan-status">

<div class="shield">
✓
</div>

<div id="faceStatus">
SCANNING
</div>

</div>


<div class="scan-detail">

DETECTED BY

<br>

FACE AI

<br><br>

LAST UPDATE

<br>

<span id="faceUpdate">
--
</span>

</div>

</div>


</div>


<!-- VEHICLE SCANNER -->

<div class="scanner-row">


<div class="scanner">

<div class="scanner-label">
VEHICLE / LPR
</div>

<div class="ring ring1"></div>
<div class="ring ring2"></div>
<div class="ring ring3"></div>

<div class="car">

<div class="light left-light"></div>
<div class="light right-light"></div>

</div>

<div class="scanline"></div>

</div>


<div class="scan-info">

<div class="scan-title">
VEHICLE STATUS
</div>

<div class="scan-status">

<div class="shield">
✓
</div>

<div id="vehicleStatus">
SCANNING
</div>

</div>


<div class="scan-detail">

PLATE READ

<div
    id="scannerPlate"
    class="scan-plate"
>
------
</div>

<br>

DETECTED BY

<br>

LPR AI

</div>

</div>


</div>


<!-- SECURITY CONTROLS -->

<div class="rec-title">
AI SECURITY CONTROLS
</div>


<div id="cloudPlanCard" style="grid-column:1 / -1;border:1px solid #164b67;padding:10px;margin-bottom:8px;font-size:10px;color:#8ba9b8;background:rgba(2,15,24,.72);">
  <div style="display:flex;justify-content:space-between"><span>CLOUD PLAN</span><strong id="cloudPlanName" style="color:#34d9ff">CHECKING...</strong></div>
  <div id="cloudPlanUsage" style="margin-top:6px;color:#d8f4ff">Loading plan limits...</div>
</div>

<div class="security-controls">

<button
    type="button"
    id="openFaceEnroll"
    class="security-button face-button"
>
＋ ADD FACE
</button>


<button
    type="button"
    id="openVehicleEnroll"
    class="security-button vehicle-button"
>
＋ ADD VEHICLE
</button>


<button
    type="button"
    id="openFaceLibrary"
    class="security-button"
>
FACE LIBRARY
</button>


<button
    type="button"
    id="openVehicleLibrary"
    class="security-button"
>
KNOWN VEHICLES
</button>


<button
    type="button"
    id="goHistory"
    class="security-button"
    style="grid-column:1 / -1"
>
EVENT HISTORY
</button>


<button
    type="button"
    id="cameraToggle"
    class="security-button"
    style="grid-column:1 / -1; border-color:#9a6200; color:#ffb23c;"
>
CAMERA AI • CHECKING...
</button>

<button
    type="button"
    id="objectAiToggle"
    class="security-button"
    style="grid-column:1 / -1; border-color:#9a6200; color:#ffb23c;"
>
OBJECT AI • CHECKING...
</button>
<div id="objectAiPanel" style="grid-column:1 / -1; border:1px solid #164b67; padding:9px; font-size:10px; color:#8ba9b8; background:rgba(2,15,24,.72);">
  <div style="display:flex;justify-content:space-between"><span>OBJECTS DETECTED</span><span id="objectAiCount">0</span></div>
  <div id="objectAiList" style="margin-top:7px;color:#d8f4ff;line-height:1.6">WAITING FOR OBJECTS...</div>
</div>

<button
    type="button"
    id="droneToggle"
    class="security-button"
    style="grid-column:1 / -1; border-color:#9a6200; color:#ffb23c;"
>
DRONE AI • CHECKING...
</button>

<button type="button" id="droneTrackingToggle" class="security-button" style="grid-column:1 / -1; border-color:#385e74; color:#7edcff;">
DRONE TRACKING ASSIST • OFF
</button>
<div id="droneTrackingPanel" style="grid-column:1 / -1; border:1px solid #164b67; padding:10px; font-size:10px; color:#8ba9b8; background:rgba(2,15,24,.72);">
  <div style="display:flex; justify-content:space-between;"><span>TRACK TARGET</span><span id="droneTrackState">OFF</span></div>
  <div id="droneTrackLabel" style="margin-top:8px; font-size:13px; color:#d8f4ff;">NO TARGET</div>
  <div id="droneTrackDirection" style="margin-top:5px; font-size:18px; font-weight:bold; color:#34d9ff;">WAITING</div>
  <div style="margin-top:6px; font-size:8px; color:#617f8f;">MANUAL FLIGHT GUIDANCE — KEEP THE TARGET CENTERED</div>
</div>

<button
    type="button"
    id="voiceControlButton"
    class="security-button voice-button"
>
<span class="voice-bars">
<span></span><span></span><span></span><span></span><span></span>
</span>
VOICE COMMAND
</button>


<div class="voice-console">
<div class="voice-console-head">
<span>VOICE INTERACTION</span>
<span id="voiceState" class="voice-state">READY</span>
</div>
<div id="voiceTranscript" class="voice-transcript">
Say “add face”, “add face John Smith”, “start scan”, or “system status”.
</div>
<div class="voice-hint">
Commands: Add Face • Start Scan • Cancel Scan • Add Vehicle • Face Library • Known Vehicles • Event History • System Status • What Did You Detect • Close
</div>
</div>


</div>


<div class="rec-title">
CURRENT RECOGNITION
</div>


<div id="recognition">

<div class="waiting">

AI scanners active —
waiting for detection...

</div>

</div>


</div>

</div>


</div>


</div>


<!-- =======================================================
     FACE ENROLLMENT MODAL
     ======================================================= -->

<div
    id="faceEnrollOverlay"
    class="enroll-overlay"
>


<div class="enroll-window">


<div class="enroll-header">

<div>
SECURE BIOMETRIC FACE ENROLLMENT
</div>

<button
    type="button"
    id="closeFaceEnroll"
    class="close-enroll"
>
×
</button>

</div>


<div class="enroll-content">


<!-- LIVE BIOMETRIC VIEW -->

<div
    id="enrollScanner"
    class="enroll-scanner"
>

<img
    id="enrollCameraFeed"
    src="/video_feed"
    class="enroll-live-camera"
>

<div class="enroll-blue-filter"></div>

<div class="enroll-grid"></div>

<div class="enroll-ring ring-a"></div>
<div class="enroll-ring ring-b"></div>
<div class="enroll-ring ring-c"></div>


<div class="face-target">

<div class="face-landmark lm1"></div>
<div class="face-landmark lm2"></div>
<div class="face-landmark lm3"></div>
<div class="face-landmark lm4"></div>
<div class="face-landmark lm5"></div>

</div>


<div class="enroll-scan-line"></div>


<div class="scanner-corner ec1"></div>
<div class="scanner-corner ec2"></div>
<div class="scanner-corner ec3"></div>
<div class="scanner-corner ec4"></div>


<div
    id="enrollScannerText"
    class="scanner-message"
>
READY FOR BIOMETRIC CAPTURE
</div>


</div>


<!-- ENROLLMENT CONTROLS -->

<div class="enroll-panel">


<div class="enroll-label">
PERSON NAME
</div>


<input
    id="faceName"
    class="enroll-input"
    type="text"
    autocomplete="off"
    placeholder="Enter person's name"
>

<div class="enroll-label" style="margin-top:12px;">CAPTURE SOURCE</div>
<select id="faceEnrollSource" class="enroll-input">
    <option value="camera">MAIN CAMERA</option>
    <option value="drone">DRONE</option>
</select>

<div class="security-note">

SECURE ENROLLMENT PROCEDURE

<br><br>

• Only one person should be visible.

<br>

• Keep the face inside the blue frame.

<br>

• Good lighting is required.

<br>

• Hold still during each capture.

<br>

• The system captures 3 facial samples.

<br><br>

The movement prompts improve the
variety of stored samples. They are
guidance prompts rather than certified
liveness detection.

</div>


<button
    type="button"
    id="startFaceEnrollment"
    class="start-scan-button"
>
START BIOMETRIC SCAN
</button>


<button
    type="button"
    id="cancelFaceEnrollment"
    class="cancel-scan-button"
>
CANCEL SCAN
</button>


<div class="progress-area">


<div class="progress-header">

<span id="enrollStage">
READY
</span>

<span id="enrollPercent">
0%
</span>

</div>


<div class="progress-track">

<div
    id="enrollProgress"
    class="progress-fill"
></div>

</div>


<div class="sample-dots">

<div
    id="sample1"
    class="sample-dot"
></div>

<div
    id="sample2"
    class="sample-dot"
></div>

<div
    id="sample3"
    class="sample-dot"
></div>

<div id="sample4" class="sample-dot" style="display:none"></div>
<div id="sample5" class="sample-dot" style="display:none"></div>

</div>


<div
    id="enrollMessage"
    class="enroll-message"
>
Position the person's face
inside the scanner.
</div>


</div>


</div>


</div>

</div>

</div>


<!-- =======================================================
     VEHICLE ENROLLMENT MODAL
     ======================================================= -->

<div
    id="vehicleEnrollOverlay"
    class="enroll-overlay"
>


<div class="enroll-window small-window">


<div class="enroll-header">

<div>
VEHICLE / LPR ENROLLMENT
</div>

<button
    id="closeVehicleEnroll"
    class="close-enroll"
    type="button"
>
×
</button>

</div>


<div class="vehicle-enroll-body">


<div class="mini-car-scanner">

<div class="mini-radar"></div>

<div class="mini-car">
🚙
</div>

<div class="vehicle-sweep"></div>

</div>


<div>


<div class="enroll-label">
VEHICLE NAME
</div>


<input
    id="newVehicleName"
    class="enroll-input"
    type="text"
    placeholder="Example: Tony F150"
>


<div
    class="enroll-label vehicle-label-space"
>
LICENSE PLATE
</div>


<input
    id="newVehiclePlate"
    class="enroll-input plate-input"
    type="text"
    placeholder="ABC123 — leave blank to use latest LPR"
>

<div class="enroll-label" style="margin-top:12px;">DETECTION SOURCE</div>
<select id="vehicleEnrollSource" class="enroll-input">
    <option value="camera">MAIN CAMERA</option>
    <option value="drone">DRONE</option>
</select>

<button
    id="saveVehicle"
    type="button"
    class="start-scan-button"
>
REGISTER VEHICLE
</button>


<div
    id="vehicleSaveMessage"
    class="enroll-message"
></div>


</div>


</div>

</div>

</div>


<!-- =======================================================
     FACE LIBRARY MODAL
     ======================================================= -->

<div
    id="faceLibraryOverlay"
    class="enroll-overlay"
>


<div class="enroll-window small-window">


<div class="enroll-header">

<div>
FACE LIBRARY
</div>

<button
    id="closeFaceLibrary"
    class="close-enroll"
    type="button"
>
×
</button>

</div>


<div class="simple-body">

<div
    id="faceLibraryContent"
    class="library-grid"
>

<div class="waiting">
Loading face library...
</div>

</div>

</div>


</div>

</div>


<!-- =======================================================
     VEHICLE LIBRARY MODAL
     ======================================================= -->

<div
    id="vehicleLibraryOverlay"
    class="enroll-overlay"
>


<div class="enroll-window small-window">


<div class="enroll-header">

<div>
KNOWN VEHICLES
</div>

<button
    id="closeVehicleLibrary"
    class="close-enroll"
    type="button"
>
×
</button>

</div>


<div class="simple-body">

<div
    id="vehicleLibraryContent"
    class="library-grid"
>

<div class="waiting">
Loading vehicles...
</div>

</div>

</div>


</div>

</div>


<script>

/* ==========================================================
   CLOCK
   ========================================================== */

function updateClock() {

    const now =
        new Date();

    document.getElementById(
        "clock"
    ).innerText =
        now.toLocaleTimeString();

    document.getElementById(
        "date"
    ).innerText =
        now.toLocaleDateString();
}


setInterval(
    updateClock,
    1000
);

updateClock();


/* ==========================================================
   MATRIX RUNNING NUMBERS
   ========================================================== */

const canvas =
    document.getElementById(
        "matrixCanvas"
    );

const ctx =
    canvas.getContext(
        "2d"
    );

const fontSize = 13;

let drops = [];


function resizeMatrix() {

    const parent =
        canvas.parentElement;

    canvas.width =
        parent.clientWidth;

    canvas.height =
        parent.clientHeight;

    const columns =
        Math.floor(
            canvas.width
            / fontSize
        );

    drops =
        new Array(columns)
        .fill(1)
        .map(
            () =>
                Math.floor(
                    Math.random()
                    * canvas.height
                    / fontSize
                )
        );
}


function drawMatrix() {

    ctx.fillStyle =
        "rgba(0,8,5,0.12)";

    ctx.fillRect(
        0,
        0,
        canvas.width,
        canvas.height
    );

    ctx.font =
        fontSize
        + "px Consolas, monospace";


    for (
        let i = 0;
        i < drops.length;
        i++
    ) {

        const random =
            Math.random();

        let character;

        if (random < .40) {

            character =
                Math.floor(
                    Math.random()
                    * 10
                );

        }

        else if (random < .80) {

            character =
                Math.random() > .5
                ? "1"
                : "0";

        }

        else {

            character =
                String.fromCharCode(
                    65
                    +
                    Math.floor(
                        Math.random()
                        * 6
                    )
                );
        }


        if (
            Math.random()
            > .93
        ) {

            ctx.fillStyle =
                "#9affad";

        }

        else {

            ctx.fillStyle =
                "#12c755";
        }


        ctx.fillText(
            character,
            i * fontSize,
            drops[i] * fontSize
        );


        if (
            drops[i] * fontSize
            > canvas.height
            &&
            Math.random() > .97
        ) {

            drops[i] = 0;

        }

        else {

            drops[i] += .65;
        }
    }
}


resizeMatrix();

window.addEventListener(
    "resize",
    resizeMatrix
);

setInterval(
    drawMatrix,
    110
);


/* ==========================================================
   STATUS
   ========================================================== */

let lastDashboardStatus = null;
let lastDetectedFace = "";
let lastDetectedVehicle = "";
let lastDetectedPlate = "";

async function refreshStatus() {

    try {

        const response =
            await fetch(
                "/api/status"
            );

        const d =
            await response.json();

        lastDashboardStatus = d;
        if (d.face) lastDetectedFace = d.face;
        if (d.vehicle && !d.unknown_vehicle) lastDetectedVehicle = d.vehicle;
        if (d.plate && !d.unknown_vehicle) lastDetectedPlate = d.plate;


        document.getElementById(
            "faceCount"
        ).innerText =
            d.face_count;


        document.getElementById(
            "plateCount"
        ).innerText =
            d.plate_count;


        document.getElementById(
            "totalCount"
        ).innerText =
            d.total_events;


        document.getElementById(
            "leftCamera"
        ).innerText =
            d.camera
            ? "ONLINE"
            : "OFFLINE";


        document.getElementById(
            "leftMqtt"
        ).innerText =
            d.mqtt
            ? "CONNECTED"
            : "OFFLINE";


        document.getElementById(
            "topCamera"
        ).innerHTML =
            d.camera

            ? '<span class="dot"></span>ONLINE'

            : '<span class="dot" style="background:#ff4558;box-shadow:0 0 10px #ff4558"></span>OFFLINE';


        document.getElementById(
            "topMqtt"
        ).innerHTML =
            d.mqtt

            ? '<span class="dot"></span>CONNECTED'

            : '<span class="dot" style="background:#ff4558;box-shadow:0 0 10px #ff4558"></span>OFFLINE';


        const alertActive =
            d.unknown_face
            ||
            d.unknown_vehicle;


        document.getElementById(
            "topSystem"
        ).innerHTML =
            alertActive

            ? '<span class="dot" style="background:#ff4558;box-shadow:0 0 10px #ff4558"></span>ALERT'

            : '<span class="dot"></span>PROTECTED';


        document.getElementById(
            "health"
        ).innerText =
            d.camera
            &&
            d.mqtt

            ? "READY"

            : "CHECK";


        /* FACE */

        const faceStatus =
            document.getElementById(
                "faceStatus"
            );


        if (d.unknown_face) {

            faceStatus.innerText =
                "UNKNOWN";

            faceStatus.style.color =
                "#ff5364";

        }

        else if (d.face) {

            faceStatus.innerText =
                "AUTHORIZED";

            faceStatus.style.color =
                "#2eee91";

        }

        else {

            faceStatus.innerText =
                "SCANNING";

            faceStatus.style.color =
                "#39c8ff";
        }


        /* VEHICLE */

        const vehicleStatus =
            document.getElementById(
                "vehicleStatus"
            );


        if (d.unknown_vehicle) {

            vehicleStatus.innerText =
                "UNKNOWN";

            vehicleStatus.style.color =
                "#ffb62b";

        }

        else if (d.plate) {

            vehicleStatus.innerText =
                "AUTHORIZED";

            vehicleStatus.style.color =
                "#2eee91";

        }

        else {

            vehicleStatus.innerText =
                "SCANNING";

            vehicleStatus.style.color =
                "#39c8ff";
        }


        document.getElementById(
            "scannerPlate"
        ).innerText =
            d.plate
            ||
            "------";


        /* CURRENT RECOGNITION — MULTI TARGET */

        let html = "";

        const activeFaces = Array.isArray(d.active_faces) ? d.active_faces : [];
        const activeVehicles = Array.isArray(d.active_vehicles) ? d.active_vehicles : [];

        activeFaces.forEach(faceItem => {
            const known = !!faceItem.known;
            const label = faceItem.label || (known ? "KNOWN PERSON" : "PERSON");

            if (known) {
                html += `
                <div class="rec-card person-card">
                    <div class="rec-row">
                        <div class="rec-icon">◉</div>
                        <div class="rec-info">
                            <div class="rec-label">IDENTITY VERIFIED</div>
                            <div class="rec-name">${label}</div>
                            <div class="rec-sub">Authorized Person</div>
                        </div>
                        <div class="check">✓</div>
                    </div>
                </div>`;
            } else {
                html += `
                <div class="rec-card unknown-person">
                    <div class="rec-row">
                        <div class="rec-icon">!</div>
                        <div class="rec-info">
                            <div class="rec-label">${label === "PERSON" ? "PERSON DETECTED" : "UNKNOWN PERSON ALERT"}</div>
                            <div class="rec-sub">${label === "PERSON" ? "Face identification pending" : "Identity not recognized"}</div>
                        </div>
                    </div>
                </div>`;
            }
        });

        activeVehicles.forEach(vehicleItem => {
            const known = !!vehicleItem.known;
            const label = vehicleItem.label || (known ? "KNOWN VEHICLE" : "VEHICLE");
            const plate = vehicleItem.plate || "";

            if (known) {
                html += `
                <div class="rec-card vehicle-card">
                    <div class="rec-row">
                        <div class="rec-icon">🚙</div>
                        <div class="rec-info">
                            <div class="rec-label">VEHICLE AUTHORIZED</div>
                            <div class="rec-name">${label}</div>
                            <div class="rec-sub">${plate ? "Plate: " + plate : "Vehicle recognized"}</div>
                        </div>
                        ${plate ? `<div class="plate-box">${plate}</div>` : ""}
                        <div class="check">✓</div>
                    </div>
                </div>`;
            } else {
                html += `
                <div class="rec-card unknown-vehicle">
                    <div class="rec-row">
                        <div class="rec-icon">!</div>
                        <div class="rec-info">
                            <div class="rec-label">${plate ? "UNKNOWN VEHICLE ALERT" : "VEHICLE DETECTED"}</div>
                            <div class="rec-sub">${plate ? "Unregistered plate: " + plate : "Plate identification pending"}</div>
                        </div>
                    </div>
                </div>`;
            }
        });

        // Backward-compatible fallback if an older state reaches the browser.
        if (!activeFaces.length && d.face) {
            html += `
            <div class="rec-card person-card">
                <div class="rec-row">
                    <div class="rec-icon">◉</div>
                    <div class="rec-info">
                        <div class="rec-label">IDENTITY VERIFIED</div>
                        <div class="rec-name">${d.face}</div>
                        <div class="rec-sub">Authorized Person</div>
                    </div>
                    <div class="check">✓</div>
                </div>
            </div>`;
        }

        if (!activeVehicles.length && d.plate && !d.unknown_vehicle) {
            html += `
            <div class="rec-card vehicle-card">
                <div class="rec-row">
                    <div class="rec-icon">🚙</div>
                    <div class="rec-info">
                        <div class="rec-label">VEHICLE AUTHORIZED</div>
                        <div class="rec-name">${d.vehicle}</div>
                        <div class="rec-sub">Plate: ${d.plate}</div>
                    </div>
                    <div class="plate-box">${d.plate}</div>
                    <div class="check">✓</div>
                </div>
            </div>`;
        }


        if (!html) {

            html = `

            <div class="waiting">
                AI scanners active —
                waiting for detection...
            </div>

            `;
        }


        document.getElementById(
            "recognition"
        ).innerHTML =
            html;


        if (
            d.face
            ||
            d.unknown_face
        ) {

            document.getElementById(
                "faceUpdate"
            ).innerText =
                new Date()
                .toLocaleTimeString();
        }


    }

    catch (error) {

        console.log(
            "Dashboard status error:",
            error
        );
    }
}


setInterval(
    refreshStatus,
    750
);

refreshStatus();


/* ==========================================================
   VOICE INTERACTION
   ========================================================== */

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let voiceRecognition = null;
let voiceListening = false;
let voicePendingAction = "";

const voiceButton = document.getElementById("voiceControlButton");
const voiceState = document.getElementById("voiceState");
const voiceTranscript = document.getElementById("voiceTranscript");

function setVoiceUI(state, text = "") {
    if (voiceState) {
        voiceState.innerText = state;
        voiceState.classList.toggle("active", state === "LISTENING");
    }
    if (voiceButton) {
        voiceButton.classList.toggle("listening", state === "LISTENING");
        voiceButton.innerHTML = state === "LISTENING"
            ? '<span class="voice-bars"><span></span><span></span><span></span><span></span><span></span></span>LISTENING...'
            : '<span class="voice-bars"><span></span><span></span><span></span><span></span><span></span></span>VOICE COMMAND';
    }
    if (text && voiceTranscript) voiceTranscript.innerText = text;
}

function speakDashboard(text, thenListen = false) {
    if (!("speechSynthesis" in window)) {
        if (thenListen) setTimeout(startVoiceListening, 250);
        return;
    }
    try {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 0.98;
        utterance.pitch = 1.0;
        utterance.volume = 0.9;
        utterance.onend = () => {
            if (thenListen) setTimeout(startVoiceListening, 300);
        };
        window.speechSynthesis.speak(utterance);
    } catch (error) {
        if (thenListen) setTimeout(startVoiceListening, 300);
    }
}

function openFaceEnrollmentByVoice() {
    document.getElementById("faceEnrollOverlay").classList.add("open");
    setTimeout(() => document.getElementById("faceName").focus(), 100);
}

function openVehicleEnrollmentByVoice() {
    document.getElementById("vehicleEnrollOverlay").classList.add("open");
    setTimeout(() => document.getElementById("newVehicleName").focus(), 100);
}

function closeVoiceTarget() {
    document.querySelectorAll(".enroll-overlay.open").forEach(el => el.classList.remove("open"));
    stopBiometricSound();
    voicePendingAction = "";
    speakDashboard("Closed.");
}

function normalizeSpokenPlate(text) {
    return text.toUpperCase().replace(/\b(DASH|HYPHEN|SPACE)\b/g, "").replace(/[^A-Z0-9]/g, "");
}

function titleCaseVoiceName(text) {
    return text.trim().replace(/\s+/g, " ").split(" ")
        .map(word => word ? word.charAt(0).toUpperCase() + word.slice(1).toLowerCase() : "")
        .join(" ");
}

async function handleVoiceCommand(rawTranscript) {
    const transcript = rawTranscript.trim();
    const command = transcript.toLowerCase().replace(/[.,!?]/g, "").trim();
    if (!command) return;

    setVoiceUI("PROCESSING", 'Heard: “' + transcript + '”');

    if (voicePendingAction === "face_name") {
        const name = titleCaseVoiceName(transcript);
        document.getElementById("faceName").value = name;
        openFaceEnrollmentByVoice();
        voicePendingAction = "";
        speakDashboard("Name set to " + name + ". Say start scan when ready.");
        setVoiceUI("READY", "Person name: " + name + ". Say “start scan” when ready.");
        return;
    }

    if (voicePendingAction === "vehicle_name") {
        const vehicleName = transcript.trim();
        document.getElementById("newVehicleName").value = vehicleName;
        openVehicleEnrollmentByVoice();
        voicePendingAction = "vehicle_plate";
        speakDashboard("Vehicle name set to " + vehicleName + ". What is the license plate?", true);
        return;
    }

    if (voicePendingAction === "vehicle_plate") {
        const plate = normalizeSpokenPlate(transcript);
        document.getElementById("newVehiclePlate").value = plate;
        voicePendingAction = "";
        speakDashboard("Plate set to " + plate.split("").join(" ") + ". Say register vehicle to save it.");
        setVoiceUI("READY", "Plate: " + plate + ". Say “register vehicle” to save.");
        return;
    }

    let match = transcript.match(/^\s*(?:add|register|enroll)\s+(?:face|person)\s+(.+)$/i);
    if (match && match[1].trim()) {
        const name = titleCaseVoiceName(match[1]);
        document.getElementById("faceName").value = name;
        openFaceEnrollmentByVoice();
        speakDashboard("Face enrollment opened for " + name + ". Say start scan when ready.");
        setVoiceUI("READY", "Enrollment ready for " + name + ".");
        return;
    }

    if (/^(add|register|enroll) (a )?(face|person)$/.test(command)) {
        openFaceEnrollmentByVoice();
        voicePendingAction = "face_name";
        speakDashboard("Face enrollment ready. What is the person's name?", true);
        return;
    }

    if (/^(start|begin) (biometric )?(face )?scan$/.test(command) || command === "start scan") {
        openFaceEnrollmentByVoice();
        const name = document.getElementById("faceName").value.trim();
        if (!name) {
            voicePendingAction = "face_name";
            speakDashboard("I need the person's name first. What is the name?", true);
            return;
        }
        speakDashboard("Starting biometric scan for " + name + ".");
        document.getElementById("startFaceEnrollment").click();
        setVoiceUI("READY", "Biometric scan started for " + name + ".");
        return;
    }

    if (/^(cancel|stop) (the )?(biometric )?(face )?scan$/.test(command) || command === "cancel scan") {
        document.getElementById("cancelFaceEnrollment").click();
        voicePendingAction = "";
        speakDashboard("Biometric scan cancelled.");
        setVoiceUI("READY", "Biometric scan cancelled.");
        return;
    }

    match = transcript.match(/^\s*(?:add|register)\s+vehicle\s+(.+?)\s+plate\s+([A-Za-z0-9\s-]+)$/i);
    if (match) {
        const vehicleName = match[1].trim();
        const plate = normalizeSpokenPlate(match[2]);
        document.getElementById("newVehicleName").value = vehicleName;
        document.getElementById("newVehiclePlate").value = plate;
        openVehicleEnrollmentByVoice();
        speakDashboard("Vehicle information entered. Say register vehicle to save it.");
        setVoiceUI("READY", vehicleName + " • " + plate);
        return;
    }

    if (/^(add|register) (a )?vehicle$/.test(command)) {
        openVehicleEnrollmentByVoice();
        voicePendingAction = "vehicle_name";
        speakDashboard("Vehicle enrollment ready. What is the vehicle name?", true);
        return;
    }

    if (command === "register vehicle" || command === "save vehicle") {
        const vehicle = document.getElementById("newVehicleName").value.trim();
        const plate = document.getElementById("newVehiclePlate").value.trim();
        if (!vehicle) {
            voicePendingAction = "vehicle_name";
            speakDashboard("I need the vehicle name first. What is the vehicle name?", true);
            return;
        }
        if (!plate) {
            voicePendingAction = "vehicle_plate";
            speakDashboard("I need the license plate. What is the plate?", true);
            return;
        }
        document.getElementById("saveVehicle").click();
        speakDashboard("Registering " + vehicle + " with plate " + plate.split("").join(" ") + ".");
        setVoiceUI("READY", "Registering vehicle " + vehicle + " • " + plate);
        return;
    }

    if (command.includes("face library") || command === "show faces") {
        document.getElementById("openFaceLibrary").click();
        speakDashboard("Opening face library.");
        setVoiceUI("READY", "Face library opened.");
        return;
    }

    if (command.includes("known vehicles") || command.includes("vehicle library")) {
        document.getElementById("openVehicleLibrary").click();
        speakDashboard("Opening known vehicles.");
        setVoiceUI("READY", "Known vehicles opened.");
        return;
    }

    if (command.includes("event history") || command === "show history" || command === "history") {
        document.getElementById("goHistory").click();
        speakDashboard("Showing event history.");
        setVoiceUI("READY", "Event history displayed.");
        return;
    }

    if (command === "system status" || command === "security status" || command === "status") {
        const d = lastDashboardStatus;
        if (!d) {
            speakDashboard("System status is not available yet.");
            return;
        }
        const cameraText = d.camera ? "camera online" : "camera offline";
        const mqttText = d.mqtt ? "M Q T T connected" : "M Q T T offline";
        const alertText = (d.unknown_face || d.unknown_vehicle)
            ? "Attention. An unknown detection is active."
            : "No active unknown alerts.";
        const text = "System status. " + cameraText + ". " + mqttText + ". " + alertText;
        speakDashboard(text);
        setVoiceUI("READY", text);
        return;
    }

    if (command.includes("what did you detect") || command.includes("last detection") || command.includes("who did you see")) {
        const pieces = [];
        if (lastDetectedFace) pieces.push("Last recognized person was " + lastDetectedFace);
        if (lastDetectedVehicle) {
            let vehicleText = "last recognized vehicle was " + lastDetectedVehicle;
            if (lastDetectedPlate) vehicleText += " with plate " + lastDetectedPlate.split("").join(" ");
            pieces.push(vehicleText);
        }
        const text = pieces.length ? pieces.join(". ") + "." : "I do not have a recent recognized person or vehicle yet.";
        speakDashboard(text);
        setVoiceUI("READY", text);
        return;
    }

    if (command === "close" || command === "close window" || command === "go back") {
        closeVoiceTarget();
        setVoiceUI("READY", "Closed.");
        return;
    }

    if (command === "help" || command === "voice help" || command === "commands") {
        const help = "You can say add face, add face followed by a name, start scan, cancel scan, add vehicle, face library, known vehicles, event history, system status, what did you detect, or close.";
        speakDashboard(help);
        setVoiceUI("READY", help);
        return;
    }

    if (command.includes("delete event")) {
        const text = "For safety, voice control does not delete events. Please use the delete event button and confirm it on screen.";
        speakDashboard(text);
        setVoiceUI("READY", text);
        return;
    }

    const notUnderstood = "Command not recognized. Say voice help to hear available commands.";
    speakDashboard(notUnderstood);
    setVoiceUI("READY", notUnderstood);
}

function setupVoiceRecognition() {
    if (!SpeechRecognition) {
        setVoiceUI("UNAVAILABLE", "Voice recognition is not supported by this browser. Use Microsoft Edge or Google Chrome and allow microphone access.");
        if (voiceButton) voiceButton.disabled = true;
        return;
    }

    voiceRecognition = new SpeechRecognition();
    voiceRecognition.lang = "en-CA";
    voiceRecognition.continuous = false;
    voiceRecognition.interimResults = true;
    voiceRecognition.maxAlternatives = 1;

    voiceRecognition.onstart = () => {
        voiceListening = true;
        setVoiceUI("LISTENING", "Listening for a command...");
    };

    voiceRecognition.onresult = event => {
        let interim = "";
        let finalText = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
            const text = event.results[i][0].transcript;
            if (event.results[i].isFinal) finalText += text;
            else interim += text;
        }
        if (interim) setVoiceUI("LISTENING", interim);
        if (finalText.trim()) handleVoiceCommand(finalText.trim());
    };

    voiceRecognition.onerror = event => {
        voiceListening = false;
        if (event.error === "not-allowed" || event.error === "service-not-allowed") {
            setVoiceUI("MIC BLOCKED", "Microphone permission is blocked. Allow microphone access for this dashboard, then try again.");
        } else if (event.error === "no-speech") {
            setVoiceUI("READY", "No speech heard. Press Voice Command and try again.");
        } else if (event.error !== "aborted") {
            setVoiceUI("ERROR", "Voice recognition error: " + event.error);
        }
    };

    voiceRecognition.onend = () => {
        voiceListening = false;
        if (voiceState && voiceState.innerText === "LISTENING") {
            setVoiceUI("READY", voiceTranscript ? voiceTranscript.innerText : "Ready.");
        }
    };
}

function startVoiceListening() {
    if (!voiceRecognition) return;
    try {
        if ("speechSynthesis" in window) window.speechSynthesis.cancel();
        if (voiceListening) voiceRecognition.stop();
        setTimeout(() => {
            try { voiceRecognition.start(); }
            catch (error) { }
        }, voiceListening ? 180 : 0);
    } catch (error) {
        setVoiceUI("ERROR", "Could not start microphone. Check browser microphone permission.");
    }
}

setupVoiceRecognition();

if (voiceButton) {
    voiceButton.addEventListener("click", () => {
        if (!voiceRecognition) return;
        if (voiceListening) {
            voiceRecognition.stop();
            setVoiceUI("READY", "Voice listening stopped.");
        } else {
            startVoiceListening();
        }
    });
}

document.addEventListener("keydown", event => {
    const tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || event.target.isContentEditable) return;
    if (event.key.toLowerCase() === "v") {
        event.preventDefault();
        startVoiceListening();
    }
});


/* ==========================================================
   MODALS
   ========================================================== */

const faceOverlay =
    document.getElementById(
        "faceEnrollOverlay"
    );

const vehicleOverlay =
    document.getElementById(
        "vehicleEnrollOverlay"
    );

const faceLibraryOverlay =
    document.getElementById(
        "faceLibraryOverlay"
    );

const vehicleLibraryOverlay =
    document.getElementById(
        "vehicleLibraryOverlay"
    );


document.getElementById(
    "openFaceEnroll"
).addEventListener(
    "click",
    () => {

        faceOverlay
            .classList
            .add("open");

        setTimeout(
            () => {

                document.getElementById(
                    "faceName"
                ).focus();

            },
            100
        );
    }
);


document.getElementById(
    "closeFaceEnroll"
).addEventListener(
    "click",
    () => {

        faceOverlay
            .classList
            .remove("open");

        stopBiometricSound();
    }
);


document.getElementById(
    "openVehicleEnroll"
).addEventListener(
    "click",
    () => {

        vehicleOverlay
            .classList
            .add("open");
    }
);


document.getElementById(
    "closeVehicleEnroll"
).addEventListener(
    "click",
    () => {

        vehicleOverlay
            .classList
            .remove("open");
    }
);


document.getElementById(
    "closeFaceLibrary"
).addEventListener(
    "click",
    () => {

        faceLibraryOverlay
            .classList
            .remove("open");
    }
);


document.getElementById(
    "closeVehicleLibrary"
).addEventListener(
    "click",
    () => {

        vehicleLibraryOverlay
            .classList
            .remove("open");
    }
);



/* ==========================================================
   CLOUD PLAN / LIMITS
   ========================================================== */
async function refreshCloudPlan() {
    try {
        const r = await fetch("/api/cloud/status", {cache:"no-store"});
        const d = await r.json();
        const plan = document.getElementById("cloudPlanName");
        const usage = document.getElementById("cloudPlanUsage");
        if (plan) plan.innerText = String(d.plan_code || "UNKNOWN").toUpperCase();
        const cu = Number((d.usage||{}).cameras||0), du = Number((d.usage||{}).drones||0);
        const cl = (d.limits||{}).cameras, dl = (d.limits||{}).drones;
        if (usage) usage.innerText = `CAMERAS ${cu}/${cl == null ? "∞" : cl}  •  DRONES ${du}/${dl == null ? "∞" : dl}`;
        const faceBtn=document.getElementById("openFaceEnroll"), vehicleBtn=document.getElementById("openVehicleEnroll");
        if(faceBtn){faceBtn.disabled=!d.face_ai_allowed;faceBtn.title=d.face_ai_allowed?"":"Face AI is not included in this plan.";}
        if(vehicleBtn){vehicleBtn.disabled=!d.lpr_allowed;vehicleBtn.title=d.lpr_allowed?"":"LPR is not included in this plan.";}
    } catch(e) {}
}
refreshCloudPlan();
setInterval(refreshCloudPlan, 10000);

/* ==========================================================
   CAMERA AI ON / OFF
   ========================================================== */

const cameraToggle = document.getElementById("cameraToggle");
let cameraEnabled = true;
let cameraBusy = false;

function paintCameraButton(enabled, mqttOk=true) {
    if (!cameraToggle) return;
    cameraEnabled = !!enabled;
    if (!mqttOk) {
        cameraToggle.innerText = "CAMERA AI • MQTT OFFLINE";
        cameraToggle.style.borderColor = "#8c3030";
        cameraToggle.style.color = "#ff6262";
        cameraToggle.style.boxShadow = "none";
        return;
    }
    if (cameraEnabled) {
        cameraToggle.innerText = "CAMERA AI • ON — CLICK TO STOP";
        cameraToggle.style.borderColor = "#19d978";
        cameraToggle.style.color = "#35f59a";
        cameraToggle.style.boxShadow = "0 0 16px rgba(25,217,120,.18)";
    } else {
        cameraToggle.innerText = "CAMERA AI • OFF — CLICK TO START";
        cameraToggle.style.borderColor = "#9a6200";
        cameraToggle.style.color = "#ffb23c";
        cameraToggle.style.boxShadow = "none";
    }
}

async function refreshCameraStatus() {
    try {
        const response = await fetch("/api/camera/status", {cache: "no-store"});
        const data = await response.json();
        paintCameraButton(data.enabled, data.mqtt);
    } catch (error) {
        paintCameraButton(false, false);
    }
}

if (cameraToggle) {
    cameraToggle.addEventListener("click", async () => {
        if (cameraBusy) return;
        const nextState = !cameraEnabled;
        cameraBusy = true;
        cameraToggle.disabled = true;
        cameraToggle.innerText = nextState ? "STARTING CAMERA AI..." : "STOPPING CAMERA AI...";
        try {
            const response = await fetch("/api/camera/toggle", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({enabled: nextState}),
            });
            const result = await response.json();
            if (!response.ok || !result.ok) throw new Error(result.error || "Unable to change camera state.");
            paintCameraButton(result.enabled, true);
        } catch (error) {
            alert(error.message || "Unable to change camera state.");
            await refreshCameraStatus();
        } finally {
            cameraBusy = false;
            cameraToggle.disabled = false;
        }
    });
}

refreshCameraStatus();
setInterval(refreshCameraStatus, 3000);


/* ==========================================================
   OBJECT AI ON / OFF + LIVE LABEL LIST
   ========================================================== */
const objectAiToggle = document.getElementById("objectAiToggle");
const objectAiList = document.getElementById("objectAiList");
const objectAiCount = document.getElementById("objectAiCount");
let objectAiEnabled = true;

function paintObjectAi(data) {
    objectAiEnabled = !!data.enabled;
    if (objectAiToggle) {
        objectAiToggle.innerText = objectAiEnabled ? "OBJECT AI • ON — CLICK TO STOP" : "OBJECT AI • OFF — CLICK TO START";
        objectAiToggle.style.borderColor = objectAiEnabled ? "#19d978" : "#9a6200";
        objectAiToggle.style.color = objectAiEnabled ? "#35f59a" : "#ffb23c";
    }
    const objects = Array.isArray(data.objects) ? data.objects : [];
    if (objectAiCount) objectAiCount.innerText = objects.length;
    if (objectAiList) {
        objectAiList.innerHTML = objects.length ? objects.slice(0, 8).map(o => {
            const c = (o.confidence === null || o.confidence === undefined) ? "" : ` — ${o.confidence}%`;
            return `<div><b>${o.label}</b>${c} <span style="color:#617f8f">[${o.source}]</span></div>`;
        }).join("") : (objectAiEnabled ? "WAITING FOR OBJECTS..." : "OBJECT AI DISABLED");
    }
}
async function refreshObjectAi() {
    try { const r=await fetch("/api/object_ai/status", {cache:"no-store"}); paintObjectAi(await r.json()); } catch(e) {}
}
if (objectAiToggle) objectAiToggle.addEventListener("click", async () => {
    objectAiToggle.disabled = true;
    try {
        const r=await fetch("/api/object_ai/toggle", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({enabled:!objectAiEnabled})});
        paintObjectAi(await r.json());
        await refreshObjectAi();
    } finally { objectAiToggle.disabled=false; }
});
refreshObjectAi();
setInterval(refreshObjectAi, 1500);

/* ==========================================================
   DRONE AI ON / OFF
   ========================================================== */

const droneToggle = document.getElementById("droneToggle");
let droneEnabled = false;
let droneVideoOnline = false;
let droneBusy = false;

function paintDroneButton(enabled, mqttOk=true) {
    if (!droneToggle) return;
    droneEnabled = !!enabled;

    if (!mqttOk) {
        droneToggle.innerText = "DRONE AI • MQTT OFFLINE";
        droneToggle.style.borderColor = "#8c3030";
        droneToggle.style.color = "#ff6262";
        droneToggle.style.boxShadow = "none";
        return;
    }

    if (droneEnabled) {
        droneToggle.innerText = "DRONE AI • ON — CLICK TO STOP";
        droneToggle.style.borderColor = "#19d978";
        droneToggle.style.color = "#35f59a";
        droneToggle.style.boxShadow = "0 0 16px rgba(25,217,120,.18)";
    } else {
        droneToggle.innerText = "DRONE AI • OFF — CLICK TO START";
        droneToggle.style.borderColor = "#9a6200";
        droneToggle.style.color = "#ffb23c";
        droneToggle.style.boxShadow = "none";
    }
}

async function refreshDroneStatus() {
    try {
        const response = await fetch("/api/drone/status", {cache: "no-store"});
        const data = await response.json();
        droneVideoOnline = !!data.video;
        paintDroneButton(data.enabled, data.mqtt);
    } catch (error) {
        paintDroneButton(false, false);
    }
}

if (droneToggle) {
    droneToggle.addEventListener("click", async () => {
        if (droneBusy) return;
        const nextState = !droneEnabled;

        if (nextState) {
            const confirmed = confirm(
                "Start DRONE AI?\n\nMake sure DJI Fly is already livestreaming to the PC first."
            );
            if (!confirmed) return;
        }

        droneBusy = true;
        droneToggle.disabled = true;
        droneToggle.innerText = nextState ? "STARTING DRONE AI..." : "STOPPING DRONE AI...";

        try {
            const response = await fetch("/api/drone/toggle", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({enabled: nextState}),
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || "Unable to change drone state.");
            }
            paintDroneButton(result.enabled, true);
        } catch (error) {
            alert(error.message || "Unable to change drone state.");
            await refreshDroneStatus();
        } finally {
            droneBusy = false;
            droneToggle.disabled = false;
        }
    });
}

refreshDroneStatus();
setInterval(refreshDroneStatus, 3000);


/* DRONE TRACKING ASSIST */
const droneTrackingToggle = document.getElementById("droneTrackingToggle");
const droneTrackState = document.getElementById("droneTrackState");
const droneTrackLabel = document.getElementById("droneTrackLabel");
const droneTrackDirection = document.getElementById("droneTrackDirection");
let droneTrackingEnabled = false;
let latestDroneTrackingStatus = {
    enabled: false,
    active: false,
    known: false,
    label: "",
    direction: "WAITING"
};

function paintDroneTracking(d) {
    latestDroneTrackingStatus = d || latestDroneTrackingStatus;
    droneTrackingEnabled = !!d.enabled;
    if (droneTrackingToggle) {
        droneTrackingToggle.innerText = droneTrackingEnabled ? "DRONE TRACKING ASSIST • ON — CLICK TO STOP" : "DRONE TRACKING ASSIST • OFF — CLICK TO START";
        droneTrackingToggle.style.borderColor = droneTrackingEnabled ? "#18d67b" : "#385e74";
        droneTrackingToggle.style.color = droneTrackingEnabled ? "#35f59a" : "#7edcff";
    }
    if (!droneTrackingEnabled) {
        droneTrackState.innerText = "OFF"; droneTrackLabel.innerText = "NO TARGET"; droneTrackDirection.innerText = "WAITING"; droneTrackDirection.style.color = "#34d9ff"; return;
    }
    droneTrackState.innerText = d.active ? "LOCKED" : "SEARCHING";
    droneTrackLabel.innerText = d.active ? (d.label || "TARGET") : "SEARCHING FOR PERSON / VEHICLE";
    droneTrackDirection.innerText = d.active ? (d.direction || "CENTERED") : "WAITING";
    droneTrackDirection.style.color = d.active ? (d.known ? "#31ed88" : "#ff9e32") : "#34d9ff";
}
async function refreshDroneTracking() {
    try { const r = await fetch("/api/drone/tracking/status", {cache:"no-store"}); paintDroneTracking(await r.json()); } catch (e) {}
}
if (droneTrackingToggle) {
    droneTrackingToggle.addEventListener("click", async () => {
        const next = !droneTrackingEnabled;
        if (next && !droneEnabled) { alert("Start DRONE AI first, then enable Tracking Assist."); return; }
        const r = await fetch("/api/drone/tracking/toggle", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({enabled:next})});
        const d = await r.json();
        if (!r.ok || !d.ok) { alert(d.error || "Unable to change tracking-assist state."); return; }
        refreshDroneTracking();
    });
}
setInterval(refreshDroneTracking, 1500);
refreshDroneTracking();


/* ==========================================================
   EVENT HISTORY BUTTON
   ========================================================== */

const eventHistoryOverlay = document.getElementById("eventHistoryOverlay");

function openEventHistory() {
    if (eventHistoryOverlay) eventHistoryOverlay.classList.add("open");
}

function closeEventHistory() {
    if (eventHistoryOverlay) eventHistoryOverlay.classList.remove("open");
}

document.getElementById("goHistory").addEventListener("click", openEventHistory);

document.getElementById("viewAllHistory").addEventListener("click", openEventHistory);

document.getElementById("closeEventHistory").addEventListener("click", closeEventHistory);

eventHistoryOverlay.addEventListener("click", event => {
    if (event.target === eventHistoryOverlay) closeEventHistory();
});

document.getElementById("clearAllEvents").addEventListener("click", async () => {
    const confirmed = confirm(
        "CLEAR ALL SECURITY EVENTS?\n\nThis permanently removes every event-history row and all snapshots saved by the dashboard."
    );
    if (!confirmed) return;

    const button = document.getElementById("clearAllEvents");
    const oldText = button.innerText;
    button.disabled = true;
    button.innerText = "CLEARING...";

    try {
        const response = await fetch("/api/events", {method: "DELETE"});
        const result = await response.json();
        if (!result.ok) throw new Error(result.error || "Unable to clear event history.");
        window.location.reload();
    } catch (error) {
        alert(error.message || "Unable to clear event history.");
        button.disabled = false;
        button.innerText = oldText;
    }
});


/* ==========================================================
   DELETE SECURITY EVENT
   ========================================================== */

document.addEventListener("click", async event => {
    const button = event.target.closest(".delete-event-button");
    if (!button) return;

    const eventIndex = Number(button.dataset.eventIndex);
    const confirmed = confirm(
        "Delete this security event?\n\nThe event and its snapshot will be permanently removed."
    );
    if (!confirmed) return;

    const oldText = button.innerText;
    button.disabled = true;
    button.innerText = "DELETING...";

    try {
        const response = await fetch("/api/events/" + eventIndex, {method: "DELETE"});
        const result = await response.json();
        if (!result.ok) throw new Error(result.error || "Unable to delete event.");

        const card = button.closest(".event");
        if (card) {
            card.style.opacity = "0";
            card.style.transform = "scale(.94)";
            card.style.transition = ".25s ease";
        }
        setTimeout(() => window.location.reload(), 260);
    } catch (error) {
        alert(error.message || "Unable to delete event.");
        button.disabled = false;
        button.innerText = oldText;
    }
});


/* ==========================================================
   BIOMETRIC SCANNER AUDIO
   ========================================================== */

let biometricAudio = null;
let biometricBeepTimer = null;
let biometricSoundRunning = false;
let biometricLastStage = "";
let biometricFinishedState = "";

function getBiometricAudio() {
    if (!biometricAudio) {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return null;
        biometricAudio = new AudioContext();
    }
    if (biometricAudio.state === "suspended") biometricAudio.resume();
    return biometricAudio;
}

function scannerBeep(frequency=900, duration=0.055, volume=0.035) {
    const audio = getBiometricAudio();
    if (!audio) return;
    const oscillator = audio.createOscillator();
    const gain = audio.createGain();
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(frequency, audio.currentTime);
    gain.gain.setValueAtTime(volume, audio.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + duration);
    oscillator.connect(gain);
    gain.connect(audio.destination);
    oscillator.start();
    oscillator.stop(audio.currentTime + duration);
}

function biometricPulse() {
    scannerBeep(Math.random() > .5 ? 880 : 1120, .05, .032);
}

function startBiometricSound() {
    stopBiometricSound();
    biometricSoundRunning = true;
    biometricLastStage = "";
    biometricFinishedState = "";
    scannerBeep(620, .07, .04);
    setTimeout(() => scannerBeep(930, .06, .035), 90);
    biometricBeepTimer = setInterval(biometricPulse, 520);
}

function changeBiometricSpeed(milliseconds) {
    if (!biometricSoundRunning) return;
    clearInterval(biometricBeepTimer);
    biometricBeepTimer = setInterval(biometricPulse, milliseconds);
}

function stopBiometricSound() {
    biometricSoundRunning = false;
    if (biometricBeepTimer) clearInterval(biometricBeepTimer);
    biometricBeepTimer = null;
}

function biometricSuccessSound() {
    stopBiometricSound();
    scannerBeep(750, .08, .04);
    setTimeout(() => scannerBeep(1050, .08, .04), 100);
    setTimeout(() => scannerBeep(1450, .16, .045), 210);
}

function biometricFailureSound() {
    stopBiometricSound();
    scannerBeep(520, .13, .045);
    setTimeout(() => scannerBeep(360, .20, .045), 150);
}




/* Enrollment source preview */
const faceEnrollSource = document.getElementById("faceEnrollSource");
if (faceEnrollSource) {
    faceEnrollSource.addEventListener("change", () => {
        const feed = document.getElementById("enrollCameraFeed");
        if (feed) feed.src = faceEnrollSource.value === "drone" ? "/drone_video_feed" : "/video_feed";
        const msg = document.getElementById("enrollMessage");
        if (msg) msg.innerText = faceEnrollSource.value === "drone"
            ? "DRONE selected — turn Drone AI ON and position one face clearly in the drone view."
            : "MAIN CAMERA selected — position the person's face inside the scanner.";
    });
}

/* ==========================================================
   START FACE BIOMETRIC ENROLLMENT
   ========================================================== */

document.getElementById(
    "startFaceEnrollment"
).addEventListener(
    "click",
    async () => {

        const name =
            document.getElementById(
                "faceName"
            ).value.trim();
        const source = document.getElementById("faceEnrollSource").value;


        if (!name) {

            document.getElementById(
                "enrollMessage"
            ).innerText =
                "Enter the person's name first.";

            return;
        }


        getBiometricAudio();
        startBiometricSound();


        const button =
            document.getElementById(
                "startFaceEnrollment"
            );


        button.disabled = true;

        button.innerText =
            "INITIALIZING BIOMETRIC SCAN";


        try {

            const response =
                await fetch(
                    "/api/enroll/face",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify({
                                name: name,
                                source: source
                            })
                    }
                );


            const result =
                await response.json();


            if (!result.ok) {

                document.getElementById(
                    "enrollMessage"
                ).innerText =
                    result.error
                    ||
                    "Could not start enrollment.";

                button.disabled = false;

                button.innerText =
                    "START BIOMETRIC SCAN";
                biometricFailureSound();
            }

        }

        catch (error) {

            document.getElementById(
                "enrollMessage"
            ).innerText =
                "Enrollment request failed.";

            button.disabled = false;

            button.innerText =
                "START BIOMETRIC SCAN";
            biometricFailureSound();
        }
    }
);


/* ==========================================================
   CANCEL FACE ENROLLMENT
   ========================================================== */

document.getElementById(
    "cancelFaceEnrollment"
).addEventListener(
    "click",
    async () => {

        await fetch(
            "/api/enroll/cancel",
            {
                method: "POST"
            }
        );

        document.getElementById(
            "enrollMessage"
        ).innerText =
            "Cancelling biometric scan...";

        stopBiometricSound();
    }
);


/* ==========================================================
   FACE ENROLLMENT STATUS
   ========================================================== */

async function refreshEnrollment() {

    try {

        const response =
            await fetch(
                "/api/enroll/status"
            );

        const d =
            await response.json();

        if (d.running && d.stage !== biometricLastStage) {
            biometricLastStage = d.stage;
            if (d.stage === "BIOMETRIC CAPTURE") {
                changeBiometricSpeed(210);
                scannerBeep(1350, .07, .04);
            } else if (d.stage === "REGISTERING") {
                changeBiometricSpeed(280);
                scannerBeep(1050, .08, .04);
            } else if (d.stage === "SAMPLE ACCEPTED") {
                changeBiometricSpeed(500);
                scannerBeep(1550, .09, .045);
            } else {
                changeBiometricSpeed(520);
            }
        }

        if (d.success && biometricFinishedState !== "success") {
            biometricFinishedState = "success";
            biometricSuccessSound();
        } else if (!d.running && d.error && biometricFinishedState !== "failure") {
            biometricFinishedState = "failure";
            biometricFailureSound();
        }


        document.getElementById(
            "enrollStage"
        ).innerText =
            d.stage;


        document.getElementById(
            "enrollPercent"
        ).innerText =
            d.progress
            + "%";


        document.getElementById(
            "enrollProgress"
        ).style.width =
            d.progress
            + "%";


        document.getElementById(
            "enrollScannerText"
        ).innerText =
            d.stage;


        document.getElementById(
            "enrollMessage"
        ).innerText =
            d.error
            ||
            d.message;


        for (
            let i = 1;
            i <= 5;
            i++
        ) {

            const dot =
                document.getElementById(
                    "sample" + i
                );


            if (
                i <=
                (
                    d.success
                    ? 5
                    : Math.max(
                        0,
                        d.sample - (
                            d.stage === "SAMPLE ACCEPTED"
                            ? 0
                            : 1
                        )
                    )
                )
            ) {

                dot.classList.add(
                    "complete"
                );

            }

            else {

                dot.classList.remove(
                    "complete"
                );
            }
        }


        const button =
            document.getElementById(
                "startFaceEnrollment"
            );


        if (d.running) {

            button.disabled = true;

            button.innerText =
                "BIOMETRIC SCAN IN PROGRESS";

        }

        else {

            button.disabled = false;

            button.innerText =
                d.success

                ? "ENROLL ANOTHER FACE"

                : "START BIOMETRIC SCAN";
        }


        const scanner =
            document.getElementById(
                "enrollScanner"
            );


        if (d.success) {

            scanner.style.borderColor =
                "#26e990";

            scanner.style.boxShadow =
                "inset 0 0 45px rgba(38,233,144,.12)";

        }

        else if (d.error) {

            scanner.style.borderColor =
                "#ff5062";

            scanner.style.boxShadow =
                "inset 0 0 45px rgba(255,80,98,.08)";

        }

        else {

            scanner.style.borderColor =
                "#087fb5";

            scanner.style.boxShadow =
                "none";
        }


    }

    catch (error) {

        console.log(
            "Enrollment status error:",
            error
        );
    }
}


setInterval(
    refreshEnrollment,
    400
);

refreshEnrollment();


/* ==========================================================
   ADD VEHICLE
   ========================================================== */

document.getElementById(
    "saveVehicle"
).addEventListener(
    "click",
    async () => {

        const vehicle =
            document.getElementById(
                "newVehicleName"
            ).value.trim();

        const plate =
            document.getElementById(
                "newVehiclePlate"
            ).value.trim();
        const source = document.getElementById("vehicleEnrollSource").value;


        const output =
            document.getElementById(
                "vehicleSaveMessage"
            );


        output.innerText =
            "Registering vehicle...";


        try {

            const response =
                await fetch(
                    "/api/add_vehicle",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify({
                                vehicle: vehicle,
                                plate: plate,
                                source: source
                            })
                    }
                );


            const result =
                await response.json();


            if (result.ok) {

                output.innerText =
                    "✓ VEHICLE REGISTERED — "
                    + result.vehicle
                    + " • "
                    + result.plate;

            }

            else {

                output.innerText =
                    result.error;
            }

        }

        catch (error) {

            output.innerText =
                "Unable to register vehicle.";
        }
    }
);


/* ==========================================================
   FACE LIBRARY
   ========================================================== */

document.getElementById(
    "openFaceLibrary"
).addEventListener(
    "click",
    async () => {

        faceLibraryOverlay
            .classList
            .add("open");


        const container =
            document.getElementById(
                "faceLibraryContent"
            );


        container.innerHTML =
            '<div class="waiting">Loading face library...</div>';


        try {

            const response =
                await fetch(
                    "/api/face_library"
                );

            const result =
                await response.json();


            if (
                !result.ok
                ||
                !result.faces.length
            ) {

                container.innerHTML =
                    '<div class="waiting">'
                    +
                    (
                        result.error
                        ||
                        "No enrolled faces found."
                    )
                    +
                    '</div>';

                return;
            }


            container.innerHTML =
                result.faces.map(
                    name => `

                        <div class="library-item">

                            <div class="library-type">
                                ENROLLED IDENTITY
                            </div>

                            <div class="library-name">
                                ${name}
                            </div>

                            <div class="library-sub">
                                FACE RECOGNITION
                            </div>

                        </div>

                    `
                ).join("");

        }

        catch (error) {

            container.innerHTML =
                '<div class="waiting">Unable to read face library.</div>';
        }
    }
);


/* ==========================================================
   KNOWN VEHICLES
   ========================================================== */

document.getElementById(
    "openVehicleLibrary"
).addEventListener(
    "click",
    async () => {

        vehicleLibraryOverlay
            .classList
            .add("open");


        const container =
            document.getElementById(
                "vehicleLibraryContent"
            );


        container.innerHTML =
            '<div class="waiting">Loading known vehicles...</div>';


        try {

            const response =
                await fetch(
                    "/api/known_vehicles"
                );

            const vehicles =
                await response.json();

            const entries =
                Object.entries(
                    vehicles
                );


            if (!entries.length) {

                container.innerHTML =
                    '<div class="waiting">No registered vehicles.</div>';

                return;
            }


            container.innerHTML =
                entries.map(
                    ([plate, name]) => `

                        <div class="library-item">

                            <div class="library-type">
                                AUTHORIZED VEHICLE
                            </div>

                            <div class="library-name">
                                ${name}
                            </div>

                            <div class="library-sub">
                                PLATE • ${plate}
                            </div>

                        </div>

                    `
                ).join("");

        }

        catch (error) {

            container.innerHTML =
                '<div class="waiting">Unable to read known vehicles.</div>';
        }
    }
);



/* DRONE FEED STATUS
   Uses already-cached Drone AI + tracking state.
   No extra HTTP requests are generated here. */
function refreshDroneFeedStatus() {
    const stateEl = document.getElementById("droneFeedState");
    if (stateEl) {
        stateEl.innerText = droneVideoOnline ? "● VIDEO LIVE" : (droneEnabled ? "WAITING FOR VIDEO" : "NO VIDEO");
        stateEl.style.color = droneVideoOnline ? "#2fee91" : "#ffae2b";
    }

    const ts = latestDroneTrackingStatus || {};
    const out = document.getElementById("droneTrackingReadout");
    if (out) {
        if (!ts.enabled) out.innerText = "TRACKING ASSIST • OFF";
        else if (!ts.active) out.innerText = "TRACKING ASSIST • SEARCHING";
        else out.innerText =
            "TRACKING • "
            + (ts.label || "TARGET")
            + " • "
            + (ts.direction || "CENTERED");
    }
}
setInterval(refreshDroneFeedStatus, 1000);
refreshDroneFeedStatus();
</script>


</body>

</html>
"""



PAIRING_PAGE = """
<!doctype html>
<html><head><meta charset="utf-8"><title>AI Security Command Center Setup</title>
<style>
body{margin:0;background:#071019;color:#eaf6ff;font-family:Arial,sans-serif;display:grid;place-items:center;min-height:100vh}
.card{width:min(520px,92vw);background:#0d1a26;border:1px solid #1d3a4d;border-radius:16px;padding:30px}
.brand{color:#66e3ff;letter-spacing:.12em}.muted{color:#93a9b7}input,button{width:100%;box-sizing:border-box;padding:14px;margin-top:12px;border-radius:9px;font-size:16px}
input{background:#071019;color:#fff;border:1px solid #28556c}button{border:0;font-weight:700;cursor:pointer}
.code{text-transform:uppercase;letter-spacing:4px}#msg{min-height:24px;margin-top:14px}
</style></head>
<body><div class="card"><div class="brand">AI SECURITY COMMAND CENTER</div>
<h1>Pair this Windows device</h1>
<p class="muted">In your Customer Portal, choose <b>Pair a Windows device</b>, then enter the one-time code below.</p>
<input id="name" value="Windows Edge" placeholder="Device name">
<input id="code" class="code" maxlength="8" placeholder="PAIRING CODE">
<button id="pair">PAIR DEVICE</button><div id="msg" class="muted"></div></div>
<script>
const btn=document.getElementById("pair"),msg=document.getElementById("msg");
btn.onclick=async()=>{
 const code=document.getElementById("code").value.trim().toUpperCase();
 const device_name=document.getElementById("name").value.trim()||"Windows Edge";
 if(code.length!==8){msg.innerText="Enter the 8-character pairing code.";return}
 btn.disabled=true;msg.innerText="Pairing securely...";
 try{
  const r=await fetch("/api/cloud/pair",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code,device_name})});
  const d=await r.json();
  if(!r.ok||!d.ok)throw new Error(d.error||"Pairing failed");
  msg.innerText="✓ DEVICE PAIRED — starting Command Center...";
  setTimeout(()=>location.href="/",1200);
 }catch(e){msg.innerText=e.message||"Pairing failed";btn.disabled=false}
};
</script></body></html>
"""



CUSTOMER_PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Security Command Center</title>
<style>
:root{--bg:#071019;--panel:#0d1924;--panel2:#101f2c;--line:#1d3445;--text:#eef7fc;--muted:#8fa6b5;--accent:#22b7ff;--good:#35d07f;--warn:#ffbd45;--bad:#ff667a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif}
.shell{display:grid;grid-template-columns:230px 1fr;min-height:100vh}.side{border-right:1px solid var(--line);padding:22px 16px;background:#08131d;position:sticky;top:0;height:100vh}
.brand{font-weight:800;letter-spacing:.08em;font-size:14px;color:#bfeaff;margin:6px 10px 28px}.nav a{display:flex;gap:12px;align-items:center;color:#b7c9d4;text-decoration:none;padding:12px 14px;border-radius:10px;margin:4px 0}.nav a.active,.nav a:hover{background:#102636;color:white}.nav .ico{width:20px;text-align:center}
.main{padding:28px 32px;max-width:1500px;width:100%;margin:auto}.top{display:flex;justify-content:space-between;gap:18px;align-items:center;margin-bottom:24px}.top h1{margin:0;font-size:28px}.sub{color:var(--muted);margin-top:6px}.actions{display:flex;gap:10px}.btn{border:1px solid var(--line);background:#102332;color:white;padding:10px 14px;border-radius:10px;font-weight:700;cursor:pointer}.btn.primary{background:var(--accent);color:#00131d;border-color:transparent}
.health{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}.stat,.card{background:var(--panel);border:1px solid var(--line);border-radius:16px}.stat{padding:16px}.label{color:var(--muted);font-size:13px}.value{font-size:18px;font-weight:800;margin-top:7px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;background:var(--muted)}.dot.good{background:var(--good)}.dot.warn{background:var(--warn)}.dot.bad{background:var(--bad)}
.grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(320px,.8fr);gap:18px}.card{overflow:hidden}.cardhead{display:flex;align-items:center;justify-content:space-between;padding:16px 18px;border-bottom:1px solid var(--line)}.cardhead h2{font-size:17px;margin:0}.live{background:#020609;aspect-ratio:16/9;display:grid;place-items:center;position:relative}.live img{width:100%;height:100%;object-fit:contain}.badge{padding:6px 9px;border-radius:999px;background:#102b20;color:#7ff0ad;font-size:12px;font-weight:800}.overlay{position:absolute;left:14px;bottom:14px;background:#071019cc;padding:8px 10px;border-radius:9px;font-size:12px}
.quick{padding:16px;display:grid;gap:10px}.quickrow{display:flex;justify-content:space-between;align-items:center;background:var(--panel2);padding:13px;border-radius:11px}.small{font-size:12px;color:var(--muted)}.events{margin-top:18px}.eventlist{padding:4px 16px 14px}.event{display:grid;grid-template-columns:52px 1fr auto;gap:12px;align-items:center;padding:12px 0;border-bottom:1px solid #172b39}.thumb{width:52px;height:42px;border-radius:8px;background:#142634;object-fit:cover}.event:last-child{border-bottom:0}
.notice{display:none;margin-bottom:16px;padding:12px 14px;border-radius:11px;background:#17291e;border:1px solid #285c3b;color:#baf4cf}.notice.show{display:block}
@media(max-width:900px){.shell{grid-template-columns:1fr}.side{display:none}.main{padding:18px}.health{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}}@media(max-width:520px){.health{grid-template-columns:1fr}.actions{display:none}}
</style>
</head>
<body><div class="shell">
<aside class="side"><div class="brand">AI SECURITY<br>COMMAND CENTER</div><nav class="nav">
<a class="active" href="/"><span class="ico">⌂</span>Dashboard</a>
<a href="/"><span class="ico">▣</span>Live View</a>
<a href="/legacy#history"><span class="ico">◷</span>Events</a>
<a href="/legacy#face-library"><span class="ico">◎</span>People</a>
<a href="/legacy#vehicle-library"><span class="ico">▱</span>Vehicles</a>
<a href="/legacy"><span class="ico">⌁</span>Drones</a>
<a href="/setup/discover"><span class="ico">＋</span>Devices</a>
<a href="/settings"><span class="ico">⚙</span>Settings</a>
</nav></aside>
<main class="main">
<div class="top"><div><h1>Good to see you</h1><div class="sub">Your security system at a glance.</div></div>
<div class="actions"><button class="btn" onclick="location.href='/setup/discover'">Add device</button><button class="btn primary" onclick="runRecovery()">Check system</button></div></div>
<div id="notice" class="notice"></div>
<section class="health">
<div class="stat"><div class="label">Front Camera</div><div class="value"><span id="camDot" class="dot"></span><span id="camText">Checking…</span></div></div>
<div class="stat"><div class="label">AI Detection</div><div class="value"><span id="aiDot" class="dot"></span><span id="aiText">Checking…</span></div></div>
<div class="stat"><div class="label">Drone</div><div class="value"><span id="droneDot" class="dot"></span><span id="droneText">Checking…</span></div></div>
<div class="stat"><div class="label">Edge Agent</div><div class="value"><span id="edgeDot" class="dot"></span><span id="edgeText">Connected</span></div></div>
</section>
<section class="grid">
<div class="card"><div class="cardhead"><h2>Front Camera</h2><span id="liveBadge" class="badge">LIVE</span></div>
<div class="live"><img src="/video_feed" alt="Front camera live view"><div class="overlay" id="recoveryLabel">Automatic recovery active</div></div></div>
<div class="card"><div class="cardhead"><h2>System</h2><span class="small">Automatic</span></div><div class="quick">
<div class="quickrow"><div><b>Camera recovery</b><div class="small" id="recoveryDetail">Monitoring network changes</div></div><span id="recoveryState">●</span></div>
<div class="quickrow"><div><b>People recognition</b><div class="small">Known & unknown people</div></div><span id="faceState">—</span></div>
<div class="quickrow"><div><b>License plate recognition</b><div class="small">Vehicle events</div></div><span id="lprState">—</span></div>
<div class="quickrow"><div><b>Cloud connection</b><div class="small" id="planText">Checking subscription</div></div><span id="cloudState">●</span></div>
</div></div>
</section>
<section class="card events"><div class="cardhead"><h2>Recent security events</h2><button class="btn" onclick="location.href='/legacy#history'">View all</button></div>
<div class="eventlist">
{% if events %}
{% for e in events[:5] %}
<div class="event">{% if e.image_file %}<img class="thumb" src="/events/{{e.image_file}}">{% else %}<div class="thumb"></div>{% endif %}
<div><b>{{ e.get('Type', e.get('Event','Security event')) }}</b><div class="small">{{ e.get('Name', e.get('Details','')) }}</div></div><div class="small">{{ e.get('Time', e.get('Timestamp','')) }}</div></div>
{% endfor %}
{% else %}<div class="small" style="padding:22px 0">No recent security events.</div>{% endif %}
</div></section>
</main></div>
<script>
function setState(id,text,state){document.getElementById(id+'Text').textContent=text;const d=document.getElementById(id+'Dot');d.className='dot '+state}
async function refresh(){
 try{
  const [c,a,d,r,cl]=await Promise.all([
   fetch('/api/camera/status').then(x=>x.json()),fetch('/api/object_ai/status').then(x=>x.json()),
   fetch('/api/drone/status').then(x=>x.json()),fetch('/api/recovery/status').then(x=>x.json()),
   fetch('/api/cloud/status').then(x=>x.json())
  ]);
  setState('cam',c.connected?'Online':(c.enabled?'Reconnecting…':'Off'),c.connected?'good':(c.enabled?'warn':'bad'));
  setState('ai',a.enabled?'Active':'Off',a.enabled?'good':'warn');
  setState('drone',d.video?'Online':(d.enabled?'Waiting…':'Offline'),d.video?'good':(d.enabled?'warn':''));
  document.getElementById('edgeDot').className='dot good';
  const rc=(r.cameras||{}).tony||{}; const rs=rc.status||'monitoring';
  document.getElementById('recoveryDetail').textContent=rs==='stream_unavailable'?'Camera found — enable RTSP or check camera account':rs==='reconnected'?'IP changed — reconnected automatically':rs==='network_changed'?'Network changed — finding your camera…':rs==='recovering'?'Finding your camera…':rs==='checking'?'Checking camera…':rs==='offline'?'Camera offline — recovery will retry':'Monitoring network changes';
  document.getElementById('recoveryLabel').textContent=rs==='stream_unavailable'?'Camera found — video unavailable':rs==='reconnected'?'Reconnected automatically':rs==='network_changed'?'Network changed — reconnecting…':rs==='recovering'?'Reconnecting automatically…':rs==='checking'?'Checking connection…':'Automatic recovery active';
  document.getElementById('planText').textContent=cl.plan_code?('Plan: '+String(cl.plan_code).toUpperCase()):(cl.connected?'Cloud connected':'Local mode');
  document.getElementById('cloudState').textContent=cl.connected?'●':'○';
 }catch(e){setState('cam','Needs attention','bad')}
}
async function runRecovery(){
 const n=document.getElementById('notice');n.classList.add('show');n.textContent='Checking your system…';
 try{const x=await fetch('/api/recovery/run',{method:'POST'});const d=await x.json();
 n.textContent=d.state==='already_running'?'Automatic recovery is already checking the camera.':d.ok?'System check complete — camera is online.':'Check complete — automatic recovery will keep trying.';
 }catch(e){n.textContent='Could not complete the check.'} setTimeout(()=>{n.classList.remove('show')},5000);refresh()
}
refresh();setInterval(refresh,10000);
</script></body></html>
"""



CUSTOMER_SETTINGS_FILE = Path(BASE_FOLDER) / "customer_settings.json"
DEFAULT_CUSTOMER_SETTINGS={"camera_ai":True,"face_ai":True,"lpr":True,"drone_runtime":False,"drone_ai":False,"drone_tracking":False,"gps_dispatch":False,"camera_latitude":None,"camera_longitude":None,"gps_safety_radius_m":120,"require_dispatch_confirmation":True}
def _load_customer_settings():
    try:return {**DEFAULT_CUSTOMER_SETTINGS,**json.loads(CUSTOMER_SETTINGS_FILE.read_text(encoding="utf-8"))}
    except Exception:return dict(DEFAULT_CUSTOMER_SETTINGS)
def _save_customer_settings(data):
    safe={**DEFAULT_CUSTOMER_SETTINGS}
    for k in safe:
        if k in data:safe[k]=data[k]
    CUSTOMER_SETTINGS_FILE.parent.mkdir(parents=True,exist_ok=True)
    tmp=CUSTOMER_SETTINGS_FILE.with_suffix(".tmp");tmp.write_text(json.dumps(safe,indent=2),encoding="utf-8");os.replace(tmp,CUSTOMER_SETTINGS_FILE);return safe

SETTINGS_PAGE="""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Settings</title><style>
body{margin:0;background:#071019;color:#eef7fc;font-family:Segoe UI,Arial}.w{max-width:900px;margin:auto;padding:28px}.c{background:#0d1924;border:1px solid #1d3445;border-radius:16px;padding:20px;margin:14px 0}.r{display:flex;justify-content:space-between;gap:20px;align-items:center;padding:14px 0;border-bottom:1px solid #183040}.r:last-child{border:0}.m{color:#8fa6b5;font-size:13px}.t{width:48px;height:26px}.b{background:#22b7ff;border:0;border-radius:10px;padding:11px 16px;font-weight:800;cursor:pointer}.a{color:#9edfff;text-decoration:none}input[type=number]{background:#071019;color:white;border:1px solid #28506a;border-radius:8px;padding:10px;width:160px}.s{padding:10px 12px;border-radius:9px;background:#102332;margin-top:10px}</style></head><body><div class=w><a class=a href="/">← Dashboard</a><h1>Settings</h1><p class=m>Simple controls for AI, cameras and drones.</p>
<div class=c><h2>AI & devices</h2>
<div class=r><div><b>Camera AI</b><div class=m>Person and vehicle detection</div></div><input class=t type=checkbox data-key=camera_ai></div>
<div class=r><div><b>Face recognition</b></div><input class=t type=checkbox data-key=face_ai></div><div class=r><div><b>License plate recognition</b></div><input class=t type=checkbox data-key=lpr></div>
<div class=r><div><b>Drone runtime</b><div class=m>Live receiver only when needed</div></div><input class=t type=checkbox data-key=drone_runtime></div><div class=r><div><b>Drone AI</b></div><input class=t type=checkbox data-key=drone_ai></div><div class=r><div><b>Drone tracking assist</b></div><input class=t type=checkbox data-key=drone_tracking></div></div>
<div class=c><h2>GPS Dispatch</h2><p class=m>Store the camera location locally. Aircraft movement remains safety-gated behind a compatible flight-control bridge.</p><div class=r><b>Enable GPS Dispatch</b><input class=t type=checkbox data-key=gps_dispatch></div><div class=r><b>Camera latitude</b><input id=lat type=number step=any></div><div class=r><b>Camera longitude</b><input id=lon type=number step=any></div><div class=r><b>Safety radius (m)</b><input id=radius type=number min=10 max=1000></div><div class=r><b>Require dispatch confirmation</b><input class=t type=checkbox data-key=require_dispatch_confirmation></div><button class=b onclick=save()>Save settings</button><div id=msg class=s>Loading…</div></div>
<div class=c><h2>Add device</h2><p class=m>Scan the current local network for nearby camera and stream candidates.</p><button class=b onclick="location.href='/setup/discover'">Add camera or drone</button></div></div>
<script>let cfg={};async function load(){cfg=await fetch('/api/customer/settings').then(r=>r.json());document.querySelectorAll('[data-key]').forEach(x=>x.checked=!!cfg[x.dataset.key]);lat.value=cfg.camera_latitude??'';lon.value=cfg.camera_longitude??'';radius.value=cfg.gps_safety_radius_m??120;msg.textContent='Settings loaded'}async function save(){document.querySelectorAll('[data-key]').forEach(x=>cfg[x.dataset.key]=x.checked);cfg.camera_latitude=lat.value===''?null:Number(lat.value);cfg.camera_longitude=lon.value===''?null:Number(lon.value);cfg.gps_safety_radius_m=Number(radius.value||120);let d=await fetch('/api/customer/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)}).then(r=>r.json());msg.textContent=d.ok?'Saved. Controls applied.':(d.message||'Could not save.')}load()</script></body></html>"""
@app.route("/settings")
def customer_settings_page():return Response(SETTINGS_PAGE,mimetype="text/html")
@app.route("/api/customer/settings",methods=["GET","POST"])
def customer_settings_api():
    global camera_ai_enabled,drone_enabled_runtime,drone_ai_enabled
    if request.method=="GET":return jsonify(_load_customer_settings())
    cfg=_save_customer_settings(request.get_json(silent=True) or {})
    try:camera_ai_enabled=bool(cfg["camera_ai"])
    except Exception:pass
    try:drone_enabled_runtime=bool(cfg["drone_runtime"])
    except Exception:pass
    try:drone_ai_enabled=bool(cfg["drone_ai"])
    except Exception:pass
    return jsonify({"ok":True,"settings":cfg})
@app.route("/api/gps-dispatch/status")
def gps_dispatch_status():
    cfg=_load_customer_settings();bridge=bool(os.environ.get("AI_SECURITY_FLIGHT_BRIDGE_URL"));loc=all(isinstance(cfg.get(k),(int,float)) for k in ("camera_latitude","camera_longitude"))
    return jsonify({"ok":True,"enabled":bool(cfg["gps_dispatch"]),"camera_location_configured":loc,"drone_runtime":bool(drone_enabled_runtime),"flight_control_bridge":bridge,"ready":bool(cfg["gps_dispatch"] and loc and drone_enabled_runtime and bridge),"confirmation_required":bool(cfg["require_dispatch_confirmation"])})
@app.route("/api/gps-dispatch/request",methods=["POST"])
def gps_dispatch_request():
    cfg=_load_customer_settings();bridge=os.environ.get("AI_SECURITY_FLIGHT_BRIDGE_URL")
    if not cfg["gps_dispatch"]:return jsonify({"ok":False,"state":"disabled","message":"GPS Dispatch is disabled."}),409
    if not all(isinstance(cfg.get(k),(int,float)) for k in ("camera_latitude","camera_longitude")):return jsonify({"ok":False,"state":"location_missing","message":"Configure the camera GPS location first."}),409
    if not drone_enabled_runtime:return jsonify({"ok":False,"state":"drone_offline","message":"Enable and connect the drone first."}),409
    if not bridge:return jsonify({"ok":False,"state":"bridge_required","message":"Compatible flight-control bridge required. No aircraft command sent."}),409
    return jsonify({"ok":False,"state":"bridge_not_integrated","message":"Bridge configured; flight command integration is not enabled in this release."}),501

# ============================================================
# WEB ROUTES
# ============================================================

def _dashboard_context():
    events = get_events(8)
    history_events = get_events(None)
    def decorate_event_images(items):
        for event in items:
            snapshot = event.get("Snapshot", "")
            if snapshot:
                snapshot = snapshot.replace("\\", "/")
                event["image_file"] = os.path.basename(snapshot)
            else:
                event["image_file"] = ""
    decorate_event_images(events)
    decorate_event_images(history_events)
    return events, history_events

@app.route("/")
def dashboard():
    edge_cfg = load_edge_agent_config()
    if not str(edge_cfg.get("device_token") or "").strip():
        return Response(PAIRING_PAGE, mimetype="text/html")
    events, history_events = _dashboard_context()
    return render_template_string(CUSTOMER_PAGE, events=events, history_events=history_events)

@app.route("/legacy")
def legacy_dashboard():
    edge_cfg = load_edge_agent_config()
    if not str(edge_cfg.get("device_token") or "").strip():
        return Response(PAIRING_PAGE, mimetype="text/html")
    events, history_events = _dashboard_context()
    return render_template_string(PAGE, events=events, history_events=history_events)


@app.route(
    "/video_feed"
)
def video_feed():
    return Response(
        generate_frames(),
        mimetype=(
            "multipart/"
            "x-mixed-replace;"
            " boundary=frame"
        ),
    )


@app.route(
    "/drone_video_feed"
)
def drone_video_feed():
    if not cloud_feature_enabled("drone_live"):
        return Response("Drone Live is disabled by the SaaS subscription.", status=403)
    return Response(
        generate_drone_frames(),
        mimetype=(
            "multipart/"
            "x-mixed-replace;"
            " boundary=frame"
        ),
    )


@app.route(
    "/events/<path:filename>"
)
def event_image(filename):
    return send_from_directory(
        EVENT_FOLDER,
        filename
    )


# ============================================================
# START
# ============================================================


# ---------------- V10.5 LOCAL CAMERA AUTO-RECOVERY ----------------
# This subsystem is intentionally local-only: camera credentials never leave this PC.
RECOVERY_STATE_PATH = os.path.join(BASE_FOLDER, "camera_recovery_v11.json")
FRIGATE_CONFIG_CANDIDATES = [
    r"C:\frigate\config\config.yaml",
    r"C:\frigate\config\config.yml",
]
RECOVERY_INTERVAL_SECONDS = 10
_recovery_stop = threading.Event()
_recovery_lock = threading.Lock()

def _active_windows_ipv4():
    """Prefer an adapter with a real default gateway; ignore WSL/Docker/APIPA/loopback."""
    ps = r"""$x=Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway -and $_.IPv4Address};
$x | ForEach-Object {[PSCustomObject]@{Alias=$_.InterfaceAlias;IP=$_.IPv4Address.IPAddress;Gateway=$_.IPv4DefaultGateway.NextHop}} | ConvertTo-Json -Compress"""
    try:
        p=run_background_command(["powershell","-NoProfile","-Command",ps],capture_output=True,text=True,timeout=5)
        raw=(p.stdout or "").strip()
        if raw:
            items=json.loads(raw)
            if isinstance(items,dict): items=[items]
            for x in items:
                ip=x.get("IP","")
                alias=(x.get("Alias") or "").lower()
                if ipaddress.ip_address(ip).is_private and not ip.startswith("169.254.") and not any(v in alias for v in ("wsl","docker","vethernet")):
                    return x
    except Exception:
        pass
    return {"Alias":"","IP":_lan_ip(),"Gateway":""}

def _network_signature():
    """Stable identity for the active LAN. Changes when Windows moves to another Wi-Fi/router."""
    a=_active_windows_ipv4()
    ip=str(a.get("IP") or "")
    gw=str(a.get("Gateway") or "")
    alias=str(a.get("Alias") or "")
    try:
        net=str(ipaddress.ip_network(ip+"/24",strict=False).network_address)+"/24"
    except Exception:
        net=""
    return {"alias":alias,"ip":ip,"gateway":gw,"network":net}

def _ip_on_active_lan(ip):
    a=_active_windows_ipv4()
    local=str(a.get("IP") or "")
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(local+"/24",strict=False)
    except Exception:
        return False

def _neighbor_mac(ip):
    """Read the MAC Windows currently associates with an IP, without touching RTSP."""
    try:
        p=run_background_command(["arp","-a"],capture_output=True,text=True,timeout=3)
        for line in (p.stdout or "").splitlines():
            m=re.search(r"^\s*"+re.escape(str(ip))+r"\s+([0-9a-fA-F-]{17})\s+",line)
            if m:return m.group(1).lower()
    except Exception:
        pass
    return None

def _frigate_config_path():
    for p in FRIGATE_CONFIG_CANDIDATES:
        if os.path.exists(p): return p
    return None

def _load_recovery_state():
    try:
        with open(RECOVERY_STATE_PATH,"r",encoding="utf-8") as f:return json.load(f)
    except Exception:return {"cameras":{}}

def _save_recovery_state(s):
    os.makedirs(os.path.dirname(RECOVERY_STATE_PATH),exist_ok=True)
    tmp=RECOVERY_STATE_PATH+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(s,f,indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp,RECOVERY_STATE_PATH)

def _camera_source_parts(url):
    # Do not log returned user/password.
    from urllib.parse import urlsplit
    u=urlsplit(url)
    return u.username or "",u.password or "",u.hostname or "",u.port or 554,u.path or "/stream1"

def _rtsp_auth_probe(url, timeout=4):
    """Use OpenCV only as a last-mile stream check; URL is never logged."""
    result={"ok":False}
    def run():
        cap=None
        try:
            cap=cv2.VideoCapture(url,cv2.CAP_FFMPEG)
            ok,frame=cap.read()
            result["ok"]=bool(ok and frame is not None)
        except Exception:pass
        finally:
            try:
                if cap:cap.release()
            except Exception:pass
    t=threading.Thread(target=run,daemon=True);t.start();t.join(timeout)
    return bool(result["ok"])

def _arp_neighbors_on_active_lan():
    a=_active_windows_ipv4(); ip=a.get("IP","")
    if not ip:return a,{}
    try:net=ipaddress.ip_network(ip+"/24",strict=False)
    except Exception:return a,{}
    # Brief parallel ping sweep populates ARP, but never probes application ports on all 254 hosts.
    hosts=[str(h) for h in net.hosts() if str(h)!=ip]
    def ping(h):
        try:run_background_command(["ping","-n","1","-w","60",h],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=.5)
        except Exception:pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=48) as ex:
        list(ex.map(ping,hosts))
    found={}
    try:
        p=run_background_command(["arp","-a"],capture_output=True,text=True,timeout=3)
        for line in (p.stdout or "").splitlines():
            m=re.search(r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})\s+",line)
            if m and ipaddress.ip_address(m.group(1)) in net:
                found[m.group(1)]=m.group(2).lower()
    except Exception:pass
    return a,found

def _backup_file(path):
    stamp=time.strftime("%Y%m%d-%H%M%S")
    dst=path+".backup-"+stamp
    shutil.copy2(path,dst)
    return dst

def _docker_restart_frigate():
    try:
        p=run_background_command(["docker","restart","frigate"],capture_output=True,text=True,timeout=35)
        if p.returncode==0:return True
    except Exception:pass
    # Frigate's documented MQTT restart command; the container must auto-restart.
    try:
        import paho.mqtt.publish as publish
        publish.single("frigate/restart",payload="",qos=1,retain=False,hostname=MQTT_HOST,port=MQTT_PORT)
        time.sleep(3)
        return True
    except Exception:return False

def _wait_for_frigate(timeout=45):
    """Wait for Frigate HTTP to return after a controlled restart."""
    deadline=time.time()+timeout
    while time.time()<deadline:
        try:
            import urllib.request
            ctx=ssl._create_unverified_context()
            with urllib.request.urlopen("https://127.0.0.1:8971/api/version",timeout=2,context=ctx) as r:
                if 200 <= r.status < 500:
                    return True
        except urllib.error.HTTPError as e:
            if e.code in (401,403):return True
        except Exception:
            pass
        time.sleep(2)
    return False

def _safe_update_camera_host(camera_name,new_ip,new_stream=None):
    """Patch only the go2rtc source host/path. Preserve every unrelated Frigate setting."""
    path=_frigate_config_path()
    if not path:return False,"Frigate config not found"
    with open(path,"r",encoding="utf-8") as f: cfg=yaml.safe_load(f) or {}
    streams=((cfg.get("go2rtc") or {}).get("streams") or {})
    source=streams.get(camera_name)
    if isinstance(source,list) and source: old=source[0]
    elif isinstance(source,str): old=source
    else:return False,"Camera source not found"
    user,pw,host,port,stream=_camera_source_parts(old)
    if not user or pw is None:return False,"Camera credentials are not configured"
    stream=new_stream or stream
    from urllib.parse import quote
    # Quote credentials for URI safety without changing what is stored in the camera.
    new=f"rtsp://{quote(user,safe='')}:{quote(pw,safe='')}@{new_ip}:{port}{stream}"
    candidate=copy.deepcopy(cfg)
    if isinstance(source,list):candidate["go2rtc"]["streams"][camera_name][0]=new
    else:candidate["go2rtc"]["streams"][camera_name]=new
    # Validate serialization before touching live file.
    rendered=yaml.safe_dump(candidate,sort_keys=False,allow_unicode=True)
    yaml.safe_load(rendered)
    backup=_backup_file(path)
    tmp=path+".v105.tmp"
    try:
        with open(tmp,"w",encoding="utf-8") as f:f.write(rendered)
        os.replace(tmp,path)
        if not _docker_restart_frigate() or not _wait_for_frigate():
            shutil.copy2(backup,path)
            _docker_restart_frigate()
            _wait_for_frigate(30)
            return False,"Frigate did not recover after update; previous configuration restored"
        return True,backup
    except Exception as e:
        try:shutil.copy2(backup,path);_docker_restart_frigate()
        except Exception:pass
        return False,"Update failed; previous configuration restored"

def _discover_same_camera(camera_name, expected_mac, old_url):
    user,pw,old_ip,port,old_stream=_camera_source_parts(old_url)
    if not user or pw is None:return None
    adapter,neighbors=_arp_neighbors_on_active_lan()
    candidates=[]
    # V10.9: camera identity follows the physical MAC across Wi-Fi/router changes.
    if expected_mac:
        candidates=[ip for ip,mac in neighbors.items() if mac.lower()==expected_mac.lower()]
        # Do not immediately fall back to a random RTSP device when we know the camera identity.
        # A second ARP population pass handles Windows changing adapters/networks.
        if not candidates:
            adapter,neighbors=_arp_neighbors_on_active_lan()
            candidates=[ip for ip,mac in neighbors.items() if mac.lower()==expected_mac.lower()]
    # Enroll identity explicitly instead of sending saved credentials to unknown devices.
    if not expected_mac:return None
    # Prefer the previously working Tapo stream, then try stream1/stream2.
    paths=[]
    for p in (old_stream,"/stream2","/stream1"):
        if p not in paths:paths.append(p)
    from urllib.parse import quote
    for ip in candidates:
        if not _port(ip,port,.5):
            return {"ip":ip,"mac":neighbors.get(ip),"stream":old_stream,"adapter":adapter,"stream_ready":False}
        for pth in paths:
            url=f"rtsp://{quote(user,safe='')}:{quote(pw,safe='')}@{ip}:{port}{pth}"
            if _rtsp_auth_probe(url,4):
                return {"ip":ip,"mac":neighbors.get(ip),"stream":pth,"adapter":adapter,"stream_ready":True}
        return {"ip":ip,"mac":neighbors.get(ip),"stream":old_stream,"adapter":adapter,"stream_ready":False}
    return None

def _recover_camera(camera_name):
    state=_load_recovery_state()
    rec=state.setdefault("cameras",{}).setdefault(camera_name,{})
    rec.update({"status":"checking","last_check":int(time.time())})
    _save_recovery_state(state)
    path=_frigate_config_path()
    if not path:return {"ok":False,"state":"config_missing","message":"Frigate config.yaml/config.yml was not found"}
    try:
        cfg=yaml.safe_load(open(path,encoding="utf-8")) or {}
        source=((cfg.get("go2rtc") or {}).get("streams") or {}).get(camera_name)
        url=source[0] if isinstance(source,list) and source else source
        if not url:return {"ok":False,"state":"source_missing"}
        user,pw,ip,port,stream=_camera_source_parts(url)
        state=_load_recovery_state(); rec=state.setdefault("cameras",{}).setdefault(camera_name,rec)
        # V10.9: detect LAN changes and never authenticate against a stale/reused IP.
        current_net=_network_signature()
        previous_net=rec.get("network") or {}
        network_changed=bool(previous_net and (
            previous_net.get("gateway") != current_net.get("gateway") or
            previous_net.get("network") != current_net.get("network")
        ))
        expected_mac=(rec.get("mac") or "").lower()
        current_mac=None
        if _ip_on_active_lan(ip):
            # Populate ARP first; this is safe and does not open RTSP.
            try: run_background_command(["ping","-n","1","-w","120",ip],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=1)
            except Exception: pass
            current_mac=(_neighbor_mac(ip) or "").lower()

        identity_ok=(not expected_mac) or (current_mac and current_mac==expected_mac)
        if (not network_changed) and _ip_on_active_lan(ip) and identity_ok and _port(ip,port,.15) and _rtsp_auth_probe(url,3):
            rec.update({"last_ip":ip,"stream":stream,"status":"online","last_ok":int(time.time()),"network":current_net})
            if current_mac:rec["mac"]=current_mac
            _save_recovery_state(state)
            return {"ok":True,"state":"online","ip":ip}

        # Same camera, new Wi-Fi/router/DHCP address: discover by learned MAC and working credentials.
        rec.update({"status":"network_changed" if network_changed else "recovering","network":current_net})
        _save_recovery_state(state)
        found=_discover_same_camera(camera_name,expected_mac or None,url)
        if not found:
            rec.update({"status":"offline","last_check":int(time.time())});_save_recovery_state(state)
            return {"ok":False,"state":"offline"}
        if not found.get("stream_ready",True):
            rec.update({"last_ip":found["ip"],"mac":found["mac"],"status":"stream_unavailable","last_check":int(time.time())})
            _save_recovery_state(state)
            return {"ok":False,"state":"stream_unavailable","ip":found["ip"],"message":"Camera identified; RTSP video is unavailable. Enable RTSP and check the camera account."}
        if found["ip"]==ip and found["stream"]==stream:
            rec.update({"last_ip":ip,"mac":found.get("mac") or rec.get("mac"),"stream":stream,
                        "status":"online","last_ok":int(time.time()),"network":_network_signature()})
            _save_recovery_state(state)
            return {"ok":True,"state":"online","ip":ip}
        ok,msg=_safe_update_camera_host(camera_name,found["ip"],found["stream"])
        if ok:
            rec.update({"last_ip":found["ip"],"mac":found.get("mac") or rec.get("mac"),
                        "stream":found["stream"],"status":"reconnected","last_ok":int(time.time()),
                        "network":_network_signature()})
            _save_recovery_state(state)
            return {"ok":True,"state":"reconnected","ip":found["ip"],"stream":found["stream"]}
        return {"ok":False,"state":"rollback","message":msg}
    except Exception as e:
        safe_type=type(e).__name__
        safe_msg=str(e)
        safe_msg=re.sub(r"rtsp://[^\\s]+","rtsp://[REDACTED]",safe_msg,flags=re.I)
        safe_msg=re.sub(r"(?i)(password|passwd|token|secret)\\s*[=:]\\s*[^\\s,;]+",r"\\1=[REDACTED]",safe_msg)
        print(f"[V10.5.2 recovery] {safe_type}: {safe_msg}")
        return {"ok":False,"state":"error","error_type":safe_type,"message":safe_msg[:240]}

def _recovery_loop():
    # Delay startup so Flask/Frigate can settle.
    _recovery_stop.wait(20)
    while not _recovery_stop.is_set():
        try:
            if _recovery_lock.acquire(blocking=False):
                try:_recover_camera("tony")
                finally:_recovery_lock.release()
        except Exception:pass
        _recovery_stop.wait(RECOVERY_INTERVAL_SECONDS)

@app.route("/api/recovery/status")
def recovery_status():
    # Never return RTSP URLs or credentials.
    s=_load_recovery_state()
    return jsonify({"ok":True,"cameras":s.get("cameras",{}),
                    "adapter":_active_windows_ipv4()})


@app.route("/api/recovery/test-discovery",methods=["POST"])
def recovery_test_discovery():
    """Exercise identity/discovery against the live camera without editing Frigate."""
    path=_frigate_config_path()
    if not path:return jsonify({"ok":False,"state":"config_missing"}),404
    try:
        cfg=yaml.safe_load(open(path,encoding="utf-8")) or {}
        source=((cfg.get("go2rtc") or {}).get("streams") or {}).get("tony")
        url=source[0] if isinstance(source,list) and source else source
        if not url:return jsonify({"ok":False,"state":"source_missing"}),404
        st=_load_recovery_state(); rec=(st.get("cameras") or {}).get("tony") or {}
        found=_discover_same_camera("tony",rec.get("mac"),url)
        if not found:return jsonify({"ok":False,"state":"not_found"}),404
        return jsonify({"ok":True,"state":"identified","ip":found["ip"],"mac":found.get("mac"),"stream":found["stream"],
                        "adapter":found.get("adapter")})
    except Exception as e:
        return jsonify({"ok":False,"state":"error","error_type":type(e).__name__,"message":str(e)[:160]}),500


@app.route("/api/recovery/simulate-ip-change",methods=["POST"])
def recovery_simulate_ip_change():
    """Dry-run the recovery pipeline. Never writes config and never restarts Frigate."""
    path=_frigate_config_path()
    if not path:
        return jsonify({"ok":False,"state":"config_missing"}),404
    try:
        with open(path,"r",encoding="utf-8") as f:
            cfg=yaml.safe_load(f) or {}
        source=((cfg.get("go2rtc") or {}).get("streams") or {}).get("tony")
        old=source[0] if isinstance(source,list) and source else source
        if not old:
            return jsonify({"ok":False,"state":"source_missing"}),404
        user,pw,old_ip,port,old_stream=_camera_source_parts(old)
        st=_load_recovery_state()
        rec=(st.get("cameras") or {}).get("tony") or {}
        found=_discover_same_camera("tony",rec.get("mac"),old)
        if not found:
            return jsonify({"ok":False,"state":"camera_not_identified"}),404
        from urllib.parse import quote
        simulated_ip="192.0.2.10"  # RFC 5737 documentation-only address; never contacted.
        candidate=copy.deepcopy(cfg)
        fake=f"rtsp://{quote(user,safe='')}:{quote(pw,safe='')}@{simulated_ip}:{port}{found['stream']}"
        if isinstance(source,list):
            candidate["go2rtc"]["streams"]["tony"][0]=fake
        else:
            candidate["go2rtc"]["streams"]["tony"]=fake
        rendered=yaml.safe_dump(candidate,sort_keys=False,allow_unicode=True)
        yaml.safe_load(rendered)
        # Verify rollback source remains intact in memory. No disk write occurs.
        assert old != fake
        return jsonify({
            "ok":True,
            "state":"simulation_passed",
            "camera_identified":True,
            "current_ip":found["ip"],
            "mac":found.get("mac"),
            "stream":found["stream"],
            "candidate_yaml_valid":True,
            "backup_plan_ready":True,
            "rollback_plan_ready":True,
            "config_written":False,
            "frigate_restarted":False
        })
    except Exception as e:
        msg=re.sub(r"rtsp://[^\\s]+","rtsp://[REDACTED]",str(e),flags=re.I)
        return jsonify({"ok":False,"state":"simulation_error","error_type":type(e).__name__,"message":msg[:180]}),500

@app.route("/api/recovery/run",methods=["POST"])
def recovery_run():
    if not _recovery_lock.acquire(blocking=False):
        return jsonify({"ok":True,"state":"already_running","message":"Automatic recovery is already checking the camera."}),200
    try:
        return jsonify(_recover_camera("tony")),200
    finally:
        _recovery_lock.release()

def _start_v105_recovery():
    t=threading.Thread(target=_recovery_loop,name="camera-auto-recovery",daemon=True)
    t.start()
    return t
# ---------------- END V10.5 LOCAL CAMERA AUTO-RECOVERY ----------------

if __name__ == "__main__":
    _start_v105_recovery()
    print()
    print(
        "======================================"
    )
    print(
        "       AI SECURITY COMMAND CENTER"
    )
    print(
        "======================================"
    )
    print()
    print(
        "Dashboard:"
        f" http://localhost:{PORT}"
    )
    print("V11.0.2 CUSTOMER PLATFORM")
    print()

    app.run(
        host="127.0.0.1",
        port=PORT,
        debug=False,
        threaded=True,
    )
