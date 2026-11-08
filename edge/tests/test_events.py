"""Deleting one event, and clearing all, removes the rows and their snapshots."""
import os
import sys

from conftest import APP

sys.path.insert(0, os.path.abspath(APP))


def write_events(d, n):
    os.makedirs(d.EVENT_FOLDER, exist_ok=True)
    rows = []
    for i in range(n):
        snap = os.path.join(d.EVENT_FOLDER, f"test_{i}.jpg")
        open(snap, "wb").write(b"\xff\xd8")
        rows.append({"Date": "2026-10-30", "Time": f"10:00:0{i}", "Type": "UNKNOWN FACE", "Name": f"n{i}", "Identifier": f"id{i}", "Snapshot": snap})
    d.STORE.clear_events()
    for r in rows:
        d.STORE.add_event_row(r)
    return [d.STORE.events()[len(rows) - 1 - i] for i in range(len(rows))]  # as stored, oldest first


def test_delete_one_event(d, client):
    rows = write_events(d, 3)
    newest = rows[-1]
    r = client.delete("/api/events/0", json={"key": d.event_key(newest)}).get_json()
    assert r["ok"]
    left = d.STORE.events()
    assert [x["Name"] for x in left] == ["n1", "n0"] and not os.path.exists(newest["Snapshot"])


def test_clear_all(d, client):
    rows = write_events(d, 2)
    assert client.delete("/api/events").get_json()["ok"]
    assert d.STORE.events() == []
    assert not any(os.path.exists(r["Snapshot"]) for r in rows)


def test_old_files_are_imported_once(tmp_path):
    import csv
    import json
    import store
    ev = tmp_path / "event_history.csv"
    with open(ev, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Date", "Time", "Type", "Name", "Identifier", "Snapshot"])
        w.writeheader()
        w.writerow({"Date": "2026-10-30", "Time": "10:00:01", "Type": "UNKNOWN PLATE", "Identifier": "ABC123"})
        w.writerow({"Date": "bad", "Time": "", "Type": "x"})
    si = tmp_path / "sightings.jsonl"
    si.write_text(json.dumps({"t": 1790000000, "kind": "face", "name": "Kim", "id": "", "camera": "front", "known": True}) + "\n")
    s = store.Store(str(tmp_path / "db.sqlite"))
    assert s.migrate(event_csv=str(ev), sightings_jsonl=str(si)) == {"events": 1, "sightings": 1}
    assert not ev.exists() and (tmp_path / "event_history.csv.migrated").exists()
    assert s.events()[0]["Identifier"] == "ABC123" and s.events()[0]["Time"] == "10:00:01"
    assert s.sightings(0, 2e9)[0]["name"] == "Kim"
    ev.write_text("Date,Time\n")  # a file that reappears is not imported again
    assert s.migrate(event_csv=str(ev)) == {}
    s.close()
