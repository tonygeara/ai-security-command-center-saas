"""Phone access through the cloud (cloud edition only, off until the owner turns it on).

When "Phone access" is on (Settings → System) and the PC is paired with the portal:
  * incidents at "unknown" level and above are sent to the portal with one snapshot each, so the
    owner sees them on a phone (portal → Incidents);
  * the portal can ask for a live view of a camera: this PC then uploads a fresh snapshot every few
    seconds for as long as someone is watching (at most 2 minutes per request, renewable).

Everything goes through one cloud function (edge-sync) with this PC's device token. Video never
streams through the cloud, only still pictures. The on-prem edition never contacts the cloud.
"""
import base64
import threading
import time

IDLE_POLL_S = 20      # how often the PC asks whether a phone wants a live view
LIVE_EVERY_S = 3      # one live picture every 3 s while someone watches
MAX_JPEG = 1_500_000  # bytes per picture sent
MIN_SEVERITY = 2      # unknown faces/plates and drone responses


class CloudSync:
    def __init__(self, url, token, enabled, incidents, snapshot_file, camera_snapshot, cameras, post=None):
        self.url = url                      # edge-sync function URL
        self.token = token                  # () -> device token or ""
        self.enabled = enabled              # () -> bool (setting on, cloud edition, paired)
        self.incidents = incidents          # incidents.Incidents
        self.snapshot_file = snapshot_file  # (event snapshot path) -> bytes or None
        self.camera_snapshot = camera_snapshot  # (camera) -> jpeg bytes or None
        self.cameras = cameras              # () -> [camera names]
        self._post = post                   # tests replace the network
        self.sent = {}                      # incident id -> (updated, status) last sent
        self.photo_sent = set()             # incident ids whose snapshot is up
        self.live = {}                      # request id -> {"camera", "until"}
        self.state = {"ok": None, "last": 0.0, "error": "", "incidents_sent": 0, "live_frames": 0}

    def post(self, body):
        if self._post:
            return self._post(body)
        import requests
        r = requests.post(self.url, json=body, headers={"x-device-token": self.token()}, timeout=20)
        if r.status_code >= 400:
            raise RuntimeError(f"cloud said {r.status_code}: {r.text[:200]}")
        return r.json()

    # ---- one round: incidents, then live requests ----
    def step(self, now=None):
        now = now or time.time()
        if not self.enabled() or not self.token():
            return False
        try:
            self.push_incidents(now)
            self.poll_live(now)
            self.state.update(ok=True, last=now, error="")
            return True
        except Exception as e:
            self.state.update(ok=False, last=now, error=str(e)[:200])
            return False

    def push_incidents(self, now):
        rows = [r for r in self.incidents.list(now - 7 * 86400, limit=100, min_severity=MIN_SEVERITY)
                if self.sent.get(r["id"]) != (r["updated"], r["status"])]
        if not rows:
            return
        out = []
        for r in rows[:25]:
            full = self.incidents.get(r["id"]) or {}
            out.append({"local_id": r["id"], "camera": r["camera"], "title": r["title"], "level": r["level"],
                        "severity": r["severity"], "status": r["status"], "started": r["started"], "updated": r["updated"],
                        "items": [{"t": x["t"], "kind": x["kind"], "text": x["text"]} for x in full.get("items", [])][-40:]})
        self.post({"action": "incidents", "incidents": out, "cameras": list(self.cameras())[:64]})
        for r in rows[:25]:
            self.sent[r["id"]] = (r["updated"], r["status"])
            self.state["incidents_sent"] += 1
            if r["id"] not in self.photo_sent:
                full = self.incidents.get(r["id"]) or {}
                snap = next((e["snapshot"] for e in full.get("events", []) if e.get("snapshot")), None)
                data = self.snapshot_file(snap) if snap else None
                if data and len(data) <= MAX_JPEG:
                    self.post({"action": "photo", "local_id": r["id"], "jpeg": base64.b64encode(data).decode()})
                self.photo_sent.add(r["id"])

    def poll_live(self, now):
        d = self.post({"action": "poll"}) or {}
        for req in d.get("live", []):
            self.live[req["id"]] = {"camera": req["camera"], "until": now + max(0, float(req.get("seconds_left") or 0))}
        self.live = {k: v for k, v in self.live.items() if v["until"] > now}

    def send_live_frames(self, now=None):
        now = now or time.time()
        for rid, req in list(self.live.items()):
            if req["until"] <= now:
                self.live.pop(rid, None)
                continue
            jpg = self.camera_snapshot(req["camera"])
            if jpg and len(jpg) <= MAX_JPEG:
                self.post({"action": "live", "request_id": rid, "camera": req["camera"], "jpeg": base64.b64encode(jpg).decode()})
                self.state["live_frames"] += 1

    def run(self):
        last_poll = 0.0
        while True:
            now = time.time()
            try:
                if self.live and self.enabled():
                    self.send_live_frames(now)
                if now - last_poll >= (LIVE_EVERY_S * 2 if self.live else IDLE_POLL_S):
                    last_poll = now
                    self.step(now)
            except Exception as e:
                self.state.update(ok=False, error=str(e)[:200])
            time.sleep(LIVE_EVERY_S if self.live else 2)

    def start(self):
        threading.Thread(target=self.run, name="cloud-sync", daemon=True).start()
