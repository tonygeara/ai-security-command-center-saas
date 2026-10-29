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
import math
import datetime
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
    redirect,
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
UNKNOWN_FACE_WAIT_SECONDS = 30    # first look at a person's face-recognition result
UNKNOWN_FACE_MIN_ATTEMPTS = 6     # failed face attempts before an in-view person counts as unknown
UNKNOWN_FACE_MAX_SECONDS = 300    # decide by then even if the person is still in view

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
# The config file the Frigate container actually reads (mounted by the launcher's runtime).
LIVE_FRIGATE_CONFIG = os.path.join(
    os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER), "frigate", "config", "config.yaml"
)

def load_local_settings():
    try:
        with open(LOCAL_SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_local_settings(updates):
    settings = load_local_settings()
    settings.update(updates)
    tmp = LOCAL_SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, LOCAL_SETTINGS_FILE)
    return settings

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
APP_VERSION = "V11.1.0"

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
# Frigate's drone detect resolution (4:3, matching the DJI 1440x1080 stream); detection
# boxes arrive in this coordinate space.
DRONE_FRAME_WIDTH = 960
DRONE_FRAME_HEIGHT = 720

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
assistant_state = {"muted_until": 0}  # Telegram assistant: /mute pauses detection alerts


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


def queue_telegram_alert(kind, text, key, snapshot_bytes=None, buttons=None):
    config = load_telegram_config()
    if not telegram_ready(config):
        return False
    if time.time() < float(assistant_state.get("muted_until") or 0) and kind in ("unknown_face", "unknown_vehicle", "known_face", "known_vehicle"):
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
        "buttons": buttons,
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
            extra = {}
            if item.get("buttons"):
                extra["reply_markup"] = json.dumps({"inline_keyboard": item["buttons"]})

            if snapshot:
                response = requests.post(
                    base + "/sendPhoto",
                    data={"chat_id": chat_id, "caption": text[:1000], **extra},
                    files={"photo": ("security_event.jpg", snapshot, "image/jpeg")},
                    timeout=15,
                )
            else:
                response = requests.post(
                    base + "/sendMessage",
                    data={"chat_id": chat_id, "text": text[:4000], **extra},
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


def set_face_overlay(known, label, box=None, object_id="", preserve_identity=False):
    global face_overlay
    key = _overlay_key("face", object_id, label)
    with overlay_lock:
        if box is None:
            box = _tracked_box(tracked_person_boxes, object_id)
        if box is None and time.time() < recent_person_box_until:
            box = recent_person_box

        # Generic tracker updates only move the box; they must not reset a
        # recognized (or flagged unknown) face back to "PERSON".
        existing = face_overlays.get(key)
        if preserve_identity and existing and existing.get("label") not in (None, "", "PERSON"):
            known, label = existing.get("known"), existing.get("label")

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


def set_plate_overlay(known, label, plate, box=None, object_id="", preserve_identity=False):
    global plate_overlay
    key = _overlay_key("vehicle", object_id, plate or label)
    with overlay_lock:
        if box is None:
            box = _tracked_box(tracked_vehicle_boxes, object_id)
        if box is None and time.time() < recent_vehicle_box_until:
            box = recent_vehicle_box

        existing = plate_overlays.get(key)
        if preserve_identity and existing and existing.get("plate"):
            known, label, plate = existing.get("known"), existing.get("label"), existing.get("plate")

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


def update_drone_overlay(data, known=None, identity_label=None, plate="", preserve_identity=False):
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
        if preserve_identity and (previous.get("known") or previous.get("plate")):
            known, identity_label = None, None
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
        if latest_jpeg:
            return bytes(latest_jpeg)
    # Local reader idle: take Frigate's latest frame, with detection boxes drawn.
    try:
        r = requests.get(f"{FRIGATE_API_URL}/api/{CAMERA_NAME}/latest.jpg",
                         params={"bbox": 1, "h": 720}, timeout=3)
        if r.ok and r.content[:2] == b"\xff\xd8":
            return r.content
    except Exception as e:
        print("Frigate snapshot error:", e)
    return None


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
        "Camera": CAMERA_NAME,
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
                buttons=alert_buttons(CAMERA_NAME),
            )
        elif event_type.upper() in {"UNKNOWN PLATE", "UNKNOWN VEHICLE"}:
            plate_text = identifier or "Plate unavailable"
            queue_telegram_alert(
                "unknown_vehicle",
                f"⚠️ UNKNOWN VEHICLE detected at {CAMERA_NAME}\nPlate: {plate_text}\n{date_text} {time_text}",
                f"unknown_vehicle:{object_id or plate_text}",
                snapshot_bytes=snapshot_bytes,
                buttons=alert_buttons(CAMERA_NAME),
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


face_attempts = {}  # object_id -> failed face-recognition attempts seen over MQTT


def record_face_attempt(object_id):
    """A face was seen but not matched. Counted, not saved: Frigate keeps trying."""
    object_id = str(object_id or "").strip()
    if object_id:
        with unknown_event_lock:
            face_attempts[object_id] = face_attempts.get(object_id, 0) + 1


def person_left(object_id):
    """Frigate ended this person's event: decide on the unknown-face question now."""
    object_id = str(object_id or "").strip()
    with unknown_event_lock:
        item = pending_unknown_people.get(object_id)
        if item:
            item["ended"] = True
            item["due"] = time.time()


def frigate_sub_label(object_id):
    """The name Frigate finally assigned to this person, if any."""
    try:
        ev = requests.get(f"{FRIGATE_API_URL}/api/events/{object_id}", timeout=3).json()
        sub = ev.get("sub_label")
        if isinstance(sub, (list, tuple)):
            sub = sub[0] if sub else None
        return None if is_unknown(sub) else str(sub)
    except Exception:
        return None


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
                        face_attempts.pop(object_id, None)
                        continue
                    attempts = face_attempts.get(object_id, 0)
                age = now - float(item.get("created", now))
                ended = bool(item.get("ended"))
                # Unknown only when Frigate saw the face and kept failing to match it:
                # when the person leaves, after enough attempts, or after a long stay.
                if attempts == 0:
                    decide = None if (ended or age >= UNKNOWN_FACE_MAX_SECONDS) else "wait"
                elif ended or age >= UNKNOWN_FACE_MAX_SECONDS or (attempts >= UNKNOWN_FACE_MIN_ATTEMPTS and age >= 60):
                    decide = "unknown"
                else:
                    decide = "wait"
                if decide == "wait":
                    item["due"] = now + 10
                    with unknown_event_lock:
                        if object_id not in recognized_person_ids:
                            pending_unknown_people[object_id] = item
                    continue
                with unknown_event_lock:
                    face_attempts.pop(object_id, None)
                if decide is None:
                    continue  # no face ever seen (back turned, too far): not an unknown face
                name = frigate_sub_label(object_id)  # final check: Frigate may have matched late
                if name:
                    mark_person_recognized(object_id)
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


# Event snapshots and history are pruned after this many days (0 keeps everything).
EVENT_RETENTION_DAYS = int(os.environ.get("AI_SECURITY_EVENT_RETENTION_DAYS", "30"))


def prune_old_events(days=None, now=None):
    """Delete event snapshots and history rows older than the retention period."""
    days = EVENT_RETENTION_DAYS if days is None else days
    if days <= 0:
        return 0, 0
    cutoff = (now or time.time()) - days * 86400
    cutoff_date = time.strftime("%Y-%m-%d", time.localtime(cutoff))
    removed_rows = removed_files = 0
    with event_log_lock:
        if os.path.exists(EVENT_LOG):
            with open(EVENT_LOG, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                rows = list(reader)
            keep = [r for r in rows if not r.get("Date") or r["Date"] >= cutoff_date]
            removed_rows = len(rows) - len(keep)
            if removed_rows and fieldnames:
                tmp = EVENT_LOG + ".tmp"
                with open(tmp, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(keep)
                os.replace(tmp, EVENT_LOG)
    if os.path.isdir(EVENT_FOLDER):
        for name in os.listdir(EVENT_FOLDER):
            path = os.path.join(EVENT_FOLDER, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed_files += 1
            except OSError:
                pass
    if removed_rows or removed_files:
        print(f"Event retention: removed {removed_rows} history rows and {removed_files} snapshots older than {days} days")
    return removed_rows, removed_files


def event_retention_worker():
    while True:
        try:
            prune_old_events()
        except Exception as e:
            print("Event retention error:", e)
        time.sleep(6 * 3600)


threading.Thread(target=event_retention_worker, daemon=True).start()


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

# The browser plays the live view straight from Frigate's go2rtc relay, so the dashboard
# only decodes the camera itself when something needs frames here: an MJPEG fallback
# viewer, face enrollment, or a short on-demand request. Decoding the stream full-time
# in Python cost ~15-20% of the PC and lagged ~1 s behind.
FRIGATE_API_URL = os.environ.get("AI_SECURITY_FRIGATE_API", "http://127.0.0.1:5000")
GO2RTC_URL = os.environ.get("AI_SECURITY_GO2RTC_URL", "http://127.0.0.1:1984")
live_viewers = 0
live_viewers_lock = threading.Lock()
frame_demand_until = 0.0
_frigate_online_cache = {}


def request_frames(seconds=8.0):
    """Ask the camera reader to run for at least `seconds`."""
    global frame_demand_until
    frame_demand_until = max(frame_demand_until, time.time() + seconds)


def frames_wanted():
    return live_viewers > 0 or bool(enrollment.get("running")) or time.time() < frame_demand_until


def frigate_camera_online(camera=None):
    """Camera status from Frigate (cached 5 s per camera), used while the local reader is idle."""
    camera = camera or CAMERA_NAME
    now = time.time()
    cached = _frigate_online_cache.get(camera)
    if cached and now - cached[0] < 5:
        return cached[1]
    online = False
    try:
        stats = requests.get(f"{FRIGATE_API_URL}/api/stats", timeout=2).json()
        online = float(((stats.get("cameras") or {}).get(camera) or {}).get("camera_fps") or 0) > 0
    except Exception:
        pass
    _frigate_online_cache[camera] = (now, online)
    return online


def camera_worker():
    global latest_frame
    global camera_connected

    cap = None

    while True:
        try:
            # Close the local RTSP reader while Camera AI is disabled or nothing needs frames.
            if not camera_enabled_runtime or not frames_wanted():
                camera_connected = bool(camera_enabled_runtime and frigate_camera_online())
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

drone_viewers = 0
drone_viewers_lock = threading.Lock()


def drone_frames_wanted():
    """The browser plays the drone from the go2rtc relay; decode it here only for the
    MJPEG fallback viewer or drone face enrollment."""
    return drone_viewers > 0 or (bool(enrollment.get("running")) and enrollment.get("source") == "drone")


def drone_video_online():
    """Is the drone publishing? Checked without opening a stream: Frigate's drone camera
    fps while Drone AI is on, otherwise a quick look at the go2rtc relay."""
    if frigate_camera_online(DRONE_CAMERA_NAME):
        return True
    try:
        info = requests.get(f"{GO2RTC_URL}/api/streams", params={"src": DRONE_CAMERA_NAME}, timeout=2).json()
        return any(p.get("medias") for p in (info.get("producers") or []))
    except Exception:
        return False


def drone_camera_worker():
    global drone_latest_frame, drone_source_connected
    cap = None
    while True:
        try:
            # V10.8: do not probe the RTSP drone path while Drone runtime is OFF.
            # V11.1: and only decode here when something on this PC needs the frames.
            if not drone_enabled_runtime or not drone_frames_wanted():
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = None
                with drone_frame_lock:
                    drone_latest_frame = None
                drone_source_connected = bool(drone_enabled_runtime and drone_video_online())
                time.sleep(2.0)
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
    # MJPEG fallback / enrollment preview: keeps the local drone reader running while open.
    global drone_viewers
    with drone_viewers_lock:
        drone_viewers += 1
    try:
        last_sent = None
        while True:
            jpg = None
            with drone_jpeg_lock:
                if drone_latest_jpeg is not None:
                    jpg = drone_latest_jpeg
            if jpg is None or jpg is last_sent:
                # Only send newly encoded frames. Re-sending the same JPEG every few ms
                # floods the socket, and the browser-side buffering adds latency.
                time.sleep(0.005)
                continue
            last_sent = jpg
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-cache, no-store, must-revalidate\r\n"
                b"Pragma: no-cache\r\n"
                b"Expires: 0\r\n\r\n" + jpg + b"\r\n"
            )
    finally:
        with drone_viewers_lock:
            drone_viewers -= 1


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

        # Re-apply sources the user stopped: Frigate starts every configured camera.
        for name in load_local_settings().get("paused_sources") or []:
            client.publish(f"frigate/{name}/enabled/set", "OFF")

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
                            preserve_identity=True,
                        )
                    elif quick_label in {"car", "motorcycle", "truck", "bus"}:
                        update_drone_overlay(
                            data,
                            known=False,
                            identity_label="READING PLATE...",
                            preserve_identity=True,
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
                    set_face_overlay(False, "PERSON", box, object_id=object_id, preserve_identity=True)
                    queue_unknown_person(object_id, box)
                    sub = after.get("sub_label")
                    if isinstance(sub, (list, tuple)):
                        sub = sub[0] if sub else None
                    if sub and not is_unknown(sub):
                        mark_person_recognized(object_id)  # Frigate matched the face
                    if data.get("type") == "end":
                        person_left(object_id)
                        tracked_person_boxes.pop(object_id, None)

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
                    set_plate_overlay(False, label.upper(), "", box, object_id=object_id, preserve_identity=True)
                    if data.get("type") == "end":
                        tracked_vehicle_boxes.pop(object_id, None)

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
                # One failed attempt, not a verdict: Frigate keeps trying while the person
                # is in view. unknown_person_worker decides (and alerts) once it has its answer.
                face_object_id = payload_object_id(data) or recent_person_object_id
                record_face_attempt(face_object_id)
                queue_unknown_person(face_object_id, payload_box(data))
                set_face_overlay(False, "SCANNING FACE…", payload_box(data), object_id=face_object_id)
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
            record_sighting("face", display_name, "", CAMERA_NAME, face_object_id)
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
            record_sighting("plate", vehicle if known else "", plate, CAMERA_NAME, vehicle_object_id, known=known)

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

        # connect_async + loop_start keeps retrying in the background, so the
        # dashboard recovers if Mosquitto/Frigate start after this script.
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.connect_async(
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
            "app_version": APP_VERSION
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
    "offline_grace": False,
    "grace_expires_at": 0.0,
}

# A security system must keep running when the internet or the cloud is down.
# The cloud's signed lease is cached locally and honoured until it expires (about LICENSE_GRACE_SECONDS).
LICENSE_CACHE_FILE = os.path.join(BASE_FOLDER, "license_cache.json")
LICENSE_GRACE_SECONDS = 7 * 24 * 3600

def save_license_cache(token, data):
    """Keep the cloud-signed lease for offline use. Only the vendor's key can make one and it is
    bound to this PC's device token, so it can't be edited or copied (no lease = online only)."""
    lease = data.get("lease")
    ok, reason, _ = licensing.verify_lease(lease, token)
    if not ok:
        if lease:
            print("Cloud lease rejected:", reason)
        return
    try:
        tmp = LICENSE_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(lease, f)
        os.replace(tmp, LICENSE_CACHE_FILE)
    except Exception as e:
        print("License cache save error:", e)

def load_license_cache(token, now=None):
    """Return the cached lease's licence if it is genuine, for this PC and not expired."""
    try:
        with open(LICENSE_CACHE_FILE, "r", encoding="utf-8") as f:
            lease = json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print("License cache read error:", e)
        return None
    ok, reason, payload = licensing.verify_lease(lease, token, now=now)
    if not ok:
        print("License cache ignored:", reason)
        return None
    return payload

def _apply_license(data, connected, last_success):
    org_active = str(data.get("organization_status") or "").lower() in {"active", "trial"}
    features = data.get("features") if isinstance(data.get("features"), dict) else {}
    with cloud_lock:
        cloud_state.update({
            "connected": connected,
            "licensed": org_active,
            "organization_status": str(data.get("organization_status") or "unknown"),
            "plan_code": str(data.get("plan_code") or "unknown"),
            "features": features,
            "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {"cameras": 0, "drones": 0},
            "limits": data.get("limits") if isinstance(data.get("limits"), dict) else {"cameras": None, "drones": None},
            "last_success": last_success,
            "offline_grace": not connected,
            "grace_expires_at": last_success + LICENSE_GRACE_SECONDS,
        })
    return org_active, features

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

# ---------------- On-prem (offline license file) ----------------
import licensing
import edition

# Optional flag beside the brand subtitle (on-prem "Lebanon" edition sets BRAND_FLAG = "lb").
BRAND_FLAGS = {
    "lb": '<svg class="brand-flag" viewBox="0 0 30 20" width="18" height="12" aria-label="Lebanon" '
          'style="vertical-align:-2px;margin-left:5px;border-radius:1px;box-shadow:0 0 0 1px rgba(255,255,255,.15)">'
          '<rect width="30" height="20" fill="#ED1C24"/><rect y="5" width="30" height="10" fill="#fff"/>'
          '<polygon fill="#00A651" points="15,5.6 18.4,9.3 16.9,9.3 19.8,12.1 17.9,12.1 21.4,14.3 8.6,14.3 '
          '12.1,12.1 10.2,12.1 13.1,9.3 11.6,9.3"/><rect x="14.4" y="14.3" width="1.2" height="0.7" fill="#00A651"/></svg>'
}
BRAND_SUB_HTML = edition.BRAND_SUB + BRAND_FLAGS.get(getattr(edition, "BRAND_FLAG", ""), "")

LICENSE_FILE = os.path.join(os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER), "license.lic")
offline_license = {"ok": False, "reason": "No license installed.", "payload": None}


def check_offline_license():
    """Verify the installed license file and, when valid, use it instead of the cloud."""
    ok, reason, payload = licensing.check_file(LICENSE_FILE)
    offline_license.update(ok=ok, reason=reason, payload=payload if ok else None)
    if ok:
        with cloud_lock:
            cloud_state.update({
                "connected": False,
                "licensed": True,
                "organization_status": "active",
                "plan_code": str(payload.get("plan") or "on-prem"),
                "features": licensing.features_for_dashboard(payload),
                "limits": {"cameras": (payload.get("limits") or {}).get("cameras"),
                           "drones": (payload.get("limits") or {}).get("drones")},
                "last_error": "",
                "offline_grace": False,
                "license_mode": "offline",
                "license": {k: payload.get(k) for k in ("customer", "expires", "license_id", "plan")},
            })
    return ok


def onprem_mode():
    return bool(offline_license.get("ok"))


check_offline_license()


def local_source_usage():
    """Cameras/drones configured on this PC (on-prem plan limits are counted locally)."""
    names = _frigate_camera_names() if "_frigate_camera_names" in globals() else []
    drones = sum(1 for n in names if str(n).lower().startswith(DRONE_CAMERA_NAME))
    return {"cameras": len(names) - drones, "drones": drones}


def cloud_control_worker():
    global camera_enabled_runtime
    if check_offline_license() or edition.EDITION == "onprem":
        # On-prem: never contact the cloud. Re-check the license (expiry) every hour.
        while True:
            if check_offline_license():
                with cloud_lock:
                    cloud_state["usage"] = local_source_usage()
            else:
                with cloud_lock:
                    cloud_state.update({"licensed": False, "license_mode": "offline",
                                        "last_error": offline_license.get("reason") or ""})
            time.sleep(3600)
    config = load_edge_agent_config()
    token = str(config.get("device_token") or "").strip()
    if not token:
        with cloud_lock:
            cloud_state["last_error"] = "Missing device_token in edge_agent_config.json"
        print("Cloud Edge Agent disabled: missing device token.")
        return

    # Start from the cached license so features work immediately, even offline.
    cached = load_license_cache(token)
    if cached:
        issued = datetime.datetime.fromisoformat(str(cached["issued_at"]).replace("Z", "+00:00")).timestamp()
        _apply_license(cached, connected=False, last_success=issued)
        print("Using cached license until cloud responds")

    while True:
        try:
            response = requests.post(
                CLOUD_CONTROL_URL,
                headers={"x-device-token": token},
                json={"app_version": APP_VERSION},
                timeout=12,
            )
            response.raise_for_status()
            data = response.json()
            now = time.time()
            org_active, features = _apply_license(data, connected=True, last_success=now)
            with cloud_lock:
                cloud_state["last_error"] = ""
            save_license_cache(token, data)

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
                last_success = float(cloud_state.get("last_success") or 0)
                if last_success and time.time() - last_success <= LICENSE_GRACE_SECONDS:
                    # Keep the last good license; features stay on while offline.
                    cloud_state["offline_grace"] = True
                elif cloud_state.get("licensed"):
                    cloud_state["licensed"] = False
                    cloud_state["offline_grace"] = False
                    print("Offline grace period expired: licensed features disabled")
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
    # MJPEG fallback (and the enrollment preview): keeps the local reader running while open.
    global live_viewers
    with live_viewers_lock:
        live_viewers += 1
    try:
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
    finally:
        with live_viewers_lock:
            live_viewers -= 1


_detect_size_cache = {}


def camera_detect_size(camera=None):
    """Frigate's detect resolution: the coordinate space of detection boxes (cached 60 s)."""
    camera = camera or CAMERA_NAME
    now = time.time()
    cached = _detect_size_cache.get(camera)
    if cached and now - cached[0] < 60:
        return cached[1]
    size = cached[1] if cached else (1280, 720)
    try:
        cfg = requests.get(f"{FRIGATE_API_URL}/api/config", timeout=3).json()
        detect = ((cfg.get("cameras") or {}).get(camera) or {}).get("detect") or {}
        if detect.get("width") and detect.get("height"):
            size = (int(detect["width"]), int(detect["height"]))
    except Exception:
        pass
    _detect_size_cache[camera] = (now, size)
    return size


@app.route("/api/live/config")
def api_live_config():
    width, height = camera_detect_size()
    dwidth, dheight = camera_detect_size(DRONE_CAMERA_NAME)
    main = {"stream": CAMERA_NAME, "width": width, "height": height, "fallback": "/video_feed",
            "overlays": "/api/status", "fallback_on_timeout": True}
    drone = {"stream": DRONE_CAMERA_NAME, "width": dwidth, "height": dheight, "fallback": "/drone_video_feed",
             # The drone is often not flying: keep waiting on the relay instead of falling back.
             "overlays": "/api/drone/tracking/status", "fallback_on_timeout": False}
    cameras = {"main": main, "drone": drone}
    # Extra cameras and drones (multi-camera grid): relay only, no MJPEG fallback.
    for name in _frigate_camera_names():
        if name not in (CAMERA_NAME, DRONE_CAMERA_NAME):
            w, h = camera_detect_size(name)
            cameras[name] = {"stream": name, "width": w, "height": h, "fallback": None,
                             "overlays": None, "fallback_on_timeout": False}
    return jsonify({"go2rtc": GO2RTC_URL, **main, "cameras": cameras})


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

        # The local camera reader only runs on demand; give it time to connect.
        if source != "drone":
            request_frames(15)
            for _ in range(50):
                with frame_lock:
                    if latest_frame is not None:
                        break
                time.sleep(0.2)

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
    usage = local_source_usage() if onprem_mode() else (c.get("usage") or {})
    used = int(usage.get(usage_key) or 0)
    limit = (c.get("limits") or {}).get(usage_key)
    allowed = bool(c.get("licensed")) and cloud_feature_enabled(feature_key) and (limit is None or used < int(limit))
    plan = str(c.get("plan_code") or "current").upper()
    if allowed:
        message = f"{source_type.title()} can be added ({used}/{limit if limit is not None else 'unlimited'} used)."
    elif limit is not None and used >= int(limit):
        noun = usage_key if int(limit) != 1 else usage_key[:-1]
        more = "Contact your supplier for a license with more." if onprem_mode() else "Upgrade your plan to add more."
        message = f"{plan} plan allows a maximum of {limit} {noun}. {more}"
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

# ============================================================
# HUD THEME (shared by every page; same look as the Drones / control page)
# ============================================================

HUD_CSS = r"""
*{box-sizing:border-box}
html,body{margin:0;min-height:100%}
body{background:#02070c;color:#d9efff;font-family:Arial,Helvetica,sans-serif;overflow-x:hidden}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:linear-gradient(rgba(20,135,180,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(20,135,180,.025) 1px,transparent 1px);
  background-size:40px 40px}
a{color:#5bd9ff}

/* top bar */
.hud-top{position:sticky;top:0;z-index:20;display:flex;align-items:stretch;min-height:64px;background:#03101a;
  border-bottom:1px solid #0876ad;box-shadow:0 0 26px rgba(0,153,255,.10);overflow:hidden}
.hud-top::after{content:"";position:absolute;bottom:0;left:-40%;width:40%;height:1px;
  background:linear-gradient(90deg,transparent,#36cfff,transparent);animation:topSweep 4s linear infinite}
@keyframes topSweep{to{left:100%}}
.hud-brand{display:flex;align-items:center;gap:11px;padding:0 18px;border-right:1px solid #12405a;text-decoration:none;flex:none}
.brand-shield{width:40px;height:45px;display:flex;align-items:center;justify-content:center;
  clip-path:polygon(50% 0,92% 15%,84% 74%,50% 100%,16% 74%,8% 15%);background:rgba(18,151,215,.20);
  color:#45d0ff;font-size:18px;border:1px solid #31c6ff}
.brand-name{color:#5bd9ff;font-size:17px;font-weight:bold;letter-spacing:2px}
.brand-sub{margin-top:2px;color:#4a91b2;font-size:8px;letter-spacing:2px}
.hud-nav{display:flex;flex:1;overflow-x:auto;scrollbar-width:none}
.hud-nav::-webkit-scrollbar{display:none}
.hud-nav a{position:relative;display:flex;align-items:center;gap:8px;padding:0 16px;color:#6d8b9d;text-decoration:none;
  font-size:10px;letter-spacing:1.5px;text-transform:uppercase;border-right:1px solid #123447;white-space:nowrap;transition:.2s}
.hud-nav a .ico{color:#2f7fa3;font-size:13px}
.hud-nav a:hover{color:#bfefff;background:rgba(14,88,128,.12)}
.hud-nav a.active{color:#5bd9ff;background:rgba(18,151,215,.10)}
.hud-nav a.active .ico{color:#45d0ff}
.hud-nav a.active::after{content:"";position:absolute;left:0;right:0;bottom:0;height:2px;background:#36cfff;box-shadow:0 0 10px #36cfff}
.hud-clock{display:flex;flex-direction:column;justify-content:center;align-items:flex-end;padding:0 18px;border-left:1px solid #12405a;min-width:150px;flex:none}
.hud-clock b{color:#e9f8ff;font-size:16px;letter-spacing:1px}
.hud-clock span{margin-top:3px;color:#24ed87;font-size:9px;letter-spacing:1.5px;display:flex;align-items:center;gap:6px}

/* layout */
.hud-main{position:relative;z-index:1;max-width:1500px;margin:0 auto;padding:22px 24px 40px}
.hud-main.narrow{max-width:920px}
.page-head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;margin-bottom:18px;flex-wrap:wrap}
.page-kicker{color:#4a91b2;font-size:10px;letter-spacing:3px;text-transform:uppercase}
.page-title{margin:6px 0 0;color:#5bd9ff;font-size:22px;letter-spacing:2px;text-transform:uppercase;font-weight:bold;text-shadow:0 0 18px rgba(54,207,255,.25)}
.page-sub{color:#6d8b9d;font-size:12px;margin-top:6px;letter-spacing:.5px;line-height:1.5}
.actions{display:flex;gap:8px;flex-wrap:wrap}
.grid-2{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(320px,.8fr);gap:16px;align-items:start}
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px}

/* panels */
.panel{position:relative;overflow:hidden;background:#04111b;border:1px solid #0a5480;border-radius:6px;box-shadow:0 0 20px rgba(0,126,188,.08);margin-bottom:16px}
.panel::before{content:"";position:absolute;top:0;left:0;width:130px;height:1px;background:linear-gradient(90deg,#36cfff,transparent)}
.panel-head{min-height:43px;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:0 14px;border-bottom:1px solid #123447}
.panel-title{color:#a8c7d7;font-size:11px;letter-spacing:1.5px;text-transform:uppercase}
.panel-body{padding:16px}
.live{color:#2aea88;font-size:10px;letter-spacing:1px}
.stat{position:relative;overflow:hidden;background:#04111b;border:1px solid #0a5480;border-radius:6px;padding:14px 16px}
.stat::after{content:"";position:absolute;bottom:0;left:-100%;width:100%;height:1px;background:linear-gradient(90deg,transparent,#36cfff,transparent);animation:topSweep 4s linear infinite}
.stat-label{color:#6d8b9d;font-size:10px;letter-spacing:1.5px;text-transform:uppercase}
.stat-value{margin-top:8px;font-size:15px;font-weight:bold;color:#e9f8ff;letter-spacing:.5px}

/* status dots */
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#4d6b7c;margin-right:8px;vertical-align:middle}
.dot.good{background:#26ee89;box-shadow:0 0 10px #26ee89;animation:pulseDot 1.4s infinite}
.dot.warn{background:#ffb23c;box-shadow:0 0 10px #ffb23c;animation:pulseDot 1.4s infinite}
.dot.bad{background:#ff5d6c;box-shadow:0 0 10px #ff5d6c}
@keyframes pulseDot{50%{opacity:.35;transform:scale(.7)}}

/* video */
.camera-box{position:relative;background:#000;aspect-ratio:16/9}
.camera-box img{width:100%;height:100%;object-fit:contain;display:block}
.corner{position:absolute;width:34px;height:34px;pointer-events:none}
.corner.tl{top:14px;left:14px;border-top:2px solid #3dd8ff;border-left:2px solid #3dd8ff}
.corner.tr{top:14px;right:14px;border-top:2px solid #3dd8ff;border-right:2px solid #3dd8ff}
.corner.bl{bottom:14px;left:14px;border-bottom:2px solid #3dd8ff;border-left:2px solid #3dd8ff}
.corner.br{bottom:14px;right:14px;border-bottom:2px solid #3dd8ff;border-right:2px solid #3dd8ff}
.overlay-tag{position:absolute;left:56px;bottom:22px;background:rgba(3,16,26,.85);border:1px solid #155879;color:#9edfff;padding:7px 10px;border-radius:4px;font-size:10px;letter-spacing:1px;text-transform:uppercase}
.camera-footer{min-height:30px;display:flex;align-items:center;justify-content:space-between;padding:0 12px;color:#5d8499;font-size:9px;letter-spacing:1px}
.cam-name{color:#35caff}

/* rows, text */
.hud-row{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:12px 14px;background:#05131d;border:1px solid #153c56;border-radius:5px;margin-bottom:8px}
.hud-row:last-child{margin-bottom:0}
.hud-row b{color:#d9efff;font-size:13px;letter-spacing:.3px}
.muted{color:#6d8b9d;font-size:12px;line-height:1.5}
.state{color:#2aea88;font-size:11px;font-weight:bold;letter-spacing:1px}
code{color:#2eef88;background:#020a10;border:1px solid #123447;border-radius:3px;padding:2px 6px;font-size:12px;word-break:break-all}

/* buttons, inputs */
.hud-btn{min-height:36px;padding:0 16px;cursor:pointer;color:#66dfff;background:rgba(14,88,128,.12);border:1px solid #155879;border-radius:4px;
  font-size:10px;font-weight:bold;letter-spacing:1.5px;text-transform:uppercase;font-family:inherit;transition:.2s}
.hud-btn:hover{color:#fff;border-color:#35cbff;box-shadow:0 0 12px rgba(53,203,255,.16)}
.hud-btn.primary{color:#02131d;background:#25c7ff;border-color:#45d0ff;box-shadow:0 0 16px rgba(37,199,255,.25)}
.hud-btn.primary:hover{background:#5bd9ff;color:#02131d}
.hud-btn.danger{color:#ff7b86;border-color:#7a2935;background:rgba(125,12,28,.12)}
.hud-btn:disabled{opacity:.5;cursor:default;box-shadow:none}
label{display:block;margin:16px 0 7px;color:#a8c7d7;font-size:10px;letter-spacing:1.5px;text-transform:uppercase}
input[type=text],input[type=password],input[type=number],input:not([type]),select{width:100%;background:#020a10;color:#d9efff;border:1px solid #155879;
  border-radius:4px;padding:11px 12px;font-size:14px;font-family:inherit;outline:none;transition:.2s}
input:focus,select:focus{border-color:#36cfff;box-shadow:0 0 12px rgba(54,207,255,.18)}
input.toggle{appearance:none;-webkit-appearance:none;position:relative;flex:none;width:46px;height:24px;margin:0;border-radius:12px;
  background:#0a1c28;border:1px solid #155879;cursor:pointer;transition:.2s}
input.toggle::after{content:"";position:absolute;top:3px;left:3px;width:16px;height:16px;border-radius:50%;background:#4d6b7c;transition:.2s}
input.toggle:checked{background:rgba(37,199,255,.18);border-color:#36cfff;box-shadow:0 0 12px rgba(54,207,255,.2)}
input.toggle:checked::after{left:25px;background:#45d0ff;box-shadow:0 0 8px #45d0ff}
.hud-msg{margin-top:16px;padding:12px 14px;border-radius:5px;border:1px solid #155879;background:#05131d;font-size:13px;color:#9edfff}
.hud-msg:empty{display:none}
.hud-msg.ok{border-color:#1f7a50;color:#7dffc1;background:rgba(18,120,70,.12)}
.hud-msg.bad{border-color:#7a2935;color:#ff9ea8;background:rgba(125,12,28,.14)}
.notice{display:none}.notice.show{display:block}

/* events */
.event-row{display:grid;grid-template-columns:64px 1fr auto;gap:12px;align-items:center;padding:10px 0;border-bottom:1px solid #123447}
.event-row:last-child{border-bottom:0}
.thumb{width:64px;height:44px;border-radius:4px;border:1px solid #153c56;background:#05131d;object-fit:cover;display:block}
.event-type{color:#5bd9ff;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase}
.event-type.unknown{color:#ffb23c}

@media(max-width:1000px){.grid-2{grid-template-columns:1fr}.stat-grid{grid-template-columns:1fr 1fr}.hud-clock{display:none}}
@media(max-width:560px){.stat-grid{grid-template-columns:1fr}.brand-sub{display:none}.hud-main{padding:16px 12px 32px}}
"""

# Live camera player shared by the dashboard pages. Any element with data-live-camera
# plays the camera straight from Frigate's go2rtc relay (MSE over WebSocket, decoded by
# the browser) with detection boxes drawn on a canvas. Falls back to /video_feed (MJPEG,
# decoded by this program) when the relay is unavailable.
LIVE_PLAYER_HTML = r"""
<style>
.live-slot{position:relative;width:100%;height:100%;background:#000;overflow:hidden}
.live-slot video-stream,.live-slot video,.live-slot>img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;display:block;background:#000}
.live-slot canvas{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:2}
.live-slot video-stream div{display:none!important}  /* go2rtc's raw status text; our tag shows status */
.live-mode{position:absolute;right:12px;top:10px;z-index:3;font:bold 9px Arial,sans-serif;letter-spacing:1px;color:#2aea88;
  background:rgba(3,16,26,.8);border:1px solid #155879;padding:4px 7px;border-radius:3px}
.live-mode.compat{color:#ffb23c}
</style>
<script type="module">
const cfg = await fetch("/api/live/config", {cache: "no-store"}).then(r => r.json()).catch(() => null);

function setMode(slot, text, compat) {
    let tag = slot.querySelector(".live-mode");
    if (!tag) { tag = document.createElement("div"); tag.className = "live-mode"; slot.appendChild(tag); }
    tag.textContent = text;
    tag.classList.toggle("compat", !!compat);
}

function useFallback(slot, why, cam) {
    if (cam && cam.fallback === null) {  // extra cameras/drones: no MJPEG feed to fall back to
        setMode(slot, "NO VIDEO", true);
        console.info("Live view unavailable:", why);
        return;
    }
    slot.querySelector("video-stream")?.remove();
    if (!slot.querySelector(":scope > img")) {
        const img = new Image();
        img.alt = "Live camera";
        img.src = (cam && cam.fallback) || (cfg && cfg.fallback) || "/video_feed";
        slot.prepend(img);
    }
    slot.dataset.mode = "mjpeg";
    setMode(slot, "COMPATIBILITY MODE", true);
    console.info("Live view fallback:", why);
}

function drawOverlays(slot, cam) {
    const canvas = document.createElement("canvas");
    slot.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    let items = [];
    const render = () => {
        const w = slot.clientWidth, h = slot.clientHeight, dpr = window.devicePixelRatio || 1;
        canvas.width = w * dpr; canvas.height = h * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);
        if (slot.dataset.mode !== "direct") return;  // the MJPEG fallback has boxes drawn in
        // Boxes arrive in Frigate's detect resolution; the video is scaled to fit the slot.
        const v = slot.querySelector("video");
        const vw = cam.width || 1280, vh = cam.height || 720;
        const ar = (v && v.videoWidth && v.videoHeight) ? v.videoWidth / v.videoHeight : vw / vh;
        const dispW = Math.min(w, h * ar), dispH = dispW / ar, s = dispW / vw, sy = dispH / vh;
        const ox = (w - dispW) / 2, oy = (h - dispH) / 2;
        for (const it of items) {
            const color = it.known ? "#00dc50" : "#ffa500";
            let X = ox + 18, Y = oy + 18, W = dispW - 36, H = dispH - 36;  // no box: frame the view
            if (Array.isArray(it.box) && it.box.length === 4) {
                const [x1, y1, x2, y2] = it.box.map(Number);
                X = ox + x1 * s; Y = oy + y1 * sy; W = (x2 - x1) * s; H = (y2 - y1) * sy;
            }
            ctx.lineWidth = 3; ctx.strokeStyle = color; ctx.strokeRect(X, Y, W, H);
            let label = String(it.label || (it.kind === "face" ? "PERSON" : "VEHICLE"));
            if (it.plate) label += " | " + it.plate;
            ctx.font = "bold 13px Arial, sans-serif";
            const tw = ctx.measureText(label).width + 12, ty = Math.max(0, Y - 20);
            ctx.fillStyle = color; ctx.fillRect(X, ty, tw, 20);
            ctx.fillStyle = "#000"; ctx.fillText(label, X + 6, ty + 15);
        }
    };
    const poll = async () => {
        if (slot.dataset.mode === "direct" && !document.hidden) {
            try {
                const st = await fetch(cam.overlays || "/api/status", {cache: "no-store"}).then(r => r.json());
                items = st.targets  // drone: every tracked person/vehicle
                    ? st.targets.map(t => ({...t, kind: t.type === "person" ? "face" : "vehicle"}))
                    : [...(st.active_faces || []).map(f => ({...f, kind: "face"})),
                       ...(st.active_vehicles || []).map(v => ({...v, kind: "vehicle"}))];
            } catch (e) { items = []; }
        }
        render();
    };
    (slot._timers = slot._timers || []).push(setInterval(poll, 700));
    window.addEventListener("resize", render);
    slot._cleanup = () => window.removeEventListener("resize", render);
    poll();
}

async function attach(slot) {
    const key = slot.dataset.liveCamera || "main";
    // A camera added after this page loaded isn't in cfg yet: play its relay stream by name.
    const cam = (cfg && cfg.cameras && cfg.cameras[key])
        || (key !== "main" ? {stream: key, fallback: null, overlays: null, fallback_on_timeout: false} : cfg);
    if (!cfg || !cfg.go2rtc || !cam) return useFallback(slot, "no live config", cam);
    try { await import(cfg.go2rtc + "/video-stream.js"); }
    catch (e) { return useFallback(slot, "relay player unavailable", cam); }
    const el = document.createElement("video-stream");
    el.mode = "mse";          // MSE over WebSocket works through Docker's localhost-only ports
    el.background = false;    // pause while the page is hidden, to save CPU
    el.src = cfg.go2rtc.replace(/^http/, "ws") + "/api/ws?src=" + encodeURIComponent(cam.stream);
    slot.prepend(el);
    slot.dataset.mode = "direct";
    setMode(slot, "CONNECTING…", true);
    const started = Date.now();
    if (!slot._fullscreenBound) {  // double-click any live feed for full screen
        slot.addEventListener("dblclick", () => slot.requestFullscreen?.());
        slot._fullscreenBound = true;
    }
    const check = setInterval(() => {
        if (!slot.isConnected || slot.dataset.mode === undefined) { clearInterval(check); return; }
        const v = el.querySelector("video");
        if (v && v.controls) v.controls = false;  // no browser player bar over the camera
        if (v && v.currentTime > 0 && !v.paused) {
            setMode(slot, "● REAL-TIME");
            if (cam.fallback_on_timeout !== false) clearInterval(check);
            return;
        }
        if (Date.now() - started > 8000) {
            if (cam.fallback_on_timeout !== false) { clearInterval(check); useFallback(slot, "no video from relay", cam); }
            else setMode(slot, "WAITING FOR VIDEO", true);  // the player keeps retrying on its own
        }
    }, 1000);
    if (cam.overlays) drawOverlays(slot, cam);
}

// Panels with data-live-deferred are started by their Live feed switch instead.
document.querySelectorAll("[data-live-camera]:not([data-live-deferred])").forEach(attach);
// The multi-camera grid adds tiles after load and attaches them with this.
window.attachLiveCamera = attach;

// Stop a live view completely: closes the relay connection or MJPEG stream and its timers.
function detach(slot) {
    (slot._timers || []).forEach(clearInterval);
    slot._timers = [];
    if (slot._cleanup) { slot._cleanup(); slot._cleanup = null; }
    slot.querySelectorAll("video-stream, canvas, .live-mode").forEach(el => el.remove());
    const img = slot.querySelector(":scope > img");
    if (img) { img.src = "data:,"; img.remove(); }
    delete slot.dataset.mode;
}
window.detachLiveCamera = detach;
window.dispatchEvent(new Event("live-player-ready"));
</script>
"""

HUD_NAV_ITEMS = [
    ("dashboard", "/", "⌂", "Dashboard"),
    ("events", "/#history", "◷", "Events"),
    ("people", "/#face-library", "◎", "People"),
    ("vehicles", "/#vehicle-library", "▱", "Vehicles"),
    ("drone", "/drone-control", "✈", "Drone"),
    ("virtual", "/virtual-drones", "◇", "Virtual drones"),
    ("devices", "/setup/add", "＋", "Devices"),
    ("settings", "/settings", "⚙", "Settings"),
    ("license", "/license", "⚿", "License"),
]


def hud_topbar(active="", nav=True):
    active_attr = ' class="active"'
    links = "".join(
        f'<a href="{href}"{active_attr if key == active else ""}><span class="ico">{ico}</span>{label}</a>'
        for key, href, ico, label in HUD_NAV_ITEMS
    ) if nav else ""
    return (
        '<header class="hud-top">'
        '<a class="hud-brand" href="/"><div class="brand-shield">A</div>'
        f'<div><div class="brand-name">{edition.BRAND_TOP}</div><div class="brand-sub">{BRAND_SUB_HTML}</div></div></a>'
        f'<nav class="hud-nav">{links}</nav>'
        '<div class="hud-clock"><b id="hudClock">--:--:--</b><span><i class="dot good"></i>SYSTEM PROTECTED</span></div>'
        '</header>'
        '<script>(function(){const c=document.getElementById("hudClock");'
        'const t=()=>{c.textContent=new Date().toLocaleTimeString()};t();setInterval(t,1000)})()</script>'
    )


def hud_page(title, body, active="", head="", nav=True):
    """A complete page in the HUD theme. `body` is inserted under the top bar."""
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title} — {edition.PRODUCT_NAME}</title>'
        '<link rel="stylesheet" href="/hud.css">' + head + '</head><body>'
        + hud_topbar(active, nav) + body + '</body></html>'
    )


def hud_subnav(active=""):
    """Navigation strip for the Drones & Control page, which keeps its own status top bar."""
    links = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}"><span>{ico}</span>{label}</a>'
        for key, href, ico, label in HUD_NAV_ITEMS
    )
    return (
        '<style>.hud-subnav{position:relative;z-index:15;display:flex;overflow-x:auto;background:#03101a;'
        'border-bottom:1px solid #12405a;margin-bottom:10px;scrollbar-width:none}'
        '.hud-subnav a{position:relative;display:flex;align-items:center;gap:8px;padding:11px 16px;color:#6d8b9d;'
        'text-decoration:none;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;border-right:1px solid #123447;white-space:nowrap}'
        '.hud-subnav a span{color:#2f7fa3;font-size:13px}.hud-subnav a:hover{color:#bfefff;background:rgba(14,88,128,.12)}'
        '.hud-subnav a.active{color:#5bd9ff;background:rgba(18,151,215,.10)}'
        '.hud-subnav a.active::after{content:"";position:absolute;left:0;right:0;bottom:0;height:2px;background:#36cfff;box-shadow:0 0 10px #36cfff}'
        '</style>'
        f'<nav class="hud-subnav">{links}</nav>'
    )


@app.route("/hud.css")
def hud_css():
    return Response(HUD_CSS, mimetype="text/css", headers={"Cache-Control": "max-age=300"})


@app.route("/setup/discover")
@app.route("/setup/camera")
def setup_legacy_pages():
    return redirect("/setup/add")
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

# Registers camera/drone sources against the plan limits (supabase/functions/edge-source-control).
EDGE_SOURCE_CONTROL_URL = os.environ.get(
    "AI_SECURITY_SOURCE_CONTROL_URL",
    "https://qfnxwuejfotofuxlyqjd.supabase.co/functions/v1/edge-source-control",
)
def _test_rtsp(url):
    cap = cv2.VideoCapture(str(url), cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, frame = cap.read()
        return bool(ok and frame is not None and getattr(frame, "size", 0) > 0)
    finally:
        cap.release()

def _cloud_source(method="GET", payload=None):
    if onprem_mode():
        # On-prem license: sources are tracked on this PC only (limits checked locally).
        return {"ok": True, "offline": True, "sources": [], "source": None}
    token = _edge_token()
    if not token:
        return {"ok": False, "error": "Pair this Windows device to your customer account first."}
    if not EDGE_SOURCE_CONTROL_URL:
        return {"ok": False, "error": "Cloud camera-source sync is not available in this version. Configure the camera on this PC."}
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
    """Add or update one camera in the live Frigate config, keeping everything else
    (other cameras, drone, face recognition, LPR). Customer credentials stay on this PC."""
    import copy, shutil, yaml
    if not os.path.isfile(LIVE_FRIGATE_CONFIG):
        return _write_fresh_frigate(camera_name, source_url)
    with open(LIVE_FRIGATE_CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cameras = cfg.setdefault("cameras", {})
    template = next((c for n, c in cameras.items() if n != "drone" and isinstance(c, dict)), None)
    camera = copy.deepcopy(cameras.get(camera_name) or template or {
        "objects": {"track": ["person", "car", "motorcycle"]}, "detect": {"enabled": True}})
    camera["enabled"] = True
    camera["ffmpeg"] = {"inputs": [{"path": f"rtsp://127.0.0.1:8554/{camera_name}",
                                    "input_args": "preset-rtsp-restream", "roles": ["detect", "record"]}]}
    cameras[camera_name] = camera
    cfg.setdefault("go2rtc", {}).setdefault("streams", {})[camera_name] = [source_url]
    shutil.copyfile(LIVE_FRIGATE_CONFIG, LIVE_FRIGATE_CONFIG + ".before-camera-setup")
    _save_frigate_config(cfg)

def _write_fresh_frigate(camera_name, source_url):
    # No live config yet (first setup): write a minimal one where Frigate reads it.
    import yaml
    cfg = {
      "mqtt":{"host":"host.docker.internal","port":1883},
      "go2rtc":{"streams":{camera_name: [source_url]}},
      # Same defaults as edge/runtime/frigate/config.example.yaml.
      "detectors":{"cpu1":{"type":"cpu","num_threads":3}},
      "record":{"enabled":True,"motion":{"days":3},
                "alerts":{"retain":{"days":14,"mode":"motion"}},"detections":{"retain":{"days":14,"mode":"motion"}}},
      "snapshots":{"enabled":True,"bounding_box":True,"retain":{"default":14}},
      "objects":{"track":["person","car","motorcycle"]},
      "cameras":{camera_name:{
        "ffmpeg":{"inputs":[
          {"path":f"rtsp://127.0.0.1:8554/{camera_name}","input_args":"preset-rtsp-restream","roles":["detect","record"]}
        ]},
        "detect":{"enabled":True}
      }}
    }
    os.makedirs(os.path.dirname(LIVE_FRIGATE_CONFIG), exist_ok=True)
    tmp=LIVE_FRIGATE_CONFIG+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        yaml.safe_dump(cfg,f,sort_keys=False)
    os.replace(tmp,LIVE_FRIGATE_CONFIG)

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
    if _is_drone_name(slug):
        slug="cam_"+slug  # names starting with "drone" are reserved for drones
    if slug in _frigate_camera_names():
        return jsonify({"ok":False,"error":f'A camera named "{slug}" already exists. Choose another name.'}),409
    cloud=_cloud_source("POST",{"source_type":"camera","name":display})
    if not cloud.get("ok"):
        return jsonify({"ok":False,"error":cloud.get("error") or "Cloud registration failed."}),409
    try:
        # The first camera becomes the main camera; later ones join the multi-camera grid.
        is_first = CAMERA_NAME not in _frigate_camera_names()
        _write_managed_frigate(slug,url)
        if is_first:
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

def _save_frigate_config(cfg):
    """Write the live Frigate config. Docker or Frigate can hold the file open for a few seconds
    (e.g. while Frigate restarts), which makes Windows refuse the swap, so retry, then write in place."""
    tmp = LIVE_FRIGATE_CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    for _ in range(20):
        try:
            os.replace(tmp, LIVE_FRIGATE_CONFIG)
            return
        except PermissionError:
            time.sleep(0.5)
    with open(tmp, "r", encoding="utf-8") as src, open(LIVE_FRIGATE_CONFIG, "w", encoding="utf-8") as dst:
        dst.write(src.read())
    try:
        os.remove(tmp)
    except OSError:
        pass


def _frigate_camera_names():
    """Camera names in the live Frigate config (main camera, extra cameras and drones)."""
    try:
        with open(LIVE_FRIGATE_CONFIG, "r", encoding="utf-8") as f:
            return list(((yaml.safe_load(f) or {}).get("cameras") or {}).keys())
    except Exception:
        return []


def _is_drone_name(name):
    return str(name).lower().startswith("drone")


def _write_drone_frigate(name):
    """Add one more drone to the live Frigate config, using the first drone's settings.
    The DJI app publishes to rtmp://<PC>:1935/<name>; MediaMTX serves it at :8556/<name>."""
    import copy, shutil
    with open(LIVE_FRIGATE_CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cameras = cfg.setdefault("cameras", {})
    camera = copy.deepcopy(cameras.get(DRONE_CAMERA_NAME) or {
        "objects": {"track": ["person", "car", "motorcycle"]},
        "detect": {"enabled": True, "width": DRONE_FRAME_WIDTH, "height": DRONE_FRAME_HEIGHT, "fps": 5}})
    camera["enabled"] = True
    camera["ffmpeg"] = {"inputs": [{"path": f"rtsp://127.0.0.1:8554/{name}",
                                    "input_args": "preset-rtsp-restream", "roles": ["detect", "record"]}]}
    cameras[name] = camera
    cfg.setdefault("go2rtc", {}).setdefault("streams", {})[name] = [f"rtsp://host.docker.internal:8556/{name}"]
    shutil.copyfile(LIVE_FRIGATE_CONFIG, LIVE_FRIGATE_CONFIG + ".before-drone-setup")
    _save_frigate_config(cfg)


@app.route("/api/setup/drone", methods=["POST"])
def api_setup_drone():
    allowed = requests.get("http://127.0.0.1:%d/api/cloud/can-add-source/drone" % PORT, timeout=4).json()
    if not allowed.get("allowed"):
        return jsonify({"ok": False, "error": allowed.get("message") or "Your plan does not allow another drone."}), 403
    existing = set(_frigate_camera_names())
    n = 1 if DRONE_CAMERA_NAME not in existing else 2
    while n > 1 and f"{DRONE_CAMERA_NAME}{n}" in existing:
        n += 1
    name = DRONE_CAMERA_NAME if n == 1 else f"{DRONE_CAMERA_NAME}{n}"
    cloud = _cloud_source("POST", {"source_type": "drone", "name": f"Drone {n}"})
    if not cloud.get("ok"):
        return jsonify({"ok": False, "error": cloud.get("error") or "Cloud registration failed."}), 409
    try:
        _write_drone_frigate(name)
        restarted, msg = _restart_frigate()
        return jsonify({"ok": True, "name": name, "publish_url": f"rtmp://{_lan_ip()}:1935/{name}",
                        "frigate_restarted": restarted,
                        "message": f"Drone {n} added. In DJI Fly, stream RTMP to the address shown."})
    except Exception as e:
        sid = ((cloud.get("source") or {}).get("id"))
        if sid:
            _cloud_source("DELETE", {"id": sid})
        return jsonify({"ok": False, "error": f"Drone setup failed safely: {e}"}), 500


# Licence limits are enforced on what Frigate actually runs, however the camera or drone was
# added (wizard, launcher or a hand-edited config): sources beyond the limit are switched off.
over_limit_sources = set()


def _sources_over_limit(names=None):
    names = names if names is not None else _frigate_camera_names()
    with cloud_lock:
        limits = dict(cloud_state.get("limits") or {})
    cams = [n for n in names if not _is_drone_name(n)]
    drones = [n for n in names if _is_drone_name(n)]
    # Keep the main camera / first drone, then the rest in config order.
    cams.sort(key=lambda n: n != CAMERA_NAME)
    drones.sort(key=lambda n: n != DRONE_CAMERA_NAME)
    over = set()
    for group, limit in ((cams, limits.get("cameras")), (drones, limits.get("drones"))):
        if limit is not None:
            over.update(group[max(0, int(limit)):])
    return over


def _enforce_source_limits_worker():
    global over_limit_sources
    while True:
        try:
            over = _sources_over_limit()
            if over != over_limit_sources:
                if over:
                    print("Licence limit: switching off", ", ".join(sorted(over)))
                over_limit_sources = over
            if over and mqtt_connected and mqtt_client is not None:
                for name in over:
                    mqtt_client.publish(f"frigate/{name}/enabled/set", "OFF")
        except Exception as e:
            print("Licence limit check error:", e)
        time.sleep(30)


@app.route("/api/cameras")
def api_cameras():
    """Every camera and drone Frigate knows, with live status, for the multi-camera grid."""
    names = _frigate_camera_names()
    try:
        stats = requests.get(f"{FRIGATE_API_URL}/api/stats", timeout=3).json().get("cameras") or {}
    except Exception:
        stats = {}
    settings = load_local_settings()
    hidden = set(settings.get("hidden_feeds") or [])
    paused = set(settings.get("paused_sources") or [])
    items = []
    for name in names:
        fps = float((stats.get(name) or {}).get("camera_fps") or 0)
        items.append({"name": name, "kind": "drone" if _is_drone_name(name) else "camera",
                      "online": fps > 0, "fps": round(fps, 1),
                      "primary": name in (CAMERA_NAME, DRONE_CAMERA_NAME),
                      "feed_visible": name not in hidden, "paused": name in paused or name in over_limit_sources,
                      "over_limit": name in over_limit_sources})
    return jsonify({"ok": True, "main": CAMERA_NAME, "drone": DRONE_CAMERA_NAME, "cameras": items})


def _known_source_or_404(name):
    if name not in _frigate_camera_names():
        return jsonify({"ok": False, "error": "Unknown camera or drone."}), 404
    return None


@app.route("/api/sources/<name>/feed", methods=["POST"])
def api_source_feed(name):
    """Show or hide a live feed on the dashboard (display only; recording and AI continue)."""
    err = _known_source_or_404(name)
    if err:
        return err
    visible = bool((request.get_json(silent=True) or {}).get("visible"))
    hidden = set(load_local_settings().get("hidden_feeds") or [])
    (hidden.discard if visible else hidden.add)(name)
    save_local_settings({"hidden_feeds": sorted(hidden)})
    return jsonify({"ok": True, "name": name, "feed_visible": visible})


@app.route("/api/sources/<name>/pause", methods=["POST"])
def api_source_pause(name):
    """Stop or start Frigate's processing for an added camera/drone without removing it."""
    err = _known_source_or_404(name)
    if err:
        return err
    if name in (CAMERA_NAME, DRONE_CAMERA_NAME):
        return jsonify({"ok": False, "error": "Use the Camera AI / Drone AI switch for the main camera and drone."}), 400
    if not mqtt_connected or mqtt_client is None:
        return jsonify({"ok": False, "error": "MQTT is offline."}), 503
    paused = bool((request.get_json(silent=True) or {}).get("paused"))
    if not paused and name in _sources_over_limit():
        return jsonify({"ok": False, "error": "This source is beyond your licence limit. Remove another source or upgrade the licence."}), 403
    mqtt_client.publish(f"frigate/{name}/enabled/set", "OFF" if paused else "ON")
    current = set(load_local_settings().get("paused_sources") or [])
    (current.add if paused else current.discard)(name)
    save_local_settings({"paused_sources": sorted(current)})
    return jsonify({"ok": True, "name": name, "paused": paused})


@app.route("/api/sources/<name>", methods=["DELETE"])
def api_source_remove(name):
    """Remove an added camera/drone from Frigate and free its slot on the plan."""
    import shutil
    err = _known_source_or_404(name)
    if err:
        return err
    if name in (CAMERA_NAME, DRONE_CAMERA_NAME):
        return jsonify({"ok": False, "error": "The main camera and first drone can't be removed here."}), 400
    try:
        return _remove_source(name)
    except OSError as e:
        return jsonify({"ok": False, "error": f"Could not update the camera settings file ({e.strerror or e}). Wait a few seconds and try again."}), 409


def _remove_source(name):
    import shutil
    with open(LIVE_FRIGATE_CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    (cfg.get("cameras") or {}).pop(name, None)
    ((cfg.get("go2rtc") or {}).get("streams") or {}).pop(name, None)
    shutil.copyfile(LIVE_FRIGATE_CONFIG, LIVE_FRIGATE_CONFIG + ".before-remove-" + name)
    _save_frigate_config(cfg)
    settings = load_local_settings()
    save_local_settings({k: sorted(set(settings.get(k) or []) - {name}) for k in ("hidden_feeds", "paused_sources")})
    # Free the plan slot: drones are registered as "Drone N", cameras by their name.
    label = f"Drone {name[len(DRONE_CAMERA_NAME):]}" if _is_drone_name(name) else name
    cloud_note = ""
    sources = _cloud_source("GET").get("sources") or []
    match = next((s for s in sources if str(s.get("name", "")).lower() in (label.lower(), name.lower())), None)
    if match:
        if not _cloud_source("DELETE", {"id": match.get("id")}).get("ok"):
            cloud_note = " (could not free the plan slot in the cloud)"
    if _is_drone_name(name):  # forget that drone's phone link and pairing code
        _slots_cache["at"] = 0.0
        link = drone_links.get(name)
        if link and link["conn"] is not None:
            with link["lock"]:
                _drone_drop(link["conn"], "drone removed", name)
        drone_links.pop(name, None)
        try:
            os.remove(_token_file(name))
        except OSError:
            pass
    restarted, msg = _restart_frigate()
    return jsonify({"ok": True, "name": name, "frigate_restarted": restarted,
                    "message": f"{name} removed{cloud_note}."})


# ============================================================
# ADD-DEVICE WIZARD: brand presets, connection diagnosis, snapshot preview, drone QR
# ============================================================
# Main-stream RTSP paths per brand ({ch} = channel, 1 for a single camera; NVRs use 1..N).
CAMERA_BRANDS = {
    "hikvision": {"label": "Hikvision / HiLook / Annke", "user": "admin", "port": 554,
                  "paths": ["/Streaming/Channels/{ch}01"]},
    "dahua": {"label": "Dahua / Imou / Amcrest / Lorex", "user": "admin", "port": 554,
              "paths": ["/cam/realmonitor?channel={ch}&subtype=0"]},
    "reolink": {"label": "Reolink", "user": "admin", "port": 554,
                "paths": ["/h264Preview_{ch:02d}_main", "/Preview_{ch:02d}_main"]},
    "tapo": {"label": "TP-Link Tapo / VIGI", "user": "", "port": 554, "paths": ["/stream1"],
             "note": "Use the camera account from the Tapo app: Camera settings > Advanced > Camera account."},
    "uniview": {"label": "Uniview (UNV)", "user": "admin", "port": 554,
                "paths": ["/unicast/c{ch}/s0/live", "/media/video1"]},
    "ezviz": {"label": "EZVIZ", "user": "admin", "port": 554,
              "paths": ["/h264/ch{ch}/main/av_stream", "/Streaming/Channels/{ch}01"],
              "note": "The password is the 6-letter verification code on the camera label."},
    "axis": {"label": "Axis", "user": "root", "port": 554, "paths": ["/axis-media/media.amp"]},
    "hanwha": {"label": "Hanwha / Wisenet / Samsung", "user": "admin", "port": 554,
               "paths": ["/profile2/media.smp", "/profile1/media.smp"]},
    "other": {"label": "Other / not sure (try all)", "user": "admin", "port": 554, "paths": []},
}
# Words on a camera's web login page that identify the brand (used by the network scan).
_BRAND_HINTS = (("hikvision", ("hikvision", "doc/page/login.asp", "app-http")), ("dahua", ("dahua", "dhwebclient", "web service")),
                ("reolink", ("reolink",)), ("uniview", ("uniview", "unv")), ("axis", ("axis communications",)),
                ("hanwha", ("wisenet", "hanwha", "samsung techwin")), ("tapo", ("tapo", "tp-link")), ("ezviz", ("ezviz",)))


def _brand_paths(brand, channel):
    brands = [brand] if brand in CAMERA_BRANDS and brand != "other" else [b for b in CAMERA_BRANDS if b != "other"]
    paths = []
    for b in brands:
        for p in CAMERA_BRANDS[b]["paths"]:
            p = p.format(ch=channel)
            if p not in paths:
                paths.append(p)
    return paths


def _guess_brand(ip):
    try:
        r = requests.get(f"http://{ip}/", timeout=1.5, allow_redirects=True)
        text = (r.headers.get("Server", "") + " " + r.text[:4000]).lower()
    except Exception:
        return ""
    return next((b for b, words in _BRAND_HINTS if any(w in text for w in words)), "")


def _rtsp_describe(host, port, path, user, password, timeout=4):
    """Ask the camera for one stream (RTSP DESCRIBE). Returns the RTSP status code:
    200 = stream found, 401 = login refused, 404 = no such path. Raises OSError if unreachable."""
    import base64, hashlib
    url = f"rtsp://{host}:{port}{path}"

    def describe(auth=None):
        with socket.create_connection((host, int(port)), timeout=timeout) as s:
            s.settimeout(timeout)
            req = f"DESCRIBE {url} RTSP/1.0\r\nCSeq: {2 if auth else 1}\r\nAccept: application/sdp\r\nUser-Agent: AI-Security\r\n"
            if auth:
                req += f"Authorization: {auth}\r\n"
            s.sendall((req + "\r\n").encode())
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 65536:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1")
        m = re.match(r"RTSP/1\.\d\s+(\d{3})", head)
        return (int(m.group(1)) if m else 0), head

    code, head = describe()
    if code != 401 or not (user or password):
        return code
    challenges = [l.split(":", 1)[1].strip() for l in head.split("\r\n") if l.lower().startswith("www-authenticate:")]
    digest = next((c for c in challenges if c.lower().startswith("digest")), None)
    if digest:
        p = dict(re.findall(r'(\w+)="?([^",]*)"?', digest[6:]))
        realm, nonce = p.get("realm", ""), p.get("nonce", "")
        ha1 = hashlib.md5(f"{user}:{realm}:{password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"DESCRIBE:{url}".encode()).hexdigest()
        auth = f'Digest username="{user}", realm="{realm}", nonce="{nonce}", uri="{url}"'
        if "auth" in p.get("qop", ""):
            cnonce, nc = os.urandom(8).hex(), "00000001"
            auth += f', qop=auth, nc={nc}, cnonce="{cnonce}", response="' + \
                hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}".encode()).hexdigest() + '"'
        else:
            auth += ', response="' + hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest() + '"'
    else:
        auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    return describe(auth)[0]


def _snapshot(url):
    """One frame from the stream: (jpeg data URI, width, height, fps) or None."""
    import base64
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG,
                           [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000])
    try:
        ok, frame = cap.read()
        if not ok or frame is None or not getattr(frame, "size", 0):
            return None
        h, w = frame.shape[:2]
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
    finally:
        cap.release()
    preview = cv2.resize(frame, (640, max(1, int(h * 640 / w)))) if w > 640 else frame
    ok, jpg = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return ("data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()) if ok else "", w, h, round(fps if 0 < fps < 121 else 0)


def _probe_camera(data):
    """Find a working stream from brand + IP + login (or a full RTSP address) and explain failures."""
    from urllib.parse import quote, unquote, urlsplit
    full = str(data.get("rtsp_url") or "").strip()
    if full:
        if not full.lower().startswith(("rtsp://", "rtsps://")):
            return {"ok": False, "error": "The address must start with rtsp://"}
        u = urlsplit(full)
        ip, port = u.hostname or "", u.port or 554
        user, password = unquote(u.username or ""), unquote(u.password or "")
        paths = [(u.path or "/") + (("?" + u.query) if u.query else "")]
        brand, channel = "custom", 1
    else:
        ip = str(data.get("ip") or "").strip()
        brand = str(data.get("brand") or "other")
        port = int(data.get("port") or CAMERA_BRANDS.get(brand, {}).get("port") or 554)
        user, password = str(data.get("user") or ""), str(data.get("password") or "")
        channel = max(1, min(64, int(data.get("channel") or 1)))
        paths = _brand_paths(brand, channel)
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return {"ok": False, "error": "Enter the camera's IP address, for example 192.168.1.64."}
    if not _port(ip, port, 1.5):
        if any(_port(ip, p, 1.0) for p in (80, 443, 8000)):
            return {"ok": False, "kind": "rtsp_closed",
                    "error": f"The device at {ip} is online, but its RTSP port {port} is closed. "
                             "Turn on RTSP in the camera's settings, or check the port number."}
        return {"ok": False, "kind": "unreachable",
                "error": f"No device answers at {ip}. Check the IP address, the cable / Wi-Fi, "
                         "and that the camera is on the same network as this PC."}
    login_refused = False
    for path in paths:
        try:
            code = _rtsp_describe(ip, port, path, user, password)
        except OSError:
            continue
        if code == 401:
            login_refused = True
            break  # cameras check the login before the path, so other paths won't help
        if code != 200:
            continue
        url = f"rtsp://{quote(user, safe='')}:{quote(password, safe='')}@{ip}:{port}{path}" if (user or password) \
            else f"rtsp://{ip}:{port}{path}"
        shot = _snapshot(url)
        if not shot:
            return {"ok": False, "kind": "no_video",
                    "error": "The camera accepted the login but sent no video. Set its video codec to H.264 "
                             "(or H.265) in the camera's settings and try again."}
        image, w, h, fps = shot
        if brand == "other":
            brand = next((b for b in CAMERA_BRANDS if b != "other" and path in _brand_paths(b, channel)), "other")
        return {"ok": True, "rtsp_url": url, "brand": brand, "path": path, "snapshot": image,
                "width": w, "height": h, "fps": fps,
                "message": f"Camera connected: {w}×{h}" + (f" at {fps} fps" if fps else "") + "."}
    if login_refused:
        return {"ok": False, "kind": "auth", "error": "The camera refused the username or password. "
                "Check them (they are the camera's own login, not your Wi-Fi password)."}
    return {"ok": False, "kind": "path",
            "error": "The camera answered but none of the stream addresses for this brand worked. "
                     "Pick the exact brand, or use “Enter full RTSP address”."}


# ---------- whole recorder (NVR/DVR) in one step ----------
# Lower-resolution "sub" streams per brand, for recorders with many channels (less CPU; faces/plates
# are read best from the main stream).
SUB_STREAM_PATHS = {"hikvision": "/Streaming/Channels/{ch}02", "dahua": "/cam/realmonitor?channel={ch}&subtype=1",
                    "reolink": "/h264Preview_{ch:02d}_sub", "uniview": "/unicast/c{ch}/s1/live",
                    "ezviz": "/h264/ch{ch}/sub/av_stream", "tapo": "/stream2"}
RECORDER_MAX_CHANNELS = 64


def _recorder_api(ip, user, password, http_port=80):
    """Ask the recorder itself (Hikvision ISAPI / Dahua CGI) for brand, model and channel names.
    Only a successful answer counts; a refused login is left to the RTSP check, which reports it reliably."""
    from requests.auth import HTTPDigestAuth, HTTPBasicAuth
    base = f"http://{ip}:{http_port}"
    for auth in (HTTPDigestAuth(user, password), HTTPBasicAuth(user, password)):
        try:
            r = requests.get(base + "/ISAPI/System/deviceInfo", auth=auth, timeout=4)
            if r.status_code == 200 and "<DeviceInfo" in r.text:
                model = (re.search(r"<model>([^<]*)</model>", r.text) or re.search(r"<deviceName>([^<]*)</deviceName>", r.text))
                chans = []
                for path in ("/ISAPI/ContentMgmt/InputProxy/channels", "/ISAPI/System/Video/inputs/channels"):
                    c = requests.get(base + path, auth=auth, timeout=6)
                    if c.status_code == 200:
                        for block in re.findall(r"<(?:InputProxyChannel|VideoInputChannel)>(.*?)</(?:InputProxyChannel|VideoInputChannel)>", c.text, re.S):
                            cid = re.search(r"<id>(\d+)</id>", block)
                            name = re.search(r"<name>([^<]*)</name>", block)
                            if cid and int(cid.group(1)) not in [x["ch"] for x in chans]:
                                chans.append({"ch": int(cid.group(1)), "name": (name.group(1).strip() if name else "")})
                return {"brand": "hikvision", "model": model.group(1) if model else "Hikvision recorder", "channels": sorted(chans, key=lambda x: x["ch"]), }
        except requests.RequestException:
            break
    for auth in (HTTPDigestAuth(user, password), HTTPBasicAuth(user, password)):
        try:
            r = requests.get(base + "/cgi-bin/magicBox.cgi?action=getDeviceType", auth=auth, timeout=4)
            if r.status_code == 200 and "type=" in r.text:
                model = r.text.split("=", 1)[1].strip()
                chans = []
                t = requests.get(base + "/cgi-bin/configManager.cgi?action=getConfig&name=ChannelTitle", auth=auth, timeout=6)
                if t.status_code == 200:
                    for idx, name in re.findall(r"table\.ChannelTitle\[(\d+)\]\.Name=([^\r\n]*)", t.text):
                        chans.append({"ch": int(idx) + 1, "name": name.strip()})
                return {"brand": "dahua", "model": model or "Dahua recorder", "channels": chans, }
        except requests.RequestException:
            break
    return None


def _channel_url(brand, ip, port, user, password, ch, sub=False):
    from urllib.parse import quote
    path = (SUB_STREAM_PATHS.get(brand) if sub else None) or CAMERA_BRANDS[brand]["paths"][0]
    cred = f"{quote(user, safe='')}:{quote(password, safe='')}@" if (user or password) else ""
    return f"rtsp://{cred}{ip}:{port}{path.format(ch=ch)}", path.format(ch=ch)


def _thumb(url):
    shot = _snapshot(url)
    if not shot:
        return None
    image, w, h, fps = shot
    return {"snapshot": image, "width": w, "height": h, "fps": fps}


def scan_recorder(data):
    ip = str(data.get("ip") or "").strip()
    user, password = str(data.get("user") or ""), str(data.get("password") or "")
    rtsp_port = int(data.get("port") or 554)
    sub = bool(data.get("sub_stream"))
    brand = str(data.get("brand") or "other")
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return {"ok": False, "error": "Enter the recorder's IP address, for example 192.168.1.100."}
    if not _port(ip, rtsp_port, 1.5):
        if any(_port(ip, p, 1.0) for p in (80, 443, 8000, 37777)):
            return {"ok": False, "error": f"The recorder at {ip} is online but its RTSP port {rtsp_port} is closed. Turn on RTSP in the recorder's network settings."}
        return {"ok": False, "error": f"No device answers at {ip}. Check the IP address and that the recorder is on the same network."}

    api = _recorder_api(ip, user, password) if brand in ("other", "hikvision", "dahua") else None
    if api:
        brand = api["brand"]
    model = (api or {}).get("model") or ""
    channels = (api or {}).get("channels") or []

    if brand == "other":
        # Unknown brand: find which brand's stream address the recorder answers on channel 1.
        for b in [b for b in CAMERA_BRANDS if b != "other"]:
            try:
                code = _rtsp_describe(ip, rtsp_port, CAMERA_BRANDS[b]["paths"][0].format(ch=1), user, password)
            except OSError:
                continue
            if code == 401:
                return {"ok": False, "error": "The recorder refused the username or password."}
            if code == 200:
                brand = b
                break
        if brand == "other":
            return {"ok": False, "error": "Could not recognise this recorder. Choose its brand, or add cameras one by one with their RTSP address."}
    if brand not in CAMERA_BRANDS or not CAMERA_BRANDS[brand]["paths"]:
        return {"ok": False, "error": "This brand cannot be scanned as a recorder; add its cameras one by one."}

    if not channels:  # no API: try channel numbers until several in a row are missing
        misses = 0
        # Brands whose stream address has no channel number are single cameras, not recorders.
        last = RECORDER_MAX_CHANNELS if "{ch" in CAMERA_BRANDS[brand]["paths"][0] else 1
        for ch in range(1, last + 1):
            try:
                code = _rtsp_describe(ip, rtsp_port, _channel_url(brand, ip, rtsp_port, user, password, ch, sub)[1], user, password, timeout=3)
            except OSError:
                code = 0
            if code == 401:
                return {"ok": False, "error": "The recorder refused the username or password."}
            if code == 200:
                channels.append({"ch": ch, "name": ""})
                misses = 0
            else:
                misses += 1
                if misses >= 4 and ch >= 4:
                    break

    def probe(c):
        url, path = _channel_url(brand, ip, rtsp_port, user, password, c["ch"], sub)
        info = _thumb(url)
        return {"ch": c["ch"], "name": c["name"] or f"Camera {c['ch']}", "rtsp_url": url, "online": bool(info), **(info or {})}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        found = list(ex.map(probe, channels[:RECORDER_MAX_CHANNELS]))
    allowed = requests.get("http://127.0.0.1:%d/api/cloud/can-add-source/camera" % PORT, timeout=4).json()
    limit, used = allowed.get("limit"), int(allowed.get("used") or 0)
    return {"ok": True, "brand": brand, "brand_label": CAMERA_BRANDS[brand]["label"], "model": model, "channels": found,
            "existing": _frigate_camera_names(), "can_add": None if limit is None else max(0, int(limit) - used)}


def add_cameras_batch(cameras):
    """Add several cameras with a single Frigate restart. Returns (added, errors)."""
    global CAMERA_NAME, STREAM, CAMERA_STATE_TOPIC, CAMERA_SET_TOPIC
    added, errors = [], []
    existing = set(_frigate_camera_names())
    for cam in cameras:
        display = str(cam.get("name") or "Camera").strip()[:80]
        url = str(cam.get("rtsp_url") or "").strip()
        if not url.lower().startswith(("rtsp://", "rtsps://")):
            errors.append(f"{display}: invalid address"); continue
        allowed = requests.get("http://127.0.0.1:%d/api/cloud/can-add-source/camera" % PORT, timeout=4).json()
        if not allowed.get("allowed"):
            errors.append(f"{display}: {allowed.get('message') or 'licence limit reached'}"); break
        slug = _safe_camera_slug(display)
        if _is_drone_name(slug):
            slug = "cam_" + slug
        base, n = slug, 2
        while slug in existing:
            slug = f"{base}_{n}"[:40]; n += 1
        cloud = _cloud_source("POST", {"source_type": "camera", "name": display})
        if not cloud.get("ok"):
            errors.append(f"{display}: {cloud.get('error') or 'registration failed'}"); continue
        try:
            is_first = CAMERA_NAME not in existing
            _write_managed_frigate(slug, url)
            existing.add(slug)
            if is_first:
                settings = load_local_settings()
                settings.update({"camera_name": slug, "camera_stream": f"rtsp://localhost:8554/{slug}", "camera_display_name": display})
                tmp = LOCAL_SETTINGS_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(settings, f, indent=2)
                os.replace(tmp, LOCAL_SETTINGS_FILE)
                CAMERA_NAME = slug; STREAM = f"rtsp://localhost:8554/{slug}"
                CAMERA_STATE_TOPIC = f"frigate/{slug}/enabled/state"; CAMERA_SET_TOPIC = f"frigate/{slug}/enabled/set"
            added.append({"name": display, "camera_name": slug})
        except Exception as e:
            sid = ((cloud.get("source") or {}).get("id"))
            if sid:
                _cloud_source("DELETE", {"id": sid})
            errors.append(f"{display}: {e}")
    restarted = _restart_frigate()[0] if added else False
    return added, errors, restarted


@app.route("/api/setup/recorder/scan", methods=["POST"])
def api_setup_recorder_scan():
    try:
        result = scan_recorder(request.get_json(silent=True) or {})
    except Exception as e:
        result = {"ok": False, "error": f"Scan failed: {e}"}
    return jsonify(result), (200 if result.get("ok") else 400)


@app.route("/api/setup/recorder/add", methods=["POST"])
def api_setup_recorder_add():
    cams = (request.get_json(silent=True) or {}).get("cameras") or []
    if not isinstance(cams, list) or not cams:
        return jsonify({"ok": False, "error": "Choose at least one camera."}), 400
    added, errors, restarted = add_cameras_batch(cams[:RECORDER_MAX_CHANNELS])
    msg = f"{len(added)} camera(s) added" + (". Video processing restarted." if restarted else ".")
    return jsonify({"ok": bool(added), "added": added, "errors": errors, "message": msg + ((" Not added: " + "; ".join(errors)) if errors else "")}), (200 if added else 409)


@app.route("/api/setup/brands")
def api_setup_brands():
    return jsonify({"ok": True, "brands": [{"id": k, "label": v["label"], "user": v["user"], "port": v["port"],
                                            "note": v.get("note", "")} for k, v in CAMERA_BRANDS.items()]})


@app.route("/api/setup/camera/probe", methods=["POST"])
def api_setup_camera_probe():
    try:
        result = _probe_camera(request.get_json(silent=True) or {})
    except Exception as e:
        result = {"ok": False, "error": f"Camera test failed: {e}"}
    return jsonify(result), (200 if result.get("ok") else 400)


@app.route("/api/setup/scan", methods=["POST"])
def api_setup_scan():
    """Network scan for the wizard: camera candidates first, with a brand guess."""
    resp = discovery_scan()
    data = (resp[0] if isinstance(resp, tuple) else resp).get_json()
    cams = [d for d in data.get("devices") or [] if 554 in (d.get("ports") or []) or d.get("kind") == "known_camera"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        for d, brand in zip(cams, ex.map(lambda d: _guess_brand(d["ip"]), cams)):
            d["brand"] = brand
    data["cameras"] = cams
    return jsonify(data)


def _qr_svg(text):
    try:
        import segno
        return segno.make(text, error="m").svg_inline(scale=4, dark="#02131d", light="#ffffff", border=2)
    except Exception:
        return ""


@app.route("/api/setup/drones")
def api_setup_drones():
    """Every drone slot with its DJI Fly RTMP address (and QR code) and live status."""
    host = _lan_ip()
    try:
        stats = requests.get(f"{FRIGATE_API_URL}/api/stats", timeout=3).json().get("cameras") or {}
    except Exception:
        stats = {}
    drones = []
    for name in _frigate_camera_names():
        if not _is_drone_name(name):
            continue
        url = f"rtmp://{host}:1935/{name}"
        drones.append({"name": name, "publish_url": url, "qr": _qr_svg(url), "primary": name == DRONE_CAMERA_NAME,
                       "online": float((stats.get(name) or {}).get("camera_fps") or 0) > 0})
    return jsonify({"ok": True, "host_ip": host, "receiver_ready": _port("127.0.0.1", 1935, .3), "drones": drones})


@app.route("/setup/add")
def setup_add_page():
    return DEVICE_WIZARD_PAGE


DEVICE_WIZARD_PAGE = hud_page("Devices", r"""
<style>
.wz-tabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.wz-tab{flex:1;min-width:200px;text-align:left;padding:14px 16px;cursor:pointer;background:#04111b;border:1px solid #0a5480;border-radius:6px;color:#a8c7d7;font-family:inherit}
.wz-tab b{display:block;color:#5bd9ff;font-size:14px;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:4px}
.wz-tab span{font-size:12px;color:#6d8b9d}
.wz-tab.on{border-color:#36cfff;box-shadow:0 0 16px rgba(54,207,255,.18);background:rgba(18,151,215,.08)}
.wz-steps{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap}
.wz-steps i{font-style:normal;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:#4d6b7c;padding:6px 10px;border:1px solid #123447;border-radius:12px}
.wz-steps i.on{color:#02131d;background:#25c7ff;border-color:#45d0ff}
.wz-steps i.done{color:#2aea88;border-color:#1f7a50}
.wz-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}
.wz-grid .full{grid-column:1/-1}
.wz-found{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px;margin-top:12px}
.wz-found button{text-align:left;padding:10px 12px;cursor:pointer;background:#05131d;border:1px solid #153c56;border-radius:5px;color:#d9efff;font-family:inherit}
.wz-found button:hover{border-color:#36cfff}
.wz-found small{display:block;color:#6d8b9d;font-size:11px;margin-top:3px}
.wz-shot{width:100%;max-width:520px;border:1px solid #155879;border-radius:5px;display:block;margin-top:12px;background:#000}
.wz-link{background:none;border:0;color:#5bd9ff;cursor:pointer;font-family:inherit;font-size:12px;padding:0;margin-top:12px;text-decoration:underline}
.wz-drone{display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:center;padding:14px;background:#05131d;border:1px solid #153c56;border-radius:5px;margin-bottom:10px}
.wz-drone .qr{width:132px;height:132px;background:#fff;border-radius:4px;display:flex;align-items:center;justify-content:center}
.wz-drone .qr svg{width:124px;height:124px}
.wz-hidden{display:none}
.rec-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.rec-cam{background:#05131d;border:1px solid #153c56;border-radius:6px;overflow:hidden}
.rec-cam.on{border-color:#2aea88}
.rec-cam img,.rec-cam .nopic{width:100%;aspect-ratio:16/9;object-fit:cover;display:block;background:#000}
.rec-cam .nopic{display:flex;align-items:center;justify-content:center;color:#6d8b9d;font-size:12px}
.rec-cam .rc-body{padding:8px 10px}
.rec-cam input[type=text]{padding:7px 9px;font-size:13px;margin-top:6px}
.rec-cam label{margin:0;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;font-size:12px;color:#d9efff}
@media(max-width:640px){.wz-grid{grid-template-columns:1fr}.wz-drone{grid-template-columns:1fr}}
</style>
<main class="hud-main narrow">
<div class="page-head"><div><div class="page-kicker">Devices</div><h1 class="page-title">Add a camera or drone</h1>
<div class="page-sub">Pick the brand, enter the IP and login. The system finds the stream, shows a live snapshot, and adds it. Nothing is changed until you confirm.</div></div>
<div id="usage" class="muted"></div></div>

<div class="wz-tabs">
<button class="wz-tab on" id="tabCam" onclick="mode('cam')"><b>▣ Camera</b><span>IP / CCTV camera or NVR channel</span></button>
<button class="wz-tab" id="tabRec" onclick="mode('rec')"><b>📼 Recorder</b><span>Whole NVR / DVR in one step</span></button>
<button class="wz-tab" id="tabDrone" onclick="mode('drone')"><b>✈ Drone</b><span>DJI live stream over RTMP</span></button>
</div>

<section class="panel" id="camPanel"><div class="panel-head"><div class="panel-title">▣ New camera</div><div class="live">RTSP</div></div>
<div class="panel-body">
<div class="wz-steps"><i id="st1" class="on">1 · Find</i><i id="st2">2 · Connect</i><i id="st3">3 · Check</i><i id="st4">4 · Add</i></div>

<div id="step1">
<div class="actions"><button class="hud-btn primary" id="scanBtn" onclick="scan()">Scan network for cameras</button>
<button class="hud-btn" onclick="go(2)">I know the IP address</button></div>
<div id="scanMsg" class="muted" style="margin-top:12px"></div>
<div id="found" class="wz-found"></div>
</div>

<div id="step2" class="wz-hidden">
<div id="simple" class="wz-grid">
<div class="full"><label for="brand">Brand</label><select id="brand" onchange="brandChanged()"></select><div id="note" class="muted" style="margin-top:6px"></div></div>
<div><label for="ip">IP address</label><input id="ip" placeholder="192.168.1.64" autocomplete="off"></div>
<div><label for="channel">Channel <span class="muted" style="text-transform:none;letter-spacing:0">(1 for a single camera; NVR = camera number)</span></label><input id="channel" type="number" min="1" max="64" value="1"></div>
<div><label for="user">Username</label><input id="user" autocomplete="off"></div>
<div><label for="pass">Password</label><input id="pass" type="password" autocomplete="new-password"></div>
<div><label for="port">RTSP port</label><input id="port" type="number" value="554"></div>
</div>
<div id="manual" class="wz-hidden"><label for="rtsp">Full RTSP address</label><input id="rtsp" type="password" placeholder="rtsp://username:password@192.168.1.50:554/stream1" autocomplete="off"></div>
<button class="wz-link" id="manualLink" onclick="toggleManual()">Enter full RTSP address instead</button>
<div class="muted" style="margin-top:10px">The login stays on this PC; it is never sent to the cloud.</div>
<div class="actions" style="margin-top:16px"><button class="hud-btn" onclick="go(1)">Back</button><button class="hud-btn primary" id="testBtn" onclick="probe()">Connect &amp; test</button></div>
<div id="m2" class="hud-msg"></div>
</div>

<div id="step3" class="wz-hidden">
<img id="shot" class="wz-shot" alt="Camera snapshot">
<div id="m3" class="hud-msg ok"></div>
<label for="cname">Camera name</label><input id="cname" placeholder="Front Gate" maxlength="40">
<div class="actions" style="margin-top:16px"><button class="hud-btn" onclick="go(2)">Back</button><button class="hud-btn primary" id="addBtn" onclick="addCam()">Add camera</button></div>
<div id="m3b" class="hud-msg"></div>
</div>

<div id="step4" class="wz-hidden">
<div id="m4" class="hud-msg"></div>
<div class="actions" style="margin-top:16px"><button class="hud-btn primary" onclick="location.href='/'">Open dashboard</button><button class="hud-btn" onclick="reset()">Add another camera</button></div>
</div>
</div></section>

<section class="panel wz-hidden" id="recPanel"><div class="panel-head"><div class="panel-title">📼 Add a whole recorder</div><div class="live">NVR / DVR</div></div>
<div class="panel-body">
<div class="muted">Enter the recorder's address and login. The system recognises the brand, finds every camera channel with its name and a live picture, and you choose which to add.</div>
<div class="wz-grid" style="margin-top:6px">
<div class="full"><label for="recBrand">Brand</label><select id="recBrand"></select></div>
<div><label for="recIp">Recorder IP address</label><input id="recIp" placeholder="192.168.1.100" autocomplete="off"></div>
<div><label for="recPort">RTSP port</label><input id="recPort" type="number" value="554"></div>
<div><label for="recUser">Username</label><input id="recUser" value="admin" autocomplete="off"></div>
<div><label for="recPass">Password</label><input id="recPass" type="password" autocomplete="new-password"></div>
<div class="full"><label style="display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;font-size:13px"><input type="checkbox" id="recSub"> Use lighter sub-streams (recommended for 8+ cameras; faces and plates are read best without it)</label></div>
</div>
<div class="actions" style="margin-top:14px"><button class="hud-btn primary" id="recScanBtn" onclick="recScan()">Find cameras</button></div>
<div id="recMsg" class="hud-msg"></div>
<div id="recResult" class="wz-hidden" style="margin-top:14px">
<div class="muted" id="recInfo"></div>
<div class="actions" style="margin:10px 0"><button class="hud-btn" onclick="recSelect(true)">Select all with video</button><button class="hud-btn" onclick="recSelect(false)">Select none</button></div>
<div id="recList" class="rec-grid"></div>
<div class="actions" style="margin-top:14px"><button class="hud-btn primary" id="recAddBtn" onclick="recAdd()">Add selected</button></div>
<div id="recMsg2" class="hud-msg"></div>
</div>
</div></section>

<section class="panel wz-hidden" id="dronePanel"><div class="panel-head"><div class="panel-title">✈ Drones</div><div class="live" id="recv"></div></div>
<div class="panel-body">
<div class="muted">In DJI Fly: tap <b>•••</b> &gt; <b>Transmission</b> &gt; <b>Live Streaming Platforms</b> &gt; <b>RTMP</b>, then type the address below (or scan the QR code with the phone and copy it). The phone/controller must be on the same Wi-Fi as this PC.</div>
<div id="drones" style="margin-top:14px"></div>
<div class="actions" style="margin-top:6px"><button class="hud-btn primary" id="droneBtn" onclick="addDrone()">Add another drone</button></div>
<div id="md" class="hud-msg"></div>
</div></section>
</main>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const msg=(id,t,cls)=>{const e=$(id);e.className='hud-msg '+(cls||'');e.textContent=t};
let brands=[],manual=false,found=null,dronePoll=null;
function mode(m){$('tabCam').classList.toggle('on',m==='cam');$('tabDrone').classList.toggle('on',m==='drone');$('tabRec').classList.toggle('on',m==='rec');
  $('camPanel').classList.toggle('wz-hidden',m!=='cam');$('dronePanel').classList.toggle('wz-hidden',m!=='drone');$('recPanel').classList.toggle('wz-hidden',m!=='rec');
  clearInterval(dronePoll);if(m==='drone'){loadDrones();dronePoll=setInterval(loadDrones,5000)}history.replaceState(null,'',m==='drone'?'#drone':m==='rec'?'#recorder':'#camera')}
function go(n){for(let i=1;i<=4;i++){$('step'+i).classList.toggle('wz-hidden',i!==n);$('st'+i).className=i===n?'on':(i<n?'done':'')}}
function brandChanged(){const b=brands.find(x=>x.id===$('brand').value)||{};$('note').textContent=b.note||'';if(!$('user').dataset.touched)$('user').value=b.user||'';$('port').value=b.port||554}
function toggleManual(){manual=!manual;$('simple').classList.toggle('wz-hidden',manual);$('manual').classList.toggle('wz-hidden',!manual);$('manualLink').textContent=manual?'Use brand + IP instead':'Enter full RTSP address instead'}
async function usage(){try{const [c,d]=await Promise.all(['camera','drone'].map(k=>fetch('/api/cloud/can-add-source/'+k).then(r=>r.json())));
  const f=x=>x.limit==null?x.used+' used':x.used+' of '+x.limit;$('usage').innerHTML='Cameras: <b>'+esc(f(c))+'</b> · Drones: <b>'+esc(f(d))+'</b>';
  if(!c.allowed){$('scanBtn').disabled=true;$('testBtn').disabled=true;msg('m2',c.message,'bad');$('scanMsg').textContent=c.message}
  $('droneBtn').disabled=!d.allowed;if(!d.allowed)msg('md',d.message,'bad')}catch(e){}}
async function scan(){$('scanBtn').disabled=true;$('found').innerHTML='';$('scanMsg').textContent='Scanning the local network… (up to 30 seconds)';
  try{const d=await fetch('/api/setup/scan',{method:'POST'}).then(r=>r.json());const cams=d.cameras||[];
    $('scanMsg').textContent=cams.length?`Found ${cams.length} camera(s) on ${d.network}. Click one to use it.`:`No cameras found on ${d.network||'the network'}. Check the camera is powered and on the same network, or enter the IP yourself.`;
    $('found').innerHTML=cams.map((c,i)=>`<button onclick="pick(${i})"><b>${esc(c.ip)}</b><small>${esc(c.camera_name?'Already added: '+c.camera_name:(brands.find(b=>b.id===c.brand)||{}).label||'Unknown brand')}</small></button>`).join('');found=cams}
  catch(e){$('scanMsg').textContent='Scan failed. Enter the IP address yourself.'}finally{$('scanBtn').disabled=false}}
function pick(i){const c=found[i];$('ip').value=c.ip;$('brand').value=c.brand||'other';brandChanged();go(2);$('pass').focus()}
let probed=null;
async function probe(){const body=manual?{rtsp_url:$('rtsp').value.trim()}:{brand:$('brand').value,ip:$('ip').value.trim(),port:$('port').value,channel:$('channel').value,user:$('user').value,password:$('pass').value};
  $('testBtn').disabled=true;msg('m2','Connecting to the camera… (up to 20 seconds)');
  try{const d=await fetch('/api/setup/camera/probe',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
    if(!d.ok){msg('m2',d.error||'Could not connect.','bad');return}
    probed=d;$('shot').src=d.snapshot;$('m3').textContent=d.message;$('m3b').className='hud-msg';$('m3b').textContent='';
    if(!$('cname').value)$('cname').value='Camera '+(($('ip').value||'').split('.').pop()||'');go(3);$('cname').focus();$('cname').select()}
  catch(e){msg('m2','Could not reach the system: '+e.message,'bad')}finally{$('testBtn').disabled=false}}
async function addCam(){const name=$('cname').value.trim();if(!name){msg('m3b','Give the camera a name.','bad');return}
  $('addBtn').disabled=true;msg('m3b','Adding the camera and restarting video processing…');
  try{const r=await fetch('/api/setup/camera',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name,rtsp_url:probed.rtsp_url})});const d=await r.json();
    if(!r.ok||!d.ok){msg('m3b',d.error||'Could not add the camera.','bad');return}
    go(4);msg('m4','“'+name+'” added. Waiting for its live video… (about 20–40 seconds)');waitLive(d.camera_name,name)}
  catch(e){msg('m3b','Could not reach the system: '+e.message,'bad')}finally{$('addBtn').disabled=false}}
async function waitLive(slug,name){for(let i=0;i<45;i++){await new Promise(r=>setTimeout(r,2000));
  try{const d=await fetch('/api/cameras').then(r=>r.json());const c=(d.cameras||[]).find(x=>x.name===slug);
    if(c&&c.online){msg('m4','✓ “'+name+'” is live ('+c.fps+' fps) with face and plate recognition. It now appears on the dashboard.','ok');usage();return}}catch(e){}}
  msg('m4','“'+name+'” was added, but its video has not started yet. Give it a minute, then check the dashboard.','bad')}
function reset(){probed=null;['ip','pass','rtsp','cname'].forEach(k=>$(k).value='');$('channel').value=1;go(1);usage()}
async function loadDrones(){try{const d=await fetch('/api/setup/drones').then(r=>r.json());
  $('recv').innerHTML=d.receiver_ready?'<i class="dot good"></i>RECEIVER READY':'<i class="dot bad"></i>RECEIVER OFF';
  $('drones').innerHTML=(d.drones||[]).map(x=>`<div class="wz-drone"><div class="qr">${x.qr||''}</div><div><b style="color:#5bd9ff;letter-spacing:1px;text-transform:uppercase">${esc(x.name)}</b>
  <span class="state" style="margin-left:10px">${x.online?'<i class="dot good"></i>LIVE':'<i class="dot warn"></i>WAITING FOR STREAM'}</span>
  <label>RTMP address for DJI Fly</label><code>${esc(x.publish_url)}</code> <button class="hud-btn" style="min-height:28px;margin-left:6px" onclick="navigator.clipboard.writeText('${esc(x.publish_url)}')">Copy</button></div></div>`).join('')||'<p class="muted">No drone slot yet. Click “Add another drone”.</p>'}catch(e){}}
async function addDrone(){$('droneBtn').disabled=true;msg('md','Adding a drone slot…');
  try{const r=await fetch('/api/setup/drone',{method:'POST'});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Could not add the drone');
    msg('md',d.message,'ok');loadDrones()}catch(e){msg('md',e.message,'bad')}finally{usage()}}
let recFound=[],recCanAdd=null;
async function recScan(){const body={brand:$('recBrand').value,ip:$('recIp').value.trim(),port:$('recPort').value,user:$('recUser').value,password:$('recPass').value,sub_stream:$('recSub').checked};
  $('recScanBtn').disabled=true;$('recResult').classList.add('wz-hidden');msg('recMsg','Looking for the recorder and its cameras… (up to a minute)');
  try{const d=await fetch('/api/setup/recorder/scan',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
    if(!d.ok){msg('recMsg',d.error||'Scan failed.','bad');return}
    recFound=d.channels||[];recCanAdd=d.can_add;const live=recFound.filter(c=>c.online).length;
    msg('recMsg',`Found ${d.brand_label}${d.model?' ('+d.model+')':''}: ${recFound.length} channel(s), ${live} with video.`,'ok');
    $('recInfo').textContent=recCanAdd==null?'Your licence has no camera limit.':`Your licence allows ${recCanAdd} more camera${recCanAdd===1?'':'s'}.`;
    $('recList').innerHTML=recFound.map((c,i)=>`<div class="rec-cam${c.online?' on':''}">${c.snapshot?`<img src="${c.snapshot}" alt="">`:'<div class="nopic">No video on this channel</div>'}
      <div class="rc-body"><label><input type="checkbox" id="rc${i}" ${c.online?'checked':''} onchange="recCount()"> Channel ${c.ch}${c.width?` · ${c.width}×${c.height}`:''}</label>
      <input type="text" id="rn${i}" value="${esc(c.name)}" maxlength="40"></div></div>`).join('')||'<p class="muted">No channels found.</p>';
    $('recResult').classList.remove('wz-hidden');recCount()}
  catch(e){msg('recMsg','Could not reach the system: '+e.message,'bad')}finally{$('recScanBtn').disabled=false}}
function recSelect(on){recFound.forEach((c,i)=>{$('rc'+i).checked=on&&c.online});recCount()}
function recCount(){const n=recFound.filter((c,i)=>$('rc'+i).checked).length;$('recAddBtn').textContent=`Add selected (${n})`;
  if(recCanAdd!=null&&n>recCanAdd)msg('recMsg2',`You selected ${n}, but the licence allows ${recCanAdd} more. Only the first ${recCanAdd} will be added.`,'bad');else $('recMsg2').textContent=''}
async function recAdd(){const cams=recFound.map((c,i)=>({sel:$('rc'+i).checked,name:$('rn'+i).value.trim()||('Camera '+c.ch),rtsp_url:c.rtsp_url})).filter(c=>c.sel);
  if(!cams.length){msg('recMsg2','Select at least one camera.','bad');return}
  $('recAddBtn').disabled=true;msg('recMsg2',`Adding ${cams.length} camera(s) and restarting video processing once…`);
  try{const r=await fetch('/api/setup/recorder/add',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({cameras:cams})});const d=await r.json();
    msg('recMsg2',(d.message||d.error)+(d.ok?' They appear on the dashboard within about a minute.':''),d.ok?'ok':'bad');usage()}
  catch(e){msg('recMsg2','Could not reach the system: '+e.message,'bad')}finally{$('recAddBtn').disabled=false}}
fetch('/api/setup/brands').then(r=>r.json()).then(d=>{brands=d.brands||[];
  $('recBrand').innerHTML=brands.filter(b=>['other','hikvision','dahua','reolink','uniview','ezviz'].includes(b.id)).map(b=>`<option value="${b.id}">${b.id==='other'?'Not sure: detect automatically':esc(b.label)}</option>`).join('');$('brand').innerHTML=brands.map(b=>`<option value="${b.id}">${esc(b.label)}</option>`).join('');$('brand').value='other';brandChanged()});
$('user').addEventListener('input',()=>$('user').dataset.touched=1);
usage();mode(location.hash==='#drone'?'drone':location.hash==='#recorder'?'rec':'cam');
</script>""", active="devices")


# ============================================================
# DRONE LINK: fly the drone from this PC through the "Drone Link" phone app
# ============================================================
# The phone (DJI MSDK app on the RC-N1/N2) connects to this PC over the LAN (TCP, one JSON
# message per line), proves it knows the pairing token (HMAC of a random challenge), then
# streams telemetry and carries out commands. The dashboard itself stays localhost-only.
#   PC -> phone: challenge, welcome, ping (heartbeat), cmd {id, cmd, args}, stick {x,y,z,r}
#   phone -> PC: hello {mac}, tel {...}, ack {id, ok, error}, event {msg}
# Safety: the phone zeroes the sticks when no stick update arrives for 0.5 s and releases
# control when the heartbeat stops for 1.5 s; the pilot's RC can always take control back.
DRONE_LINK_PORT = int(os.environ.get("AI_SECURITY_DRONE_LINK_PORT", "8765"))
DRONE_LINK_TOKEN_FILE = os.path.join(os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER), "drone_link_token")
DRONE_STICK_TIMEOUT = 0.4    # browser stopped sending sticks -> send zero sticks (hover)
DRONE_LIMITS = {"max_altitude_m": 120, "max_distance_m": 500, "max_speed_level": 0.5}
DRONE_COMMANDS = {"takeoff", "land", "cancel_land", "confirm_land", "goto", "goto_cancel", "go_home", "cancel_go_home", "hover",
                  "control_on", "control_off", "gimbal", "photo", "record_start", "record_stop",
                  "sim_on", "sim_off", "stream_on", "stream_off"}
def _new_link():
    return {"conn": None, "lock": threading.Lock(), "telemetry": {}, "tel_at": 0.0, "device": "",
            "connected_at": 0.0, "events": [], "acks": {}, "next_id": 1, "stick_at": 0.0,
            "stick_active": False, "error": ""}


# One link per drone slot (drone, drone2, …: the drone cameras in Frigate, up to the licence).
# Each slot has its own phone, pairing code, telemetry and video path rtmp://PC:1935/<slot>.
drone_links = {DRONE_CAMERA_NAME: _new_link()}
drone_link = drone_links[DRONE_CAMERA_NAME]  # the first drone
drone_ack_cond = threading.Condition()


_slots_cache = {"at": 0.0, "slots": [DRONE_CAMERA_NAME]}


def drone_slots():
    """Drone slots in order (first drone first); always at least the first one."""
    if time.time() - _slots_cache["at"] > 5:  # sticks call this 10x per second; the config rarely changes
        names = {n for n in _frigate_camera_names() if _is_drone_name(n)} | {DRONE_CAMERA_NAME} | set(virtual_drones)
        _slots_cache.update(at=time.time(), slots=sorted(names, key=lambda n: (is_virtual(n), n != DRONE_CAMERA_NAME, len(n), n)))
    return list(_slots_cache["slots"])


def drone_label(slot):
    if str(slot).startswith("drone-v"):  # virtual drones (simulator)
        return "Virtual " + slot[len("drone-v"):]
    return "Drone 1" if slot == DRONE_CAMERA_NAME else "Drone " + (slot[len(DRONE_CAMERA_NAME):] or "?")


def get_link(slot=None):
    return drone_links.setdefault(slot or DRONE_CAMERA_NAME, _new_link())


def _req_slot():
    slot = request.args.get("drone") or (request.get_json(silent=True) or {}).get("drone") or DRONE_CAMERA_NAME
    return slot if slot in drone_slots() else None


def _distance_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def drone_control_allowed():
    if onprem_mode():
        return "drone_control" in set((offline_license.get("payload") or {}).get("features") or [])
    with cloud_lock:
        explicit = "drone_control" in (cloud_state.get("features") or {})
    # Set per client in the admin portal; accounts never given that setting keep the drone-live rule.
    return cloud_feature_enabled("drone_control" if explicit else "drone_live")


def _token_file(slot):
    return DRONE_LINK_TOKEN_FILE if slot in (None, DRONE_CAMERA_NAME) else f"{DRONE_LINK_TOKEN_FILE}_{slot}"


def drone_link_token(reset=False, slot=None):
    import secrets
    path = _token_file(slot)
    if not reset:
        try:
            with open(path, "r", encoding="utf-8") as f:
                token = f.read().strip()
            if len(token) >= 32:
                return token
        except OSError:
            pass
    token = secrets.token_hex(24)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(token)
    os.replace(tmp, path)
    return token


def _drone_send(msg, slot=None):
    """Send one message to that drone's phone; False when it is not connected."""
    link = get_link(slot)
    with link["lock"]:
        conn = link["conn"]
        if conn is None:
            return False
        try:
            conn.sendall((json.dumps(msg, separators=(",", ":")) + "\n").encode())
            return True
        except OSError:
            _drone_drop(conn, "send failed", slot)
            return False


def _drone_drop(conn, why, slot=None):
    # Caller holds the link's lock or owns conn.
    link = get_link(slot)
    if link["conn"] is conn:
        link["conn"] = None
        link["stick_active"] = False
        link["error"] = why
        _drone_event(f"Phone disconnected ({why}).", slot)
    try:
        conn.close()
    except OSError:
        pass


def _drone_event(msg, slot=None):
    link = get_link(slot)
    link["events"] = (link["events"] + [{"at": time.time(), "msg": str(msg)[:200]}])[-30:]


def _drone_session(conn, addr):
    import hashlib, hmac, secrets
    conn.settimeout(10)
    reader = conn.makefile("r", encoding="utf-8", newline="\n")
    nonce = secrets.token_hex(16)
    conn.sendall((json.dumps({"t": "challenge", "nonce": nonce}) + "\n").encode())
    try:
        hello = json.loads(reader.readline() or "{}")
    except ValueError:
        hello = {}
    # The pairing code the phone holds tells which drone slot it is.
    slot = next((s for s in drone_slots() if hello.get("t") == "hello" and hmac.compare_digest(
        str(hello.get("mac", "")), hmac.new(drone_link_token(slot=s).encode(), nonce.encode(), hashlib.sha256).hexdigest())), None)
    if slot is None:
        conn.sendall(b'{"t":"denied","error":"Pairing code does not match. Scan the QR code again."}\n')
        conn.close()
        print(f"Drone link: refused {addr[0]} (wrong pairing code)")
        return
    if not drone_control_allowed():
        conn.sendall(b'{"t":"denied","error":"Drone control is not included in this license."}\n')
        conn.close()
        return
    if slot in _sources_over_limit():
        conn.sendall(b'{"t":"denied","error":"This drone is beyond the licence limit."}\n')
        conn.close()
        return
    link = get_link(slot)
    with link["lock"]:
        if link["conn"] is not None:
            _drone_drop(link["conn"], "replaced by a new phone connection", slot)
        link.update({"conn": conn, "device": str(hello.get("device", ""))[:80], "connected_at": time.time(),
                     "telemetry": {}, "tel_at": 0.0, "error": ""})
        _drone_event(f"Phone connected: {link['device'] or addr[0]}", slot)
    conn.settimeout(5)  # telemetry arrives 5x per second; silence means the link is gone
    _drone_send({"t": "welcome", "rtmp": f"rtmp://{_lan_ip()}:1935/{slot}", "limits": DRONE_LIMITS}, slot)
    try:
        for line in reader:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            kind = msg.get("t")
            if kind == "tel":
                msg.pop("t", None)
                link["telemetry"], link["tel_at"] = msg, time.time()
            elif kind == "ack":
                with drone_ack_cond:
                    link["acks"][int(msg.get("id") or 0)] = msg
                    drone_ack_cond.notify_all()
            elif kind == "event":
                _drone_event(msg.get("msg", ""), slot)
    except OSError:
        pass
    finally:
        with link["lock"]:
            _drone_drop(conn, "connection closed", slot)


def _drone_heartbeat_worker():
    while True:
        time.sleep(0.25)
        for slot, link in list(drone_links.items()):
            if link["conn"] is None:
                continue
            _drone_send({"t": "ping"}, slot)
            # The browser holds the sticks by re-sending them; if it stops (tab closed, crash),
            # centre the sticks so the drone hovers.
            if link["stick_active"] and time.time() - link["stick_at"] > DRONE_STICK_TIMEOUT:
                link["stick_active"] = False
                _drone_send({"t": "stick", "x": 0, "y": 0, "z": 0, "r": 0}, slot)


def _drone_link_server():
    try:
        srv = socket.create_server(("0.0.0.0", DRONE_LINK_PORT), reuse_port=False)
    except OSError as e:
        drone_link["error"] = f"Drone link port {DRONE_LINK_PORT} unavailable: {e}"
        print(drone_link["error"])
        return
    print(f"Drone link listening on port {DRONE_LINK_PORT}")
    while True:
        conn, addr = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=_drone_session, args=(conn, addr), daemon=True).start()


def start_drone_link():
    drone_link_token()
    threading.Thread(target=_drone_link_server, daemon=True).start()
    threading.Thread(target=_drone_heartbeat_worker, daemon=True).start()


def drone_command(cmd, args=None, timeout=8.0, slot=None):
    """Send a command to that drone's phone and wait for its acknowledgement."""
    link = get_link(slot)
    with drone_ack_cond:
        cid = link["next_id"]
        link["next_id"] += 1
    if not _drone_send({"t": "cmd", "id": cid, "cmd": cmd, "args": args or {}}, slot):
        return {"ok": False, "error": f"The Drone Link phone for {drone_label(slot or DRONE_CAMERA_NAME)} is not connected."}
    deadline = time.time() + timeout
    with drone_ack_cond:
        while cid not in link["acks"]:
            left = deadline - time.time()
            if left <= 0:
                return {"ok": False, "error": "The phone did not answer in time."}
            drone_ack_cond.wait(left)
        ack = link["acks"].pop(cid)
    return {"ok": bool(ack.get("ok")), "error": ack.get("error") or ""}


def link_fresh(slot=None, seconds=3):
    link = get_link(slot)
    return link["conn"] is not None and time.time() - link["tel_at"] < seconds


def _drone_link_status(slot=None):
    link = get_link(slot)
    fresh = link_fresh(slot, 2)
    return {"ok": True, "drone": slot or DRONE_CAMERA_NAME, "label": drone_label(slot or DRONE_CAMERA_NAME),
            "allowed": drone_control_allowed(), "phone_connected": link["conn"] is not None,
            "telemetry_fresh": fresh, "device": link["device"], "telemetry": link["telemetry"] if fresh else {},
            "events": link["events"][-10:], "error": link["error"], "limits": DRONE_LIMITS,
            "link": {"host": _lan_ip(), "port": DRONE_LINK_PORT}}


@app.route("/api/drone/link")
def api_drone_link():
    slot = _req_slot()
    if slot is None:
        return jsonify({"ok": False, "error": "Unknown drone."}), 404
    return jsonify(_drone_link_status(slot))


@app.route("/api/drone/links")
def api_drone_links():
    """Every drone slot with a short status, for the drone selector and the map."""
    over = _sources_over_limit()
    out = []
    for s in drone_slots():
        link, fresh = get_link(s), link_fresh(s, 3)
        t = link["telemetry"] if fresh else {}
        out.append({"drone": s, "label": drone_label(s), "phone_connected": link["conn"] is not None,
                    "drone_connected": bool(t.get("drone_connected")), "battery": t.get("battery"), "flying": t.get("flying"),
                    "lat": t.get("lat"), "lon": t.get("lon"), "heading": t.get("heading"), "over_limit": s in over,
                    "virtual": is_virtual(s), "altitude": t.get("altitude"), "speed": t.get("speed"),
                    "gps": t.get("gps_satellites"), "mode": t.get("flight_mode"), "distance_home": t.get("distance_home")})
    allowed = api_cloud_can_add_source("drone").get_json()
    busy = {drone_response.get("drone"): "response"} if drone_response["active"] else {}
    if route_run["active"]:
        busy[route_run.get("drone")] = "route"
    for d in out:
        d["mission"] = busy.get(d["drone"], "")
    return jsonify({"ok": True, "drones": out, "can_add": bool(allowed.get("allowed")), "limit": allowed.get("limit"),
                    "used": allowed.get("used"), "message": allowed.get("message")})


@app.route("/api/drone/link/pair")
def api_drone_link_pair():
    """QR code the phone app scans: where to connect and that drone's pairing code."""
    if not drone_control_allowed():
        return jsonify({"ok": False, "error": "Drone control is not included in this license."}), 403
    slot = _req_slot()
    if slot is None:
        return jsonify({"ok": False, "error": "Unknown drone."}), 404
    host = _lan_ip()
    payload = json.dumps({"app": "ai-drone-link", "host": host, "port": DRONE_LINK_PORT,
                          "token": drone_link_token(slot=slot)}, separators=(",", ":"))
    return jsonify({"ok": True, "host": host, "port": DRONE_LINK_PORT, "drone": slot, "label": drone_label(slot), "qr": _qr_svg(payload)})


@app.route("/api/drone/link/pair/reset", methods=["POST"])
def api_drone_link_pair_reset():
    """New pairing code for one drone: its phone must scan again (use if a phone was lost)."""
    slot = _req_slot() or DRONE_CAMERA_NAME
    drone_link_token(reset=True, slot=slot)
    link = get_link(slot)
    with link["lock"]:
        if link["conn"] is not None:
            _drone_drop(link["conn"], "pairing code changed", slot)
    return jsonify({"ok": True})


LAND_ASSIST_SECONDS = 120


def start_land_assist(slot, why):
    """See a landing through to motors off. DJI drones stop about 0.5 m above the ground and wait
    for a landing confirmation (and never land from the sticks alone), so confirm or re-ask as needed."""
    link = get_link(slot)
    token = time.time()
    link["land_assist"] = token
    _drone_event(f"Landing ({why})", slot)

    def run():
        start, last_ask, low_since = time.time(), 0.0, 0.0
        while link.get("land_assist") == token and time.time() - start < LAND_ASSIST_SECONDS:
            time.sleep(0.3)
            t = link["telemetry"]
            if time.time() - link["tel_at"] > 3:
                continue
            if not t.get("flying") and not t.get("motors_on"):
                _drone_event("Landed, motors off", slot)
                break
            now = time.time()
            if t.get("landing_confirm_needed"):
                if now - last_ask > 2:
                    last_ask = now
                    r = drone_command("confirm_land", timeout=5.0, slot=slot)
                    _drone_event("Landing confirmed" if r["ok"] else f"Confirm landing failed: {r['error']}", slot)
                continue
            # Hovering just above the ground and not descending: the landing was paused, ask again.
            low = (t.get("altitude") or 0) < 1.0 and (t.get("vertical_speed") or 0) > -0.15
            low_since = (low_since or now) if low else 0.0
            if low_since and now - low_since > 3 and now - last_ask > 4:
                last_ask = now
                r = drone_command("land", timeout=8.0, slot=slot)
                if r["ok"]:
                    drone_command("confirm_land", timeout=5.0, slot=slot)
        if link.get("land_assist") == token:
            link["land_assist"] = 0

    threading.Thread(target=run, daemon=True).start()


def stop_land_assist(slot):
    get_link(slot)["land_assist"] = 0


@app.route("/api/drone/command", methods=["POST"])
def api_drone_command():
    if not drone_control_allowed():
        return jsonify({"ok": False, "error": "Drone control is not included in this license."}), 403
    slot = _req_slot()
    if slot is None:
        return jsonify({"ok": False, "error": "Unknown drone."}), 404
    link = get_link(slot)
    data = request.get_json(silent=True) or {}
    cmd = str(data.get("cmd") or "")
    if cmd not in DRONE_COMMANDS:
        return jsonify({"ok": False, "error": "Unknown drone command."}), 400
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    if cmd == "gimbal":
        args = {"pitch": max(-90.0, min(30.0, float(args.get("pitch") or 0)))}
    elif cmd == "sim_on":
        args = {"lat": float(args.get("lat") or 0), "lon": float(args.get("lon") or 0)}
    elif cmd == "control_on":
        args = {"speed": max(0.1, min(DRONE_LIMITS["max_speed_level"], float(args.get("speed") or 0.3)))}
    elif cmd == "goto":
        try:
            lat, lon = float(args["lat"]), float(args["lon"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"ok": False, "error": "Click the map to choose where to fly."}), 400
        tel = link["telemetry"]
        home = (tel.get("home_lat") or tel.get("lat"), tel.get("home_lon") or tel.get("lon"))
        if None in home:
            return jsonify({"ok": False, "error": "The drone has no GPS position yet."}), 409
        if _distance_m(home[0], home[1], lat, lon) > DRONE_LIMITS["max_distance_m"]:
            return jsonify({"ok": False, "error": f"That point is more than {DRONE_LIMITS['max_distance_m']} m from home."}), 400
        arrive = args.get("arrive") if args.get("arrive") in ("hover", "land", "home") else "hover"
        args = {"lat": lat, "lon": lon, "arrive": arrive,
                "alt": max(5.0, min(float(DRONE_LIMITS["max_altitude_m"]), float(args.get("alt") or 30))),
                "speed": max(1.0, min(8.0, float(args.get("speed") or 5)))}
    if cmd == "sim_on" and time.time() - link.get("sim_off_at", 0) < 60:
        # Re-enabling the simulator soon after disabling it made the Mini 3 Pro switch itself off.
        wait = int(60 - (time.time() - link["sim_off_at"]))
        return jsonify({"ok": False, "error": f"Wait {wait} s before starting the simulator again (the drone can switch off otherwise)."}), 409
    if cmd == "sim_off":
        link["sim_off_at"] = time.time()
    if cmd in ("hover", "control_off"):
        link["stick_active"] = False
    if cmd in ("cancel_land", "takeoff", "goto", "go_home", "hover", "control_on"):
        stop_land_assist(slot)
    result = drone_command(cmd, args, timeout=15.0 if cmd in ("takeoff", "sim_on", "control_on") else 8.0, slot=slot)
    _drone_event(f"{cmd}: {'OK' if result['ok'] else result['error']}", slot)
    if cmd == "land" and result["ok"]:
        start_land_assist(slot, "Land pressed")
    return jsonify(result), (200 if result["ok"] else 409)


@app.route("/api/drone/stick", methods=["POST"])
def api_drone_stick():
    """Virtual sticks from the browser (keyboard/gamepad), each -1..1, re-sent ~10x per second."""
    if not drone_control_allowed():
        return jsonify({"ok": False}), 403
    slot = _req_slot()
    if slot is None:
        return jsonify({"ok": False}), 404
    link = get_link(slot)
    data = request.get_json(silent=True) or {}
    clamp = lambda v: max(-1.0, min(1.0, float(v or 0)))
    stick = {"t": "stick", "x": clamp(data.get("x")), "y": clamp(data.get("y")),
             "z": clamp(data.get("z")), "r": clamp(data.get("r"))}
    link["stick_at"] = time.time()
    link["stick_active"] = any(stick[k] for k in "xyzr")
    # Holding "down" close to the ground lands, like holding the throttle down on the DJI controller.
    t = link["telemetry"]
    near_ground = t.get("flying") and (t.get("altitude") if t.get("altitude") is not None else 99) < 1.2
    if stick["z"] <= -0.6 and near_ground and not stick["x"] and not stick["y"]:
        link["down_since"] = link.get("down_since") or time.time()
        if time.time() - link["down_since"] >= 1.0 and not link.get("land_assist"):
            link["down_since"] = 0
            threading.Thread(target=lambda: drone_command("land", timeout=8.0, slot=slot)["ok"]
                             and start_land_assist(slot, "down held near the ground"), daemon=True).start()
    else:
        link["down_since"] = 0
    # Holding "up" on the ground (keyboard control on) takes off, no confirmation box.
    on_ground = t.get("drone_connected") and not t.get("flying") and not t.get("motors_on") and time.time() - link["tel_at"] < 2
    if stick["z"] >= 0.6 and on_ground:
        link["up_since"] = link.get("up_since") or time.time()
        if time.time() - link["up_since"] >= 0.7 and time.time() - link.get("auto_takeoff_at", 0) > 8:
            link["up_since"], link["auto_takeoff_at"] = 0, time.time()
            stop_land_assist(slot)

            def go():
                r = drone_command("takeoff", timeout=15.0, slot=slot)
                _drone_event("Take-off (up key held)" if r["ok"] else f"Take-off failed: {r['error']}", slot)
            threading.Thread(target=go, daemon=True).start()
    else:
        link["up_since"] = 0
    return jsonify({"ok": _drone_send(stick, slot)})


@app.route("/api/drone/add", methods=["POST"])
def api_drone_add():
    """Add the next drone slot (within the licence): its video path and pairing code."""
    _slots_cache["at"] = 0.0
    r = api_setup_drone()
    _slots_cache["at"] = 0.0
    return r


# ---------- virtual drones (simulated Drone Link phones, for testing, training and demos) ----------
# Each one connects to the drone link port with its own pairing code, exactly like the phone app,
# so the Drone page, routes, patrols, responses and Telegram treat it as a real drone.
VIRTUAL_PREFIX = "drone-v"
VIRTUAL_MAX = 5
VIRTUAL_FILE = os.path.join(BASE_FOLDER, "virtual_drones.json")
VIRTUAL_DEFAULT_HOME = (33.8938, 35.5018)
virtual_drones = {}  # slot -> VirtualDrone
virtual_lock = threading.Lock()


def is_virtual(slot):
    return str(slot or "").startswith(VIRTUAL_PREFIX)


def _load_virtual_config():
    try:
        with open(VIRTUAL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_virtual_config():
    with virtual_lock:
        data = {"demo_auto": bool(_virtual_cfg.get("demo_auto")),
                "drones": [{"slot": v.slot, "home_lat": v.home[0], "home_lon": v.home[1]} for v in virtual_drones.values()]}
    tmp = VIRTUAL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, VIRTUAL_FILE)


_virtual_cfg = _load_virtual_config()


def _wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def _bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)))


class VirtualDrone:
    """A simulated DJI Mini-class drone plus its phone: 10 Hz flight model, Drone Link protocol."""
    RTH_ALT = 30.0

    def __init__(self, slot, home):
        self.slot, self.home = slot, (float(home[0]), float(home[1]))
        self.lat, self.lon, self.alt, self.heading = self.home[0], self.home[1], 0.0, 0.0
        self.v = [0.0, 0.0, 0.0]  # forward, right, up (m/s, body frame)
        self.battery, self.powered, self.motors, self.flying = 100.0, True, False, False
        self.mode, self.rth_phase = "GPS_NORMAL", ""
        self.control_pc, self.speed_level, self.stick, self.stick_at = False, 0.3, (0.0, 0.0, 0.0, 0.0), 0.0
        self.mission, self.gimbal, self.sats, self.recording = None, 0.0, 17, False
        self.link_down_until, self.stop, self.sock, self.lock = 0.0, False, None, threading.Lock()
        self.confirm_needed = self.land_confirmed = False  # like a Mini: landing pauses at 0.5 m for confirmation

    # ----- protocol (same messages as the Android app) -----
    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _send(self, msg):
        s = self.sock
        if s is None:
            return
        try:
            s.sendall((json.dumps(msg, separators=(",", ":")) + "\n").encode())
        except OSError:
            self._close()

    def _close(self):
        s, self.sock = self.sock, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    def event(self, text):
        self._send({"t": "event", "msg": f"[virtual] {text}"})

    def _run(self):
        import hashlib, hmac
        threading.Thread(target=self._physics, daemon=True).start()
        while not self.stop:
            if time.time() < self.link_down_until:
                time.sleep(0.5)
                continue
            try:
                s = socket.create_connection(("127.0.0.1", DRONE_LINK_PORT), timeout=5)
                reader = s.makefile("r", encoding="utf-8", newline="\n")
                nonce = json.loads(reader.readline() or "{}").get("nonce", "")
                mac = hmac.new(drone_link_token(slot=self.slot).encode(), nonce.encode(), hashlib.sha256).hexdigest()
                s.sendall((json.dumps({"t": "hello", "mac": mac, "device": "Virtual drone (simulator)", "app": "virtual"}) + "\n").encode())
                s.settimeout(None)
                self.sock = s
                for line in reader:
                    if self.stop or self.sock is None or time.time() < self.link_down_until:
                        break
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if msg.get("t") == "denied":
                        print(f"Virtual drone {self.slot}: {msg.get('error')}")
                        time.sleep(30)
                        break
                    if msg.get("t") == "stick":
                        self._set_sticks(msg)
                    elif msg.get("t") == "cmd":
                        with self.lock:
                            ok, err = self._command(str(msg.get("cmd")), msg.get("args") or {})
                        self._send({"t": "ack", "id": msg.get("id"), "ok": ok, "error": err})
            except (OSError, ValueError):
                pass
            self._close()
            time.sleep(2)

    def _set_sticks(self, msg):
        vals = tuple(max(-1.0, min(1.0, float(msg.get(k) or 0))) for k in "xyzr")
        if self.mission and any(abs(v) > 0.05 for v in vals):
            self._abort("manual control")
        if self.control_pc:
            self.stick, self.stick_at = vals, time.time()

    def _abort(self, why):
        if self.mission:
            self.mission = None
            self.event(f"Auto-fly stopped: {why}")

    def _command(self, cmd, args):
        if not self.powered:
            return False, "The drone is switched off."
        if cmd == "takeoff":
            if self.flying:
                return False, "Already flying."
            if self.battery < 15:
                return False, "Battery too low to take off."
            self.motors, self.flying, self.mode = True, True, "AUTO_TAKE_OFF"
            self.confirm_needed = self.land_confirmed = False
            self.event("Take-off")
        elif cmd == "land":
            self._abort("land pressed")
            if not self.flying:
                return False, "Not flying."
            self.control_pc, self.stick = False, (0.0, 0.0, 0.0, 0.0)  # the real app hands control back first
            self.mode, self.rth_phase = "AUTO_LANDING", ""
        elif cmd == "cancel_land":
            if self.mode == "AUTO_LANDING":
                self.mode, self.confirm_needed = "GPS_NORMAL", False
        elif cmd == "confirm_land":
            if not self.confirm_needed:
                return False, "No landing confirmation is needed."
            self.land_confirmed, self.confirm_needed = True, False
        elif cmd == "go_home":
            self._abort("return home pressed")
            if not self.flying:
                return False, "Not flying."
            self.stick, self.mode, self.rth_phase = (0.0, 0.0, 0.0, 0.0), "GO_HOME", "climb"
            self.control_pc = False
        elif cmd == "cancel_go_home":
            if self.mode == "GO_HOME":
                self.mode, self.rth_phase = "GPS_NORMAL", ""
        elif cmd == "hover":
            self._abort("STOP pressed")
            self.stick = (0.0, 0.0, 0.0, 0.0)
        elif cmd == "goto":
            try:
                lat, lon = float(args["lat"]), float(args["lon"])
            except (KeyError, TypeError, ValueError):
                return False, "No target."
            if not self.flying and self.battery < 15:
                return False, "Battery too low to take off."
            self.mission = {"state": "ENABLING" if self.flying else "TAKING_OFF", "lat": lat, "lon": lon,
                            "alt": max(5.0, min(120.0, float(args.get("alt") or 30))), "speed": max(1.0, min(8.0, float(args.get("speed") or 5))),
                            "arrive": args.get("arrive") if args.get("arrive") in ("hover", "land", "home") else "hover", "distance": -1, "arrived_at": 0.0}
            if not self.flying:
                self.motors, self.flying, self.mode = True, True, "AUTO_TAKE_OFF"
            elif self.mode in ("GO_HOME", "AUTO_LANDING"):
                self.mode, self.rth_phase = "GPS_NORMAL", ""
            self.event("Auto-fly started")
        elif cmd == "goto_cancel":
            self._abort("cancelled")
        elif cmd == "control_on":
            self.control_pc, self.speed_level, self.stick_at = True, max(0.1, min(0.5, float(args.get("speed") or 0.3))), time.time()
        elif cmd == "control_off":
            self.control_pc, self.stick = False, (0.0, 0.0, 0.0, 0.0)
            self._abort("control handed back")
        elif cmd == "gimbal":
            self.gimbal = max(-90.0, min(30.0, float(args.get("pitch") or 0)))
        elif cmd == "photo":
            self.event("Photo taken (virtual)")
        elif cmd in ("record_start", "record_stop"):
            self.recording = cmd == "record_start"
            self.event("Recording started" if self.recording else "Recording stopped")
        elif cmd in ("sim_on", "sim_off", "stream_on", "stream_off"):
            pass  # always simulated; the "video" is drawn on the Drone page
        else:
            return False, "Unknown command."
        return True, ""

    # ----- flight model -----
    def distance_home(self):
        return _distance_m(self.home[0], self.home[1], self.lat, self.lon)

    def _fly_towards(self, lat, lon, alt, speed):
        """Return (forward, up, yaw_rate) like the phone's auto-fly controller."""
        dist = _distance_m(self.lat, self.lon, lat, lon)
        hdg_err = _wrap180(_bearing_deg(self.lat, self.lon, lat, lon) - self.heading)
        up = max(-2.0, min(2.0, 0.8 * (alt - self.alt)))
        yaw = max(-60.0, min(60.0, 2.0 * hdg_err)) if dist > 3 else 0.0
        fwd = min(speed, max(0.5, 0.4 * dist)) * math.cos(math.radians(hdg_err)) if abs(hdg_err) < 30 and dist >= 1.0 else 0.0
        return fwd, up, yaw, dist

    def _targets(self):
        fwd = right = up = yaw = 0.0
        m = self.mission
        if self.mode == "AUTO_TAKE_OFF":
            up = 1.5
            if self.alt >= 1.2:
                self.mode = "GPS_NORMAL"
        elif self.mode == "AUTO_LANDING":
            if self.alt <= 0.5 and not self.land_confirmed:
                self.confirm_needed = True  # waits just above the ground, like the real drone
            else:
                up = -1.2 if self.alt > 1 else -0.5
        elif self.mode == "GO_HOME":
            if self.rth_phase == "climb":
                up = max(-2.0, min(3.0, (self.RTH_ALT - self.alt))) if self.alt < self.RTH_ALT - 0.5 else 0.0
                if self.alt >= self.RTH_ALT - 0.5 or self.distance_home() < 20:
                    self.rth_phase = "cruise"
            else:
                fwd, up, yaw, dist = self._fly_towards(self.home[0], self.home[1], max(self.alt, 0), 8.0)
                up = 0.0
                if dist < 1.5:
                    self.mode, self.rth_phase, self.land_confirmed = "AUTO_LANDING", "", True
        elif m:
            if m["state"] == "TAKING_OFF" and self.mode != "AUTO_TAKE_OFF":
                m["state"] = "ENABLING"
            if m["state"] == "ENABLING":
                self.control_pc, m["state"] = True, "CLIMB"
            if m["state"] in ("CLIMB", "CRUISE"):
                fwd, up, yaw, dist = self._fly_towards(m["lat"], m["lon"], m["alt"], m["speed"])
                m["distance"] = dist
                if m["state"] == "CLIMB":
                    fwd = 0.0 if abs(m["alt"] - self.alt) >= 2.0 else fwd
                    if abs(m["alt"] - self.alt) < 2.0:
                        m["state"] = "CRUISE"
                if m["state"] == "CRUISE" and dist < 2.0:
                    m["state"], m["arrived_at"] = "ARRIVED", time.time()
                    self.event("Auto-fly: arrived")
            if m["state"] == "ARRIVED":
                fwd = up = yaw = 0.0
                if time.time() - m["arrived_at"] >= 2.0:
                    self.mission = None
                    if m["arrive"] == "land":
                        self.mode, self.land_confirmed = "AUTO_LANDING", True
                    elif m["arrive"] == "home":
                        self.mode, self.rth_phase = "GO_HOME", "climb"
                    else:
                        self.event("Auto-fly: hovering over the target")
        elif self.control_pc and self.flying:
            if time.time() - self.stick_at > 0.5:
                self.stick = (0.0, 0.0, 0.0, 0.0)
            x, y, z, r = self.stick
            if self.alt >= DRONE_LIMITS["max_altitude_m"] and z > 0:
                z = 0.0
            if self.alt <= 0.5 and z < 0:
                z = 0.0  # landing protection: sticks alone never put it on the ground
            if self.distance_home() >= DRONE_LIMITS["max_distance_m"] and (x or y):
                h = math.radians(self.heading)
                north, east = y * math.cos(h) - x * math.sin(h), y * math.sin(h) + x * math.cos(h)
                away_n, away_e = self.lat - self.home[0], (self.lon - self.home[1]) * math.cos(math.radians(self.lat))
                if north * away_n + east * away_e > 0:
                    x = y = 0.0
            fwd, right, up, yaw = y * self.speed_level * 10, x * self.speed_level * 10, z * min(3.0, self.speed_level * 6), r * 120 * self.speed_level
        return fwd, right, up, yaw

    def _physics(self):
        dt, last_tel = 0.1, 0.0
        while not self.stop:
            time.sleep(dt)
            with self.lock:
                if self.flying:
                    tf, tr, tu, yaw = self._targets()
                    for i, (t, a) in enumerate(((tf, 4.0), (tr, 4.0), (tu, 3.0))):
                        self.v[i] += max(-a * dt, min(a * dt, t - self.v[i]))
                    self.heading = _wrap180(self.heading + yaw * dt)
                    h = math.radians(self.heading)
                    north = self.v[0] * math.cos(h) - self.v[1] * math.sin(h)
                    east = self.v[0] * math.sin(h) + self.v[1] * math.cos(h)
                    self.lat += north * dt / 111320.0
                    self.lon += east * dt / (111320.0 * math.cos(math.radians(self.lat)))
                    self.alt = max(0.0, self.alt + self.v[2] * dt)
                    self.battery = max(0.0, self.battery - dt * 100.0 / (24 * 60))  # ~24 min flight
                    if self.mode == "AUTO_LANDING" and self.alt <= 0.05:
                        self.flying = self.motors = False
                        self.confirm_needed = self.land_confirmed = False
                        self.mode, self.v, self.alt = "GPS_NORMAL", [0.0, 0.0, 0.0], 0.0
                        self.event("Landed, motors stopped")
                    elif self.battery <= 5 and self.mode != "AUTO_LANDING":
                        self._abort("critical battery")
                        self.mode, self.land_confirmed = "AUTO_LANDING", True
                        self.event("Critical battery: landing now")
                    elif self.battery <= 15 and self.mode not in ("GO_HOME", "AUTO_LANDING"):
                        self._abort("low battery")
                        self.mode, self.rth_phase = "GO_HOME", "climb"
                        self.event("Low battery: returning home")
            if time.time() - last_tel >= 0.2:
                last_tel = time.time()
                self._send(self.telemetry())

    def telemetry(self):
        speed = math.hypot(self.v[0], self.v[1]) if self.flying else 0.0
        t = {"t": "tel", "virtual": True, "sdk_registered": True, "drone_connected": self.powered,
             "control": "PC" if self.control_pc else "PILOT", "simulator": True, "streaming": False}
        if not self.powered:
            return t
        m = self.mission
        if m:
            t["mission"] = {k: m[k] for k in ("state", "lat", "lon", "alt", "speed", "arrive", "distance")}
        t.update({"lat": round(self.lat, 7), "lon": round(self.lon, 7), "altitude": round(self.alt, 2), "heading": round(self.heading, 1),
                  "speed": round(speed, 2), "vertical_speed": round(self.v[2] if self.flying else 0.0, 2), "battery": int(round(self.battery)),
                  "gps_satellites": self.sats, "flying": self.flying, "motors_on": self.motors, "flight_mode": self.mode,
                  "landing_confirm_needed": self.confirm_needed, "signal": 100, "gimbal_pitch": self.gimbal, "recording": self.recording,
                  "home_lat": self.home[0], "home_lon": self.home[1], "distance_home": round(self.distance_home(), 1)})
        return t

    def summary(self):
        link = get_link(self.slot)
        return {"drone": self.slot, "label": drone_label(self.slot), "powered": self.powered, "linked": link["conn"] is not None,
                "link_down": time.time() < self.link_down_until, "flying": self.flying, "mode": self.mode,
                "battery": int(round(self.battery)), "altitude": round(self.alt, 1), "lat": self.lat, "lon": self.lon,
                "heading": self.heading, "home_lat": self.home[0], "home_lon": self.home[1], "gps_satellites": self.sats,
                "mission": (self.mission or {}).get("state", "")}


def start_virtual_drones():
    for d in _virtual_cfg.get("drones") or []:
        slot = str(d.get("slot") or "")
        if is_virtual(slot) and slot not in virtual_drones:
            v = VirtualDrone(slot, (d.get("home_lat") or VIRTUAL_DEFAULT_HOME[0], d.get("home_lon") or VIRTUAL_DEFAULT_HOME[1]))
            virtual_drones[slot] = v
            v.start()
    _slots_cache["at"] = 0.0


@app.route("/api/virtual-drones", methods=["GET", "POST"])
def api_virtual_drones():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if "demo_auto" in data:
            _virtual_cfg["demo_auto"] = bool(data["demo_auto"])
            _save_virtual_config()
            return jsonify({"ok": True, "demo_auto": _virtual_cfg["demo_auto"]})
        if len(virtual_drones) >= VIRTUAL_MAX:
            return jsonify({"ok": False, "error": f"{VIRTUAL_MAX} virtual drones maximum."}), 409
        try:
            home = (float(data["lat"]), float(data["lon"]))
        except (KeyError, TypeError, ValueError):
            return jsonify({"ok": False, "error": "Click the map to choose where the virtual drone starts."}), 400
        n = next(i for i in range(1, VIRTUAL_MAX + 2) if f"{VIRTUAL_PREFIX}{i}" not in virtual_drones)
        slot = f"{VIRTUAL_PREFIX}{n}"
        drone_link_token(reset=True, slot=slot)
        v = VirtualDrone(slot, home)
        with virtual_lock:
            virtual_drones[slot] = v
        _slots_cache["at"] = 0.0
        _save_virtual_config()
        v.start()
        return jsonify({"ok": True, "drone": slot, "label": drone_label(slot)})
    return jsonify({"ok": True, "allowed": drone_control_allowed(), "max": VIRTUAL_MAX, "demo_auto": bool(_virtual_cfg.get("demo_auto")),
                    "drones": [v.summary() for v in list(virtual_drones.values())]})


@app.route("/api/virtual-drones/<slot>", methods=["POST", "DELETE"])
def api_virtual_drone(slot):
    v = virtual_drones.get(slot)
    if v is None:
        return jsonify({"ok": False, "error": "Unknown virtual drone."}), 404
    if request.method == "DELETE":
        v.stop = True
        v._close()
        with virtual_lock:
            virtual_drones.pop(slot, None)
        drone_links.pop(slot, None)
        try:
            os.remove(_token_file(slot))
        except OSError:
            pass
        _slots_cache["at"] = 0.0
        _save_virtual_config()
        return jsonify({"ok": True})
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "")
    with v.lock:
        if action == "power":
            if v.flying:
                return jsonify({"ok": False, "error": "Land it before switching it off."}), 409
            v.powered = not v.powered
        elif action == "recharge":
            if v.flying:
                return jsonify({"ok": False, "error": "Land it first."}), 409
            v.battery = 100.0
        elif action == "low_battery":
            v.battery = min(v.battery, 20.0)
        elif action == "weak_gps":
            v.sats = 5 if v.sats > 5 else 17
        elif action == "drop_link":
            v.link_down_until = time.time() + 10
            v._close()
        elif action == "home":
            if v.flying:
                return jsonify({"ok": False, "error": "Land it before moving its home point."}), 409
            try:
                v.home = (float(data["lat"]), float(data["lon"]))
            except (KeyError, TypeError, ValueError):
                return jsonify({"ok": False, "error": "No position."}), 400
            v.lat, v.lon = v.home
        else:
            return jsonify({"ok": False, "error": "Unknown action."}), 400
    if action == "home":
        _save_virtual_config()
    return jsonify({"ok": True, "drone": v.summary()})


@app.route("/virtual-drones")
def virtual_drones_page():
    return VIRTUAL_DRONES_PAGE


VIRTUAL_DRONES_PAGE = hud_page("Virtual Drones", r"""
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
.vd-grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(340px,1fr);gap:16px;align-items:start}
#vdMap{height:460px;border:1px solid #155879;border-radius:5px;background:#020a10}
.vd-card{border:1px solid #155879;border-radius:5px;background:#05131d;padding:12px;margin-bottom:10px}
.vd-card h3{margin:0 0 6px;font-size:14px;color:#e9f8ff;letter-spacing:1px;display:flex;justify-content:space-between;align-items:center}
.vd-tag{font-size:10px;color:#ffcf7a;border:1px solid #7a5a12;border-radius:3px;padding:2px 6px;letter-spacing:1px}
.vd-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:8px 0}
.vd-stats div{background:#020a10;border:1px solid #153c56;border-radius:4px;padding:6px 8px}
.vd-stats small{display:block;color:#6d8b9d;font-size:9px;letter-spacing:1.5px;text-transform:uppercase}
.vd-stats b{color:#e9f8ff;font-size:14px}
.vd-card .actions{flex-wrap:wrap;gap:6px}
.vd-card .hud-btn{min-height:32px;font-size:11px}
@media(max-width:1000px){.vd-grid{grid-template-columns:1fr}}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Testing &amp; demos</div><h1 class="page-title">Virtual Drones</h1>
<div class="page-sub">Simulated drones that connect like a real Drone Link phone. Use them to test routes, patrols and alert responses, train operators, or demo the system with no drone on site. They never control a real aircraft.</div></div>
<div class="actions"><span class="state" id="vdState"><i class="dot warn"></i>LOADING</span></div></div>
<div class="vd-grid">
<section class="panel"><div class="panel-head"><div class="panel-title">⌖ Map</div><div class="live" id="vdHint">CLICK THE MAP TO CHOOSE A START POINT</div></div>
<div class="panel-body"><div id="vdMap"></div>
<div class="actions" style="margin-top:10px;align-items:center"><button class="hud-btn primary" id="vdAdd" onclick="addVd()">+ Add virtual drone here</button>
<span class="muted" id="vdPick">No start point chosen yet.</span></div>
<label style="margin-top:12px;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0"><input type="checkbox" id="vdAuto" onchange="setAuto(this.checked)">
Demo mode: let automatic missions (alert response, patrols set to "any drone", Telegram) use virtual drones when no real drone is ready</label>
<div id="vdMsg" class="hud-msg"></div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">◇ Virtual fleet</div><div class="live" id="vdCount"></div></div>
<div class="panel-body"><div id="vdList"><p class="muted">Loading…</p></div>
<div class="muted" style="margin-top:8px">Fly them from <b>Open controls</b> exactly like a real drone (take off, keyboard, click-to-fly, routes, patrols). Battery lasts about 24 minutes of flight; at 15% they return home and at 5% they land, like a real DJI drone.</div></div></section>
</div>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
let map=null,pick=null,pickMark=null,marks={},trails={},homes={},data={drones:[]};
function msg(t,ok){const e=$('vdMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
function initMap(lat,lon){if(map||typeof L==='undefined')return;map=L.map('vdMap').setView([lat,lon],17);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Esri'}).addTo(map);
  map.on('click',e=>{pick=[e.latlng.lat,e.latlng.lng];pickMark=pickMark||L.circleMarker(pick,{radius:8,color:'#ffd23f'}).addTo(map);pickMark.setLatLng(pick);
    $('vdPick').textContent='Start point: '+pick[0].toFixed(5)+', '+pick[1].toFixed(5)})}
const icon=h=>L.divIcon({className:'',iconSize:[26,26],iconAnchor:[13,13],html:`<div style="transform:rotate(${h||0}deg);font-size:22px;line-height:26px;text-align:center;color:#ffcf7a;text-shadow:0 0 4px #000">➤</div>`});
function draw(){if(!map)return;const seen=new Set();
  data.drones.forEach(d=>{seen.add(d.drone);const p=[d.lat,d.lon];
    marks[d.drone]=marks[d.drone]||L.marker(p).bindTooltip('',{permanent:true,direction:'right'}).addTo(map);
    marks[d.drone].setLatLng(p).setIcon(icon(d.heading-90)).setTooltipContent(esc(d.label)+(d.flying?' · '+d.altitude+' m':''));
    trails[d.drone]=trails[d.drone]||L.polyline([],{color:'#ffcf7a',weight:2,opacity:.7}).addTo(map);if(d.flying)trails[d.drone].addLatLng(p);
    homes[d.drone]=homes[d.drone]||L.circleMarker([d.home_lat,d.home_lon],{radius:5,color:'#2aea88'}).addTo(map);homes[d.drone].setLatLng([d.home_lat,d.home_lon])});
  Object.keys(marks).filter(k=>!seen.has(k)).forEach(k=>{[marks,trails,homes].forEach(o=>{o[k].remove();delete o[k]})})}
function card(d){const st=!d.powered?'Switched off':d.link_down?'Link lost (reconnecting)':!d.linked?'Connecting…':d.mission?'Auto-fly: '+d.mission:d.flying?d.mode.replace(/_/g,' ').toLowerCase():'On the ground';
  return `<div class="vd-card"><h3>${esc(d.label)} <span class="vd-tag">VIRTUAL</span></h3><div class="muted">${esc(st)}</div>
  <div class="vd-stats"><div><small>Battery</small><b>${d.battery}%</b></div><div><small>Height</small><b>${d.altitude} m</b></div><div><small>GPS</small><b>${d.gps_satellites}</b></div></div>
  <div class="actions"><a class="hud-btn primary" href="/drone-control?drone=${encodeURIComponent(d.drone)}" style="text-decoration:none">Open controls</a>
  <button class="hud-btn" onclick="act('${d.drone}','power')">${d.powered?'Switch off':'Switch on'}</button>
  <button class="hud-btn" onclick="act('${d.drone}','recharge')">Recharge</button>
  <button class="hud-btn" onclick="moveHome('${d.drone}')">Move home here</button>
  <button class="hud-btn warn" onclick="act('${d.drone}','low_battery')" title="Battery to 20%">Low battery</button>
  <button class="hud-btn warn" onclick="act('${d.drone}','weak_gps')">${d.gps_satellites<8?'Restore GPS':'Weak GPS'}</button>
  <button class="hud-btn warn" onclick="act('${d.drone}','drop_link')" title="Phone link drops for 10 seconds">Drop link 10 s</button>
  <button class="hud-btn danger" onclick="removeVd('${d.drone}')">Remove</button></div></div>`}
async function load(){try{data=await fetch('/api/virtual-drones',{cache:'no-store'}).then(r=>r.json())}catch(e){return}
  $('vdState').innerHTML=data.allowed?'<i class="dot good"></i>SIMULATOR READY':'<i class="dot bad"></i>DRONE CONTROL NOT IN LICENCE';
  $('vdCount').textContent=data.drones.length+' / '+data.max;$('vdAdd').disabled=data.drones.length>=data.max;$('vdAuto').checked=!!data.demo_auto;
  $('vdList').innerHTML=data.drones.map(card).join('')||'<p class="muted">No virtual drones yet. Click the map, then <b>+ Add virtual drone here</b>.</p>';
  if(!map){const d=data.drones[0];if(d)initMap(d.home_lat,d.home_lon);else navigator.geolocation?navigator.geolocation.getCurrentPosition(p=>initMap(p.coords.latitude,p.coords.longitude),()=>initMap(33.8938,35.5018),{timeout:4000}):initMap(33.8938,35.5018)}
  draw()}
async function addVd(){if(!pick){msg('Click the map first to choose where it starts.',false);return}
  const d=await fetch('/api/virtual-drones',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({lat:pick[0],lon:pick[1]})}).then(r=>r.json());
  msg(d.ok?d.label+' added. Open controls to fly it.':d.error,d.ok);load()}
async function act(slot,action,extra){const d=await fetch('/api/virtual-drones/'+encodeURIComponent(slot),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action,...(extra||{})})}).then(r=>r.json());
  if(!d.ok)msg(d.error,false);load()}
function moveHome(slot){if(!pick){msg('Click the map first to choose the new home point.',false);return}act(slot,'home',{lat:pick[0],lon:pick[1]})}
async function removeVd(slot){if(!confirm('Remove this virtual drone?'))return;await fetch('/api/virtual-drones/'+encodeURIComponent(slot),{method:'DELETE'});load()}
async function setAuto(on){await fetch('/api/virtual-drones',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({demo_auto:on})});
  msg(on?'Demo mode on: automatic missions may use virtual drones.':'Demo mode off: automatic missions use real drones only.',true)}
load();setInterval(load,1000);
</script>""", active="virtual")


@app.route("/drone-grid")
def drone_grid_page():
    return DRONE_GRID_PAGE


DRONE_GRID_PAGE = hud_page("Drone Grid", r"""
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
.dg-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.dg-bar select{width:auto}
.dg-grid{display:grid;gap:10px;grid-template-columns:repeat(var(--cols,2),minmax(0,1fr))}
.dg-tile{position:relative;background:#000;border:1px solid #155879;border-radius:5px;overflow:hidden;aspect-ratio:16/9;cursor:pointer}
.dg-tile.sel{box-shadow:0 0 0 2px #5bd9ff}
.dg-tile .live-slot,.dg-tile .dg-vcam{position:absolute;inset:0;width:100%;height:100%}
.dg-tile .live-slot video{width:100%;height:100%;object-fit:contain}
.dg-head{position:absolute;left:0;right:0;top:0;z-index:600;display:flex;justify-content:space-between;align-items:center;gap:6px;padding:7px 9px;background:linear-gradient(rgba(2,10,16,.85),rgba(2,10,16,0))}
.dg-name{color:#e9f8ff;font:bold 12px Arial;letter-spacing:1px}
.dg-name i{display:inline-block;width:8px;height:8px;border-radius:50%;background:#53636d;margin-right:6px}
.dg-name i.ok{background:#26ee89}.dg-name i.half{background:#ffb23c}
.dg-tag{font-size:9px;color:#ffcf7a;border:1px solid #7a5a12;border-radius:3px;padding:1px 4px;margin-left:6px}
.dg-btns{display:flex;gap:5px}
.dg-btns a,.dg-btns button{background:rgba(3,16,26,.85);border:1px solid #155879;color:#9edfff;border-radius:3px;padding:4px 8px;font:bold 10px Arial;letter-spacing:.5px;text-decoration:none;cursor:pointer}
.dg-hud{position:absolute;left:8px;right:8px;bottom:8px;z-index:600;display:flex;gap:5px;flex-wrap:wrap}
.dg-hud span{background:rgba(3,16,26,.85);border:1px solid #155879;color:#9edfff;padding:3px 7px;border-radius:3px;font:bold 10px Arial}
.dg-hud b{color:#fff}
.dg-off{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#6d8b9d;font:bold 12px Arial;letter-spacing:1px;text-align:center;padding:20px}
.dg-x{position:absolute;left:50%;top:50%;width:40px;height:40px;margin:-20px 0 0 -20px;border:2px solid rgba(91,217,255,.8);border-radius:50%;z-index:500;pointer-events:none}
.dg-grid:fullscreen{background:#000;padding:8px;align-content:center;overflow:auto}
.dg-grid:fullscreen .dg-tile{aspect-ratio:auto;height:calc((100vh - 16px - (var(--rows,1) - 1) * 10px) / var(--rows,1))}
.dg-tile:fullscreen{aspect-ratio:auto;border:0;border-radius:0}
.dg-grid.solo .dg-tile:not(.sel){display:none}
.dg-grid.solo{grid-template-columns:1fr}
@media(max-width:760px){.dg-grid{grid-template-columns:1fr}}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Drone</div><h1 class="page-title">Drone Grid</h1>
<div class="page-sub">Every drone live at once. Click a drone to select it, double-click (or ⛶) for its own full screen, or put the whole grid full screen.</div></div>
<div class="actions"><span class="state" id="dgState"><i class="dot warn"></i>LOADING</span></div></div>
<div class="dg-bar">
<button class="hud-btn primary" onclick="fullAll()">⛶ Full screen: all drones</button>
<button class="hud-btn" id="soloBtn" onclick="toggleSolo()">Show selected only</button>
<label style="margin:0;display:flex;gap:6px;align-items:center;text-transform:none;letter-spacing:0">Layout
<select id="dgCols" onchange="layout()"><option value="0">Auto</option><option value="1">1 per row</option><option value="2">2 per row</option><option value="3">3 per row</option><option value="4">4 per row</option></select></label>
<a class="hud-btn" href="/drone-control" style="text-decoration:none">← Drone controls</a>
</div>
<div class="dg-grid" id="dgGrid"></div>
<p class="muted" id="dgEmpty" style="display:none">No drones yet. Add one on the Drone page, or add a virtual drone on the Virtual drones tab.</p>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const fmt=(v,d=1)=>v==null||isNaN(v)?'–':Number(v).toFixed(d);
const tiles={};let selected=null,solo=false;
const whenPlayer=fn=>window.attachLiveCamera?fn():window.addEventListener('live-player-ready',fn,{once:true});
function tileFor(x){const t=document.createElement('div');t.className='dg-tile';t.dataset.drone=x.drone;
  t.innerHTML=(x.virtual?'<div class="dg-vcam"></div><div class="dg-x"></div>':'<div class="live-slot" data-live-camera="'+esc(x.drone)+'"></div>')
    +'<div class="dg-off" style="display:none"></div>'
    +'<div class="dg-head"><span class="dg-name"><i></i>'+esc(x.label).toUpperCase()+(x.virtual?'<span class="dg-tag">VIRTUAL</span>':'')+'</span>'
    +'<span class="dg-btns"><a href="/drone-control?drone='+encodeURIComponent(x.drone)+'" onclick="event.stopPropagation()">CONTROLS</a>'
    +'<button type="button" title="Full screen this drone">⛶</button></span></div><div class="dg-hud"></div>';
  t.querySelector('button').addEventListener('click',e=>{e.stopPropagation();full(t)});
  t.addEventListener('click',()=>select(x.drone));
  t.addEventListener('dblclick',()=>full(t));
  if(!x.virtual)whenPlayer(()=>window.attachLiveCamera(t.querySelector('.live-slot')));
  return t}
function full(el){if(document.fullscreenElement)document.exitFullscreen();else el.requestFullscreen?.()}
function fullAll(){const g=$('dgGrid');if(document.fullscreenElement){document.exitFullscreen();return}g.requestFullscreen?.()}
function select(d){selected=d;Object.values(tiles).forEach(t=>t.classList.toggle('sel',t.dataset.drone===d))}
function toggleSolo(){if(!selected&&!solo){const f=Object.keys(tiles)[0];if(f)select(f)}solo=!solo;$('dgGrid').classList.toggle('solo',solo);
  $('soloBtn').textContent=solo?'Show all drones':'Show selected only';layout()}
function layout(){const n=solo?1:Object.keys(tiles).length||1,pick=+$('dgCols').value;
  const cols=solo?1:pick||(n<=1?1:n<=4?2:3),rows=Math.ceil(n/cols);
  $('dgGrid').style.setProperty('--cols',cols);$('dgGrid').style.setProperty('--rows',rows);
  Object.values(tiles).forEach(t=>t._map&&t._map.invalidateSize())}
function vcam(t,x){if(typeof L==='undefined'||!x.lat)return;const z=x.altitude>90?16:x.altitude>45?17:x.altitude>15?18:19;
  if(!t._map){t._map=L.map(t.querySelector('.dg-vcam'),{zoomControl:false,attributionControl:false,dragging:false,scrollWheelZoom:false,doubleClickZoom:false,boxZoom:false,keyboard:false,touchZoom:false});
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19}).addTo(t._map);t._map.setView([x.lat,x.lon],z)}
  else t._map.setView([x.lat,x.lon],z,{animate:false})}
function paint(t,x){const dot=x.drone_connected?'ok':x.phone_connected?'half':'';t.querySelector('.dg-name i').className=dot;
  const off=t.querySelector('.dg-off'),down=!x.phone_connected||!x.drone_connected;
  off.style.display=down?'flex':'none';off.textContent=x.over_limit?'OVER LICENCE LIMIT':!x.phone_connected?'PHONE NOT CONNECTED':!x.drone_connected?'DRONE OFF':'';
  const state=x.mission?(x.mission==='route'?'ROUTE':'RESPONSE'):x.flying?'FLYING':'ON GROUND';
  t.querySelector('.dg-hud').innerHTML=down?'':`<span>${state}</span><span>ALT <b>${fmt(x.altitude)}</b> m</span><span>SPD <b>${fmt(x.speed)}</b> m/s</span>`
    +`<span>BAT <b>${x.battery??'–'}</b>%</span><span>GPS <b>${x.gps??'–'}</b></span><span>HOME <b>${fmt(x.distance_home,0)}</b> m</span>`;
  if(x.virtual)vcam(t,x)}
async function load(){let d;try{d=await fetch('/api/drone/links',{cache:'no-store'}).then(r=>r.json())}catch(e){return}if(!d.ok)return;
  const g=$('dgGrid'),seen=new Set();
  d.drones.forEach(x=>{seen.add(x.drone);if(!tiles[x.drone]){tiles[x.drone]=tileFor(x);g.appendChild(tiles[x.drone]);layout()}paint(tiles[x.drone],x)});
  Object.keys(tiles).filter(k=>!seen.has(k)).forEach(k=>{const s=tiles[k].querySelector('.live-slot');if(s)window.detachLiveCamera?.(s);tiles[k].remove();delete tiles[k];layout()});
  const live=d.drones.filter(x=>x.drone_connected).length;
  $('dgState').innerHTML='<i class="dot '+(live?'good':'warn')+'"></i>'+live+' / '+d.drones.length+' DRONES LINKED';
  $('dgEmpty').style.display=d.drones.length?'none':''}
document.addEventListener('fullscreenchange',()=>setTimeout(layout,100));
window.addEventListener('resize',layout);
load();setInterval(load,1000);
</script>""", active="drone")
_body_end = DRONE_GRID_PAGE.rfind("</body>")
DRONE_GRID_PAGE = DRONE_GRID_PAGE[:_body_end] + LIVE_PLAYER_HTML + DRONE_GRID_PAGE[_body_end:]


@app.route("/drone-control")
def drone_control_page():
    slot = request.args.get("drone") or DRONE_CAMERA_NAME
    if slot not in drone_slots():
        slot = DRONE_CAMERA_NAME
    page = DRONE_CONTROL_PAGE
    if is_virtual(slot):
        page = page.replace('<div class="live-slot" data-live-camera="drone"></div>',
                            '<div id="vcam" style="position:absolute;inset:0"></div><div class="vcam-x"></div>'
                            '<div class="vcam-tag">VIRTUAL CAMERA · SIMULATED VIEW</div>')
    return (page.replace('data-live-camera="drone"', f'data-live-camera="{slot}"')
            .replace("const DRONE='drone';", f"const DRONE={json.dumps(slot)};")
            .replace("<title>", f"<title>{drone_label(slot)} · ", 1)
            .replace('<h1 class="page-title">Drone Control</h1>', f'<h1 class="page-title">Drone Control · {drone_label(slot)}</h1>', 1))


DRONE_CONTROL_PAGE = hud_page("Drone Control", r"""
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
.dc-grid{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(330px,1fr);gap:16px;align-items:start}
.dc-video{aspect-ratio:16/9;position:relative;background:#000}
.dc-hud{position:absolute;left:10px;bottom:10px;z-index:4;display:flex;gap:6px;flex-wrap:wrap}
.dc-hud span{background:rgba(3,16,26,.85);border:1px solid #155879;color:#9edfff;padding:5px 8px;border-radius:3px;font:bold 11px Arial,sans-serif;letter-spacing:.5px}
.dc-hud span b{color:#fff}
.dc-btns{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.dc-btns .hud-btn{min-height:44px}
.dc-big{font-size:12px!important}
.hud-btn.warn{color:#ffcf7a;border-color:#7a5a12;background:rgba(125,90,12,.14)}
.dc-tel{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.dc-tel div{background:#05131d;border:1px solid #153c56;border-radius:4px;padding:8px 10px}
.dc-tel small{display:block;color:#6d8b9d;font-size:9px;letter-spacing:1.5px;text-transform:uppercase}
.dc-tel b{color:#e9f8ff;font-size:15px}
#dcMap{height:260px;border:1px solid #155879;border-radius:5px;background:#020a10}
.dc-keys{display:grid;grid-template-columns:repeat(2,1fr);gap:4px 14px;font-size:12px;color:#9edfff}
.dc-keys kbd{display:inline-block;min-width:22px;text-align:center;padding:2px 5px;border:1px solid #155879;border-radius:3px;background:#020a10;color:#5bd9ff;font:bold 11px Arial}
.dc-ctl-on{box-shadow:0 0 0 2px #26ee89 inset}
.dc-pair{display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.dc-pair .qr{background:#fff;border-radius:4px;padding:4px}
.dc-fleet{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 14px}
.dc-fleet a,.dc-fleet button{display:flex;align-items:center;gap:7px;padding:8px 12px;border:1px solid #155879;border-radius:4px;background:#05131d;color:#9edfff;text-decoration:none;font:bold 12px Arial,sans-serif;letter-spacing:.5px;cursor:pointer}
.dc-fleet a.on{border-color:#5bd9ff;background:rgba(53,202,255,.14);color:#fff;box-shadow:0 0 0 1px #5bd9ff inset}
.dc-fleet a small{color:#6d8b9d;font-weight:normal}
.dc-fleet i{width:8px;height:8px;border-radius:50%;background:#53636d;display:inline-block}
.dc-fleet i.ok{background:#26ee89}.dc-fleet i.half{background:#ffb23c}
.dc-fleet button:disabled{opacity:.5;cursor:not-allowed}
.vcam-x{position:absolute;left:50%;top:50%;width:46px;height:46px;margin:-23px 0 0 -23px;border:2px solid rgba(91,217,255,.85);border-radius:50%;z-index:500;pointer-events:none}
.vcam-tag{position:absolute;right:10px;top:10px;z-index:500;background:rgba(3,16,26,.85);border:1px solid #7a5a12;color:#ffcf7a;padding:4px 8px;border-radius:3px;font:bold 10px Arial;letter-spacing:1px}
@media(max-width:1000px){.dc-grid{grid-template-columns:1fr}}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Drone</div><h1 class="page-title">Drone Control</h1>
<div class="page-sub">Fly the drone from this PC through the Drone Link app on the controller's phone. Keep the drone in sight — the pilot's controller can take over at any time.</div></div>
<div class="actions"><span class="state" id="linkState"><i class="dot bad"></i>PHONE NOT CONNECTED</span></div></div>
<div class="dc-fleet" id="fleet"></div>

<section class="panel" id="pairPanel"><div class="panel-head"><div class="panel-title">⌁ Connect the phone</div><div class="live">PAIRING</div></div>
<div class="panel-body dc-pair"><div class="qr" id="pairQr"></div><div style="flex:1;min-width:240px">
<div class="muted">1. Plug the Android phone into the RC-N1 controller and turn on the drone.<br>2. Open <b>Drone Link</b> on the phone and tap <b>Scan pairing code</b>.<br>3. Scan this QR code. The phone and this PC must be on the same Wi-Fi.</div>
<div class="muted" style="margin-top:10px">PC address: <code id="pairAddr">…</code></div>
<div class="actions" style="margin-top:12px"><button class="hud-btn danger" onclick="resetPair()">New pairing code</button></div>
<div id="pairMsg" class="hud-msg"></div></div></div></section>

<div class="dc-grid">
<div>
<section class="panel"><div class="panel-head"><div class="panel-title">✈ Live view</div><div class="live" id="flyState">ON GROUND</div></div>
<div class="dc-video"><div class="live-slot" data-live-camera="drone"></div>
<div class="dc-hud"><span>ALT <b id="hAlt">–</b> m</span><span>DIST <b id="hDist">–</b> m</span><span>SPD <b id="hSpd">–</b> m/s</span><span>BAT <b id="hBat">–</b>%</span><span>GPS <b id="hGps">–</b></span><span>SIGNAL <b id="hSig">–</b></span></div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">⌖ Map</div><div class="live" id="mapState"></div></div>
<div class="panel-body"><div id="dcMap"></div><div class="muted" id="coords" style="margin-top:8px"></div></div></section>
</div>
<div>
<section class="panel"><div class="panel-head"><div class="panel-title">◉ Flight</div><div class="live" id="modeState"></div></div>
<div class="panel-body">
<div class="dc-btns">
<button class="hud-btn primary dc-big" onclick="takeoff()">Take off</button>
<button class="hud-btn warn dc-big" onclick="cmd('land')">Land</button>
<button class="hud-btn warn dc-big" onclick="cmd('go_home',{},'Fly back to the home point and land?')">Return home</button>
<button class="hud-btn danger dc-big" style="grid-column:1/-1;min-height:52px" onclick="stopAll()">■ STOP — hover in place (Space)</button>
<button class="hud-btn" onclick="cmd('cancel_land')">Cancel landing</button>
<button class="hud-btn primary dc-big" id="confirmLand" style="grid-column:1/-1;display:none" onclick="cmd('confirm_land')">▼ Confirm landing — drone is waiting just above the ground</button>
<button class="hud-btn" onclick="cmd('cancel_go_home')">Cancel return</button>
<button class="hud-btn" id="ctlBtn" onclick="toggleControl()">Keyboard control: OFF</button>
</div>
<label for="speed">Speed limit <span id="speedVal" class="muted"></span></label>
<input id="speed" type="range" min="0.1" max="0.5" step="0.05" value="0.3" style="width:100%" oninput="speedVal.textContent=Math.round(this.value*100)+'%'">
<div class="dc-keys" style="margin-top:12px">
<div><kbd>W</kbd><kbd>S</kbd> forward / back</div><div><kbd>A</kbd><kbd>D</kbd> left / right</div>
<div><kbd>↑</kbd><kbd>↓</kbd> up / down (hold ↑ on the ground: take off · hold ↓ near the ground: land)</div><div><kbd>←</kbd><kbd>→</kbd> turn</div>
<div><kbd>Space</kbd> stop &amp; hover</div><div>🎮 Gamepad works too</div></div>
<div id="cmdMsg" class="hud-msg"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">🗺️ Auto-fly route</div><div class="live" id="routeState"></div></div>
<div class="panel-body">
<div class="muted">Click the map to add stops; the drone takes off if needed and flies through them in order (one stop = fly to a point). Every stop must be within <span id="routeMax">500</span> m of home. STOP, any flying key or the controller cancels it.</div>
<div class="actions" style="margin-top:10px"><button class="hud-btn" onclick="undoPoint()">Undo</button><button class="hud-btn" onclick="clearRoute()">Clear</button>
<select id="routeSel" onchange="loadRoute(this.value)" style="flex:1;min-width:140px"><option value="">Saved routes…</option></select></div>
<div id="routeInfo" class="muted" style="margin-top:8px">No stops yet.</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:0 10px">
<div><label for="rtAlt">Height (m)</label><input id="rtAlt" type="number" min="10" max="120" value="30" oninput="routeInfo()"></div>
<div><label for="rtSpeed">Speed (m/s)</label><input id="rtSpeed" type="number" min="1" max="8" value="5" oninput="routeInfo()"></div>
<div><label for="rtPause">Pause (s)</label><input id="rtPause" type="number" min="0" max="120" value="5" oninput="routeInfo()"></div>
<div><label for="rtEnd">At the end</label><select id="rtEnd"><option value="home">Return home</option><option value="hover">Hover at last stop</option><option value="land">Land at last stop</option></select></div>
</div>
<label style="margin-top:10px;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0"><input type="checkbox" id="rtLoop" onchange="routeInfo()"> <b>Repeat the route again and again</b> until you press Stop route</label>
<label style="margin-top:6px;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;flex-wrap:wrap"><input type="checkbox" id="rtRelay"> Relay: at
<input id="rtSwap" type="number" min="20" max="50" value="20" style="width:64px">% battery the drone returns home and the next ready drone takes off and continues the patrol</label>
<div class="muted" style="margin-top:4px">A continuous patrol always sends the drone home at that battery level; without relay the patrol then ends. Each drone needs its own phone and controller (or use virtual drones).</div>
<div class="actions" style="margin-top:12px"><input id="rtName" placeholder="Route name" style="flex:1;min-width:120px"><button class="hud-btn" onclick="saveRoute()">Save</button><button class="hud-btn danger" onclick="deleteRoute()">Delete</button></div>
<div class="actions" style="margin-top:8px"><button class="hud-btn primary" onclick="flyRoute()">Fly route</button><button class="hud-btn danger" onclick="stopRoute()">Stop route</button></div>
<div id="routeMsg" class="hud-msg"></div>
<div style="margin-top:16px;border-top:1px solid #123447;padding-top:12px"><b style="color:#5bd9ff;font-size:11px;letter-spacing:1.5px">🗓 SCHEDULED PATROLS</b>
<div class="muted" style="margin-top:6px">Runs a saved route on chosen days. <b>Ask first</b> sends you a Telegram Start/Skip message; <b>auto-start</b> flies after the safety checks. The drone and controller must be on and connected at patrol time, and a pilot must be able to take over.</div>
<div id="schedList" style="margin-top:8px"></div>
<div class="actions" style="margin-top:8px;align-items:center"><select id="scRoute" style="flex:1;min-width:120px"></select><input id="scTime" type="time" value="02:00" style="width:110px">
<span id="scDays" style="display:flex;gap:4px;flex-wrap:wrap"></span><select id="scDrone" style="min-width:120px" title="Which drone flies it"><option value="">Any ready drone</option></select></div>
<div class="actions" style="margin-top:8px;align-items:center"><label style="margin:0;display:flex;gap:6px;align-items:center;text-transform:none;letter-spacing:0"><input type="checkbox" id="scAuto"> Auto-start (no confirmation)</label>
<button class="hud-btn primary" onclick="addSched()">Add schedule</button></div>
<div id="schedMsg" class="hud-msg"></div></div>

</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">🚨 Drone response &amp; Telegram</div><div class="live" id="respState"></div></div>
<div class="panel-body">
<div class="muted">When a camera sees an unknown person or vehicle, the Telegram alert gets a <b>Send drone</b> button. Set each camera's place on the map so the drone knows where to fly.</div>
<div id="respCams" style="margin-top:10px"></div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0 10px">
<div><label for="rAlt">Height (m)</label><input id="rAlt" type="number" min="10" max="120"></div>
<div><label for="rSpeed">Speed (m/s)</label><input id="rSpeed" type="number" min="1" max="8"></div>
<div><label for="rHover">Hover (s)</label><input id="rHover" type="number" min="10" max="600"></div>
<div><label for="rBatt">Min battery %</label><input id="rBatt" type="number" min="20" max="90"></div>
<div><label for="rBrief">Morning briefing</label><input id="rBrief" type="time"></div>
<div style="display:flex;flex-direction:column;justify-content:flex-end;gap:6px;padding-bottom:4px">
<label style="margin:0;display:flex;gap:6px;align-items:center"><input type="checkbox" id="rReturn"> Auto return home</label>
<label style="margin:0;display:flex;gap:6px;align-items:center"><input type="checkbox" id="rBriefOn"> Send briefing</label></div>
</div>
<div class="actions" style="margin-top:12px"><button class="hud-btn primary" onclick="saveResp()">Save</button><button class="hud-btn danger" onclick="recallResp()">Recall drone</button>
<button class="hud-btn" onclick="briefNow()">Send briefing now</button></div>
<div id="respMsg" class="hud-msg"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">▣ Camera</div></div>
<div class="panel-body"><div class="dc-btns">
<button class="hud-btn" onclick="cmd('gimbal',{pitch:0})">Look ahead</button>
<button class="hud-btn" onclick="cmd('gimbal',{pitch:-45})">Tilt 45°</button>
<button class="hud-btn" onclick="cmd('gimbal',{pitch:-90})">Look down</button>
<button class="hud-btn" onclick="cmd('photo')">Photo</button>
<button class="hud-btn" onclick="cmd('record_start')">Record</button>
<button class="hud-btn" onclick="cmd('record_stop')">Stop rec</button>
</div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">◷ Telemetry</div></div>
<div class="panel-body"><div class="dc-tel">
<div><small>Height</small><b id="tAlt">–</b></div><div><small>Distance home</small><b id="tDist">–</b></div>
<div><small>Speed</small><b id="tSpd">–</b></div><div><small>Heading</small><b id="tHdg">–</b></div>
<div><small>Battery</small><b id="tBat">–</b></div><div><small>GPS satellites</small><b id="tGps">–</b></div>
<div><small>Flight mode</small><b id="tMode">–</b></div><div><small>Control</small><b id="tCtl">–</b></div>
</div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">⚙ Testing</div><div class="live" id="simState"></div></div>
<div class="panel-body"><div class="muted">Simulator: the drone stays on the ground with motors locked while it pretends to fly. <b>Remove the propellers first.</b></div>
<div class="actions" style="margin-top:10px"><button class="hud-btn" onclick="simOn()">Start simulator</button><button class="hud-btn" onclick="cmd('sim_off')">Stop simulator</button>
<button class="hud-btn" onclick="cmd('stream_on')">Restart video</button></div>
<div id="events" class="muted" style="margin-top:12px;max-height:150px;overflow:auto"></div></div></section>
</div></div>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const DRONE='drone';
{const f=window.fetch.bind(window);
 window.fetch=(u,o)=>f(typeof u==='string'&&/^\/api\/(drone\/|routes\/fly|response\/dispatch)/.test(u)?u+(u.includes('?')?'&':'?')+'drone='+encodeURIComponent(DRONE):u,o)}
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const fmt=(v,d=1)=>v==null||isNaN(v)?'–':Number(v).toFixed(d);
async function loadFleet(){try{const d=await fetch('/api/drone/links',{cache:'no-store'}).then(r=>r.json());if(!d.ok)return;
  const many=d.drones.length>1;droneNames=Object.fromEntries(d.drones.map(x=>[x.drone,x.label]));
  const sel=$('scDrone');if(sel&&sel.options.length!==d.drones.length+1){const v=sel.value;sel.innerHTML='<option value="">Any ready drone</option>'+d.drones.map(x=>`<option value="${esc(x.drone)}">${esc(x.label)}</option>`).join('');sel.value=v;sel.style.display=many?'':'none'}
  $('fleet').innerHTML=d.drones.map(x=>{const dot=x.drone_connected?'ok':x.phone_connected?'half':'';
    const info=x.over_limit?'over licence':x.mission?(x.mission==='route'?'on route':'responding'):x.drone_connected?(x.flying?'flying':'ready')+(x.battery!=null?' · '+x.battery+'%':''):x.phone_connected?'drone off':'not paired';
    return `<a href="/drone-control?drone=${encodeURIComponent(x.drone)}" class="${x.drone===DRONE?'on':''}"><i class="${dot}"></i>${esc(x.label)} <small>${esc(info)}</small></a>`}).join('')
    +`<button onclick="addDroneSlot()" ${d.can_add?'':'disabled'} title="${esc(d.message||'')}">+ Add drone <small>${d.used??'?'} of ${d.limit??'∞'}</small></button>`
    +`<a href="/drone-grid">▦ Grid view</a>`;
  if(!many&&!d.can_add)$('fleet').querySelector('button').style.display='none';
  $('fleet').querySelector('a[href="/drone-grid"]').style.display=many?'':'none';
  others=d.drones.filter(x=>x.drone!==DRONE&&x.lat&&x.lon);if(typeof drawOthers==='function')drawOthers()}catch(e){}}
async function addDroneSlot(){if(!confirm('Add another drone? It gets its own pairing QR code and video. Frigate restarts (about 20 s).'))return;
  const d=await fetch('/api/drone/add',{method:'POST'}).then(r=>r.json());
  if(d.ok){location.href='/drone-control?drone='+encodeURIComponent(d.name)}else alert(d.error||'Could not add a drone.')}
let others=[],oMarks=[],droneNames={};
let vcam=null;
function vcamUpdate(t){if(!$('vcam')||typeof L==='undefined'||!t.lat)return;
  const z=t.altitude>90?16:t.altitude>45?17:t.altitude>15?18:19;
  if(!vcam){vcam=L.map('vcam',{zoomControl:false,attributionControl:false,dragging:false,scrollWheelZoom:false,doubleClickZoom:false,boxZoom:false,keyboard:false,touchZoom:false});
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19}).addTo(vcam);vcam.setView([t.lat,t.lon],z)}
  else vcam.setView([t.lat,t.lon],z,{animate:false})}
function drawOthers(){if(!map||!window.L)return;oMarks.forEach(m=>m.remove());
  oMarks=others.map(x=>L.circleMarker([x.lat,x.lon],{radius:7,color:'#ffb23c',fillColor:'#ffb23c',fillOpacity:.8}).bindTooltip(x.label,{permanent:true,direction:'right',className:''}).addTo(map))}
let st={},control=false,map=null,dMark=null,hMark=null,trail=null,keys=new Set(),lastStickZero=true;
function msg(t,ok){const e=$('cmdMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
async function cmd(c,args,confirmText){if(confirmText&&!confirm(confirmText))return;msg(c.replace('_',' ')+'…');
  try{const r=await fetch('/api/drone/command',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({cmd:c,args:args||{}})});const d=await r.json();
    msg(d.ok?c.replace(/_/g,' ')+': done':d.error||'Failed',d.ok);return d.ok}catch(e){msg('Lost contact with the system',false)}}
function takeoff(){const sim=(st.telemetry||{}).simulator;
  cmd('takeoff',{},sim?'SIMULATOR take-off (motors stay locked). Continue?':'⚠ REAL TAKE-OFF: the simulator is OFF and the motors WILL start. Propellers on, people clear, drone in sight, pilot holding the controller?')}
async function stopAll(){keys.clear();await sendStick(true);cmd('hover')}
async function toggleControl(){if(!control){if(!(await cmd('control_on',{speed:+$('speed').value})))return;control=true}
  else{await sendStick(true);await cmd('control_off');control=false}
  $('ctlBtn').textContent='Keyboard control: '+(control?'ON':'OFF');$('ctlBtn').classList.toggle('dc-ctl-on',control)}
function stickFromInputs(){let x=0,y=0,z=0,r=0;
  if(keys.has('KeyA'))x-=1;if(keys.has('KeyD'))x+=1;if(keys.has('KeyW'))y+=1;if(keys.has('KeyS'))y-=1;
  if(keys.has('ArrowUp'))z+=1;if(keys.has('ArrowDown'))z-=1;if(keys.has('ArrowLeft'))r-=1;if(keys.has('ArrowRight'))r+=1;
  const gp=(navigator.getGamepads?[...navigator.getGamepads()]:[]).find(g=>g&&g.connected);
  if(gp){const dz=v=>Math.abs(v)<0.12?0:v;r+=dz(gp.axes[0]);z+=-dz(gp.axes[1]);x+=dz(gp.axes[2]);y+=-dz(gp.axes[3]);
    if(gp.buttons[1]&&gp.buttons[1].pressed){stopAll()}}
  const c=v=>Math.max(-1,Math.min(1,v));return{x:c(x),y:c(y),z:c(z),r:c(r)}}
async function sendStick(zero){const s=zero?{x:0,y:0,z:0,r:0}:stickFromInputs();const isZero=!s.x&&!s.y&&!s.z&&!s.r;
  if(isZero&&lastStickZero&&!zero)return;lastStickZero=isZero;
  try{await fetch('/api/drone/stick',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(s)})}catch(e){}}
setInterval(()=>{if(control&&document.hasFocus())sendStick(false)},100);
window.addEventListener('blur',()=>{keys.clear();if(control)sendStick(true)});
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'&&e.target.type!=='range')return;
  if(e.code==='Space'){e.preventDefault();stopAll();return}
  if(['KeyW','KeyA','KeyS','KeyD','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.code)){e.preventDefault();
    if(control)keys.add(e.code);else msg('Click “Keyboard control: OFF” to turn it ON first — then W/A/S/D and the arrow keys fly the drone.',false)}});
document.addEventListener('keyup',e=>keys.delete(e.code));
function initMap(lat,lon){if(map||typeof L==='undefined')return;map=L.map('dcMap',{zoomControl:true}).setView([lat,lon],18);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:20,attribution:'© OpenStreetMap'}).addTo(map);
  trail=L.polyline([],{color:'#36cfff',weight:2}).addTo(map);
  map.on('click',e=>locFor?saveCamLoc(e.latlng.lat,e.latlng.lng):addPoint(e.latlng.lat,e.latlng.lng))}
function distM(a,b,c,d){const R=6371000,p1=a*Math.PI/180,p2=c*Math.PI/180,dp=(c-a)*Math.PI/180,dl=(d-b)*Math.PI/180;
  const x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))}
function drone_icon(hdg){return L.divIcon({className:'',iconSize:[26,26],iconAnchor:[13,13],html:`<div style="transform:rotate(${hdg||0}deg);color:#25c7ff;font-size:24px;line-height:26px;text-align:center;text-shadow:0 0 6px #000">▲</div>`})}
function render(){const t=st.telemetry||{};const on=st.phone_connected,fresh=st.telemetry_fresh;
  $('linkState').innerHTML=!st.allowed?'<i class="dot bad"></i>NOT LICENSED':on?(t.drone_connected?'<i class="dot good"></i>DRONE LINKED':'<i class="dot warn"></i>PHONE CONNECTED · DRONE OFF'):'<i class="dot bad"></i>PHONE NOT CONNECTED';
  $('pairPanel').style.display=on?'none':'';
  $('flyState').textContent=t.flying?'IN FLIGHT':(t.motors_on?'MOTORS ON':'ON GROUND');
  $('modeState').textContent=t.simulator?'SIMULATOR':'';$('simState').textContent=t.simulator?'SIMULATOR ON':'';
  const sp=t.speed;[['hAlt','tAlt',t.altitude,' m'],['hDist','tDist',t.distance_home,' m'],['hSpd','tSpd',sp,' m/s']].forEach(([a,b,v,u])=>{$(a).textContent=fmt(v);$(b).textContent=fmt(v)+(v==null?'':u)});
  $('hBat').textContent=t.battery??'–';$('tBat').textContent=t.battery==null?'–':t.battery+'%';$('hGps').textContent=t.gps_satellites??'–';$('tGps').textContent=t.gps_satellites??'–';
  $('hSig').textContent=t.signal==null?'–':t.signal+'%';$('tHdg').textContent=t.heading==null?'–':Math.round((t.heading+360)%360)+'°';$('tMode').textContent=t.flight_mode||'–';
  $('tCtl').textContent=t.control||'–';$('confirmLand').style.display=t.landing_confirm_needed?'':'none';
  if(control&&t.control&&t.control!=='PC'){control=false;$('ctlBtn').textContent='Keyboard control: OFF';$('ctlBtn').classList.remove('dc-ctl-on');msg(/LANDING|GO_HOME/.test(t.flight_mode||'')?'Keyboard control ended: the drone is landing / returning home by itself.':'The pilot took control on the remote controller.',false)}
  if(t.lat&&t.lon){initMap(t.lat,t.lon);if(map){const p=[t.lat,t.lon];dMark=dMark||L.marker(p).addTo(map);dMark.setLatLng(p).setIcon(drone_icon(t.heading));
    trail.addLatLng(p);if(t.home_lat&&t.home_lon){hMark=hMark||L.circleMarker([t.home_lat,t.home_lon],{radius:7,color:'#2aea88'}).bindTooltip('Home').addTo(map);hMark.setLatLng([t.home_lat,t.home_lon])}}
    $('coords').textContent=t.lat.toFixed(6)+', '+t.lon.toFixed(6)}
  $('mapState').textContent=typeof L==='undefined'?'MAP NEEDS INTERNET':'';
  const m=t.mission;if(m)$('flyState').textContent='AUTO-FLY · '+m.state+(m.distance>=0?' · '+Math.round(m.distance)+' m to stop':'');
  vcamUpdate(t);
  $('events').innerHTML=(st.events||[]).slice().reverse().map(e=>`<div>${new Date(e.at*1000).toLocaleTimeString()} · ${esc(e.msg)}</div>`).join('')}
const DAYS=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];let scheds=[];
function scmsg(t,ok){const e=$('schedMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
function renderScheds(){const names=Object.keys(routes);$('scRoute').innerHTML=names.length?names.map(n=>`<option>${esc(n)}</option>`).join(''):'<option value="">Save a route first</option>';
  if(!$('scDays').children.length)$('scDays').innerHTML=DAYS.map((d,i)=>`<label style="margin:0;display:flex;gap:3px;align-items:center;text-transform:none;letter-spacing:0;font-size:12px"><input type="checkbox" data-day="${i}" checked>${d}</label>`).join('');
  $('schedList').innerHTML=scheds.map((s,i)=>`<div class="hud-row"><div><b>${esc(s.route)}</b> at ${esc(s.time)}<div class="muted">${s.days.length===7?'Every day':s.days.map(d=>DAYS.at(d)).join(', ')} · ${s.auto_start?'auto-start':'asks first on Telegram'}${s.drone?' · '+esc(droneNames[s.drone]||s.drone):''}${s.enabled?'':' · paused'}</div></div>
    <div class="actions"><button class="hud-btn" onclick="toggleSched(${i})">${s.enabled?'Pause':'Resume'}</button><button class="hud-btn danger" onclick="delSched(${i})">Delete</button></div></div>`).join('')||'<p class="muted">No scheduled patrols.</p>'}
async function saveScheds(note){const d=await fetch('/api/response/settings',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({patrol_schedules:scheds})}).then(r=>r.json());
  if(d.ok){scheds=d.settings.patrol_schedules;scmsg(note,true)}else scmsg(d.error,false);renderScheds()}
function addSched(){const route=$('scRoute').value,days=[...$('scDays').querySelectorAll('input:checked')].map(x=>+x.dataset.day);
  if(!route){scmsg('Save a route first.',false);return}if(!days.length){scmsg('Choose at least one day.',false);return}
  const auto=$('scAuto').checked;if(auto&&!confirm('Auto-start flies the drone with no confirmation at '+$('scTime').value+'. Only use it when the drone and controller are on, the area is clear, and a pilot can take over. Continue?'))return;
  scheds=[...scheds,{route,time:$('scTime').value,days,enabled:true,auto_start:auto,drone:$('scDrone').value}];saveScheds('Schedule added.')}
function toggleSched(i){scheds=scheds.map((s,j)=>j===i?{...s,enabled:!s.enabled}:s);saveScheds('Updated.')}
function delSched(i){if(!confirm('Delete this schedule?'))return;scheds=scheds.filter((s,j)=>j!==i);saveScheds('Deleted.')}
async function loadScheds(){try{const d=await fetch('/api/response/settings').then(r=>r.json());scheds=d.settings.patrol_schedules||[];renderScheds()}catch(e){}}
let route=[],routes={},rLine=null,rMarks=[],rMax=500;
function rtmsg(t,ok){const e=$('routeMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
function addPoint(lat,lon){if(route.length>=25){rtmsg('25 stops maximum.',false);return}route.push({lat,lon});drawRoute()}
function undoPoint(){route.pop();drawRoute()}
function clearRoute(){route=[];drawRoute()}
function homePos(){const t=st.telemetry||{};return t.home_lat?[t.home_lat,t.home_lon]:(t.lat?[t.lat,t.lon]:null)}
function routeInfo(){const h=homePos();let len=0,far=[];
  route.forEach((p,i)=>{const prev=i?route[i-1]:(h?{lat:h[0],lon:h[1]}:null);if(prev)len+=distM(prev.lat,prev.lon,p.lat,p.lon);
    if(h&&distM(h[0],h[1],p.lat,p.lon)>rMax)far.push(i+1)});
  if(h&&route.length&&$('rtEnd').value==='home'){const l=route[route.length-1];len+=distM(l.lat,l.lon,h[0],h[1])}
  const sp=+$('rtSpeed').value||5,mins=(len/sp+(+$('rtAlt').value||30)/2+route.length*(+$('rtPause').value||0)+30)/60;
  $('routeInfo').innerHTML=route.length?`<b>${route.length}</b> stop${route.length>1?'s':''} · <b>${Math.round(len)} m</b> · about <b>${mins.toFixed(1)} min</b> (≈ ${Math.ceil(mins*3.5)}% battery)`+
    (far.length?` · <span style="color:#ff8a8a">stop ${far.join(', ')} beyond ${rMax} m</span>`:'')+(h?'':' · <span style="color:#ffbd66">drone position unknown</span>'):'No stops yet.'}
function drawRoute(){routeInfo();if(!map||typeof L==='undefined')return;rMarks.forEach(m=>map.removeLayer(m));rMarks=[];
  rLine=rLine||L.polyline([],{color:'#ffd23f',weight:3}).addTo(map);rLine.setLatLngs(route.map(p=>[p.lat,p.lon]));
  route.forEach((p,i)=>rMarks.push(L.marker([p.lat,p.lon],{icon:L.divIcon({className:'',iconSize:[22,22],iconAnchor:[11,11],
    html:`<div style="width:22px;height:22px;border-radius:50%;background:#ffd23f;color:#111;font:bold 12px Arial;display:flex;align-items:center;justify-content:center;box-shadow:0 0 6px #000">${i+1}</div>`})}).addTo(map)))}
async function loadRoutes(){try{const d=await fetch('/api/routes').then(r=>r.json());routes=d.routes||{};rMax=d.max_distance_m||500;$('routeMax').textContent=rMax;
  const sel=$('routeSel'),cur=sel.value;sel.innerHTML='<option value="">Saved routes…</option>'+Object.keys(routes).map(n=>`<option>${esc(n)}</option>`).join('');sel.value=cur;
  if(typeof renderScheds==='function'&&$('scRoute'))renderScheds();const r=d.run||{};$('routeState').textContent=r.active?('ROUTE '+r.name+' · '+r.message):(r.message||'')}catch(e){}}
function loadRoute(n){const r=routes[n];if(!r)return;route=r.points.map(p=>({...p}));$('rtAlt').value=r.alt;$('rtSpeed').value=r.speed;$('rtPause').value=r.pause;$('rtEnd').value=r.end;$('rtLoop').checked=!!r.loop;$('rtRelay').checked=!!r.relay;$('rtSwap').value=r.swap_at||20;$('rtName').value=n;drawRoute();
  if(map&&route.length)map.fitBounds(route.map(p=>[p.lat,p.lon]),{padding:[30,30]})}
function routeBody(){return{points:route,alt:+$('rtAlt').value,speed:+$('rtSpeed').value,pause:+$('rtPause').value,end:$('rtEnd').value,
  loop:$('rtLoop').checked,relay:$('rtRelay').checked,swap_at:+$('rtSwap').value||20}}
async function saveRoute(){if(!route.length){rtmsg('Draw at least one stop.',false);return}const d=await fetch('/api/routes',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({...routeBody(),name:$('rtName').value})}).then(r=>r.json());
  rtmsg(d.ok?'Route “'+d.name+'” saved.':d.error,d.ok);await loadRoutes();if(d.ok)$('routeSel').value=d.name}
async function deleteRoute(){const n=$('routeSel').value;if(!n||!confirm('Delete route “'+n+'”?'))return;await fetch('/api/routes',{method:'DELETE',headers:{'content-type':'application/json'},body:JSON.stringify({name:n})});rtmsg('Deleted.',true);loadRoutes()}
async function flyRoute(){if(!route.length){rtmsg('Click the map to add stops, or choose a saved route.',false);return}const sim=(st.telemetry||{}).simulator;
  if(!confirm((sim?'SIMULATOR: ':'REAL FLIGHT: the drone takes off if it is on the ground. ')+'Fly '+route.length+' stop'+(route.length>1?'s':'')+' at '+$('rtAlt').value+' m'
    +($('rtLoop').checked?', repeating the route until you press Stop route':'')+'? Keep the drone in sight.'))return;
  const d=await fetch('/api/routes/fly',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({...routeBody(),name:$('rtName').value||$('routeSel').value||'route'})}).then(r=>r.json());
  rtmsg(d.message||d.error,d.ok);loadRoutes()}
async function stopRoute(){await fetch('/api/routes/stop',{method:'POST'});rtmsg('Route stopped, drone hovering.',true);loadRoutes()}
setInterval(loadRoutes,3000);
let resp=null,locFor='',camMarks={};
function rmsg(t,ok){const e=$('respMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
async function loadResp(){try{const d=await fetch('/api/response/settings').then(r=>r.json());resp=d;const c=d.settings;
  $('rAlt').value=c.altitude_m;$('rSpeed').value=c.speed_ms;$('rHover').value=c.hover_seconds;$('rBatt').value=c.min_battery;$('rBrief').value=c.briefing_time;
  $('rReturn').checked=!!c.auto_return;$('rBriefOn').checked=!!c.briefing_enabled;renderResp()}catch(e){}}
function renderResp(){if(!resp)return;const locs=resp.settings.camera_locations||{},r=resp.response||{};
  $('respState').textContent=r.active?('RESPONDING: '+r.camera+' · '+r.phase):(resp.telegram?'TELEGRAM READY':'TELEGRAM NOT SET UP');
  $('respCams').innerHTML=(resp.cameras||[]).filter(n=>!/^drone/i.test(n)).map(n=>{const l=locs[n];return `<div class="hud-row"><div><b>${esc(n)}</b><div class="muted">${l?('📍 '+l.lat.toFixed(5)+', '+l.lon.toFixed(5)):'No location yet'}</div></div>
    <div class="actions"><button class="hud-btn" onclick="pickLoc('${esc(n)}')">${locFor===n?'Click the map…':(l?'Move':'Set on map')}</button>${l?`<button class="hud-btn primary" onclick="sendTo('${esc(n)}')">Send drone</button>`:''}</div></div>`}).join('')||'<p class="muted">No cameras yet.</p>';
  if(map&&typeof L!=='undefined'){for(const [n,l] of Object.entries(locs)){camMarks[n]=camMarks[n]||L.marker([l.lat,l.lon],{icon:L.divIcon({className:'',iconSize:[24,24],iconAnchor:[12,12],html:'<div style="font-size:20px;line-height:24px;text-shadow:0 0 6px #000">📹</div>'})}).bindTooltip(n).addTo(map);camMarks[n].setLatLng([l.lat,l.lon])}}}
function pickLoc(n){locFor=n;rmsg('Click the camera\'s position on the map.');renderResp()}
async function saveCamLoc(lat,lon){const n=locFor;locFor='';const locs={...(resp.settings.camera_locations||{}),[n]:{lat,lon}};
  const d=await fetch('/api/response/settings',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({camera_locations:locs})}).then(r=>r.json());
  if(d.ok){resp.settings=d.settings;rmsg('Location of '+n+' saved.',true)}else rmsg(d.error,false);renderResp()}
async function saveResp(){const body={altitude_m:+$('rAlt').value,speed_ms:+$('rSpeed').value,hover_seconds:+$('rHover').value,min_battery:+$('rBatt').value,
  briefing_time:$('rBrief').value,auto_return:$('rReturn').checked,briefing_enabled:$('rBriefOn').checked};
  const d=await fetch('/api/response/settings',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
  if(d.ok){resp.settings=d.settings;rmsg('Saved.',true);loadResp()}else rmsg(d.error,false)}
async function sendTo(n){const sim=(st.telemetry||{}).simulator;
  if(!confirm((sim?'SIMULATOR: ':'REAL FLIGHT: the drone takes off if it is on the ground. ')+'Send the drone to '+n+'? Keep it in sight.'))return;
  const d=await fetch('/api/response/dispatch',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({camera:n})}).then(r=>r.json());rmsg(d.message||d.error,d.ok);loadResp()}
async function recallResp(){const d=await fetch('/api/response/recall',{method:'POST'}).then(r=>r.json());rmsg(d.ok?'Drone returning home.':d.error,d.ok);loadResp()}
async function briefNow(){const d=await fetch('/api/assistant/briefing',{method:'POST'}).then(r=>r.json());rmsg(d.ok?'Briefing sent to Telegram.':d.error,d.ok)}
setInterval(()=>{if(!locFor)loadResp()},5000);
async function poll(){try{st=await fetch('/api/drone/link',{cache:'no-store'}).then(r=>r.json());render()}catch(e){}}
async function loadPair(){try{const d=await fetch('/api/drone/link/pair').then(r=>r.json());if(!d.ok){$('pairMsg').className='hud-msg bad';$('pairMsg').textContent=d.error;return}
  $('pairQr').innerHTML=d.qr;$('pairAddr').textContent=d.host+':'+d.port}catch(e){}}
async function resetPair(){if(!confirm('Make a new pairing code? The phone will have to scan again.'))return;await fetch('/api/drone/link/pair/reset',{method:'POST'});loadPair()}
function simOn(){if(!confirm('Start the simulator? Remove the propellers first.'))return;
  const go=(lat,lon)=>cmd('sim_on',{lat,lon});const t=st.telemetry||{};
  if(t.lat&&t.lon)return go(t.lat,t.lon);navigator.geolocation?navigator.geolocation.getCurrentPosition(p=>go(p.coords.latitude,p.coords.longitude),()=>go(33.8938,35.5018)):go(33.8938,35.5018)}
$('speedVal').textContent='30%';loadFleet();setInterval(loadFleet,3000);loadPair();poll();loadResp();loadRoutes().then(loadScheds);setInterval(poll,500);
</script>""", active="drone")
_body_end = DRONE_CONTROL_PAGE.rfind("</body>")
DRONE_CONTROL_PAGE = DRONE_CONTROL_PAGE[:_body_end] + LIVE_PLAYER_HTML + DRONE_CONTROL_PAGE[_body_end:]


# ============================================================
# SIGHTINGS, DRONE RESPONSE AND TELEGRAM ASSISTANT
# ============================================================
# Sightings: known faces and plates (unknown faces are already in event_history.csv), kept 30 days,
# so the assistant can answer "who came today?" and build the morning briefing offline.
SIGHTINGS_FILE = os.path.join(BASE_FOLDER, "sightings.jsonl")
RESPONSE_SETTINGS_FILE = os.path.join(os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER), "response_settings.json")
RESPONSE_DEFAULTS = {"camera_locations": {}, "altitude_m": 30, "speed_ms": 6, "hover_seconds": 60, "auto_return": True,
                     "min_battery": 35, "briefing_enabled": True, "briefing_time": "08:00", "patrol_schedules": []}
sightings_lock = threading.Lock()
_sighting_last = {}


def record_sighting(kind, name, identifier, camera, object_id="", known=True):
    """One line per person/vehicle visit (repeat reports of the same object within 2 min are skipped)."""
    key = (kind, object_id or identifier or name)
    now = time.time()
    if now - _sighting_last.get(key, 0) < 120:
        return
    _sighting_last[key] = now
    row = {"t": round(now), "kind": kind, "name": str(name or ""), "id": str(identifier or ""), "camera": str(camera or ""), "known": bool(known)}
    try:
        with sightings_lock, open(SIGHTINGS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:
        print("Sighting log error:", e)


def load_sightings(since, until=None):
    """Known faces/plates from the sightings log plus unknown faces from the event history."""
    until = until or time.time() + 60
    rows = []
    try:
        with sightings_lock, open(SIGHTINGS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if since <= r.get("t", 0) <= until:
                    rows.append(r)
    except FileNotFoundError:
        pass
    try:
        with event_log_lock, open(EVENT_LOG, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    t = time.mktime(time.strptime(f"{r.get('Date')} {r.get('Time')}", "%Y-%m-%d %H:%M:%S"))
                except Exception:
                    continue
                if since <= t <= until:
                    kind = "face" if "FACE" in str(r.get("Type", "")).upper() else "plate"
                    rows.append({"t": t, "kind": kind, "name": "", "id": r.get("Identifier", "") if kind == "plate" else "",
                                 "camera": r.get("Camera") or CAMERA_NAME, "known": False, "snapshot": r.get("Snapshot", "")})
    except FileNotFoundError:
        pass
    return sorted(rows, key=lambda r: r["t"])


def prune_sightings(days=30):
    cutoff = time.time() - days * 86400
    try:
        with sightings_lock:
            with open(SIGHTINGS_FILE, "r", encoding="utf-8") as f:
                keep = [line for line in f if (json.loads(line).get("t", 0) if line.strip() else 0) >= cutoff]
            with open(SIGHTINGS_FILE, "w", encoding="utf-8") as f:
                f.writelines(keep)
    except FileNotFoundError:
        pass
    except Exception as e:
        print("Sightings prune error:", e)


def load_response_settings():
    cfg = dict(RESPONSE_DEFAULTS)
    try:
        with open(RESPONSE_SETTINGS_FILE, "r", encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in RESPONSE_DEFAULTS})
    except (FileNotFoundError, ValueError):
        pass
    # The main camera can also use the location saved on the Settings page.
    legacy = _load_customer_settings() if "_load_customer_settings" in globals() else {}
    if CAMERA_NAME not in cfg["camera_locations"] and isinstance(legacy.get("camera_latitude"), (int, float)) and isinstance(legacy.get("camera_longitude"), (int, float)):
        cfg["camera_locations"] = {**cfg["camera_locations"], CAMERA_NAME: {"lat": legacy["camera_latitude"], "lon": legacy["camera_longitude"]}}
    return cfg


def save_response_settings(data):
    cfg = load_response_settings()
    for k, v in data.items():
        if k not in RESPONSE_DEFAULTS:
            continue
        if k == "camera_locations" and isinstance(v, dict):
            v = {str(cam): {"lat": float(p["lat"]), "lon": float(p["lon"])} for cam, p in v.items()
                 if isinstance(p, dict) and -90 <= float(p.get("lat", 999)) <= 90 and -180 <= float(p.get("lon", 999)) <= 180}
        elif k in ("altitude_m", "speed_ms", "hover_seconds", "min_battery"):
            lo, hi = {"altitude_m": (10, DRONE_LIMITS["max_altitude_m"]), "speed_ms": (1, 8), "hover_seconds": (10, 600), "min_battery": (20, 90)}[k]
            v = max(lo, min(hi, float(v)))
        elif k in ("auto_return", "briefing_enabled"):
            v = bool(v)
        elif k == "patrol_schedules":
            v = _clean_schedules(v)
        elif k == "briefing_time":
            v = str(v) if re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(v)) else RESPONSE_DEFAULTS["briefing_time"]
        cfg[k] = v
    tmp = RESPONSE_SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, RESPONSE_SETTINGS_FILE)
    return cfg


# ---------- drone response ----------
drone_response = {"active": False, "drone": DRONE_CAMERA_NAME, "camera": "", "phase": "", "started": 0.0, "arrived": 0.0,
                  "stay_until": 0.0, "by": "", "message": ""}


def _pick_drone(check, drone=None):
    """First drone (or the one asked for) that passes check(slot) == ''. Returns (slot, problem)."""
    # Automatic choices use real drones; virtual ones only in demo mode (Virtual Drones tab).
    slots = [drone] if drone else [d for d in drone_slots() if d not in _sources_over_limit()
                                   and (not is_virtual(d) or _virtual_cfg.get("demo_auto"))]
    problems = []
    for d in slots:
        problem = check(d)
        if not problem:
            return d, ""
        problems.append((d, problem))
    if len(problems) == 1:
        return None, problems[0][1]
    connected = [(d, pr) for d, pr in problems if get_link(d)["conn"] is not None] or problems
    return None, "No drone is ready. " + " ".join(f"{drone_label(d)}: {pr}" for d, pr in connected)


def _drone_busy(slot):
    return ((drone_response["active"] and drone_response.get("drone") == slot)
            or (route_run["active"] and route_run.get("drone") == slot))


def _drone_ready_problem(camera, slot=None):
    """Why that drone (any drone when slot is None) can't be sent to this camera now ('' = ready)."""
    if slot is None:
        return _pick_drone(lambda d: _drone_ready_problem(camera, d))[1]
    if not drone_control_allowed():
        return "Drone control is not included in this licence."
    link = get_link(slot)
    if link["conn"] is None:
        return "The Drone Link phone is not connected."
    tel = link["telemetry"]
    if time.time() - link["tel_at"] > 3 or not tel.get("drone_connected"):
        return "The drone is not connected to the controller."
    cfg = load_response_settings()
    loc = cfg["camera_locations"].get(camera)
    if not loc:
        return f"No map location saved for camera '{camera}'. Set it on the Drone page."
    if (tel.get("battery") or 0) < cfg["min_battery"]:
        return f"Battery is {tel.get('battery')}% (minimum {int(cfg['min_battery'])}%)."
    home = (tel.get("home_lat") or tel.get("lat"), tel.get("home_lon") or tel.get("lon"))
    if None in home:
        return "The drone has no GPS position yet."
    if _distance_m(home[0], home[1], loc["lat"], loc["lon"]) > DRONE_LIMITS["max_distance_m"]:
        return f"That camera is more than {DRONE_LIMITS['max_distance_m']} m from the drone's home point."
    if _drone_busy(slot):
        return "The drone is already on a mission."
    return ""


def dispatch_drone(camera, by="dashboard", drone=None):
    if drone_response["active"]:
        return {"ok": False, "error": f"{drone_label(drone_response['drone'])} is already responding to {drone_response['camera']}."}
    slot, problem = _pick_drone(lambda d: _drone_ready_problem(camera, d), drone)
    if problem:
        return {"ok": False, "error": problem}
    cfg = load_response_settings()
    loc = cfg["camera_locations"][camera]
    result = drone_command("goto", {"lat": loc["lat"], "lon": loc["lon"], "alt": cfg["altitude_m"],
                                    "speed": cfg["speed_ms"], "arrive": "hover"}, timeout=15.0, slot=slot)
    if not result["ok"]:
        return result
    who = drone_label(slot) if len(drone_slots()) > 1 else "Drone"
    drone_response.update(active=True, drone=slot, camera=camera, phase="flying", started=time.time(), arrived=0.0, stay_until=0.0, by=by,
                          message=f"{who} on its way to {camera}")
    _drone_event(f"Drone response to {camera} started ({by})", slot)
    return {"ok": True, "drone": slot, "message": f"{who} on its way to {camera} at {int(cfg['altitude_m'])} m."}


def recall_drone(reason="recalled"):
    if not drone_response["active"]:
        return {"ok": False, "error": "No drone response in progress."}
    result = drone_command("go_home", timeout=10.0, slot=drone_response["drone"])
    drone_response.update(phase="returning", message=f"Returning home ({reason})")
    _drone_event(f"Drone response: returning home ({reason})", drone_response["drone"])
    return result


def _drone_snapshot(slot=None):
    slot = slot or (drone_response["drone"] if drone_response["active"] else DRONE_CAMERA_NAME)
    try:
        r = requests.get(f"{FRIGATE_API_URL}/api/{slot}/latest.jpg", params={"bbox": 1, "h": 720}, timeout=4)
        if r.ok and r.content[:2] == b"\xff\xd8":
            return r.content
    except Exception:
        pass
    return None


def _drone_response_worker():
    while True:
        time.sleep(1)
        if not drone_response["active"]:
            continue
        try:
            link = get_link(drone_response["drone"])
            if time.time() - link["tel_at"] > 5:
                continue  # no fresh telemetry (Wi-Fi hiccup): wait instead of deciding anything
            tel = link["telemetry"]
            mission = tel.get("mission")
            cam = drone_response["camera"]
            cfg = load_response_settings()
            if drone_response["phase"] == "flying":
                if not mission and drone_response["started"] and time.time() - drone_response["started"] > 5:
                    loc = cfg["camera_locations"].get(cam) or {}
                    near = tel.get("lat") and loc and _distance_m(tel["lat"], tel["lon"], loc["lat"], loc["lon"]) < 8
                    if near:
                        drone_response.update(phase="hovering", arrived=time.time(), stay_until=time.time() + cfg["hover_seconds"],
                                              message=f"Hovering over {cam}")
                        send_telegram(f"🚁 {drone_label(drone_response['drone'])} is over {cam} at {int(tel.get('altitude') or 0)} m. Battery {tel.get('battery')}%.\n"
                                      f"{'Returning home in ' + str(int(cfg['hover_seconds'])) + ' s.' if cfg['auto_return'] else 'Staying until you send it home.'}",
                                      _drone_snapshot(), [[{"text": "🏠 Return now", "callback_data": "home"}, {"text": "⏱ Stay 2 min", "callback_data": "stay"}],
                                                          [{"text": "📷 New snapshot", "callback_data": "dsnap"}]])
                    else:
                        drone_response.update(active=False, phase="stopped", message="Stopped before arriving")
                        send_telegram(f"⚠️ Drone response to {cam} stopped before arriving (STOP pressed, pilot took control or link lost). The pilot has control.")
            elif drone_response["phase"] == "hovering":
                if tel.get("control") != "PC":
                    drone_response.update(active=False, phase="pilot", message="The pilot took control")
                    send_telegram("ℹ️ The pilot took control of the drone. Drone response ended.")
                elif cfg["auto_return"] and time.time() > drone_response["stay_until"]:
                    recall_drone("hover time over")
                    send_telegram("🏠 Drone returning home.")
            elif drone_response["phase"] == "returning":
                if tel.get("flight_mode") not in ("GO_HOME", "AUTO_LANDING") and not tel.get("flying"):
                    drone_response.update(active=False, phase="landed", message="Landed at home")
                    send_telegram(f"✅ Drone landed at home. Battery {tel.get('battery')}%.")
                elif time.time() - drone_response["started"] > 900:
                    drone_response.update(active=False, phase="", message="")
        except Exception as e:
            print("Drone response error:", e)


# ---------- Telegram assistant ----------
def _tg(method, **data):
    cfg = load_telegram_config()
    if not telegram_ready(cfg):
        return None
    files = data.pop("files", None)
    try:
        r = requests.post(f"https://api.telegram.org/bot{str(cfg['bot_token']).strip()}/{method}", data=data, files=files, timeout=35)
        return r.json() if r.ok else None
    except Exception as e:
        print("Telegram error:", e)
        return None


def send_telegram(text, photo=None, buttons=None):
    """Assistant replies and drone notices (not subject to detection-alert mute/cooldown)."""
    chat = str(load_telegram_config().get("chat_id") or "").strip()
    extra = {"reply_markup": json.dumps({"inline_keyboard": buttons})} if buttons else {}
    if photo:
        return _tg("sendPhoto", chat_id=chat, caption=text[:1000], files={"photo": ("snapshot.jpg", photo, "image/jpeg")}, **extra)
    return _tg("sendMessage", chat_id=chat, text=text[:4000], **extra)


def alert_buttons(camera):
    row = []
    if drone_control_allowed() and load_response_settings()["camera_locations"].get(camera):
        row.append({"text": "🚁 Send drone", "callback_data": f"drone:{camera}"[:64]})
    row.append({"text": "📷 Live snapshot", "callback_data": f"snap:{camera}"[:64]})
    return [row, [{"text": "🔕 Mute 1 h", "callback_data": "mute:60"}]]


def _camera_snapshot(camera):
    try:
        r = requests.get(f"{FRIGATE_API_URL}/api/{camera}/latest.jpg", params={"bbox": 1, "h": 720}, timeout=4)
        if r.ok and r.content[:2] == b"\xff\xd8":
            return r.content
    except Exception:
        pass
    return None


def _fmt_time(t):
    return time.strftime("%H:%M", time.localtime(t))


def _period(text):
    """(start, end, label) for words like today / yesterday / last night / this week."""
    now = time.time()
    lt = time.localtime(now)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    t = text.lower()
    if "last night" in t or "tonight" in t or re.search(r"\bnight\b", t):
        start = midnight - 2 * 3600 if lt.tm_hour < 12 else midnight + 22 * 3600
        if lt.tm_hour < 12:
            return start, midnight + 6 * 3600, "last night (22:00–06:00)"
        return start, start + 8 * 3600, "tonight"
    if "yesterday" in t:
        return midnight - 86400, midnight, "yesterday"
    if "week" in t:
        return now - 7 * 86400, now + 60, "the last 7 days"
    return midnight, now + 60, "today"


def summary_text(start, end, label):
    rows = load_sightings(start, end)
    faces = [r for r in rows if r["kind"] == "face"]
    plates = [r for r in rows if r["kind"] == "plate"]
    known = {}
    for r in faces:
        if r["known"]:
            known.setdefault(r["name"], []).append(r["t"])
    unknown = [r for r in faces if not r["known"]]
    lines = [f"📋 Summary for {label}"]
    if known:
        lines.append(f"\n✅ Known people ({len(known)}):")
        for name, ts in sorted(known.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"• {name}: {len(ts)}× (first {_fmt_time(min(ts))}, last {_fmt_time(max(ts))})")
    lines.append(f"\n⚠️ Unknown people: {len(unknown)}" + (f" (last at {_fmt_time(unknown[-1]['t'])})" if unknown else ""))
    if plates:
        by_plate = {}
        for r in plates:
            by_plate.setdefault(r["id"] or "unreadable", []).append(r)
        lines.append(f"\n🚗 Vehicles ({len(by_plate)} plates):")
        for plate, rs in sorted(by_plate.items(), key=lambda kv: -len(kv[1]))[:12]:
            night = sum(1 for r in rs if time.localtime(r["t"]).tm_hour >= 22 or time.localtime(r["t"]).tm_hour < 6)
            tag = (rs[0]["name"] or "authorized") if rs[0]["known"] else "unknown"
            lines.append(f"• {plate} ({tag}): {len(rs)}×" + (f", {night} at night 🌙" if night else ""))
    if not rows:
        lines.append("\nNo activity recorded.")
    return "\n".join(lines)


def briefing_text():
    now = time.time()
    text = summary_text(now - 86400, now, "the last 24 hours").replace("📋 Summary for", "☀️ Good morning! Briefing for", 1)
    try:
        stats = requests.get(f"{FRIGATE_API_URL}/api/stats", timeout=3).json().get("cameras") or {}
        offline = [n for n in _frigate_camera_names() if not _is_drone_name(n) and float((stats.get(n) or {}).get("camera_fps") or 0) <= 0]
        text += "\n\n📹 Cameras: " + ("all online ✅" if not offline else "offline: " + ", ".join(offline) + " ⚠️")
    except Exception:
        text += "\n\n📹 Cameras: status unavailable"
    return text


def status_text():
    lines = [f"🛡️ {edition.PRODUCT_NAME} · {APP_VERSION}"]
    try:
        stats = requests.get(f"{FRIGATE_API_URL}/api/stats", timeout=3).json().get("cameras") or {}
        for n in _frigate_camera_names():
            fps = float((stats.get(n) or {}).get("camera_fps") or 0)
            lines.append(f"{'✈' if _is_drone_name(n) else '📹'} {n}: {'online ' + str(round(fps)) + ' fps' if fps > 0 else 'offline'}")
    except Exception:
        lines.append("📹 Video service not reachable (is Docker running?)")
    lines.append(_drone_status_line())
    today = load_sightings(_period("today")[0])
    lines.append(f"👥 Today: {len({r['name'] for r in today if r['kind'] == 'face' and r['known']})} known people, "
                 f"{sum(1 for r in today if r['kind'] == 'face' and not r['known'])} unknown, {len({r['id'] for r in today if r['kind'] == 'plate'})} plates")
    if time.time() < assistant_state["muted_until"]:
        lines.append(f"🔕 Alerts muted until {_fmt_time(assistant_state['muted_until'])}")
    return "\n".join(lines)


def _drone_status_line():
    if not drone_control_allowed():
        return "🚁 Drone control: not licensed"
    slots = drone_slots()
    lines = []
    for slot in slots:
        name = drone_label(slot) if len(slots) > 1 else "Drone"
        link = get_link(slot)
        t = link["telemetry"]
        if link["conn"] is None:
            lines.append(f"🚁 {name}: phone not connected")
        elif not t.get("drone_connected"):
            lines.append(f"🚁 {name}: not connected to the controller")
        else:
            state = "flying" if t.get("flying") else "on the ground"
            resp = (f" · responding to {drone_response['camera']} ({drone_response['phase']})"
                    if drone_response["active"] and drone_response["drone"] == slot else "")
            route = f" · flying route {route_run['name']}" if route_run["active"] and route_run.get("drone") == slot else ""
            lines.append(f"🚁 {name}: {state}, battery {t.get('battery')}%, GPS {t.get('gps_satellites')}{resp}{route}")
    return "\n".join(lines)


def answer_question(text):
    """Offline question answering over the sightings: plates, names, periods, unknown visitors."""
    t = text.strip()
    low = t.lower()
    start, end, label = _period(low)
    plate = re.search(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9-]{4,10}\b", t.upper())
    if plate and not re.match(r"^\d+$", plate.group(0)):
        p = plate.group(0).replace("-", "")
        rows = [r for r in load_sightings(time.time() - 30 * 86400) if r["kind"] == "plate" and r["id"].replace("-", "").upper() == p]
        if not rows:
            return f"🚗 Plate {p} has not been seen in the last 30 days."
        last = rows[-1]
        return (f"🚗 Plate {p}{' (' + last['name'] + ')' if last['name'] else ''}: seen {len(rows)}× in 30 days.\n"
                f"Last: {time.strftime('%Y-%m-%d %H:%M', time.localtime(last['t']))} at {last['camera']}.")
    names = {r["name"] for r in load_sightings(time.time() - 30 * 86400) if r["kind"] == "face" and r["known"] and r["name"]}
    for name in sorted(names, key=len, reverse=True):
        if name.lower() in low or name.split()[0].lower() in low.split():
            rows = [r for r in load_sightings(time.time() - 30 * 86400) if r["kind"] == "face" and r["name"] == name]
            in_period = [r for r in rows if start <= r["t"] <= end]
            last = rows[-1]
            return (f"👤 {name}: {len(in_period)}× {label}" + (f" (first {_fmt_time(in_period[0]['t'])}, last {_fmt_time(in_period[-1]['t'])})" if in_period else "") +
                    f".\nLast seen {time.strftime('%Y-%m-%d %H:%M', time.localtime(last['t']))} at {last['camera']}.")
    if "unknown" in low or "stranger" in low:
        rows = [r for r in load_sightings(start, end) if r["kind"] == "face" and not r["known"]]
        if not rows:
            return f"✅ No unknown people {label}."
        times = ", ".join(_fmt_time(r["t"]) for r in rows[-10:])
        return f"⚠️ {len(rows)} unknown {'person' if len(rows) == 1 else 'people'} {label}. Times: {times}"
    if any(w in low for w in ("who", "visitor", "came", "summary", "today", "yesterday", "night", "week", "activity", "happened")):
        return summary_text(start, end, label)
    return None


HELP_TEXT = ("🤖 I can help with:\n"
             "/status – cameras, drone and today's numbers\n/snapshot [camera] – live picture\n"
             "/today · /yesterday · /night – who came\n/briefing – the full daily report\n"
             "/drone – drone status · /send <camera> – send the drone · /home – bring it back\n"
             "/routes – saved routes · /fly <route> – fly a route · /patrols – scheduled patrols\n"
             "/mute [minutes] · /unmute – pause detection alerts\n\n"
             "Or just ask: “who came today?”, “unknown last night?”, “Tony”, or a plate like ABC123.")


def _handle_command(text):
    parts = text.strip().split()
    cmd = parts[0].lower().split("@")[0]
    arg = " ".join(parts[1:]).strip()
    cams = _frigate_camera_names()
    if cmd in ("/start", "/help"):
        send_telegram(HELP_TEXT)
    elif cmd == "/status":
        send_telegram(status_text())
    elif cmd == "/snapshot":
        cam = arg or CAMERA_NAME
        if cam not in cams:
            send_telegram("Cameras: " + ", ".join(cams))
            return
        photo = _camera_snapshot(cam)
        send_telegram(f"📷 {cam} · {time.strftime('%H:%M:%S')}" if photo else f"Could not get a picture from {cam}.", photo, alert_buttons(cam) if photo else None)
    elif cmd in ("/today", "/yesterday", "/night", "/week"):
        send_telegram(summary_text(*_period(cmd[1:])))
    elif cmd == "/briefing":
        send_telegram(briefing_text())
    elif cmd == "/drone":
        send_telegram(_drone_status_line())
    elif cmd == "/send":
        located = list(load_response_settings()["camera_locations"])
        cam = arg or (located[0] if len(located) == 1 else "")
        if cam not in located:
            send_telegram("Send the drone to which camera? " + (", ".join(located) if located else "No camera locations set yet (Drone page)."))
            return
        problem = _drone_ready_problem(cam)
        send_telegram(f"⚠️ {problem}" if problem else f"Send the drone to {cam}? It will take off if needed. Keep it in sight.",
                      buttons=None if problem else [[{"text": f"✅ Yes, send to {cam}", "callback_data": f"go:{cam}"[:64]}, {"text": "Cancel", "callback_data": "cancel"}]])
    elif cmd == "/routes":
        routes = load_routes()
        send_telegram("🗺️ Saved routes:\n" + "\n".join(f"• {n}: {len(r['points'])} stops, {int(r['alt'])} m" for n, r in routes.items())
                      + "\n\nFly one with /fly <name>" if routes else "No saved routes yet (draw one on the Drone page).")
    elif cmd == "/patrols":
        send_telegram(patrols_text())
    elif cmd == "/fly":
        routes = load_routes()
        if arg not in routes:
            send_telegram("Which route? " + (", ".join(routes) if routes else "No saved routes yet."))
            return
        problem = _route_problem(_clean_route(routes[arg]))
        send_telegram(f"⚠️ {problem}" if problem else f"Fly route “{arg}” ({len(routes[arg]['points'])} stops)? The drone takes off if needed. Keep it in sight.",
                      buttons=None if problem else [[{"text": "✅ Yes, fly it", "callback_data": f"route:{arg}"[:64]}, {"text": "Cancel", "callback_data": "cancel"}]])
    elif cmd == "/home":
        send_telegram(recall_drone("asked on Telegram").get("error") or "🏠 Drone returning home.")
    elif cmd == "/mute":
        minutes = int(arg) if arg.isdigit() else 60
        assistant_state["muted_until"] = time.time() + minutes * 60
        send_telegram(f"🔕 Detection alerts muted for {minutes} min (until {_fmt_time(assistant_state['muted_until'])}). /unmute to resume.")
    elif cmd == "/unmute":
        assistant_state["muted_until"] = 0
        send_telegram("🔔 Alerts are back on.")
    else:
        send_telegram("I don't know that command.\n\n" + HELP_TEXT)


def _handle_callback(data):
    if data.startswith("drone:"):
        cam = data.split(":", 1)[1]
        problem = _drone_ready_problem(cam)
        if problem:
            return send_telegram(f"⚠️ Can't send the drone: {problem}")
        send_telegram(f"Send the drone to {cam}? It will take off if needed. Keep it in sight.",
                      buttons=[[{"text": f"✅ Yes, send to {cam}", "callback_data": f"go:{cam}"[:64]}, {"text": "Cancel", "callback_data": "cancel"}]])
    elif data.startswith("go:"):
        r = dispatch_drone(data.split(":", 1)[1], by="Telegram")
        send_telegram(("🚁 " + r["message"]) if r["ok"] else f"⚠️ {r['error']}")
    elif data.startswith("snap:"):
        cam = data.split(":", 1)[1]
        photo = _camera_snapshot(cam)
        send_telegram(f"📷 {cam} · {time.strftime('%H:%M:%S')}" if photo else f"Could not get a picture from {cam}.", photo)
    elif data.startswith("patrolgo:"):
        sid = data.split(":", 1)[1]
        if patrol_state["pending"].pop(sid, None) is None:
            return send_telegram("That patrol request has expired.")
        r = start_scheduled_patrol(sid, by="schedule (confirmed on Telegram)")
        send_telegram(("🗺️ " + r["message"]) if r["ok"] else f"⚠️ Patrol not started: {r['error']}")
    elif data.startswith("patrolskip:"):
        patrol_state["pending"].pop(data.split(":", 1)[1], None)
        send_telegram("⏭ Patrol skipped.")
    elif data.startswith("route:"):
        r = fly_route(data.split(":", 1)[1], by="Telegram")
        send_telegram(("🗺️ " + r["message"]) if r["ok"] else f"⚠️ {r['error']}")
    elif data == "dsnap":
        photo = _drone_snapshot()
        send_telegram("📷 Drone view" if photo else "No drone picture right now.", photo)
    elif data == "home":
        send_telegram(recall_drone("asked on Telegram").get("error") or "🏠 Drone returning home.")
    elif data == "stay":
        if drone_response["phase"] == "hovering":
            drone_response["stay_until"] = max(drone_response["stay_until"], time.time()) + 120
            send_telegram(f"⏱ Staying until {_fmt_time(drone_response['stay_until'])}.")
    elif data.startswith("mute:"):
        assistant_state["muted_until"] = time.time() + int(data.split(":")[1]) * 60
        send_telegram(f"🔕 Detection alerts muted until {_fmt_time(assistant_state['muted_until'])}. /unmute to resume.")
    elif data == "cancel":
        send_telegram("OK, cancelled.")


def telegram_assistant_worker():
    """Long-polls the bot for messages and button presses. Only the configured chat is obeyed."""
    offset, warned = 0, False
    while True:
        cfg = load_telegram_config()
        if not telegram_ready(cfg):
            time.sleep(30)
            continue
        res = _tg("getUpdates", offset=offset, timeout=25, allowed_updates=json.dumps(["message", "callback_query"]))
        if not res or not res.get("ok"):
            if not warned:
                print("Telegram assistant: cannot read messages (another program may use this bot, or a webhook is set)")
                warned = True
            time.sleep(10)
            continue
        warned = False
        own_chat = str(cfg.get("chat_id")).strip()
        for upd in res.get("result", []):
            offset = max(offset, upd["update_id"] + 1)
            try:
                if "callback_query" in upd:
                    cq = upd["callback_query"]
                    _tg("answerCallbackQuery", callback_query_id=cq["id"])
                    if str((cq.get("message") or {}).get("chat", {}).get("id")) == own_chat:
                        _handle_callback(str(cq.get("data") or ""))
                    continue
                msg = upd.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != own_chat:
                    continue  # strangers who find the bot get nothing
                text = str(msg.get("text") or "").strip()
                if not text:
                    continue
                if text.startswith("/"):
                    _handle_command(text)
                else:
                    send_telegram(answer_question(text) or "I didn't understand that.\n\n" + HELP_TEXT)
            except Exception as e:
                print("Telegram assistant error:", e)
                send_telegram("Sorry, something went wrong answering that.")


def _briefing_worker():
    sent_on = ""
    while True:
        time.sleep(30)
        try:
            cfg = load_response_settings()
            today = time.strftime("%Y-%m-%d")
            if cfg["briefing_enabled"] and time.strftime("%H:%M") >= cfg["briefing_time"] and sent_on != today and telegram_ready():
                sent_on = today
                send_telegram(briefing_text())
                prune_sightings()
            elif not sent_on:
                sent_on = today if time.strftime("%H:%M") >= cfg["briefing_time"] else ""  # don't send a late briefing at startup
        except Exception as e:
            print("Briefing error:", e)


def start_assistant():
    threading.Thread(target=telegram_assistant_worker, daemon=True).start()
    threading.Thread(target=_briefing_worker, daemon=True).start()
    threading.Thread(target=_drone_response_worker, daemon=True).start()
    threading.Thread(target=_patrol_scheduler_worker, daemon=True).start()


# ---------- multi-stop routes (draw on the map, fly stop by stop) ----------
ROUTES_FILE = os.path.join(os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER), "drone_routes.json")
ROUTE_MAX_POINTS = 25
route_run = {"active": False, "drone": DRONE_CAMERA_NAME, "name": "", "index": 0, "total": 0, "phase": "", "message": "", "stop": False}


def load_routes():
    try:
        with open(ROUTES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _clean_route(r):
    pts = [{"lat": float(p["lat"]), "lon": float(p["lon"])} for p in (r.get("points") or [])
           if -90 <= float(p["lat"]) <= 90 and -180 <= float(p["lon"]) <= 180][:ROUTE_MAX_POINTS]
    return {"points": pts, "alt": max(10.0, min(float(DRONE_LIMITS["max_altitude_m"]), float(r.get("alt") or 30))),
            "speed": max(1.0, min(8.0, float(r.get("speed") or 5))), "pause": max(0.0, min(120.0, float(r.get("pause") or 0))),
            "end": r.get("end") if r.get("end") in ("hover", "home", "land") else "home",
            "loop": bool(r.get("loop")), "relay": bool(r.get("relay")),
            "swap_at": max(20, min(50, int(float(r.get("swap_at") or 20))))}


def save_route(name, route):
    name = re.sub(r"[^\w \-]", "", str(name or "")).strip()[:40]
    if not name:
        raise ValueError("Give the route a name")
    routes = load_routes()
    routes[name] = _clean_route(route)
    tmp = ROUTES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(routes, f, indent=2)
    os.replace(tmp, ROUTES_FILE)
    return name, routes[name]


def delete_route(name):
    routes = load_routes()
    routes.pop(name, None)
    with open(ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump(routes, f, indent=2)


def _route_problem(route, slot=None):
    if slot is None:
        return _pick_drone(lambda d: _route_problem(route, d))[1]
    if not drone_control_allowed():
        return "Drone control is not included in this licence."
    link = get_link(slot)
    if link["conn"] is None:
        return "The Drone Link phone is not connected."
    tel = link["telemetry"]
    if time.time() - link["tel_at"] > 3 or not tel.get("drone_connected"):
        return "The drone is not connected to the controller."
    pts = route["points"]
    if len(pts) < 1:
        return "The route has no stops."
    home = (tel.get("home_lat") or tel.get("lat"), tel.get("home_lon") or tel.get("lon"))
    if None in home:
        return "The drone has no GPS position yet."
    for i, p in enumerate(pts, 1):
        d = _distance_m(home[0], home[1], p["lat"], p["lon"])
        if d > DRONE_LIMITS["max_distance_m"]:
            return f"Stop {i} is {int(d)} m from home (limit {DRONE_LIMITS['max_distance_m']} m)."
    if (tel.get("battery") or 0) < load_response_settings()["min_battery"]:
        return f"Battery is {tel.get('battery')}%."
    if _drone_busy(slot):
        return "The drone is already on a mission."
    return ""


def _wait_arrival(p, started):
    """Wait until the phone's auto-fly reaches p. Returns '' on arrival, else why it ended."""
    while True:
        time.sleep(0.5)
        if route_run["stop"]:
            return "stopped from the PC"
        link = get_link(route_run["drone"])
        if time.time() - link["tel_at"] > 5:
            if time.time() - started > 900:
                return "lost contact with the drone"
            continue  # Wi-Fi hiccup: wait
        tel = link["telemetry"]
        if route_run.get("swap_at") and tel.get("battery") is not None and tel["battery"] <= route_run["swap_at"]:
            return SWAP
        if tel.get("mission"):
            continue
        if time.time() - started < 3:
            continue  # the mission may not have started yet
        if tel.get("lat") and _distance_m(tel["lat"], tel["lon"], p["lat"], p["lon"]) < 8:
            return ""
        return "STOP pressed, the pilot took control or the link dropped"


SWAP = "__battery_swap__"


class PatrolEnded(Exception):
    """The patrol ended with the drone already on its way home (don't tell it to hover)."""


def _battery_low(slot):
    b = get_link(slot)["telemetry"].get("battery")
    return bool(route_run.get("swap_at")) and b is not None and b <= route_run["swap_at"]


def _hand_over(name, route, old, stop):
    """Send the tired drone home and put the next ready drone on the patrol. Returns the new drone."""
    bat = get_link(old)["telemetry"].get("battery")
    drone_command("go_home", timeout=10.0, slot=old)
    _drone_event(f"Battery {bat}%: returning home from route {name}", old)
    over = _sources_over_limit()
    nxt, problem = None, "no other drone"
    if route["relay"]:
        # Same kind of drone takes over (real → real, virtual → virtual) unless demo mode mixes them.
        candidates = [d for d in drone_slots() if d != old and d not in over
                      and (is_virtual(d) == is_virtual(old) or _virtual_cfg.get("demo_auto"))]
        nxt = next((d for d in candidates if not _route_problem(route, d)), None)
        problem = "no other drone is ready" if candidates else "no other drone"
    if not nxt:
        msg = (f"🔋 {drone_label(old)} at {bat}% is returning home. Patrol “{name}” ended at stop {stop}"
               + (f": {problem}." if route["relay"] else "."))
        send_telegram(msg) if telegram_ready() else None
        raise PatrolEnded(f"battery {bat}%, {drone_label(old)} returning home" + (f"; {problem}" if route["relay"] else ""))
    route_run.update(drone=nxt, handovers=route_run.get("handovers", 0) + 1)
    _drone_event(f"Taking over route {name} at stop {stop} from {drone_label(old)} ({bat}%)", nxt)
    send_telegram(f"🔁 {drone_label(old)} at {bat}% is returning home. {drone_label(nxt)} is taking off to continue patrol "
                  f"“{name}” from stop {stop}.") if telegram_ready() else None
    return nxt


def _run_route(name, route, by, slot):
    pts = route["points"]
    route_run.update(swap_at=route["swap_at"] if (route["loop"] or route["relay"]) else 0, lap=1, handovers=0)
    who = f" ({drone_label(slot)})" if len(drone_slots()) > 1 else ""
    kind = " · continuous patrol" if route["loop"] else ""
    kind += f" · relay at {route['swap_at']}%" if route["relay"] else ""
    _drone_event(f"Route {name} started ({len(pts)} stops, {by}{kind})", slot)
    send_telegram(f"🗺️ Route “{name}”{who} started: {len(pts)} stops at {int(route['alt'])} m{kind}.") if telegram_ready() else None
    i = 0
    try:
        while True:
            p = pts[i]
            if _battery_low(slot):
                slot = _hand_over(name, route, slot, i + 1)
            lap = f" · lap {route_run['lap']}" if route["loop"] else ""
            route_run.update(index=i + 1, phase="flying", message=f"{drone_label(slot)} flying to stop {i + 1} of {len(pts)}{lap}")
            r = drone_command("goto", {"lat": p["lat"], "lon": p["lon"], "alt": route["alt"], "speed": route["speed"], "arrive": "hover"},
                              timeout=15.0, slot=slot)
            if not r["ok"]:
                raise RuntimeError(r["error"] or "the drone refused the next stop")
            why = _wait_arrival(p, time.time())
            if why == SWAP:
                slot = _hand_over(name, route, slot, i + 1)
                continue  # the new drone flies to the same stop
            if why:
                raise RuntimeError(why)
            route_run.update(phase="pause", message=f"{drone_label(slot)} at stop {i + 1} of {len(pts)}{lap}")
            end = time.time() + route["pause"]
            while time.time() < end and not route_run["stop"]:
                time.sleep(0.5)
            if route_run["stop"]:
                raise RuntimeError("stopped from the PC")
            i += 1
            if i >= len(pts):
                if not route["loop"]:
                    break
                i = 0
                route_run["lap"] += 1
        action = {"home": "go_home", "land": "land"}.get(route["end"])
        if action:
            drone_command(action, timeout=10.0, slot=slot)
        done = {"home": "returning home", "land": "landing at the last stop", "hover": "hovering at the last stop"}[route["end"]]
        route_run.update(phase="done", message=f"Route {name} complete, {done}")
        _drone_event(f"Route {name} complete ({done})", slot)
        send_telegram(f"✅ Route “{name}” complete, {done}.") if telegram_ready() else None
    except PatrolEnded as e:
        route_run.update(phase="done", message=f"Patrol {name} ended: {e}")
        _drone_event(f"Route {name} ended: {e}", slot)
    except Exception as e:
        drone_command("hover", timeout=5.0, slot=slot)
        route_run.update(phase="stopped", message=f"Route stopped at stop {route_run['index']}: {e}")
        _drone_event(f"Route {name} stopped: {e}", slot)
        send_telegram(f"⚠️ Route “{name}” stopped at stop {route_run['index']}: {e}. The drone is hovering.") if telegram_ready() else None
    finally:
        route_run.update(active=False, swap_at=0)


def fly_route(name=None, route=None, by="dashboard", drone=None):
    if route is None:
        route = load_routes().get(name or "")
        if not route:
            return {"ok": False, "error": f"No saved route named “{name}”."}
    if route_run["active"]:
        return {"ok": False, "error": f"{drone_label(route_run['drone'])} is already flying route {route_run['name']}."}
    route = _clean_route(route)
    slot, problem = _pick_drone(lambda d: _route_problem(route, d), drone)
    if problem:
        return {"ok": False, "error": problem}
    # Claimed here (not in the thread) so a second request can't start another route meanwhile.
    route_run.update(active=True, drone=slot, name=name or "unsaved route", index=0, total=len(route["points"]), phase="flying",
                     stop=False, message=f"Route {name or 'unsaved route'} started")
    threading.Thread(target=_run_route, args=(name or "unsaved route", route, by, slot), daemon=True).start()
    who = f"{drone_label(slot)}: " if len(drone_slots()) > 1 else ""
    return {"ok": True, "drone": slot, "message": f"{who}Route started: {len(route['points'])} stops."}


@app.route("/api/routes", methods=["GET", "POST", "DELETE"])
def api_routes():
    try:
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            name, route = save_route(data.get("name"), data)
            return jsonify({"ok": True, "name": name, "route": route})
        if request.method == "DELETE":
            delete_route(str((request.get_json(silent=True) or {}).get("name") or ""))
            return jsonify({"ok": True})
    except (TypeError, ValueError, KeyError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "routes": load_routes(), "run": route_run, "max_distance_m": DRONE_LIMITS["max_distance_m"]})


@app.route("/api/routes/fly", methods=["POST"])
def api_routes_fly():
    data = request.get_json(silent=True) or {}
    try:
        drone = data.get("drone") or request.args.get("drone")
        r = fly_route(data.get("name"), data if data.get("points") else None, by="dashboard",
                      drone=drone if drone in drone_slots() else None)
    except (TypeError, ValueError, KeyError) as e:
        r = {"ok": False, "error": f"Invalid route: {e}"}
    return jsonify(r), (200 if r["ok"] else 409)


@app.route("/api/routes/stop", methods=["POST"])
def api_routes_stop():
    route_run["stop"] = True
    drone_command("hover", timeout=5.0, slot=route_run["drone"])
    return jsonify({"ok": True})


# ---------- scheduled patrols (a saved route on chosen days at a set time) ----------
PATROL_CONFIRM_MINUTES = 15
PATROL_MIN_SATELLITES = 8
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
patrol_state = {"fired": {}, "pending": {}}  # fired: schedule id -> date run; pending: id -> confirm deadline


def _clean_schedules(items):
    out = []
    for s in items if isinstance(items, list) else []:
        if not isinstance(s, dict) or not str(s.get("route") or "").strip():
            continue
        t = str(s.get("time") or "")
        days = sorted({int(d) for d in (s.get("days") or []) if str(d).isdigit() and 0 <= int(d) <= 6})
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", t) or not days:
            continue
        drone = str(s.get("drone") or "")
        out.append({"id": re.sub(r"[^\w-]", "", str(s.get("id") or "")) or os.urandom(4).hex(), "route": str(s["route"])[:40],
                    "time": t, "days": days, "enabled": bool(s.get("enabled", True)), "auto_start": bool(s.get("auto_start", False)),
                    "drone": drone if _is_drone_name(drone) else ""})
    return out[:20]


def _patrol_preflight(route, slot=None):
    """Everything a scheduled patrol must pass before take-off ('' = clear to fly); any drone when slot is None."""
    if slot is None:
        return _pick_drone(lambda d: _patrol_preflight(route, d))[1]
    problem = _route_problem(_clean_route(route), slot)
    if problem:
        return problem
    tel = get_link(slot)["telemetry"]
    if tel.get("flying"):
        return "The drone is already flying."
    if (tel.get("gps_satellites") or 0) < PATROL_MIN_SATELLITES:
        return f"Only {tel.get('gps_satellites') or 0} GPS satellites (need {PATROL_MIN_SATELLITES})."
    return ""


def _next_run(s, now=None):
    now = now or time.time()
    lt = time.localtime(now)
    hh, mm = map(int, s["time"].split(":"))
    for add in range(8):
        day = time.localtime(now + add * 86400)
        when = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, hh, mm, 0, 0, 0, -1))
        if day.tm_wday in s["days"] and when > now:
            return when
    return None


def start_scheduled_patrol(sid, by):
    s = next((x for x in load_response_settings()["patrol_schedules"] if x["id"] == sid), None)
    if not s:
        return {"ok": False, "error": "That patrol schedule no longer exists."}
    route = load_routes().get(s["route"])
    if not route:
        return {"ok": False, "error": f"Route “{s['route']}” no longer exists."}
    slot, problem = _pick_drone(lambda d: _patrol_preflight(route, d), s.get("drone") or None)
    if problem:
        return {"ok": False, "error": problem}
    return fly_route(s["route"], by=by, drone=slot)


def _patrol_scheduler_worker():
    while True:
        time.sleep(20)
        try:
            now = time.time()
            today, hhmm, wday = time.strftime("%Y-%m-%d"), time.strftime("%H:%M"), time.localtime(now).tm_wday
            for sid, deadline in list(patrol_state["pending"].items()):
                if now > deadline:
                    patrol_state["pending"].pop(sid, None)
                    send_telegram("⏭ Patrol skipped: no answer within %d minutes." % PATROL_CONFIRM_MINUTES)
            for s in load_response_settings()["patrol_schedules"]:
                if not s["enabled"] or wday not in s["days"] or s["time"] != hhmm or patrol_state["fired"].get(s["id"]) == today:
                    continue
                patrol_state["fired"][s["id"]] = today  # once per day, never flown late
                route = load_routes().get(s["route"])
                slot, problem = (_pick_drone(lambda d: _patrol_preflight(route, d), s.get("drone") or None) if route
                                 else (None, f"Route “{s['route']}” no longer exists."))
                if problem:
                    _drone_event(f"Scheduled patrol {s['route']} skipped: {problem}", s.get("drone") or None)
                    send_telegram(f"⏭ Scheduled patrol “{s['route']}” skipped: {problem}")
                    continue
                tel = get_link(slot)["telemetry"]
                who = f"{drone_label(slot)}: " if len(drone_slots()) > 1 else ""
                facts = f"{who}Battery {tel.get('battery')}%, GPS {tel.get('gps_satellites')}, {len(route['points'])} stops."
                if s["auto_start"]:
                    r = fly_route(s["route"], by="schedule", drone=slot)
                    if not r["ok"]:
                        send_telegram(f"⚠️ Scheduled patrol “{s['route']}” could not start: {r['error']}")
                else:
                    patrol_state["pending"][s["id"]] = now + PATROL_CONFIRM_MINUTES * 60
                    send_telegram(f"🗺️ Patrol “{s['route']}” is due now. {facts}\nStart it? (skipped if no answer in {PATROL_CONFIRM_MINUTES} min)",
                                  buttons=[[{"text": "✅ Start patrol", "callback_data": f"patrolgo:{s['id']}"[:64]},
                                            {"text": "⏭ Skip", "callback_data": f"patrolskip:{s['id']}"[:64]}]])
        except Exception as e:
            print("Patrol scheduler error:", e)


def patrols_text():
    items = load_response_settings()["patrol_schedules"]
    if not items:
        return "No scheduled patrols yet (Drone page → Route → Schedule)."
    lines = ["🗓 Scheduled patrols:"]
    for s in items:
        nxt = _next_run(s)
        days = "every day" if len(s["days"]) == 7 else ", ".join(DAY_NAMES[d] for d in s["days"])
        lines.append(f"• {s['route']} at {s['time']}, {days} · {'auto-start' if s['auto_start'] else 'asks first'}"
                     + ("" if s["enabled"] else " · paused") + (f" · next {time.strftime('%a %H:%M', time.localtime(nxt))}" if nxt and s["enabled"] else ""))
    return "\n".join(lines)


@app.route("/api/response/settings", methods=["GET", "POST"])
def api_response_settings():
    if request.method == "POST":
        try:
            return jsonify({"ok": True, "settings": save_response_settings(request.get_json(silent=True) or {})})
        except (TypeError, ValueError) as e:
            return jsonify({"ok": False, "error": f"Invalid value: {e}"}), 400
    return jsonify({"ok": True, "settings": load_response_settings(), "cameras": _frigate_camera_names(),
                    "response": drone_response, "telegram": telegram_ready()})


@app.route("/api/response/dispatch", methods=["POST"])
def api_response_dispatch():
    data = request.get_json(silent=True) or {}
    cam = str(data.get("camera") or "")
    drone = data.get("drone") or request.args.get("drone")
    r = dispatch_drone(cam, by="dashboard", drone=drone if drone in drone_slots() else None)
    if r["ok"]:
        send_telegram(f"🚁 {drone_label(r['drone']) if len(drone_slots()) > 1 else 'Drone'} sent to {cam} from the dashboard.")
    return jsonify(r), (200 if r["ok"] else 409)


@app.route("/api/response/recall", methods=["POST"])
def api_response_recall():
    r = recall_drone("dashboard")
    return jsonify(r), (200 if r.get("ok") else 409)


@app.route("/api/assistant/briefing", methods=["POST"])
def api_assistant_briefing():
    if not telegram_ready():
        return jsonify({"ok": False, "error": "Telegram is not set up."}), 409
    send_telegram(briefing_text())
    return jsonify({"ok": True})


# ============================================================
# TELEGRAM API
# ============================================================


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "ai-security-command-center", "version": APP_VERSION})

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
        "version": APP_VERSION,
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

def event_key(row):
    """Stable identity for a history row (list indexes shift as new events arrive)."""
    return "|".join(str(row.get(k, "") or "") for k in ("Date", "Time", "Identifier", "Snapshot"))


def delete_history_event(event_index, key=""):
    if not os.path.exists(EVENT_LOG):
        raise RuntimeError("Event history file does not exist.")

    with event_log_lock:
        with open(EVENT_LOG, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)

        if not fieldnames:
            raise RuntimeError("Event history has no headers.")

        newest_first = list(reversed(rows))
        if key:
            matches = [row for row in newest_first if event_key(row) == key]
            if not matches:
                raise RuntimeError("Event could not be found. Refresh the page and try again.")
            event_to_delete = matches[0]
        else:
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
        data = request.get_json(silent=True) or {}
        deleted = delete_history_event(event_index, str(data.get("key") or ""))
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

.confirm-armed {
    background: #7a1020 !important;
    border-color: #ff4d6a !important;
    color: #fff !important;
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

<!--HUD_SUBNAV-->

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

<div style="display:flex;align-items:center;gap:10px">
<div class="live">
● LIVE
</div>
<button type="button" class="feed-switch" data-feed-switch="main" aria-pressed="true" title="Show or hide this live feed">LIVE FEED <span class="knob"></span></button>
</div>

</div>


<div class="camera-box">

<div class="camera live-slot" data-live-camera data-live-deferred style="aspect-ratio:16/9;min-height:0"></div>

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
<div style="display:flex;align-items:center;gap:10px">
<div class="live" id="droneFeedState">DRONE</div>
<button type="button" class="feed-switch" data-feed-switch="drone" aria-pressed="true" title="Show or hide this live feed">LIVE FEED <span class="knob"></span></button>
</div>
</div>
<div class="camera-box" style="min-height:280px;">
<div id="droneCameraFeed" class="camera live-slot" data-live-camera="drone" data-live-deferred
style="width:100%;height:420px;min-height:280px;max-height:520px;"></div>
<div class="corner tl"></div><div class="corner tr"></div>
<div class="corner bl"></div><div class="corner br"></div>
</div>
<div class="camera-footer">
<div class="cam-name">DRONE 01</div>
<div id="droneTrackingReadout">TRACKING ASSIST • WAITING</div>
</div>
<style>
.drone-fleet{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px;padding:9px;border-top:1px solid #123447}
.drone-fleet a{display:block;padding:9px 11px;border:1px solid #164b67;border-radius:4px;background:rgba(2,15,24,.72);color:#d8f4ff;text-decoration:none;font-size:11px}
.drone-fleet a:hover{border-color:#35caff;background:rgba(53,202,255,.10)}
.drone-fleet b{color:#35caff;letter-spacing:1px}
.drone-fleet .df-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#53636d;margin-right:6px}
.drone-fleet .df-dot.ok{background:#26ee89}.drone-fleet .df-dot.half{background:#ffb23c}
.drone-fleet .df-info{margin-top:5px;color:#8ba9b8;font-size:10px;letter-spacing:.5px}
.drone-fleet .df-open{float:right;color:#5bd9ff;font-size:10px}
</style>
<div class="drone-fleet" id="droneFleet"></div>
<div style="padding:0 9px 9px"><a href="/drone-grid" style="color:#5bd9ff;font-size:10px;letter-spacing:1px;text-decoration:none">▦ ALL DRONES GRID VIEW / FULL SCREEN →</a></div>
<script>
(function () {
    const box = document.getElementById("droneFleet");
    const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
    async function refresh() {
        let d;
        try { d = await fetch("/api/drone/links", {cache: "no-store"}).then(r => r.json()); } catch (e) { return; }
        if (!d.ok) return;
        box.innerHTML = d.drones.map(x => {
            const dot = x.drone_connected ? "ok" : x.phone_connected ? "half" : "";
            const info = x.over_limit ? "Over licence limit"
                : x.mission ? (x.mission === "route" ? "Flying a route" : "On a drone response")
                : x.drone_connected ? (x.flying ? "Flying" : "Ready on the ground") + (x.battery != null ? " · battery " + x.battery + "%" : "")
                : x.phone_connected ? "Phone connected · drone off" : "Phone not paired";
            return '<a href="/drone-control?drone=' + encodeURIComponent(x.drone) + '" title="Open the controls for ' + esc(x.label) + '">'
                + '<span class="df-open">CONTROLS →</span><span class="df-dot ' + dot + '"></span><b>' + esc(x.label).toUpperCase() + '</b>'
                + (x.virtual ? ' <span style="color:#ffcf7a;font-size:9px;border:1px solid #7a5a12;border-radius:3px;padding:1px 4px">VIRTUAL</span>' : '')
                + '<div class="df-info">' + esc(info) + '</div></a>';
        }).join("");
    }
    refresh();
    setInterval(refresh, 4000);
})();
</script>
</div>


<!-- =======================================================
     MULTI-CAMERA GRID: every extra camera and drone
     ======================================================= -->
<style>
.multi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px;padding:10px}
.grid-tile{position:relative;background:#000;border:1px solid #123447;border-radius:5px;overflow:hidden}
.grid-tile .live-slot{aspect-ratio:16/9;height:auto;cursor:zoom-in}
.grid-tile.feed-off .live-slot{display:none}
.grid-tile .tile-foot{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 9px;font-size:9px;letter-spacing:1px;color:#5d8499;background:#03101a;flex-wrap:wrap}
.grid-tile .tile-name{color:#35caff;text-transform:uppercase}
.grid-tile .tile-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#ff5d6c;margin-right:6px}
.grid-tile .tile-dot.on{background:#26ee89;box-shadow:0 0 8px #26ee89}
.grid-tile .tile-dot.paused{background:#ffb23c;box-shadow:none}
.grid-tile .tile-actions{display:flex;gap:6px;align-items:center}
.tile-btn{min-height:22px;padding:0 8px;cursor:pointer;color:#66dfff;background:rgba(14,88,128,.12);border:1px solid #155879;border-radius:3px;font-size:8px;letter-spacing:1px;font-family:inherit}
.tile-btn:hover{color:#fff;border-color:#35cbff}
.tile-btn.danger{color:#ff7b86;border-color:#7a2935;background:rgba(125,12,28,.12)}
.tile-btn:disabled{opacity:.5;cursor:default}
.feed-off-note{display:none;padding:18px 12px;color:#6d8b9d;font-size:10px;letter-spacing:1px;text-align:center}
.panel.feed-off .camera-box{display:none}
.panel.feed-off .feed-off-note{display:block}
.feed-switch{display:inline-flex;align-items:center;gap:7px;min-height:22px;padding:0 8px;cursor:pointer;color:#2aea88;background:rgba(18,120,70,.10);border:1px solid #1f7a50;border-radius:12px;font-size:8px;letter-spacing:1px;font-family:inherit}
.feed-switch .knob{position:relative;display:inline-block;width:26px;height:14px;border-radius:7px;background:rgba(37,199,255,.18);border:1px solid #36cfff}
.feed-switch .knob::after{content:"";position:absolute;top:2px;left:13px;width:8px;height:8px;border-radius:50%;background:#45d0ff;box-shadow:0 0 6px #45d0ff;transition:.2s}
.feed-switch[aria-pressed="false"]{color:#6d8b9d;background:rgba(14,88,128,.08);border-color:#155879}
.feed-switch[aria-pressed="false"] .knob{background:#0a1c28;border-color:#155879}
.feed-switch[aria-pressed="false"] .knob::after{left:2px;background:#4d6b7c;box-shadow:none}
.grid-empty{padding:22px 14px;color:#6d8b9d;font-size:11px;letter-spacing:.5px;line-height:1.6}
.grid-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:0 10px 12px}
.grid-actions code{color:#2eef88;font-size:11px;word-break:break-all}
</style>
<div class="panel" style="margin-top:9px;" id="multiGridPanel">
<div class="panel-head">
<div class="panel-title">▦ CAMERAS &amp; DRONES</div>
<div class="live" id="multiGridCount">—</div>
</div>
<div id="multiGrid" class="multi-grid"></div>
<div class="grid-actions">
<button type="button" class="history-action-button" onclick="location.href='/setup/camera'">+ ADD CAMERA</button>
<button type="button" class="history-action-button" id="addDroneBtn">+ ADD DRONE</button>
<span id="addDroneMsg" style="font-size:10px;color:#9edfff"></span>
</div>
</div>
<script>
(function () {
    const grid = document.getElementById("multiGrid");
    const count = document.getElementById("multiGridCount");
    const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
    const tiles = {};
    let names = {main: null, drone: null};

    const whenPlayerReady = fn => window.attachLiveCamera ? fn()
        : window.addEventListener("live-player-ready", fn, {once: true});
    const setSwitch = (btn, on) => btn.setAttribute("aria-pressed", on ? "true" : "false");
    const post = (url, body) => fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})
        .then(r => r.json().then(d => { if (!r.ok || !d.ok) throw new Error(d.error || "Request failed"); return d; }));

    // Show or stop one live view. Off = no stream at all (saves CPU), not just hidden.
    function showFeed(slot, on) {
        whenPlayerReady(() => {
            const running = slot.dataset.mode !== undefined;
            if (on && !running) window.attachLiveCamera(slot);
            if (!on && running) window.detachLiveCamera(slot);
        });
    }

    // Live feed switches on the main camera and drone panels.
    function syncPrimary(key, visible) {
        const btn = document.querySelector('[data-feed-switch="' + key + '"]');
        const slot = document.querySelector('[data-live-camera="' + (key === "main" ? "" : key) + '"]')
            || (key === "main" ? document.querySelector("[data-live-camera]:not([data-live-camera='drone'])") : null);
        if (!btn || !slot) return;
        const panel = btn.closest(".panel");
        if (!panel.querySelector(".feed-off-note")) {
            const note = document.createElement("div");
            note.className = "feed-off-note";
            note.textContent = "LIVE FEED OFF — switch it on to view. Recording and AI keep running.";
            panel.querySelector(".camera-box").after(note);
        }
        setSwitch(btn, visible);
        panel.classList.toggle("feed-off", !visible);
        showFeed(slot, visible);
    }
    document.querySelectorAll("[data-feed-switch]").forEach(btn => btn.addEventListener("click", async () => {
        const key = btn.dataset.feedSwitch, name = names[key];
        if (!name) return;
        const on = btn.getAttribute("aria-pressed") !== "true";
        btn.disabled = true;
        try { await post("/api/sources/" + encodeURIComponent(name) + "/feed", {visible: on}); syncPrimary(key, on); }
        catch (e) { alert(e.message); }
        finally { btn.disabled = false; }
    }));

    function tileFor(c) {
        const t = document.createElement("div");
        t.className = "grid-tile";
        t.innerHTML = '<div class="live-slot" data-live-camera="' + esc(c.name) + '" title="Double-click for full screen"></div>'
            + '<div class="tile-foot"><span><i class="tile-dot"></i><span class="tile-name">'
            + (c.kind === "drone" ? "✈ " : "▣ ") + esc(c.name) + '</span> <span class="tile-fps"></span></span>'
            + '<span class="tile-actions">'
            + (c.kind === "drone" ? '<a class="tile-btn" href="/drone-control?drone=' + encodeURIComponent(c.name) + '" style="text-decoration:none">CONTROLS</a>' : '')
            + '<button type="button" class="feed-switch" data-act="feed">FEED <span class="knob"></span></button>'
            + '<button type="button" class="tile-btn" data-act="pause"></button>'
            + '<button type="button" class="tile-btn danger" data-act="remove">REMOVE</button>'
            + '</span></div>';
        const slot = t.querySelector(".live-slot");
        t.querySelector('[data-act="feed"]').addEventListener("click", async e => {
            const btn = e.currentTarget, on = btn.getAttribute("aria-pressed") !== "true";
            btn.disabled = true;
            try { await post("/api/sources/" + encodeURIComponent(c.name) + "/feed", {visible: on}); applyTile(t, {...t._c, feed_visible: on}); }
            catch (err) { alert(err.message); } finally { btn.disabled = false; }
        });
        t.querySelector('[data-act="pause"]').addEventListener("click", async e => {
            const btn = e.currentTarget, paused = !t._c.paused;
            btn.disabled = true;
            try { await post("/api/sources/" + encodeURIComponent(c.name) + "/pause", {paused}); applyTile(t, {...t._c, paused}); }
            catch (err) { alert(err.message); } finally { btn.disabled = false; }
        });
        t.querySelector('[data-act="remove"]').addEventListener("click", async e => {
            if (!confirm("Remove " + c.name + "?\n\nIt will be deleted from Frigate and its slot freed on your plan. "
                + "Recordings already saved are kept.")) return;
            const btn = e.currentTarget;
            btn.disabled = true; btn.textContent = "REMOVING…";
            try {
                const r = await fetch("/api/sources/" + encodeURIComponent(c.name), {method: "DELETE"});
                const d = await r.json();
                if (!r.ok || !d.ok) throw new Error(d.error || "Could not remove");
                window.detachLiveCamera?.(slot);
                t.remove(); delete tiles[c.name];
                document.getElementById("addDroneMsg").textContent = d.message + " Frigate is restarting.";
            } catch (err) { alert(err.message); btn.disabled = false; btn.textContent = "REMOVE"; }
        });
        return t;
    }

    function applyTile(t, c) {
        t._c = c;
        const visible = c.feed_visible !== false;
        t.classList.toggle("feed-off", !visible);
        setSwitch(t.querySelector('[data-act="feed"]'), visible);
        showFeed(t.querySelector(".live-slot"), visible);
        const dot = t.querySelector(".tile-dot");
        dot.classList.toggle("on", !!c.online && !c.paused);
        dot.classList.toggle("paused", !!c.paused);
        t.querySelector(".tile-fps").textContent = c.over_limit ? "OVER LICENCE LIMIT" : c.paused ? "STOPPED" : (c.online ? c.fps + " FPS" : "OFFLINE");
        t.title = c.over_limit ? "Switched off: your licence allows fewer cameras/drones. Remove one or upgrade the licence." : "";
        t.querySelector('[data-act="pause"]').textContent = c.paused ? "START" : "STOP";
    }

    async function refresh() {
        let data;
        try { data = await fetch("/api/cameras", {cache: "no-store"}).then(r => r.json()); } catch (e) { return; }
        const all = data.cameras || [];
        names = {main: data.main, drone: data.drone};
        for (const key of ["main", "drone"]) {
            const c = all.find(x => x.name === names[key]);
            const btn = document.querySelector('[data-feed-switch="' + key + '"]');
            const wanted = c ? c.feed_visible !== false : true;
            if (btn && (btn.dataset.synced !== "1" || (btn.getAttribute("aria-pressed") === "true") !== wanted)) {
                syncPrimary(key, wanted);
                btn.dataset.synced = "1";
            }
        }
        // The main camera and first drone have their own panels above; the grid shows the rest.
        const extra = all.filter(c => !c.primary);
        count.textContent = all.filter(c => c.online).length + " / " + all.length + " ONLINE";
        if (!extra.length) {
            grid.innerHTML = '<div class="grid-empty">No additional cameras or drones yet. Use <b>+ ADD CAMERA</b> or <b>+ ADD DRONE</b> below; '
                + 'each one appears here live.</div>';
            for (const k in tiles) delete tiles[k];
            return;
        }
        grid.querySelector(".grid-empty")?.remove();
        for (const c of extra) {
            if (!tiles[c.name]) { tiles[c.name] = tileFor(c); grid.appendChild(tiles[c.name]); }
            applyTile(tiles[c.name], c);
        }
        for (const name of Object.keys(tiles)) {
            if (!extra.some(c => c.name === name)) { window.detachLiveCamera?.(tiles[name].querySelector(".live-slot")); tiles[name].remove(); delete tiles[name]; }
        }
    }

    document.getElementById("addDroneBtn").addEventListener("click", async () => {
        const btn = document.getElementById("addDroneBtn"), msg = document.getElementById("addDroneMsg");
        btn.disabled = true; msg.textContent = "Adding drone…";
        try {
            const r = await fetch("/api/setup/drone", {method: "POST"});
            const d = await r.json();
            if (!r.ok || !d.ok) throw new Error(d.error || "Could not add drone");
            msg.innerHTML = esc(d.message) + " RTMP: <code>" + esc(d.publish_url) + "</code>";
            setTimeout(refresh, 20000);  // Frigate restarts to load the new drone
        } catch (e) { msg.textContent = e.message; }
        finally { btn.disabled = false; }
    });

    refresh();
    setInterval(refresh, 10000);
})();
</script>


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
    data-event-key="{{ event.event_key }}"
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

<button type="button" class="delete-event-button" data-event-index="{{ loop.index0 }}" data-event-key="{{ event.event_key }}">DELETE EVENT</button>
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
    data-src="/video_feed"
    class="enroll-live-camera"
    alt=""
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

// Delete buttons ask on the page itself (click again to confirm): the browser's own confirm box
// can be switched off ("don't let this page create more dialogs"), which made deleting do nothing.
function armedForDelete(button, question) {
    if (button.dataset.armed === "1") return true;
    button.dataset.armed = "1";
    button.dataset.label = button.innerText;
    button.innerText = question;
    button.classList.add("confirm-armed");
    clearTimeout(button._disarm);
    button._disarm = setTimeout(() => {
        button.dataset.armed = "";
        button.innerText = button.dataset.label;
        button.classList.remove("confirm-armed");
    }, 4000);
    return false;
}

document.getElementById("clearAllEvents").addEventListener("click", async () => {
    const button = document.getElementById("clearAllEvents");
    if (!armedForDelete(button, "CLICK AGAIN TO CLEAR ALL EVENTS")) return;
    clearTimeout(button._disarm);
    const oldText = button.dataset.label;
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
    if (!armedForDelete(button, "CLICK AGAIN TO DELETE")) return;
    clearTimeout(button._disarm);
    const oldText = button.dataset.label;
    button.disabled = true;
    button.innerText = "DELETING...";

    try {
        const response = await fetch("/api/events/" + eventIndex, {
            method: "DELETE",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({key: button.dataset.eventKey || ""}),
        });
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




/* Stream the enrollment preview only while its window is open, so the dashboard
   doesn't decode the camera in the background. */
(function () {
    const overlay = document.getElementById("faceEnrollOverlay");
    const feed = document.getElementById("enrollCameraFeed");
    if (!overlay || !feed) return;
    const sync = () => {
        if (overlay.classList.contains("open")) {
            if (feed.dataset.on !== "1") { feed.src = feed.dataset.src || "/video_feed"; feed.dataset.on = "1"; }
        } else if (feed.dataset.on === "1") {
            feed.src = "data:,";  // aborts the open MJPEG connection
            feed.dataset.on = "0";
        }
    };
    new MutationObserver(sync).observe(overlay, {attributes: true, attributeFilter: ["class"]});
    sync();
})();

/* Enrollment source preview */
const faceEnrollSource = document.getElementById("faceEnrollSource");
if (faceEnrollSource) {
    faceEnrollSource.addEventListener("change", () => {
        const feed = document.getElementById("enrollCameraFeed");
        if (feed) {
            feed.dataset.src = faceEnrollSource.value === "drone" ? "/drone_video_feed" : "/video_feed";
            if (feed.dataset.on === "1") feed.src = feed.dataset.src;
        }
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

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
}

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
                    escapeHtml(
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
                                ${escapeHtml(name)}
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
                                ${escapeHtml(name)}
                            </div>

                            <div class="library-sub">
                                PLATE • ${escapeHtml(plate)}
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
    // The drone video itself is played (and reconnected) by the shared live player.
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

/* Links like /#history from the other pages open the matching panel. */
function openPanelFromHash() {
    const h = location.hash;
    if (h === "#history") openEventHistory();
    else if (h === "#face-library") document.getElementById("openFaceLibrary")?.click();
    else if (h === "#vehicle-library") document.getElementById("openVehicleLibrary")?.click();
}
window.addEventListener("hashchange", openPanelFromHash);
openPanelFromHash();
</script>


</body>

</html>
"""



PAGE = PAGE.replace("<!--HUD_SUBNAV-->", hud_subnav("dashboard"))
# Edition branding (e.g. "AI Command Centre Lebanon" for the on-prem build).
PAGE = (PAGE.replace("<title>\nAI Security Command Center\n</title>", f"<title>\n{edition.PRODUCT_NAME}\n</title>")
            .replace('<div class="brand-name">\nAI SECURITY\n</div>', f'<div class="brand-name">\n{edition.BRAND_TOP}\n</div>')
            .replace('<div class="brand-sub">\nCOMMAND CENTER\n</div>', f'<div class="brand-sub">\n{BRAND_SUB_HTML}\n</div>')
            .replace('<div class="rec-title">\nAI SECURITY CONTROLS\n</div>', f'<div class="rec-title">\n{edition.BRAND_TOP} CONTROLS\n</div>'))
_body_end = PAGE.rfind("</body>")
PAGE = PAGE[:_body_end] + LIVE_PLAYER_HTML + PAGE[_body_end:]

PAIRING_PAGE = hud_page("Pair Device", """
<main class="hud-main" style="max-width:560px;padding-top:8vh">
<section class="panel"><div class="panel-head"><div class="panel-title">⌁ Device pairing</div><div class="live">SECURE</div></div>
<div class="panel-body">
<div class="page-kicker">Setup</div><h1 class="page-title" style="margin-bottom:10px">Pair this Windows device</h1>
<p class="muted">In your Customer Portal, choose <b>Pair a Windows device</b>, then enter the one-time code below.</p>
<label for="name">Device name</label><input id="name" value="Windows Edge" placeholder="Device name">
<label for="code">Pairing code</label><input id="code" maxlength="8" placeholder="PAIRING CODE" style="text-transform:uppercase;letter-spacing:6px;font-size:18px;text-align:center">
<button id="pair" class="hud-btn primary" style="width:100%;margin-top:18px;min-height:44px">Pair device</button>
<div id="msg" class="hud-msg"></div>
</div></section></main>
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
</script>
<p class="muted" style="text-align:center;margin-top:-6px">Installing without internet? <a href="/license">Use a license file instead</a>.</p>""", nav=False)


LICENSE_PAGE = hud_page("License", r"""
<main class="hud-main narrow">
<div class="page-head"><div><div class="page-kicker">On-prem license</div><h1 class="page-title" id="prod">License</h1>
<div class="page-sub">Runs fully on this computer with a license file: no internet or cloud account needed.</div></div></div>
<section class="panel"><div class="panel-head"><div class="panel-title">⚿ This computer</div><div class="live" id="state">CHECKING</div></div>
<div class="panel-body">
<div class="hud-row"><div><b>Machine ID</b><div class="muted">Send this to your supplier to receive your license file.</div></div><code id="mid">…</code></div>
<div class="hud-row"><div><b>Status</b><div class="muted" id="reason">…</div></div><span class="state" id="valid">…</span></div>
<div id="details"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">⤓ Install license file</div></div>
<div class="panel-body">
<p class="muted" style="margin-top:0">Choose the <b>.lic</b> file you received. It only works on the computer whose Machine ID it was issued for.</p>
<input type="file" id="file" accept=".lic,application/json" style="color:#9edfff">
<div class="actions" style="margin-top:14px"><button class="hud-btn primary" id="install">Install license</button><button class="hud-btn" onclick="location.href='/'">Open dashboard</button></div>
<div id="msg" class="hud-msg"></div>
</div></section>
</main>
<script>
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
async function load(){
  const d=await fetch('/api/license',{cache:'no-store'}).then(r=>r.json());
  document.getElementById('prod').textContent=d.product+' — License';
  document.getElementById('mid').textContent=d.machine_id;
  document.getElementById('valid').innerHTML=d.valid?'<i class="dot good"></i>LICENSED':'<i class="dot bad"></i>NOT LICENSED';
  document.getElementById('state').textContent=d.valid?'ACTIVE':'REQUIRED';
  document.getElementById('reason').textContent=d.valid?('Valid until '+d.expires):d.reason;
  const u=d.usage||{},l=d.limits||{};
  document.getElementById('details').innerHTML=d.valid?
    '<div class="hud-row"><div><b>Licensed to</b></div><span class="state">'+esc(d.customer)+'</span></div>'+
    '<div class="hud-row"><div><b>Plan</b><div class="muted">'+esc((d.features||[]).join(', '))+'</div></div><span class="state">'+esc(String(d.plan||'').toUpperCase())+'</span></div>'+
    '<div class="hud-row"><div><b>Cameras</b></div><span class="state">'+esc(u.cameras)+' / '+esc(l.cameras??'∞')+'</span></div>'+
    '<div class="hud-row"><div><b>Drones</b></div><span class="state">'+esc(u.drones)+' / '+esc(l.drones??'∞')+'</span></div>'+
    '<div class="hud-row"><div><b>Licence ID</b><div class="muted">Same ID as in your supplier records</div></div><span class="state">'+esc(String(d.license_id||'').slice(0,8).toUpperCase())+'</span></div>':'';
}
document.getElementById('install').onclick=async()=>{
  const f=document.getElementById('file').files[0],m=document.getElementById('msg');
  if(!f){m.className='hud-msg bad';m.textContent='Choose a license file first.';return}
  const r=await fetch('/api/license',{method:'POST',headers:{'Content-Type':'application/json'},body:await f.text()});
  const d=await r.json();m.className='hud-msg '+(d.ok?'ok':'bad');m.textContent=d.ok?'License installed. Opening the dashboard…':d.error;
  if(d.ok){load();setTimeout(()=>location.href='/',1500)}
};
load();
</script>""", active="license")







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

SETTINGS_PAGE = hud_page("Settings", r"""
<main class="hud-main narrow">
<div class="page-head"><div><div class="page-kicker">Configuration</div><h1 class="page-title">Settings</h1><div class="page-sub">Simple controls for AI, cameras and drones.</div></div></div>
<section class="panel"><div class="panel-head"><div class="panel-title">◎ AI &amp; devices</div><div class="live">LOCAL</div></div><div class="panel-body">
<div class="hud-row"><div><b>Camera AI</b><div class="muted">Person and vehicle detection</div></div><input class="toggle" type="checkbox" data-key="camera_ai"></div>
<div class="hud-row"><div><b>Face recognition</b></div><input class="toggle" type="checkbox" data-key="face_ai"></div>
<div class="hud-row"><div><b>License plate recognition</b></div><input class="toggle" type="checkbox" data-key="lpr"></div>
<div class="hud-row"><div><b>Drone runtime</b><div class="muted">Live receiver only when needed</div></div><input class="toggle" type="checkbox" data-key="drone_runtime"></div>
<div class="hud-row"><div><b>Drone AI</b></div><input class="toggle" type="checkbox" data-key="drone_ai"></div>
<div class="hud-row"><div><b>Drone tracking assist</b></div><input class="toggle" type="checkbox" data-key="drone_tracking"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">✈ GPS dispatch</div><div class="live">SAFETY-GATED</div></div><div class="panel-body">
<p class="muted" style="margin-top:0">Store the camera location locally. Aircraft movement remains safety-gated behind a compatible flight-control bridge.</p>
<div class="hud-row"><div><b>Enable GPS dispatch</b></div><input class="toggle" type="checkbox" data-key="gps_dispatch"></div>
<div class="hud-row"><div><b>Camera latitude</b></div><input id="lat" type="number" step="any" style="width:180px"></div>
<div class="hud-row"><div><b>Camera longitude</b></div><input id="lon" type="number" step="any" style="width:180px"></div>
<div class="hud-row"><div><b>Safety radius (m)</b></div><input id="radius" type="number" min="10" max="1000" style="width:180px"></div>
<div class="hud-row"><div><b>Require dispatch confirmation</b></div><input class="toggle" type="checkbox" data-key="require_dispatch_confirmation"></div>
<div class="actions" style="margin-top:16px"><button class="hud-btn primary" onclick="save()">Save settings</button></div>
<div id="msg" class="hud-msg">Loading…</div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">＋ Add device</div></div><div class="panel-body">
<p class="muted" style="margin-top:0">Scan the current local network for nearby camera and stream candidates.</p>
<button class="hud-btn" onclick="location.href='/setup/discover'">Add camera or drone</button>
</div></section>
</main>
<script>let cfg={};async function load(){cfg=await fetch('/api/customer/settings').then(r=>r.json());document.querySelectorAll('[data-key]').forEach(x=>x.checked=!!cfg[x.dataset.key]);lat.value=cfg.camera_latitude??'';lon.value=cfg.camera_longitude??'';radius.value=cfg.gps_safety_radius_m??120;msg.textContent='Settings loaded'}async function save(){document.querySelectorAll('[data-key]').forEach(x=>cfg[x.dataset.key]=x.checked);cfg.camera_latitude=lat.value===''?null:Number(lat.value);cfg.camera_longitude=lon.value===''?null:Number(lon.value);cfg.gps_safety_radius_m=Number(radius.value||120);let d=await fetch('/api/customer/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)}).then(r=>r.json());msg.textContent=d.ok?'Saved. Controls applied.':(d.message||'Could not save.')}load()</script>""", active="settings")
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
    for event in events + history_events:
        event["event_key"] = event_key(event)
    return events, history_events

@app.route("/")
def dashboard():
    if not onprem_mode():
        if edition.EDITION == "onprem":
            return redirect("/license")  # on-prem edition: a license file, never cloud pairing
        edge_cfg = load_edge_agent_config()
        if not str(edge_cfg.get("device_token") or "").strip():
            return Response(PAIRING_PAGE, mimetype="text/html")
    events, history_events = _dashboard_context()
    return render_template_string(PAGE, events=events, history_events=history_events)

@app.route("/api/license", methods=["GET", "POST"])
def api_license():
    """On-prem license status (with this PC's Machine ID) and license installation."""
    if request.method == "POST":
        raw = request.get_data(as_text=True) or ""
        try:
            doc = json.loads(raw)
        except Exception:
            return jsonify({"ok": False, "error": "That is not a license file."}), 400
        ok, reason, payload = licensing.verify(doc)
        if not ok:
            return jsonify({"ok": False, "error": reason}), 400
        tmp = LICENSE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        os.replace(tmp, LICENSE_FILE)
        check_offline_license()
        with cloud_lock:
            cloud_state["usage"] = local_source_usage()
        return jsonify({"ok": True, "message": "License installed.", "license": offline_license["payload"]})
    payload = offline_license.get("payload") or {}
    return jsonify({"ok": True, "machine_id": licensing.machine_id(), "edition": edition.EDITION,
                    "product": edition.PRODUCT_NAME, "valid": onprem_mode(),
                    "reason": offline_license.get("reason"), "customer": payload.get("customer"),
                    "plan": payload.get("plan"), "expires": payload.get("expires"), "license_id": payload.get("license_id"),
                    "features": payload.get("features") or [], "limits": payload.get("limits") or {},
                    "usage": local_source_usage()})


@app.route("/license")
def license_page():
    return Response(LICENSE_PAGE, mimetype="text/html")


@app.route("/legacy")
def legacy_dashboard():
    # Old address of the full dashboard, which is now the main page.
    return redirect("/", code=301)


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
# The live config first; C:\frigate only for PCs still running a pre-V11.1 Frigate container.
FRIGATE_CONFIG_CANDIDATES = [
    LIVE_FRIGATE_CONFIG,
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
    # Prefer the previously working stream (main quality first), then the other Tapo stream.
    paths=[]
    for p in (old_stream,"/stream1","/stream2"):
        if p not in paths:paths.append(p)
    from urllib.parse import quote
    for ip in candidates:
        if not _port(ip,port,.5):
            return {"ip":ip,"mac":neighbors.get(ip),"stream":old_stream,"adapter":adapter,"stream_ready":False}
        for pth in paths:
            url=f"rtsp://{quote(user,safe='')}:{quote(pw,safe='')}@{ip}:{port}{pth}"
            # Give the stream the user had more time before falling back to another one.
            if _rtsp_auth_probe(url,8 if pth==old_stream else 4):
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
        # Compare only values both checks actually read: under heavy CPU load the Windows
        # network query can time out and return a blank gateway, which looked like a
        # network change and triggered needless camera rediscovery and Frigate restarts.
        def _changed(key):
            a, b = previous_net.get(key), current_net.get(key)
            return bool(a and b and a != b)
        network_changed=bool(previous_net and (_changed("gateway") or _changed("network")))
        expected_mac=(rec.get("mac") or "").lower()
        current_mac=None
        if _ip_on_active_lan(ip):
            # Populate ARP first; this is safe and does not open RTSP.
            try: run_background_command(["ping","-n","1","-w","120",ip],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=1)
            except Exception: pass
            current_mac=(_neighbor_mac(ip) or "").lower()

        identity_ok=(not expected_mac) or (current_mac and current_mac==expected_mac)
        # Frigate receiving frames proves the stream works. Opening another RTSP session
        # here often missed its 3 s window (Tapo is slow to start sessions and limits how
        # many it allows), which sent every check into a full 254-address ping sweep.
        stream_ok = frigate_camera_online() or _rtsp_auth_probe(url,6)
        if (not network_changed) and _ip_on_active_lan(ip) and identity_ok and _port(ip,port,.5) and stream_ok:
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
        if found["ip"]==ip:
            # Same camera at the same address: a probe just timed out (busy PC or network blip).
            # Never rewrite the config or switch to another stream for that; keep the user's stream.
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

def main():
    """Start the dashboard web server. Called by `python dashboard.py` and by the packaged
    launcher (which imports this module, also when it is compiled to native code)."""
    _start_v105_recovery()
    start_drone_link()
    start_virtual_drones()
    threading.Thread(target=_enforce_source_limits_worker, daemon=True).start()
    start_assistant()
    print()
    print(
        "======================================"
    )
    print(
        "       " + edition.PRODUCT_NAME.upper()
    )
    print(
        "======================================"
    )
    print()
    print(
        "Dashboard:"
        f" http://localhost:{PORT}"
    )
    print(f"{APP_VERSION} CUSTOMER PLATFORM")
    print()

    # The browser polls several endpoints every second; logging each request
    # grew dashboard.log to hundreds of MB. Keep warnings and errors only.
    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    app.run(
        host="127.0.0.1",
        port=PORT,
        debug=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()
