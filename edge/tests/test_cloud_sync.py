"""Phone access: what the PC sends to the cloud, and live pictures only while someone watches."""
import base64
import os
import sys

import pytest

from conftest import APP

sys.path.insert(0, os.path.abspath(APP))
import cloud_sync  # noqa: E402
import incidents  # noqa: E402
import store  # noqa: E402


@pytest.fixture
def cs(tmp_path):
    s = store.Store(str(tmp_path / "c.db"))
    inc = incidents.Incidents(s)
    calls, live = [], []
    on = {"v": True}

    def post(body):
        calls.append(body)
        if body["action"] == "poll":
            return {"ok": True, "live": live}
        return {"ok": True}
    c = cloud_sync.CloudSync("https://x/edge-sync", lambda: "t" * 40, lambda: on["v"], inc,
                             lambda snap: b"\xff\xd8photo" if snap == "a.jpg" else None,
                             lambda cam: b"\xff\xd8live-" + cam.encode(), lambda: ["front", "gate"], post=post)
    yield c, inc, s, calls, live, on
    s.close()


def test_only_unknown_and_responses_are_sent_once_with_one_photo(cs):
    c, inc, s, calls, live, on = cs
    inc.on_message({"kind": "detection", "t": 1000, "camera": "front", "label": "person", "object_id": "a"})  # activity only
    eid = s.add_event("UNKNOWN FACE", camera="gate", snapshot="a.jpg", t=1010)
    inc.on_message({"kind": "event", "t": 1010, "camera": "gate", "type": "UNKNOWN FACE", "event_id": eid, "snapshot": "a.jpg"})
    assert c.step(now=2000)
    sent = [b for b in calls if b["action"] == "incidents"]
    assert len(sent) == 1 and [i["camera"] for i in sent[0]["incidents"]] == ["gate"] and sent[0]["cameras"] == ["front", "gate"]
    photos = [b for b in calls if b["action"] == "photo"]
    assert len(photos) == 1 and base64.b64decode(photos[0]["jpeg"]) == b"\xff\xd8photo"
    calls.clear()
    assert c.step(now=2020)  # nothing changed: nothing re-sent
    assert [b["action"] for b in calls] == ["poll"]
    inc.on_message({"kind": "dispatch", "t": 1100, "camera": "gate", "drone": "drone", "by": "auto"})
    c.step(now=2040)
    assert [b["action"] for b in calls if b["action"] != "poll"] == ["incidents"]  # updated incident, photo not again


def test_nothing_leaves_the_pc_when_off(cs):
    c, inc, s, calls, live, on = cs
    on["v"] = False
    inc.on_message({"kind": "dispatch", "t": 1100, "camera": "gate", "drone": "drone", "by": "auto"})
    assert c.step(now=2000) is False and calls == []


def test_live_pictures_only_while_watched(cs):
    c, inc, s, calls, live, on = cs
    live.append({"id": "r1", "camera": "front", "seconds_left": 100})
    c.step(now=5000)
    c.send_live_frames(now=5003)
    frames = [b for b in calls if b["action"] == "live"]
    assert len(frames) == 1 and frames[0]["request_id"] == "r1" and base64.b64decode(frames[0]["jpeg"]) == b"\xff\xd8live-front"
    calls.clear()
    c.send_live_frames(now=5101)  # request ran out
    assert calls == [] and c.live == {}


def test_failures_are_reported_not_raised(cs):
    c, inc, s, calls, live, on = cs
    c._post = lambda body: (_ for _ in ()).throw(RuntimeError("cloud said 500"))
    inc.on_message({"kind": "dispatch", "t": 1100, "camera": "gate", "drone": "drone", "by": "auto"})
    assert c.step(now=2000) is False and c.state["ok"] is False and "500" in c.state["error"]


def test_status_endpoint_and_off_by_default(d, client):
    assert d._load_customer_settings()["cloud_incidents"] is False
    st = client.get("/api/cloud/sync").get_json()
    assert st["ok"] and st["enabled"] is False
