"""Automatic updates (Settings → Updates).

The PC checks the newest published release (GitHub, the same one the admin portal links to) every few hours.
- Updates ON: a newer version is downloaded, checked against GitHub's SHA-256 of the file, and installed silently
  (the installer stops the program, upgrades it and starts it again). It waits while a drone or dock is flying.
- Updates OFF: nothing is installed and the PC doesn't check by itself (nothing leaves it); "Check now" in Settings
  still looks.
- Switching it ON while a new version is waiting asks first ("Install now" / "Not now"). "Not now" skips that
  version; later versions install by themselves.

Each edition installs its own installer (online or on-prem). Settings live in updates.json in the data folder.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

REPO = "tonygeara/ai-security-command-center-saas"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY = 6 * 3600          # seconds between checks
FIRST_CHECK_AFTER = 120         # seconds after start
INSTALLER_PREFIX = {"saas": "AI-Security-Command-Center-Setup-", "onprem": "On-prem-AI-Command-Centre-Setup-"}
SILENT_ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]


def parse_version(v):
    """'V11.12.1' or 'edge-v11.12.1' -> (11, 12, 1); None if it isn't a version."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", str(v or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def _http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "AI-Security-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _download(url, path, timeout=600):
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Security-Updater"})
    h = hashlib.sha256()
    tmp = path + ".part"
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            f.write(chunk)
    os.replace(tmp, path)
    return h.hexdigest()


def _run_installer(path):
    """Start the installer detached, so it can stop this program and start the new version."""
    if os.name != "nt":
        raise RuntimeError("Installing updates works on Windows only.")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    subprocess.Popen([path, *SILENT_ARGS], creationflags=flags, close_fds=True)


class Updater:
    def __init__(self, folder, current, edition, busy=lambda: "", log=print, audit=None, now=time.time):
        self.folder = folder
        self.path = os.path.join(folder, "updates.json")
        self.current = current                    # e.g. "V11.12.1"
        self.edition = edition if edition in INSTALLER_PREFIX else "saas"
        self.busy = busy                          # '' when it's safe to restart, else why not (a drone is flying…)
        self.log = log
        self.audit = audit or (lambda *a, **k: None)
        self.now = now
        self.fetch = _http_json
        self.download = _download
        self.run_installer = _run_installer
        self.lock = threading.Lock()
        self.state = {"auto": False, "skipped": "", "checked_at": None, "error": "", "latest": None,
                      "installing": None, "waiting": ""}
        self._load()

    # --- settings ---
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                saved = json.load(f)
            self.state["auto"] = bool(saved.get("auto"))
            self.state["skipped"] = str(saved.get("skipped") or "")
        except (OSError, ValueError):
            pass

    def _save(self):
        os.makedirs(self.folder, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"auto": self.state["auto"], "skipped": self.state["skipped"]}, f, indent=2)
        os.replace(tmp, self.path)

    def set_auto(self, on, by=""):
        """Switch updates on or off. Returns the status; "ask" in it means: offer the waiting version now."""
        if on and not self.state["auto"]:
            self.check()  # turning it on: see what's waiting, so the page can ask
        with self.lock:
            was = self.state["auto"]
            self.state["auto"] = bool(on)
            self._save()
        self.audit("updates: " + ("on" if on else "off"), detail={"by": by})
        st = self.status()
        st["ask"] = bool(on and not was and st["available"])
        return st

    def skip(self, version, by=""):
        """'Not now' on the question: this version isn't installed automatically (later ones are)."""
        with self.lock:
            self.state["skipped"] = str(version or "")
            self._save()
        self.audit("updates: skipped", detail={"by": by, "version": version})

    # --- checking ---
    def check(self):
        """Ask GitHub for the newest release. Returns its info or None (the error is kept in the status)."""
        try:
            r = self.fetch(LATEST_URL)
            tag = str(r.get("tag_name") or "")
            ver = parse_version(tag)
            prefix = INSTALLER_PREFIX[self.edition]
            asset = next((a for a in r.get("assets") or [] if str(a.get("name", "")).startswith(prefix)
                          and parse_version(a.get("name")) == ver), None)
            latest = None
            if ver and asset:
                digest = str(asset.get("digest") or "")
                latest = {"version": "V%d.%d.%d" % ver, "url": asset.get("browser_download_url"), "name": asset["name"],
                          "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
                          "size": asset.get("size"), "notes": str(r.get("html_url") or ""), "published": r.get("published_at")}
            with self.lock:
                self.state.update(latest=latest, checked_at=self.now(), error="" if latest else "No installer in the newest release.")
            return latest
        except Exception as e:  # noqa: BLE001 - offline PCs (on-prem) simply have nothing to update from
            with self.lock:
                self.state.update(checked_at=self.now(), error=f"Couldn't check for updates: {e}")
            return None

    def newer(self, latest=None):
        latest = latest if latest is not None else self.state["latest"]
        if not latest:
            return False
        a, b = parse_version(latest["version"]), parse_version(self.current)
        return bool(a and b and a > b)

    def status(self):
        with self.lock:
            s = dict(self.state)
        avail = self.newer(s["latest"])
        return {"auto": s["auto"], "current": self.current, "edition": self.edition,
                "available": s["latest"]["version"] if avail else None, "latest": s["latest"],
                "skipped": s["skipped"], "checked_at": s["checked_at"], "error": s["error"],
                "installing": s["installing"], "waiting": s["waiting"]}

    # --- installing ---
    def install(self, by="", force=False):
        """Download, check and start the installer for the newest version. Returns (ok, message)."""
        latest = self.state["latest"] or self.check()
        if not self.newer(latest):
            return False, f"{self.current} is the newest version."
        why = self.busy()
        if why and not force:
            with self.lock:
                self.state["waiting"] = why
            return False, f"Not now: {why} The update installs when it's done."
        if not latest.get("sha256"):
            return False, "The release has no SHA-256 for its installer, so it can't be checked. Not installed."
        with self.lock:
            if self.state["installing"]:
                return False, "The update is already being installed."
            self.state.update(installing=latest["version"], waiting="")
        try:
            folder = os.path.join(self.folder, "updates")
            os.makedirs(folder, exist_ok=True)
            target = os.path.join(folder, os.path.basename(latest["name"]))
            got = self.download(latest["url"], target)
            if got.lower() != latest["sha256"].lower():
                os.remove(target)
                raise RuntimeError("the download doesn't match the published SHA-256")
            self.audit("updates: installing", detail={"by": by or "automatic", "from": self.current, "to": latest["version"]})
            self.log(f"Installing update {latest['version']} (from {self.current}); the program restarts by itself.")
            self.run_installer(target)
            return True, f"Installing {latest['version']}. The program closes and starts again in about a minute."
        except Exception as e:  # noqa: BLE001
            with self.lock:
                self.state.update(installing=None, error=f"Update failed: {e}")
            self.audit("updates: failed", detail={"by": by or "automatic", "to": latest["version"], "error": str(e)})
            return False, f"Update failed: {e}"

    def tick(self):
        """One periodic check: with updates on, install a newer version that wasn't skipped (when nothing is flying).
        With updates off it does nothing (no check)."""
        if not self.state["auto"]:
            return None
        latest = self.check()
        if not (self.state["auto"] and latest and self.newer(latest)) or self.state["installing"]:
            return None
        if latest["version"] == self.state["skipped"]:
            return None
        return self.install(by="automatic")

    def start(self):
        def run():
            time.sleep(FIRST_CHECK_AFTER)
            while True:
                try:
                    self.tick()
                except Exception as e:  # noqa: BLE001
                    self.log(f"Update check error: {e}")
                # Waiting for a flight to end: try again sooner.
                time.sleep(600 if self.state["waiting"] else CHECK_EVERY)
        threading.Thread(target=run, name="updater", daemon=True).start()


def frozen():
    """True in the installed program (PyInstaller / Nuitka), where installing updates makes sense."""
    return bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
