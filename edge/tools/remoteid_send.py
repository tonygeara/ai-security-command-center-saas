"""Pretend to be a Remote ID receiver: send a drone's broadcasts to the PC, to test the Detector drones tab.

A drone with Remote ID ID flies in a straight line from START to END (lat,lon) at HEIGHT metres, with its pilot standing
at START, and the PC is told every second, by UDP (Detector drones → Remote ID receivers → "Listen on UDP" on) or HTTP
(with the receiver token, from the same panel, admins).

  python remoteid_send.py --pc 192.168.1.20 --udp 47911 --start 33.8960,35.5018 --end 33.8938,35.5018
  python remoteid_send.py --pc 127.0.0.1:8080 --token <receiver token> --start ... --end ...

Only for testing your own system. Real receivers send the same kind of JSON.
"""
import argparse
import json
import socket
import time
import urllib.request


def point(s):
    lat, lon = (float(v) for v in s.split(","))
    return lat, lon


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pc", required=True, help="the PC's address (host for UDP, host:port for HTTP)")
    ap.add_argument("--udp", type=int, help="UDP port (as set on the Detector drones tab)")
    ap.add_argument("--token", help="receiver token (HTTP)")
    ap.add_argument("--start", type=point, required=True, help="lat,lon where the drone starts (and the pilot stands)")
    ap.add_argument("--end", type=point, required=True, help="lat,lon where it flies to")
    ap.add_argument("--id", default="TEST-RID-0001", help="the drone's Remote ID")
    ap.add_argument("--height", type=float, default=60)
    ap.add_argument("--seconds", type=int, default=60, help="how long the flight takes")
    a = ap.parse_args()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if a.udp else None
    for i in range(a.seconds + 1):
        f = i / max(1, a.seconds)
        msg = {"id": a.id, "lat": a.start[0] + (a.end[0] - a.start[0]) * f, "lon": a.start[1] + (a.end[1] - a.start[1]) * f,
               "alt": a.height, "speed": 5, "operator_lat": a.start[0], "operator_lon": a.start[1]}
        data = json.dumps(msg).encode()
        if sock:
            sock.sendto(data, (a.pc, a.udp))
        else:
            req = urllib.request.Request(f"http://{a.pc}/api/remoteid/report", data=data, method="POST",
                                         headers={"Content-Type": "application/json", "X-RemoteID-Token": a.token or ""})
            print(urllib.request.urlopen(req, timeout=5).read().decode())
        print(f"{i:3d}s  {msg['lat']:.6f}, {msg['lon']:.6f}")
        time.sleep(1)


if __name__ == "__main__":
    main()
