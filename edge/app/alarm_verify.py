"""Drone-verified alarms: a drone checks first, then the monitoring centre gets a verified alarm.

Off until the owner turns it on (Settings → Monitoring centre). When a drone is sent to a camera
(auto-dispatch, handoff, Telegram or the dashboard), a verification starts:

  * verified by the drone's AI   the drone has arrived and its own camera sees a person or vehicle
                                 within `verify_window_s`;
  * verified by a person         otherwise Telegram asks "confirm intrusion?" (Confirm / False alarm),
                                 also on the Incidents page; an operator can confirm at any time;
  * false alarm                  the operator says so: nothing is sent (it is logged).
  * unconfirmed                  nobody confirmed within `operator_window_s`: sent as "unconfirmed"
                                 only if `send_unconfirmed` is on.

A verified alarm goes, as configured, to an HTTPS webhook (JSON, HMAC-SHA256 signed, with the camera
and drone snapshots; the evidence pack follows when the response ends) and/or an alarm-receiving
centre over SIA DC-09 (Contact ID 130 burglary, 380 for unconfirmed). Every step is written to the
incident and the audit log.
"""
import base64
import hashlib
import hmac
import json
import threading
import time
import uuid

import sia_dc09

DEFAULTS = {"verified_alarms": False, "verify_window_s": 60, "operator_window_s": 600, "send_unconfirmed": False,
            "webhook_url": "", "webhook_secret": "", "sia_host": "", "sia_port": 0, "sia_account": "",
            "sia_receiver": "", "sia_line": "0", "site_name": ""}
EVIDENCE_DELAY_S = 60       # after the response ends: the response event (with the drone's video) is saved first
MAX_EVIDENCE_BYTES = 20 * 1024 * 1024
SECRET_MASK = "••••••••"


def clean(cfg):
    """The monitoring-centre settings, checked and bounded (used when saving)."""
    c = {**DEFAULTS, **{k: v for k, v in (cfg or {}).items() if k in DEFAULTS}}
    c["verified_alarms"] = bool(c["verified_alarms"])
    c["send_unconfirmed"] = bool(c["send_unconfirmed"])
    c["verify_window_s"] = max(15, min(300, int(float(c["verify_window_s"] or 60))))
    c["operator_window_s"] = max(60, min(3600, int(float(c["operator_window_s"] or 600))))
    url = str(c["webhook_url"] or "").strip()[:500]
    if url and not url.startswith("https://") and not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
        raise ValueError("The webhook address must start with https://")
    c["webhook_url"] = url
    c["webhook_secret"] = str(c["webhook_secret"] or "")[:200]
    c["sia_host"] = str(c["sia_host"] or "").strip()[:200]
    c["sia_port"] = max(0, min(65535, int(float(c["sia_port"] or 0))))
    c["sia_account"] = "".join(ch for ch in str(c["sia_account"] or "") if ch.isalnum())[:16]
    c["sia_receiver"] = "".join(ch for ch in str(c["sia_receiver"] or "") if ch.isalnum())[:6]
    c["sia_line"] = "".join(ch for ch in str(c["sia_line"] or "0") if ch.isalnum())[:6] or "0"
    c["site_name"] = str(c["site_name"] or "").strip()[:120]
    return c


class Verifier:
    def __init__(self, settings, arrived, drone_active, snapshots, publish, incident_note, audit, ask_operator,
                 evidence, camera_zone, post=None, sia_send=None, run_worker=True):
        self.settings = settings          # () -> dict with DEFAULTS keys
        self.arrived = arrived            # (drone) -> arrival time or 0
        self.drone_active = drone_active  # (drone) -> bool (still on this response)
        self.snapshots = snapshots        # (camera, drone) -> (camera jpeg|None, drone jpeg|None)
        self.publish = publish            # (kind, **data): Telegram alerts go out as "alert"
        self.incident_note = incident_note  # (camera, text, severity, data) -> incident id
        self.audit = audit                # (action, target, detail, result)
        self.ask_operator = ask_operator  # (vid, text, photo) -> None
        self.evidence = evidence          # (incident id) -> (zip bytes, manifest) or None
        self.camera_zone = camera_zone    # (camera) -> zone number for SIA
        self._post = post                 # tests replace the network
        self._sia = sia_send or sia_dc09.send
        self.items = {}                   # vid -> verification
        self.lock = threading.Lock()
        self.seq = 0
        if run_worker:
            threading.Thread(target=self._worker, name="alarm-verify", daemon=True).start()

    def attach(self, bus):
        bus.subscribe("dispatch", self.on_dispatch)
        bus.subscribe("drone_detection", self.on_drone_detection)

    # ---- pipeline ----
    def on_dispatch(self, m):
        if not self.settings().get("verified_alarms"):
            return None
        vid = uuid.uuid4().hex[:10]
        v = {"id": vid, "camera": m.get("camera") or "", "drone": m.get("drone") or "", "drone_label": m.get("drone_label") or "",
             "by": m.get("by") or "", "started": m["t"], "status": "watching", "verified_by": "", "sent": {}, "asked": False,
             "incident": None, "ended": 0.0, "evidence_sent": False, "lat": m.get("lat"), "lon": m.get("lon")}
        with self.lock:
            self.items[vid] = v
            if len(self.items) > 200:
                for k in sorted(self.items, key=lambda k: self.items[k]["started"])[:50]:
                    self.items.pop(k, None)
        v["incident"] = self.incident_note(v["camera"], f"Alarm verification started ({v['drone_label'] or v['drone']} on its way)", 3,
                                           {"verification": vid})
        return vid

    def on_drone_detection(self, m):
        drone, label = m.get("drone") or m.get("camera"), m.get("label") or "something"
        for v in self._open():
            arrived = self.arrived(v["drone"])
            if v["drone"] == drone and v["status"] == "watching" and arrived and m["t"] >= arrived - 2:
                self.verify(v["id"], f"drone AI ({label} seen by {v['drone_label'] or drone})")

    # ---- decisions ----
    def verify(self, vid, by, operator=""):
        with self.lock:
            v = self.items.get(vid)
            if not v or v["status"] in ("verified", "false_alarm"):
                return {"ok": False, "error": "That alarm was already decided."}
            v.update(status="verified", verified_by=by, decided=time.time(), operator=operator)
        self.incident_note(v["camera"], f"✅ Intrusion verified by {by}", 3, {"verification": vid})
        self.audit("alarm verified", v["camera"], {"verification": vid, "by": by}, "ok")
        threading.Thread(target=self.send, args=(vid, "verified"), daemon=True).start()
        return {"ok": True}

    def false_alarm(self, vid, operator=""):
        with self.lock:
            v = self.items.get(vid)
            if not v or v["status"] in ("verified", "false_alarm"):
                return {"ok": False, "error": "That alarm was already decided."}
            v.update(status="false_alarm", decided=time.time(), operator=operator)
        self.incident_note(v["camera"], f"❎ Marked false alarm{' by ' + operator if operator else ''}: nothing sent", 2, {"verification": vid})
        self.audit("alarm marked false", v["camera"], {"verification": vid}, "ok")
        return {"ok": True}

    def _open(self):
        with self.lock:
            return [dict(v) for v in self.items.values() if v["status"] in ("watching", "asked")]

    def tick(self, now=None):
        now = now or time.time()
        cfg = self.settings()
        for v in self._open():
            arrived = self.arrived(v["drone"])
            if v["status"] == "watching" and arrived and now - arrived >= cfg["verify_window_s"]:
                with self.lock:
                    self.items[v["id"]]["status"] = "asked"
                    self.items[v["id"]]["asked_at"] = now
                cam, drn = self.snapshots(v["camera"], v["drone"])
                self.ask_operator(v["id"], f"🛰 {v['drone_label'] or 'The drone'} is over {v['camera']} and its camera sees nobody. "
                                           f"Is this a real intrusion?", drn or cam)
                self.incident_note(v["camera"], "Drone saw nobody: asked the operator to confirm", 2, {"verification": v["id"]})
            elif v["status"] == "watching" and not arrived and not self.drone_active(v["drone"]) and now - v["started"] > 30:
                # The response ended before arriving (recalled, pilot took over): an operator decides.
                with self.lock:
                    self.items[v["id"]]["status"] = "asked"
                    self.items[v["id"]]["asked_at"] = now
                self.ask_operator(v["id"], f"🛰 The drone response to {v['camera']} ended before arriving. Is this a real intrusion?", None)
            elif v["status"] == "asked" and now - self.items.get(v["id"], {}).get("asked_at", now) >= cfg["operator_window_s"]:
                with self.lock:
                    self.items[v["id"]]["status"] = "unconfirmed"
                if cfg["send_unconfirmed"]:
                    self.incident_note(v["camera"], "Nobody confirmed: sent as unconfirmed", 2, {"verification": v["id"]})
                    threading.Thread(target=self.send, args=(v["id"], "unconfirmed"), daemon=True).start()
                else:
                    self.incident_note(v["camera"], "Nobody confirmed: not sent to the monitoring centre", 2, {"verification": v["id"]})
        # evidence pack after a verified response ends
        for v in list(self.items.values()):
            if v["status"] in ("verified", "unconfirmed") and not v["evidence_sent"] and v["sent"].get("webhook") == "ok":
                if self.drone_active(v["drone"]):
                    continue
                v["ended"] = v["ended"] or now
                if now - v["ended"] >= EVIDENCE_DELAY_S:
                    v["evidence_sent"] = True
                    threading.Thread(target=self.send_evidence, args=(v["id"],), daemon=True).start()

    def _worker(self):
        while True:
            time.sleep(2)
            try:
                if self.settings().get("verified_alarms"):
                    self.tick()
            except Exception as e:
                print("Alarm verification error:", e)

    # ---- sending ----
    def payload(self, v, kind):
        cfg = self.settings()
        cam, drn = self.snapshots(v["camera"], v["drone"])
        return {"type": "intrusion", "status": kind, "verified_by": v.get("verified_by", ""),
                "site": cfg.get("site_name") or "", "camera": v["camera"], "zone": self.camera_zone(v["camera"]),
                "drone": v["drone_label"] or v["drone"], "dispatched_by": v["by"],
                "location": {"lat": v.get("lat"), "lon": v.get("lon")} if v.get("lat") is not None else None,
                "incident_id": v.get("incident"), "verification_id": v["id"],
                "time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(v.get("decided") or time.time())),
                "pictures": [{"name": n, "jpeg_base64": base64.b64encode(b).decode()} for n, b in
                             (("camera.jpg", cam), ("drone.jpg", drn)) if b]}

    def post_json(self, url, body, secret):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "AI-Security-Command-Center"}
        if secret:
            headers["X-Signature-SHA256"] = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if self._post:
            return self._post(url, raw, headers)
        import requests
        r = requests.post(url, data=raw, headers=headers, timeout=20)
        return r.status_code

    def send(self, vid, kind):
        v = self.items.get(vid)
        if not v:
            return {}
        cfg = self.settings()
        results = {}
        if cfg["webhook_url"]:
            try:
                code = self.post_json(cfg["webhook_url"], self.payload(v, kind), cfg["webhook_secret"])
                results["webhook"] = "ok" if 200 <= int(code) < 300 else f"refused ({code})"
            except Exception as e:
                results["webhook"] = f"failed: {str(e)[:120]}"
        if cfg["sia_host"] and cfg["sia_port"] and cfg["sia_account"]:
            try:
                self.seq = (self.seq % 9999) + 1
                ok, reply = self._sia(cfg["sia_host"], cfg["sia_port"], cfg["sia_account"],
                                      sia_dc09.CODES["verified" if kind == "verified" else "unconfirmed"],
                                      zone=self.camera_zone(v["camera"]), seq=self.seq, receiver=cfg["sia_receiver"], line=cfg["sia_line"])
                results["sia"] = "ok" if ok else f"not acknowledged ({reply[:60]})"
            except Exception as e:
                results["sia"] = f"failed: {str(e)[:120]}"
        v["sent"] = results
        if not results:
            text = "⚠️ Verified alarm, but no monitoring centre is set up (Settings → Monitoring centre)."
        elif all(r == "ok" for r in results.values()):
            text = f"📡 {'Verified' if kind == 'verified' else 'Unconfirmed'} alarm sent to the monitoring centre ({', '.join(results)})."
        else:
            text = "⚠️ Monitoring centre: " + "; ".join(f"{k} {r}" for k, r in results.items())
        self.incident_note(v["camera"], text, 3 if kind == "verified" else 2, {"verification": vid, "sent": results})
        self.audit(f"alarm sent ({kind})", v["camera"], {"verification": vid, **results},
                   "ok" if results and all(r == "ok" for r in results.values()) else "failed")
        self.publish("alert", alert="verified_alarm", camera=v["camera"], text=text, key=f"alarm:{vid}")
        return results

    def send_evidence(self, vid):
        v = self.items.get(vid)
        cfg = self.settings()
        if not v or not cfg["webhook_url"] or not v.get("incident"):
            return
        try:
            got = self.evidence(v["incident"])
            if not got:
                return
            data, manifest = got
            if len(data) > MAX_EVIDENCE_BYTES:
                self.incident_note(v["camera"], "Evidence pack too large to send: download it from the Incidents page", 2, {})
                return
            code = self.post_json(cfg["webhook_url"], {"type": "evidence", "verification_id": vid, "incident_id": v["incident"],
                                                       "key_fingerprint": manifest.get("key_fingerprint"),
                                                       "evidence_zip_base64": base64.b64encode(data).decode()}, cfg["webhook_secret"])
            ok = 200 <= int(code) < 300
            self.incident_note(v["camera"], "Evidence pack sent to the monitoring centre" if ok else f"Evidence pack refused ({code})",
                               2, {"verification": vid})
        except Exception as e:
            self.incident_note(v["camera"], f"Evidence pack not sent: {str(e)[:100]}", 2, {"verification": vid})

    def test(self):
        """Send a test message to each configured destination (SIA: event 602 periodic test)."""
        cfg = self.settings()
        out = {}
        if cfg["webhook_url"]:
            try:
                code = self.post_json(cfg["webhook_url"], {"type": "test", "site": cfg["site_name"], "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                                      cfg["webhook_secret"])
                out["webhook"] = "ok" if 200 <= int(code) < 300 else f"refused ({code})"
            except Exception as e:
                out["webhook"] = f"failed: {str(e)[:120]}"
        if cfg["sia_host"] and cfg["sia_port"] and cfg["sia_account"]:
            try:
                self.seq = (self.seq % 9999) + 1
                ok, reply = self._sia(cfg["sia_host"], cfg["sia_port"], cfg["sia_account"], 602, zone=0, seq=self.seq,
                                      receiver=cfg["sia_receiver"], line=cfg["sia_line"])
                out["sia"] = "ok" if ok else f"not acknowledged ({reply[:60]})"
            except Exception as e:
                out["sia"] = f"failed: {str(e)[:120]}"
        return out

    def status(self):
        with self.lock:
            return [{k: v[k] for k in ("id", "camera", "drone_label", "status", "verified_by", "started", "sent", "incident")}
                    for v in sorted(self.items.values(), key=lambda x: -x["started"])[:20]]
