"""After each patrol a short report goes to Telegram: time, laps, battery used, what the drone saw, photos."""
from conftest import offset, wait_until


def test_report_after_patrol(d, client, fleet, monkeypatch):
    (v1,) = fleet(1)
    albums = []
    monkeypatch.setattr(d, "_drone_snapshot", lambda slot=None: b"\xff\xd8photo")
    monkeypatch.setattr(d, "send_telegram_album", lambda photos, caption="": albums.append((len(photos), caption)))
    route = {"name": "yard", "points": [offset(15, 0), offset(15, 15)], "alt": 12, "speed": 8, "pause": 1, "end": "hover"}
    assert client.post(f"/api/routes/fly?drone={v1}", json=route).get_json()["ok"]
    assert wait_until(lambda: d.run_of(v1) and d.run_of(v1).get("phase") == "pause", 60)
    d.note_drone_detection(v1, "person", "p1")
    d.note_drone_detection(v1, "person", "p1")  # same object again: counted once
    d.note_drone_detection(v1, "truck", "t1")
    d.note_drone_detection(v1, "dog", "x")  # not reported
    assert wait_until(lambda: any("Patrol report" in t and "“yard”" in t for t in d.sent), 90)
    report = next(t for t in d.sent if "Patrol report" in t and "“yard”" in t)
    assert "“yard”" in report and "✅ Complete" in report and "1 lap" in report and "2 stops" in report
    assert "Virtual 1:" in report and "% used" in report
    assert "1 person, 1 vehicle" in report
    assert albums and albums[0][0] >= 2  # stop photos + the sightings
    run = client.get(f"/api/routes?drone={v1}").get_json()["run"]
    assert "Patrol report" in run["report"] and "photos" not in run


def test_report_when_stopped(d, client, fleet, monkeypatch):
    (v1,) = fleet(1)
    monkeypatch.setattr(d, "send_telegram_album", lambda photos, caption="": None)
    route = {"name": "loop", "points": [offset(15, 0), offset(15, 15)], "alt": 12, "speed": 8, "loop": True}
    assert client.post(f"/api/routes/fly?drone={v1}", json=route).get_json()["ok"]
    assert wait_until(lambda: d.run_of(v1) and d.run_of(v1).get("index", 0) >= 1, 30)
    client.post(f"/api/routes/stop?drone={v1}")
    assert wait_until(lambda: any("Patrol report" in t and "“loop”" in t for t in d.sent), 30)
    report = next(t for t in d.sent if "“loop”" in t and "Patrol report" in t)
    assert "Stopped from the PC" in report and "Nothing seen" in report
