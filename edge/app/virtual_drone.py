"""A simulated DJI Mini-class drone and its phone, speaking the real Drone Link protocol (see the Virtual drones tab)."""
import json
import math
import socket
import threading
import time

from geo import _bearing_deg, _distance_m, _wrap180

host = None  # the dashboard module; set by dashboard.py


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
        self.lost_link = ""  # what to do by itself if the PC link drops during an auto-fly ('' = hand back and hover)

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
            linked = False
            try:
                s = socket.create_connection(("127.0.0.1", host.DRONE_LINK_PORT), timeout=5)
                reader = s.makefile("r", encoding="utf-8", newline="\n")
                nonce = json.loads(reader.readline() or "{}").get("nonce", "")
                mac = hmac.new(host.drone_link_token(slot=self.slot).encode(), nonce.encode(), hashlib.sha256).hexdigest()
                s.sendall((json.dumps({"t": "hello", "mac": mac, "device": "Virtual drone (simulator)", "app": "virtual"}) + "\n").encode())
                s.settimeout(None)
                self.sock, linked = s, True
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
            if linked:
                self._link_lost()
            self._close()
            time.sleep(2)

    def _link_lost(self):
        """Same as the phone app: the auto-fly's lost-link action, or hand control back to the pilot (hover)."""
        with self.lock:
            if not (self.mission or self.control_pc):
                return
            act, self.lost_link = self.lost_link, ""
            self.mission, self.control_pc, self.stick = None, False, (0.0, 0.0, 0.0, 0.0)
            if self.flying and act == "home":
                self.mode, self.rth_phase = "GO_HOME", "climb"
            elif self.flying and act == "land":
                self.mode, self.land_confirmed = "AUTO_LANDING", True
            self.last_lost_link = act or "hover"

    def _set_sticks(self, msg):
        vals = tuple(max(-1.0, min(1.0, float(msg.get(k) or 0))) for k in "xyzr")
        if self.mission and any(abs(v) > 0.05 for v in vals):
            self._abort("manual control")
            self.lost_link = ""
        if self.control_pc:
            self.stick, self.stick_at = vals, time.time()

    def _abort(self, why):
        if self.mission:
            self.mission = None
            self.event(f"Auto-fly stopped: {why}")

    def _command(self, cmd, args):
        if not self.powered:
            return False, "The drone is switched off."
        if cmd in ("hover", "control_off", "land", "go_home", "goto_cancel"):
            self.lost_link = ""  # the pilot / PC decided; no automatic lost-link action any more
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
            self.lost_link = args.get("lost_link") if args.get("lost_link") in ("home", "hover", "land") else ""
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
            if self.alt >= host.DRONE_LIMITS["max_altitude_m"] and z > 0:
                z = 0.0
            if self.alt <= 0.5 and z < 0:
                z = 0.0  # landing protection: sticks alone never put it on the ground
            if self.distance_home() >= host.DRONE_LIMITS["max_distance_m"] and (x or y):
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
        link = host.get_link(self.slot)
        return {"drone": self.slot, "label": host.drone_label(self.slot), "powered": self.powered, "linked": link["conn"] is not None,
                "link_down": time.time() < self.link_down_until, "flying": self.flying, "mode": self.mode,
                "battery": int(round(self.battery)), "altitude": round(self.alt, 1), "lat": self.lat, "lon": self.lon,
                "heading": self.heading, "home_lat": self.home[0], "home_lon": self.home[1], "gps_satellites": self.sats,
                "mission": (self.mission or {}).get("state", "")}
