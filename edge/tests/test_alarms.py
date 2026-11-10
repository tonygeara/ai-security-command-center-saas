"""Drone-verified alarms: SIA DC-09 encoding, the verification steps, and the dashboard end to end."""
import hashlib
import hmac
import http.server
import json
import os
import socket
import sys
import threading

import pytest

from conftest import APP, offset, wait_until

sys.path.insert(0, os.path.abspath(APP))
import alarm_verify  # noqa: E402
import sia_dc09  # noqa: E402


# ---- SIA DC-09 ----

def test_crc_and_frame():
    assert sia_dc09.crc16_arc(b"123456789") == 0xBB3D  # CRC-16/ARC check value
    msg = sia_dc09.body("1234", 130, zone=3, seq=7, receiver="R1", line="L2", now=0)
    assert msg == '"ADM-CID"0007RR1LL2#1234[#1234|1130 01 003]_00:00:00,01-01-1970'
    ok, back = sia_dc09.parse(sia_dc09.frame(msg))
    assert ok and back == msg
    bad = bytearray(sia_dc09.frame(msg)); bad[-3] ^= 1
    assert sia_dc09.parse(bytes(bad))[0] is False


def _receiver(answer="ACK"):
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    got = []

    def run():
        conn, _ = srv.accept()
        data = conn.recv(1024)
        ok, msg = sia_dc09.parse(data)
        got.append((ok, msg))
        conn.sendall(sia_dc09.frame(f'"{answer}"' + msg[9:13] + "L0#" + msg.split("#")[1].split("[")[0] + "[]_00:00:00,01-01-1970"))
        conn.close(); srv.close()
    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1], got


def test_send_to_a_receiver_needs_its_ack():
    port, got = _receiver("ACK")
    ok, _ = sia_dc09.send("127.0.0.1", port, "5678", 130, zone=2, seq=1)
    assert ok and got[0][0] and "|1130 01 002]" in got[0][1]
    port, _ = _receiver("NAK")
    assert sia_dc09.send("127.0.0.1", port, "5678", 130)[0] is False


# ---- the verification steps ----

class World:
    def __init__(self, **cfg):
        self.cfg = {**alarm_verify.DEFAULTS, "verified_alarms": True, "webhook_url": "https://centre.example/alarms",
                    "webhook_secret": "s3cret", "sia_host": "arc.example", "sia_port": 3061, "sia_account": "1234", **cfg}
        self.arrived_at, self.active = 0, True
        self.posts, self.sia, self.notes, self.asked, self.alerts = [], [], [], [], []
        self.v = alarm_verify.Verifier(
            settings=lambda: self.cfg, arrived=lambda d: self.arrived_at, drone_active=lambda d: self.active,
            snapshots=lambda c, d: (b"\xff\xd8cam", b"\xff\xd8drone"), publish=lambda k, **m: self.alerts.append(m),
            incident_note=lambda c, t, s, d: self.notes.append(t) or 7, audit=lambda *a: None,
            ask_operator=lambda vid, text, photo: self.asked.append(vid), evidence=lambda inc: (b"PK zip", {"key_fingerprint": "AB"}),
            camera_zone=lambda c: 4, post=lambda url, raw, headers: self.posts.append((url, raw, headers)) or 200,
            sia_send=lambda *a, **k: self.sia.append((a, k)) or (True, '"ACK"'), run_worker=False)

    def dispatch(self, t=1000.0):
        return self.v.on_dispatch({"kind": "dispatch", "t": t, "camera": "gate", "drone": "drone", "drone_label": "Drone 1", "by": "auto",
                                   "lat": 45.5, "lon": -75.6})

    def wait_sent(self):
        assert wait_until(lambda: any("monitoring centre" in n or "Monitoring centre" in n for n in self.notes), 5)


def test_off_does_nothing():
    w = World(verified_alarms=False)
    assert w.dispatch() is None and w.notes == []


def test_drone_ai_verifies_only_after_arrival_and_sends_signed_alarm():
    w = World()
    vid = w.dispatch()
    w.v.on_drone_detection({"kind": "drone_detection", "t": 1010.0, "drone": "drone", "label": "person"})  # en route: ignored
    assert w.v.items[vid]["status"] == "watching"
    w.arrived_at = 1030.0
    w.v.on_drone_detection({"kind": "drone_detection", "t": 1031.0, "drone": "drone", "label": "person"})
    assert w.v.items[vid]["status"] == "verified" and "drone AI (person" in w.v.items[vid]["verified_by"]
    w.wait_sent()
    url, raw, headers = w.posts[0]
    body = json.loads(raw)
    assert body["status"] == "verified" and body["zone"] == 4 and len(body["pictures"]) == 2 and body["location"]["lat"] == 45.5
    assert headers["X-Signature-SHA256"] == hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    (args, kw), = w.sia
    assert args[3] == 130 and kw["zone"] == 4
    assert w.v.items[vid]["sent"] == {"webhook": "ok", "sia": "ok"}
    assert w.v.verify(vid, "again")["ok"] is False  # decided once


def test_nobody_seen_asks_operator_false_alarm_sends_nothing():
    w = World()
    vid = w.dispatch()
    w.arrived_at = 1030.0
    w.v.tick(now=1030.0 + w.cfg["verify_window_s"])
    assert w.asked == [vid] and w.v.items[vid]["status"] == "asked"
    assert w.v.false_alarm(vid, "boss")["ok"]
    assert w.posts == [] and w.sia == [] and any("false alarm" in n for n in w.notes)


def test_operator_confirms_then_evidence_follows_when_response_ends():
    w = World()
    vid = w.dispatch()
    w.arrived_at = 1030.0
    w.v.tick(now=1100.0)
    w.v.verify(vid, "operator on Telegram")
    w.wait_sent()
    w.active = False
    w.v.tick(now=2000.0)
    w.v.tick(now=2000.0 + alarm_verify.EVIDENCE_DELAY_S)
    assert wait_until(lambda: any(json.loads(p[1]).get("type") == "evidence" for p in w.posts), 5)


def test_unconfirmed_is_sent_only_when_switched_on():
    for send in (False, True):
        w = World(send_unconfirmed=send)
        vid = w.dispatch()
        w.arrived_at = 1030.0
        w.v.tick(now=1100.0)
        w.v.tick(now=1100.0 + w.cfg["operator_window_s"])
        assert w.v.items[vid]["status"] == "unconfirmed"
        if send:
            w.wait_sent()
            assert w.sia[0][0][3] == 380
        else:
            assert w.posts == [] and w.sia == []


def test_settings_are_checked():
    with pytest.raises(ValueError):
        alarm_verify.clean({"webhook_url": "http://plain.example"})
    c = alarm_verify.clean({"verify_window_s": 5, "sia_port": "99999", "sia_account": "12-34!"})
    assert c["verify_window_s"] == 15 and c["sia_port"] == 65535 and c["sia_account"] == "1234"


# ---- the dashboard, end to end ----

class Hook(http.server.BaseHTTPRequestHandler):
    got = []

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        Hook.got.append((json.loads(raw), self.headers.get("X-Signature-SHA256"), raw))
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


def test_verified_alarm_through_the_dashboard(d, client, fleet, monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Hook.got.clear()
    try:
        (v1,) = fleet(1)
        d._virtual_cfg["demo_auto"] = True
        monkeypatch.setattr(d, "_camera_snapshot", lambda camera: b"\xff\xd8cam")
        monkeypatch.setattr(d, "_drone_snapshot", lambda slot=None: b"\xff\xd8drone")
        client.post("/api/response/settings", json={"camera_locations": {"acam": offset(20, 0)}, "min_battery": 20, "hover_seconds": 30})
        r = client.post("/api/alarms/settings", json={"verified_alarms": True, "webhook_url": f"http://127.0.0.1:{srv.server_port}/hook",
                                                      "webhook_secret": "abc", "site_name": "Test site"}).get_json()
        assert r["ok"] and r["settings"]["webhook_secret"] == alarm_verify.SECRET_MASK  # never shown again
        assert client.get("/api/response/settings").get_json()["settings"]["webhook_secret"] == alarm_verify.SECRET_MASK
        client.post("/api/alarms/settings", json={"webhook_secret": alarm_verify.SECRET_MASK, "site_name": "Test site"})
        assert d.load_response_settings()["webhook_secret"] == "abc"  # the mask doesn't overwrite it
        t = client.post("/api/alarms/test").get_json()
        assert t["ok"] and Hook.got[-1][0]["type"] == "test"
        assert d.dispatch_drone("acam", by="test")["ok"]
        assert wait_until(lambda: d.drone_response["phase"] == "hovering", 60)
        d.note_drone_detection(v1, "person", "obj-x")
        assert wait_until(lambda: any(g[0].get("status") == "verified" for g in Hook.got), 15)
        body, sig, raw = next(g for g in Hook.got if g[0].get("status") == "verified")
        assert body["site"] == "Test site" and body["camera"] == "acam" and sig == hmac.new(b"abc", raw, hashlib.sha256).hexdigest()
        st = client.get("/api/alarms").get_json()
        assert st["verifications"][0]["status"] == "verified"
        assert client.get("/alarms").status_code == 200
        d.recall_drone("test over")
        assert wait_until(lambda: not d.drone_response["active"], 90)
    finally:
        client.post("/api/alarms/settings", json={"verified_alarms": False, "webhook_url": "", "webhook_secret": ""})
        srv.shutdown()
