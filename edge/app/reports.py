"""Scheduled reports (Settings → Reports): daily, weekly and/or monthly summaries of what happened on the site, sent to
Telegram as a short text with a PDF, and kept on this PC. The daily report replaces the old morning briefing.

This module only works on plain data (lists of dicts) so it can be tested on its own; dashboard.py gathers the data,
sends the reports and serves the Settings page."""
import calendar
import json
import os
import re
import time
from datetime import datetime, timedelta

import pdfmini

KINDS = ("daily", "weekly", "monthly")
KIND_NAME = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}
SECTIONS = {  # key: (title, what it holds)
    "detections": "Detections",
    "incidents": "Incidents and drone responses",
    "flights": "Drone flights",
    "drones_detected": "Unknown drones",
    "alarms": "Verified alarms",
    "uptime": "Cameras and PC",
    "busiest": "Busiest cameras and hours",
}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# A report is not sent if the PC was off at its time and comes back later than this (a stale report is noise).
MAX_LATE = {"daily": 2 * 3600, "weekly": 2 * 86400, "monthly": 5 * 86400}
KEEP_DAYS = 400  # saved PDFs older than this are deleted
VEHICLES = {"car", "truck", "bus", "motorcycle", "bicycle", "vehicle"}
DETECTOR_ALARM_KINDS = {"position": "position", "camera": "camera", "remote_id": "Remote ID", "acoustic": "acoustic", "rf": "RF"}

DEFAULTS = {
    "daily": {"on": True, "time": "08:00"},
    "weekly": {"on": False, "time": "08:00", "weekday": 0},
    "monthly": {"on": False, "time": "08:00", "day": 1},
    "sections": {k: True for k in SECTIONS},
    "telegram": True,
    "email": {"on": False, "to": []},  # online PCs: emailed through the portal to some of the company's portal accounts
}
EMAIL_RX = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")


# ---------------------------------------------------------------- settings
def _hhmm(v, default="08:00"):
    v = str(v or "")
    return v if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v) else default


def clean_settings(raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for k in KINDS:
        r = raw.get(k) if isinstance(raw.get(k), dict) else {}
        d = dict(DEFAULTS[k])
        d["on"] = bool(r.get("on", d["on"]))
        d["time"] = _hhmm(r.get("time"), d["time"])
        if k == "weekly":
            try:
                d["weekday"] = max(0, min(6, int(r.get("weekday", d["weekday"]))))
            except (TypeError, ValueError):
                pass
        if k == "monthly":
            try:
                d["day"] = max(1, min(31, int(r.get("day", d["day"]))))
            except (TypeError, ValueError):
                pass
        out[k] = d
    sec = raw.get("sections") if isinstance(raw.get("sections"), dict) else {}
    out["sections"] = {k: bool(sec.get(k, True)) for k in SECTIONS}
    out["telegram"] = bool(raw.get("telegram", True))
    em = raw.get("email") if isinstance(raw.get("email"), dict) else {}
    to = [str(x).strip().lower() for x in (em.get("to") if isinstance(em.get("to"), list) else [])]
    out["email"] = {"on": bool(em.get("on", False)), "to": list(dict.fromkeys(x for x in to if EMAIL_RX.match(x)))[:25]}
    return out


def load_settings(path, legacy_briefing=None):
    """The saved settings; before the first save, the daily report follows the old morning briefing switch and time."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return clean_settings(json.load(f))
    except (OSError, ValueError):
        s = clean_settings({})
        if legacy_briefing:
            s["daily"]["on"] = bool(legacy_briefing.get("briefing_enabled", True))
            s["daily"]["time"] = _hhmm(legacy_briefing.get("briefing_time"), "08:00")
        return s


def save_settings(path, raw):
    s = clean_settings(raw)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    for attempt in range(20):  # Windows refuses the replace while another reader has the file open for a moment
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if os.name != "nt" or attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))
    return s


# ---------------------------------------------------------------- schedule
def _at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m)


def _month_day(year, month, day):
    return min(day, calendar.monthrange(year, month)[1])


def last_moment(kind, cfg, now=None):
    """The latest time this report was due, at or before now (local time), as a timestamp."""
    now_dt = datetime.fromtimestamp(now if now is not None else time.time())
    c = cfg[kind]
    if kind == "daily":
        m = _at(now_dt, c["time"])
        if m > now_dt:
            m -= timedelta(days=1)
    elif kind == "weekly":
        m = _at(now_dt - timedelta(days=(now_dt.weekday() - c["weekday"]) % 7), c["time"])
        if m > now_dt:
            m -= timedelta(days=7)
    else:
        y, mo = now_dt.year, now_dt.month
        m = _at(datetime(y, mo, _month_day(y, mo, c["day"])), c["time"])
        if m > now_dt:
            y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
            m = _at(datetime(y, mo, _month_day(y, mo, c["day"])), c["time"])
    return m.timestamp()


def period(kind, end, cfg=None):
    """(start, end) of the report that ends at `end`: the last day, the last 7 days, or the last month."""
    if kind == "daily":
        return end - 86400, end
    if kind == "weekly":
        return end - 7 * 86400, end
    e = datetime.fromtimestamp(end)
    y, mo = (e.year - 1, 12) if e.month == 1 else (e.year, e.month - 1)
    s = datetime(y, mo, _month_day(y, mo, e.day), e.hour, e.minute, e.second)
    return s.timestamp(), end


def due(cfg, state, now=None):
    """[(kind, moment)] of the reports to send now: switched on, their time has come, not sent yet, not too late."""
    now = now if now is not None else time.time()
    out = []
    for k in KINDS:
        if not cfg[k]["on"]:
            continue
        m = last_moment(k, cfg, now)
        if (state.get("last") or {}).get(k, 0) >= m:
            continue
        if now - m <= MAX_LATE[k]:
            out.append((k, m))
    return out


def mark_handled(cfg, state, now=None):
    """After the settings change: the reports whose time has already passed today are not sent late."""
    last = dict(state.get("last") or {})
    for k in KINDS:
        last[k] = max(last.get(k, 0), last_moment(k, cfg, now))
    return {**state, "last": last}


def describe_schedule(cfg):
    parts = []
    if cfg["daily"]["on"]:
        parts.append(f"daily at {cfg['daily']['time']}")
    if cfg["weekly"]["on"]:
        parts.append(f"weekly on {WEEKDAYS[cfg['weekly']['weekday']]} at {cfg['weekly']['time']}")
    if cfg["monthly"]["on"]:
        parts.append(f"monthly on day {cfg['monthly']['day']} at {cfg['monthly']['time']}")
    return ", ".join(parts) or "off"


# ---------------------------------------------------------------- figures
def _in(t, start, end):
    return start <= t < end


def _label(item):
    d = item.get("data") if isinstance(item.get("data"), dict) else {}
    return str(d.get("label") or "").lower()


def figures(data, start, end):
    """Numbers for one period. data: {"sightings", "items", "incidents", "audit", "flights", "detector_events", "uptime"}.
    Every list holds dicts with a "t" (or "start" for flights, "day" for uptime)."""
    sight = [r for r in data.get("sightings", []) if _in(r["t"], start, end)]
    items = [r for r in data.get("items", []) if _in(r["t"], start, end)]
    incs = [r for r in data.get("incidents", []) if _in(r.get("updated", r.get("t", 0)), start, end)]
    audit = [r for r in data.get("audit", []) if _in(r["t"], start, end)]
    flights = [r for r in data.get("flights", []) if _in(r["start"], start, end)]
    dets = [r for r in data.get("detector_events", []) if _in(r["t"], start, end) and r.get("kind") in DETECTOR_ALARM_KINDS]

    detections = [i for i in items if i.get("kind") == "detection"]
    people = sum(1 for i in detections if _label(i) == "person")
    vehicles = sum(1 for i in detections if _label(i) in VEHICLES)
    faces = [r for r in sight if r["kind"] == "face"]
    plates = [r for r in sight if r["kind"] == "plate"]
    known_people = sorted({r["name"] for r in faces if r.get("known") and r.get("name")})
    unknown_faces = sum(1 for r in faces if not r.get("known"))
    plate_counts = {}
    for r in plates:
        key = r.get("id") or r.get("ident") or "unreadable"
        p = plate_counts.setdefault(key, {"plate": key, "n": 0, "known": bool(r.get("known")), "name": r.get("name") or ""})
        p["n"] += 1
    unknown_plates = [p for p in plate_counts.values() if not p["known"]]
    repeat = sorted([p for p in unknown_plates if p["n"] >= 2 and p["plate"] != "unreadable"], key=lambda p: -p["n"])[:8]

    sev = {3: 0, 2: 0, 1: 0}
    for i in incs:
        sev[max(1, min(3, int(i.get("severity") or 1)))] += 1
    dispatches = [i for i in items if i.get("kind") == "dispatch"]
    top_incidents = sorted(incs, key=lambda i: (-(i.get("severity") or 1), -i.get("updated", 0)))[:8]

    per_drone = {}
    for f in flights:
        d = per_drone.setdefault(f.get("label") or f.get("slot") or "Drone", {"drone": f.get("label") or f.get("slot"), "n": 0, "min": 0.0, "km": 0.0})
        d["n"] += 1
        d["min"] += max(0.0, (f["end"] - f["start"]) / 60)
        d["km"] += (f.get("distance_m") or 0) / 1000
    weather = sum(1 for a in audit if "despite the weather" in str(a.get("action") or ""))

    by_kind, by_det = {}, {}
    for e in dets:
        by_kind[DETECTOR_ALARM_KINDS[e["kind"]]] = by_kind.get(DETECTOR_ALARM_KINDS[e["kind"]], 0) + 1
        by_det[e.get("detector_name") or "Detector"] = by_det.get(e.get("detector_name") or "Detector", 0) + 1

    act = lambda name: sum(1 for a in audit if str(a.get("action") or "") == name)
    sent = sum(1 for a in audit if str(a.get("action") or "").startswith("alarm sent"))

    # Uptime: minutes the PC was running and minutes each camera was offline while it ran (counted once a minute).
    span_min = max(1.0, (end - start) / 60)
    up = data.get("uptime", [])
    pc_min = sum(u.get("pc", 0) for u in up if _in(u["t"], start, end))
    cam_off = {}
    for u in up:
        if _in(u["t"], start, end):
            for cam, m in (u.get("cams_off") or {}).items():
                cam_off[cam] = cam_off.get(cam, 0) + m

    per_cam, hours = {}, [0] * 24
    for i in detections:
        per_cam[i.get("camera") or "?"] = per_cam.get(i.get("camera") or "?", 0) + 1
        hours[time.localtime(i["t"]).tm_hour] += 1

    return {
        "detections": {"people": people, "vehicles": vehicles, "known_people": known_people, "unknown_faces": unknown_faces,
                       "plates": len(plate_counts), "unknown_plates": len(unknown_plates), "repeat_plates": repeat},
        "incidents": {"total": len(incs), "high": sev[3], "medium": sev[2], "low": sev[1], "drone_responses": len(dispatches),
                      "top": [{"t": i.get("updated", 0), "camera": i.get("camera") or "", "title": i.get("title") or "",
                               "severity": i.get("severity") or 1} for i in top_incidents]},
        "flights": {"count": len(flights), "minutes": round(sum(d["min"] for d in per_drone.values()), 1),
                    "km": round(sum(d["km"] for d in per_drone.values()), 2), "weather_overrides": weather,
                    "per_drone": sorted(per_drone.values(), key=lambda d: -d["min"])},
        "drones_detected": {"alarms": len(dets), "by_kind": by_kind, "by_detector": by_det,
                            "last": [{"t": e["t"], "text": e.get("text") or "", "detector": e.get("detector_name") or ""} for e in dets[-6:]][::-1]},
        "alarms": {"verified": act("alarm verified"), "false": act("alarm marked false"), "sent": sent},
        "uptime": {"pc_percent": round(min(100.0, 100 * pc_min / span_min), 1) if up else None,
                   "cams_offline_min": dict(sorted(cam_off.items(), key=lambda kv: -kv[1]))},
        "busiest": {"cameras": sorted(({"camera": c, "n": n} for c, n in per_cam.items()), key=lambda x: -x["n"])[:8],
                    "hours": hours, "peak_hour": max(range(24), key=lambda h: hours[h]) if any(hours) else None},
    }


HEADLINES = [("detections", "people", "People seen"), ("detections", "vehicles", "Vehicles seen"),
             ("detections", "unknown_faces", "Unknown faces"), ("incidents", "total", "Incidents"),
             ("flights", "count", "Drone flights"), ("drones_detected", "alarms", "Unknown drones")]


def build(kind, start, end, data, cfg, site="", version=""):
    """One report: this period's figures, the previous period's for comparison, and its sections."""
    now = figures(data, start, end)
    prev = figures(data, start - (end - start), start)
    return {"kind": kind, "start": start, "end": end, "site": site, "version": version, "generated": time.time(),
            "sections": [k for k in SECTIONS if cfg["sections"].get(k, True)], "now": now, "prev": prev}


# ---------------------------------------------------------------- text and file names
def _d(t, with_time=True):
    return time.strftime("%d %b %Y %H:%M" if with_time else "%d %b %Y", time.localtime(t))


def title(r):
    return f"{KIND_NAME.get(r['kind'], 'Custom')} report" + (f" · {r['site']}" if r.get("site") else "")


def span(r):
    return f"{_d(r['start'])} – {_d(r['end'])}"


def _change(now, prev):
    if prev == now:
        return "same as before"
    if not prev:
        return "new"
    pct = round(100 * (now - prev) / prev)
    return f"{'+' if pct > 0 else ''}{pct}% vs before"


def text_summary(r):
    """The short Telegram message sent with the PDF."""
    n, p = r["now"], r["prev"]
    lines = [f"📊 {title(r)}", span(r), ""]
    for sec, key, label in HEADLINES:
        if sec in r["sections"]:
            lines.append(f"• {label}: {n[sec][key]} ({_change(n[sec][key], p[sec][key])})")
    if "detections" in r["sections"] and n["detections"]["repeat_plates"]:
        lines.append("• Unknown plates seen more than once: " + ", ".join(f"{x['plate']} ×{x['n']}" for x in n["detections"]["repeat_plates"][:4]))
    if "incidents" in r["sections"] and n["incidents"]["drone_responses"]:
        lines.append(f"• Drone responses: {n['incidents']['drone_responses']}")
    if "alarms" in r["sections"] and (n["alarms"]["verified"] or n["alarms"]["false"]):
        lines.append(f"• Alarms: {n['alarms']['verified']} verified, {n['alarms']['false']} false")
    if "uptime" in r["sections"]:
        off = n["uptime"]["cams_offline_min"]
        lines.append("• Cameras: " + ("no camera went offline" if not off else "offline: " + ", ".join(f"{c} {_mins(m)}" for c, m in list(off.items())[:4])))
    lines += ["", "The full report is in the PDF."]
    return "\n".join(lines)


def _mins(m):
    m = int(round(m))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def file_name(r):
    return f"{r['kind']}-report-{time.strftime('%Y-%m-%d-%H%M', time.localtime(r['end']))}.pdf"


NAME_RX = re.compile(r"^(daily|weekly|monthly|custom)-report-\d{4}-\d{2}-\d{2}-\d{4}\.pdf$")


def saved(folder):
    """The saved reports, newest first."""
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for n in names:
        if NAME_RX.match(n):
            p = os.path.join(folder, n)
            out.append({"name": n, "kind": n.split("-", 1)[0], "size": os.path.getsize(p), "at": os.path.getmtime(p)})
    return sorted(out, key=lambda x: x["name"][-19:], reverse=True)


def prune(folder, now=None):
    now = now or time.time()
    for x in saved(folder):
        if now - x["at"] > KEEP_DAYS * 86400:
            try:
                os.remove(os.path.join(folder, x["name"]))
            except OSError:
                pass


# ---------------------------------------------------------------- PDF
INK, MUTED, ACC, LIGHT, GRID, RED, GREEN = "#1b2a35", "#5f7381", "#1f4e79", "#e8f0f7", "#bfcfdd", "#b3261e", "#1e7d46"


class _Layout:
    def __init__(self, pdf, footer):
        self.pdf, self.y, self.footer, self.page = pdf, 0, footer, 1
        self.left, self.right = 48, pdf.width - 48
        self._foot()

    def _foot(self):
        self.pdf.text(self.pdf.width / 2, self.pdf.height - 24, f"{self.footer} · page {self.page}", 8, color=MUTED, align="center")

    def need(self, h):
        if self.y + h > self.pdf.height - 56:
            self.pdf.add_page()
            self.page += 1
            self._foot()
            self.y = 48

    def heading(self, text):
        self.need(60)
        self.y += 14
        self.pdf.text(self.left, self.y + 12, text, 14, True, ACC)
        self.y += 20
        self.pdf.line(self.left, self.y, self.right, self.y, ACC, 1)
        self.y += 10

    def para(self, text, size=9.5, color=MUTED):
        for ln in pdfmini.wrap(text, size, self.right - self.left):
            self.need(size + 4)
            self.pdf.text(self.left, self.y + size, ln, size, color=color)
            self.y += size + 4
        self.y += 2

    def table(self, head, rows, widths):
        """widths are fractions of the line; long cells wrap."""
        total = self.right - self.left
        ws = [w * total for w in widths]

        def row(cells, bold=False, fill=None):
            lines = [pdfmini.wrap(str(c), 9, w - 10, bold) for c, w in zip(cells, ws)]
            h = 6 + 12 * max(len(x) for x in lines)
            self.need(h)
            if fill:
                self.pdf.rect(self.left, self.y, total, h, fill)
            x = self.left
            for ls, w in zip(lines, ws):
                for k, ln in enumerate(ls):
                    self.pdf.text(x + 5, self.y + 13 + 12 * k, ln, 9, bold, "#ffffff" if fill == ACC else INK)
                x += w
            self.y += h
            self.pdf.line(self.left, self.y, self.right, self.y, GRID)

        row(head, True, ACC)
        for k, r in enumerate(rows):
            row(r, fill=LIGHT if k % 2 else None)
        self.y += 6


def pdf_bytes(r):
    n, p = r["now"], r["prev"]
    pdf = pdfmini.Pdf(title(r), "AI Security Command Center")
    L = _Layout(pdf, f"AI Security Command Center · {title(r)}")
    W = pdf.width
    pdf.rect(0, 0, W, 92, ACC)
    pdf.text(48, 38, "AI SECURITY COMMAND CENTER", 9, True, "#9edfff")
    pdf.text(48, 62, title(r), 20, True, "#ffffff")
    pdf.text(48, 80, span(r), 10, color="#d6ecfa")
    pdf.text(W - 48, 80, f"Made {_d(r['generated'])}" + (f" · {r['version']}" if r.get("version") else ""), 8, color="#d6ecfa", align="right")
    L.y = 110

    # Headline tiles with the change from the previous period.
    tiles = [(s, k, lab) for s, k, lab in HEADLINES if s in r["sections"]]
    if tiles:
        cols = 3
        tw = (L.right - L.left - (cols - 1) * 10) / cols
        for i, (s, k, lab) in enumerate(tiles):
            x, y = L.left + (i % cols) * (tw + 10), L.y + (i // cols) * 66
            pdf.rect(x, y, tw, 58, LIGHT, GRID)
            pdf.text(x + 10, y + 16, lab.upper(), 7.5, True, MUTED)
            pdf.text(x + 10, y + 40, str(n[s][k]), 20, True, INK)
            ch = _change(n[s][k], p[s][k])
            up = n[s][k] > p[s][k]
            pdf.text(x + 10, y + 52, ch, 7.5, color=(RED if up and s in ("incidents", "drones_detected") else MUTED))
        L.y += ((len(tiles) + cols - 1) // cols) * 66 + 4

    if "detections" in r["sections"]:
        d = n["detections"]
        L.heading(SECTIONS["detections"])
        L.table(["What", "This period", "Before"], [
            ["People seen", d["people"], p["detections"]["people"]],
            ["Vehicles seen", d["vehicles"], p["detections"]["vehicles"]],
            ["Known people", len(d["known_people"]), len(p["detections"]["known_people"])],
            ["Unknown faces", d["unknown_faces"], p["detections"]["unknown_faces"]],
            ["Number plates read", d["plates"], p["detections"]["plates"]],
            ["Unknown plates", d["unknown_plates"], p["detections"]["unknown_plates"]]], [0.5, 0.25, 0.25])
        if d["known_people"]:
            L.para("Known people: " + ", ".join(d["known_people"][:30]))
        if d["repeat_plates"]:
            L.para("Unknown plates seen more than once (could be someone checking the place):", 9.5, INK)
            L.table(["Plate", "Times seen"], [[x["plate"], x["n"]] for x in d["repeat_plates"]], [0.6, 0.4])

    if "incidents" in r["sections"]:
        d = n["incidents"]
        L.heading(SECTIONS["incidents"])
        L.para(f"{d['total']} incidents: {d['high']} serious, {d['medium']} medium, {d['low']} low. "
               f"Drones were sent {d['drone_responses']} time{'' if d['drone_responses'] == 1 else 's'}.", 10, INK)
        if d["top"]:
            L.table(["When", "Camera", "What happened"], [[_d(i["t"]), i["camera"], ("Serious: " if i["severity"] >= 3 else "") + i["title"]]
                                                         for i in d["top"]], [0.24, 0.22, 0.54])

    if "flights" in r["sections"]:
        d = n["flights"]
        L.heading(SECTIONS["flights"])
        L.para(f"{d['count']} flight{'' if d['count'] == 1 else 's'}, {_mins(d['minutes'])} in the air, {d['km']:.1f} km flown."
               + (f" {d['weather_overrides']} flight{'' if d['weather_overrides'] == 1 else 's'} despite the weather (chosen by a user)."
                  if d["weather_overrides"] else ""), 10, INK)
        if d["per_drone"]:
            L.table(["Drone", "Flights", "Time in the air", "Distance"],
                    [[x["drone"], x["n"], _mins(x["min"]), f"{x['km']:.1f} km"] for x in d["per_drone"]], [0.4, 0.15, 0.25, 0.2])

    if "drones_detected" in r["sections"]:
        d = n["drones_detected"]
        L.heading(SECTIONS["drones_detected"])
        if not d["alarms"]:
            L.para("No unknown drone was detected.", 10, INK)
        else:
            L.para(f"{d['alarms']} unknown-drone alarm{'' if d['alarms'] == 1 else 's'} ("
                   + ", ".join(f"{v} by {k}" for k, v in d["by_kind"].items()) + ").", 10, INK)
            L.table(["Detector", "Alarms"], [[k, v] for k, v in sorted(d["by_detector"].items(), key=lambda kv: -kv[1])], [0.7, 0.3])
            L.table(["When", "Detector", "What"], [[_d(e["t"]), e["detector"], e["text"]] for e in d["last"]], [0.24, 0.22, 0.54])

    if "alarms" in r["sections"]:
        d = n["alarms"]
        L.heading(SECTIONS["alarms"])
        L.para(f"{d['verified']} alarm{'' if d['verified'] == 1 else 's'} verified, {d['false']} marked false, "
               f"{d['sent']} sent to the monitoring centre.", 10, INK)

    if "uptime" in r["sections"]:
        d = n["uptime"]
        L.heading(SECTIONS["uptime"])
        L.para(("This PC was running " + f"{d['pc_percent']}% of the period." if d["pc_percent"] is not None
                else "No running time recorded yet for this period."), 10, INK)
        if d["cams_offline_min"]:
            L.table(["Camera", "Offline"], [[c, _mins(m)] for c, m in d["cams_offline_min"].items()], [0.6, 0.4])
        else:
            L.para("No camera went offline while the PC was running.", 10, INK)

    if "busiest" in r["sections"]:
        d = n["busiest"]
        L.heading(SECTIONS["busiest"])
        if d["cameras"]:
            L.table(["Camera", "People and vehicles seen"], [[c["camera"], c["n"]] for c in d["cameras"]], [0.6, 0.4])
        if d["peak_hour"] is not None:
            L.para(f"Busiest hour: {d['peak_hour']:02d}:00–{(d['peak_hour'] + 1) % 24:02d}:00.", 10, INK)
            L.need(120)
            top = max(d["hours"]) or 1
            bw = (L.right - L.left) / 24
            base = L.y + 90
            for h, v in enumerate(d["hours"]):
                bh = 80 * v / top
                if v:
                    pdf.rect(L.left + h * bw + 2, base - bh, bw - 4, bh, ACC)
                if h % 3 == 0:
                    pdf.text(L.left + h * bw + bw / 2, base + 11, f"{h:02d}", 7, color=MUTED, align="center")
            pdf.line(L.left, base, L.right, base, GRID)
            L.y = base + 22
        if not d["cameras"]:
            L.para("No people or vehicles were seen.", 10, INK)

    L.y += 8
    L.para("Numbers come from this PC's own records. Detections count each person or vehicle once per appearance on a camera. "
           "\"Before\" is the same length of time just before this period.", 8)
    return pdf.output()
