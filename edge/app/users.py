"""Dashboard sign-in and roles.

Sign-in is off until the first user (always an admin) is created on the Users page; existing installs keep
working as before until then. Roles:
    viewer    watches live video, events and maps; changes nothing
    operator  also flies: drone controls, routes, drone responses, live-feed switches
    admin     everything, including setup, licences, no-fly zones and users
Users are stored with salted password hashes (werkzeug scrypt), never the passwords themselves.
"""
import json
import os
import re
import secrets
import time

from werkzeug.security import check_password_hash, generate_password_hash

ROLES = ("viewer", "operator", "admin")
ROLE_NAMES = {"viewer": "Viewer: watch only", "operator": "Operator: watch and fly", "admin": "Admin: everything"}

# Paths anyone may open without signing in (the app also calls can-add-source on itself).
OPEN_PATHS = ("/login", "/logout", "/healthz", "/favicon.ico", "/api/cloud/can-add-source/")
# Read-only pages that still need an admin (they show secrets or manage users).
ADMIN_ONLY_READ = ("/users", "/api/users", "/api/drone/link/pair")
# What an operator may change: flying, routes, responses, which live feeds are shown.
OPERATOR_WRITES = [re.compile(p) for p in (
    r"^/api/drone/(?!add$|link/pair)",
    r"^/api/routes(/fly|/stop)?$",
    r"^/api/response/(dispatch|recall)$",
    r"^/api/assistant/briefing$",
    r"^/api/sources/[^/]+/feed$",
    r"^/api/virtual-drones/[^/]+$",
    r"^/api/maps(/plan|/[a-f0-9]{12}/(fly|stop|photos|process|cancel))?$",  # 3D maps: plan, fly, add photos, process
)]

_cache = {"path": None, "mtime": None, "users": []}


def load(path):
    """All users (cached until the file changes)."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []
    if _cache["path"] != path or _cache["mtime"] != mtime:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = []
        _cache.update(path=path, mtime=mtime, users=[u for u in data if isinstance(u, dict) and u.get("username")])
    return list(_cache["users"])


def save(path, users):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    os.replace(tmp, path)
    _cache["mtime"] = None


def find(users, username):
    name = str(username or "").strip().lower()
    return next((u for u in users if u["username"].lower() == name), None)


def clean_name(username):
    name = str(username or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._@-]{2,40}", name):
        raise ValueError("Use 2-40 letters, numbers, dots, dashes or @ for the user name")
    return name


def check_new_password(password):
    if len(str(password or "")) < 8:
        raise ValueError("The password needs at least 8 characters")
    return str(password)


def add(path, username, password, role):
    users = load(path)
    name = clean_name(username)
    if find(users, name):
        raise ValueError(f"There is already a user called {name}")
    if role not in ROLES:
        raise ValueError("Choose a role")
    if not users and role != "admin":
        raise ValueError("The first user must be an admin")
    users.append({"username": name, "role": role, "hash": generate_password_hash(check_new_password(password)),
                  "created": int(time.time()), "stamp": secrets.token_hex(4)})
    save(path, users)
    return name


def update(path, username, role=None, password=None):
    users = load(path)
    u = find(users, username)
    if not u:
        raise ValueError("No such user")
    if role is not None:
        if role not in ROLES:
            raise ValueError("Choose a role")
        if u["role"] == "admin" and role != "admin" and sum(x["role"] == "admin" for x in users) == 1:
            raise ValueError("Keep at least one admin")
        u["role"] = role
    if password:
        u["hash"] = generate_password_hash(check_new_password(password))
        u["stamp"] = secrets.token_hex(4)  # signs this user out everywhere else
    save(path, users)
    return u


def delete(path, username):
    users = load(path)
    u = find(users, username)
    if not u:
        raise ValueError("No such user")
    if u["role"] == "admin" and sum(x["role"] == "admin" for x in users) == 1:
        raise ValueError("Keep at least one admin")
    save(path, [x for x in users if x is not u])


def authenticate(path, username, password):
    u = find(load(path), username)
    if u and check_password_hash(u["hash"], str(password or "")):
        return u
    return None


def public(u):
    return {"username": u["username"], "role": u["role"], "created": u.get("created")}


def allowed(role, method, path):
    """May this role make this request?"""
    if role == "admin":
        return True
    if any(path == p or path.startswith(p + "?") or path.startswith(p + "/") for p in ADMIN_ONLY_READ):
        return False
    if method in ("GET", "HEAD", "OPTIONS"):
        return True
    return role == "operator" and any(rx.match(path) for rx in OPERATOR_WRITES) and not (
        method == "DELETE" and path.startswith("/api/virtual-drones/"))


def secret_key(path):
    """A random key for signing session cookies, made once per install."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if len(key) >= 32:
            return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    return key
