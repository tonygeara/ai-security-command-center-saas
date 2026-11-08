"""The event pipeline and incidents: one story per camera, severity only goes up."""
import os
import sys

import pytest

from conftest import APP, wait_until

sys.path.insert(0, os.path.abspath(APP))
import bus  # noqa: E402
import incidents  # noqa: E402
import store  # noqa: E402


@pytest.fixture
def inc(tmp_path):
    s = store.Store(str(tmp_path / "i.db"))
    yield incidents.Incidents(s, gap=300), s
    s.close()


def msg(kind, t, **kw):
    return {"kind": kind, "t": t, **kw}


def test_one_story_per_camera_and_severity_goes_up(inc):
    i, s = inc
    i.on_message(msg("detection", 100, camera="front", label="person", object_id="a"))
    i.on_message(msg("detection", 101, camera="front", label="person", object_id="a"))  # same object: once
    i.on_message(msg("detection", 102, camera="front", label="car", object_id="b", stationary=True))  # parked: ignored
    eid = s.add_event("UNKNOWN FACE", camera="front", snapshot="x.jpg", t=150)
    i.on_message(msg("event", 150, camera="front", type="UNKNOWN FACE", event_id=eid, snapshot="x.jpg"))
    i.on_message(msg("dispatch", 160, camera="front", drone="drone", drone_label="Drone 1", by="auto: person seen"))
    i.on_message(msg("drone", 170, camera="front", drone="drone", text="Arrived, hovering"))
    i.on_message(msg("detection", 120, camera="back", label="car", object_id="c"))
    rows = i.list(0)
    assert len(rows) == 2
    front = next(r for r in rows if r["camera"] == "front")
    assert front["severity"] == 3 and front["level"] == "response" and front["title"] == "Drone 1 sent (auto: person seen) at front"
    full = i.get(front["id"])
    assert [x["kind"] for x in full["items"]] == ["detection", "event", "dispatch", "drone"]
    assert full["events"][0]["id"] == eid and s.event(eid)["incident"] == front["id"]


def test_quiet_gap_starts_a_new_incident_and_late_drone_chatter_is_dropped(inc):
    i, _ = inc
    i.on_message(msg("detection", 100, camera="front", label="person", object_id="a"))
    i.on_message(msg("detection", 100 + 301, camera="front", label="person", object_id="b"))
    assert len(i.list(0)) == 2
    i.close_stale(now=2000)
    i.on_message(msg("drone", 2001, camera="front", drone="drone", text="Landed"))  # nothing open: no new incident
    assert len(i.list(0)) == 2 and all(r["status"] == "closed" for r in i.list(0))


def test_known_sightings_join_and_unknown_wait_for_their_event(inc):
    i, _ = inc
    i.on_message(msg("sighting", 100, camera="gate", sighting="plate", identifier="ABC123", name="Boss car", known=True))
    i.on_message(msg("sighting", 110, camera="gate", sighting="face", name="", known=False))
    (r,) = i.list(0)
    assert r["severity"] == 1 and [x["text"] for x in i.get(r["id"])["items"]] == ["Known vehicle: Boss car"]


def test_a_failing_subscriber_does_not_stop_the_others():
    b = bus.Bus("test")
    got = []
    b.subscribe("x", lambda m: 1 / 0)
    b.subscribe("x", lambda m: got.append(m["n"]))
    for n in range(3):
        b.publish("x", n=n)
    assert b.flush() and got == [0, 1, 2]


def test_dashboard_pipeline_feeds_incidents_and_auto_dispatch(d, client, monkeypatch):
    calls = []
    monkeypatch.setattr(d, "auto_dispatch_check", lambda *a: calls.append(a))
    d.PIPELINE.publish("detection", camera="pipecam", label="person", object_id="p1", stationary=False)
    d._append_event_row({"Date": "2026-11-08", "Time": "12:00:00", "Type": "UNKNOWN PLATE", "Identifier": "XYZ9",
                         "Camera": "pipecam", "Snapshot": ""})
    assert d.PIPELINE.flush()
    assert wait_until(lambda: calls, 5) and calls[0][:2] == ("pipecam", "person")
    found = [i for i in client.get("/api/incidents?days=3650&min=1").get_json()["incidents"] if i["camera"] == "pipecam"]
    assert found and found[0]["level"] == "unknown"
    inc = client.get(f"/api/incidents/{found[0]['id']}").get_json()["incident"]
    assert {x["kind"] for x in inc["items"]} == {"detection", "event"}
    assert client.post(f"/api/incidents/{found[0]['id']}", json={"status": "reviewed", "note": "checked"}).get_json()["ok"]
    assert client.get(f"/api/incidents/{found[0]['id']}").get_json()["incident"]["status"] == "reviewed"
    assert client.post("/api/incidents/999999", json={"status": "reviewed"}).status_code == 404
    assert client.get("/incidents").status_code == 200
