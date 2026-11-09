"""Casing and unusual-activity warnings, and alerts going through the pipeline."""
import os
import sys

import pytest

from conftest import APP, wait_until

sys.path.insert(0, os.path.abspath(APP))
import incidents  # noqa: E402
import patterns  # noqa: E402
import store  # noqa: E402

H = 3600
T0 = 1_790_000_000 - (1_790_000_000 % (7 * 86400)) + 30 * 86400  # a fixed hour start, weeks after the epoch


@pytest.fixture
def env(tmp_path):
    s = store.Store(str(tmp_path / "p.db"))
    cfg = dict(patterns.DEFAULTS)
    sent = []
    p = patterns.Patterns(s, lambda: cfg, lambda kind, **m: sent.append({"kind": kind, **m}))
    yield p, s, cfg, sent
    s.close()


def plate(p, s, t, ident, camera="front", known=False):
    s.add_sighting("plate", "", ident, camera, known=known, t=t)
    p.on_sighting({"kind": "sighting", "t": t, "sighting": "plate", "identifier": ident, "camera": camera, "known": known})


def test_casing_after_three_separate_visits(env):
    p, s, cfg, sent = env
    plate(p, s, T0, "ABC-123")
    plate(p, s, T0 + 60, "ABC123", camera="gate")  # same pass, second camera: same visit
    plate(p, s, T0 + 2 * H, "abc 123")
    assert not sent
    plate(p, s, T0 + 5 * H, "ABC123")
    (a,) = sent
    assert a["alert"] == "casing" and a["plate"] == "ABC123" and a["visits"] == 3 and "front/gate" in a["text"]
    plate(p, s, T0 + 6 * H, "ABC123")
    assert len(sent) == 1  # once per window


def test_no_casing_for_known_plates_spread_out_visits_or_when_off(env):
    p, s, cfg, sent = env
    for i in range(4):
        plate(p, s, T0 + i * H, "OWN1", known=True)
    for i in range(3):
        plate(p, s, T0 + i * 13 * H, "FAR1")  # 3 visits but over 26 h
    cfg["casing_alerts"] = False
    for i in range(3):
        plate(p, s, T0 + i * H, "OFF1")
    assert sent == []


def detections(p, camera, t0, n, prefix):
    for i in range(n):
        p.on_detection({"kind": "detection", "t": t0 + i * 30, "camera": camera, "label": "person", "object_id": f"{prefix}{i}"})


def test_unusual_activity_learns_then_warns(env, tmp_path):
    p, s, cfg, sent = env
    inc = incidents.Incidents(s)
    detections(p, "yard", T0, 20, "early")  # no history: learning, no warning
    assert sent == []
    for week in (1, 2, 3):  # usual: 1 person in this hour on this weekday
        inc.on_message({"kind": "detection", "t": T0 - week * 7 * 86400 + 60, "camera": "yard", "label": "person", "object_id": f"w{week}"})
    p2 = patterns.Patterns(s, lambda: cfg, lambda kind, **m: sent.append({"kind": kind, **m}))
    detections(p2, "yard", T0, 5, "a")  # 5 people: under 3x usual + 3 = 6
    assert sent == []
    detections(p2, "yard", T0 + 200, 1, "b")
    (a,) = sent
    assert a["alert"] == "unusual" and a["count"] == 6 and a["usual"] == 1
    detections(p2, "yard", T0 + 300, 5, "c")
    assert len(sent) == 1  # once per camera and hour


def test_alerts_reach_telegram_and_the_incident(d, client, monkeypatch):
    got = []
    monkeypatch.setattr(d, "queue_telegram_alert", lambda kind, text, key, snapshot_bytes=None, buttons=None: got.append((kind, text, key)))
    for i, cam in enumerate(("patcam", "patcam2", "patcam")):
        d._sighting_last.clear()
        d.record_sighting("plate", "", "ZZ9PLUR", cam, object_id=f"o{i}", known=False)
        d.PIPELINE.flush()
        if i < 2:  # make each sighting its own visit
            d.STORE.x("UPDATE sightings SET t = t - ? WHERE ident = 'ZZ9PLUR'", (3600,))
    assert wait_until(lambda: any(k == "casing" for k, _, _ in got), 5)
    inc = [i for i in client.get("/api/incidents?days=1&min=2").get_json()["incidents"] if i["camera"] == "patcam"]
    assert inc and any(x["kind"] == "pattern" for x in client.get(f"/api/incidents/{inc[0]['id']}").get_json()["incident"]["items"])
    d.PIPELINE.publish("alert", alert="unknown_face", camera="front", text="⚠️ UNKNOWN PERSON", key="unknown_face:1")
    d.PIPELINE.flush()
    assert ("unknown_face", "⚠️ UNKNOWN PERSON", "unknown_face:1") in got
