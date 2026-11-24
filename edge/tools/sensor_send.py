"""Pretend to be acoustic and RF drone sensors: send what they "hear" to the PC, to test the Detector drones tab.

A drone flies in a straight line from START to END (lat,lon). Each sensor given with --sensor NAME@lat,lon[@kind] reports
every second the direction it hears the drone from (and, for RF, a radio link), as long as the drone is within --range
metres of it. Make detectors with the same names on the Detector drones tab and set their type (Acoustic sensor or
RF sensor); where two sensors' directions cross, the drone is located on the map.

  python sensor_send.py --pc 192.168.1.20 --udp 47911 --start 33.8960,35.5000 --end 33.8930,35.5040 \\
      --sensor "North mast@33.8950,35.4990@acoustic" --sensor "East mast@33.8945,35.5060@rf"
  python sensor_send.py --pc 127.0.0.1:8080 --token <receiver token> ...

Sends by UDP (Detector drones → Remote ID receivers → "Listen on UDP" on, same port) or HTTP (with the receiver token,
admins see it there). Only for testing your own system. Real sensors send the same kind of JSON.
"""
import argparse
import json
import math
import random
import socket
import time
import urllib.request

M = 111320.0


def point(s):
    lat, lon = (float(v) for v in s.split(","))
    return lat, lon


def sensor(s):
    parts = s.split("@")
    if len(parts) < 2:
        raise argparse.ArgumentTypeError("use NAME@lat,lon[@acoustic|rf]")
    return {"name": parts[0], "pos": point(parts[1]), "kind": parts[2] if len(parts) > 2 else "acoustic"}


def bearing_and_distance(a, b):
    dn = (b[0] - a[0]) * M
    de = (b[1] - a[1]) * M * math.cos(math.radians(a[0]))
    return math.degrees(math.atan2(de, dn)) % 360, math.hypot(dn, de)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pc", required=True, help="the PC's address (host for UDP, host:port for HTTP)")
    ap.add_argument("--udp", type=int, help="UDP port (as set on the Detector drones tab)")
    ap.add_argument("--token", help="receiver token (HTTP)")
    ap.add_argument("--start", type=point, required=True, help="lat,lon where the drone starts")
    ap.add_argument("--end", type=point, required=True, help="lat,lon where it flies to")
    ap.add_argument("--sensor", type=sensor, action="append", required=True, help="NAME@lat,lon[@acoustic|rf] (repeat)")
    ap.add_argument("--range", type=float, default=800, help="how far the sensors hear the drone (metres)")
    ap.add_argument("--noise", type=float, default=2.0, help="direction error, degrees (random)")
    ap.add_argument("--seconds", type=int, default=60, help="how long the flight takes")
    a = ap.parse_args()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if a.udp else None
    for i in range(a.seconds + 1):
        f = i / max(1, a.seconds)
        drone = (a.start[0] + (a.end[0] - a.start[0]) * f, a.start[1] + (a.end[1] - a.start[1]) * f)
        msgs = []
        for s in a.sensor:
            b, dist = bearing_and_distance(s["pos"], drone)
            heard = dist <= a.range
            m = {"sensor": s["name"], "detected": heard}
            if heard:
                m.update(confidence=round(max(0.5, 0.97 - dist / a.range * 0.4), 2), bearing=round((b + random.uniform(-a.noise, a.noise)) % 360, 1),
                         type="quadcopter")
                if s["kind"] == "rf":
                    m.update(protocol="OcuSync", freq_mhz=2440, rssi_dbm=round(-40 - dist / 20, 1))
            msgs.append(m)
        data = json.dumps({"detections": msgs}).encode()
        if sock:
            sock.sendto(data, (a.pc, a.udp))
        else:
            req = urllib.request.Request(f"http://{a.pc}/api/sensors/report", data=data, method="POST",
                                         headers={"Content-Type": "application/json", "X-Sensor-Token": a.token or ""})
            print(urllib.request.urlopen(req, timeout=5).read().decode())
        print(f"{i:3d}s  drone {drone[0]:.6f}, {drone[1]:.6f}  " + "  ".join(
            f"{m['sensor']}: {m.get('bearing', '-')}" for m in msgs))
        time.sleep(1)


if __name__ == "__main__":
    main()
