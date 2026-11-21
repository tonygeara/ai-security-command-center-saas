"""Docker Desktop: asked and installed when it's missing, stopped by "Log out and turn off", and the program starts at
the next Windows sign-in."""
import io
import json
import os
import sys
import types
import urllib.request

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import browser_mode as bm  # noqa: E402
import docker_setup as ds  # noqa: E402
from conftest import _free_port  # noqa: E402


class Done:
    def __init__(self, code=0, out=""):
        self.returncode, self.stdout = code, out


def test_local_installer_and_arch(tmp_path, monkeypatch):
    assert ds.local_installer([str(tmp_path), None]) is None
    (tmp_path / ds.INSTALLER_NAME).write_bytes(b"x")
    assert ds.local_installer(["", str(tmp_path)]) == str(tmp_path / ds.INSTALLER_NAME)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "ARM64")
    assert ds.arch() == "arm64"
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    assert ds.arch() == "amd64" and ds.INSTALLER_URL["amd64"].startswith("https://desktop.docker.com/")


def test_download_reports_progress(tmp_path):
    body = b"y" * (3 << 20)

    class Resp(io.BytesIO):
        headers = {"Content-Length": str(len(body))}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    seen = []
    dest = str(tmp_path / "d.exe")
    ds.download("https://x", dest, progress=seen.append, opener=lambda req, timeout: Resp(body))
    assert open(dest, "rb").read() == body and seen[-1] == 100 and not os.path.exists(dest + ".part")


def test_signature_must_be_valid_and_from_docker():
    assert ds.signature_ok("i.exe", run=lambda a, timeout: Done(out="Valid|CN=Docker Inc, O=Docker Inc, C=US"))
    assert not ds.signature_ok("i.exe", run=lambda a, timeout: Done(out="Valid|CN=Someone Else"))
    assert not ds.signature_ok("i.exe", run=lambda a, timeout: Done(out="NotSigned|"))
    def boom(a, timeout):
        raise OSError("no powershell")
    assert not ds.signature_ok("i.exe", run=boom)


def test_run_installer_elevated_and_exit_codes():
    calls = []
    def run(args, timeout):
        calls.append(args)
        return Done(out="0\n")
    assert ds.run_installer("C:/i.exe", run=run) == 0
    assert "-Verb RunAs" in calls[0][4] and calls[0][-4:] == ds.INSTALL_ARGS and "--accept-license" in calls[0]
    assert ds.run_installer("i.exe", run=lambda a, timeout: Done(out="3010")) == 3010
    assert ds.run_installer("i.exe", run=lambda a, timeout: Done(out="")) is None  # permission refused


def test_stop_docker():
    calls = []
    assert ds.stop_docker(run=lambda a, timeout: calls.append(a) or Done(0)) and calls == [["docker", "desktop", "stop"]]
    calls.clear()
    def old(a, timeout):  # an older Docker Desktop: no "docker desktop stop"
        calls.append(a)
        return Done(1 if a[:2] in (["docker", "desktop"], ["docker", "info"]) else 0)
    assert ds.stop_docker(run=old)
    assert ["taskkill", "/IM", "Docker Desktop.exe", "/T", "/F"] in calls and ["wsl", "--terminate", "docker-desktop"] in calls


def test_ensure_autostart_adds_the_sign_in_start_once():
    store = {}

    class Key:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    reg = types.SimpleNamespace(HKEY_CURRENT_USER=1, KEY_READ=1, KEY_SET_VALUE=2, REG_SZ=1,
                                OpenKey=lambda *a: Key(),
                                QueryValueEx=lambda k, n: (store[n], 1) if n in store else (_ for _ in ()).throw(OSError()),
                                SetValueEx=lambda k, n, z, t, v: store.__setitem__(n, v))
    assert ds.ensure_autostart(r"C:\Apps\AI-Security-Command-Center.exe", winreg=reg)
    assert store == {"AI-Security-Command-Center": r'"C:\Apps\AI-Security-Command-Center.exe" --background'}
    store["AI-Security-Command-Center"] = "kept"
    ds.ensure_autostart(r"C:\Apps\AI-Security-Command-Center.exe", winreg=reg)
    assert store["AI-Security-Command-Center"] == "kept"  # an existing value is left alone


def _post(url):
    req = urllib.request.Request(url, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read())


def test_start_page_asks_to_install_docker():
    class Owner:
        actions = []
        def status(self): return {"message": "Docker Desktop is needed to run the AI services.", "ready": False, "url": "",
                                  "error": "", "need_docker": True}
        def on_action(self, name): self.actions.append(name)
    port = _free_port()
    page = bm.StartPage(Owner(), "x", port=port)
    assert page.start()
    try:
        url = f"http://127.0.0.1:{port}/"
        html = urllib.request.urlopen(url, timeout=3).read().decode()
        assert "Install Docker Desktop" in html and "Not now" in html and "s.need_docker" in html
        assert json.loads(urllib.request.urlopen(url + "status", timeout=3).read())["need_docker"]
        for a in ("install_docker", "skip_docker", "logout"):
            assert _post(url + a)["ok"]
        assert Owner.actions == ["install_docker", "skip_docker", "logout"]
    finally:
        page.stop()


def test_log_out_and_turn_off(d, client, monkeypatch):
    class Owner:
        actions = []
        def status(self): return {}
        def on_action(self, name): self.actions.append(name)
    settings = client.get("/settings").get_data(as_text=True)
    assert 'id="logoutBtn"' in settings and "Docker Desktop included" in settings
    port = _free_port()
    page = bm.StartPage(Owner(), "x", port=port)
    assert page.start()
    try:
        monkeypatch.setattr(d.web_records, "LAUNCHER_URL", f"http://127.0.0.1:{port}/")
        assert client.post("/api/system/logout").get_json()["ok"] and Owner.actions == ["logout"]
    finally:
        page.stop()
    monkeypatch.setattr(d.web_records, "LAUNCHER_URL", f"http://127.0.0.1:{_free_port()}/")
    r = client.post("/api/system/logout")
    assert r.status_code == 503 and "launcher isn't running" in r.get_json()["error"]
    import users
    assert not users.allowed("operator", "POST", "/api/system/logout") and users.allowed("admin", "POST", "/api/system/logout")
