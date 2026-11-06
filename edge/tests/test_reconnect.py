"""Changing Wi-Fi or router: every camera and recorder is found again by its MAC; drone phones find the PC again."""
import hashlib
import hmac
import json
import os
import socket
import time

import pytest
import yaml

NVR = "rtsp://admin:p%40ss@192.168.1.30:554/cam/realmonitor?channel={ch}&subtype=0"
CONFIG = {
    "cameras": {"front": {"ffmpeg": {"inputs": [{"path": "rtsp://127.0.0.1:8554/front"}]}}},
    "go2rtc": {"streams": {
        "front": ["rtsp://user:secret@192.168.1.20:554/stream1"],
        "gate": [NVR.format(ch=1)], "yard": [NVR.format(ch=2)],
        "drone": ["rtsp://127.0.0.1:8556/drone"],
        "shed": ["rtsp://user:pw@192.168.1.40:554/live"],  # never seen online: must not be searched for
    }}}
MACS = {"192.168.1.20": "aa-aa-aa-aa-aa-01", "192.168.1.30": "aa-aa-aa-aa-aa-02"}


@pytest.fixture
def lan(d, tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    world = {"net": {"gateway": "192.168.1.1", "network": "192.168.1.0/24"}, "addr": dict(MACS), "online": True,
             "restarts": 0, "sweeps": 0, "frigate_ok": True, "probes": []}
    monkeypatch.setattr(d, "RECOVERY_STATE_PATH", str(tmp_path / "recovery.json"))
    monkeypatch.setattr(d, "_frigate_config_path", lambda: str(cfg_file))
    monkeypatch.setattr(d, "_network_signature", lambda: dict(world["net"]))
    monkeypatch.setattr(d, "_ip_on_active_lan", lambda ip: ip.rsplit(".", 1)[0] + ".0/24" == world["net"]["network"])
    monkeypatch.setattr(d, "_neighbor_mac", lambda ip: world["addr"].get(ip))
    monkeypatch.setattr(d, "_port", lambda ip, port, t=.35: ip in world["addr"])
    monkeypatch.setattr(d, "frigate_camera_online", lambda camera=None: world["online"])

    def probe(url, timeout=4):
        world["probes"].append(url)
        host = url.split("@")[-1].split(":")[0]
        return host in world["addr"]
    monkeypatch.setattr(d, "_rtsp_auth_probe", probe)

    def sweep():
        world["sweeps"] += 1
        return {}, {ip: mac for ip, mac in world["addr"].items()}
    monkeypatch.setattr(d, "_arp_neighbors_on_active_lan", sweep)

    def restart():
        world["restarts"] += 1
        return True
    monkeypatch.setattr(d, "_docker_restart_frigate", restart)
    monkeypatch.setattr(d, "_wait_for_frigate", lambda timeout=45: world["frigate_ok"])
    monkeypatch.setattr(d, "run_background_command", lambda *a, **k: None)
    world["file"] = cfg_file
    return world


def streams(world):
    return yaml.safe_load(world["file"].read_text(encoding="utf-8"))["go2rtc"]["streams"]


def test_every_camera_and_recorder_follows_a_new_router(d, lan):
    r = d._recover_all()
    assert r["cameras"] == {"front": "online", "gate": "online", "yard": "online", "shed": "offline"}  # drone left out
    assert lan["restarts"] == 0 and lan["sweeps"] == 0
    # New router: new network, every device got a new DHCP address.
    lan["net"] = {"gateway": "10.0.0.1", "network": "10.0.0.0/24"}
    lan["addr"] = {"10.0.0.5": MACS["192.168.1.20"], "10.0.0.9": MACS["192.168.1.30"], "10.0.0.77": "bb-bb-bb-bb-bb-bb"}
    lan["online"] = False
    r = d._recover_all()
    assert r["moved"] == ["front", "gate", "yard"] and lan["restarts"] == 1 and lan["sweeps"] == 1  # one sweep, one restart
    s = streams(lan)
    assert s["front"] == ["rtsp://user:secret@10.0.0.5:554/stream1"]
    assert s["gate"] == ["rtsp://admin:p%40ss@10.0.0.9:554/cam/realmonitor?channel=1&subtype=0"]
    assert s["yard"] == ["rtsp://admin:p%40ss@10.0.0.9:554/cam/realmonitor?channel=2&subtype=0"]
    assert s["drone"] == ["rtsp://127.0.0.1:8556/drone"] and s["shed"] == CONFIG["go2rtc"]["streams"]["shed"]
    assert not any("10.0.0.77" in u or "192.168.1.40" in u for u in lan["probes"])  # passwords never sent to strangers
    st = d._load_recovery_state()["cameras"]
    assert st["front"]["status"] == "reconnected" and st["yard"]["last_ip"] == "10.0.0.9"
    assert "Add it again" in st["shed"]["note"]
    # Next pass: all fine at the new addresses, nothing rewritten.
    lan["online"] = True
    assert d._recover_all()["moved"] == [] and lan["restarts"] == 1


def test_a_failed_restart_puts_the_old_addresses_back(d, lan):
    d._recover_all()
    lan["net"] = {"gateway": "10.0.0.1", "network": "10.0.0.0/24"}
    lan["addr"] = {"10.0.0.5": MACS["192.168.1.20"]}
    lan["online"], lan["frigate_ok"] = False, False
    r = d._recover_all(only=["front"])
    assert r["cameras"]["front"] == "rollback"
    assert streams(lan)["front"] == CONFIG["go2rtc"]["streams"]["front"]
    assert d._recover_camera("nope")["ok"] is False


def test_drone_phone_finds_the_pc_again(d):
    token = d.drone_link_token(slot="drone")
    tid = hashlib.sha256(token.encode()).hexdigest()[:16]
    ask = json.dumps({"t": "where", "id": tid, "nonce": "0123456789abcdef"}).encode()
    ans = json.loads(d.discovery_answer(ask, "192.168.5.20", local_ip="192.168.5.10"))
    assert ans["host"] == "192.168.5.10" and ans["port"] == d.DRONE_LINK_PORT
    assert ans["sig"] == hmac.new(token.encode(), f"here|0123456789abcdef|192.168.5.10|{d.DRONE_LINK_PORT}".encode(), hashlib.sha256).hexdigest()
    assert d.discovery_answer(json.dumps({"t": "where", "id": "0" * 16, "nonce": "0123456789abcdef"}).encode(), "1.2.3.4") is None
    assert d.discovery_answer(b"not json", "1.2.3.4") is None
    assert d.discovery_answer(json.dumps({"t": "where", "id": tid}).encode(), "1.2.3.4") is None  # no nonce: no answer
    # the real UDP service started with the drone link answers over the network
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(3)
        s.sendto(ask, ("127.0.0.1", d.DRONE_DISCOVERY_PORT))
        reply = json.loads(s.recvfrom(2048)[0])
    assert reply["t"] == "here" and reply["host"] == "127.0.0.1"
