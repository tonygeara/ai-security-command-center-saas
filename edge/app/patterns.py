"""Patterns: warnings that come from what the site remembers, not from a single detection.

Casing: burglars drive past a few times before they come back. The same unknown plate seen on
`casing_visits` separate visits (any cameras) within `casing_hours` raises one warning for that
plate in that window. Sightings closer than VISIT_GAP count as one visit (a car passing two cameras).

Unusual activity: each camera's number of people/vehicles for this hour is compared with the same
hour on the same weekday in the previous weeks (from the incidents history). Far more than usual
raises one warning for that camera and hour. Needs two weeks of history; until then it is learning.

Both are published on the pipeline as "alert" messages (pattern=True): Telegram sends them and the
camera's incident records them.
"""
import math
import re
import time

VISIT_GAP = 600          # seconds: sightings closer than this are one visit
WEEK = 7 * 86400
MIN_UNUSUAL = 5          # never warn below this many people/vehicles in an hour
MIN_HISTORY_WEEKS = 2
DEFAULTS = {"casing_alerts": True, "casing_visits": 3, "casing_hours": 24, "unusual_alerts": True}


def norm_plate(p):
    return re.sub(r"[^A-Z0-9]", "", str(p or "").upper())


class Patterns:
    def __init__(self, store, settings, publish):
        self.store = store
        self.settings = settings      # () -> dict with the DEFAULTS keys
        self.publish = publish        # (kind, **data)
        self._casing_warned = {}      # plate -> time warned
        self._hour_counts = {}        # (camera, hour) -> count
        self._unusual_warned = set()  # (camera, hour)
        self._baseline = {}           # (camera, hour) -> (avg or None)
        self._seen = {}               # object id -> time

    def attach(self, bus):
        bus.subscribe("sighting", self.on_sighting)
        bus.subscribe("detection", self.on_detection)

    def cfg(self):
        c = {**DEFAULTS, **{k: v for k, v in (self.settings() or {}).items() if k in DEFAULTS}}
        c["casing_visits"] = max(2, int(c["casing_visits"] or 3))
        c["casing_hours"] = max(1, min(24 * 14, float(c["casing_hours"] or 24)))
        return c

    # ---- casing ----
    def on_sighting(self, m):
        c = self.cfg()
        if m.get("sighting") != "plate" or m.get("known") or not c["casing_alerts"]:
            return
        plate = norm_plate(m.get("identifier"))
        if len(plate) < 3:
            return
        t, window = m["t"], c["casing_hours"] * 3600
        if t - self._casing_warned.get(plate, 0) < window:
            return
        rows = [r for r in self.store.q("SELECT t, camera, ident FROM sightings WHERE kind='plate' AND t >= ? AND t <= ? ORDER BY t",
                                        (t - window, t + 1)) if norm_plate(r["ident"]) == plate]
        visits = []
        for r in rows:
            if visits and r["t"] - visits[-1]["last"] < VISIT_GAP:
                visits[-1]["last"] = r["t"]
                visits[-1]["cameras"].add(r["camera"])
            else:
                visits.append({"first": r["t"], "last": r["t"], "cameras": {r["camera"]}})
        if len(visits) < c["casing_visits"]:
            return
        self._casing_warned[plate] = t
        when = ", ".join(f"{time.strftime('%H:%M', time.localtime(v['first']))} ({'/'.join(sorted(v['cameras']))})" for v in visits[-6:])
        hours = int(c["casing_hours"]) if c["casing_hours"] == int(c["casing_hours"]) else c["casing_hours"]
        self.publish("alert", alert="casing", pattern=True, camera=m.get("camera") or "", key=f"casing:{plate}:{int(t // window)}",
                     text=f"🔎 Possible casing: plate {plate} came by {len(visits)} times in the last {hours} h: {when}.",
                     plate=plate, visits=len(visits))

    # ---- unusual activity ----
    def on_detection(self, m):
        c = self.cfg()
        if not c["unusual_alerts"] or m.get("stationary"):
            return
        oid, t, camera = m.get("object_id") or "", m["t"], m.get("camera") or ""
        if oid:
            if oid in self._seen:
                return
            self._seen[oid] = t
            if len(self._seen) > 5000:
                self._seen = {k: v for k, v in self._seen.items() if t - v < 7200}
        hour = int(t // 3600)
        key = (camera, hour)
        self._hour_counts[key] = self._hour_counts.get(key, 0) + 1
        if len(self._hour_counts) > 500:
            self._hour_counts = {k: v for k, v in self._hour_counts.items() if k[1] >= hour - 2}
        if key in self._unusual_warned:
            return
        n = self._hour_counts[key]
        if n < MIN_UNUSUAL:
            return
        usual = self.usual(camera, hour)
        if usual is None:
            return  # still learning this camera
        limit = max(MIN_UNUSUAL, math.ceil(3 * usual) + 3)
        if n >= limit:
            self._unusual_warned.add(key)
            self.publish("alert", alert="unusual", pattern=True, camera=camera, key=f"unusual:{camera}:{hour}",
                         text=f"📈 Unusual activity at {camera}: {n} people/vehicles this hour; usually about {usual:.0f} "
                              f"at this time on a {time.strftime('%A', time.localtime(t))}.", count=n, usual=usual)

    def usual(self, camera, hour):
        """Average people/vehicles in this hour of the week over the previous weeks, or None while learning."""
        key = (camera, hour)
        if key in self._baseline:
            return self._baseline[key]
        start = hour * 3600
        oldest = self.store.q("SELECT MIN(i.t) AS t FROM incident_items i JOIN incidents n ON n.id = i.incident "
                              "WHERE n.camera = ? AND i.kind = 'detection'", (camera,))[0]["t"]
        weeks = int((start - oldest) // WEEK) if oldest else 0
        if weeks < MIN_HISTORY_WEEKS:
            self._baseline[key] = None
            return None
        weeks = min(weeks, 4)
        total = 0
        for k in range(1, weeks + 1):
            a = start - k * WEEK
            total += self.store.q("SELECT COUNT(*) AS n FROM incident_items i JOIN incidents n ON n.id = i.incident "
                                  "WHERE n.camera = ? AND i.kind = 'detection' AND i.t >= ? AND i.t < ?", (camera, a, a + 3600))[0]["n"]
        self._baseline[key] = total / weeks
        if len(self._baseline) > 500:
            self._baseline = {k: v for k, v in self._baseline.items() if k[1] >= hour - 2}
        return self._baseline[key]
