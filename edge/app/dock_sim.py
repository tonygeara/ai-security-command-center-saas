"""A simulated DJI Dock with its drone, for tests, training and demos (no broker or hardware needed).

It sends the hub what a real dock sends over MQTT (DJI Cloud API): its topology (update_topo, with the drone in it),
dock telemetry (cover, weather, drone charging) and the drone's telemetry, once a second, and takes the hub's
replies. It flies the flight plans the PC sends (Phase 3): it downloads the KMZ, takes off, flies the waypoints
(hovering where the plan says), reports flighttask_progress, returns to the dock and lands. speedup makes tests quick.

model "dock4" is a DJI Dock 4 with a Matrice 5TD: an O4 ground station is the gateway (sn) with the dock (sn-DOCK)
and the drone behind it, as DJI's Cloud API documents. It doesn't charge the drone: after landing below 79% it swaps
in the fullest battery from its bays (25 s) and charges the old one there; manual_battery_swap does it on demand.
"""
import math
import random
import threading
import time
import uuid

MODELS = {  # simulated model -> (dock domain, type, sub_type), (drone domain, type, sub_type)
    "dock3": ((3, 3, 0), (0, 100, 1)),   # Dock 3 with Matrice 4TD
    "dock2": ((3, 2, 0), (0, 91, 1)),    # Dock 2 with Matrice 3TD
    "dock4": ((8, 135, 0), (0, 130, 0)),  # O4 ground station (gateway) with Dock 4 and Matrice 5TD behind it
}
DOCK4 = (9, 131, 0)
SWAP_SECONDS = 25      # Dock 4 battery swap
SWAP_BELOW = 79        # Dock 4 swaps by itself after landing below this %
DRONE_CAMERA = {"dock3": "99-0-0", "dock2": "99-0-0", "dock4": "122-0-0"}


class SimulatedDock:
    def __init__(self, sn, send, home, model="dock3", period=1.0):
        self.sn = sn
        self.drone_sn = sn + "-UAV"
        self.send = send            # send(topic, dict): into the hub
        self.home = (float(home[0]), float(home[1]))
        self.model = model if model in MODELS else "dock3"
        self.dock_sn = sn + "-DOCK" if self.model == "dock4" else sn   # the dock's own sn (Dock 4: behind the gateway)
        self.bays = [96.0, 71.0, None, None] if self.model == "dock4" else []  # Dock 4: 4 bays, 2 batteries besides the drone's
        self.swaps = 0
        self.swap = None            # (ends at, slot) while swapping
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
        # V11.12: look at, aim, thermal, orbit, emergency stop, siren and floodlight
        self.ground = 50.0          # ellipsoid height of the ground at the dock (m)
        self.looked_at = None       # (lat, lon) of the last look-at
        self.aimed = None           # (x, y) of the last aim
        self.ir = {"mode": 0, "x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2}
        self.siren = False
        self.light = False
        self.stopped = False        # emergency stop received

    def _msg(self, method=None, data=None, **extra):
        return {"tid": str(uuid.uuid4()), "bid": str(uuid.uuid4()), "timestamp": int(time.time() * 1000),
                **({"method": method} if method else {}), "data": data or {}, **extra}

    def topology(self):
        (dd, dt, ds), (ud, ut, us) = MODELS[self.model]
        subs = [{"sn": self.drone_sn, "domain": ud, "type": ut, "sub_type": us, "index": "A",
                 "device_secret": "sim", "nonce": "sim", "version": "1.0.0"}]
        if self.model == "dock4":
            subs.append({"sn": self.dock_sn, "domain": DOCK4[0], "type": DOCK4[1], "sub_type": DOCK4[2],
                         "device_secret": "sim", "nonce": "sim", "thing_version": "1.3.0"})
        self.send(f"sys/product/{self.sn}/status", self._msg("update_topo", {
            "domain": dd, "type": dt, "sub_type": ds, "version": "1.0.0", "device_secret": "sim", "nonce": "sim",
            "sub_devices": subs}))

    def go_offline(self):
        self.send(f"sys/product/{self.sn}/status", self._msg("update_topo", {}))

    def capacity(self):
        """What it can stream (DJI live_capacity): the drone's camera with wide/zoom/thermal, and the dock's own camera."""
        self.send(f"thing/product/{self.sn}/state", self._msg(data={"live_capacity": {
            "available_video_number": 2, "coexist_video_number_max": 1, "device_list": [
                {"sn": self.drone_sn, "available_video_number": 1, "coexist_video_number_max": 1, "camera_list": [
                    {"camera_index": DRONE_CAMERA[self.model], "available_video_number": 1, "coexist_video_number_max": 1,
                     "video_list": [{"video_index": "normal-0", "video_type": "normal", "switchable_video_types": ["wide", "zoom", "ir"]}]}]},
                {"sn": self.dock_sn, "available_video_number": 1, "coexist_video_number_max": 1, "camera_list": [
                    {"camera_index": "165-0-7", "available_video_number": 1, "coexist_video_number_max": 1,
                     "video_list": [{"video_index": "normal-0", "video_type": "normal", "switchable_video_types": []}]}]}]}}))

    def osd(self):
        f = self.fault
        swap4 = self.model == "dock4"
        if f == "battery":
            self.battery, charging = 12.0, False
            self.bays = [10.0 if b is not None else None for b in self.bays]
        elif swap4:  # Dock 4 doesn't charge the drone; it charges the batteries in its bays
            charging = False
            self.bays = [min(100.0, b + 0.5 * self.speedup) if b is not None else None for b in self.bays]
        else:
            charging = self.battery < 100
            self.battery = min(100.0, self.battery + 0.5)
        out = self.flight is not None
        if out:
            self.battery, charging = max(5.0, self.battery - 0.3), False
        if self.swap and time.time() >= self.swap[0]:
            self._finish_swap()
        if swap4:
            self.send(f"thing/product/{self.sn}/osd", self._msg(data={  # the ground station: the dock's position
                "mode_code": 4 if out else 0, "basestation_work_mode": 1, "latitude": self.home[0], "longitude": self.home[1],
                "height": self.ground,
                "network_state": {"type": 2, "quality": 5, "rate": 12000}}))
        extra = {"battery_swap_times": self.swaps, "battery_system": {
            "total_slots": len(self.bays), "present_count": sum(b is not None for b in self.bays),
            "slots": [{"slot_id": i, "pack_presence": 0 if b is None else 4 if b >= 100 else 2,
                       **({} if b is None else {"capacity_percent": int(b), "soh_percent": 98, "battery_sn": f"SIMBAT{i}"})}
                      for i, b in enumerate(self.bays, 1)]}} if swap4 else {"latitude": self.home[0], "longitude": self.home[1], "height": self.ground}
        self.send(f"thing/product/{self.dock_sn}/osd", self._msg(data={
            "mode_code": 8 if self.swap else 4 if out else 0, "cover_state": 3 if f == "cover" else 1 if out else 0,
            "drone_in_dock": 0 if out else 1, **extra, "alarm_state": int(self.siren), "supplement_light_state": int(self.light),
            "environment_temperature": 47.5 if f == "hot" else round(24 + random.uniform(-0.3, 0.3), 1), "temperature": 28.0,
            "wind_speed": 14.2 if f == "wind" else round(random.uniform(1.0, 3.5), 1), "rainfall": 3 if f == "rain" else 0,
            "network_state": {"type": 2, "quality": 5, "rate": 12000},
            "drone_charge_state": {"state": 1 if charging else 0, "capacity_percent": int(self.battery)}}))
        self.send(f"thing/product/{self.drone_sn}/osd", self._msg(data={
            "mode_code": (9 if self.flight["phase"] == "returning" else 5) if out else 14,
            "latitude": self.pos[0], "longitude": self.pos[1], "height": round(self.ground + self.height, 1), "elevation": round(self.height, 1),
            "horizontal_speed": 0, "vertical_speed": 0, "attitude_head": 0, "cameras": [self.camera_state()],
            "battery": {"capacity_percent": int(self.battery), "remain_flight_time": int(self.battery * 0.4 * 60)}}))

    def camera_state(self):
        """The drone camera's telemetry: thermal readings while measuring (a warm spot where it last looked or aimed)."""
        warm = 36.4 if (self.looked_at or self.aimed) else 21.0
        m = self.ir["mode"]
        return {"payload_index": DRONE_CAMERA[self.model], "camera_mode": 0, "ir_metering_mode": m,
                "thermal_global_temperature_min": 18.5, "thermal_global_temperature_max": max(warm, 24.0),
                **({"ir_metering_point": {"x": self.ir["x"], "y": self.ir["y"], "temperature": warm}} if m == 1 else {}),
                **({"ir_metering_area": {"x": self.ir["x"], "y": self.ir["y"], "width": self.ir["w"], "height": self.ir["h"],
                                         "aver_temperature": round((warm + 19.0) / 2, 1),
                                         "max_temperature_point": {"x": 0.5, "y": 0.5, "temperature": warm},
                                         "min_temperature_point": {"x": 0.1, "y": 0.1, "temperature": 19.0}}} if m == 2 else {})}

    def hms(self):
        """A DJI health message about the dock, repeated while it lasts, as real docks do."""
        dd, dt, ds = DOCK4 if self.model == "dock4" else MODELS[self.model][0]
        self.send(f"thing/product/{self.dock_sn}/events", self._msg("hms", {"list": [
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
        if f["phase"] == "orbit":
            o = f["orbit"]
            o["angle"] += o["speed"] * self.period * self.speedup / max(5.0, o["radius"])
            lat, lon = o["center"]
            self.pos = (lat + o["radius"] * math.cos(o["angle"]) / 111320.0,
                        lon + o["radius"] * math.sin(o["angle"]) / (111320.0 * math.cos(math.radians(lat))))
            self.send(f"thing/product/{self.sn}/events", self._msg("poi_status_notify", {
                "status": "in_progress", "reason": 0, "circle_radius": o["radius"], "circle_speed": o["speed"], "max_circle_speed": 10}))
        if f["phase"] == "manual" and self.stick and time.time() - self.stick[0] < 0.5:
            _, x, y, z, _r = self.stick
            m = 10.0 * self.period * self.speedup  # m per tick at full stick
            self.pos = (self.pos[0] + y * m / 111320.0, self.pos[1] + x * m / (111320.0 * math.cos(math.radians(self.pos[0]))))
            self.height = max(5.0, min(120.0, self.height + z * 3.0 * self.period * self.speedup))
        if f["phase"] == "returning" and self._move_to(self.home, step):
            self.height, self.pos = 0.0, self.home
            self.progress(100, f["status"])
            self.flight = None
            if self.model == "dock4" and self.battery < SWAP_BELOW:
                self.start_swap()
            return
        if f["phase"] in ("goto", "holding", "manual", "orbit"):
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

    def start_swap(self, slot=None):
        """Dock 4: swap the drone's battery for the fullest one in the bays (or this slot's). False if it can't."""
        if self.flight or self.swap or self.model != "dock4":
            return False
        full = [(b, i) for i, b in enumerate(self.bays, 1) if b is not None and (slot is None or i == slot)]
        if not full:
            return False
        self.swap = (time.time() + SWAP_SECONDS / self.speedup, max(full)[1])
        return True

    def _finish_swap(self):
        _, slot = self.swap
        self.battery, self.bays[slot - 1] = self.bays[slot - 1], self.battery
        self.swaps += 1
        self.swap = None

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
            elif payload.get("method") == "drone_emergency_stop" and self.flight:
                self.stopped, self.stick = True, None
                self.flight["phase"] = "holding"
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
            elif method == "payload_authority_grab":
                result = 0 if self.flight else 319002
            elif method == "flight_authority_grab":
                result = 0 if self.drc else 319002
                if self.drc:
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
            elif method == "camera_look_at":
                if not self.flight or float(data.get("height") or 0) < 2:
                    result = 319003
                else:
                    self.looked_at = (data.get("latitude"), data.get("longitude"))
            elif method == "camera_aim":
                if not self.flight:
                    result = 319003
                else:
                    self.aimed = (data.get("x"), data.get("y"))
            elif method == "ir_metering_mode_set":
                self.ir["mode"] = int(data.get("mode") or 0)
            elif method == "ir_metering_point_set":
                self.ir.update(x=data.get("x"), y=data.get("y"))
            elif method == "ir_metering_area_set":
                self.ir.update(x=data.get("x"), y=data.get("y"), w=data.get("width"), h=data.get("height"))
            elif method == "poi_mode_enter":
                if self.model != "dock4":
                    result = 314000  # Dock 2/3 don't have it
                elif not self.flight:
                    result = 314004
                else:
                    c = (float(data["latitude"]), float(data["longitude"]))
                    dn = (self.pos[0] - c[0]) * 111320.0
                    de = (self.pos[1] - c[1]) * 111320.0 * math.cos(math.radians(c[0]))
                    self.flight.update(phase="orbit", orbit={"center": c, "radius": math.hypot(dn, de), "speed": 3.0,
                                                             "angle": math.atan2(de, dn)})
            elif method == "poi_circle_speed_set":
                if self.flight and self.flight.get("orbit"):
                    self.flight["orbit"]["speed"] = float(data.get("circle_speed") or 3.0)
            elif method == "poi_mode_exit":
                if self.flight and self.flight["phase"] == "orbit":
                    self.flight["phase"] = "holding"
                    self.send(f"thing/product/{self.sn}/events", self._msg("poi_status_notify", {"status": "ok", "reason": 0}))
            elif method == "emergency_stop":
                if self.model != "dock4":
                    result = 314000
                elif self.flight:
                    self.stopped = True
                    self.flight["phase"] = "holding"
            elif method == "alarm_state_switch":
                self.siren = bool(data.get("action"))
            elif method in ("supplement_light_open", "supplement_light_close"):
                self.light = method.endswith("open")
            elif method == "manual_battery_swap":
                ok = self.start_swap(int(data.get("slot_id") or 0) or None)
                self.send(topic + "_reply", {"tid": payload.get("tid"), "bid": payload.get("bid"), "method": method,
                                             "timestamp": int(time.time() * 1000),
                                             "data": {"result": 0, "device_sn": self.dock_sn,
                                                      "output": {"status": "in_progress" if ok else "failed"}}})
                return
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
