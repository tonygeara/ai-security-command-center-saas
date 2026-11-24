"""A tiny MAVLink aircraft for the tests: announces itself like an ArduPilot (or PX4) quadcopter, arms, takes off,
flies to DO_REPOSITION points, returns to launch, lands, and answers commands with COMMAND_ACK."""
import math
import socket
import threading
import time

from pymavlink.dialects.v20 import ardupilotmega as mavlink2

M = 1 / 111320.0
GUIDED, RTL, LAND, LOITER = 4, 6, 9, 5


class _Link:
    """A MAVLink 2 link over its own UDP socket on an ephemeral port. (pymavlink's udpout binds the destination port on
    Windows, which clashes with the PC listening on that port when both run on one machine, as in these tests.)"""

    def __init__(self, port, source_system=1, source_component=1):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setblocking(False)
        self.dest = ("127.0.0.1", port)
        self.mav = mavlink2.MAVLink(self, srcSystem=source_system, srcComponent=source_component)
        self.mav.robust_parsing = True
        self.pending = []

    def write(self, data):
        try:
            self.sock.sendto(data, self.dest)
        except OSError:
            pass  # nobody listening yet (Windows reports it on the next call)

    def recv_match(self, blocking=False):
        while not self.pending:
            try:
                data = self.sock.recv(65535)
            except OSError:
                return None
            self.pending.extend(m for m in (self.mav.parse_buffer(data) or []) if m.get_type() != "BAD_DATA")
        return self.pending.pop(0)


class FakeAircraft:
    def __init__(self, port, home, autopilot=3, vehicle_type=2, speed=8.0):
        self.port, self.home = port, home
        self.autopilot, self.vehicle_type, self.speed = autopilot, vehicle_type, speed
        self.lat, self.lon, self.alt = home[0], home[1], 0.0
        self.armed, self.mode = False, 0
        self.target = None  # (lat, lon, alt)
        self.landing = False
        self.stop = False
        self.commands = []
        self.c = _Link(port)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _ack(self, command, result=0):
        self.c.mav.command_ack_send(command, result)

    def _handle(self, m):
        t = m.get_type()
        if t == "SET_MODE":
            self.mode = m.custom_mode
        elif t in ("COMMAND_LONG", "COMMAND_INT"):
            cmd = m.command
            self.commands.append(cmd)
            if cmd == 176:  # DO_SET_MODE
                self.mode = int(m.param2)
                self._ack(cmd)
            elif cmd == 400:  # arm
                self.armed = bool(m.param1)
                self._ack(cmd)
            elif cmd == 22:  # take-off
                if not self.armed:
                    self._ack(cmd, 4)
                    return
                self.target, self.landing = (self.lat, self.lon, float(m.param7)), False
                self._ack(cmd)
            elif cmd == 192:  # reposition (COMMAND_INT: x, y in 1e7 degrees)
                lat, lon = (m.x / 1e7, m.y / 1e7) if t == "COMMAND_INT" else (m.param5, m.param6)
                self.target, self.landing, self.mode = (lat, lon, float(m.z if t == "COMMAND_INT" else m.param7)), False, GUIDED
                self._ack(cmd)
            elif cmd == 20:  # RTL
                self.mode, self.target, self.landing = RTL, (self.home[0], self.home[1], max(self.alt, 15.0)), False
                self._ack(cmd)
            elif cmd == 21:  # land here
                self.mode, self.target, self.landing = LAND, None, True
                self._ack(cmd)
            elif cmd in (2000, 2500, 2501, 205):
                self._ack(cmd, 3)  # no camera on this test aircraft
            else:
                self._ack(cmd, 3)

    def _step(self, dt):
        if not self.armed:
            return
        if self.landing:
            self.alt = max(0.0, self.alt - 2.0 * dt)
            if self.alt == 0.0:
                self.armed, self.landing = False, False
            return
        if self.target:
            lat, lon, alt = self.target
            self.alt += max(-3 * dt, min(3 * dt, alt - self.alt))
            dn, de = (lat - self.lat) / M, (lon - self.lon) / M * math.cos(math.radians(self.lat))
            d = math.hypot(dn, de)
            if d > 0.2 and self.alt > 1:
                step = min(d, self.speed * dt)
                self.lat += dn / d * step * M
                self.lon += de / d * step * M / math.cos(math.radians(self.lat))
            elif self.mode == RTL and d <= 0.2:
                self.landing = True

    def _run(self):
        last_hb = last_pos = 0.0
        dt = 0.05
        while not self.stop:
            m = self.c.recv_match(blocking=False)
            while m is not None:
                self._handle(m)
                m = self.c.recv_match(blocking=False)
            self._step(dt)
            now = time.time()
            if now - last_hb > 0.5:
                last_hb = now
                base = 1 | (128 if self.armed else 0)
                self.c.mav.heartbeat_send(self.vehicle_type, self.autopilot, base, self.mode, 4)
                self.c.mav.sys_status_send(0, 0, 0, 0, 12000, -1, 87, 0, 0, 0, 0, 0, 0)
                self.c.mav.gps_raw_int_send(0, 3, int(self.lat * 1e7), int(self.lon * 1e7), 0, 0, 0, 0, 0, 14)
                self.c.mav.extended_sys_state_send(0, 2 if self.armed and self.alt > 0.3 else 1)
                self.c.mav.home_position_send(int(self.home[0] * 1e7), int(self.home[1] * 1e7), 0, 0, 0, 0, [1, 0, 0, 0], 0, 0, 0)
            if now - last_pos > 0.2:
                last_pos = now
                self.c.mav.global_position_int_send(int(now * 1000) % 2**32, int(self.lat * 1e7), int(self.lon * 1e7),
                                                    int((100 + self.alt) * 1000), int(self.alt * 1000), 0, 0, 0, 0)
            time.sleep(dt)
