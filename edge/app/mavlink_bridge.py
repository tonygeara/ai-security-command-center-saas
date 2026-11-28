"""MAVLink drones (PX4, ArduPilot and other MAVLink autopilots) as Drone Link drones.

A MavlinkDrone connects to the aircraft over MAVLink (UDP or TCP: a telemetry radio, a companion computer, a network
link or a simulator) and to this PC's drone link exactly like the Drone Link phone app does. So routes, patrols, drone
responses, the backup drone, Run patrol, the detector and the map work with these drones without anything else changing.

What it does on the aircraft: arm and take off, fly to a point (MAV_CMD_DO_REPOSITION, on both PX4 and ArduPilot),
hold position, return to launch, land, camera photo/video and gimbal pitch (when the aircraft has them). Keyboard and
gamepad flying works on ArduPilot (GUIDED velocity); on PX4 use the routes and fly-to-a-point. If the link to the PC
drops, the aircraft's own failsafe (configured on the autopilot) applies.
"""
import hashlib
import hmac
import json
import math
import socket
import threading
import time

from geo import _distance_m

host = None  # the dashboard module; set by dashboard.py

AUTOPILOTS = {3: "ArduPilot", 12: "PX4"}
VEHICLES = {1: "fixed-wing", 2: "quadcopter", 3: "coaxial", 4: "helicopter", 13: "hexacopter", 14: "octocopter",
            15: "tricopter", 19: "VTOL", 20: "VTOL", 21: "VTOL", 22: "VTOL", 23: "VTOL", 24: "VTOL", 25: "VTOL", 29: "dodecacopter",
            10: "ground rover", 11: "surface boat", 12: "submarine"}  # ground and water vehicles: listed on Add Robot → Others
DEFAULT_SCAN_PORTS = (14550, 14540, 14551, 14560)


def describe(autopilot, vehicle_type):
    """A model line from a HEARTBEAT, e.g. "ArduPilot quadcopter"."""
    return f"{AUTOPILOTS.get(autopilot, 'MAVLink autopilot')} {VEHICLES.get(vehicle_type, 'aircraft')}"


def _mav():
    from pymavlink import mavutil  # imported when first used: only PCs with MAVLink drones need it
    return mavutil


def _sender(c):
    """The address a UDP aircraft sends from (pymavlink keeps the latest one per listening socket)."""
    seen = getattr(c, "clients_last_alive", None) or {}
    if seen:
        a = max(seen, key=seen.get)
        return "%s:%s" % a
    a = getattr(c, "last_address", None)
    return "%s:%s" % a if a else ""


def scan(ports=DEFAULT_SCAN_PORTS, seconds=6.0, busy=()):
    """Listen for MAVLink aircraft announcing themselves (HEARTBEAT) on these UDP ports. "Others": finds the drone and
    its model. Returns [{"connection", "port", "sysid", "autopilot", "vehicle", "model", "address"}]."""
    mavutil = _mav()
    found, conns = {}, []
    for port in ports:
        if port in busy:
            continue
        try:
            conns.append((port, mavutil.mavlink_connection(f"udpin:0.0.0.0:{port}", source_system=255)))
        except OSError:
            pass
    end = time.time() + seconds
    try:
        while time.time() < end:
            for port, c in conns:
                m = c.recv_match(type="HEARTBEAT", blocking=False)
                while m is not None:
                    if m.type != 6 and m.autopilot != 8:  # not a ground station, not "no autopilot"
                        key = (port, m.get_srcSystem())
                        found[key] = {"connection": f"udpin:0.0.0.0:{port}", "port": port, "sysid": m.get_srcSystem(),
                                      "autopilot": AUTOPILOTS.get(m.autopilot, f"autopilot {m.autopilot}"),
                                      "vehicle": VEHICLES.get(m.type, f"type {m.type}"), "model": describe(m.autopilot, m.type),
                                      "address": _sender(c)}
                    m = c.recv_match(type="HEARTBEAT", blocking=False)
            time.sleep(0.05)
    finally:
        for _, c in conns:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
    return list(found.values())


class MavlinkDrone:
    """One MAVLink aircraft, linked to the PC like a Drone Link phone."""
    ARRIVE_M = 3.0

    def __init__(self, slot, connection, name=""):
        self.slot, self.connection, self.name = slot, connection, name
        self.stop, self.sock, self.mav, self.lock = False, None, None, threading.Lock()
        self.tel = {}            # the latest values from the aircraft
        self.autopilot = None    # 3 ArduPilot, 12 PX4
        self.vehicle_type = None
        self.armed = False
        self.mode = ""
        self.mission = None      # our fly-to-a-point state, reported like the phone app's auto-fly
        self.lost_link = ""
        self.control_pc, self.stick, self.stick_at = False, (0.0, 0.0, 0.0, 0.0), 0.0
        self.heard_at = 0.0
        self.acks = {}           # command id -> result
        self.error = ""

    # ----- start / stop -----
    def start(self):
        threading.Thread(target=self._mav_loop, daemon=True).start()
        threading.Thread(target=self._link_loop, daemon=True).start()
        threading.Thread(target=self._mission_loop, daemon=True).start()

    def close(self):
        self.stop = True
        self._close()
        try:
            if self.mav:
                self.mav.close()
        except Exception:  # noqa: BLE001
            pass

    @property
    def model(self):
        return describe(self.autopilot, self.vehicle_type) if self.autopilot is not None else ""

    @property
    def is_px4(self):
        return self.autopilot == 12

    def connected(self):
        return time.time() - self.heard_at < 5

    # ----- MAVLink side -----
    def _mav_loop(self):
        mavutil = _mav()
        last_hb = 0.0
        while not self.stop:
            try:
                if self.mav is None:
                    self.mav = mavutil.mavlink_connection(self.connection, source_system=255, source_component=190)
                    self.error = ""
                if time.time() - last_hb >= 1.0:  # a ground station's heartbeat: autopilots expect one
                    last_hb = time.time()
                    self.mav.mav.heartbeat_send(6, 8, 0, 0, 4)
                m = self.mav.recv_match(blocking=True, timeout=0.5)
                if m is not None:
                    self._on_message(m)
            except Exception as e:  # noqa: BLE001 - a broken link: try again
                self.error = f"MAVLink connection: {e}"
                try:
                    if self.mav:
                        self.mav.close()
                except Exception:  # noqa: BLE001
                    pass
                self.mav = None
                time.sleep(2)

    def _on_message(self, m):
        t = m.get_type()
        if t == "HEARTBEAT":
            if m.type == 6 or m.autopilot == 8:
                return  # another ground station
            self.heard_at = time.time()
            self.autopilot, self.vehicle_type = m.autopilot, m.type
            self.armed = bool(m.base_mode & 128)
            try:
                self.mode = _mav().mode_string_v10(m)
            except Exception:  # noqa: BLE001
                self.mode = str(m.custom_mode)
        elif t == "GLOBAL_POSITION_INT":
            self.tel.update(lat=m.lat / 1e7, lon=m.lon / 1e7, alt=m.relative_alt / 1000.0, alt_msl=m.alt / 1000.0,
                            speed=math.hypot(m.vx, m.vy) / 100.0, vz=-m.vz / 100.0,
                            heading=(m.hdg / 100.0) if m.hdg != 65535 else self.tel.get("heading", 0.0))
            if "home_lat" not in self.tel and self.armed is False:
                self.tel.update(home_lat=self.tel["lat"], home_lon=self.tel["lon"])  # until HOME_POSITION arrives
        elif t == "HOME_POSITION":
            self.tel.update(home_lat=m.latitude / 1e7, home_lon=m.longitude / 1e7)
        elif t == "SYS_STATUS":
            if m.battery_remaining >= 0:
                self.tel["battery"] = int(m.battery_remaining)
        elif t == "BATTERY_STATUS":
            if m.battery_remaining >= 0:
                self.tel["battery"] = int(m.battery_remaining)
        elif t == "GPS_RAW_INT":
            self.tel["sats"] = m.satellites_visible
        elif t == "EXTENDED_SYS_STATE":
            self.tel["landed_state"] = m.landed_state  # 1 on ground, 2 in air, 3 taking off, 4 landing
        elif t == "COMMAND_ACK":
            self.acks[m.command] = (m.result, time.time())
        elif t == "STATUSTEXT":
            text = getattr(m, "text", "")
            if isinstance(text, bytes):
                text = text.decode("utf-8", "replace")
            self.event(text.strip("\x00").strip()[:120])

    def flying(self):
        ls = self.tel.get("landed_state")
        if ls in (2, 3, 4):
            return True
        if ls == 1:
            return False
        return self.armed and self.tel.get("alt", 0) > 0.5

    def _cmd(self, command, params=(0, 0, 0, 0, 0, 0, 0), wait=3.0):
        """COMMAND_LONG and its COMMAND_ACK. Returns (ok, error)."""
        if self.mav is None or not self.connected():
            return False, "The aircraft is not connected (no MAVLink heartbeat)."
        self.acks.pop(command, None)
        p = list(params) + [0] * (7 - len(params))
        self.mav.mav.command_long_send(self.mav.target_system or 1, self.mav.target_component or 1, command, 0, *p)
        end = time.time() + wait
        while time.time() < end:
            r = self.acks.get(command)
            if r:
                res = r[0]
                if res in (0, 5):  # accepted, in progress
                    return True, ""
                names = {1: "temporarily rejected", 2: "denied", 3: "not supported", 4: "failed"}
                return False, f"The aircraft {names.get(res, 'refused')} the command."
            time.sleep(0.05)
        return False, "The aircraft did not answer."

    def _reposition(self, lat, lon, alt, speed=-1):
        """Fly to a point and hold there (DO_REPOSITION, PX4 and ArduPilot)."""
        if self.mav is None or not self.connected():
            return False, "The aircraft is not connected (no MAVLink heartbeat)."
        mavutil = _mav()
        if not self.is_px4 and self.mode != "GUIDED":
            self._set_mode("GUIDED")
        self.acks.pop(192, None)
        self.mav.mav.command_int_send(self.mav.target_system or 1, self.mav.target_component or 1,
                                      mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, 192, 0, 0,
                                      float(speed), 1, 0, float("nan"), int(lat * 1e7), int(lon * 1e7), float(alt))
        end = time.time() + 3
        while time.time() < end:
            r = self.acks.get(192)
            if r:
                return (r[0] in (0, 5)), ("" if r[0] in (0, 5) else "The aircraft refused to fly to that point.")
            time.sleep(0.05)
        return True, ""  # some autopilots don't acknowledge COMMAND_INT: the position shows whether it went

    def _set_mode(self, name):
        try:
            self.mav.set_mode(name)
            return True
        except Exception:  # noqa: BLE001 - a mode this autopilot doesn't have
            return False

    def _takeoff(self, alt):
        if not self.is_px4:
            self._set_mode("GUIDED")
        if not self.armed:
            ok, err = self._cmd(400, (1,))  # MAV_CMD_COMPONENT_ARM_DISARM
            if not ok:
                return False, "Arming refused: " + err
        if self.is_px4:  # PX4's take-off height is above sea level
            ground = self.tel.get("alt_msl", 0.0) - self.tel.get("alt", 0.0)
            return self._cmd(22, (-1, 0, 0, float("nan"), float("nan"), float("nan"), ground + alt))
        return self._cmd(22, (0, 0, 0, 0, 0, 0, alt))

    # ----- the PC's Drone Link side (same protocol as the phone app) -----
    def _link_loop(self):
        while not self.stop:
            linked = False
            try:
                s = socket.create_connection(("127.0.0.1", host.DRONE_LINK_PORT), timeout=5)
                reader = s.makefile("r", encoding="utf-8", newline="\n")
                nonce = json.loads(reader.readline() or "{}").get("nonce", "")
                mac = hmac.new(host.drone_link_token(slot=self.slot).encode(), nonce.encode(), hashlib.sha256).hexdigest()
                s.sendall((json.dumps({"t": "hello", "mac": mac, "device": f"MAVLink bridge ({self.model or 'waiting for the aircraft'})",
                                       "app": "mavlink"}) + "\n").encode())
                s.settimeout(None)
                self.sock, linked = s, True
                threading.Thread(target=self._tel_loop, args=(s,), daemon=True).start()
                for line in reader:
                    if self.stop or self.sock is None:
                        break
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if msg.get("t") == "denied":
                        time.sleep(30)
                        break
                    if msg.get("t") == "stick":
                        self._sticks(msg)
                    elif msg.get("t") == "cmd":
                        threading.Thread(target=self._answer, args=(msg,), daemon=True).start()
            except (OSError, ValueError):
                pass
            if linked:
                self._link_lost()
            self._close()
            time.sleep(2)

    def _answer(self, msg):
        with self.lock:
            try:
                ok, err = self._command(str(msg.get("cmd")), msg.get("args") or {})
            except Exception as e:  # noqa: BLE001
                ok, err = False, f"MAVLink: {e}"
        self._send({"t": "ack", "id": msg.get("id"), "ok": ok, "error": err})

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
        if text:
            self._send({"t": "event", "msg": f"[MAVLink] {text}"})

    def _link_lost(self):
        """The PC link dropped during an auto-fly: do its lost-link action, like the phone app."""
        act, self.lost_link = self.lost_link, ""
        if self.mission or self.control_pc:
            self.mission, self.control_pc = None, False
            if self.flying() and act == "home":
                self._cmd(20)
            elif self.flying() and act == "land":
                self._cmd(21)

    def _tel_loop(self, s):
        while not self.stop and self.sock is s:
            self._send(self.telemetry())
            time.sleep(0.2)

    def telemetry(self):
        t = {"t": "tel", "mavlink": True, "sdk_registered": True, "drone_connected": self.connected(),
             "control": "PC" if (self.control_pc or self.mission) else "PILOT", "simulator": False, "streaming": False,
             "model": self.model, "autopilot_mode": self.mode}
        if not self.connected() or "lat" not in self.tel:
            return t
        m = self.mission
        if m:
            t["mission"] = {k: m[k] for k in ("state", "lat", "lon", "alt", "speed", "arrive", "distance")}
        mode = {"RTL": "GO_HOME", "AUTO.RTL": "GO_HOME", "LAND": "AUTO_LANDING", "AUTO.LAND": "AUTO_LANDING",
                "TAKEOFF": "AUTO_TAKE_OFF", "AUTO.TAKEOFF": "AUTO_TAKE_OFF"}.get(self.mode, "GPS_NORMAL")
        home = (self.tel.get("home_lat"), self.tel.get("home_lon"))
        t.update({"lat": round(self.tel["lat"], 7), "lon": round(self.tel["lon"], 7), "altitude": round(self.tel.get("alt", 0), 2),
                  "heading": round(self.tel.get("heading", 0), 1), "speed": round(self.tel.get("speed", 0), 2),
                  "vertical_speed": round(self.tel.get("vz", 0), 2), "battery": self.tel.get("battery"),
                  "gps_satellites": self.tel.get("sats"), "flying": self.flying(), "motors_on": self.armed, "flight_mode": mode,
                  "landing_confirm_needed": False, "signal": 100 if self.connected() else 0})
        if None not in home:
            t.update(home_lat=home[0], home_lon=home[1], distance_home=round(_distance_m(home[0], home[1], self.tel["lat"], self.tel["lon"]), 1))
        return t

    # ----- commands from the PC -----
    def _command(self, cmd, args):
        if cmd in ("hover", "control_off", "land", "go_home", "goto_cancel"):
            self.lost_link = ""
        if cmd == "takeoff":
            if self.flying():
                return False, "Already flying."
            return self._takeoff(10.0)
        if cmd == "land":
            self.mission = None
            return self._cmd(21)  # MAV_CMD_NAV_LAND (here)
        if cmd == "go_home":
            self.mission = None
            return self._cmd(20)  # MAV_CMD_NAV_RETURN_TO_LAUNCH
        if cmd in ("hover", "goto_cancel"):
            self.mission = None
            if self.flying() and "lat" in self.tel:
                return self._reposition(self.tel["lat"], self.tel["lon"], self.tel.get("alt", 10))
            return True, ""
        if cmd in ("cancel_land", "cancel_go_home"):
            self.mission = None
            if "lat" in self.tel:
                return self._reposition(self.tel["lat"], self.tel["lon"], max(5.0, self.tel.get("alt", 10)))
            return False, "No position yet."
        if cmd == "confirm_land":
            return False, "No landing confirmation is needed."
        if cmd == "goto":
            try:
                lat, lon = float(args["lat"]), float(args["lon"])
            except (KeyError, TypeError, ValueError):
                return False, "No target."
            alt = max(5.0, min(120.0, float(args.get("alt") or 30)))
            self.mission = {"state": "CRUISE" if self.flying() else "TAKING_OFF", "lat": lat, "lon": lon, "alt": alt,
                            "speed": max(1.0, min(15.0, float(args.get("speed") or 5))),
                            "arrive": args.get("arrive") if args.get("arrive") in ("hover", "land", "home") else "hover",
                            "distance": -1, "arrived_at": 0.0, "sent": False}
            self.lost_link = args.get("lost_link") if args.get("lost_link") in ("home", "hover", "land") else ""
            if not self.flying():
                ok, err = self._takeoff(alt)
                if not ok:
                    self.mission = None
                    return False, err
            return True, ""
        if cmd == "control_on":
            if self.is_px4:
                return False, "Keyboard and gamepad flying isn't available for PX4 drones yet: use routes and fly-to-a-point."
            if not self._set_mode("GUIDED"):
                return False, "The aircraft didn't switch to GUIDED."
            self.control_pc, self.stick_at = True, time.time()
            return True, ""
        if cmd == "control_off":
            self.control_pc, self.stick = False, (0.0, 0.0, 0.0, 0.0)
            return True, ""
        if cmd == "gimbal":
            return self._cmd(205, (max(-90.0, min(30.0, float(args.get("pitch") or 0))), 0, 0, 0, 0, 0, 2))  # DO_MOUNT_CONTROL
        if cmd == "photo":
            return self._cmd(2000, (0, 0, 1, 0))  # IMAGE_START_CAPTURE, one picture
        if cmd == "record_start":
            return self._cmd(2500)  # VIDEO_START_CAPTURE
        if cmd == "record_stop":
            return self._cmd(2501)  # VIDEO_STOP_CAPTURE
        if cmd in ("sim_on", "sim_off", "stream_on", "stream_off"):
            return True, ""  # video: the aircraft's camera stream is added as a camera source
        return False, "Unknown command."

    def _sticks(self, msg):
        vals = tuple(max(-1.0, min(1.0, float(msg.get(k) or 0))) for k in "xyzr")
        if self.mission and any(abs(v) > 0.05 for v in vals):
            self.mission = None
        if self.control_pc and self.mav is not None:
            x, y, z, r = vals
            speed = 5.0
            # Body-frame velocity (forward, right, down) and yaw rate: ArduPilot GUIDED.
            self.mav.mav.set_position_target_local_ned_send(0, self.mav.target_system or 1, self.mav.target_component or 1,
                                                            8, 0b0000010111000111, 0, 0, 0, y * speed, x * speed, -z * 2.0,
                                                            0, 0, 0, 0, math.radians(r * 60))

    def _mission_loop(self):
        """Our fly-to-a-point: after take-off, send the point; report the distance; on arrival, do the arrive action."""
        while not self.stop:
            time.sleep(0.3)
            m = self.mission
            if not m or "lat" not in self.tel:
                continue
            try:
                if m["state"] == "TAKING_OFF":
                    if self.tel.get("alt", 0) >= min(m["alt"], 10.0) - 1.5:
                        m["state"] = "CRUISE"
                    continue
                if m["state"] == "CRUISE" and not m["sent"]:
                    ok, err = self._reposition(m["lat"], m["lon"], m["alt"], m["speed"])
                    m["sent"] = True
                    if not ok:
                        self.event(err)
                        self.mission = None
                        continue
                dist = _distance_m(self.tel["lat"], self.tel["lon"], m["lat"], m["lon"])
                m["distance"] = round(dist, 1)
                if m["state"] == "CRUISE" and dist < self.ARRIVE_M:
                    m["state"], m["arrived_at"] = "ARRIVED", time.time()
                    self.event("Auto-fly: arrived")
                if m["state"] == "ARRIVED" and time.time() - m["arrived_at"] >= 2.0:
                    self.mission = None
                    if m["arrive"] == "land":
                        self._cmd(21)
                    elif m["arrive"] == "home":
                        self._cmd(20)
            except Exception as e:  # noqa: BLE001
                self.event(f"Auto-fly error: {e}")

    def summary(self):
        link = host.get_link(self.slot)
        return {"drone": self.slot, "label": host.drone_label(self.slot), "name": self.name, "connection": self.connection,
                "model": self.model, "aircraft_connected": self.connected(), "linked": link["conn"] is not None,
                "armed": self.armed, "mode": self.mode, "flying": self.flying(), "battery": self.tel.get("battery"),
                "lat": self.tel.get("lat"), "lon": self.tel.get("lon"), "error": self.error}
