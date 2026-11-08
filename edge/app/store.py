"""The edge app's database: one SQLite file (ai_security.db in the data folder).

Holds the event history, the sightings of faces and plates, the audit log, the incidents and the
drones' GPS tracks during responses.
It replaces event_history.csv, sightings.jsonl and audit_log.jsonl: on first start those are
imported once and renamed to *.migrated (kept, never deleted).

WAL mode: the dashboard's many threads read while one writes, and a power cut loses at most the
last write, never the whole history (rewriting a CSV could).

Event rows are returned in the shape the dashboard always used for the CSV:
    {"id", "t", "Date", "Time", "Type", "Name", "Identifier", "Camera", "Snapshot", "incident"}
"""
import csv
import json
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, t REAL NOT NULL, type TEXT, name TEXT, identifier TEXT, camera TEXT,
    snapshot TEXT, incident INTEGER);
CREATE INDEX IF NOT EXISTS events_t ON events(t);
CREATE TABLE IF NOT EXISTS sightings (
    id INTEGER PRIMARY KEY, t REAL NOT NULL, kind TEXT, name TEXT, ident TEXT, camera TEXT, known INTEGER);
CREATE INDEX IF NOT EXISTS sightings_t ON sightings(t);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, t REAL NOT NULL, user TEXT, source TEXT, action TEXT, target TEXT,
    detail TEXT, result TEXT, prev TEXT, hash TEXT);
CREATE INDEX IF NOT EXISTS audit_t ON audit(t);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY, started REAL NOT NULL, updated REAL NOT NULL, camera TEXT, title TEXT,
    severity INTEGER DEFAULT 1, status TEXT DEFAULT 'open', summary TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS incidents_updated ON incidents(updated);
CREATE TABLE IF NOT EXISTS incident_items (
    id INTEGER PRIMARY KEY, incident INTEGER NOT NULL, t REAL NOT NULL, kind TEXT, text TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS incident_items_incident ON incident_items(incident);
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY, incident INTEGER NOT NULL, t REAL NOT NULL, drone TEXT, lat REAL, lon REAL, alt REAL);
CREATE INDEX IF NOT EXISTS tracks_incident ON tracks(incident);
"""


def _event_dict(r):
    t = r["t"]
    lt = time.localtime(t)
    return {"id": r["id"], "t": t, "Date": time.strftime("%Y-%m-%d", lt), "Time": time.strftime("%H:%M:%S", lt),
            "Type": r["type"] or "", "Name": r["name"] or "", "Identifier": r["identifier"] or "",
            "Camera": r["camera"] or "", "Snapshot": r["snapshot"] or "", "incident": r["incident"]}


def _parse_date_time(date, time_text):
    try:
        return time.mktime(time.strptime(f"{date} {time_text}", "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError):
        return None


class Store:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.executescript(SCHEMA)
            self.db.commit()

    # ---- helpers ----
    def q(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def x(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def meta(self, key, value=None):
        if value is None:
            rows = self.q("SELECT value FROM meta WHERE key=?", (key,))
            return rows[0]["value"] if rows else None
        self.x("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, str(value)))

    def close(self):
        with self.lock:
            self.db.close()

    # ---- events ----
    def add_event(self, type_, name="", identifier="", camera="", snapshot="", t=None, incident=None):
        cur = self.x("INSERT INTO events(t, type, name, identifier, camera, snapshot, incident) VALUES(?,?,?,?,?,?,?)",
                     (t or time.time(), str(type_ or ""), str(name or ""), str(identifier or ""), str(camera or ""),
                      str(snapshot or ""), incident))
        return cur.lastrowid

    def add_event_row(self, row, incident=None):
        """Add a row in the old CSV shape (Date/Time/Type/...)."""
        t = _parse_date_time(row.get("Date"), row.get("Time")) or time.time()
        return self.add_event(row.get("Type"), row.get("Name"), row.get("Identifier"), row.get("Camera"),
                              row.get("Snapshot"), t=t, incident=incident)

    def events(self, limit=None, since=None, until=None):
        """Newest first."""
        sql, args = "SELECT * FROM events WHERE t >= ? AND t <= ? ORDER BY t DESC, id DESC", [since or 0, until or 4e9]
        if limit is not None:
            sql += " LIMIT ?"
            args.append(int(limit))
        return [_event_dict(r) for r in self.q(sql, args)]

    def event(self, event_id):
        rows = self.q("SELECT * FROM events WHERE id=?", (event_id,))
        return _event_dict(rows[0]) if rows else None

    def delete_event(self, event_id):
        self.x("DELETE FROM events WHERE id=?", (event_id,))

    def clear_events(self):
        """Delete every event; returns their snapshot paths so the files can go too."""
        with self.lock:
            snaps = [r["snapshot"] for r in self.q("SELECT snapshot FROM events")]
            self.x("DELETE FROM events")
        return snaps

    def prune_events(self, before):
        with self.lock:
            n = self.q("SELECT COUNT(*) AS n FROM events WHERE t < ?", (before,))[0]["n"]
            self.x("DELETE FROM events WHERE t < ?", (before,))
        return n

    # ---- sightings ----
    def add_sighting(self, kind, name, ident, camera, known=True, t=None):
        self.x("INSERT INTO sightings(t, kind, name, ident, camera, known) VALUES(?,?,?,?,?,?)",
               (t or time.time(), kind, str(name or ""), str(ident or ""), str(camera or ""), 1 if known else 0))

    def sightings(self, since, until):
        return [{"t": r["t"], "kind": r["kind"], "name": r["name"], "id": r["ident"], "camera": r["camera"],
                 "known": bool(r["known"])}
                for r in self.q("SELECT * FROM sightings WHERE t >= ? AND t <= ? ORDER BY t", (since, until))]

    def prune_sightings(self, before):
        self.x("DELETE FROM sightings WHERE t < ?", (before,))

    # ---- one-time import of the old files ----
    def migrate(self, event_csv=None, sightings_jsonl=None, audit_jsonl=None):
        """Import the files the app used before the database (once each); returns counts."""
        done = {}
        for name, path, fn in (("events", event_csv, self._import_events), ("sightings", sightings_jsonl, self._import_sightings),
                               ("audit", audit_jsonl, self._import_audit)):
            if not path or not os.path.exists(path) or self.meta(f"migrated_{name}"):
                continue
            try:
                with self.lock:
                    done[name] = fn(path)
                    self.meta(f"migrated_{name}", int(time.time()))
                os.replace(path, path + ".migrated")
            except Exception as e:  # leave the file where it is; the app keeps working on the new store
                print(f"Could not import {path}: {e}")
        return done

    def _import_events(self, path):
        n = 0
        with open(path, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                t = _parse_date_time(r.get("Date"), r.get("Time"))
                if t is None:
                    continue
                self.db.execute("INSERT INTO events(t, type, name, identifier, camera, snapshot) VALUES(?,?,?,?,?,?)",
                                (t, r.get("Type", ""), r.get("Name", ""), r.get("Identifier", ""), r.get("Camera", ""),
                                 r.get("Snapshot", "")))
                n += 1
        self.db.commit()
        return n

    def _import_sightings(self, path):
        n = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                self.db.execute("INSERT INTO sightings(t, kind, name, ident, camera, known) VALUES(?,?,?,?,?,?)",
                                (r.get("t", 0), r.get("kind", ""), r.get("name", ""), r.get("id", ""), r.get("camera", ""),
                                 1 if r.get("known") else 0))
                n += 1
        self.db.commit()
        return n

    def _import_audit(self, path):
        n = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                self.db.execute("INSERT INTO audit(t, user, source, action, target, detail, result, prev, hash) "
                                "VALUES(?,?,?,?,?,?,?,?,?)",
                                (r.get("t"), r.get("user", ""), r.get("source", ""), r.get("action", ""), r.get("target", ""),
                                 json.dumps(r.get("detail") or {}, ensure_ascii=False), r.get("result", ""),
                                 r.get("prev", ""), r.get("hash", "")))
                n += 1
        self.db.commit()
        return n
