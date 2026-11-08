"""Evidence packs: one signed file per incident that police, insurers or a court can check.

A pack is a ZIP:
    manifest.json      what happened (incident, timeline, drone track) and the SHA-256 of every file
    manifest.sig       Ed25519 signature of manifest.json, made with this PC's evidence key
    report.html        the same, readable in any browser (open it from the unzipped folder)
    files/...          camera snapshots, the drone's photo and video clip
    track.csv          the drone's GPS track during the response (if a drone was sent)
    VERIFY.txt + verify_evidence.py   how anyone can check the pack

Each PC makes its own key pair the first time (evidence_signing.key in the data folder; the private
key never leaves the PC). The public key and its fingerprint are inside every pack and shown on the
Incidents page, so the customer can hand the fingerprint to whoever receives packs. Making a pack is
also written to the audit log with the manifest's hash.

What a valid pack proves: nothing in it changed after this PC made it. It does not prove the camera
saw the truth; the timeline and files are what the system recorded.
"""
import base64
import csv
import datetime
import hashlib
import html
import io
import json
import os
import zipfile

FORMAT = "ai-security-evidence/1"
KEY_FILE = "evidence_signing.key"


# ---------------- keys ----------------
def load_or_create_key(data_folder):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    path = os.path.join(data_folder, KEY_FILE)
    try:
        with open(path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)
    except FileNotFoundError:
        pass
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(pem)
    os.replace(tmp, path)
    return key


def public_key_b64(key):
    from cryptography.hazmat.primitives import serialization
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def fingerprint(pub_b64):
    """Short form people can read out or print: 8 groups of 4 hex digits."""
    h = hashlib.sha256(base64.b64decode(pub_b64)).hexdigest().upper()[:32]
    return "-".join(h[i:i + 4] for i in range(0, 32, 4))


# ---------------- building ----------------
def _ts(t):
    return datetime.datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")


def _safe_file(folder, name):
    """A file inside `folder` named by the basename of `name` (never outside it), or None."""
    base = os.path.basename(str(name or "").replace("\\", "/"))
    if not base:
        return None
    path = os.path.join(folder, base)
    return path if os.path.isfile(path) else None


def build(incident, track, event_folder, key, made_by="", product="", version="", now=None):
    """The pack as bytes, and its manifest. `incident` is incidents.Incidents.get(); `track` a list of
    {"t","drone","lat","lon","alt"}."""
    import time as _time
    now = now or _time.time()
    files = {}  # path in zip -> bytes

    attached = []
    for ev in incident.get("events", []):
        snap = _safe_file(event_folder, ev.get("snapshot"))
        if not snap:
            continue
        stem = os.path.splitext(snap)[0]
        for path, label in ((snap, "camera snapshot"), (stem + "_drone.jpg", "drone photo"), (stem + "_drone.mp4", "drone video")):
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    files["files/" + os.path.basename(path)] = f.read()
                attached.append({"path": "files/" + os.path.basename(path), "what": label, "event_id": ev.get("id"),
                                 "event_type": ev.get("type"), "time": _ts(ev.get("t") or 0)})

    if track:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["time", "drone", "lat", "lon", "alt_m"])
        for p in track:
            w.writerow([_ts(p["t"]), p.get("drone", ""), p["lat"], p["lon"], p.get("alt", "")])
        files["track.csv"] = out.getvalue().encode("utf-8")

    timeline = [{"time": _ts(x["t"]), "what": x["text"], "kind": x["kind"]} for x in incident.get("items", [])]
    manifest = {
        "format": FORMAT,
        "made": _ts(now), "made_by": made_by, "product": product, "version": version,
        "incident": {"id": incident["id"], "camera": incident["camera"], "title": incident["title"],
                     "level": incident.get("level"), "started": _ts(incident["started"]), "updated": _ts(incident["updated"]),
                     "status": incident.get("status")},
        "timeline": timeline,
        "attachments": attached,
        "track_points": len(track or []),
        "public_key": public_key_b64(key),
    }
    manifest["key_fingerprint"] = fingerprint(manifest["public_key"])
    files["report.html"] = _report(manifest, track).encode("utf-8")
    files["VERIFY.txt"] = VERIFY_TXT.replace("__FP__", manifest["key_fingerprint"]).encode("utf-8")
    files["verify_evidence.py"] = VERIFY_SCRIPT.encode("utf-8")  # hashed too: a swapped checker would show
    manifest["files"] = [{"path": p, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for p, b in sorted(files.items())]
    mbytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    sig = base64.b64encode(key.sign(mbytes))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", mbytes)
        z.writestr("manifest.sig", sig)
        for p, b in sorted(files.items()):
            z.writestr(p, b, compress_type=zipfile.ZIP_STORED if p.endswith((".jpg", ".mp4")) else zipfile.ZIP_DEFLATED)
    return buf.getvalue(), manifest, hashlib.sha256(mbytes).hexdigest()


def _report(m, track):
    e = html.escape
    rows = "".join(f"<tr><td>{e(x['time'])}</td><td>{e(x['what'])}</td></tr>" for x in m["timeline"])
    pics = "".join(f'<figure><img src="{e(a["path"])}" alt=""><figcaption>{e(a["what"])} · {e(a["time"])}</figcaption></figure>'
                   if a["path"].endswith(".jpg") else f'<p>▶ <a href="{e(a["path"])}">{e(a["what"])}</a> · {e(a["time"])}</p>'
                   for a in m["attachments"])
    trk = ""
    if track:
        first, last = track[0], track[-1]
        trk = (f"<h2>Drone track</h2><p>{len(track)} GPS points from {e(_ts(first['t']))} to {e(_ts(last['t']))} "
               f"(see track.csv). Start {first['lat']:.6f}, {first['lon']:.6f}; end {last['lat']:.6f}, {last['lon']:.6f}.</p>")
    inc = m["incident"]
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Incident {inc['id']} evidence</title>
<style>body{{font:14px Arial,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#111}}table{{border-collapse:collapse;width:100%}}
td{{border-top:1px solid #ddd;padding:5px 8px;vertical-align:top}}figure{{display:inline-block;margin:6px}}img{{max-width:400px;border:1px solid #ccc}}
.k{{font-family:monospace;background:#f3f3f3;padding:2px 5px}}</style></head><body>
<h1>{e(inc['title'])}</h1>
<p>Camera <b>{e(inc['camera'])}</b> · level <b>{e(str(inc['level']))}</b> · from {e(inc['started'])} to {e(inc['updated'])}</p>
<p>Evidence pack made {e(m['made'])}{' by ' + e(m['made_by']) if m['made_by'] else ''} with {e(m['product'])} {e(m['version'])}.
Signing key fingerprint: <span class="k">{e(m['key_fingerprint'])}</span>. See VERIFY.txt to check this pack.</p>
<h2>Timeline</h2><table>{rows}</table>{trk}<h2>Pictures and video</h2>{pics or '<p>None saved.</p>'}</body></html>"""


# ---------------- checking ----------------
def verify(zip_bytes, expected_fingerprint=None):
    """(ok, problems, manifest). Checks the signature and every file's hash; no file may be added."""
    problems = []
    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
        mbytes, sig = z.read("manifest.json"), z.read("manifest.sig")
        manifest = json.loads(mbytes)
    except Exception as e:
        return False, [f"Not an evidence pack ({e})."], None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(base64.b64decode(manifest["public_key"])).verify(base64.b64decode(sig), mbytes)
    except Exception:
        problems.append("The signature does not match: manifest.json was changed or signed with another key.")
    fp = fingerprint(manifest.get("public_key", "")) if manifest.get("public_key") else ""
    if expected_fingerprint and fp.replace("-", "").upper() != expected_fingerprint.replace("-", "").replace(" ", "").upper():
        problems.append(f"Signed by a different PC (key {fp}).")
    listed = {f["path"]: f for f in manifest.get("files", [])}
    for path, f in listed.items():
        try:
            data = z.read(path)
        except KeyError:
            problems.append(f"Missing file: {path}")
            continue
        if hashlib.sha256(data).hexdigest() != f["sha256"]:
            problems.append(f"Changed file: {path}")
    extra = set(z.namelist()) - set(listed) - {"manifest.json", "manifest.sig"}
    problems += [f"File not in the manifest: {p}" for p in sorted(extra)]
    return not problems, problems, manifest


VERIFY_TXT = """HOW TO CHECK THIS EVIDENCE PACK

This pack was signed by the PC that recorded it. Its signing key fingerprint is:

    __FP__

Ask the owner of the system to confirm this fingerprint (it is shown on their dashboard under
Settings -> Incidents). If it matches, and the check below passes, nothing in this pack has been
changed since that PC made it.

To check (needs Python 3 and the "cryptography" package: pip install cryptography):

    python verify_evidence.py <this-pack>.zip __FP__

Or upload the pack on the system's dashboard: Settings -> Incidents -> Check an evidence pack.
"""

VERIFY_SCRIPT = r'''"""Check an evidence pack: python verify_evidence.py pack.zip [expected key fingerprint]"""
import base64, hashlib, io, json, sys, zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def main(path, expected=None):
    z = zipfile.ZipFile(path)
    mbytes, sig = z.read("manifest.json"), z.read("manifest.sig")
    m = json.loads(mbytes)
    bad = []
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(m["public_key"])).verify(base64.b64decode(sig), mbytes)
    except Exception:
        bad.append("signature does not match")
    h = hashlib.sha256(base64.b64decode(m["public_key"])).hexdigest().upper()[:32]
    fp = "-".join(h[i:i + 4] for i in range(0, 32, 4))
    if expected and fp.replace("-", "") != expected.replace("-", "").replace(" ", "").upper():
        bad.append("signed by a different key: " + fp)
    listed = {f["path"]: f for f in m["files"]}
    for p, f in listed.items():
        if p not in z.namelist():
            bad.append("missing " + p)
        elif hashlib.sha256(z.read(p)).hexdigest() != f["sha256"]:
            bad.append("changed " + p)
    for p in set(z.namelist()) - set(listed) - {"manifest.json", "manifest.sig"}:
        bad.append("not in manifest " + p)
    print("Key fingerprint:", fp)
    print("VALID: nothing was changed." if not bad else "NOT VALID:\n  " + "\n  ".join(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
'''
