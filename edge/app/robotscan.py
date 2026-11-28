"""Add Robot → Others: find robots on the site network so a connection can be requested for them.

Listening only (plus a quick TCP knock at a few makers' usual addresses); nothing is sent to a robot and nothing moves.
- ROS 2 / DDS: ROS 2 robots (Unitree Go2 / B2 / G1 / H1 and most research and service robots) announce themselves
  with RTPS "SPDP" packets on multicast 239.255.0.1:7400 (DDS domain 0) every few seconds.
- MAVLink ground vehicles: ArduPilot / PX4 rovers, boats and submarines send HEARTBEATs like drones do.
- Usual addresses: Boston Dynamics Spot answers on 192.168.80.3 (its Wi-Fi) or 10.0.0.3 (its Ethernet) port 443;
  a Unitree robot's own network uses 192.168.123.161 (Ethernet) or 192.168.12.1 (its Wi-Fi hotspot).
"""
import socket
import struct
import threading
import time

SPDP_GROUP, SPDP_PORT = "239.255.0.1", 7400
# RTPS vendor IDs (OMG registry) of the DDS libraries robots use.
DDS_VENDORS = {0x0101: "RTI Connext DDS", 0x0102: "OpenSplice DDS", 0x0103: "OpenDDS", 0x010F: "eProsima Fast DDS",
               0x0110: "Eclipse Cyclone DDS", 0x0112: "Eclipse Cyclone DDS", 0x0113: "GurumNetworks GurumDDS",
               0x0116: "Eclipse Zenoh / DDS"}
ROVER_TYPES = {10: "ground rover", 11: "surface boat", 12: "submarine"}
KNOWN_ADDRESSES = [  # (address, port, what usually answers there)
    ("192.168.80.3", 443, "Boston Dynamics Spot (its usual Wi-Fi address)"),
    ("10.0.0.3", 443, "Boston Dynamics Spot (its usual Ethernet address)"),
    ("192.168.123.161", 22, "Unitree robot (Go2 / B2 / G1 / H1: its usual Ethernet address)"),
    ("192.168.12.1", 22, "Unitree robot (its usual Wi-Fi hotspot address)"),
]
PID_ENTITY_NAME = 0x0062


def parse_rtps(data):
    """(vendor name, GUID prefix hex, participant name or "") from an RTPS packet, or None if it is not RTPS."""
    if len(data) < 20 or data[:4] != b"RTPS":
        return None
    vendor = struct.unpack(">H", data[6:8])[0]
    guid = data[8:20].hex()
    return DDS_VENDORS.get(vendor, f"DDS vendor {vendor:#06x}"), guid, _participant_name(data)


def _participant_name(data):
    """The participant's name from an SPDP DATA submessage (PID_ENTITY_NAME), best effort."""
    try:
        pos = 20
        while pos + 4 <= len(data):
            sid, flags, length = data[pos], data[pos + 1], 0
            little = flags & 1
            length = struct.unpack("<H" if little else ">H", data[pos + 2:pos + 4])[0]
            body = data[pos + 4:pos + 4 + length] if length else data[pos + 4:]
            if sid == 0x15 and len(body) > 24:  # DATA: extraFlags(2) octetsToInlineQos(2) readerId(4) writerId(4) seq(8)
                q = 4 + struct.unpack("<H" if little else ">H", body[2:4])[0]
                payload = body[q:]
                if len(payload) > 4:
                    pl_little = payload[1] in (0x01, 0x03)  # CDR_LE / PL_CDR_LE
                    p = 4
                    while p + 4 <= len(payload):
                        pid, plen = struct.unpack("<HH" if pl_little else ">HH", payload[p:p + 4])
                        if pid == 1:  # PID_SENTINEL
                            break
                        if pid == PID_ENTITY_NAME and plen >= 4:
                            n = struct.unpack("<I" if pl_little else ">I", payload[p + 4:p + 8])[0]
                            return payload[p + 8:p + 8 + n].split(b"\0", 1)[0].decode("utf-8", "replace")[:80]
                        p += 4 + plen
            if not length:
                break
            pos += 4 + length
    except (struct.error, IndexError, ValueError):
        pass
    return ""


def scan_dds(seconds=6.0):
    """ROS 2 / DDS participants announcing themselves on domain 0: [{"address", "vendor", "guid", "name"}]."""
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", SPDP_PORT))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(SPDP_GROUP) + socket.inet_aton("0.0.0.0"))
        s.settimeout(0.3)
        end = time.time() + seconds
        while time.time() < end:
            try:
                data, (addr, _port) = s.recvfrom(65535)
            except socket.timeout:
                continue
            r = parse_rtps(data)
            if r:
                vendor, guid, name = r
                key = guid[:16]  # one robot's participants share the host part of the GUID prefix
                x = found.setdefault(key, {"address": addr, "vendor": vendor, "guid": guid, "names": []})
                if name and name not in x["names"]:
                    x["names"].append(name)
    except OSError:
        pass  # no network, or the port is held by another program: nothing found this way
    finally:
        s.close()
    return [{"address": x["address"], "vendor": x["vendor"], "guid": x["guid"], "name": ", ".join(x["names"][:3])}
            for x in found.values()]


# Addresses that never exist (TEST-NET-2 and -3, RFC 5737): if one "answers", this network (a proxy or firewall) accepts
# every connection, so an answer at a robot's usual address proves nothing. A neighbour of each usual address that is
# almost never used (.249) is knocked too, for networks that only answer for their own private ranges.
CONTROL_ADDRESSES = [("198.51.100.7", 443), ("203.0.113.9", 443)]


def _controls(addresses):
    near = {(a.rsplit(".", 1)[0] + ".249", p) for a, p, _g in addresses}
    return CONTROL_ADDRESSES + sorted(near)


def _answers(addr, port, timeout):
    """True when something really listens there. Port 22 must also greet like SSH (a Unitree robot's computer)."""
    try:
        with socket.create_connection((addr, port), timeout=timeout) as c:
            if port != 22:
                return True
            c.settimeout(timeout + 0.6)
            return c.recv(64).startswith(b"SSH-")
    except OSError:
        return False


def knock(addresses=KNOWN_ADDRESSES, timeout=0.6, controls=None):
    """Which makers' usual addresses answer: [{"address", "port", "guess"}]. Nothing if the network answers for any address
    (controls: addresses that must not answer; default: never-used and neighbour addresses; [] to skip the check)."""
    out, lock = [], threading.Lock()
    controls = _controls(addresses) if controls is None else controls
    hits = []

    def ctl(addr, port):
        if _answers(addr, port, timeout):
            hits.append(addr)
    ts = [threading.Thread(target=ctl, args=c, daemon=True) for c in controls]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout + 1.5)
    if hits:
        return []

    def one(addr, port, guess):
        if _answers(addr, port, timeout):
            with lock:
                out.append({"address": addr, "port": port, "guess": guess})
    threads = [threading.Thread(target=one, args=a, daemon=True) for a in addresses]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout + 0.5)
    return out


def scan(mavlink_scan=None, seconds=6.0):
    """Everything found, as one list of {"kind", "label", "address", "details"} (DDS, MAVLink ground vehicles,
    usual addresses), all at once in about `seconds`."""
    results = {"dds": [], "mav": [], "knock": []}
    jobs = [threading.Thread(target=lambda: results.__setitem__("dds", scan_dds(seconds)), daemon=True),
            threading.Thread(target=lambda: results.__setitem__("knock", knock()), daemon=True)]
    if mavlink_scan:
        jobs.append(threading.Thread(target=lambda: results.__setitem__("mav", mavlink_scan(seconds)), daemon=True))
    for t in jobs:
        t.start()
    for t in jobs:
        t.join(seconds + 3)
    out = []
    for x in results["dds"]:
        out.append({"kind": "ros2", "label": x["name"] or "ROS 2 / DDS robot", "address": x["address"],
                    "details": f"ROS 2 / DDS ({x['vendor']}) at {x['address']}" + (f", nodes: {x['name']}" if x["name"] else "")})
    for x in results["mav"]:
        out.append({"kind": "mavlink", "label": x.get("model") or "MAVLink ground vehicle", "address": x.get("address") or "",
                    "details": f"MAVLink {x.get('model', '')} (system {x.get('sysid')}) on UDP port {x.get('port')}"
                               + (f" from {x['address']}" if x.get("address") else "")})
    for x in results["knock"]:
        out.append({"kind": "address", "label": x["guess"], "address": x["address"],
                    "details": f"Something answers at {x['address']} port {x['port']}: possibly a {x['guess']}"})
    return out
