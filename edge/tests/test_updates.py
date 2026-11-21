"""Settings → Updates: automatic updates on/off, the question when it's switched on, checks before installing."""
import hashlib
import json

import pytest

BODY = b"fake installer bytes"
SHA = hashlib.sha256(BODY).hexdigest()


def release(version="11.99.0", sha=SHA, prefix_saas=True):
    return {"tag_name": f"edge-v{version}", "html_url": "https://github.com/x/releases/tag/edge-v" + version,
            "published_at": "2026-11-20T00:00:00Z", "assets": [
                {"name": f"AI-Security-Command-Center-Setup-{version}.exe", "browser_download_url": "https://dl/saas.exe",
                 "digest": f"sha256:{sha}", "size": len(BODY)},
                {"name": "AI-Security-Command-Center-Setup.exe", "browser_download_url": "https://dl/latest.exe", "digest": f"sha256:{sha}"},
                {"name": f"On-prem-AI-Command-Centre-Setup-{version}.exe", "browser_download_url": "https://dl/onprem.exe",
                 "digest": f"sha256:{sha}"},
                {"name": "Online-INSTALL.txt", "browser_download_url": "https://dl/guide.txt"}]}


@pytest.fixture
def up(tmp_path):
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
    import updater
    log = []
    u = updater.Updater(str(tmp_path), "V11.12.1", "saas", audit=lambda a, detail=None: log.append((a, detail)))
    u.fetch = lambda url: release()
    u.downloaded = []

    def download(url, path):
        u.downloaded.append(url)
        open(path, "wb").write(BODY)
        return hashlib.sha256(BODY).hexdigest()
    u.download = download
    u.ran = []
    u.run_installer = lambda path: u.ran.append(path)
    u.audit_log = log
    return u


def test_versions(up):
    import updater
    assert updater.parse_version("V11.12.1") == (11, 12, 1) == updater.parse_version("edge-v11.12.1")
    assert updater.parse_version("nope") is None
    assert up.check()["version"] == "V11.99.0" and up.newer()
    up.fetch = lambda url: release("11.12.1")
    up.check()
    assert not up.newer() and up.status()["available"] is None


def test_off_does_nothing(up):
    calls = []
    up.fetch = lambda url: calls.append(url) or release()
    assert up.tick() is None and calls == [] and up.ran == []  # off: no check, nothing installed


def test_turning_on_asks_then_installs_later_versions(up):
    st = up.set_auto(True, by="tony")
    assert st["auto"] and st["ask"] and st["available"] == "V11.99.0"  # the page asks: Install now / Not now
    assert json.load(open(up.path)) == {"auto": True, "skipped": ""}
    up.skip("V11.99.0", by="tony")  # "Not now"
    assert up.tick() is None and up.ran == []
    up.fetch = lambda url: release("11.100.0")  # a later version installs by itself
    ok, msg = up.tick()
    assert ok and up.downloaded == ["https://dl/saas.exe"] and up.ran and up.ran[0].endswith("Setup-11.100.0.exe")
    assert up.status()["installing"] == "V11.100.0"
    assert ("updates: installing", {"by": "automatic", "from": "V11.12.1", "to": "V11.100.0"}) in up.audit_log
    assert up.set_auto(True)["ask"] is False  # already on: no question


def test_install_now_and_checks(up):
    ok, msg = up.install(by="tony")
    assert ok and "Installing V11.99.0" in msg and len(up.ran) == 1
    # Not twice at once.
    assert up.install(by="tony") == (False, "The update is already being installed.")


def test_wrong_checksum_not_installed(up):
    up.fetch = lambda url: release(sha="0" * 64)
    ok, msg = up.install(by="tony")
    assert not ok and "SHA-256" in msg and up.ran == [] and up.status()["installing"] is None
    up.fetch = lambda url: release(sha="")
    up.state["latest"] = None
    ok, msg = up.install(by="tony")
    assert not ok and "can't be checked" in msg and up.ran == []


def test_waits_while_flying(up):
    up.busy = lambda: "Drone 1 is flying."
    up.set_auto(True)
    ok, msg = up.tick()
    assert not ok and "Drone 1 is flying" in msg and up.ran == [] and up.status()["waiting"] == "Drone 1 is flying."
    up.busy = lambda: ""
    assert up.tick()[0] and up.ran and up.status()["waiting"] == ""


def test_onprem_gets_its_own_installer(up):
    up.edition = "onprem"
    assert up.check()["url"] == "https://dl/onprem.exe"


def test_offline_check(up):
    def boom(url):
        raise OSError("no internet")
    up.fetch = boom
    assert up.check() is None and "no internet" in up.status()["error"]
    assert up.install()[0] is False


def test_updates_api_and_settings(d, client, monkeypatch, tmp_path):
    import updater as ul
    u = ul.Updater(str(tmp_path), d.APP_VERSION, "saas")
    u.fetch = lambda url: release()
    u.download = lambda url, path: (open(path, "wb").write(BODY), SHA)[1]
    ran = []
    u.run_installer = lambda path: ran.append(path)
    monkeypatch.setattr(d, "UPDATER", u)
    page = client.get("/settings").get_data(as_text=True)
    assert 'id="updAuto"' in page and "⟳ Updates" in page and "Install now" in page
    st = client.get("/api/updates").get_json()
    assert st["ok"] and st["auto"] is False and st["current"] == d.APP_VERSION and st["checked_at"] is None  # no check while off
    assert client.post("/api/updates", json={}).status_code == 400
    r = client.post("/api/updates", json={"auto": True}).get_json()
    assert r["ok"] and r["auto"] and r["ask"] and r["available"] == "V11.99.0"
    # Only the installed Windows program installs.
    monkeypatch.setattr(ul, "frozen", lambda: False)
    assert client.post("/api/updates/install").status_code == 409 and ran == []
    monkeypatch.setattr(ul, "frozen", lambda: True)
    monkeypatch.setattr(d.os, "name", "nt")
    r = client.post("/api/updates/install").get_json()
    assert r["ok"] and ran
    assert client.post("/api/updates/skip", json={"version": "V11.99.0"}).get_json()["ok"] and u.state["skipped"] == "V11.99.0"
    assert client.post("/api/updates", json={"auto": False}).get_json()["auto"] is False


def test_only_admins_change_updates():
    import users
    for path in ("/api/updates", "/api/updates/install", "/api/updates/skip"):
        assert not users.allowed("operator", "POST", path) and not users.allowed("viewer", "POST", path)
        assert users.allowed("admin", "POST", path)
    assert users.allowed("viewer", "GET", "/api/updates")
