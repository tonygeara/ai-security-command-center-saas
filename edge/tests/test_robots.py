"""Add Robot: the robots that can be connected (on request), and Others (finding a robot on the network)."""
import os
import socket
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import robotscan  # noqa: E402


def spdp_packet(name="unitree_go2", vendor=0x0110):
    """A minimal RTPS SPDP packet (little-endian) with a participant name, as a ROS 2 robot sends."""
    name_b = name.encode() + b"\0"
    pad = (4 - len(name_b) % 4) % 4
    params = struct.pack("<HHI", 0x0062, 4 + len(name_b) + pad, len(name_b)) + name_b + b"\0" * pad + struct.pack("<HH", 1, 0)
    payload = b"\x00\x03\x00\x00" + params  # PL_CDR_LE
    data_sub = struct.pack("<HH", 0, 16) + b"\0" * 4 + b"\0\x01\x00\xc2" + struct.pack("<ii", 0, 1) + payload
    sub = bytes([0x15, 0x05]) + struct.pack("<H", len(data_sub)) + data_sub
    return b"RTPS" + bytes([2, 3]) + struct.pack(">H", vendor) + bytes(range(12)) + sub


def test_rtps_announcement_is_read():
    vendor, guid, name = robotscan.parse_rtps(spdp_packet())
    assert vendor == "Eclipse Cyclone DDS" and guid == bytes(range(12)).hex() and name == "unitree_go2"
    assert robotscan.parse_rtps(b"not rtps at all") is None
    assert robotscan.parse_rtps(spdp_packet(vendor=0x010F))[0] == "eProsima Fast DDS"
    assert robotscan.parse_rtps(b"RTPS" + bytes(16) + b"\x15\x05\xff\xff")[2] == ""  # broken: no name, no crash


def test_knock_finds_what_answers():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        out = robotscan.knock([("127.0.0.1", port, "Test robot"), ("127.0.0.1", 1, "Nothing here")], timeout=0.3, controls=[])
        assert out == [{"address": "127.0.0.1", "port": port, "guess": "Test robot"}]
        # A network that answers for any address (here: the "control" address answers too) proves nothing.
        assert robotscan.knock([("127.0.0.1", port, "Test robot")], timeout=0.3, controls=[("127.0.0.1", port)]) == []
    finally:
        srv.close()


def test_scan_puts_everything_in_one_list(monkeypatch):
    monkeypatch.setattr(robotscan, "scan_dds", lambda seconds: [{"address": "192.168.1.50", "vendor": "Eclipse Cyclone DDS",
                                                                  "guid": "ab", "name": "go2_driver"}])
    monkeypatch.setattr(robotscan, "knock", lambda: [{"address": "192.168.80.3", "port": 443, "guess": "Boston Dynamics Spot"}])
    mav = lambda s: [{"model": "ArduPilot ground rover", "sysid": 1, "port": 14550, "address": "192.168.1.60:14550"}]
    out = robotscan.scan(mav, seconds=0.1)
    assert [x["kind"] for x in out] == ["ros2", "mavlink", "address"]
    assert out[0]["label"] == "go2_driver" and "Eclipse Cyclone DDS" in out[0]["details"]
    assert out[1]["label"] == "ArduPilot ground rover" and "possibly a Boston Dynamics Spot" in out[2]["details"]


def test_add_robot_page_list_requests_and_permissions(d, client, monkeypatch):
    kinds = client.get("/api/robot/kinds").get_json()
    keys = [k["k"] for k in kinds["kinds"]]
    assert "spot" in keys and "unitree_humanoid" in keys and "tug" in keys and keys[-1] == "others" and len(keys) >= 18
    assert kinds["groups"][0] == "Robot dogs" and kinds["groups"][-1] == "Others"
    monkeypatch.setattr(d.robotscan, "scan", lambda mav, seconds=6.0: [{"kind": "ros2", "label": "go2_driver", "address": "192.168.1.50",
                                                                       "details": "ROS 2 / DDS (Eclipse Cyclone DDS) at 192.168.1.50"}])
    found = client.post("/api/robot/scan").get_json()["found"]
    assert found[0]["label"] == "go2_driver"
    r = client.post("/api/robot/integration-request", json={"kind": "spot", "email": "me@site.example", "details": "2 dogs"}).get_json()
    assert r["ok"] and "Boston Dynamics Spot" in r["message"]  # on-prem in tests: noted, not sent
    r = client.post("/api/robot/integration-request", json={"kind": "found", "device": found[0], "email": "me@site.example"}).get_json()
    assert r["ok"] and "go2_driver" in r["message"]
    assert client.post("/api/robot/integration-request", json={"kind": "spot", "email": "nope"}).status_code == 400
    assert client.post("/api/robot/integration-request", json={"kind": "toaster", "email": "me@site.example"}).status_code == 400
    reqs = client.get("/api/robot/requests").get_json()["requests"]
    assert reqs[0]["label"].startswith("Found on the network: go2_driver") and "Found by the PC" in reqs[0]["details"]
    html = client.get("/robot-add").get_data(as_text=True)
    assert "Add a robot" in html and "function scan()" in html and "Connect this robot" in html
    assert "location.href='/robot-add'" in client.get("/drone-control").get_data(as_text=True)
    assert 'id="addRobotBtn"' in client.get("/").get_data(as_text=True)
    import users
    assert not users.allowed("operator", "POST", "/api/robot/scan") and not users.allowed("operator", "POST", "/api/robot/integration-request")
    assert users.allowed("viewer", "GET", "/api/robot/kinds")
