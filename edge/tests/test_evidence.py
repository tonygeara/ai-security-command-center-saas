"""Evidence packs: signed, every file hashed, and any change shows."""
import io
import json
import os
import subprocess
import sys
import zipfile

import pytest

from conftest import APP, offset, wait_until

sys.path.insert(0, os.path.abspath(APP))
import evidence  # noqa: E402

JPG, MP4 = b"\xff\xd8snapshot", b"\x00\x00\x00\x18ftypmp42" + b"0" * 3000


@pytest.fixture
def pack(tmp_path):
    folder = tmp_path / "events"
    folder.mkdir()
    (folder / "ev1.jpg").write_bytes(JPG)
    (folder / "ev1_drone.mp4").write_bytes(MP4)
    inc = {"id": 7, "camera": "front", "title": "Drone 1 sent at front", "level": "response", "status": "closed",
           "started": 1790000000, "updated": 1790000300,
           "items": [{"t": 1790000000, "kind": "detection", "text": "Person seen"},
                     {"t": 1790000100, "kind": "dispatch", "text": "Drone 1 sent (auto)"}],
           "events": [{"id": 1, "t": 1790000050, "type": "UNKNOWN FACE", "snapshot": str(folder / "ev1.jpg")},
                      {"id": 2, "t": 1790000060, "type": "x", "snapshot": "../../etc/passwd"}]}
    track = [{"t": 1790000100 + i * 2, "drone": "drone", "lat": 45.5 + i * 1e-5, "lon": -75.6, "alt": 30} for i in range(5)]
    key = evidence.load_or_create_key(str(tmp_path))
    data, manifest, mhash = evidence.build(inc, track, str(folder), key, made_by="boss", product="Test", version="V1")
    return data, manifest, key, tmp_path


def rezip(data, change):
    """A copy of the pack with `change(name, bytes) -> bytes or None (drop)` applied, plus extra files."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n in src.namelist():
            b = change(n, src.read(n))
            if b is not None:
                z.writestr(n, b)
    return out.getvalue()


def test_pack_contents_and_valid_signature(pack):
    data, manifest, key, tmp = pack
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert {"manifest.json", "manifest.sig", "report.html", "track.csv", "files/ev1.jpg", "files/ev1_drone.mp4",
            "VERIFY.txt", "verify_evidence.py"} <= set(names)
    assert not any("passwd" in n for n in names)  # snapshot names can't reach outside the events folder
    assert manifest["track_points"] == 5 and manifest["incident"]["id"] == 7 and manifest["made_by"] == "boss"
    ok, problems, m = evidence.verify(data, expected_fingerprint=manifest["key_fingerprint"])
    assert ok and not problems
    assert evidence.load_or_create_key(str(tmp)).public_key().public_bytes_raw() == key.public_key().public_bytes_raw()  # same key next time


@pytest.mark.parametrize("what,change,expect", [
    ("photo", lambda n, b: b + b"x" if n == "files/ev1.jpg" else b, "Changed file: files/ev1.jpg"),
    ("video removed", lambda n, b: None if n.endswith(".mp4") else b, "Missing file: files/ev1_drone.mp4"),
    ("checker swapped", lambda n, b: b"print('VALID')" if n == "verify_evidence.py" else b, "Changed file: verify_evidence.py"),
    ("timeline edited", lambda n, b: b.replace(b"Person seen", b"Cat seen") if n == "manifest.json" else b, "signature does not match"),
])
def test_any_change_shows(pack, what, change, expect):
    data = rezip(pack[0], change)
    ok, problems, _ = evidence.verify(data)
    assert not ok and any(expect in p for p in problems), (what, problems)


def test_added_file_and_other_key_show(pack, tmp_path):
    data, manifest, _, _ = pack
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n in src.namelist():
            z.writestr(n, src.read(n))
        z.writestr("files/planted.jpg", b"\xff\xd8")
    ok, problems, _ = evidence.verify(out.getvalue())
    assert not ok and "File not in the manifest: files/planted.jpg" in problems
    ok, problems, _ = evidence.verify(data, expected_fingerprint="0000-0000")
    assert not ok and "different PC" in problems[0]


def test_bundled_checker_works_on_its_own(pack, tmp_path):
    data, manifest, _, _ = pack
    z = tmp_path / "pack.zip"
    z.write_bytes(data)
    zipfile.ZipFile(io.BytesIO(data)).extract("verify_evidence.py", tmp_path / "x")
    script = tmp_path / "x" / "verify_evidence.py"
    r = subprocess.run([sys.executable, str(script), str(z), manifest["key_fingerprint"]], capture_output=True, text=True)
    assert r.returncode == 0 and "VALID" in r.stdout
    bad = tmp_path / "bad.zip"
    bad.write_bytes(rezip(data, lambda n, b: b + b"x" if n == "files/ev1.jpg" else b))
    r = subprocess.run([sys.executable, str(script), str(bad)], capture_output=True, text=True)
    assert r.returncode == 1 and "changed files/ev1.jpg" in r.stdout


def test_response_track_and_pack_from_the_dashboard(d, client, fleet, monkeypatch):
    (v1,) = fleet(1)
    d._virtual_cfg["demo_auto"] = True
    monkeypatch.setattr(d, "_camera_snapshot", lambda camera: b"\xff\xd8cam")
    monkeypatch.setattr(d, "_drone_snapshot", lambda slot=None: b"\xff\xd8drone")
    monkeypatch.setattr(d, "_fetch_clip", lambda slot, start, end: None)
    monkeypatch.setattr(d, "CLIP_DELAY_S", 0)
    client.post("/api/response/settings", json={"camera_locations": {"evcam": offset(25, 0)}, "min_battery": 20,
                                                "hover_seconds": 5, "auto_return": True})
    r = d.dispatch_drone("evcam", by="test")
    assert r["ok"], r
    assert wait_until(lambda: not d.drone_response["active"], 120)
    d.PIPELINE.flush()
    inc = next(i for i in client.get("/api/incidents?days=1&min=3").get_json()["incidents"] if i["camera"] == "evcam")
    assert wait_until(lambda: any(e["type"] == "DRONE RESPONSE" for e in client.get(f"/api/incidents/{inc['id']}").get_json()["incident"]["events"]), 20)
    assert len(d.INCIDENTS.track(inc["id"])) >= 3
    r = client.get(f"/api/incidents/{inc['id']}/evidence.zip")
    assert r.status_code == 200 and r.mimetype == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert "track.csv" in names and any(n.startswith("files/drone_response_") for n in names)
    v = client.post("/api/evidence/verify", data={"pack": (io.BytesIO(r.data), "p.zip")}).get_json()
    assert v["valid"] and v["signed_here"] and v["incident"]["id"] == inc["id"]
    fp = client.get("/api/evidence/key").get_json()["fingerprint"]
    assert v["fingerprint"] == fp
    made = [a for a in d.audit.read(d.web_records.STORE, 50) if a["action"] == "evidence pack made"]
    assert made and made[0]["detail"]["fingerprint"] == fp and len(made[0]["detail"]["manifest_sha256"]) == 64
    bad = rezip(r.data, lambda n, b: b.replace(b"evcam", b"other") if n == "manifest.json" else b)
    assert client.post("/api/evidence/verify", data={"pack": (io.BytesIO(bad), "p.zip")}).get_json()["valid"] is False
    json.loads(zipfile.ZipFile(io.BytesIO(r.data)).read("manifest.json"))
