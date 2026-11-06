import copy
import sys
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
    session,
    g,
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
APP_VERSION = "V11.3.4"

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
        if msg.topic == MQTT_EVENTS_TOPIC and camera and _is_drone_name(camera) and data.get("type") in ("new", "update"):
            after_seen = data.get("after") if isinstance(data.get("after"), dict) else {}
            if after_seen.get("false_positive") is False:
                note_drone_detection(camera, str(after_seen.get("label") or "").lower(), str(after_seen.get("id") or ""))
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
        if msg.topic == MQTT_EVENTS_TOPIC and camera and not _is_drone_name(camera) and data.get("type") in ("new", "update"):
            after_auto = data.get("after") if isinstance(data.get("after"), dict) else {}
            if after_auto.get("false_positive") is False:
                threading.Thread(target=auto_dispatch_check, daemon=True,
                                 args=(camera, str(after_auto.get("label") or "").lower(), str(after_auto.get("id") or ""),
                                       bool(after_auto.get("stationary")))).start()
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
import nofly
import mapping
import weather
import airtraffic
import airspace
import rf
from geo import _bearing_deg, _distance_m, _wrap180  # noqa: E402
import virtual_drone
from virtual_drone import VirtualDrone  # noqa: E402
import pages.drone_control, pages.drone_grid, pages.virtual_drones, pages.device_wizard, pages.maps, pages.safety, pages.live4d, pages.mapsearch  # noqa: E401
import users as user_accounts

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

from pages.hud import HUD_CSS  # noqa: E402

# Live camera player shared by the dashboard pages. Any element with data-live-camera
# plays the camera straight from Frigate's go2rtc relay (MSE over WebSocket, decoded by
# the browser) with detection boxes drawn on a canvas. Falls back to /video_feed (MJPEG,
# decoded by this program) when the relay is unavailable.
from pages.live_player import LIVE_PLAYER_HTML  # noqa: E402

HUD_NAV_ITEMS = [
    ("dashboard", "/", "⌂", "Dashboard"),
    ("drone", "/drone-control", "✈", "Drone"),
    ("virtual", "/virtual-drones", "◇", "Virtual drones"),
    ("devices", "/setup/add", "＋", "Devices"),
    ("settings", "/settings", "⚙", "Settings"),
]
# Pages reached from inside a tab light up that tab: 3D maps and flight safety from Drone; events, people,
# vehicles, licence and users from Settings.
NAV_ALIAS = {"maps": "drone", "safety": "drone", "license": "settings", "users": "settings",
             "events": "settings", "people": "settings", "vehicles": "settings"}


def hud_topbar(active="", nav=True):
    active = NAV_ALIAS.get(active, active)
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
    active = NAV_ALIAS.get(active, active)
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


DEVICE_WIZARD_PAGE = hud_page("Devices", pages.device_wizard.BODY, active="devices")


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
    for r in list(route_runs.values()):
        if r["active"]:
            busy[r["drone"]] = "route"
            if r.get("backup"):
                busy.setdefault(r["backup"], "backup")
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


@app.route("/api/drone/remove", methods=["POST"])
def api_drone_remove():
    """Remove a drone (admins; the sign-in rules keep operators out). A virtual drone is deleted, an added drone is
    removed from the cameras and the plan, and the first drone, which always stays, is unpaired instead."""
    slot = (request.get_json(silent=True) or {}).get("drone")
    if slot not in drone_slots():
        return jsonify({"ok": False, "error": "Unknown drone."}), 404
    tel = get_link(slot)["telemetry"] if link_fresh(slot, 5) else {}
    if tel.get("flying"):
        return jsonify({"ok": False, "error": f"{drone_label(slot)} is flying. Land it first."}), 409
    if _drone_busy(slot):
        return jsonify({"ok": False, "error": f"{drone_label(slot)} is on a mission (route, response or backup). Stop it first."}), 409
    label = drone_label(slot)
    if is_virtual(slot):
        with app.test_request_context(method="DELETE"):
            r = api_virtual_drone(slot)
        resp = r[0] if isinstance(r, tuple) else r
        if not resp.get_json().get("ok", True):
            return resp, (r[1] if isinstance(r, tuple) else 400)
        drone_trails.pop(slot, None)
        return jsonify({"ok": True, "removed": True, "message": f"{label} removed."})
    if slot == DRONE_CAMERA_NAME:
        drone_link_token(reset=True, slot=slot)
        link = get_link(slot)
        with link["lock"]:
            if link["conn"] is not None:
                _drone_drop(link["conn"], "drone removed (unpaired)", slot)
        link.update(telemetry={}, tel_at=0.0, device="")
        drone_trails.pop(slot, None)
        return jsonify({"ok": True, "removed": False,
                        "message": f"{label} unpaired: its phone was disconnected and it has a new pairing code. "
                                   "The first drone slot always stays; pair another phone when you need it."})
    try:
        r = _remove_source(slot)
    except OSError as e:
        return jsonify({"ok": False, "error": f"Could not update the camera settings file ({e.strerror or e}). Try again."}), 409
    drone_trails.pop(slot, None)
    return jsonify({**r.get_json(), "removed": True, "message": f"{label} removed."})


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
    if cmd == "takeoff" and not link["telemetry"].get("flying"):
        tel = link["telemetry"]
        home = (tel.get("home_lat") or tel.get("lat"), tel.get("home_lon") or tel.get("lon"))
        problem = flight_conditions(home if None not in home else None)[0]
        if problem and not args.get("force"):
            return jsonify({"ok": False, "error": problem, "can_force": True}), 409
        args = {}
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
        z = nofly.zone_at(nofly_zones(), lat, lon)
        if z:
            return jsonify({"ok": False, "error": f"That point is inside no-fly zone “{z['name']}”."}), 400
        if tel.get("lat") and nofly.leg_zone(nofly_zones(), (tel["lat"], tel["lon"]), (lat, lon),
                                             {x["id"] for x in nofly_zones() if nofly.zone_at([x], tel["lat"], tel["lon"])}):
            return jsonify({"ok": False, "error": "The straight line there crosses a no-fly zone. Add it as a route stop instead and the route flies round it."}), 400
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
    if cmd == "go_home":
        result = _go_home_safe(slot, "Return home pressed")  # flies round no-fly zones first if needed
    else:
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


virtual_drone.host = sys.modules[__name__]


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


VIRTUAL_DRONES_PAGE = hud_page("Virtual Drones", pages.virtual_drones.BODY, active="virtual")


@app.route("/drone-grid")
def drone_grid_page():
    return DRONE_GRID_PAGE


DRONE_GRID_PAGE = hud_page("Drone Grid", pages.drone_grid.BODY, active="drone")
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
    user = getattr(g, "user", None)
    admin = user is None or user.get("role") == "admin"  # sign-in off: whoever is at the PC is the admin
    return (page.replace('data-live-camera="drone"', f'data-live-camera="{slot}"')
            .replace("const DRONE='drone';", f"const DRONE={json.dumps(slot)};const IS_ADMIN={json.dumps(admin)};")
            .replace("<title>", f"<title>{drone_label(slot)} · ", 1)
            .replace('<h1 class="page-title">Drone Control</h1>', f'<h1 class="page-title">Drone Control · {drone_label(slot)}</h1>', 1))


DRONE_CONTROL_PAGE = hud_page("Drone Control", pages.drone_control.BODY, active="drone", head=pages.live4d.IMPORTMAP)
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
                     "min_battery": 35, "briefing_enabled": True, "briefing_time": "08:00", "patrol_schedules": [],
                     # Auto-send the nearest drone when a camera sees someone at night (off until the owner turns it on).
                     "auto_dispatch": False, "auto_person": True, "auto_vehicle": True, "auto_from": "19:00", "auto_to": "06:00",
                     "auto_cooldown_min": 10}
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
        elif k in ("altitude_m", "speed_ms", "hover_seconds", "min_battery", "auto_cooldown_min"):
            lo, hi = {"altitude_m": (10, DRONE_LIMITS["max_altitude_m"]), "speed_ms": (1, 8), "hover_seconds": (10, 600), "min_battery": (20, 90),
                      "auto_cooldown_min": (1, 120)}[k]
            v = max(lo, min(hi, float(v)))
        elif k in ("auto_return", "briefing_enabled", "auto_dispatch", "auto_person", "auto_vehicle"):
            v = bool(v)
        elif k in ("auto_from", "auto_to"):
            v = str(v) if re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(v)) else RESPONSE_DEFAULTS[k]
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
            or run_of(slot) is not None or backup_run_of(slot) is not None)


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
    problem = flight_conditions(home)[0]  # weather and crewed aircraft
    if problem:
        return problem
    b = backup_run_of(slot)
    if b:
        return f"It is the backup drone for {drone_label(b['drone'])} on route {b['name']}."
    if _drone_busy(slot):
        return "The drone is already on a mission."
    return ""


def _nearest_ready(camera):
    """The ready drone closest to the camera, judged by where each drone is right now. Returns (slot, problem)."""
    slot, problem = _pick_drone(lambda d: _drone_ready_problem(camera, d))
    loc = load_response_settings()["camera_locations"].get(camera)
    if not slot or not loc:
        return slot, problem
    ready = [d for d in drone_slots() if d not in _sources_over_limit() and (not is_virtual(d) or _virtual_cfg.get("demo_auto"))
             and not _drone_ready_problem(camera, d)]

    def far(d):
        tel = get_link(d)["telemetry"]
        return _distance_m(tel["lat"], tel["lon"], loc["lat"], loc["lon"]) if tel.get("lat") else math.inf
    return min(ready, key=far), ""


def dispatch_drone(camera, by="dashboard", drone=None):
    if drone_response["active"]:
        return {"ok": False, "error": f"{drone_label(drone_response['drone'])} is already responding to {drone_response['camera']}."}
    slot, problem = _pick_drone(lambda d: _drone_ready_problem(camera, d), drone) if drone else _nearest_ready(camera)
    if problem:
        return {"ok": False, "error": problem}
    cfg = load_response_settings()
    loc = cfg["camera_locations"][camera]
    tel = get_link(slot)["telemetry"]
    via = nofly.detour(nofly_zones(), (tel["lat"], tel["lon"]), (loc["lat"], loc["lon"])) if tel.get("lat") else []
    if via is None:
        z = nofly.zone_at(nofly_zones(), loc["lat"], loc["lon"])
        return {"ok": False, "error": f"Camera {camera} is inside no-fly zone “{z['name']}”." if z else
                f"There is no way round the no-fly zones to {camera}."}
    first = via[0] if via else (loc["lat"], loc["lon"])
    goto = {"alt": cfg["altitude_m"], "speed": cfg["speed_ms"], "arrive": "hover", "lost_link": "home"}
    result = drone_command("goto", {"lat": first[0], "lon": first[1], **goto}, timeout=15.0, slot=slot)
    if not result["ok"]:
        return result
    who = drone_label(slot) if len(drone_slots()) > 1 else "Drone"
    drone_response.update(active=True, drone=slot, camera=camera, phase="flying", started=time.time(), arrived=0.0, stay_until=0.0, by=by,
                          message=f"{who} on its way to {camera}", routing=bool(via),
                          began=time.time(), log_pending=True, cam_snap=None, drone_snap=None)
    # The camera's view when the drone was sent, for the event record (fetched in the background).
    threading.Thread(target=lambda: drone_response.update(cam_snap=_camera_snapshot(camera)), daemon=True).start()
    if via:
        def round_zones():
            # The response worker waits while the drone flies round the zones, then watches the last leg as usual.
            for q, nxt in zip(via, via[1:] + [(loc["lat"], loc["lon"])]):
                if _wait_point(slot, q, time.time(), lambda: not drone_response["active"]):
                    break
                if not drone_command("goto", {"lat": nxt[0], "lon": nxt[1], **goto}, timeout=15.0, slot=slot)["ok"]:
                    break
            drone_response.update(routing=False, started=time.time())
        threading.Thread(target=round_zones, daemon=True).start()
        _drone_event(f"Flying round the no-fly zones to {camera} ({len(via)} turn{'s' if len(via) > 1 else ''})", slot)
    _drone_event(f"Drone response to {camera} started ({by})", slot)
    return {"ok": True, "drone": slot, "message": f"{who} on its way to {camera} at {int(cfg['altitude_m'])} m."}


def _in_window(start, end, now=None):
    """Is the time now (HH:MM) inside start..end? The window may cross midnight; start == end means all day."""
    now = now or time.strftime("%H:%M")
    if start == end:
        return True
    return start <= now < end if start < end else (now >= start or now < end)


_auto_seen, _auto_last = set(), {}


def auto_dispatch_check(camera, label, object_id="", stationary=False):
    """A camera saw something: send the nearest ready drone if auto-dispatch is on and it is inside the night window."""
    try:
        cfg = load_response_settings()
        if not cfg["auto_dispatch"] or not drone_control_allowed() or stationary:
            return None
        vehicle = label in ("car", "motorcycle", "truck", "bus")
        if not ((label == "person" and cfg["auto_person"]) or (vehicle and cfg["auto_vehicle"])):
            return None
        if not _in_window(cfg["auto_from"], cfg["auto_to"]) or camera not in cfg["camera_locations"] or drone_response["active"]:
            return None
        if object_id and object_id in _auto_seen:
            return None
        if time.time() - _auto_last.get(camera, 0) < cfg["auto_cooldown_min"] * 60:
            return None
        _auto_last[camera] = time.time()
        if object_id:
            _auto_seen.add(object_id)
        what = "Person" if label == "person" else "Vehicle"
        r = dispatch_drone(camera, by=f"auto: {what.lower()} seen")
        if r["ok"]:
            tel, loc = get_link(r["drone"])["telemetry"], cfg["camera_locations"][camera]
            far = f", {int(_distance_m(tel['lat'], tel['lon'], loc['lat'], loc['lon']))} m away" if tel.get("lat") else ""
            send_telegram(f"🚨 {what} seen by {camera}. {drone_label(r['drone'])} (nearest ready drone{far}) is flying there now.",
                          _camera_snapshot(camera), [[{"text": "🏠 Recall drone", "callback_data": "home"}]])
        else:
            send_telegram(f"🚨 {what} seen by {camera}, but no drone could be sent: {r['error']}")
        return r
    except Exception as e:
        print("Auto-dispatch error:", e)
        return None


CLIP_DELAY_S = 20  # Frigate writes recordings in short segments; wait for the last one before asking for the clip


def _fetch_clip(slot, start, end):
    """The drone camera's recording between start and end (Frigate), or None. Virtual drones have no video."""
    if is_virtual(slot) or end - start > 1800:
        return None
    try:
        r = requests.get(f"{FRIGATE_API_URL}/api/{slot}/start/{int(start)}/end/{int(end) + 1}/clip.mp4", timeout=90)
        if r.ok and len(r.content) > 2000 and b"ftyp" in r.content[:64]:
            return r.content
    except Exception as e:
        print("Drone clip error:", e)
    return None


def _append_event_row(row):
    with event_log_lock:
        os.makedirs(os.path.dirname(EVENT_LOG), exist_ok=True)
        fieldnames = ["Date", "Time", "Type", "Name", "Identifier", "Snapshot"]
        exists = os.path.exists(EVENT_LOG) and os.path.getsize(EVENT_LOG) > 0
        if exists:
            with open(EVENT_LOG, "r", encoding="utf-8") as f:
                fieldnames = csv.DictReader(f).fieldnames or fieldnames
        with open(EVENT_LOG, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if not exists:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in fieldnames})


def save_response_event(resp, ended):
    """One event-history record per drone response: the camera's snapshot plus the drone's view and video.
    The drone files sit next to the snapshot as <name>_drone.jpg / <name>_drone.mp4."""
    try:
        time.sleep(CLIP_DELAY_S)
        slot, camera, began = resp.get("drone"), resp.get("camera"), resp.get("began") or resp.get("started") or ended
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(began))
        safe = re.sub(r"[^\w-]", "", str(slot))
        base = os.path.join(EVENT_FOLDER, f"drone_response_{stamp}_{safe}")
        os.makedirs(EVENT_FOLDER, exist_ok=True)
        cam_snap, drone_snap = resp.get("cam_snap"), resp.get("drone_snap")
        clip = _fetch_clip(slot, began, ended)
        snapshot = ""
        if cam_snap or drone_snap:
            snapshot = base + ".jpg"
            with open(snapshot, "wb") as f:
                f.write(cam_snap or drone_snap)
        if drone_snap and cam_snap:
            with open(base + "_drone.jpg", "wb") as f:
                f.write(drone_snap)
        if clip:
            if not snapshot:  # the row needs a snapshot name for the drone files to hang off
                snapshot = base + ".jpg"
                with open(snapshot, "wb") as f:
                    f.write(_drone_snapshot(slot) or b"")
            with open(base + "_drone.mp4", "wb") as f:
                f.write(clip)
        t = time.localtime(began)
        _append_event_row({"Date": time.strftime("%Y-%m-%d", t), "Time": time.strftime("%H:%M:%S", t), "Type": "DRONE RESPONSE",
                           "Name": f"{drone_label(slot)} → {camera}", "Identifier": f"{resp.get('by') or ''} · {resp.get('message') or ''}"[:120],
                           "Camera": camera, "Snapshot": snapshot})
    except Exception as e:
        print("Drone response event error:", e)


def recall_drone(reason="recalled"):
    if not drone_response["active"]:
        return {"ok": False, "error": "No drone response in progress."}
    result = _go_home_safe(drone_response["drone"], reason)
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
        if drone_response.get("log_pending") and not drone_response["active"]:
            drone_response["log_pending"] = False
            threading.Thread(target=save_response_event, args=(dict(drone_response), time.time()), daemon=True).start()
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
            if drone_response["phase"] == "flying" and drone_response.get("routing"):
                continue  # still flying round a no-fly zone
            if drone_response["phase"] == "flying":
                if not mission and drone_response["started"] and time.time() - drone_response["started"] > 5:
                    loc = cfg["camera_locations"].get(cam) or {}
                    near = tel.get("lat") and loc and _distance_m(tel["lat"], tel["lon"], loc["lat"], loc["lon"]) < 8
                    if near:
                        drone_response.update(phase="hovering", arrived=time.time(), stay_until=time.time() + cfg["hover_seconds"],
                                              message=f"Hovering over {cam}")
                        drone_response["drone_snap"] = snap = _drone_snapshot()
                        send_telegram(f"🚁 {drone_label(drone_response['drone'])} is over {cam} at {int(tel.get('altitude') or 0)} m. Battery {tel.get('battery')}%.\n"
                                      f"{'Returning home in ' + str(int(cfg['hover_seconds'])) + ' s.' if cfg['auto_return'] else 'Staying until you send it home.'}",
                                      snap, [[{"text": "🏠 Return now", "callback_data": "home"}, {"text": "⏱ Stay 2 min", "callback_data": "stay"}],
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
            r, b = run_of(slot), backup_run_of(slot)
            route = (f" · flying route {r['name']}" if r else "") + (f" · backup for {drone_label(b['drone'])}" if b else "")
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
    threading.Thread(target=_nofly_watch_worker, daemon=True).start()
    start_mapping()
    threading.Thread(target=_traffic_worker, daemon=True).start()
    threading.Thread(target=_trail_worker, daemon=True).start()


# ---------- multi-stop routes (draw on the map, fly stop by stop) ----------
ROUTES_FILE = os.path.join(os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER), "drone_routes.json")
ROUTE_MAX_POINTS = 25
NOFLY_FILE = os.path.join(os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER), "nofly_zones.json")
LOST_LINK_ACTIONS = ("home", "hover", "land")


def nofly_zones():
    return nofly.active(nofly.load_zones(NOFLY_FILE))


def _lost_link_args(route):
    """What the phone does by itself if the PC link drops mid-flight ('' = hand control back to the pilot)."""
    return {"lost_link": route.get("lost_link", "home") if route.get("lost_link_on", True) else ""}


def _wait_point(slot, q, started, should_stop=lambda: False, limit=900):
    """Wait until the drone's auto-fly reaches q = (lat, lon). '' on arrival, else why it ended."""
    while True:
        time.sleep(0.5)
        if should_stop():
            return "stopped from the PC"
        link = get_link(slot)
        if time.time() - link["tel_at"] > 5:
            if time.time() - started > limit:
                return "lost contact with the drone"
            continue
        tel = link["telemetry"]
        if tel.get("mission") or time.time() - started < 3:
            continue
        if tel.get("lat") and _distance_m(tel["lat"], tel["lon"], q[0], q[1]) < 8:
            return ""
        return "STOP pressed, the pilot took control or the link dropped"


def _go_home_safe(slot, why="return home"):
    """Return home. DJI's return home flies straight back, so first fly round any no-fly zone in the way."""
    tel = get_link(slot)["telemetry"]
    home = (tel.get("home_lat"), tel.get("home_lon"))
    via = []
    if tel.get("lat") and None not in home:
        via = nofly.detour(nofly_zones(), (tel["lat"], tel["lon"]), home) or []
    if not via:
        return drone_command("go_home", timeout=10.0, slot=slot)
    alt = max(30.0, float(tel.get("altitude") or 0))

    def fly():
        _drone_event(f"Flying round a no-fly zone before returning home ({why})", slot)
        for q in via:
            r = drone_command("goto", {"lat": q[0], "lon": q[1], "alt": alt, "speed": 6, "arrive": "hover", "lost_link": "home"},
                              timeout=15.0, slot=slot)
            if not r["ok"] or _wait_point(slot, q, time.time()):
                break
        drone_command("go_home", timeout=10.0, slot=slot)
    threading.Thread(target=fly, daemon=True).start()
    return {"ok": True, "error": ""}


def _nofly_watch_worker():
    """Tell the owner when any drone is inside a no-fly zone (manual flying can still take it there)."""
    inside = {}
    while True:
        time.sleep(1)
        try:
            zones = nofly_zones()
            for slot in drone_slots():
                link = get_link(slot)
                tel = link["telemetry"]
                if not zones or time.time() - link["tel_at"] > 5 or not tel.get("flying") or not tel.get("lat"):
                    inside.pop(slot, None)
                    continue
                z = nofly.zone_at(zones, tel["lat"], tel["lon"])
                if z and inside.get(slot) != z["id"]:
                    _drone_event(f"⛔ Entered no-fly zone {z['name']}", slot)
                    send_telegram(f"⛔ {drone_label(slot)} is inside no-fly zone “{z['name']}”. Fly it out.") if telegram_ready() else None
                inside[slot] = z["id"] if z else None
        except Exception as e:
            print("No-fly watch error:", e)
route_runs = {}  # run id -> state; each drone can fly its own route (a run moves to the backup drone on a handover)


def run_of(slot):
    """The active route this drone is flying, if any."""
    return next((r for r in list(route_runs.values()) if r["active"] and r["drone"] == slot), None)


def backup_run_of(slot):
    """The active route this drone stands by for as the chosen backup, if any."""
    return next((r for r in list(route_runs.values()) if r["active"] and r.get("backup") == slot and r["drone"] != slot), None)


def load_routes():
    try:
        with open(ROUTES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _clean_route(r):
    # A 3D-map survey flies a grid with more stops than a patrol; it is built by the 3D Maps page, never typed in.
    survey = r.get("survey") if mapping._safe_id(r.get("survey")) else None
    pts = [{"lat": float(p["lat"]), "lon": float(p["lon"])} for p in (r.get("points") or [])
           if -90 <= float(p["lat"]) <= 90 and -180 <= float(p["lon"]) <= 180][:mapping.MAX_POINTS if survey else ROUTE_MAX_POINTS]
    return {**({"survey": survey} if survey else {}), "points": pts, "alt": max(10.0, min(float(DRONE_LIMITS["max_altitude_m"]), float(r.get("alt") or 30))),
            "speed": max(1.0, min(8.0, float(r.get("speed") or 5))), "pause": max(0.0, min(120.0, float(r.get("pause") or 0))),
            "end": r.get("end") if r.get("end") in ("hover", "home", "land") else "home",
            "loop": bool(r.get("loop") or r.get("ignore_battery")), "relay": bool(r.get("relay")),
            "ignore_battery": bool(r.get("ignore_battery")),
            "lost_link_on": r.get("lost_link_on", True) is not False,
            "lost_link": r.get("lost_link") if r.get("lost_link") in LOST_LINK_ACTIONS else "home",
            "swap_at": max(20, min(50, int(float(r.get("swap_at") or 20))))}


def save_route(name, route):
    name = re.sub(r"[^\w \-]", "", str(name or "")).strip()[:40]
    if not name:
        raise ValueError("Give the route a name")
    routes = load_routes()
    route = _clean_route(route)
    problem = nofly.route_problem(nofly_zones(), route["points"], route["loop"])
    if problem:
        raise ValueError(problem)
    routes[name] = route
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
    problem = nofly.route_problem(nofly_zones(), pts, route.get("loop"), home, route.get("end") == "home")
    if problem:
        return problem
    problem = flight_conditions(home)[0]  # weather and crewed aircraft
    if problem:
        return problem
    if (tel.get("battery") or 0) < load_response_settings()["min_battery"]:
        return f"Battery is {tel.get('battery')}%."
    b = backup_run_of(slot)
    if b:
        return f"It is the backup drone for {drone_label(b['drone'])} on route {b['name']}."
    if _drone_busy(slot):
        return "The drone is already on a mission."
    return ""


def _wait_arrival(p, started, run):
    """Wait until the phone's auto-fly reaches p. Returns '' on arrival, else why it ended."""
    while True:
        time.sleep(0.5)
        if run["stop"]:
            return "stopped from the PC"
        link = get_link(run["drone"])
        if time.time() - link["tel_at"] > 5:
            if time.time() - started > 900:
                return "lost contact with the drone"
            continue  # Wi-Fi hiccup: wait
        tel = link["telemetry"]
        if run.get("swap_at") and tel.get("battery") is not None and tel["battery"] <= run["swap_at"]:
            return SWAP
        if tel.get("mission"):
            continue
        if time.time() - started < 3:
            continue  # the mission may not have started yet
        if tel.get("lat") and _distance_m(tel["lat"], tel["lon"], p["lat"], p["lon"]) < 8:
            return ""
        b = tel.get("battery")
        if str(tel.get("flight_mode") or "").upper() in ("GO_HOME", "AUTO_LANDING", "LANDING"):
            mode = str(tel.get('flight_mode')).replace('_', ' ').lower()
            if b is not None and b <= 20:
                return f"the drone's own low-battery protection took over at {b}% ({mode})"
            return f"the drone took over by itself ({mode}): the link dropped and it did its lost-link action, or the pilot sent it"
        return "STOP pressed, the pilot took control or the link dropped"


SWAP = "__battery_swap__"
REPORT_LABELS = {"person": "person", "car": "vehicle", "motorcycle": "vehicle", "truck": "vehicle", "bus": "vehicle"}
drone_detections = []  # (time, drone, "person"/"vehicle", object id), last 2000


def note_drone_detection(slot, label, object_id=""):
    """A drone camera saw a person or vehicle. Kept for patrol reports; a patrol also grabs a photo of it."""
    kind = REPORT_LABELS.get(label)
    if not kind or any(o == object_id and d == slot for _, d, _, o in drone_detections[-200:] if object_id):
        return
    drone_detections.append((time.time(), slot, kind, object_id))
    del drone_detections[:-2000]
    run = run_of(slot)
    if run is not None and len(run.get("photos", [])) < 8:
        _patrol_photo(run, slot, f"{kind} seen")


def _patrol_photo(run, slot, why):
    def grab():
        snap = _drone_snapshot(slot)
        if snap and len(run["photos"]) < 9:
            run["photos"].append((snap, f"{drone_label(slot)}: {why}"))
    threading.Thread(target=grab, daemon=True).start()


def send_telegram_album(photos, caption=""):
    """Up to 10 photos in one Telegram message (photos: list of jpg bytes)."""
    photos = photos[:10]
    if not photos:
        return None
    if len(photos) == 1:
        return send_telegram(caption, photos[0])
    chat = str(load_telegram_config().get("chat_id") or "").strip()
    media = [{"type": "photo", "media": f"attach://p{i}", **({"caption": caption[:1000]} if i == 0 and caption else {})} for i in range(len(photos))]
    return _tg("sendMediaGroup", chat_id=chat, media=json.dumps(media),
               files={f"p{i}": (f"p{i}.jpg", b, "image/jpeg") for i, b in enumerate(photos)})


def patrol_report(name, run, ended_how):
    """Short summary after a patrol: time, laps, battery used per drone, what the drones saw, photos."""
    end = time.time()
    began = run.get("began") or end
    mins = max(0, int(round((end - began) / 60)))
    survey = (run.get("route") or {}).get("survey")
    lines = [f"🗺 Mapping flight: “{name}”" if survey else f"📋 Patrol report: “{name}”", ended_how,
             f"⏱ {mins} min · {run.get('lap', 1)} lap{'s' if run.get('lap', 1) != 1 else ''} · {run.get('total', 0)} stops"]
    for slot, start in run.get("battery", {}).items():
        now_b = get_link(slot)["telemetry"].get("battery")
        last = run.get("battery_end", {}).get(slot, now_b)
        used = f" ({start - last}% used)" if isinstance(start, (int, float)) and isinstance(last, (int, float)) else ""
        lines.append(f"🚁 {drone_label(slot)}: {start if start is not None else '?'}% → {last if last is not None else '?'}%{used}")
    if run.get("handovers"):
        lines.append(f"🔁 {run['handovers']} handover{'s' if run['handovers'] > 1 else ''} between drones")
    seen = [k for t, dr, k, _ in drone_detections if began <= t <= end + 5 and dr in run.get("battery", {})]
    people, vehicles = seen.count("person"), seen.count("vehicle")
    lines.append(f"👁 Seen: {people} {'person' if people == 1 else 'people'}, {vehicles} vehicle{'s' if vehicles != 1 else ''}"
                 if seen else "👁 Nothing seen by the drone cameras")
    if survey:
        lines.append(f"📸 {run.get('frames', 0)} map images captured")
    text = "\n".join(lines)
    run["report"] = text
    if telegram_ready():
        send_telegram(text)
        photos = [b for b, _ in run.get("photos", [])]
        if photos:
            send_telegram_album(photos, f"Patrol “{name}”: " + ", ".join(w for _, w in run["photos"][:3]))
    return text


class PatrolEnded(Exception):
    """The patrol ended with the drone already on its way home (don't tell it to hover)."""


def _battery_low(slot, run):
    b = get_link(slot)["telemetry"].get("battery")
    return bool(run.get("swap_at")) and b is not None and b <= run["swap_at"]


def _fly_leg(slot, p, route, run):
    """Fly to stop p, round any no-fly zone on the way. '' on arrival, SWAP, or why it ended."""
    tel = get_link(slot)["telemetry"]
    via = nofly.detour(nofly_zones(), (tel["lat"], tel["lon"]), (p["lat"], p["lon"])) if tel.get("lat") else []
    if via is None:
        raise RuntimeError(f"no way round the no-fly zones to stop {run['index']}")
    for q in via + [(p["lat"], p["lon"])]:
        r = drone_command("goto", {"lat": q[0], "lon": q[1], "alt": route["alt"], "speed": route["speed"], "arrive": "hover",
                                   **_lost_link_args(route)}, timeout=15.0, slot=slot)
        if not r["ok"]:
            raise RuntimeError(r["error"] or "the drone refused the next stop")
        why = _wait_arrival({"lat": q[0], "lon": q[1]}, time.time(), run)
        if why:
            return why
    return ""


def _hand_over(name, route, old, stop, run):
    """Send the tired drone home and put the backup (or the next ready drone) on the route. Returns the new drone."""
    bat = get_link(old)["telemetry"].get("battery")
    _go_home_safe(old, f"battery {bat}%")
    _drone_event(f"Battery {bat}%: returning home from route {name}", old)
    backup, run["backup"] = run.get("backup"), None  # released, so it can take over
    nxt, problem = None, "no other drone"
    if backup:
        problem = _route_problem(route, backup)
        if problem:
            problem = f"backup {drone_label(backup)} not ready ({problem})"
        else:
            nxt = backup
    if not nxt and route["relay"]:
        # Same kind of drone takes over (real → real, virtual → virtual) unless demo mode mixes them.
        over = _sources_over_limit()
        candidates = [d for d in drone_slots() if d not in (old, backup) and d not in over
                      and (is_virtual(d) == is_virtual(old) or _virtual_cfg.get("demo_auto"))]
        nxt = next((d for d in candidates if not _route_problem(route, d)), None)
        if not nxt:
            problem = (problem + "; " if backup else "") + ("no other drone is ready" if candidates else "no other drone")
    if not nxt:
        send_telegram(f"🔋 {drone_label(old)} at {bat}% is returning home. Patrol “{name}” ended at stop {stop}: {problem}.") \
            if telegram_ready() else None
        raise PatrolEnded(f"battery {bat}%, {drone_label(old)} returning home; {problem}")
    # The tired drone becomes the backup, ready to take over again once its battery is swapped.
    run.update(drone=nxt, backup=old if backup else None, handovers=run.get("handovers", 0) + 1)
    run.setdefault("battery_end", {})[old] = bat
    run.setdefault("battery", {}).setdefault(nxt, get_link(nxt)["telemetry"].get("battery"))
    _drone_event(f"Taking over route {name} at stop {stop} from {drone_label(old)} ({bat}%)", nxt)
    send_telegram(f"🔁 {drone_label(old)} at {bat}% is returning home. {drone_label(nxt)} is taking off to continue patrol "
                  f"“{name}” from stop {stop}.") if telegram_ready() else None
    return nxt


def _run_route(name, route, by, slot, run):
    pts = route["points"]
    # "Ignore battery": the PC never sends the drone home or swaps it; only the drone's own low-battery protection acts.
    nobat = route.get("ignore_battery")
    run.update(swap_at=route["swap_at"] if not nobat and (route["loop"] or route["relay"] or run.get("backup")) else 0, lap=1, handovers=0,
               began=time.time(), battery={slot: get_link(slot)["telemetry"].get("battery")}, battery_end={}, photos=[])
    who = f" ({drone_label(slot)})" if len(drone_slots()) > 1 else ""
    kind = " · continuous patrol" if route["loop"] else ""
    kind += " · ignoring battery level" if nobat else ""
    kind += f" · relay at {route['swap_at']}%" if route["relay"] and not nobat else ""
    kind += f" · backup {drone_label(run['backup'])}" if run.get("backup") and not nobat else ""
    _drone_event(f"Route {name} started ({len(pts)} stops, {by}{kind})", slot)
    send_telegram(f"🗺️ Route “{name}”{who} started: {len(pts)} stops at {int(route['alt'])} m{kind}.") if telegram_ready() else None
    if route.get("survey"):  # 3D-map survey: camera straight down, grab images along the grid
        drone_command("gimbal", {"pitch": -90}, timeout=5.0, slot=slot)
        threading.Thread(target=_survey_capture_worker, args=(run,), daemon=True).start()
    i = 0
    try:
        while True:
            p = pts[i]
            if _battery_low(slot, run):
                slot = _hand_over(name, route, slot, i + 1, run)
            lap = f" · lap {run['lap']}" if route["loop"] else ""
            run.update(index=i + 1, phase="flying", message=f"{drone_label(slot)} flying to stop {i + 1} of {len(pts)}{lap}")
            why = _fly_leg(slot, p, route, run)
            if why == SWAP:
                slot = _hand_over(name, route, slot, i + 1, run)
                continue  # the new drone flies to the same stop
            if why:
                # The drone is already flying home or landing on its own: end the patrol without telling it to hover.
                raise (PatrolEnded if "took over" in why else RuntimeError)(why)
            run.update(phase="pause", message=f"{drone_label(slot)} at stop {i + 1} of {len(pts)}{lap}")
            if run["lap"] == 1 and i < 4:
                _patrol_photo(run, slot, f"stop {i + 1}")
            end = time.time() + route["pause"]
            while time.time() < end and not run["stop"]:
                time.sleep(0.5)
            if run["stop"]:
                raise RuntimeError("stopped from the PC")
            i += 1
            if i >= len(pts):
                if not route["loop"]:
                    break
                i = 0
                run["lap"] += 1
        if route["end"] == "home":
            _go_home_safe(slot, f"route {name} complete")
        elif route["end"] == "land":
            drone_command("land", timeout=10.0, slot=slot)
        done = {"home": "returning home", "land": "landing at the last stop", "hover": "hovering at the last stop"}[route["end"]]
        run.update(phase="done", message=f"Route {name} complete, {done}")
        _drone_event(f"Route {name} complete ({done})", slot)
        how = f"✅ Complete, {done}."
    except PatrolEnded as e:
        run.update(phase="done", message=f"Patrol {name} ended: {e}")
        _drone_event(f"Route {name} ended: {e}", slot)
        how = f"🔋 Ended: {e}."
    except Exception as e:
        drone_command("hover", timeout=5.0, slot=slot)
        run.update(phase="stopped", message=f"Route stopped at stop {run['index']}: {e}")
        _drone_event(f"Route {name} stopped: {e}", slot)
        how = f"⚠️ Stopped at stop {run['index']}: {e}. The drone is hovering." if "stopped from the PC" not in str(e) else \
            f"⏹ Stopped from the PC at stop {run['index']}; the drone is hovering."
    finally:
        run.update(active=False, swap_at=0, backup=None, ended_at=time.time())
    run.setdefault("battery_end", {})[slot] = get_link(slot)["telemetry"].get("battery")
    if route.get("survey"):
        try:
            _survey_flight_ended(run, how)
        except Exception as e:
            print("Mapping flight end error:", e)
    try:
        time.sleep(1.5)  # let the last photo arrive
        patrol_report(name, run, how)
    except Exception as e:
        print("Patrol report error:", e)


route_lock = threading.Lock()


def fly_route(name=None, route=None, by="dashboard", drone=None, backup=None):
    if route is None:
        route = load_routes().get(name or "")
        if not route:
            return {"ok": False, "error": f"No saved route named “{name}”."}
    route = _clean_route(route)
    with route_lock:
        if drone and run_of(drone):
            return {"ok": False, "error": f"{drone_label(drone)} is already flying route {run_of(drone)['name']}. Stop it first."}
        if backup:
            if backup not in drone_slots() or backup == drone:
                return {"ok": False, "error": "Choose a different drone as the backup."}
            taken = run_of(backup) or backup_run_of(backup)
            if taken:
                return {"ok": False, "error": f"{drone_label(backup)} is already busy with route {taken['name']}; choose another backup."}
        slot, problem = _pick_drone(lambda d: "chosen as the backup" if d == backup else _route_problem(route, d), drone)
        if problem:
            return {"ok": False, "error": problem}
        # Claimed under the lock (not in the thread) so a second request can't take the same drones meanwhile.
        run = {"active": True, "id": f"{slot}-{time.time():.3f}", "route": route,
               "drone": slot, "backup": backup, "name": name or "unsaved route", "index": 0,
               "total": len(route["points"]), "phase": "flying", "stop": False, "message": f"Route {name or 'unsaved route'} started"}
        route_runs[run["id"]] = run
        for k in [k for k, r in route_runs.items() if not r["active"] and time.time() - r.get("ended_at", time.time()) > 3600]:
            route_runs.pop(k, None)
    threading.Thread(target=_run_route, args=(name or "unsaved route", route, by, slot, run), daemon=True).start()
    who = f"{drone_label(slot)}: " if len(drone_slots()) > 1 else ""
    warnings = flight_conditions()[1]
    for w in warnings:
        _drone_event(f"⚠ {w}", slot)
    return {"ok": True, "drone": slot, "message": f"{who}Route started: {len(route['points'])} stops." + "".join(f" ⚠ {w}" for w in warnings)}


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
    slot = request.args.get("drone") or DRONE_CAMERA_NAME
    run = run_of(slot) or next((r for r in reversed(list(route_runs.values())) if r["drone"] == slot), None) or {}
    run = {k: v for k, v in run.items() if k != "photos"}
    b = backup_run_of(slot)
    return jsonify({"ok": True, "routes": load_routes(), "run": run, "max_distance_m": DRONE_LIMITS["max_distance_m"],
                    "backup_for": {"drone": b["drone"], "label": drone_label(b["drone"]), "name": b["name"],
                                   "id": b.get("id"), "route": b.get("route")} if b else None})


@app.route("/api/nofly", methods=["GET", "POST", "DELETE"])
def api_nofly():
    """No-fly zones shared by every drone. GET also gives a map centre for when no drone is connected."""
    zones = nofly_zones()
    every = nofly.load_zones(NOFLY_FILE)  # also imported airspace marked as authorised
    try:
        if request.method == "POST":
            z = nofly.clean_zone({k: v for k, v in (request.get_json(silent=True) or {}).items() if k != "source"})
            for slot in drone_slots():
                tel = get_link(slot)["telemetry"]
                if tel.get("home_lat") and nofly.zone_at([z], tel["home_lat"], tel["home_lon"]):
                    raise ValueError(f"{drone_label(slot)}'s home point is inside that zone. Draw it round the home point instead.")
            if any(x["id"] == z["id"] and x.get("source") for x in every):
                raise ValueError("Imported airspace is changed on the Flight Safety page.")
            every = [x for x in every if x["id"] != z["id"]] + [z]
            nofly.save_zones(NOFLY_FILE, every)
            return jsonify({"ok": True, "zone": z, "zones": nofly.active(every)})
        if request.method == "DELETE":
            zid = str((request.get_json(silent=True) or {}).get("id") or "")
            every = [x for x in every if x["id"] != zid]
            nofly.save_zones(NOFLY_FILE, every)
            return jsonify({"ok": True, "zones": nofly.active(every)})
    except (TypeError, ValueError, KeyError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    centre = None
    for slot in [request.args.get("drone") or DRONE_CAMERA_NAME] + drone_slots():
        tel = get_link(slot)["telemetry"]
        if tel.get("home_lat") or tel.get("lat"):
            centre = [tel.get("home_lat") or tel["lat"], tel.get("home_lon") or tel["lon"]]
            break
    locs = list(load_response_settings()["camera_locations"].values())
    if not centre and locs:
        centre = [locs[0]["lat"], locs[0]["lon"]]
    if not centre and zones:
        centre = [zones[0]["points"][0]["lat"], zones[0]["points"][0]["lon"]]
    return jsonify({"ok": True, "zones": zones, "centre": centre, "max_distance_m": DRONE_LIMITS["max_distance_m"],
                    "map_cache": map_cache_stats()})


@app.route("/api/routes/fly", methods=["POST"])
def api_routes_fly():
    data = request.get_json(silent=True) or {}
    try:
        drone = data.get("drone") or request.args.get("drone")
        backup = data.get("backup") if data.get("backup") in drone_slots() else None
        if data.get("ignore_battery"):
            backup = None  # nothing is swapped, so no drone is held back as backup
        r = fly_route(data.get("name"), data if data.get("points") else None, by="dashboard",
                      drone=drone if drone in drone_slots() else None, backup=backup)
    except (TypeError, ValueError, KeyError) as e:
        r = {"ok": False, "error": f"Invalid route: {e}"}
    return jsonify(r), (200 if r["ok"] else 409)


@app.route("/api/routes/stop", methods=["POST"])
def api_routes_stop():
    slot = request.args.get("drone") or DRONE_CAMERA_NAME
    run = run_of(slot)
    if run is None:
        return jsonify({"ok": False, "error": "This drone is not flying a route."}), 409
    run["stop"] = True
    drone_command("hover", timeout=5.0, slot=slot)
    return jsonify({"ok": True})


# ---------- drone 3D site maps (survey grid → images → OpenDroneMap → 3D model + orthophoto) ----------
MAPS_DIR = os.path.join(os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER), "maps")
MAP_BUSY = ("queued", "starting", "uploading", "processing", "downloading")
MAP_ENGINE_WAIT_S = 45 * 60  # the first start downloads the engine (several GB)
MAP_POLL_S = 10
_map_queue = queue.Queue()
_map_engine = {"at": 0.0, "ok": False, "error": "", "version": "", "starting": False}


def mapping_engine_url():
    url = str(load_local_settings().get("mapping_engine_url") or "").strip().rstrip("/")
    return url if re.match(r"^https?://[\w.\-]+(:\d+)?$", url) else mapping.DEFAULT_ENGINE_URL


def mapping_engine_status(fresh=False):
    if fresh or time.time() - _map_engine["at"] > 10:
        try:
            info = mapping.engine_info(mapping_engine_url())
            _map_engine.update(ok=True, error="", version=str(info.get("engineVersion") or info.get("version") or ""),
                               queue=info.get("taskQueueCount", 0))
        except mapping.EngineError as e:
            _map_engine.update(ok=False, error=str(e), version="")
        _map_engine["at"] = time.time()
    return {"ok": _map_engine["ok"], "error": _map_engine["error"], "version": _map_engine["version"],
            "starting": _map_engine["starting"], "url": mapping_engine_url(),
            "local": mapping_engine_url() == mapping.DEFAULT_ENGINE_URL}


def _compose_file():
    here = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    for p in (os.path.join(here, "runtime", "docker-compose.yml"), os.path.join(os.path.dirname(here), "runtime", "docker-compose.yml")):
        if os.path.exists(p):
            return p
    return None


def start_mapping_engine():
    """Start the local engine container (docker compose profile "mapping"). Returns (ok, message)."""
    compose = _compose_file()
    if not compose:
        return False, "The Docker setup (runtime\\docker-compose.yml) was not found."
    env = os.environ.copy()
    env["AI_SECURITY_DATA"] = (os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER)).replace("\\", "/")
    _map_engine["starting"] = True
    try:
        p = run_background_command(["docker", "compose", "-p", "ai-security", "-f", compose, "--profile", "mapping", "up", "-d", "nodeodm"],
                                   capture_output=True, text=True, timeout=MAP_ENGINE_WAIT_S, env=env)
        return p.returncode == 0, (p.stdout + p.stderr).strip()[-400:]
    except Exception as e:
        return False, str(e)
    finally:
        _map_engine.update(starting=False, at=0.0)


def _ensure_engine(sid):
    """Wait for the engine; start the local one if needed. Raises EngineError when it never comes up."""
    if mapping_engine_status(fresh=True)["ok"]:
        return
    if mapping_engine_url() != mapping.DEFAULT_ENGINE_URL:
        raise mapping.EngineError(f"The mapping engine at {mapping_engine_url()} is not reachable.")
    _map_step(sid, status="starting",
              message="Starting the mapping engine. The first time, Docker downloads it (several GB): this can take a while.")
    result = {}
    t = threading.Thread(target=lambda: result.update(r=start_mapping_engine()), daemon=True)
    t.start()
    end = time.time() + MAP_ENGINE_WAIT_S
    while time.time() < end:
        time.sleep(MAP_POLL_S)
        _map_step(sid)  # stops here if cancelled
        if mapping_engine_status(fresh=True)["ok"]:
            return
        if not t.is_alive() and not result.get("r", (True,))[0]:
            raise mapping.EngineError("Could not start the mapping engine: " + (result["r"][1] or "Docker failed."))
    raise mapping.EngineError("The mapping engine did not start in time. Check that Docker Desktop is running.")


class _MapFrames:
    """The drone's live video, decoded in the background; jpeg() gives the newest frame at full stream quality."""

    def __init__(self, slot):
        self.url, self.frame, self.at, self.stop = f"rtsp://127.0.0.1:8556/{slot}", None, 0.0, False
        self.slot = slot
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        cap = None
        while not self.stop:
            try:
                if cap is None:
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = DRONE_FFMPEG_CAPTURE_OPTIONS
                    cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                ok, frame = cap.read()
                if ok:
                    self.frame, self.at = frame, time.time()
                    continue
            except Exception as e:
                print("Map capture video error:", e)
            if cap is not None:
                cap.release()
                cap = None
            time.sleep(1.0)
        if cap is not None:
            cap.release()

    def jpeg(self):
        frame = self.frame
        if frame is not None and time.time() - self.at < 1.0:
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            if ok:
                return buf.tobytes()
        try:  # fallback: Frigate's latest drone frame (no boxes drawn on it)
            r = requests.get(f"{FRIGATE_API_URL}/api/{self.slot}/latest.jpg", params={"quality": 95}, timeout=2)
            if r.ok and r.content[:2] == b"\xff\xd8":
                return r.content
        except Exception:
            pass
        return None

    def close(self):
        self.stop = True


def _map_frame_source(slot):
    return _MapFrames(slot)


def _survey_capture_worker(run):
    """During a mapping flight: one image every `every_m` metres along the grid, tagged with the drone's position."""
    sid = run["route"]["survey"]
    try:
        s = mapping.load(MAPS_DIR, sid)
    except KeyError:
        return
    every, alt, photos = s["plan"]["every_m"], s["settings"]["alt"], s["settings"].get("photos")
    run["frames"], source, slot, last = s.get("frames", 0), None, None, None
    try:
        while run["active"] and not run["stop"]:
            time.sleep(0.2)
            if run["drone"] != slot:  # first start, or the backup drone took over
                if source:
                    source.close()
                slot, last = run["drone"], None
                source = _map_frame_source(slot)
            if run.get("index", 0) < 2 or run.get("phase") != "flying":
                continue  # still on the way to the first grid line
            link = get_link(slot)
            tel = link["telemetry"]
            if time.time() - link["tel_at"] > 2 or not tel.get("lat") or float(tel.get("altitude") or 0) < alt - 4:
                continue
            if tel.get("gimbal_pitch") is not None and float(tel["gimbal_pitch"]) > -75:
                continue  # camera not pointing down (yet)
            pos = (float(tel["lat"]), float(tel["lon"]))
            if last and _distance_m(last[0], last[1], pos[0], pos[1]) < every:
                continue
            jpeg = source.jpeg()
            if not jpeg:
                continue
            run["frames"] = mapping.add_frame(MAPS_DIR, sid, jpeg, pos[0], pos[1], float(tel.get("altitude") or alt))
            last = pos
            if photos:  # full-resolution photo on the drone's SD card too, to import after landing
                threading.Thread(target=drone_command, args=("photo",), kwargs={"timeout": 5.0, "slot": slot}, daemon=True).start()
    finally:
        if source:
            source.close()


def _survey_flight_ended(run, how):
    sid = run["route"]["survey"]
    s = mapping.load(MAPS_DIR, sid)
    frames = s.get("frames", 0)
    flights = (s.get("flights") or []) + [{"at": time.time(), "drone": run["drone"], "frames": run.get("frames", frames),
                                            "ended": re.sub(r"^\W+", "", how)[:200]}]
    images = frames + s.get("photos", 0)
    if images >= 5:
        msg = f"{images} images ready. Process them into a 3D map, or fly again to add more."
    elif is_virtual(run["drone"]):
        msg = "Virtual drones have no camera: the flight was a rehearsal and captured no images."
    else:
        msg = f"Only {images} images were captured. Check the drone's video reached this PC, then fly again or import photos."
    mapping.update(MAPS_DIR, sid, status="captured" if images >= 5 else "planned", message=msg, flights=flights[-20:])


class _MapCanceled(Exception):
    pass


def _map_step(sid, **fields):
    """Save progress, unless the map was cancelled (or deleted) meanwhile: then stop the job."""
    with mapping._lock:
        if mapping.load(MAPS_DIR, sid).get("status") == "canceled":
            raise _MapCanceled()
        return mapping.update(MAPS_DIR, sid, **fields)


def _process_map(sid):
    s = mapping.load(MAPS_DIR, sid)
    if s.get("status") not in MAP_BUSY:
        return  # cancelled while it waited in the queue
    base = mapping_engine_url()
    task = s.get("task")
    try:
        _ensure_engine(sid)
        if not (task and s.get("status") in ("processing", "downloading")):
            if task:
                mapping.remove_task(base, task)  # an upload cut short by a restart
                task = None
            files, geo = mapping.image_files(MAPS_DIR, sid)
            _map_step(sid, status="uploading", progress=0, task=None, message=f"Sending {len(files)} images to the mapping engine…")
            task = mapping.submit(base, s["name"], files, geo, s["settings"].get("quality", "balanced"),
                                  progress=lambda a, b: _map_step(sid, message=f"Sending images to the mapping engine: {a} of {b}"))
            _map_step(sid, status="processing", task=task, progress=0, message="Processing started.")
        while True:
            info = mapping.task_info(base, task)
            if info["state"] == "completed":
                break
            if info["state"] in ("failed", "canceled"):
                _map_step(sid)  # cancelled from here: stop quietly
                raise mapping.EngineError(info["error"] or f"Processing {info['state']}.")
            mins = info["seconds"] // 60
            _map_step(sid, progress=round(info["progress"], 1),
                      message=f"Building the 3D map: {int(info['progress'])}% ({mins} min so far)" if info["state"] == "running"
                      else "Waiting for the mapping engine (another map is being processed).")
            time.sleep(MAP_POLL_S)
        _map_step(sid, status="downloading", progress=100, message="Downloading the results…")
        folder = mapping.survey_dir(MAPS_DIR, sid)
        archive = os.path.join(folder, "results.zip")
        mapping.download(base, task, archive)
        found = mapping.extract_results(archive, os.path.join(folder, "result"))
        os.remove(archive)
        if not found["model"] and not found["tiles"]:
            raise mapping.EngineError("The engine finished but made no 3D model or map. Try more images with more overlap.")
        mapping.remove_task(base, task)
        s = mapping.update(MAPS_DIR, sid, status="ready", result=found, task=None, processed_at=time.time(),
                           message="3D map ready." + ("" if found["model"] else " (No 3D model: map view only.)"))
        if telegram_ready():
            send_telegram(f"🗺 3D map “{s['name']}” is ready. Open 3D Maps on the dashboard to see it.")
    except _MapCanceled:
        if task:
            mapping.cancel(base, task)
            mapping.remove_task(base, task)
        mapping.update(MAPS_DIR, sid, task=None)
    except (mapping.EngineError, OSError, ValueError, mapping.zipfile.BadZipFile) as e:
        try:
            _map_step(sid, status="failed", message=f"Processing failed: {e}")
        except _MapCanceled:
            pass
    except KeyError:
        pass  # the map was deleted meanwhile


def _map_worker():
    while True:
        sid = _map_queue.get()
        try:
            _process_map(sid)
        except Exception as e:
            print("3D map processing error:", e)


def start_mapping():
    """Background processing, and maps that were processing when the PC was restarted carry on."""
    threading.Thread(target=_map_worker, daemon=True).start()
    for s in mapping.list_all(MAPS_DIR):
        if s.get("status") in MAP_BUSY:
            _map_queue.put(s["id"])
        elif s.get("status") == "flying":
            mapping.update(MAPS_DIR, s["id"], status="captured" if s.get("frames", 0) + s.get("photos", 0) >= 5 else "planned",
                           message="The flight was interrupted by a restart. Fly again to add more images.")


def _survey_run(sid):
    return next((r for r in list(route_runs.values()) if r["active"] and r["route"].get("survey") == sid), None)


def _map_public(s):
    run = _survey_run(s["id"])
    out = {k: s.get(k) for k in ("id", "name", "created_at", "area", "settings", "status", "message", "frames", "photos",
                                  "progress", "result", "flights", "processed_at")}
    out["plan"] = {k: v for k, v in s["plan"].items() if k != "points"}
    out["points"] = s["plan"]["points"]
    out["bounds"] = mapping.bounds(s["area"])
    if run:
        out.update(status="flying", message=run.get("message", ""), frames=run.get("frames", s.get("frames", 0)), drone=run["drone"])
    return out


def _map_or_404(sid):
    try:
        return mapping.load(MAPS_DIR, sid), None
    except KeyError:
        return None, (jsonify({"ok": False, "error": "No such map."}), 404)


def _map_settings(data):
    return {k: data[k] for k in ("alt", "overlap", "sidelap", "speed", "photos") if k in data}


@app.route("/api/maps", methods=["GET", "POST"])
def api_maps():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        try:
            alt = float(data.get("alt") or 40)
            if not 15 <= alt <= DRONE_LIMITS["max_altitude_m"]:
                raise ValueError(f"Fly between 15 and {DRONE_LIMITS['max_altitude_m']} m.")
            s = mapping.create(MAPS_DIR, data.get("name"), data.get("area"), quality=data.get("quality") or "balanced",
                               **{**_map_settings(data), "alt": alt})
        except (TypeError, ValueError, KeyError) as e:
            return jsonify({"ok": False, "error": str(e) or "Invalid map settings."}), 400
        return jsonify({"ok": True, "map": _map_public(s)})
    return jsonify({"ok": True, "maps": [_map_public(s) for s in mapping.list_all(MAPS_DIR)],
                    "engine": mapping_engine_status(), "allowed": drone_control_allowed(),
                    "drones": [{"slot": d, "label": drone_label(d), "virtual": is_virtual(d)} for d in drone_slots()]})


@app.route("/api/maps/plan", methods=["POST"])
def api_maps_plan():
    """Preview the grid for an area before saving it."""
    data = request.get_json(silent=True) or {}
    try:
        plan = mapping.plan_grid(data.get("area"), **{**{"alt": 40}, **_map_settings(data)})
    except (TypeError, ValueError, KeyError) as e:
        return jsonify({"ok": False, "error": str(e) or "Invalid area."}), 400
    problem = nofly.route_problem(nofly_zones(), plan["points"], False)
    return jsonify({"ok": True, "plan": plan, "warning": problem or (
        f"About {plan['minutes']} minutes of flying: more than one battery. The flight swaps to the backup drone, "
        "or fly the rest after a battery swap." if plan["minutes"] > 18 else "")})


@app.route("/api/maps/<sid>", methods=["GET", "DELETE"])
def api_map(sid):
    s, err = _map_or_404(sid)
    if err:
        return err
    if request.method == "DELETE":
        if _survey_run(sid):
            return jsonify({"ok": False, "error": "The drone is flying this map. Stop the flight first."}), 409
        if s.get("task"):
            mapping.cancel(mapping_engine_url(), s["task"])
            mapping.remove_task(mapping_engine_url(), s["task"])
        mapping.delete(MAPS_DIR, sid)
        return jsonify({"ok": True})
    return jsonify({"ok": True, "map": _map_public(s)})


@app.route("/api/maps/<sid>/fly", methods=["POST"])
def api_map_fly(sid):
    s, err = _map_or_404(sid)
    if err:
        return err
    if s.get("status") in MAP_BUSY:
        return jsonify({"ok": False, "error": "This map is being processed."}), 409
    data = request.get_json(silent=True) or {}
    drone = data.get("drone") if data.get("drone") in drone_slots() else None
    backup = data.get("backup") if data.get("backup") in drone_slots() and data.get("backup") != drone else None
    route = {"survey": sid, "points": s["plan"]["points"], "alt": s["settings"]["alt"], "speed": s["settings"]["speed"],
             "pause": 0, "end": "home", "lost_link": "home", "relay": bool(backup), "swap_at": 25}
    r = fly_route(f"Map: {s['name']}", route, by="3D Maps", drone=drone, backup=backup)
    if r["ok"]:
        mapping.update(MAPS_DIR, sid, status="flying", message="Flying the mapping grid…")
    return jsonify(r), (200 if r["ok"] else 409)


@app.route("/api/maps/<sid>/stop", methods=["POST"])
def api_map_stop(sid):
    run = _survey_run(sid)
    if run is None:
        return jsonify({"ok": False, "error": "This map is not being flown."}), 409
    run["stop"] = True
    drone_command("hover", timeout=5.0, slot=run["drone"])
    return jsonify({"ok": True})


@app.route("/api/maps/<sid>/photos", methods=["POST"])
def api_map_photos(sid):
    """Photos copied from the drone's SD card (full resolution, GPS in each photo)."""
    s, err = _map_or_404(sid)
    if err:
        return err
    if s.get("status") in MAP_BUSY:
        return jsonify({"ok": False, "error": "This map is being processed."}), 409
    added, problems = 0, []
    for f in request.files.getlist("photos"):
        try:
            mapping.add_photo(MAPS_DIR, sid, f.filename, f.read())
            added += 1
        except ValueError as e:
            problems.append(str(e))
    s = mapping.load(MAPS_DIR, sid)
    if added and s["status"] in ("planned", "failed", "canceled", "ready", "captured"):
        images = s.get("frames", 0) + s.get("photos", 0)
        mapping.update(MAPS_DIR, sid, status="captured" if images >= 5 else "planned",
                       message=f"{images} images ready. Process them into a 3D map." if images >= 5 else f"{images} images so far (5 needed).")
    return jsonify({"ok": added > 0 or not problems, "added": added, "photos": s.get("photos", 0), "errors": problems[:5]})


@app.route("/api/maps/<sid>/process", methods=["POST"])
def api_map_process(sid):
    s, err = _map_or_404(sid)
    if err:
        return err
    if s.get("status") in MAP_BUSY or _survey_run(sid):
        return jsonify({"ok": False, "error": "This map is already flying or processing."}), 409
    files, _ = mapping.image_files(MAPS_DIR, sid)
    if len(files) < 5:
        return jsonify({"ok": False, "error": f"A 3D map needs at least 5 images; this one has {len(files)}."}), 409
    mapping.update(MAPS_DIR, sid, status="queued", progress=0, task=None, message="Waiting to be processed…")
    _map_queue.put(sid)
    return jsonify({"ok": True})


@app.route("/api/maps/<sid>/cancel", methods=["POST"])
def api_map_cancel(sid):
    s, err = _map_or_404(sid)
    if err:
        return err
    if s.get("status") not in MAP_BUSY:
        return jsonify({"ok": False, "error": "This map is not being processed."}), 409
    mapping.update(MAPS_DIR, sid, status="canceled", message="Processing cancelled.")
    if s.get("task"):
        mapping.cancel(mapping_engine_url(), s["task"])
    return jsonify({"ok": True})


@app.route("/api/maps/engine", methods=["GET", "POST"])
def api_map_engine():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if "url" in data:
            url = str(data.get("url") or "").strip().rstrip("/")
            if url and not re.match(r"^https?://[\w.\-]+(:\d+)?$", url):
                return jsonify({"ok": False, "error": "Enter the engine address like http://192.168.1.20:3000"}), 400
            save_local_settings({"mapping_engine_url": url})
        if data.get("start"):
            if mapping_engine_url() != mapping.DEFAULT_ENGINE_URL:
                return jsonify({"ok": False, "error": "The engine is on another computer: start it there."}), 409
            if not _map_engine["starting"]:
                threading.Thread(target=start_mapping_engine, daemon=True).start()
    return jsonify({"ok": True, "engine": mapping_engine_status(fresh=True)})


def _map_result_dir(sid, *sub):
    return os.path.join(mapping.survey_dir(MAPS_DIR, sid), "result", *sub)


@app.route("/maps/<sid>/model/<path:filename>")
def map_model_file(sid, filename):
    try:
        return send_from_directory(_map_result_dir(sid, "model"), filename, max_age=3600)
    except KeyError:
        return Response(status=404)


@app.route("/maps/<sid>/tiles/<int:z>/<int:x>/<int:y>.png")
def map_ortho_tile(sid, z, x, y):
    # gdal2tiles numbers rows from the south (TMS); the page's Leaflet layer is set to match.
    try:
        folder = _map_result_dir(sid, "tiles", str(z), str(x))
    except KeyError:
        return Response(status=404)
    if not os.path.exists(os.path.join(folder, f"{y}.png")):
        return Response(status=404)
    return send_from_directory(folder, f"{y}.png", mimetype="image/png", max_age=86400)


@app.route("/maps/<sid>/report.pdf")
def map_report(sid):
    try:
        return send_from_directory(_map_result_dir(sid), "report.pdf", mimetype="application/pdf")
    except KeyError:
        return Response(status=404)


@app.route("/vendor/three/<path:filename>")
def vendor_three(filename):
    mime = "text/javascript" if filename.endswith(".js") else None
    return send_from_directory(os.path.join(VENDOR_DIR, "three"), filename, mimetype=mime, max_age=7 * 86400)


@app.route("/maps")
def maps_page():
    return Response(MAPS_PAGE, mimetype="text/html")


@app.route("/maps/<sid>/3d")
def map_viewer_page(sid):
    s, err = _map_or_404(sid)
    if err or not (s.get("result") or {}).get("model"):
        return Response(hud_page("3D map", '<main class="hud-main"><h1 class="page-title">No 3D model yet</h1>'
                                           '<a class="hud-btn" href="/maps">Back to 3D Maps</a></main>', active="maps"),
                        status=404, mimetype="text/html")
    page = MAP_VIEWER_PAGE.replace("__MAP_ID__", sid).replace("__MODEL__", urllib.parse.quote(s["result"]["model"]))
    return Response(page.replace("__MAP_NAME__", html_escape(s["name"])), mimetype="text/html")


MAPS_PAGE = hud_page("3D Maps", pages.maps.BODY, active="maps")
MAP_VIEWER_PAGE = hud_page("3D map", pages.maps.VIEWER, active="maps", head=pages.maps.VIEWER_HEAD)


# ---------- flight safety: weather, crewed aircraft, official airspace, radio coverage, shortest routes ----------
SAFETY_DATA = os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER)
SAFETY_FILE = os.path.join(SAFETY_DATA, "flight_safety.json")
AIRPORTS_FILE = os.path.join(SAFETY_DATA, "airports.csv")  # OurAirports, kept for offline re-imports
AIRPORTS_REFRESH_DAYS = 90
TRAFFIC_STALE_S = 60


def load_safety():
    try:
        with open(SAFETY_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = {}
    site = raw.get("site")
    return {"site": {"lat": float(site["lat"]), "lon": float(site["lon"])} if isinstance(site, dict) and "lat" in site else None,
            "weather": weather.clean_settings(raw.get("weather")), "traffic": airtraffic.clean_settings(raw.get("traffic")),
            "rf": rf.clean_settings(raw.get("rf")),
            "airports": {"within_km": max(5.0, min(100.0, float((raw.get("airports") or {}).get("within_km") or 30))),
                         "radius_m": {k: float(v) for k, v in ((raw.get("airports") or {}).get("radius_m") or {}).items()
                                      if k in airspace.RADIUS_M and 200 <= float(v) <= 20000}}}


def save_safety(update):
    s = load_safety()
    for k in ("weather", "traffic", "rf", "airports"):
        if isinstance(update.get(k), dict):
            s[k] = {**s[k], **update[k]}
    if "site" in update:
        site = update["site"]
        s["site"] = {"lat": float(site["lat"]), "lon": float(site["lon"])} if site else None
    s = {**s, "weather": weather.clean_settings(s["weather"]), "traffic": airtraffic.clean_settings(s["traffic"]),
         "rf": rf.clean_settings(s["rf"])}
    tmp = SAFETY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, SAFETY_FILE)
    return load_safety()


def _site_location():
    """Where the drones fly: a drone's home point, else the site position set on Flight Safety, else a camera."""
    for slot in drone_slots():
        tel = get_link(slot)["telemetry"]
        if link_fresh(slot, 10) and (tel.get("home_lat") or tel.get("lat")):
            return (tel.get("home_lat") or tel["lat"], tel.get("home_lon") or tel["lon"]), drone_label(slot)
    site = load_safety()["site"]
    if site:
        return (site["lat"], site["lon"]), "site position"
    locs = list(load_response_settings()["camera_locations"].values())
    if locs:
        return (locs[0]["lat"], locs[0]["lon"]), "camera location"
    return None, ""


def _weather_fetch(lat, lon):
    return weather.fetch(lat, lon)


weather_cache = weather.Cache(lambda lat, lon: _weather_fetch(lat, lon))


def _elevation_fetch(cells):
    return rf.Elevation._fetch(cells)


elevation = rf.Elevation(os.path.join(SAFETY_DATA, "elevation_cache.json"), fetcher=lambda cells: _elevation_fetch(cells))
_site_elev = {}


def site_elevation_m(loc):
    """Ground height at the site (m above sea), for aircraft heights; 0 while unknown (retried every 10 minutes)."""
    key = (round(loc[0], 3), round(loc[1], 3))
    hit = _site_elev.get(key)
    if hit and (hit[0] is not None or time.time() - hit[1] < 600):
        return hit[0] or 0.0
    hs = elevation.heights([loc])
    _site_elev[key] = (hs[0] if hs else None, time.time())
    return hs[0] if hs else 0.0


def weather_status(loc=None):
    s = load_safety()["weather"]
    loc = loc or _site_location()[0]
    if not s["enabled"]:
        return {"enabled": False, "reading": None, "issues": [], "error": ""}
    if not loc:
        return {"enabled": True, "reading": None, "issues": [], "error": "No site position yet: connect a drone or set the site on Flight Safety."}
    reading, err, at = weather_cache.get(loc[0], loc[1])
    return {"enabled": True, "reading": reading, "at": at, "error": err, "mode": s["mode"],
            "issues": weather.assess(reading, s) if reading else []}


traffic_state = {"ok": False, "error": "Not checked yet.", "aircraft": [], "threats": [], "at": 0.0, "centre": None, "actions": []}
_traffic_alerted = {}


def _traffic_fetch(settings, lat, lon):
    return airtraffic.fetch(settings, lat, lon)


def flight_conditions(loc=None):
    """(problem that blocks automatic flights or '' , warnings) from the weather and air traffic."""
    s = load_safety()
    problems, warnings = [], []
    w = weather_status(loc)
    if w["enabled"]:
        if w["reading"] and w["issues"]:
            (problems if s["weather"]["mode"] == "block" else warnings).append("Weather: " + ", ".join(w["issues"]) + ".")
        elif not w["reading"] and s["weather"]["unknown"] == "block":
            problems.append("The weather is unknown (no internet?) and Flight Safety requires a forecast to fly.")
    t = s["traffic"]
    if t["enabled"]:
        fresh = traffic_state["ok"] and time.time() - traffic_state["at"] < TRAFFIC_STALE_S
        if fresh and traffic_state["threats"]:
            text = "Crewed aircraft nearby: " + airtraffic.describe(traffic_state["threats"][0]) + ". Wait until it has passed."
            (problems if t["block_takeoff"] else warnings).append(text)
        elif not fresh and t["unknown"] == "block":
            problems.append("Air traffic is unknown (no ADS-B data) and Flight Safety requires it to fly.")
    return " ".join(problems), warnings


def _traffic_respond(threats, settings):
    """A crewed aircraft is close and low: tell everyone and get the flying drones out of its way."""
    flying = [d for d in drone_slots() if link_fresh(d, 5) and get_link(d)["telemetry"].get("flying")]
    new = [a for a in threats if time.time() - _traffic_alerted.get(a["hex"] or a["call"], 0) > 600]
    if not flying or not new:
        return
    for a in new:
        _traffic_alerted[a["hex"] or a["call"]] = time.time()
    act = settings["action"]
    what = {"warn": "", "descend": "Drones are descending to 15 m and hovering.", "land": "Drones are landing.",
            "home": "Drones are returning home."}[act]
    for slot in flying:
        _drone_event(f"✈ Crewed aircraft nearby: {airtraffic.describe(new[0])}", slot)
        if act == "warn":
            continue
        run = run_of(slot)
        if run:
            run["stop"] = True
            wait_until_s = time.time() + 5
            while run["active"] and time.time() < wait_until_s:
                time.sleep(0.2)
        if drone_response["active"] and drone_response.get("drone") == slot:
            drone_response.update(active=False, phase="", routing=False, message="Stopped: crewed aircraft nearby")
        tel = get_link(slot)["telemetry"]
        if act == "descend" and tel.get("lat"):
            drone_command("goto", {"lat": tel["lat"], "lon": tel["lon"], "alt": 15, "speed": 3, "arrive": "hover"}, timeout=8.0, slot=slot)
        elif act == "land":
            drone_command("land", timeout=8.0, slot=slot)
        elif act == "home":
            _go_home_safe(slot, "crewed aircraft nearby")
    traffic_state["actions"] = (traffic_state["actions"] + [{"at": time.time(), "text": airtraffic.describe(new[0]), "action": act}])[-10:]
    if telegram_ready():
        send_telegram(f"✈ Crewed aircraft near the site: {airtraffic.describe(new[0])}. {what}".strip())


def traffic_check_once():
    s = load_safety()["traffic"]
    if not s["enabled"]:
        traffic_state.update(ok=False, error="Air traffic watch is off.", aircraft=[], threats=[], at=time.time())
        return
    loc = _site_location()[0]
    if not loc:
        traffic_state.update(ok=False, error="No site position yet.", aircraft=[], threats=[], at=time.time())
        return
    try:
        data = _traffic_fetch(s, loc[0], loc[1])
        if data is None:
            raise ValueError("no source")
        ac = airtraffic.parse(data, loc[0], loc[1], site_elevation_m(loc), s["watch_km"])
        traffic_state.update(ok=True, error="", aircraft=ac[:60], threats=airtraffic.threats(ac, s), at=time.time(), centre=loc)
    except Exception as e:
        src = "the ADS-B receiver" if s["source"] == "local" else "airplanes.live (no internet?)"
        traffic_state.update(ok=False, error=f"No air traffic data from {src}: {e.__class__.__name__}.", aircraft=[], threats=[],
                             at=time.time(), centre=loc)
        return
    if traffic_state["threats"]:
        _traffic_respond(traffic_state["threats"], s)


def _traffic_worker():
    while True:
        try:
            traffic_check_once()
        except Exception as e:
            print("Air traffic error:", e)
        time.sleep(5 if load_safety()["traffic"]["source"] == "local" else 10)


def _airports_fetch():
    """OurAirports' airports.csv on disk: downloaded when missing or older than 90 days, else the saved copy."""
    fresh = os.path.exists(AIRPORTS_FILE) and time.time() - os.path.getmtime(AIRPORTS_FILE) < AIRPORTS_REFRESH_DAYS * 86400
    if not fresh:
        try:
            with requests.get(airspace.OURAIRPORTS_URL, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(AIRPORTS_FILE + ".part", "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            os.replace(AIRPORTS_FILE + ".part", AIRPORTS_FILE)
        except Exception:
            if not os.path.exists(AIRPORTS_FILE):
                raise ValueError("Could not download the airport list (no internet?). Import airports.csv from "
                                 "ourairports.com with “Import a file” instead.")
    return AIRPORTS_FILE


def _merge_zones(new, source):
    """Replace the imported zones of this source, keeping the authorised (switched off) setting of ones that stay."""
    zones = nofly.load_zones(NOFLY_FILE)
    old = {z["id"]: z for z in zones if z.get("source") == source}
    keep = [z for z in zones if z.get("source") != source]
    for z in new:
        if z["id"] in old:
            z["enabled"] = old[z["id"]].get("enabled", True)
    zones = keep + [nofly.clean_zone(z) for z in new]
    nofly.save_zones(NOFLY_FILE, zones)
    loc = _site_location()[0]
    inside = [z["name"] for z in new if z.get("enabled", True) and loc and nofly.zone_at([z], loc[0], loc[1])]
    return zones, inside


def _import_note(n, inside, kind):
    msg = f"{n} {kind} zone{'s' if n != 1 else ''} imported."
    if inside:
        msg += f" The site is inside {', '.join(inside[:3])}: flights there are refused until you mark it authorised (only with permission)."
    return msg


@app.route("/api/safety", methods=["GET"])
def api_safety():
    loc, where = _site_location()
    problem, warnings = flight_conditions(loc)
    t = dict(traffic_state)
    t["fresh"] = t["ok"] and time.time() - t["at"] < TRAFFIC_STALE_S
    return jsonify({"ok": True, "settings": load_safety(), "site": {"pos": loc, "from": where}, "weather": weather_status(loc),
                    "traffic": t, "zones": nofly.load_zones(NOFLY_FILE), "conditions": {"problem": problem, "warnings": warnings},
                    "max_distance_m": DRONE_LIMITS["max_distance_m"], "airports_cached": os.path.exists(AIRPORTS_FILE)})


@app.route("/api/safety/settings", methods=["POST"])
def api_safety_settings():
    try:
        s = save_safety(request.get_json(silent=True) or {})
    except (TypeError, ValueError, KeyError) as e:
        return jsonify({"ok": False, "error": str(e) or "Invalid settings."}), 400
    weather_cache.items.clear()
    return jsonify({"ok": True, "settings": s})


@app.route("/api/airspace/airports", methods=["POST"])
def api_airspace_airports():
    """Airports and heliports round the site as no-fly circles (OurAirports)."""
    data = request.get_json(silent=True) or {}
    loc = _site_location()[0]
    if not loc:
        return jsonify({"ok": False, "error": "Set the site position first (or connect a drone)."}), 409
    s = load_safety()["airports"]
    within = max(5.0, min(100.0, float(data.get("within_km") or s["within_km"])))
    try:
        with open(_airports_fetch(), "r", encoding="utf-8-sig", errors="replace") as f:
            found = airspace.airports_near(f, loc[0], loc[1], within)
    except (OSError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    zones, inside = _merge_zones(airspace.airport_zones(found, s["radius_m"]), "airport")
    save_safety({"airports": {"within_km": within}})
    return jsonify({"ok": True, "message": _import_note(len(found), inside, "airport") if found else
                    f"No airports or heliports within {within:g} km.", "zones": zones})


@app.route("/api/airspace/upload", methods=["POST"])
def api_airspace_upload():
    """An airspace GeoJSON (openAIP, the aviation authority) or OurAirports' airports.csv, for sites without internet."""
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "Choose a file."}), 400
    raw = f.read(60 * 1024 * 1024)
    loc = _site_location()[0]
    try:
        if f.filename.lower().endswith(".csv"):
            if not loc:
                raise ValueError("Set the site position first (or connect a drone).")
            with open(AIRPORTS_FILE + ".tmp", "wb") as out:
                out.write(raw)
            os.replace(AIRPORTS_FILE + ".tmp", AIRPORTS_FILE)
            s = load_safety()["airports"]
            found = airspace.airports_near(airspace.text_lines(raw), loc[0], loc[1], s["within_km"])
            zones, inside = _merge_zones(airspace.airport_zones(found, s["radius_m"]), "airport")
            return jsonify({"ok": True, "message": _import_note(len(found), inside, "airport"), "zones": zones})
        new, skipped = airspace.geojson_zones(json.loads(raw.decode("utf-8-sig")), loc)
        zones, inside = _merge_zones(new, "airspace")
        note = _import_note(len(new), inside, "airspace") + (f" {skipped} skipped (they start above 500 ft)." if skipped else "")
        return jsonify({"ok": True, "message": note, "zones": zones})
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"ok": False, "error": f"Could not read that file: {e}"}), 400


@app.route("/api/airspace/zone", methods=["POST", "DELETE"])
def api_airspace_zone():
    data = request.get_json(silent=True) or {}
    zones = nofly.load_zones(NOFLY_FILE)
    if request.method == "DELETE":
        source = data.get("source")
        if source not in ("airport", "airspace"):
            return jsonify({"ok": False, "error": "Unknown kind of zone."}), 400
        zones = [z for z in zones if z.get("source") != source]
    else:
        z = next((z for z in zones if z["id"] == data.get("id")), None)
        if not z or not z.get("source"):
            return jsonify({"ok": False, "error": "Only imported airspace can be switched off."}), 404
        z["enabled"] = bool(data.get("enabled"))
    nofly.save_zones(NOFLY_FILE, zones)
    return jsonify({"ok": True, "zones": zones})


@app.route("/api/routes/optimize", methods=["POST"])
def api_routes_optimize():
    """The route's stops in the order that flies the shortest distance (round the no-fly zones)."""
    data = request.get_json(silent=True) or {}
    try:
        stops = _clean_route({"points": data.get("points")})["points"]
    except (TypeError, ValueError, KeyError):
        return jsonify({"ok": False, "error": "Invalid stops."}), 400
    if len(stops) < 3:
        return jsonify({"ok": False, "error": "Add at least 3 stops to reorder."}), 400
    slot = data.get("drone") if data.get("drone") in drone_slots() else None
    tel = get_link(slot)["telemetry"] if slot else {}
    start = (tel.get("home_lat") or tel.get("lat"), tel.get("home_lon") or tel.get("lon"))
    start = start if None not in start else None
    order, before, after = nofly.best_order(nofly_zones(), stops, start, bool(data.get("loop")))
    if after == math.inf:
        return jsonify({"ok": False, "error": "Some stops can't be reached round the no-fly zones."}), 409
    return jsonify({"ok": True, "points": [stops[i] for i in order], "order": order, "before_m": round(before),
                    "after_m": round(after), "from_home": bool(start)})


def _rf_controller(s):
    c = s["rf"]["controller"]
    if c:
        return c
    loc = _site_location()[0]
    return {"lat": loc[0], "lon": loc[1]} if loc else None


@app.route("/api/rf/check", methods=["POST"])
def api_rf_check():
    """Expected controller signal at each route stop (and halfway along each leg)."""
    data = request.get_json(silent=True) or {}
    s = load_safety()
    c = _rf_controller(s)
    if not c:
        return jsonify({"ok": False, "error": "Set the controller position on Flight Safety, or connect a drone."}), 409
    try:
        stops = [(float(p["lat"]), float(p["lon"])) for p in data.get("points") or []][:mapping.MAX_POINTS]
        alt = max(5.0, min(float(DRONE_LIMITS["max_altitude_m"]), float(data.get("alt") or 30)))
    except (TypeError, ValueError, KeyError):
        return jsonify({"ok": False, "error": "Invalid stops."}), 400
    if not stops:
        return jsonify({"ok": False, "error": "Add stops first."}), 400
    targets = []
    for a, b in zip([None] + stops, stops):
        if a:
            targets.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
        targets.append(b)
    results, terrain = rf.check({**s["rf"], "controller": c}, elevation, targets, alt)
    worst = min(results, key=lambda r: r["margin_db"])
    return jsonify({"ok": True, "results": results, "terrain": terrain, "controller": c, "worst": worst,
                    "summary": ("Good signal everywhere on the route." if worst["quality"] == "good" else
                                f"{'Weak' if worst['quality'] == 'weak' else 'Poor'} signal expected {worst['dist_m']} m out "
                                f"({worst['margin_db']:+.0f} dB margin{', hills in the way' if not worst['line_of_sight'] else ''})."
                                ) + ("" if terrain else " Terrain unknown (offline): open ground assumed.")})


@app.route("/api/rf/coverage")
def api_rf_coverage():
    s = load_safety()
    c = _rf_controller(s)
    if not c:
        return jsonify({"ok": False, "error": "Set the controller position first, or connect a drone."}), 409
    alt = max(5.0, min(float(DRONE_LIMITS["max_altitude_m"]), float(request.args.get("alt") or 30)))
    pts = rf.grid((c["lat"], c["lon"]), DRONE_LIMITS["max_distance_m"])
    results, terrain = rf.check({**s["rf"], "controller": c}, elevation, pts, alt)
    step = 2 * DRONE_LIMITS["max_distance_m"] / 12
    return jsonify({"ok": True, "results": results, "terrain": terrain, "controller": c, "cell_m": step, "alt": alt})


# ---------- 4D live: every drone in 3D over the site, in real time (Drone page → map → 4D LIVE) ----------
TRAIL_SECONDS = 900  # the trail shows the last 15 minutes of flying
TRAIL_STEP_M = 2.0
drone_trails = {}  # slot -> [(lat, lon, alt, time)]


def record_trails(now=None):
    """Add each flying drone's position to its trail (called once a second)."""
    now = now or time.time()
    for slot in drone_slots():
        tel = get_link(slot)["telemetry"]
        trail = drone_trails.setdefault(slot, [])
        while trail and now - trail[0][3] > TRAIL_SECONDS:
            trail.pop(0)
        if not link_fresh(slot, 3) or not tel.get("lat") or not (tel.get("flying") or float(tel.get("altitude") or 0) > 0.5):
            continue
        p = (float(tel["lat"]), float(tel["lon"]), float(tel.get("altitude") or 0), now)
        last = trail[-1] if trail else None
        if last and _distance_m(last[0], last[1], p[0], p[1]) < TRAIL_STEP_M and abs(last[2] - p[2]) < 1 and now - last[3] < 10:
            continue
        trail.append(p)


def _trail_worker():
    while True:
        time.sleep(1)
        try:
            record_trails()
        except Exception as e:
            print("Trail error:", e)


def _live_drone(slot):
    link, fresh = get_link(slot), link_fresh(slot, 5)
    tel = link["telemetry"] if fresh else {}
    run = run_of(slot)
    mission = "route" if run else ("response" if drone_response["active"] and drone_response.get("drone") == slot else "")
    trail = drone_trails.get(slot, [])[-400:]
    return {"slot": slot, "label": drone_label(slot), "virtual": is_virtual(slot), "connected": fresh,
            "lat": tel.get("lat"), "lon": tel.get("lon"), "altitude": tel.get("altitude"), "heading": tel.get("heading"),
            "speed": tel.get("speed"), "battery": tel.get("battery"), "flying": bool(tel.get("flying")), "mission": mission,
            "home": {"lat": tel["home_lat"], "lon": tel["home_lon"]} if tel.get("home_lat") else None,
            "trail": [[round(a, 7), round(b, 7), round(c, 1)] for a, b, c, _ in trail],
            "route": {"points": run["route"]["points"], "alt": run["route"]["alt"], "index": run.get("index", 0)} if run else None}


@app.route("/api/live4d")
def api_live4d():
    slot = request.args.get("drone")
    tel = get_link(slot)["telemetry"] if slot in drone_slots() else {}
    centre = (tel.get("home_lat") or tel.get("lat"), tel.get("home_lon") or tel.get("lon"))
    if None in centre:
        centre = _site_location()[0]
    if not centre:
        return jsonify({"ok": False, "error": "No position yet: connect a drone or set the site on Flight safety."}), 409
    t = traffic_state
    fresh = t["ok"] and time.time() - t["at"] < TRAFFIC_STALE_S
    threats = {a["hex"] for a in t["threats"]} if fresh else set()
    maps = []
    for m in mapping.list_all(MAPS_DIR):
        r = m.get("result") or {}
        o = r.get("origin")
        if m.get("status") == "ready" and r.get("model") and o and _distance_m(centre[0], centre[1], o["lat"], o["lon"]) < 3000:
            maps.append({"id": m["id"], "name": m["name"], "model": r["model"], "origin": o})
    return jsonify({"ok": True, "centre": {"lat": centre[0], "lon": centre[1]},
                    "drones": [_live_drone(d) for d in drone_slots() if d not in _sources_over_limit()],
                    "zones": [{"id": z["id"], "name": z["name"], "source": z.get("source", ""), "points": z["points"]} for z in nofly_zones()],
                    "aircraft": [{**{k: a[k] for k in ("hex", "call", "lat", "lon", "height_ft", "track", "dist_m")}, "threat": a["hex"] in threats}
                                 for a in (t["aircraft"] if fresh else [])][:40],
                    "maps": maps[:1]})


GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
_geocode_cache = {}
_geocode_last = [0.0]
_geocode_lock = threading.Lock()


def _geocode_fetch(q):
    """Places matching q from OpenStreetMap's Nominatim (its rules: at most one request a second, a named app)."""
    with _geocode_lock:
        wait = 1.0 - (time.time() - _geocode_last[0])
        if wait > 0:
            time.sleep(wait)
        _geocode_last[0] = time.time()
    r = requests.get(GEOCODE_URL, params={"q": q, "format": "jsonv2", "limit": 5}, timeout=8,
                     headers={"User-Agent": f"AI-Security-Command-Center/{APP_VERSION}", "Accept-Language": "en"})
    r.raise_for_status()
    return [{"name": str(x.get("display_name") or "")[:160], "lat": float(x["lat"]), "lon": float(x["lon"])} for x in r.json()]


@app.route("/api/geocode")
def api_geocode():
    """Search by address for the maps' search box (cached, so repeated searches stay offline-friendly)."""
    q = " ".join(str(request.args.get("q") or "").split())[:200]
    if len(q) < 3:
        return jsonify({"ok": False, "error": "Type at least 3 letters."}), 400
    key = q.lower()
    if key not in _geocode_cache:
        try:
            _geocode_cache[key] = _geocode_fetch(q)
        except Exception:
            return jsonify({"ok": False, "error": "Address search needs internet. You can type coordinates instead, like 33.89, 35.50."}), 502
        while len(_geocode_cache) > 500:
            _geocode_cache.pop(next(iter(_geocode_cache)))
    return jsonify({"ok": True, "results": _geocode_cache[key]})


@app.route("/mapsearch.js")
def mapsearch_js():
    return Response(pages.mapsearch.JS, mimetype="text/javascript", headers={"Cache-Control": "no-cache"})


@app.route("/live4d.js")
def live4d_js():
    return Response(pages.live4d.JS, mimetype="text/javascript", headers={"Cache-Control": "no-cache"})


@app.route("/maps-embed")
def maps_embed_page():
    """The 3D maps tool inside the Drone page's map panel (3D MAP switch): no top bar; links open full pages."""
    return Response('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<base target="_top"><link rel="stylesheet" href="/hud.css"><style>body{background:#020a10}.hud-main{padding:12px}'
                    '.page-head{display:none}</style></head><body>' + pages.maps.BODY + '</body></html>', mimetype="text/html")


@app.route("/safety")
def safety_page():
    return Response(SAFETY_PAGE, mimetype="text/html")


SAFETY_PAGE = hud_page("Flight Safety", pages.safety.BODY, active="safety")


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
        for path in (snapshot_path, os.path.splitext(snapshot_path)[0] + "_drone.jpg", os.path.splitext(snapshot_path)[0] + "_drone.mp4"):
            try:
                if os.path.exists(path):
                    os.remove(path)
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
        for extra in ("_drone.jpg", "_drone.mp4"):
            try:
                os.remove(os.path.splitext(snapshot_path)[0] + extra)
            except OSError:
                pass
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

from pages.main_page import PAGE  # noqa: E402
CAMERA_FEED_SWITCH = ('<button type="button" class="feed-switch" data-feed-switch="main" aria-pressed="true" '
                      'title="Show or hide this live feed">LIVE FEED <span class="knob"></span></button>')


PAGE = PAGE.replace("<!--HUD_SUBNAV-->", hud_subnav("dashboard"))
# Edition branding (e.g. "AI Command Centre Lebanon" for the on-prem build).
PAGE = (PAGE.replace("<title>\nAI Security Command Center\n</title>", f"<title>\n{edition.PRODUCT_NAME}\n</title>")
            .replace('<div class="brand-name">\nAI SECURITY\n</div>', f'<div class="brand-name">\n{edition.BRAND_TOP}\n</div>')
            .replace('<div class="brand-sub">\nCOMMAND CENTER\n</div>', f'<div class="brand-sub">\n{BRAND_SUB_HTML}\n</div>')
            .replace('<div class="rec-title">\nAI SECURITY CONTROLS\n</div>', f'<div class="rec-title">\n{edition.BRAND_TOP} CONTROLS\n</div>'))
_body_end = PAGE.rfind("</body>")
# Settings → Events / People / Vehicles: the dashboard's own screens for them, each on its own page (without the
# dashboard's columns or live video), so every button keeps working as before.
SETTINGS_SECTIONS = {
    "events": ("Events", "Detections and alerts: unknown faces and vehicles, drone responses.", "openEventHistory()",
               "#eventHistoryOverlay", "closeEventHistory", ""),
    "people": ("People", "Known faces: add, check and remove the people the cameras recognise.",
               "document.getElementById('openFaceLibrary').click()", "#faceLibraryOverlay", "closeFaceLibrary",
               '<button class="sp-add" onclick="document.getElementById(\'openFaceEnroll\').click()">＋ Add person</button>'),
    "vehicles": ("Vehicles", "Known vehicles and their plates.", "document.getElementById('openVehicleLibrary').click()",
                 "#vehicleLibraryOverlay", "closeVehicleLibrary",
                 '<button class="sp-add" onclick="document.getElementById(\'openVehicleEnroll\').click()">＋ Add vehicle</button>'),
}


def _section_page(key):
    title, sub, opener, overlay, close_id, extra = SETTINGS_SECTIONS[key]
    tabs = "".join(f'<a href="/settings/{k}" class="{"on" if k == key else ""}">{v[0]}</a>' for k, v in SETTINGS_SECTIONS.items())
    block = f"""<style>
.left-column,.center-column,.right-column{{display:none!important}}
.sp-head{{position:relative;z-index:5;max-width:1180px;margin:18px auto 0;padding:0 18px;display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap}}
.sp-head h1{{margin:4px 0 2px;color:#5bd9ff;font-size:24px;letter-spacing:2px;text-transform:uppercase}}
.sp-head .kick{{color:#6d8b9d;font-size:10px;letter-spacing:2.5px;text-transform:uppercase}}
.sp-head .kick a{{color:#5bd9ff;text-decoration:none}}.sp-head p{{margin:0;color:#8ba9b8;font-size:12px}}
.sp-tabs{{display:flex;gap:6px;margin-left:auto;align-items:center;flex-wrap:wrap}}
.sp-tabs a{{padding:8px 14px;border:1px solid #155879;border-radius:4px;color:#9edfff;text-decoration:none;font:bold 10px Arial;letter-spacing:1.5px;text-transform:uppercase;background:#05131d}}
.sp-tabs a.on{{background:#25c7ff;color:#02131d;border-color:#45d0ff}}
.sp-add{{margin-right:10px;padding:8px 16px;border:1px solid #45d0ff;border-radius:4px;background:#25c7ff;color:#02131d;font:bold 10px Arial;letter-spacing:1.5px;text-transform:uppercase;cursor:pointer;box-shadow:0 0 16px rgba(37,199,255,.25)}}
.sp-add:hover{{background:#5bd9ff}}
/* the screen is the page here, not a pop-up over the dashboard */
{overlay}{{position:relative!important;inset:auto!important;display:flex!important;background:none!important;min-height:auto!important;padding:14px 18px 40px!important;
  max-width:1180px;margin:0 auto;opacity:1!important;visibility:visible!important;pointer-events:auto!important}}
{overlay}>*{{max-width:none!important;width:100%!important;max-height:none!important;margin:0!important}}
#{close_id}{{display:none!important}}
</style>
<div class="sp-head"><div><div class="kick"><a href="/settings">Settings</a> › {title}</div><h1>{title}</h1><p>{sub}</p></div>
<div class="sp-tabs">{extra}{tabs}</div></div>
<script>(function(){{try{{{opener}}}catch(e){{}}
  const o=document.querySelector('{overlay}'),h=document.querySelector('.sp-head');
  if(o&&h)h.after(o);  // show the screen right under the page title
}})();</script>"""
    page = PAGE.replace(hud_subnav("dashboard"), hud_subnav("settings"), 1).replace(
        f"<title>\n{edition.PRODUCT_NAME}\n</title>", f"<title>\n{title} — {edition.PRODUCT_NAME}\n</title>", 1)
    end = page.rfind("</body>")
    return page[:end] + block + page[end:]


SECTION_PAGES = {k: _section_page(k) for k in SETTINGS_SECTIONS}
# On the dashboard itself, events, people and vehicles now live under Settings.
_hide_moved = ("<style>#historyPanel,#openFaceEnroll,#openVehicleEnroll,#openFaceLibrary,#openVehicleLibrary"
               "{display:none!important}</style>")
_body_end = PAGE.rfind("</body>")
PAGE = PAGE[:_body_end] + _hide_moved + PAGE[_body_end:]
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
DEFAULT_CUSTOMER_SETTINGS={"camera_ai":True,"face_ai":True,"lpr":True,"drone_runtime":False,"drone_ai":False,"drone_tracking":False,"gps_dispatch":False,"camera_latitude":None,"camera_longitude":None,"gps_safety_radius_m":120,"require_dispatch_confirmation":True,"dashboard_camera_feed":False}
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
<style>.set-hub{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.set-hub a{display:flex;flex-direction:column;gap:4px;padding:14px;border:1px solid #155879;border-radius:5px;background:#05131d;color:#e9f8ff;text-decoration:none}
.set-hub a:hover{border-color:#36cfff;box-shadow:0 0 12px rgba(53,203,255,.16)}
.set-hub b{font-size:13px;letter-spacing:.5px}.set-hub span{font-size:20px;color:#5bd9ff}.set-hub small{color:#6d8b9d;font-size:11px}</style>
<nav class="set-hub">
<a href="/settings/events"><span>◷</span><b>Events</b><small>Detections and alerts</small></a>
<a href="/settings/people"><span>◎</span><b>People</b><small>Known faces</small></a>
<a href="/settings/vehicles"><span>▱</span><b>Vehicles</b><small>Known plates</small></a>
<a href="/license"><span>⚿</span><b>Licence</b><small>This PC's licence</small></a>
<a href="/users"><span>👤</span><b>Users</b><small>Sign-in and roles</small></a>
<a href="/safety"><span>⚠</span><b>Flight safety</b><small>Weather, aircraft, airspace limits</small></a>
</nav>
<section class="panel"><div class="panel-head"><div class="panel-title">⌂ Dashboard</div></div><div class="panel-body">
<div class="hud-row"><div><b>Camera live feed on the dashboard</b><div class="muted">Off: the main camera's live video is not shown (or streamed) on the dashboard.</div></div><input class="toggle" type="checkbox" data-key="dashboard_camera_feed" onchange="save()"></div>
</div></section>
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
# MAPS THAT WORK OFFLINE
# Leaflet ships with the app, and every map tile the dashboard shows is kept on disk, so a site that
# looked at its map once while online still has it without internet.
# ============================================================
import sys as _sys
VENDOR_DIR = os.path.join(getattr(_sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "static")
TILE_DIR = os.path.join(os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER), "map_tiles")
TILE_SOURCES = {"osm": ("https://tile.openstreetmap.org/{z}/{x}/{y}.png", "png", "image/png"),
                "sat": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "jpg", "image/jpeg")}
TILE_REFRESH_DAYS = 30
_tile_stats = {"at": 0.0, "tiles": 0, "mb": 0.0}


@app.route("/vendor/leaflet/<path:filename>")
def vendor_leaflet(filename):
    return send_from_directory(os.path.join(VENDOR_DIR, "leaflet"), filename, max_age=7 * 86400)


@app.route("/tiles/<layer>/<int:z>/<int:x>/<int:y>")
def map_tile(layer, z, x, y):
    """A map tile from the local cache, fetched (and kept) when online. Old tiles are refreshed when possible."""
    src = TILE_SOURCES.get(layer)
    if not src or not (0 <= z <= 20 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return Response(status=404)
    path = os.path.join(TILE_DIR, layer, str(z), str(x), f"{y}.{src[1]}")
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > TILE_REFRESH_DAYS * 86400:
        try:
            r = requests.get(src[0].format(z=z, x=x, y=y), timeout=6,
                             headers={"User-Agent": f"AI-Security-Command-Center/{APP_VERSION}"})
            if r.ok and len(r.content) > 50:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path + ".tmp", "wb") as f:
                    f.write(r.content)
                os.replace(path + ".tmp", path)
        except Exception:
            pass  # offline: use the saved tile if there is one
    if not os.path.exists(path):
        return Response(status=404)
    return send_from_directory(os.path.dirname(path), os.path.basename(path), mimetype=src[2], max_age=86400)


def map_cache_stats():
    if time.time() - _tile_stats["at"] > 60:
        n = size = 0
        for root, _, files in os.walk(TILE_DIR):
            for f in files:
                if not f.endswith(".tmp"):
                    n += 1
                    size += os.path.getsize(os.path.join(root, f))
        _tile_stats.update(at=time.time(), tiles=n, mb=round(size / 1e6, 1))
    return {"tiles": _tile_stats["tiles"], "mb": _tile_stats["mb"]}

# ============================================================
# SIGN-IN AND ROLES (off until the first admin is created on the Users page)
# ============================================================
USERS_FILE = os.path.join(os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER), "users.json")
app.secret_key = user_accounts.secret_key(os.path.join(os.environ.get("AI_SECURITY_DATA") or os.path.dirname(BASE_FOLDER), "session.key"))
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=12 * 3600)
_login_fails = {}


def current_user():
    """The signed-in user, or None (also None while sign-in is off)."""
    users = user_accounts.load(USERS_FILE)
    u = user_accounts.find(users, session.get("user")) if users else None
    return u if u and session.get("stamp") == u.get("stamp") else None


@app.before_request
def _require_sign_in():
    g.user = None
    if not user_accounts.load(USERS_FILE):
        return None  # sign-in not set up yet: open as before
    path = request.path
    if path in user_accounts.OPEN_PATHS or any(path.startswith(p) for p in user_accounts.OPEN_PATHS if p.endswith("/")):
        return None
    g.user = current_user()
    if not g.user:
        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Sign in first."}), 401
        return redirect("/login?next=" + urllib.parse.quote(request.full_path.rstrip("?")))
    if not user_accounts.allowed(g.user["role"], request.method, path):
        msg = f"Your role ({g.user['role']}) can't do that. Ask an admin."
        return (jsonify({"ok": False, "error": msg}), 403) if path.startswith("/api/") or request.method != "GET" else \
            Response(hud_page("Not allowed", f'<main class="hud-main"><h1 class="page-title">Not allowed</h1><p class="muted">{msg}</p>'
                                              '<a class="hud-btn" href="/">Back to the dashboard</a></main>'), status=403, mimetype="text/html")
    return None


@app.after_request
def _user_badge(resp):
    """Who is signed in, with Sign out, on every page."""
    u = getattr(g, "user", None)
    if u and resp.mimetype == "text/html" and not resp.direct_passthrough:
        try:
            html = resp.get_data(as_text=True)
            i = html.rfind("</body>")
            if i != -1:
                badge = ('<div id="userBadge" style="position:fixed;left:10px;bottom:10px;z-index:9999;background:rgba(3,16,26,.92);'
                         'border:1px solid #155879;border-radius:4px;padding:5px 9px;font:12px Arial;color:#9edfff">👤 '
                         f'{html_escape(u["username"])} · {u["role"]} · <a href="/logout" style="color:#5bd9ff">Sign out</a></div>')
                resp.set_data(html[:i] + badge + html[i:])
        except Exception:
            pass
    return resp


def html_escape(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


LOGIN_PAGE = r"""
<main class="hud-main" style="max-width:420px;margin:60px auto">
<div class="page-head"><div><div class="page-kicker">AI Security</div><h1 class="page-title">Sign in</h1></div></div>
<section class="panel"><div class="panel-body">
<form method="post">
<input type="hidden" name="next" value="__NEXT__">
<label for="u">User name</label><input id="u" name="username" autocomplete="username" autofocus required>
<label for="pw" style="margin-top:10px">Password</label><input id="pw" name="password" type="password" autocomplete="current-password" required>
<div class="actions" style="margin-top:14px"><button class="hud-btn primary" type="submit">Sign in</button></div>
<div class="hud-msg bad" style="__ERRSTYLE__">__ERR__</div>
</form></div></section></main>"""


@app.route("/login", methods=["GET", "POST"])
def login_page():
    nxt = request.values.get("next") or "/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    if not user_accounts.load(USERS_FILE):
        return redirect("/users")
    err = ""
    if request.method == "POST":
        ip = request.remote_addr or ""
        fails = [t for t in _login_fails.get(ip, []) if time.time() - t < 300]
        if len(fails) >= 5:
            err = "Too many wrong tries. Wait 5 minutes."
        else:
            u = user_accounts.authenticate(USERS_FILE, request.form.get("username"), request.form.get("password"))
            if u:
                session.clear()
                session.permanent = True
                session.update(user=u["username"], stamp=u.get("stamp"))
                _login_fails.pop(ip, None)
                return redirect(nxt)
            time.sleep(1)
            _login_fails[ip] = fails + [time.time()]
            err = "Wrong user name or password."
    body = (LOGIN_PAGE.replace("__NEXT__", html_escape(nxt)).replace("__ERR__", html_escape(err))
            .replace("__ERRSTYLE__", "" if err else "display:none"))
    return Response(hud_page("Sign in", body, nav=False), mimetype="text/html")


@app.route("/logout")
def logout_page():
    session.clear()
    return redirect("/login" if user_accounts.load(USERS_FILE) else "/")


USERS_PAGE = r"""
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Access</div><h1 class="page-title">Users &amp; roles</h1>
<div class="page-sub">Who can use this dashboard. <b>Viewer</b>: watches live video, events and maps. <b>Operator</b>: also flies drones, routes and drone responses. <b>Admin</b>: everything, including setup, licences, no-fly zones and users.</div></div></div>
<section class="panel"><div class="panel-body">
<div id="firstNote" class="hud-msg" style="display:none">Sign-in is <b>off</b>: anyone at this PC can use everything. Create the first user below (an admin) to turn it on; you will be signed in as that user.</div>
<div id="userList"></div>
<div style="margin-top:14px;border-top:1px solid #123447;padding-top:12px"><b style="color:#5bd9ff;font-size:11px;letter-spacing:1.5px">ADD A USER</b>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0 10px">
<div><label for="nu">User name</label><input id="nu" autocomplete="off"></div>
<div><label for="np">Password (8+ characters)</label><input id="np" type="password" autocomplete="new-password"></div>
<div><label for="nr">Role</label><select id="nr"><option value="viewer">Viewer: watch only</option><option value="operator">Operator: watch and fly</option><option value="admin">Admin: everything</option></select></div></div>
<div class="actions" style="margin-top:10px"><button class="hud-btn primary" onclick="addUser()">Add user</button></div>
<div id="umsg" class="hud-msg"></div></div>
</div></section></main>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const ROLES={viewer:'Viewer: watch only',operator:'Operator: watch and fly',admin:'Admin: everything'};
let me='',arm='';
function umsg(t,ok){const e=$('umsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
async function call(url,method,body){const r=await fetch(url,{method,headers:{'content-type':'application/json'},body:body?JSON.stringify(body):undefined});return r.json()}
async function load(){const d=await call('/api/users','GET');if(!d.ok){umsg(d.error,false);return}me=d.me||'';
  $('firstNote').style.display=d.users.length?'none':'';if(!d.users.length){$('nr').value='admin'}
  $('userList').innerHTML=d.users.map(u=>`<div class="hud-row"><div><b>${esc(u.username)}</b>${u.username===me?' <span class="muted">(you)</span>':''}<div class="muted">${ROLES[u.role]}</div></div>
    <div class="actions"><select onchange="setRole('${esc(u.username)}',this.value)">${Object.keys(ROLES).map(r=>`<option value="${r}" ${r===u.role?'selected':''}>${r}</option>`).join('')}</select>
    <button class="hud-btn" onclick="resetPw('${esc(u.username)}')">New password</button>
    <button class="hud-btn danger" onclick="delUser('${esc(u.username)}',this)">${arm===u.username?'Click again to delete':'Delete'}</button></div></div>`).join('')||'<p class="muted">No users yet.</p>'}
async function addUser(){const first=!$('userList').querySelector('.hud-row');
  const d=await call('/api/users','POST',{username:$('nu').value,password:$('np').value,role:$('nr').value});
  if(!d.ok){umsg(d.error,false);return}$('nu').value=$('np').value='';umsg('User '+d.username+' added.'+(first?' Sign-in is now on.':''),true);if(first)location.reload();else load()}
async function setRole(n,r){const d=await call('/api/users/'+encodeURIComponent(n),'POST',{role:r});umsg(d.ok?n+' is now '+r+'.':d.error,d.ok);load()}
async function resetPw(n){const pw=prompt('New password for '+n+' (8+ characters):');if(!pw)return;const d=await call('/api/users/'+encodeURIComponent(n),'POST',{password:pw});
  umsg(d.ok?'Password changed. '+n+' is signed out on other devices.':d.error,d.ok);if(d.ok&&n===me)location.href='/login'}
async function delUser(n){if(arm!==n){arm=n;load();setTimeout(()=>{if(arm===n){arm='';load()}},4000);return}arm='';
  const d=await call('/api/users/'+encodeURIComponent(n),'DELETE');umsg(d.ok?n+' deleted.':d.error,d.ok);if(d.ok&&n===me)location.href='/login';else load()}
load();
</script>"""


@app.route("/users")
def users_page():
    return Response(hud_page("Users", USERS_PAGE, active="users"), mimetype="text/html")


@app.route("/api/users", methods=["GET", "POST"])
def api_users():
    all_users = user_accounts.load(USERS_FILE)
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        try:
            name = user_accounts.add(USERS_FILE, data.get("username"), data.get("password"), data.get("role"))
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        if not all_users:  # the first admin is signed in straight away
            u = user_accounts.find(user_accounts.load(USERS_FILE), name)
            session.clear()
            session.permanent = True
            session.update(user=u["username"], stamp=u.get("stamp"))
        return jsonify({"ok": True, "username": name})
    me = current_user()
    return jsonify({"ok": True, "users": [user_accounts.public(u) for u in all_users], "me": me["username"] if me else ""})


@app.route("/api/users/<name>", methods=["POST", "DELETE"])
def api_user(name):
    try:
        if request.method == "DELETE":
            user_accounts.delete(USERS_FILE, name)
        else:
            data = request.get_json(silent=True) or {}
            user_accounts.update(USERS_FILE, name, role=data.get("role"), password=data.get("password"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})

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
            # A drone response keeps the drone's own view and video beside the camera snapshot.
            stem = os.path.splitext(event["image_file"])[0]
            for key, ext in (("drone_image", "_drone.jpg"), ("drone_clip", "_drone.mp4")):
                event[key] = stem + ext if stem and os.path.exists(os.path.join(EVENT_FOLDER, stem + ext)) else ""
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
    page = PAGE
    if not _load_customer_settings().get("dashboard_camera_feed"):
        # Settings → Dashboard → "Camera live feed": off hides the panel and its switch, so nothing is streamed.
        page = (page.replace('<div id="cameraFeedPanel">', '<div id="cameraFeedPanel" hidden style="display:none">', 1)
                .replace(CAMERA_FEED_SWITCH, "", 1))
    return render_template_string(page, events=events, history_events=history_events)

@app.route("/settings/<section>")
def settings_section_page(section):
    if section not in SECTION_PAGES:
        return redirect("/settings")
    if not onprem_mode() and not str(load_edge_agent_config().get("device_token") or "").strip():
        return redirect("/")  # not paired yet: the dashboard shows the pairing page
    events, history_events = _dashboard_context()
    return render_template_string(SECTION_PAGES[section], events=events, history_events=history_events)


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
