"""On-prem licences: signed, locked to one PC, expiring, and only the features they list.
A throwaway key pair is made for the test; the real signing key is never needed."""
import base64
import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import licensing  # noqa: E402

PC = "AAAA-BBBB-CCCC-DDDD-EEEE"


@pytest.fixture
def key(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", base64.b64encode(pub).decode())
    return k


def make(key, **changes):
    payload = {"customer": "Test", "plan": "pro", "machine_id": PC, "expires": "2099-01-01",
               "features": ["camera_ai", "face_ai", "lpr"], "limits": {"cameras": 4, "drones": 1}, **changes}
    return licensing.sign(payload, key)


def test_valid(key):
    assert licensing.verify(make(key), PC)[0]


@pytest.mark.parametrize("change", [
    lambda p: p["limits"].update(cameras=50),
    lambda p: p.update(expires="2199-01-01"),
    lambda p: p["features"].append("drone_control"),
])
def test_any_edit_breaks_the_signature(key, change):
    doc = make(key)
    change(doc["license"])
    ok, reason, _ = licensing.verify(doc, PC)
    assert not ok and "signature" in reason


def test_other_pc_and_expiry(key):
    assert "different computer" in licensing.verify(make(key), "ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ")[1]
    ok, reason, _ = licensing.verify(make(key, expires="2020-01-01"), PC)
    assert not ok and "expired" in reason


def test_lease_is_not_an_installable_licence(key):
    assert not licensing.verify(make(key, kind="saas-lease"), PC)[0]


def test_features_and_limits(key):
    f = licensing.features_for_dashboard(make(key)["license"])
    assert f["camera_ai"]["enabled"] and not f["drone_control"]["enabled"]
    assert f["camera_ai"]["limit_value"] == 4 and f["drone_live"]["limit_value"] == 1
