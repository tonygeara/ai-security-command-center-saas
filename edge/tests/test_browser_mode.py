"""Browser mode: the app opens in the browser and stops when the browser is closed."""
import json
import os
import sys
import urllib.error
import urllib.request

import pytest

from conftest import APP, _free_port

sys.path.insert(0, os.path.abspath(APP))
import browser_mode as bm  # noqa: E402


# ---- when does closing the browser stop the system? ----

def test_stops_only_after_the_browser_was_open_and_then_closed_for_the_grace_time():
    w = bm.BrowserWatch(0)
    assert w.step(2, False) is None              # never seen a page yet: don't stop
    assert w.step(4, True) is None               # start page / dashboard open
    assert w.step(6, False) is None              # closed: count starts
    assert w.step(6 + bm.BROWSER_GRACE - 1, False) is None
    assert w.step(6 + bm.BROWSER_GRACE, False) == "stop"


def test_moving_between_pages_does_not_stop():
    w = bm.BrowserWatch(0)
    w.step(2, True)
    w.step(4, False)                             # old page gone...
    assert w.step(6, True) is None               # ...new page checked in
    assert w.step(6 + bm.BROWSER_GRACE + 4, False) is None  # count restarted


def test_nothing_stops_while_starting_or_when_the_dashboard_does_not_answer():
    w = bm.BrowserWatch(0)
    w.step(2, True)
    for t in range(4, 200, 2):
        assert w.step(t, False, busy=True) is None
    for t in range(200, 400, 2):
        assert w.step(t, None) is None


def test_after_sleep_pages_get_more_time_to_check_in():
    w = bm.BrowserWatch(0)
    w.step(2, True)
    t = 2 + 3600                                 # PC slept an hour
    assert w.step(t, False) is None
    stopped_at = None
    while stopped_at is None and t < 3602 + 300:
        t += 2
        if w.step(t, False) == "stop":
            stopped_at = t
    assert stopped_at == 3602 + bm.WAKE_GRACE


def test_shows_the_window_when_the_browser_never_opened_the_start_page():
    w = bm.BrowserWatch(0)
    assert w.step(bm.NO_BROWSER_SHOW_WINDOW - 2, None, splash_ever_seen=False) is None
    assert w.step(bm.NO_BROWSER_SHOW_WINDOW + 2, None, splash_ever_seen=False) == "show-window"
    assert w.step(bm.NO_BROWSER_SHOW_WINDOW + 4, None, splash_ever_seen=False) is None  # asked once


# ---- the start page ----

class Owner:
    def __init__(self):
        self.actions = []
        self.state = {"message": "Starting Frigate...", "ready": False, "url": "", "error": ""}

    def status(self):
        return self.state

    def on_action(self, name):
        self.actions.append(name)


def _post(url, origin=None):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    with urllib.request.urlopen(urllib.request.Request(url, data=b"{}", method="POST", headers=headers), timeout=3) as r:
        return json.loads(r.read())


@pytest.fixture
def start_page(monkeypatch):
    port = _free_port()
    monkeypatch.setattr(bm, "SPLASH_URL", f"http://127.0.0.1:{port}/")
    owner = Owner()
    page = bm.StartPage(owner, "Test <Center>", port=port)
    assert page.start()
    yield page, owner, f"http://127.0.0.1:{port}/"
    page.stop()


def test_start_page_shows_progress_and_is_single_instance(start_page):
    page, owner, url = start_page
    html = urllib.request.urlopen(url, timeout=3).read().decode()
    assert "Test &lt;Center&gt;" in html and "Closing the browser stops the system" in html
    assert json.loads(urllib.request.urlopen(url + "status", timeout=3).read())["message"] == "Starting Frigate..."
    assert page.is_open(page.last_seen + 1)
    assert not bm.StartPage(Owner(), "x", port=page.port).start()  # second copy can't take the port
    assert bm.notify_running_instance("open") and owner.actions == ["open"]


def test_start_page_closing_and_buttons(start_page):
    page, owner, url = start_page
    urllib.request.urlopen(url + "status", timeout=3).read()
    assert _post(url + "bye", origin=url.rstrip("/"))["ok"]
    assert not page.is_open(page.last_seen)
    _post(url + "retry"); _post(url + "show")
    assert owner.actions == ["retry", "show"]
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(url + "show", origin="https://evil.example")
    assert e.value.code == 403 and owner.actions == ["retry", "show"]


# ---- dashboard pages check in ----

def test_dashboard_pages_carry_the_check_in_and_are_counted(d, client):
    d._browser_pages.clear()
    page = client.get("/login").get_data(as_text=True) if client.get("/login").status_code == 200 else \
        client.get("/").get_data(as_text=True)
    assert page.count("window.__aiPresence=1") == 1 and "/api/browser/" in page
    assert client.get("/api/browser/presence").get_json()["open_pages"] == 0
    assert client.post("/api/browser/ping", json={"page": "tab123abc"}).get_json()["ok"]
    assert client.post("/api/browser/ping", json={"page": "tab456def"}).get_json()["ok"]
    assert client.get("/api/browser/presence").get_json()["open_pages"] == 2
    # sendBeacon posts the id as plain text
    assert client.post("/api/browser/bye", data='{"page":"tab123abc"}', content_type="text/plain").get_json()["ok"]
    assert client.get("/api/browser/presence").get_json()["open_pages"] == 1
    assert client.post("/api/browser/ping", json={"page": "../bad id"}).status_code == 400


def test_silent_pages_expire_but_sleeping_tabs_stay_open(d, client):
    d._browser_pages.clear()
    client.post("/api/browser/ping", json={"page": "awake0001"})
    client.post("/api/browser/sleep", json={"page": "asleep001"})
    for info in d._browser_pages.values():
        info["seen"] -= d.BROWSER_PAGE_TIMEOUT + 5
    assert client.get("/api/browser/presence").get_json()["open_pages"] == 1
    assert "asleep001" in d._browser_pages
    d._browser_pages.clear()
