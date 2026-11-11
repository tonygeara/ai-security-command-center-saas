"""Sign-in and roles: off until the first admin exists; then viewer / operator / admin rights are enforced."""
import os

import pytest


@pytest.fixture
def signin(d):
    for f in (d.USERS_FILE,):
        if os.path.exists(f):
            os.remove(f)
    yield
    if os.path.exists(d.USERS_FILE):
        os.remove(d.USERS_FILE)


def login(d, name, pw):
    c = d.app.test_client()
    r = c.post("/login", data={"username": name, "password": pw, "next": "/drone-control"})
    return c, r


def test_first_start_asks_for_an_admin(d, signin, monkeypatch):
    monkeypatch.setattr(d.web_access, "REQUIRE_FIRST_ADMIN", True)
    c = d.app.test_client()
    for path in ("/", "/drone-control", "/settings", "/login"):
        r = c.get(path)
        assert r.status_code == 302 and r.headers["Location"] == "/welcome", path
    assert c.get("/api/drone/links").status_code == 401
    assert c.post("/api/drone/command?drone=drone", json={"cmd": "hover"}).status_code == 401
    page = c.get("/welcome")
    assert page.status_code == 200 and "Create the admin account" in page.get_data(as_text=True)
    assert c.get("/healthz").status_code == 200 and c.get("/hud.css").status_code == 200
    r = c.post("/api/users", json={"username": "kim", "password": "longpassword", "role": "viewer"})
    assert r.status_code == 400 and "first user must be an admin" in r.get_json()["error"]
    assert c.post("/api/users", json={"username": "boss", "password": "correct horse", "role": "admin"}).get_json()["ok"]
    assert c.get("/").status_code == 200  # signed in straight away
    assert c.get("/welcome").status_code == 302  # only once
    other = d.app.test_client()
    assert other.get("/").headers["Location"].startswith("/login")


def test_open_until_first_admin_when_not_required(d, signin):
    c = d.app.test_client()
    assert c.get("/").status_code == 200
    assert c.get("/api/users").get_json()["users"] == []
    r = c.post("/api/users", json={"username": "kim", "password": "longpassword", "role": "viewer"})
    assert r.status_code == 400 and "first user must be an admin" in r.get_json()["error"]
    r = c.post("/api/users", json={"username": "boss", "password": "short", "role": "admin"})
    assert r.status_code == 400 and "8 characters" in r.get_json()["error"]
    assert c.post("/api/users", json={"username": "boss", "password": "correct horse", "role": "admin"}).get_json()["ok"]
    # The creator is signed in; everyone else now has to sign in.
    assert c.get("/users").status_code == 200
    other = d.app.test_client()
    r = other.get("/drone-control")
    assert r.status_code == 302 and r.headers["Location"].startswith("/login?next=")
    assert other.get("/api/drone/links").status_code == 401
    assert other.get("/healthz").status_code == 200
    assert other.get("/api/cloud/can-add-source/camera").status_code != 401  # the app calls this on itself


def test_login_and_roles(d, signin):
    admin = d.app.test_client()
    admin.post("/api/users", json={"username": "boss", "password": "correct horse", "role": "admin"})
    assert admin.post("/api/users", json={"username": "vic", "password": "viewer pass", "role": "viewer"}).get_json()["ok"]
    assert admin.post("/api/users", json={"username": "ops", "password": "operator pass", "role": "operator"}).get_json()["ok"]

    c, r = login(d, "vic", "wrong one")
    assert r.status_code == 200 and "Wrong user name or password" in r.get_data(as_text=True)
    viewer, r = login(d, "VIC", "viewer pass")  # user names are not case sensitive
    assert r.status_code == 302 and r.headers["Location"] == "/drone-control"
    page = viewer.get("/drone-control")
    assert page.status_code == 200 and "vic · viewer" in page.get_data(as_text=True)
    assert viewer.post("/api/drone/command?drone=drone", json={"cmd": "hover"}).status_code == 403
    assert viewer.post("/api/routes/stop").status_code == 403
    assert viewer.get("/users").status_code == 403
    assert viewer.get("/api/drone/link/pair").status_code == 403
    assert viewer.get("/api/routes").status_code == 200

    operator, _ = login(d, "ops", "operator pass")
    assert operator.post("/api/routes/stop?drone=drone").status_code != 403
    assert operator.post("/api/drone/command?drone=drone", json={"cmd": "hover"}).status_code != 403
    assert operator.post("/api/response/recall").status_code != 403
    assert operator.post("/api/nofly", json={"points": []}).status_code == 403
    assert operator.post("/api/response/settings", json={}).status_code == 403
    assert operator.delete("/api/events").status_code == 403
    assert operator.post("/api/drone/add").status_code == 403
    assert operator.post("/api/users", json={"username": "x", "password": "yyyyyyyy", "role": "admin"}).status_code == 403

    # A new password signs the user out everywhere else; role changes apply at once.
    assert admin.post("/api/users/vic", json={"password": "a new password"}).get_json()["ok"]
    assert viewer.get("/api/routes").status_code == 401
    assert admin.post("/api/users/ops", json={"role": "viewer"}).get_json()["ok"]
    assert operator.post("/api/routes/stop").status_code == 403


def test_last_admin_is_kept(d, signin):
    admin = d.app.test_client()
    admin.post("/api/users", json={"username": "boss", "password": "correct horse", "role": "admin"})
    r = admin.delete("/api/users/boss")
    assert r.status_code == 400 and "at least one admin" in r.get_json()["error"]
    r = admin.post("/api/users/boss", json={"role": "viewer"})
    assert r.status_code == 400
    raw = open(d.USERS_FILE, encoding="utf-8").read()
    assert "correct horse" not in raw  # only the hash is stored


def test_too_many_wrong_passwords(d, signin):
    d.app.test_client().post("/api/users", json={"username": "boss", "password": "correct horse", "role": "admin"})
    d._login_fails.clear()
    c = d.app.test_client()
    for _ in range(5):
        c.post("/login", data={"username": "boss", "password": "nope"})
    r = c.post("/login", data={"username": "boss", "password": "correct horse"})
    assert "Too many wrong tries" in r.get_data(as_text=True)
    d._login_fails.clear()


def test_sign_in_page_is_styled_once_users_exist(d, signin):
    d.app.test_client().post("/api/users", json={"username": "boss", "password": "correct horse", "role": "admin"})
    c = d.app.test_client()
    r = c.get("/hud.css")
    assert r.status_code == 200 and "text/css" in r.headers["Content-Type"]  # not a redirect to /login
    page = c.get("/login").get_data(as_text=True)
    assert 'href="/hud.css"' in page and "Reset sign-in" in page and "not your portal email" in page


def test_forgotten_password_reset_from_this_pc(d, signin):
    import time
    d.app.test_client().post("/api/users", json={"username": "boss", "password": "correct horse", "role": "admin"})
    d.app.test_client().post("/api/users", json={"username": "kim", "password": "viewer pass", "role": "viewer"})
    req = os.path.join(d.web_access.DATA_FOLDER, d.web_access.RESET_FILE_NAME)
    c = d.app.test_client()
    assert c.get("/reset-signin").status_code == 403  # nobody asked from the Start menu
    open(req, "w").write("x")
    try:
        assert "Choose a new password" in c.get("/login").get_data(as_text=True)
        lan = d.app.test_client()
        lan.environ_base["REMOTE_ADDR"] = "192.168.1.50"
        assert lan.get("/reset-signin").status_code == 403  # only a browser on this PC
        assert lan.post("/reset-signin", data={"username": "boss", "password": "new password 1", "password2": "new password 1"}).status_code == 403
        page = c.get("/reset-signin").get_data(as_text=True)
        assert "boss" in page and "kim" not in page  # admins only
        r = c.post("/reset-signin", data={"username": "boss", "password": "new password 1", "password2": "different"})
        assert "different" in r.get_data(as_text=True)
        r = c.post("/reset-signin", data={"username": "kim", "password": "new password 1", "password2": "new password 1"})
        assert "Choose an admin account" in r.get_data(as_text=True)
        r = c.post("/reset-signin", data={"username": "boss", "password": "new password 1", "password2": "new password 1"})
        assert r.status_code == 302 and c.get("/settings").status_code == 200  # signed in
        assert not os.path.exists(req)  # one use
        assert c.get("/reset-signin").status_code == 403
        _, r = login(d, "boss", "correct horse")
        assert r.status_code == 200 and "Wrong user name or password" in r.get_data(as_text=True)
        d._login_fails.clear()
        _, r = login(d, "boss", "new password 1")
        assert r.status_code == 302
        open(req, "w").write("x")
        old = time.time() - d.web_access.RESET_VALID_S - 5
        os.utime(req, (old, old))
        assert c.get("/reset-signin").status_code == 403  # too old
    finally:
        if os.path.exists(req):
            os.remove(req)
        d._login_fails.clear()
