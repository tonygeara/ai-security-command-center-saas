"""Settings → Reports: daily / weekly / monthly reports with a PDF, sent to Telegram and kept on the PC."""
import json
import os
import time
from datetime import datetime

import pytest


@pytest.fixture
def rm(d):
    import reports
    return reports


def ts(y, mo, day, h=0, mi=0):
    return datetime(y, mo, day, h, mi).timestamp()


def test_settings_follow_the_old_morning_briefing_until_saved(rm, tmp_path):
    p = str(tmp_path / "r.json")
    s = rm.load_settings(p, legacy_briefing={"briefing_enabled": False, "briefing_time": "07:15"})
    assert s["daily"] == {"on": False, "time": "07:15"} and not s["weekly"]["on"] and not s["monthly"]["on"]
    assert rm.load_settings(p)["daily"]["on"]  # by default the daily report is on, like the briefing was
    s = rm.save_settings(p, {"weekly": {"on": True, "weekday": 9, "time": "25:00"}, "monthly": {"on": True, "day": 0},
                             "sections": {"flights": False}, "telegram": False})
    assert s["weekly"] == {"on": True, "time": "08:00", "weekday": 6} and s["monthly"]["day"] == 1
    assert s["sections"]["flights"] is False and s["sections"]["detections"] is True and s["telegram"] is False
    assert rm.load_settings(p) == s


def test_schedule_times_and_periods(rm):
    cfg = rm.clean_settings({"daily": {"on": True, "time": "08:00"}, "weekly": {"on": True, "weekday": 0, "time": "09:30"},
                             "monthly": {"on": True, "day": 31, "time": "07:00"}})
    now = ts(2026, 11, 28, 8, 5)  # a Saturday
    assert rm.last_moment("daily", cfg, now) == ts(2026, 11, 28, 8, 0)
    assert rm.last_moment("daily", cfg, ts(2026, 11, 28, 7, 59)) == ts(2026, 11, 27, 8, 0)
    assert rm.last_moment("weekly", cfg, now) == ts(2026, 11, 23, 9, 30)  # the Monday before
    assert rm.last_moment("monthly", cfg, now) == ts(2026, 10, 31, 7, 0)
    assert rm.last_moment("monthly", cfg, ts(2026, 3, 1, 12)) == ts(2026, 2, 28, 7, 0)  # day 31 in February: its last day
    assert rm.period("daily", ts(2026, 11, 28, 8)) == (ts(2026, 11, 27, 8), ts(2026, 11, 28, 8))
    assert rm.period("monthly", ts(2026, 3, 31, 8)) == (ts(2026, 2, 28, 8), ts(2026, 3, 31, 8))
    # Due: the daily one 5 minutes after its time; not again once sent; not 3 hours late (the PC was off).
    state = {"last": {"daily": ts(2026, 11, 27, 8), "weekly": ts(2026, 11, 23, 9, 30), "monthly": ts(2026, 10, 31, 7)}}
    assert rm.due(cfg, state, now) == [("daily", ts(2026, 11, 28, 8))]
    state["last"]["daily"] = ts(2026, 11, 28, 8)
    assert rm.due(cfg, state, now) == []
    assert rm.due(cfg, {"last": {"daily": 0, "weekly": ts(2026, 11, 23, 9, 30), "monthly": ts(2026, 10, 31, 7)}}, ts(2026, 11, 28, 11)) == []
    # Weekly: late by a day is still sent (the PC was off on Monday morning).
    assert rm.due(cfg, {"last": {"daily": 1e12, "weekly": 0, "monthly": 1e12}}, ts(2026, 11, 24, 10)) == [("weekly", ts(2026, 11, 23, 9, 30))]
    # Switching reports on after their time today does not send a late one.
    assert rm.due(cfg, rm.mark_handled(cfg, {}, now), now) == []
    assert rm.describe_schedule(cfg) == "daily at 08:00, weekly on Monday at 09:30, monthly on day 31 at 07:00"


def _data(start):
    h = 3600
    det = lambda t, label, cam="Gate": {"t": start + t, "kind": "detection", "camera": cam, "data": {"label": label}}
    return {
        "sightings": [{"t": start + h, "kind": "face", "name": "Rami", "id": "", "known": True},
                      {"t": start + 2 * h, "kind": "face", "name": "", "id": "", "known": False},
                      {"t": start + 3 * h, "kind": "plate", "name": "", "id": "123456", "known": False},
                      {"t": start + 4 * h, "kind": "plate", "name": "", "id": "123456", "known": False},
                      {"t": start + 5 * h, "kind": "plate", "name": "Boss", "id": "777", "known": True}],
        "items": [det(h, "person"), det(h + 60, "person"), det(2 * h, "car", "Car park"), det(2 * h + 5, "truck", "Car park"),
                  det(2 * h + 9, "car", "Car park"), {"t": start + 3 * h, "kind": "dispatch", "camera": "Gate", "data": {}}],
        "incidents": [{"updated": start + 3 * h, "camera": "Gate", "title": "Unknown face, drone sent", "severity": 3},
                      {"updated": start + 5 * h, "camera": "Car park", "title": "Vehicle seen", "severity": 1}],
        "audit": [{"t": start + 3 * h, "action": "drone: flight despite the weather"}, {"t": start + 4 * h, "action": "alarm verified"},
                  {"t": start + 4 * h, "action": "alarm marked false"}, {"t": start + 4 * h, "action": "alarm sent (webhook)"}],
        "flights": [{"slot": "drone-v1", "label": "Virtual 1", "start": start + h, "end": start + h + 600, "distance_m": 1500},
                    {"slot": "drone-v1", "label": "Virtual 1", "start": start + 2 * h, "end": start + 2 * h + 300, "distance_m": 500}],
        "detector_events": [{"t": start + 6 * h, "kind": "rf", "text": "Unknown drone heard", "detector_name": "North gate"},
                            {"t": start + 7 * h, "kind": "position", "text": "Unknown drone in range", "detector_name": "North gate"}],
        "uptime": [{"t": start + k * 600, "pc": 10, "cams_off": {"Car park": 10} if k == 3 else {}} for k in range(72)],
    }


def test_figures_pdf_and_telegram_text(rm):
    start = ts(2026, 11, 27, 8)
    end = start + 86400
    data = _data(start)
    data["items"].append({"t": start - 3600, "kind": "detection", "camera": "Gate", "data": {"label": "person"}})  # the day before
    r = rm.build("daily", start, end, data, rm.clean_settings({}), site="Warehouse PC", version="V11.25.0")
    n = r["now"]
    assert n["detections"]["people"] == 2 and n["detections"]["vehicles"] == 3 and n["detections"]["known_people"] == ["Rami"]
    assert n["detections"]["unknown_faces"] == 1 and n["detections"]["plates"] == 2 and n["detections"]["unknown_plates"] == 1
    assert n["detections"]["repeat_plates"] == [{"plate": "123456", "n": 2, "known": False, "name": ""}]
    assert (n["incidents"]["total"], n["incidents"]["high"], n["incidents"]["low"], n["incidents"]["drone_responses"]) == (2, 1, 1, 1)
    assert n["flights"]["count"] == 2 and n["flights"]["minutes"] == 15 and n["flights"]["km"] == 2 and n["flights"]["weather_overrides"] == 1
    assert n["drones_detected"]["alarms"] == 2 and n["drones_detected"]["by_kind"] == {"RF": 1, "position": 1}
    assert n["alarms"] == {"verified": 1, "false": 1, "sent": 1}
    assert n["uptime"]["pc_percent"] == 50.0 and n["uptime"]["cams_offline_min"] == {"Car park": 10}
    assert n["busiest"]["cameras"][0] == {"camera": "Car park", "n": 3} and n["busiest"]["peak_hour"] == time.localtime(start + 2 * 3600).tm_hour
    assert r["prev"]["detections"]["people"] == 1
    text = rm.text_summary(r)
    assert "Daily report · Warehouse PC" in text and "People seen: 2 (+100% vs before)" in text and "123456 ×2" in text
    assert "Alarms: 1 verified, 1 false" in text and "offline: Car park 10 min" in text
    pdf = rm.pdf_bytes(r)
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF") and b"/Count" in pdf
    assert rm.file_name(r) == "daily-report-" + time.strftime("%Y-%m-%d-%H%M", time.localtime(end)) + ".pdf"
    # Sections can be left out.
    r2 = rm.build("weekly", start, end, data, rm.clean_settings({"sections": {"flights": False, "detections": False}}))
    assert "Drone flights" not in rm.text_summary(r2) and "People seen" not in rm.text_summary(r2)
    assert rm.pdf_bytes(r2).startswith(b"%PDF")


def test_empty_period_still_makes_a_report(rm):
    r = rm.build("monthly", 0, 86400 * 30, {}, rm.clean_settings({}))
    assert "Unknown drones: 0 (same as before)" in rm.text_summary(r)
    assert rm.pdf_bytes(r).startswith(b"%PDF")


def test_send_now_saves_and_sends_even_with_intruder_warnings_only(d, client, monkeypatch):
    sent = []
    monkeypatch.setattr(d, "send_report_telegram", lambda text, pdf, name: sent.append((text, pdf, name)) or True)
    monkeypatch.setattr(d, "telegram_intruders_only", lambda: True)
    r = client.post("/api/reports", json={"daily": {"on": True, "time": "06:30"}, "weekly": {"on": True, "weekday": 4, "time": "18:00"},
                                          "telegram": True}).get_json()
    assert r["ok"] and r["schedule"] == "daily at 06:30, weekly on Friday at 18:00"
    st = json.load(open(d.REPORTS_STATE_FILE))
    assert set(st["last"]) == {"daily", "weekly", "monthly"}  # nothing is sent late for times already passed
    r = client.post("/api/reports/send", json={"kind": "weekly"}).get_json()
    assert r["ok"] and r["telegram"] and "sent to Telegram" in r["message"]
    text, pdf, name = sent[-1]
    assert text.startswith("📊 Weekly report") and pdf.startswith(b"%PDF") and name.startswith("weekly-report-")
    g = client.get("/api/reports").get_json()
    assert g["settings"]["weekly"]["weekday"] == 4 and any(x["name"] == name for x in g["reports"])
    f = client.get(f"/api/reports/file/{name}")
    assert f.status_code == 200 and f.data.startswith(b"%PDF") and f.mimetype == "application/pdf"
    assert client.get("/api/reports/file/..%2Fsecret.pdf").status_code == 404
    assert client.get("/api/reports/file/daily-report-2000-01-01-0000.pdf").status_code == 404
    p = client.get("/api/reports/preview?kind=monthly")
    assert p.status_code == 200 and p.data.startswith(b"%PDF")
    assert client.post("/api/reports/send", json={"kind": "yearly"}).status_code == 400
    # Telegram off: kept on the PC only.
    client.post("/api/reports", json={"telegram": False})
    n = len(sent)
    r = client.post("/api/reports/send", json={"kind": "daily"}).get_json()
    assert r["ok"] and not r["telegram"] and len(sent) == n and r["message"].endswith("kept on this PC.")
    # The old "Send briefing now" button sends the daily report now.
    client.post("/api/reports", json={"telegram": True})
    assert client.post("/api/assistant/briefing").get_json()["ok"] and sent[-1][2].startswith("daily-report-")


def test_flights_and_unknown_drones_are_logged_for_the_reports(d, monkeypatch):
    tel = {"flying": True, "lat": 33.0, "lon": 35.0, "altitude": 30}
    monkeypatch.setattr(d, "drone_slots", lambda: ["drone-v9"])
    monkeypatch.setattr(d, "get_link", lambda s: {"telemetry": tel})
    monkeypatch.setattr(d, "link_fresh", lambda s, sec=5: True)
    monkeypatch.setattr(d, "drone_label", lambda s: "Virtual 9")
    t0 = time.time()
    before = len(d._report_read(d.FLIGHT_LOG_FILE, 0, "start"))
    d._track_flights(t0)
    tel.update(lat=33.001, altitude=42)  # ~111 m north
    d._track_flights(t0 + 30)
    tel["flying"] = False
    d._track_flights(t0 + 40)
    rows = d._report_read(d.FLIGHT_LOG_FILE, 0, "start")
    assert len(rows) == before + 1
    f = rows[-1]
    assert f["label"] == "Virtual 9" and f["end"] - f["start"] == pytest.approx(30, abs=0.2) and 100 < f["distance_m"] < 125 and f["max_alt"] == 42
    # A hop of a few seconds is not a flight.
    tel["flying"] = True
    d._track_flights(t0 + 100)
    tel["flying"] = False
    d._track_flights(t0 + 105)
    assert len(d._report_read(d.FLIGHT_LOG_FILE, 0, "start")) == before + 1
    # Unknown-drone alarms are kept on disk.
    monkeypatch.setattr(d, "speak", lambda *a, **k: None)
    monkeypatch.setattr(d, "warning_sound", lambda *a, **k: None)
    d._detector_event({"id": "abc", "name": "North gate"}, "rf", "Unknown drone heard by North gate")
    assert d._report_read(d.DETECTOR_LOG_FILE, t0 - 1)[-1]["detector_name"] == "North gate"
    data = d._report_data(t0 - 60)
    assert any(x["label"] == "Virtual 9" for x in data["flights"]) and data["detector_events"]


def test_reports_page_and_permissions(client):
    html = client.get("/reports").get_data(as_text=True)
    for s in ("DAILY", "WEEKLY", "MONTHLY", "Send now", "Preview", "Saved reports", "What goes in"):
        assert s in html
    assert 'href="/reports"' in client.get("/settings").get_data(as_text=True)
    assert "Settings → Reports" in client.get("/drone-control").get_data(as_text=True)
    import users
    assert users.allowed("operator", "POST", "/api/reports/send") and not users.allowed("operator", "POST", "/api/reports")
    assert not users.allowed("viewer", "POST", "/api/reports/send") and users.allowed("viewer", "GET", "/api/reports")


def test_reports_reach_telegram_with_intruder_warnings_only_on(d, monkeypatch):
    calls = []
    monkeypatch.setattr(d, "telegram_intruders_only", lambda: True)
    monkeypatch.setattr(d, "_tg", lambda method, **data: calls.append((method, data)) or {"ok": True})
    assert d.send_report_telegram("📊 Daily report", b"%PDF-1.4 x", "daily-report-2026-11-28-0800.pdf")
    assert [c[0] for c in calls] == ["sendMessage", "sendDocument"]
    assert calls[1][1]["files"]["document"][0] == "daily-report-2026-11-28-0800.pdf"
    # An ordinary message is still held back by "intruder warnings only".
    assert d._send_telegram_real("Route finished") is None
