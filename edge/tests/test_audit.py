"""Audit log: drone actions and changes are recorded with who did them, and tampering shows."""
import json
import os
import sys

import pytest

from conftest import APP

sys.path.insert(0, os.path.abspath(APP))
import audit  # noqa: E402


@pytest.fixture
def fresh_log(d, tmp_path, monkeypatch):
    path = str(tmp_path / "audit_log.jsonl")
    monkeypatch.setattr(d, "AUDIT_FILE", path)
    audit._last.pop(path, None)
    return path


def test_chain_detects_edited_and_deleted_lines(tmp_path):
    path = str(tmp_path / "a.jsonl")
    for i in range(4):
        audit.record(path, f"action {i}", user="boss", detail={"n": i, "password": "hunter22"})
    assert audit.verify(path) == (True, 4, 0)
    rows = audit.read(path)
    assert rows[0]["action"] == "action 3" and rows[0]["detail"]["password"] == "•••"
    lines = open(path, encoding="utf-8").read().splitlines()
    edited = json.loads(lines[1]); edited["user"] = "someone else"
    open(path, "w", encoding="utf-8").write("\n".join([lines[0], json.dumps(edited)] + lines[2:]) + "\n")
    assert audit.verify(path) == (False, 1, 2)
    open(path, "w", encoding="utf-8").write("\n".join([lines[0]] + lines[2:]) + "\n")
    assert audit.verify(path)[0] is False
    audit._last.pop(path, None)


def test_csv_is_safe_for_spreadsheets(tmp_path):
    path = str(tmp_path / "a.jsonl")
    audit.record(path, "=HYPERLINK(\"x\")", user="@boss")
    text = audit.to_csv(audit.read(path))
    assert "'=HYPERLINK" in text and "'@boss" in text
    audit._last.pop(path, None)


def test_drone_actions_are_logged_with_who_did_them(d, client, fleet, fresh_log):
    (v1,) = fleet(1)
    client.post(f"/api/drone/command?drone={v1}", json={"cmd": "hover"})
    for _ in range(5):
        client.post(f"/api/drone/stick?drone={v1}", json={"lx": 0, "ly": 0, "rx": 0, "ry": 0})
    rows = audit.read(fresh_log)
    asked = [r for r in rows if r["action"] == "POST /api/drone/command"]
    assert asked and asked[0]["target"] == v1 and asked[0]["source"] == "dashboard" and asked[0]["detail"]["cmd"] == "hover"
    assert any(r["action"].startswith("drone: hover") and r["target"] == v1 for r in rows)  # what the drone did
    assert sum(r["action"] == "manual stick control" for r in rows) == 1  # one line per stick session
    assert audit.verify(fresh_log)[0]


def test_system_actions_are_logged_as_system(d, fresh_log):
    d._drone_event("Battery 20%: returning home from route A", "drone")
    r = audit.read(fresh_log)[0]
    assert r["source"] == "system" and r["user"] == "" and "returning home" in r["action"]


def test_audit_page_is_for_admins_and_reports_the_chain(d, fresh_log):
    if os.path.exists(d.USERS_FILE):
        os.remove(d.USERS_FILE)
    admin = d.app.test_client()
    admin.post("/api/users", json={"username": "boss", "password": "correct horse", "role": "admin"})
    admin.post("/api/users", json={"username": "ops", "password": "operator pass", "role": "operator"})
    ops = d.app.test_client()
    ops.post("/login", data={"username": "ops", "password": "operator pass"})
    try:
        assert ops.get("/audit").status_code == 403 and ops.get("/api/audit").status_code == 403
        assert ops.post("/api/system/shutdown").status_code == 403
        d_ = admin.get("/api/audit").get_json()
        assert d_["chain"]["ok"] and any(r["action"] == "POST /api/users" and r["user"] == "boss" for r in d_["rows"])
        assert all("correct horse" not in json.dumps(r) for r in d_["rows"])  # passwords never logged
        assert admin.get("/audit").status_code == 200
        assert admin.get("/api/audit?format=csv").mimetype == "text/csv"
    finally:
        os.remove(d.USERS_FILE)


def test_shut_down_asks_the_launcher(d, client, fresh_log, monkeypatch):
    import browser_mode as bm
    from conftest import _free_port

    class Owner:
        actions = []
        def status(self): return {}
        def on_action(self, name): self.actions.append(name)

    port = _free_port()
    page = bm.StartPage(Owner(), "x", port=port)
    assert page.start()
    try:
        monkeypatch.setattr(d, "LAUNCHER_URL", f"http://127.0.0.1:{port}/")
        assert client.post("/api/system/shutdown").get_json()["ok"] and Owner.actions == ["shutdown"]
        assert audit.read(fresh_log)[0]["action"] == "POST /api/system/shutdown"
    finally:
        page.stop()
    monkeypatch.setattr(d, "LAUNCHER_URL", f"http://127.0.0.1:{_free_port()}/")
    r = client.post("/api/system/shutdown")
    assert r.status_code == 503 and "launcher isn't running" in r.get_json()["error"]


def test_browser_close_only_stops_when_switched_on(d, client):
    assert client.get("/api/browser/presence").get_json()["stop_with_browser"] is False
    cfg = client.get("/api/customer/settings").get_json()
    client.post("/api/customer/settings", json={**cfg, "stop_with_browser": True})
    assert client.get("/api/browser/presence").get_json()["stop_with_browser"] is True
    client.post("/api/customer/settings", json={**cfg, "stop_with_browser": False})
