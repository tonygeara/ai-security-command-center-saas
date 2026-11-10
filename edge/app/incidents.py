"""Incidents: what happened at one camera, told as one story instead of scattered events.

Everything the pipeline (bus.py) carries for a camera within INCIDENT_GAP of the last thing that
happened there joins the same incident: the first detection, unknown faces and plates, known
visitors, the drone sent there and what it did. Severity only goes up:
    1 activity   people or vehicles seen
    2 unknown    an unknown face or plate
    3 response   a drone was sent
"""
import json
import time

INCIDENT_GAP = 300  # seconds of quiet at a camera before the next thing starts a new incident
SEVERITY = {1: "activity", 2: "unknown", 3: "response"}


class Incidents:
    def __init__(self, store, gap=INCIDENT_GAP):
        self.store = store
        self.gap = gap
        self._seen_objects = {}  # object id -> time (a tracked object counts once)

    def attach(self, bus):
        for kind in ("detection", "event", "sighting", "dispatch", "drone", "alert"):
            bus.subscribe(kind, self.on_message)

    # ---- pipeline ----
    def on_message(self, m):
        kind, camera, t = m["kind"], str(m.get("camera") or ""), m["t"]
        if not camera:
            return
        if kind == "detection":
            oid = m.get("object_id") or ""
            if m.get("stationary") or (oid and oid in self._seen_objects):
                return
            if oid:
                self._seen_objects[oid] = t
                if len(self._seen_objects) > 5000:
                    self._seen_objects = {k: v for k, v in self._seen_objects.items() if t - v < 3600}
            what = {"person": "Person", "car": "Vehicle", "truck": "Vehicle", "bus": "Vehicle",
                    "motorcycle": "Vehicle"}.get(m.get("label"), str(m.get("label") or "Object").capitalize())
            self.add(camera, t, kind, f"{what} seen", 1, {"label": m.get("label"), "object_id": oid})
        elif kind == "event":
            typ = str(m.get("type") or "")
            unknown = "UNKNOWN" in typ.upper()
            label = typ.title() + (f" {m['identifier']}" if m.get("identifier") else "")
            inc = self.add(camera, t, kind, label, 2 if unknown else 1,
                           {"event_id": m.get("event_id"), "snapshot": m.get("snapshot"), "type": typ})
            if m.get("event_id"):
                self.store.x("UPDATE events SET incident=? WHERE id=?", (inc, m["event_id"]))
        elif kind == "sighting":
            who = m.get("name") or m.get("identifier") or "someone"
            what = "Known person" if m.get("sighting") == "face" else "Known vehicle"
            if not m.get("known"):
                return  # unknown ones arrive as events (with a snapshot)
            self.add(camera, t, kind, f"{what}: {who}", 1, {"kind": m.get("sighting"), "name": m.get("name"),
                                                             "identifier": m.get("identifier")})
        elif kind == "dispatch":
            self.add(camera, t, kind, f"{m.get('drone_label') or m.get('drone')} sent ({m.get('by')})", 3,
                     {"drone": m.get("drone"), "by": m.get("by"), "lat": m.get("lat"), "lon": m.get("lon")})
        elif kind == "alert":
            if m.get("pattern"):  # casing / unusual activity warnings (patterns.py)
                self.add(camera, t, "pattern", m.get("text") or "", 2, {"alert": m.get("alert")})
        elif kind == "drone":
            self.add(camera, t, kind, f"{m.get('drone_label') or m.get('drone')}: {m.get('text')}", 1,
                     {"drone": m.get("drone")}, open_only=True)

    # ---- storage ----
    def current(self, camera, t):
        rows = self.store.q("SELECT * FROM incidents WHERE camera=? AND status='open' ORDER BY updated DESC LIMIT 1", (camera,))
        if rows and t - rows[0]["updated"] <= self.gap:
            return rows[0]
        return None

    def add(self, camera, t, kind, text, severity, data=None, open_only=False):
        """Add one line to the camera's open incident (or start one); returns the incident id."""
        with self.store.lock:
            inc = self.current(camera, t)
            if inc is None:
                if open_only:
                    return None  # e.g. drone chatter after the incident ended
                cur = self.store.x("INSERT INTO incidents(started, updated, camera, title, severity) VALUES(?,?,?,?,?)",
                                   (t, t, camera, f"{text} at {camera}", severity))
                inc_id, old_sev = cur.lastrowid, severity
            else:
                inc_id, old_sev = inc["id"], inc["severity"]
                title = inc["title"]
                if severity > old_sev:
                    title = f"{text} at {camera}"
                self.store.x("UPDATE incidents SET updated=?, severity=?, title=? WHERE id=?",
                             (max(t, inc["updated"]), max(severity, old_sev), title, inc_id))
            self.store.x("INSERT INTO incident_items(incident, t, kind, text, data) VALUES(?,?,?,?,?)",
                         (inc_id, t, kind, str(text)[:200], json.dumps(data or {}, ensure_ascii=False)))
        return inc_id

    def close_stale(self, now=None):
        """Incidents with nothing new for INCIDENT_GAP are closed (they can still be reopened)."""
        self.store.x("UPDATE incidents SET status='closed' WHERE status='open' AND updated < ?", ((now or time.time()) - self.gap,))

    def set_status(self, inc_id, status, note="", user=""):
        if status not in ("open", "closed", "reviewed"):
            raise ValueError("Unknown status")
        if not self.store.q("SELECT id FROM incidents WHERE id=?", (inc_id,)):
            raise KeyError(inc_id)
        self.store.x("UPDATE incidents SET status=? WHERE id=?", (status, inc_id))
        if note:
            self.store.x("INSERT INTO incident_items(incident, t, kind, text, data) VALUES(?,?,?,?,?)",
                         (inc_id, time.time(), "note", str(note)[:500], json.dumps({"user": user})))

    def list(self, since, limit=200, min_severity=1):
        rows = self.store.q("SELECT * FROM incidents WHERE updated >= ? AND severity >= ? ORDER BY updated DESC LIMIT ?",
                            (since, min_severity, int(limit)))
        return [self._public(r) for r in rows]

    def get(self, inc_id):
        rows = self.store.q("SELECT * FROM incidents WHERE id=?", (inc_id,))
        if not rows:
            return None
        inc = self._public(rows[0])
        inc["items"] = [{"t": r["t"], "kind": r["kind"], "text": r["text"], "data": json.loads(r["data"] or "{}")}
                        for r in self.store.q("SELECT * FROM incident_items WHERE incident=? ORDER BY t, id", (inc_id,))]
        inc["events"] = [dict(r) for r in self.store.q("SELECT id, t, type, identifier, snapshot FROM events WHERE incident=? ORDER BY t",
                                                       (inc_id,))]
        return inc

    @staticmethod
    def _public(r):
        return {"id": r["id"], "started": r["started"], "updated": r["updated"], "camera": r["camera"], "title": r["title"],
                "severity": r["severity"], "level": SEVERITY.get(r["severity"], "activity"), "status": r["status"]}

    def add_track_point(self, camera, t, drone, lat, lon, alt=None):
        inc = self.current(camera, t)
        if inc:
            self.store.x("INSERT INTO tracks(incident, t, drone, lat, lon, alt) VALUES(?,?,?,?,?,?)",
                         (inc["id"], t, drone, lat, lon, alt))

    def track(self, inc_id):
        return [dict(r) for r in self.store.q("SELECT t, drone, lat, lon, alt FROM tracks WHERE incident=? ORDER BY t", (inc_id,))]

    def prune(self, before):
        with self.store.lock:
            self.store.x("DELETE FROM tracks WHERE incident IN (SELECT id FROM incidents WHERE updated < ?)", (before,))
            self.store.x("DELETE FROM incident_items WHERE incident IN (SELECT id FROM incidents WHERE updated < ?)", (before,))
            self.store.x("DELETE FROM incidents WHERE updated < ?", (before,))
