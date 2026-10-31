"""Deleting one event, and clearing all, removes the rows and their snapshots."""
import csv
import os


def write_events(d, n):
    os.makedirs(d.EVENT_FOLDER, exist_ok=True)
    rows = []
    for i in range(n):
        snap = os.path.join(d.EVENT_FOLDER, f"test_{i}.jpg")
        open(snap, "wb").write(b"\xff\xd8")
        rows.append({"Date": "2026-10-30", "Time": f"10:00:0{i}", "Type": "UNKNOWN FACE", "Name": f"n{i}", "Identifier": f"id{i}", "Snapshot": snap})
    with open(d.EVENT_LOG, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Date", "Time", "Type", "Name", "Identifier", "Snapshot"])
        w.writeheader()
        w.writerows(rows)
    return rows


def test_delete_one_event(d, client):
    rows = write_events(d, 3)
    newest = rows[-1]
    r = client.delete("/api/events/0", json={"key": d.event_key(newest)}).get_json()
    assert r["ok"]
    left = list(csv.DictReader(open(d.EVENT_LOG, encoding="utf-8")))
    assert [x["Name"] for x in left] == ["n0", "n1"] and not os.path.exists(newest["Snapshot"])


def test_clear_all(d, client):
    rows = write_events(d, 2)
    assert client.delete("/api/events").get_json()["ok"]
    assert list(csv.DictReader(open(d.EVENT_LOG, encoding="utf-8"))) == []
    assert not any(os.path.exists(r["Snapshot"]) for r in rows)
