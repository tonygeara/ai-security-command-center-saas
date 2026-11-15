"""DJI Dock support through DJI Cloud API. Phase 1: registration and status (no flying yet).

How a dock reaches this PC:

    Dock ──Ethernet── site LAN ──► dock broker on this PC (Mosquitto "dock-mqtt", LAN port 1884, password)
                                        ▲
    DJI Pilot 2 on the dock's RC ── opens the setup page (LAN port 8767, secret link) once, which hands it
    this PC's Cloud API keys and the broker address and password, so the dock connects here.

MQTT topics used (DJI Cloud API; check names against DJI's current docs when adding a phase):
    sys/product/{gateway}/status          dock -> PC  update_topo: dock online, which drone is in it
    sys/product/{gateway}/status_reply    PC -> dock  result 0
    thing/product/{sn}/osd                dock or drone -> PC  telemetry, about every 0.5 to 2 s
    thing/product/{sn}/state              dock or drone -> PC  changes (firmware, etc.)
    thing/product/{gateway}/events        dock -> PC  replied to on .../events_reply when need_reply = 1
    thing/product/{gateway}/requests      dock -> PC  e.g. "config": answered on .../requests_reply
    thing/product/{gateway}/services      PC -> dock  commands (live_start_push, live_stop_push, live_lens_change)
    thing/product/{gateway}/services_reply  dock -> PC  result 0 = done
    Missions (Phase 3): flighttask_prepare (a KMZ flight plan the dock downloads from this PC) -> flighttask_execute;
    flighttask_progress events while it flies; return_home to bring it back.
    Live control (Phase 4): fly_to_point / fly_to_point_stop; DRC (drone remote control): drc_mode_enter (pointing the
    dock at this broker), flight_authority_grab, payload_authority_grab, then stick_control and heart_beat messages on
    thing/product/{gateway}/drc/down; drc_mode_exit. Camera: camera_photo_take, camera_recording_start/stop, gimbal_reset.

A dock that connects is listed as "found"; an admin registers it (name, slot dock1, dock2, …) before it is part
of the system. A simulated dock (dock_sim.py) goes through the same hub without a broker, for tests and demos.
"""
import base64
import collections
import hashlib
import json
import os
import secrets
import threading
import time
import uuid

BROKER_PORT = 1884          # LAN port of the dock broker (docker-compose: dock-mqtt)
PILOT_PAGE_PORT = 8767      # LAN port of the Pilot 2 setup page
ONLINE_SECONDS = 15         # no message for this long: offline
SLOT_PREFIX = "dock"

# (domain, type, sub_type) -> name, from DJI's Cloud API product list. Add new models there as DJI releases them.
MODELS = {
    "3-1-0": "DJI Dock", "3-2-0": "DJI Dock 2", "3-3-0": "DJI Dock 3",
    "0-60-0": "Matrice 300 RTK", "0-89-0": "Matrice 350 RTK",
    "0-67-0": "Matrice 30", "0-67-1": "Matrice 30T",
    "0-77-0": "Mavic 3E", "0-77-1": "Mavic 3T", "0-77-2": "Mavic 3M",
    "0-91-0": "Matrice 3D", "0-91-1": "Matrice 3TD",
    "0-99-0": "Matrice 4E", "0-99-1": "Matrice 4T",
    "0-100-0": "Matrice 4D", "0-100-1": "Matrice 4TD",
    "2-119-0": "DJI RC Plus", "2-144-0": "DJI RC Pro Enterprise", "2-174-0": "DJI RC Plus 2",
}
DOCK_MODES = {0: "idle", 1: "on-site debugging", 2: "remote debugging", 3: "updating firmware", 4: "working"}
COVER_STATES = {0: "closed", 1: "open", 2: "half open", 3: "cover fault"}
# Health alerts (Telegram and the Drone page). A condition must clear past its "back" value to end (no flapping).
OFFLINE_ALERT_SECONDS = 60     # a registered dock silent this long
STARTUP_GRACE_SECONDS = 120    # after the PC starts, a dock that never connected
WIND_ALERT, WIND_BACK = 12.0, 9.0          # m/s: DJI docks don't take off above about 12 m/s
HOT_ALERT, HOT_BACK = 45.0, 42.0           # °C outside the dock
COLD_ALERT, COLD_BACK = -20.0, -17.0
LOW_BATTERY = 20                            # % of the drone in the dock, not charging
HMS_CLEAR_SECONDS = 60          # a DJI health message not repeated this long has cleared
HMS_LEVELS = {0: "notice", 1: "caution", 2: "warning"}
# Live video (Phase 2): the dock pushes RTMP to this PC's MediaMTX at rtmp://PC:1935/<slot>, the same path as Drone Link.
LENSES = ("wide", "zoom", "ir", "normal")
# Mission states reported by flighttask_progress (DJI); these end a mission.
MISSION_DONE = ("ok", "failed", "canceled", "timeout", "partially_done", "rejected")
WAYLINE_TTL = 900  # seconds a flight plan's download link works
_waylines = {}     # token -> (kmz bytes, expires)


def publish_wayline(data, ttl=WAYLINE_TTL):
    """Keep a flight plan for the dock to download from the LAN page server; returns its secret token."""
    now = time.time()
    for k in [k for k, (_, exp) in _waylines.items() if exp < now]:
        _waylines.pop(k, None)
    token = secrets.token_urlsafe(24)
    _waylines[token] = (data, now + ttl)
    return token
LENS_NAMES = {"wide": "wide", "zoom": "zoom", "ir": "thermal", "normal": "main"}
# DJI live-stream result codes we expect (from DJI's error list; confirm with real hardware). Others show their number.
LIVE_ERRORS = {513003: "The video is already streaming.", 513005: "The video is not streaming.",
               513012: "The drone's camera isn't ready yet. Try again in a few seconds."}
RAIN = {0: "none", 1: "light", 2: "moderate", 3: "heavy"}


def model_name(domain, type_, sub_type):
    key = f"{domain}-{type_}-{sub_type}"
    return MODELS.get(key, f"Unknown ({key})")


# ---------- broker files (written by the launcher before docker compose starts, and by the dashboard) ----------

def mosquitto_hash(password, salt=None):
    """Mosquitto 2 password-file hash: PBKDF2-SHA512, 101 rounds ($7$), the same as mosquitto_passwd writes."""
    salt = salt or os.urandom(12)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, 101)
    return f"$7$101${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def ensure_broker_files(folder):
    """The dock broker's config, password file and the credentials this PC uses. Made once; returns the credentials:
    {"dock_user", "dock_password"} for docks and Pilot 2, {"edge_user", "edge_password"} for this PC."""
    os.makedirs(folder, exist_ok=True)
    creds_path = os.path.join(folder, "credentials.json")
    creds = _read_json(creds_path)
    if not (creds.get("dock_password") and creds.get("edge_password")):
        creds = {"dock_user": "dock", "dock_password": secrets.token_urlsafe(18),
                 "edge_user": "edge", "edge_password": secrets.token_urlsafe(18)}
        _write_json(creds_path, creds)
    conf = ("# DJI Dock broker (written by AI Security; changes are overwritten). /mosquitto/passwd is a private\n"
            "# copy of passwd made when the container starts (docker-compose.yml).\n"
            "listener 1883\nallow_anonymous false\npassword_file /mosquitto/passwd\npersistence false\n")
    _write_if_changed(os.path.join(folder, "mosquitto.conf"), conf)
    passwd_path = os.path.join(folder, "passwd")
    current = _read_text(passwd_path)
    if not (_passwd_matches(current, creds["dock_user"], creds["dock_password"])
            and _passwd_matches(current, creds["edge_user"], creds["edge_password"])):
        _write_text(passwd_path, f"{creds['dock_user']}:{mosquitto_hash(creds['dock_password'])}\n"
                                 f"{creds['edge_user']}:{mosquitto_hash(creds['edge_password'])}\n")
    return creds


def _passwd_matches(text, user, password):
    for line in (text or "").splitlines():
        name, _, h = line.partition(":")
        if name == user and h.startswith("$7$"):
            try:
                _, _, rounds, salt, _ = h.split("$")
                return h == mosquitto_hash(password, base64.b64decode(salt)) and rounds == "101"
            except ValueError:
                return False
    return False


# ---------- registry: Cloud API keys, Pilot 2 link, registered docks ----------

class DockStore:
    """docks.json in the data folder."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = _read_json(path)
        self.data.setdefault("cloud", {})
        self.data.setdefault("docks", {})
        self.data.setdefault("simulated", [])
        if not self.data.get("workspace_id"):
            self.data["workspace_id"] = str(uuid.uuid4())
        if not self.data.get("bind_token"):
            self.data["bind_token"] = secrets.token_urlsafe(24)
        self.save()

    def save(self):
        with self.lock:
            _write_json(self.path, self.data)

    # Cloud API app (developer.dji.com → Apps → Cloud API): needed by Pilot 2 and the dock.
    def cloud(self):
        c = self.data["cloud"]
        return {"app_id": str(c.get("app_id") or ""), "app_key": str(c.get("app_key") or ""),
                "app_license": str(c.get("app_license") or "")}

    def cloud_ready(self):
        c = self.cloud()
        return bool(c["app_id"] and c["app_key"] and c["app_license"])

    def set_cloud(self, app_id=None, app_key=None, app_license=None):
        c = self.data["cloud"]
        for k, v in (("app_id", app_id), ("app_key", app_key), ("app_license", app_license)):
            if v is not None:
                c[k] = str(v).strip()
        self.save()

    def new_bind_token(self):
        self.data["bind_token"] = secrets.token_urlsafe(24)
        self.save()
        return self.data["bind_token"]

    def docks(self):
        return dict(self.data["docks"])

    def register(self, sn, name, simulated=False):
        sn = clean_sn(sn)
        if not sn:
            raise ValueError("No dock serial number.")
        docks = self.data["docks"]
        if sn in docks:
            raise ValueError("This dock is already registered.")
        used = {d.get("slot") for d in docks.values()}
        n = next(i for i in range(1, len(docks) + 2) if f"{SLOT_PREFIX}{i}" not in used)
        name = str(name or "").strip()[:40] or f"Dock {n}"
        docks[sn] = {"name": name, "slot": f"{SLOT_PREFIX}{n}", "registered_at": time.time(), "simulated": bool(simulated)}
        self.save()
        return docks[sn]

    def set_settings(self, sn, **values):
        """Per-dock settings: auto_flights (+ who confirmed the site's permission, and when), range_m."""
        d = self.data["docks"].get(sn)
        if not d:
            raise KeyError(sn)
        d.update(values)
        self.save()
        return d

    def real_docks(self):
        """Registered real docks, oldest first (simulated docks are for testing and don't count)."""
        docks = self.data["docks"]
        return sorted((sn for sn, d in docks.items() if not d.get("simulated")), key=lambda sn: docks[sn].get("registered_at") or 0)

    def over_limit(self, limit):
        """Real docks beyond the licence's dock count (the newest ones), e.g. after the licence was lowered."""
        return set() if limit is None else set(self.real_docks()[max(0, int(limit)):])

    def rename(self, sn, name):
        d = self.data["docks"].get(sn)
        if not d:
            raise KeyError(sn)
        d["name"] = str(name or "").strip()[:40] or d["name"]
        self.save()

    def unregister(self, sn):
        removed = self.data["docks"].pop(sn, None)
        self.save()
        return removed

    def set_simulated(self, sns):
        self.data["simulated"] = list(sns)
        self.save()


def clean_sn(sn):
    sn = str(sn or "").strip()
    return sn if 4 <= len(sn) <= 40 and all(c.isalnum() or c in "-_" for c in sn) else ""


# ---------- hub: what the docks say, and the replies they need ----------

class DockHub:
    """Takes every message from the docks (MQTT or a simulated dock), keeps their live state and replies.
    publish(topic, dict) sends to MQTT; simulated docks get their replies directly."""

    def __init__(self, store, now=time.time):
        self.store = store
        self.now = now
        self.lock = threading.Lock()
        self.state = {}       # gateway sn -> live state
        self.drone_of = {}    # drone sn -> gateway sn
        self.local = {}       # gateway sn -> simulated dock
        self.publish_mqtt = None
        self.on_change = None  # called with (event, gateway sn): "online", "offline", "found"
        self.started_at = now()
        self.pending = {}     # tid -> {"event", "reply"} for services waiting for the dock's answer

    # --- outgoing ---
    def publish(self, topic, payload):
        sn = _topic_sn(topic)
        sim = self.local.get(sn)
        if sim is not None:
            sim.on_message(topic, payload)
        elif self.publish_mqtt:
            self.publish_mqtt(topic, payload)

    def _reply(self, topic, msg, data):
        self.publish(topic + "_reply", {"tid": msg.get("tid") or str(uuid.uuid4()), "bid": msg.get("bid") or str(uuid.uuid4()),
                                        "timestamp": int(self.now() * 1000), "method": msg.get("method"), "data": data})

    # --- incoming ---
    def handle(self, topic, payload):
        """One MQTT message. payload: bytes, str or an already decoded dict."""
        try:
            msg = payload if isinstance(payload, dict) else json.loads(payload)
        except (ValueError, TypeError):
            return
        if not isinstance(msg, dict):
            return
        parts = topic.split("/")
        if len(parts) != 4 or parts[1] != "product":
            return
        kind, sn, leaf = parts[0], parts[2], parts[3]
        if kind == "sys" and leaf == "status":
            self._status(topic, sn, msg)
        elif kind == "thing" and leaf == "osd":
            self._osd(sn, msg.get("data") or {})
        elif kind == "thing" and leaf == "state":
            gw = self.drone_of.get(sn, sn)
            self._touch(gw)
            cap = (msg.get("data") or {}).get("live_capacity")
            if isinstance(cap, dict):
                with self.lock:
                    if gw in self.state:
                        self.state[gw]["live_capacity"] = cap
        elif kind == "thing" and leaf == "services_reply":
            waiting = self.pending.get(str(msg.get("tid") or ""))
            if waiting is not None:
                waiting["reply"] = msg
                waiting["event"].set()
        elif kind == "thing" and leaf == "events":
            self._touch(sn)
            if msg.get("method") == "hms":
                self._hms(self.drone_of.get(sn, sn), msg.get("data") or {})
            elif msg.get("method") == "flighttask_progress":
                self._progress(sn, msg.get("data") or {})
            if msg.get("need_reply"):
                self._reply(topic, msg, {"result": 0})
        elif kind == "thing" and leaf == "requests":
            self._touch(sn)
            self._request(topic, msg)

    def _status(self, topic, gw, msg):
        if msg.get("method") != "update_topo":
            return
        data = msg.get("data") or {}
        subs = data.get("sub_devices") or []
        drone = subs[0] if subs and isinstance(subs[0], dict) else None
        with self.lock:
            s = self.state.setdefault(gw, {"sn": gw, "osd": {}, "drone_osd": {}, "first_seen": self.now()})
            new = "model" not in s
            if data:
                s["model"] = model_name(data.get("domain"), data.get("type"), data.get("sub_type"))
                s["is_dock"] = str(data.get("domain")) == "3"
                s["version"] = str(data.get("version") or "")
            if drone:
                s["drone_sn"] = str(drone.get("sn") or "")
                s["drone_enum"] = (int(drone.get("type") or 0), int(drone.get("sub_type") or 0))
                s["drone_model"] = model_name(drone.get("domain"), drone.get("type"), drone.get("sub_type"))
                self.drone_of[s["drone_sn"]] = gw
            elif data:
                s["drone_sn"], s["drone_model"] = "", ""
            if not data:  # an empty topology: the device went offline (and its video and stick control with it)
                s["offline_at"] = self.now()
                s.pop("live", None)
                s.pop("drc", None)
            s["last_seen"] = self.now()
        self._reply(topic, msg, {"result": 0})
        if self.on_change:
            self.on_change("offline" if not data else "found" if new and gw not in self.store.docks() else "online", gw)

    def _osd(self, sn, data):
        gw = self.drone_of.get(sn)
        with self.lock:
            if gw:
                s = self.state.get(gw)
                if s is not None:
                    s["drone_osd"] = data
                    s["drone_seen"] = self.now()
                    s["last_seen"] = self.now()
                return
            s = self.state.get(sn)
            if s is None:
                return  # telemetry before the topology: wait for update_topo
            s["osd"] = {**s["osd"], **data}  # docks send their fields in several partial messages
            s["last_seen"] = self.now()
            s.pop("offline_at", None)

    def _hms(self, gw, data):
        """DJI health messages (HMS): the dock sends the current list again while a problem lasts."""
        items = data.get("list") if isinstance(data.get("list"), list) else []
        with self.lock:
            s = self.state.get(gw)
            if s is None:
                return
            hms = s.setdefault("hms", {})
            for it in items:
                if not isinstance(it, dict) or not it.get("code"):
                    continue
                code = str(it["code"])[:20]
                hms[code] = {"code": code, "level": it.get("level"), "device_type": str(it.get("device_type") or ""),
                             "in_the_sky": bool(it.get("in_the_sky")), "seen": self.now()}

    # --- commands (DJI Cloud API services) ---
    def call(self, gw, method, data, timeout=10.0):
        """Send one service to a dock and wait for its answer. Returns (ok, message, output)."""
        tid = str(uuid.uuid4())
        waiting = self.pending[tid] = {"event": threading.Event(), "reply": None}
        try:
            self.publish(f"thing/product/{gw}/services", {"tid": tid, "bid": str(uuid.uuid4()), "timestamp": int(self.now() * 1000),
                                                         "method": method, "data": data})
            if not waiting["event"].wait(timeout):
                return False, "The dock didn't answer. Is it online?", None
        finally:
            self.pending.pop(tid, None)
        out = (waiting["reply"] or {}).get("data") or {}
        result = out.get("result", 0)
        if result == 0:
            return True, "", out
        return False, LIVE_ERRORS.get(result, f"The dock refused ({method}, DJI code {result})."), out

    def video_sources(self, gw):
        """What the dock can stream (from its live_capacity): [{"video_id", "device", "lenses"}], the drone first."""
        s = self.state.get(gw) or {}
        drone = s.get("drone_sn") or ""
        out = []
        for dev in ((s.get("live_capacity") or {}).get("device_list") or []):
            for cam in dev.get("camera_list") or []:
                for v in cam.get("video_list") or []:
                    if dev.get("sn") and cam.get("camera_index") and v.get("video_index"):
                        out.append({"video_id": f"{dev['sn']}/{cam['camera_index']}/{v['video_index']}",
                                    "device": "drone" if dev["sn"] == drone else "dock",
                                    "lenses": [t for t in (v.get("switchable_video_types") or []) if t in LENSES]})
        return sorted(out, key=lambda x: x["device"] != "drone")

    def start_video(self, gw, rtmp_url, device="drone", quality=0):
        src = next((v for v in self.video_sources(gw) if v["device"] == device), None)
        if src is None:
            return False, ("The drone isn't reporting a camera. Is it powered on in the dock?" if device == "drone"
                           else "This dock has no camera to stream."), None
        ok, msg, _ = self.call(gw, "live_start_push", {"url_type": 1, "url": rtmp_url, "video_id": src["video_id"],
                                                        "video_quality": int(quality)})
        if ok or "already" in msg:
            with self.lock:
                self.state[gw]["live"] = {"video_id": src["video_id"], "device": device, "url": rtmp_url,
                                          "lens": "wide" if "wide" in src["lenses"] else (src["lenses"] or ["normal"])[0],
                                          "lenses": src["lenses"], "since": self.now()}
            return True, "", src
        return False, msg, None

    def stop_video(self, gw):
        live = (self.state.get(gw) or {}).get("live")
        if not live:
            return True, "", None
        ok, msg, _ = self.call(gw, "live_stop_push", {"video_id": live["video_id"]})
        if ok or "not streaming" in msg:
            with self.lock:
                self.state[gw].pop("live", None)
            return True, "", None
        return False, msg, None

    def change_lens(self, gw, lens):
        live = (self.state.get(gw) or {}).get("live")
        if not live:
            return False, "Start the video first.", None
        if lens not in (live.get("lenses") or []):
            return False, f"This camera has no {LENS_NAMES.get(lens, lens)} lens.", None
        ok, msg, out = self.call(gw, "live_lens_change", {"video_id": live["video_id"], "video_type": lens})
        if ok:
            with self.lock:
                self.state[gw]["live"]["lens"] = lens
        return ok, msg, out

    # --- missions (Phase 3) ---
    def payload_enum(self, gw):
        """The drone camera's DJI type number (the first part of its camera index, e.g. 99 for "99-0-0")."""
        src = next((v for v in self.video_sources(gw) if v["device"] == "drone"), None)
        try:
            return int(src["video_id"].split("/")[1].split("-")[0]) if src else None
        except ValueError:
            return None

    def start_mission(self, gw, flight_id, url, md5, rth_alt, name="", points=None):
        """Hand the dock a flight plan and start it. Returns (ok, message)."""
        ok, msg, _ = self.call(gw, "flighttask_prepare", {
            "flight_id": flight_id, "execute_time": int(self.now() * 1000), "task_type": 0, "wayline_type": 0,
            "file": {"url": url, "fingerprint": md5}, "rth_altitude": int(rth_alt),
            "out_of_control_action": 0, "exit_wayline_when_rc_lost": 1}, timeout=30.0)
        if not ok:
            return False, msg or "The dock didn't accept the flight plan."
        with self.lock:
            self.state[gw]["mission"] = {"flight_id": flight_id, "name": name, "status": "starting", "percent": 0,
                                         "index": 0, "since": self.now(), "points": points or []}
        ok, msg, _ = self.call(gw, "flighttask_execute", {"flight_id": flight_id}, timeout=30.0)
        if not ok:
            self.call(gw, "flighttask_undo", {"flight_ids": [flight_id]}, timeout=10.0)
            with self.lock:
                self.state[gw].pop("mission", None)
            return False, msg or "The dock didn't start the flight."
        return True, ""

    def return_home(self, gw):
        """Bring the drone back to the dock now (or cancel a mission that hasn't taken off)."""
        if self.drc_active(gw):
            self.drc_exit(gw)  # sticks off first: DJI's return to home takes over
        ok, msg, _ = self.call(gw, "return_home", {}, timeout=15.0)
        if ok:
            with self.lock:
                m = self.state[gw].get("mission")
                if m:
                    m["status"] = "returning"
        return ok, msg

    def _progress(self, sn, data):
        gw = self.drone_of.get(sn, sn)
        out = data.get("output") or {}
        ext, prog = out.get("ext") or {}, out.get("progress") or {}
        with self.lock:
            m = (self.state.get(gw) or {}).get("mission")
            if m is None or (ext.get("flight_id") and ext["flight_id"] != m["flight_id"]):
                return
            status = str(out.get("status") or m["status"])
            if not (m["status"] in ("returning", "manual") and status in ("in_progress", "paused")):
                m["status"] = status
            m["percent"] = int(prog.get("percent") or m["percent"])
            m["index"] = int(ext.get("current_waypoint_index") or m["index"])
            m["updated"] = self.now()
            if status in MISSION_DONE:
                m["ended"] = self.now()

    def mission(self, gw):
        m = (self.state.get(gw) or {}).get("mission")
        if not m:
            return None
        return {k: m.get(k) for k in ("flight_id", "name", "status", "percent", "index", "since", "ended", "points")} | {
            "active": m["status"] not in MISSION_DONE, "sticks": self.drc_active(gw)}

    # --- live control (Phase 4) ---
    def payload_index(self, gw):
        """The drone camera's index, e.g. "99-0-0" (from live_capacity)."""
        src = next((v for v in self.video_sources(gw) if v["device"] == "drone"), None)
        return src["video_id"].split("/")[1] if src else None

    def _set_mission(self, gw, **values):
        with self.lock:
            m = (self.state.get(gw) or {}).get("mission")
            if m is not None:
                m.update(values)

    def fly_to(self, gw, points, speed=8.0):
        """Take over from the route and fly to these points [(lat, lon, height above the dock)]; it then holds there."""
        m = self.mission(gw) or {}
        if m.get("status") in ("in_progress", "starting", "sent"):
            self.call(gw, "flighttask_pause", {}, timeout=10.0)  # a route in progress must be paused first
        ok, msg, _ = self.call(gw, "fly_to_point", {"fly_to_id": str(uuid.uuid4()), "max_speed": int(max(1, min(15, speed))),
                                                     "points": [{"latitude": a, "longitude": b, "height": h} for a, b, h in points]},
                               timeout=15.0)
        if ok:
            self._set_mission(gw, status="manual")
        return ok, msg

    def fly_to_stop(self, gw):
        ok, msg, _ = self.call(gw, "fly_to_point_stop", {}, timeout=10.0)
        return ok, msg

    def drc_enter(self, gw, broker_address, username, password):
        """Start live stick control: the dock opens a fast channel on our broker; we take the flight and camera controls."""
        ok, msg, _ = self.call(gw, "drc_mode_enter", {
            "mqtt_broker": {"address": broker_address, "client_id": f"drc-{gw}", "username": username, "password": password,
                            "expire_time": int(self.now()) + 3600, "enable_tls": False},
            "osd_frequency": 10, "hsi_frequency": 1}, timeout=15.0)
        if not ok:
            return False, msg
        for method, data in (("flight_authority_grab", {}), ("payload_authority_grab", {"payload_index": self.payload_index(gw) or ""})):
            ok, msg, _ = self.call(gw, method, data, timeout=10.0)
            if not ok:
                self.call(gw, "drc_mode_exit", {}, timeout=10.0)
                return False, msg
        with self.lock:
            self.state[gw]["drc"] = {"seq": 0, "since": self.now(), "stick_at": 0.0, "beat_at": 0.0}
        self._set_mission(gw, status="manual")
        return True, ""

    def drc_active(self, gw):
        return bool((self.state.get(gw) or {}).get("drc"))

    def sticks(self, gw, x=0.0, y=0.0, z=0.0, r=0.0, speed=0.5, from_operator=True):
        """One stick message (-1..1 each: x right, y forward, z up, r turn right), scaled by speed (0.1..1)."""
        drc = (self.state.get(gw) or {}).get("drc")
        if not drc:
            return False
        k = 660 * max(0.1, min(1.0, float(speed)))
        c = lambda v: int(round(1024 + max(-1.0, min(1.0, float(v))) * k))  # noqa: E731
        drc["seq"] += 1
        if from_operator:
            drc["stick_at"] = self.now()
        self.publish(f"thing/product/{gw}/drc/down", {"method": "stick_control", "data": {
            "roll": c(x), "pitch": c(y), "throttle": c(z), "yaw": c(r), "seq": drc["seq"]}})
        return True

    def drc_heartbeat(self, gw):
        drc = (self.state.get(gw) or {}).get("drc")
        if drc:
            drc["seq"] += 1
            drc["beat_at"] = self.now()
            self.publish(f"thing/product/{gw}/drc/down", {"method": "heart_beat", "data": {"seq": drc["seq"], "timestamp": int(self.now() * 1000)}})

    def drc_exit(self, gw):
        with self.lock:
            had = (self.state.get(gw) or {}).pop("drc", None)
        if had:
            self.call(gw, "drc_mode_exit", {}, timeout=10.0)
        return True

    def camera(self, gw, action):
        """photo, record_start, record_stop, gimbal_down, gimbal_center."""
        idx = self.payload_index(gw)
        if not idx:
            return False, "The drone isn't reporting a camera."
        method, data = {"photo": ("camera_photo_take", {}), "record_start": ("camera_recording_start", {}),
                        "record_stop": ("camera_recording_stop", {}), "gimbal_down": ("gimbal_reset", {"reset_mode": 1}),
                        "gimbal_center": ("gimbal_reset", {"reset_mode": 0})}[action]
        ok, msg, _ = self.call(gw, method, {"payload_index": idx, **data}, timeout=10.0)
        return ok, msg

    def clear_mission(self, gw):
        with self.lock:
            (self.state.get(gw) or {}).pop("mission", None)

    def hms_active(self, gw):
        s = self.state.get(gw) or {}
        return [h for h in (s.get("hms") or {}).values() if self.now() - h["seen"] < HMS_CLEAR_SECONDS]

    def _touch(self, gw):
        with self.lock:
            if gw in self.state:
                self.state[gw]["last_seen"] = self.now()

    def _request(self, topic, msg):
        if msg.get("method") == "config":  # the dock asks for the time server and the Cloud API app it should use
            c = self.store.cloud()
            self._reply(topic, msg, {"ntp_server_host": "pool.ntp.org", "app_id": c["app_id"],
                                     "app_key": c["app_key"], "app_license": c["app_license"]})
        else:
            self._reply(topic, msg, {"result": 0})

    # --- what the dashboard shows ---
    def online(self, gw):
        s = self.state.get(gw) or {}
        return bool(s.get("last_seen")) and not s.get("offline_at") and self.now() - s["last_seen"] < ONLINE_SECONDS

    def summary(self, gw):
        s = self.state.get(gw) or {}
        o, d = s.get("osd") or {}, s.get("drone_osd") or {}
        charge = o.get("drone_charge_state") or {}
        battery = (d.get("battery") or {}).get("capacity_percent")
        if battery is None:
            battery = charge.get("capacity_percent")
        drone_on = bool(s.get("drone_seen")) and self.now() - s["drone_seen"] < ONLINE_SECONDS
        return {"sn": gw, "model": s.get("model") or "", "online": self.online(gw), "last_seen": s.get("last_seen"),
                "drone_sn": s.get("drone_sn") or "", "drone_model": s.get("drone_model") or "",
                "drone_online": drone_on, "drone_in_dock": _flag(o.get("drone_in_dock")),
                "mode": DOCK_MODES.get(o.get("mode_code"), ""), "cover": COVER_STATES.get(o.get("cover_state"), ""),
                "battery": battery, "charging": charge.get("state") == 1,
                "temperature": o.get("environment_temperature"), "wind": o.get("wind_speed"),
                "rain": RAIN.get(o.get("rainfall"), ""),
                "lat": o.get("latitude") or None, "lon": o.get("longitude") or None,
                "drone_lat": d.get("latitude") if drone_on else None, "drone_lon": d.get("longitude") if drone_on else None,
                "drone_height": d.get("height") if drone_on else None,
                "simulated": gw in self.local,
                "mission": self.mission(gw),
                "video": {"streaming": bool(s.get("live")), "lens": (s.get("live") or {}).get("lens"),
                          "device": (s.get("live") or {}).get("device"),
                          "lenses": (s.get("live") or {}).get("lenses") or next((v["lenses"] for v in self.video_sources(gw)), []),
                          "sources": [v["device"] for v in self.video_sources(gw)]}}

    def snapshot(self):
        """Registered docks (with their live state) and found, not yet registered ones."""
        registered = self.store.docks()
        docks = [{**self.summary(sn), "name": d["name"], "slot": d["slot"]} for sn, d in registered.items()]
        docks.sort(key=lambda x: (len(x["slot"]), x["slot"]))
        with self.lock:
            found = [self.summary(sn) for sn, s in self.state.items()
                     if sn not in registered and s.get("is_dock") and self.online(sn)]
        return {"docks": docks, "found": found}


def _flag(v):
    return None if v is None else bool(v)


def _topic_sn(topic):
    parts = str(topic).split("/")
    return parts[2] if len(parts) >= 3 else ""


# ---------- health alerts ----------

class DockHealth:
    """Watches the registered docks and says when a problem starts and when it ends. check() returns the changes:
    [{"sn", "name", "key", "level", "text", "active", "t"}]; active() lists what is wrong now (for the Drone page)."""

    def __init__(self, hub, hms_text=None):
        self.hub = hub
        self.hms_text = hms_text or {}   # optional DJI code -> text (DJI's hms.json, if provided)
        self.current = {}                 # (sn, key) -> alert
        self.log = collections.deque(maxlen=50)
        self.lock = threading.Lock()
        self.skip = lambda: set()         # docks not watched (over the licence's dock count)

    def _conditions(self, sn, x, name):
        """{key: (level, text)} of what is wrong now, using the previous state for the "back" thresholds."""
        now, was = self.hub.now(), lambda k: (sn, k) in self.current
        out = {}
        seen = x.get("last_seen")
        if not x["online"]:
            if seen and now - seen >= OFFLINE_ALERT_SECONDS:
                out["offline"] = ("warning", f"{name} is offline: no message for {int((now - seen) // 60) or 1} min. Check its power and network.")
            elif not seen and now - self.hub.started_at >= STARTUP_GRACE_SECONDS:
                out["offline"] = ("warning", f"{name} hasn't connected since AI Security started. Check its power and network.")
            return out  # nothing else is known about an offline dock
        if x.get("cover") == "cover fault":
            out["cover"] = ("warning", f"{name}: the dock cover reports a fault. The drone can't take off or land.")
        if x.get("rain") == "heavy":
            out["rain"] = ("caution", f"{name}: heavy rain. Flights from this dock are not safe.")
        w = x.get("wind")
        if w is not None and (w >= WIND_ALERT or (was("wind") and w > WIND_BACK)):
            out["wind"] = ("caution", f"{name}: strong wind, {w:.1f} m/s. Flights from this dock are not safe.")
        t = x.get("temperature")
        if t is not None and (t >= HOT_ALERT or (was("hot") and t > HOT_BACK)):
            out["hot"] = ("caution", f"{name}: {t:.0f} °C outside the dock. Too hot for flights.")
        if t is not None and (t <= COLD_ALERT or (was("cold") and t < COLD_BACK)):
            out["cold"] = ("caution", f"{name}: {t:.0f} °C outside the dock. Too cold for flights.")
        b = x.get("battery")
        if x.get("drone_in_dock") and b is not None and b < LOW_BATTERY and not x.get("charging"):
            out["battery"] = ("warning", f"{name}: the drone in the dock is at {b}% and not charging.")
        for h in self.hub.hms_active(sn):
            level = HMS_LEVELS.get(h["level"], "notice")
            if level == "notice":
                continue
            what = "drone" if h["device_type"].startswith("0-") else "dock"
            detail = self.hms_text.get(h["code"].lower()) or self.hms_text.get(h["code"]) or f"code {h['code']} (see DJI Pilot 2 or DJI's HMS list)"
            out["hms:" + h["code"]] = (level, f"{name}: DJI {level} on the {what}{' in flight' if h['in_the_sky'] else ''}: {detail}")
        return out

    def check(self):
        changes, now = [], self.hub.now()
        skip = self.skip()
        registered = {sn: d for sn, d in self.hub.store.docks().items() if sn not in skip}
        with self.lock:
            live = set()
            for sn, d in registered.items():
                x = self.hub.summary(sn)
                for key, (level, text) in self._conditions(sn, x, d["name"]).items():
                    live.add((sn, key))
                    if (sn, key) not in self.current:
                        a = {"sn": sn, "name": d["name"], "key": key, "level": level, "text": text, "active": True, "t": now}
                        self.current[(sn, key)] = a
                        changes.append(a)
                    else:
                        self.current[(sn, key)]["text"] = text
            for k in [k for k in self.current if k not in live]:
                a = self.current.pop(k)
                gone = k[0] not in registered
                if not gone:
                    changes.append({**a, "active": False, "t": now, "text": _cleared_text(a)})
            self.log.extend(changes)
        return changes

    def active(self, sn=None):
        with self.lock:
            return [dict(a) for (s, _), a in self.current.items() if sn is None or s == sn]

    def recent(self, n=20):
        with self.lock:
            return [dict(a) for a in list(self.log)[-n:]][::-1]


def _cleared_text(a):
    return {"offline": f"{a['name']} is back online.", "cover": f"{a['name']}: the cover fault has cleared.",
            "rain": f"{a['name']}: the heavy rain has stopped.", "wind": f"{a['name']}: the wind has dropped.",
            "hot": f"{a['name']}: the temperature is back to normal.", "cold": f"{a['name']}: the temperature is back to normal.",
            "battery": f"{a['name']}: the drone is charging again."}.get(a["key"], f"{a['name']}: the DJI message has cleared ({a['key'][4:]}).")


def load_hms_text(path):
    """DJI's HMS message list (hms.json from DJI's Cloud API docs), if the owner put it in the data folder:
    {"0x16100083": {"en": "..."}} or {"code": "text"}. Without it alerts show the code."""
    data = _read_json(path)
    out = {}
    for code, v in data.items():
        text = v.get("en") or v.get("tipEn") if isinstance(v, dict) else v
        if isinstance(text, str) and text.strip():
            out[str(code).lower() if str(code).lower().startswith("0x") else str(code)] = text.strip()[:200]
    return out


# ---------- MQTT ----------

class MqttTransport:
    """This PC's connection to the dock broker; reconnects by itself."""
    TOPICS = ("sys/product/+/status", "thing/product/+/osd", "thing/product/+/state",
              "thing/product/+/events", "thing/product/+/requests", "thing/product/+/services_reply")

    def __init__(self, hub, host, port, username, password):
        import paho.mqtt.client as mqtt
        self.hub = hub
        self.connected = False
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"ai-security-{uuid.uuid4().hex[:8]}")
        self.client.username_pw_set(username, password)
        self.client.reconnect_delay_set(1, 30)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = lambda c, u, m: hub.handle(m.topic, m.payload)
        self.host, self.port = host, port
        hub.publish_mqtt = self.send

    def start(self):
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        try:
            self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def send(self, topic, payload):
        self.client.publish(topic, json.dumps(payload, separators=(",", ":")), qos=1)

    def _on_connect(self, client, userdata, flags, reason, properties=None):
        self.connected = not getattr(reason, "is_failure", False)
        if self.connected:
            for t in self.TOPICS:
                client.subscribe(t, qos=1)

    def _on_disconnect(self, *args):
        self.connected = False


# ---------- the Pilot 2 setup page ----------

PILOT_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Security · Dock setup</title>
<style>body{margin:0;padding:24px;background:#03101a;color:#cfeeff;font:16px Arial,sans-serif}h1{font-size:22px;margin:0 0 6px}
.s{margin:10px 0;padding:12px 14px;border:1px solid #155879;border-radius:6px;background:#05131d}.ok{color:#26ee89}.bad{color:#ff7b86}
button{font-size:16px;padding:10px 18px;border-radius:6px;border:1px solid #45d0ff;background:#25c7ff;color:#02131d;font-weight:bold}</style></head>
<body><h1>AI Security · __SITE__</h1><div>Connects this controller, and the dock it is set up with, to this site's AI Security PC.</div>
<div class="s" id="lic">1. Cloud API keys: …</div><div class="s" id="mqtt">2. Connection to the PC (__HOST__): …</div>
<p><button onclick="go()">Connect again</button></p>
<script>
const CFG=__CFG__;
function set(id,ok,text){const e=document.getElementById(id);e.className='s '+(ok?'ok':'bad');e.textContent=text}
function bridge(){return window.djiBridge}
function go(){const b=bridge();
  if(!b){set('lic',false,'Open this page in DJI Pilot 2 (Cloud Service → Open Platform) on the controller.');return}
  try{b.platformVerifyLicense(CFG.app_id,CFG.app_key,CFG.app_license);
    const ok=String(b.platformIsVerified()).indexOf('true')>=0;
    set('lic',ok,ok?'1. Cloud API keys: accepted':'1. Cloud API keys: refused. Check the App ID, App Key and App License on the PC.');
    if(!ok)return;
    b.platformSetWorkspaceId(CFG.workspace_id);
    b.platformSetInformation('AI Security',CFG.site,'AI Security Command Center');
    b.platformLoadComponent('thing',JSON.stringify({host:CFG.mqtt,username:CFG.user,passwd:CFG.password,connectCallback:'onThing'}));
    set('mqtt',true,'2. Connection to the PC: connecting…')}catch(e){set('lic',false,'Setup failed: '+e)}}
window.onThing=function(arg){const ok=String(arg).indexOf('true')>=0||String(arg)==='1';
  set('mqtt',ok,ok?'2. Connected to the PC. The dock now shows on the Drone page under DJI Docks; register it there.':'2. Could not connect to the PC. Same network? Is AI Security running?')};
go();
</script></body></html>"""


def pilot_page(store, creds, host, site="this site"):
    c = store.cloud()
    cfg = {"app_id": c["app_id"], "app_key": c["app_key"], "app_license": c["app_license"],
           "workspace_id": store.data["workspace_id"], "site": site, "mqtt": f"tcp://{host}:{BROKER_PORT}",
           "user": creds["dock_user"], "password": creds["dock_password"]}
    safe = json.dumps(cfg).replace("<", "\\u003c")
    esc = lambda v: str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    return PILOT_PAGE.replace("__CFG__", safe).replace("__SITE__", esc(site)).replace("__HOST__", esc(host))


def start_pilot_server(store, creds_fn, host_fn, site_fn=lambda: "this site", port=PILOT_PAGE_PORT, bind="0.0.0.0"):
    """A tiny LAN web server with one page: /pilot?k=<secret>. Everything else, or a wrong secret, is 404."""
    import hmac
    import urllib.parse
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urllib.parse.urlparse(self.path)
            if url.path.startswith("/wayline/") and url.path.endswith(".kmz"):
                item = _waylines.get(url.path[len("/wayline/"):-4])
                if not item or item[1] < time.time():
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.google-earth.kmz")
                self.send_header("Content-Length", str(len(item[0])))
                self.end_headers()
                self.wfile.write(item[0])
                return
            key = (urllib.parse.parse_qs(url.query).get("k") or [""])[0]
            if url.path != "/pilot" or not hmac.compare_digest(key.encode(), str(store.data.get("bind_token") or "").encode()):
                self.send_error(404)
                return
            body = pilot_page(store, creds_fn(), host_fn(), site_fn()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="dock-pilot-page", daemon=True).start()
    return server


# ---------- small file helpers ----------

def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    _write_text(path, json.dumps(data, indent=2))


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _write_text(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    for attempt in range(5):  # Windows: antivirus or a reader can hold the file for a moment
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2)


def _write_if_changed(path, text):
    if _read_text(path) != text:
        _write_text(path, text)
