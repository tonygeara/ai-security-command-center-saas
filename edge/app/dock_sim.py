"""A simulated DJI Dock with its drone, for tests, training and demos (no broker or hardware needed).

It sends the hub what a real dock sends over MQTT (DJI Cloud API): its topology (update_topo, with the drone in it),
dock telemetry (cover, weather, drone charging) and the drone's telemetry, once a second, and takes the hub's
replies. It flies the flight plans the PC sends (Phase 3): it downloads the KMZ, takes off, flies the waypoints
(hovering where the plan says), reports flighttask_progress, returns to the dock and lands. speedup makes tests quick.
"""
import math
import random
import threading
import time
import uuid

MODELS = {  # simulated model -> (dock domain, type, sub_type), (drone domain, type, sub_type)
    "dock3": ((3, 3, 0), (0, 100, 1)),   # Dock 3 with Matrice 4TD
    "dock2": ((3, 2, 0), (0, 91, 1)),    # Dock 2 with Matrice 3TD
}


class SimulatedDock:
    def __init__(self, sn, send, home, model="dock3", period=1.0):
        self.sn = sn
        self.drone_sn = sn + "-UAV"
        self.send = send            # send(topic, dict): into the hub
        self.home = (float(home[0]), float(home[1]))
        self.model = model if model in MODELS else "dock3"
        self.period = period
        self.battery = 64.0
        self.powered = True
        self.topo_acked = False
        self.streaming = None       # video_id the PC asked it to stream
        self.fault = ""             # test alerts: "", offline, cover, rain, wind, hot, battery, hms
        self.replies = []           # last replies from the hub (tests look at them)
        self.stop_event = threading.Event()
        self.thread = None
        # Flying (Phase 3)
        self.fetch = _fetch           # url -> bytes (the PC's flight plan download)
        self.speedup = 1.0            # tests fly faster
        self.plan = None              # {"flight_id", "points"} after flighttask_prepare
        self.flight = None            # {"flight_id", "points", "index", "phase", "hover_until", "status"} while out
        self.pos = self.home
        self.height = 0.0
        # Live control (Phase 4)
        self.drc = False
        self.stick = None            # (time, x, y, z, r) from the last stick_control
        self.photos = 0
        self.recording = False
        self.gimbal = -45

    def _msg(self, method=None, data=None, **extra):
        return {"tid": str(uuid.uuid4()), "bid": str(uuid.uuid4()), "timestamp": int(time.time() * 1000),
                **({"method": method} if method else {}), "data": data or {}, **extra}

    def topology(self):
        (dd, dt, ds), (ud, ut, us) = MODELS[self.model]
        self.send(f"sys/product/{self.sn}/status", self._msg("update_topo", {
            "domain": dd, "type": dt, "sub_type": ds, "version": "1.0.0", "device_secret": "sim", "nonce": "sim",
            "sub_devices": [{"sn": self.drone_sn, "domain": ud, "type": ut, "sub_type": us, "index": "A",
                             "device_secret": "sim", "nonce": "sim", "version": "1.0.0"}]}))

    def go_offline(self):
        self.send(f"sys/product/{self.sn}/status", self._msg("update_topo", {}))

    def capacity(self):
        """What it can stream (DJI live_capacity): the drone's camera with wide/zoom/thermal, and the dock's own camera."""
        self.send(f"thing/product/{self.sn}/state", self._msg(data={"live_capacity": {
            "available_video_number": 2, "coexist_video_number_max": 1, "device_list": [
                {"sn": self.drone_sn, "available_video_number": 1, "coexist_video_number_max": 1, "camera_list": [
                    {"camera_index": "99-0-0", "available_video_number": 1, "coexist_video_number_max": 1,
                     "video_list": [{"video_index": "normal-0", "video_type": "normal", "switchable_video_types": ["wide", "zoom", "ir"]}]}]},
                {"sn": self.sn, "available_video_number": 1, "coexist_video_number_max": 1, "camera_list": [
                    {"camera_index": "165-0-7", "available_video_number": 1, "coexist_video_number_max": 1,
                     "video_list": [{"video_index": "normal-0", "video_type": "normal", "switchable_video_types": []}]}]}]}}))

    def osd(self):
        f = self.fault
        if f == "battery":
            self.battery, charging = 12.0, False
        else:
            charging = self.battery < 100
            self.battery = min(100.0, self.battery + 0.5)
        out = self.flight is not None
        if out:
            self.battery, charging = max(5.0, self.battery - 0.3), False
        self.send(f"thing/product/{self.sn}/osd", self._msg(data={
            "mode_code": 4 if out else 0, "cover_state": 3 if f == "cover" else 1 if out else 0, "drone_in_dock": 0 if out else 1,
            "latitude": self.home[0], "longitude": self.home[1],
            "environment_temperature": 47.5 if f == "hot" else round(24 + random.uniform(-0.3, 0.3), 1), "temperature": 28.0,
            "wind_speed": 14.2 if f == "wind" else round(random.uniform(1.0, 3.5), 1), "rainfall": 3 if f == "rain" else 0,
            "network_state": {"type": 2, "quality": 5, "rate": 12000},
            "drone_charge_state": {"state": 1 if charging else 0, "capacity_percent": int(self.battery)}}))
        self.send(f"thing/product/{self.drone_sn}/osd", self._msg(data={
            "mode_code": (9 if self.flight["phase"] == "returning" else 5) if out else 14,
            "latitude": self.pos[0], "longitude": self.pos[1], "height": round(self.height, 1), "elevation": round(self.height, 1),
            "horizontal_speed": 0, "vertical_speed": 0, "attitude_head": 0,
            "battery": {"capacity_percent": int(self.battery), "remain_flight_time": int(self.battery * 0.4 * 60)}}))

    def hms(self):
        """A DJI health message about the dock, repeated while it lasts, as real docks do."""
        (dd, dt, ds), _ = MODELS[self.model]
        self.send(f"thing/product/{self.sn}/events", self._msg("hms", {"list": [
            {"level": 2, "module": 3, "in_the_sky": 0, "code": "0x19110000", "device_type": f"{dd}-{dt}-{ds}", "imminent": 0,
             "args": {"component_index": 0, "sensor_index": 0}}]}, need_reply=0))

    def fly(self):
        """One tick of flight: towards the next waypoint (or home), hovering where asked; progress to the PC."""
        f = self.flight
        pts = f["points"]
        step = (pts[0]["speed"] if pts else 5.0) * self.period * self.speedup
        if f["phase"] == "flying":
            self.height = pts[f["index"]]["alt"]
            if time.time() < f["hover_until"]:
                pass
            elif self._move_to((pts[f["index"]]["lat"], pts[f["index"]]["lon"]), step):
                hover = pts[f["index"]]["hover"]
                if hover and not f.get("hovered") == f["index"]:
                    f["hovered"] = f["index"]
                    f["hover_until"] = time.time() + hover / self.speedup
                elif f["index"] + 1 < len(pts):
                    f["index"] += 1
                else:
                    f.update(phase="returning", status="ok")
        if f["phase"] == "goto":
            lat, lon, h = f["goto"][0]
            self.height = h
            if self._move_to((lat, lon), f.get("goto_speed", 8.0) * self.period * self.speedup):
                f["goto"] = f["goto"][1:]
                if not f["goto"]:
                    f["phase"] = "holding"
        if f["phase"] == "manual" and self.stick and time.time() - self.stick[0] < 0.5:
            _, x, y, z, _r = self.stick
            m = 10.0 * self.period * self.speedup  # m per tick at full stick
            self.pos = (self.pos[0] + y * m / 111320.0, self.pos[1] + x * m / (111320.0 * math.cos(math.radians(self.pos[0]))))
            self.height = max(5.0, min(120.0, self.height + z * 3.0 * self.period * self.speedup))
        if f["phase"] == "returning" and self._move_to(self.home, step):
            self.height, self.pos = 0.0, self.home
            self.progress(100, f["status"])
            self.flight = None
            return
        if f["phase"] in ("goto", "holding", "manual"):
            return  # the route is paused while an operator flies it; no route progress
        pct = 99 if f["phase"] == "returning" else int(100 * f["index"] / max(1, len(pts)))
        self.progress(pct, "in_progress")

    def _move_to(self, target, step):
        lat, lon = self.pos
        dn = (target[0] - lat) * 111320.0
        de = (target[1] - lon) * 111320.0 * math.cos(math.radians(lat))
        d = math.hypot(dn, de)
        if d <= step:
            self.pos = target
            return True
        k = step / d
        self.pos = (lat + dn * k / 111320.0, lon + de * k / (111320.0 * math.cos(math.radians(lat))))
        return False

    def progress(self, percent, status):
        f = self.flight
        self.send(f"thing/product/{self.sn}/events", self._msg("flighttask_progress", {"result": 0, "output": {
            "ext": {"flight_id": f["flight_id"], "current_waypoint_index": f["index"], "wayline_mission_state": 5},
            "progress": {"current_step": 13 if f["phase"] == "returning" else 10, "percent": percent}, "status": status}},
            need_reply=1))

    def upload_photo(self):
        """Like a real dock after a photo: ask where to upload, upload it (signed S3 PUT), report it to the PC."""
        try:
            import dock_media
            self.storage = None
            self.send(f"thing/product/{self.sn}/requests", self._msg("storage_config_get", {"module": 0}))
            cfg = self.storage
            if not cfg:
                return
            name = f"DJI_{self.photos:04d}.jpg"
            key = f"{cfg['object_key_prefix']}/{(self.flight or {}).get('flight_id') or 'manual'}/{name}"
            url = f"{cfg['endpoint']}/{cfg['bucket']}/{key}"
            body = b"\xff\xd8\xff\xe0 simulated photo " + name.encode()
            cred = cfg["credentials"]
            import urllib.request
            req = urllib.request.Request(url, data=body, method="PUT",
                                         headers=dock_media.sign_headers(cred["access_key_id"], cred["access_key_secret"], "PUT", url, body))
            urllib.request.urlopen(req, timeout=10).read()
            self.send(f"thing/product/{self.sn}/events", self._msg("file_upload_callback", {"file": {
                "object_key": key, "path": key.rsplit("/", 1)[0], "name": name,
                "ext": {"flight_id": (self.flight or {}).get("flight_id") or "", "is_original": True},
                "metadata": {"shoot_position": {"lat": self.pos[0], "lng": self.pos[1]}, "relative_altitude": self.height,
                             "created_time": time.strftime("%Y-%m-%dT%H:%M:%S")}}}, need_reply=1))
            self.uploaded = getattr(self, "uploaded", 0) + 1
        except Exception as e:  # noqa: BLE001
            self.upload_error = str(e)

    def set_fault(self, fault):
        """Test alerts on a simulated dock; "" clears. offline: the dock goes silent (no goodbye, like a power cut)."""
        self.fault = fault
        if fault != "offline":
            self.topo_acked = False  # back from silence: introduce itself again

    def on_message(self, topic, payload):
        self.replies = (self.replies + [(topic, payload)])[-20:]
        if topic.endswith("/requests_reply") and payload.get("method") == "storage_config_get":
            self.storage = (payload.get("data") or {}).get("output")
            return
        if topic.endswith("/drc/down"):
            if payload.get("method") == "stick_control" and self.drc:
                d = payload.get("data") or {}
                v = lambda k: (float(d.get(k, 1024)) - 1024) / 660.0  # noqa: E731
                self.stick = (time.time(), v("roll"), v("pitch"), v("throttle"), v("yaw"))
            return
        if topic.endswith("/services"):  # a command: say it's done (there is no real picture to send)
            method, data = payload.get("method"), payload.get("data") or {}
            result = 0
            if method == "flighttask_prepare":
                try:
                    import dock_wayline
                    pts = dock_wayline.read_kmz(self.fetch(data["file"]["url"]))
                    self.plan = {"flight_id": data.get("flight_id"), "points": pts}
                except Exception:  # noqa: BLE001 - like a dock that can't download or read the file
                    result = 314001
            elif method == "flighttask_execute":
                if self.flight or not self.plan or self.plan["flight_id"] != data.get("flight_id"):
                    result = 314002
                else:
                    self.flight = {**self.plan, "index": 0, "phase": "flying", "hover_until": 0.0, "status": "in_progress"}
                    self.plan = None
            elif method == "flighttask_undo":
                self.plan = None
            elif method == "flighttask_pause":
                if self.flight and self.flight["phase"] == "flying":
                    self.flight["phase"] = "holding"
            elif method == "fly_to_point":
                pts = data.get("points") or []
                if not self.flight or not pts:
                    result = 314004
                else:
                    self.flight.update(phase="goto", goto=[(p["latitude"], p["longitude"], p["height"]) for p in pts],
                                       goto_speed=float(data.get("max_speed") or 8))
            elif method == "fly_to_point_stop":
                if self.flight and self.flight["phase"] == "goto":
                    self.flight["phase"] = "holding"
            elif method == "drc_mode_enter":
                self.drc = bool(self.flight)
                result = 0 if self.flight else 319001
            elif method in ("flight_authority_grab", "payload_authority_grab"):
                result = 0 if self.drc else 319002
                if self.drc and method == "flight_authority_grab":
                    self.flight["phase"] = "manual"
            elif method == "drc_mode_exit":
                self.drc = False
                if self.flight and self.flight["phase"] == "manual":
                    self.flight["phase"] = "holding"
            elif method == "camera_photo_take":
                self.photos += 1
                threading.Thread(target=self.upload_photo, daemon=True).start()
            elif method in ("camera_recording_start", "camera_recording_stop"):
                self.recording = method.endswith("start")
            elif method == "gimbal_reset":
                self.gimbal = -90 if data.get("reset_mode") == 1 else 0
            elif method == "return_home":
                self.drc = False
                if self.flight:
                    self.flight.update(phase="returning", status="canceled")
                else:
                    result = 314003
            if method == "live_start_push":
                self.streaming = data.get("video_id")
            elif method == "live_stop_push":
                self.streaming = None
            self.send(topic + "_reply", {"tid": payload.get("tid"), "bid": payload.get("bid"), "method": method,
                                         "timestamp": int(time.time() * 1000), "data": {"result": result}})
            return
        if topic.endswith("/status_reply") and (payload.get("data") or {}).get("result") == 0:
            self.topo_acked = True

    def tick(self):
        if not self.powered or self.fault == "offline":
            return
        if not self.topo_acked:
            self.topology()
            self.capacity()
        if self.flight:
            self.fly()
        self.osd()
        if self.fault == "hms":
            self.hms()

    def start(self):
        self.thread = threading.Thread(target=self._run, name=f"sim-dock-{self.sn}", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def set_power(self, on):
        self.powered = bool(on)
        self.topo_acked = False
        if not on:
            self.go_offline()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - a demo must never take the dashboard down
                pass
            self.stop_event.wait(self.period)


def _fetch(url):
    import urllib.request
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read()
