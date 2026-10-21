"""AI Command Centre Lebanon: license tool (VENDOR ONLY, keep on your own PC).

Setup, once:
    python license_tool.py init
        Creates your private signing key in C:\\AI-Security-Keys (outside the repo) and
        writes the matching public key into edge/app/licensing.py. Back the key folder up:
        without it you can't issue licenses that existing installs accept.

Issue a license for a customer laptop (they read the Machine ID from the app's License page):
    python license_tool.py issue --customer "Karim" --machine XXXX-XXXX-XXXX-XXXX-XXXX \
        --expires 2027-10-20 --cameras 4 --drones 1 \
        --features camera_ai face_ai lpr drone_live drone_ai drone_tracking
    -> writes license-<customer>-<machine>.lic; give that file to the customer.

Check a license file:
    python license_tool.py show license-....lic
"""
import argparse
import base64
import datetime
import json
import os
import re
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
import licensing  # noqa: E402

KEY_DIR = os.environ.get("AI_CC_KEY_DIR", r"C:\AI-Security-Keys")
PRIVATE_KEY = os.path.join(KEY_DIR, "license-signing-key.pem")
LICENSING_PY = os.path.join(HERE, "..", "app", "licensing.py")


def _load_private_key():
    from cryptography.hazmat.primitives import serialization
    with open(PRIVATE_KEY, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def cmd_init(args):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if os.path.exists(PRIVATE_KEY) and not args.force:
        print(f"Signing key already exists: {PRIVATE_KEY} (use --force to replace; old licenses would stop working)")
        key = _load_private_key()
    else:
        os.makedirs(KEY_DIR, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        with open(PRIVATE_KEY, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
        print(f"Created signing key: {PRIVATE_KEY}  <-- BACK THIS UP, NEVER SHARE IT")
    public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,
                                                            serialization.PublicFormat.Raw)).decode()
    src = open(LICENSING_PY, encoding="utf-8").read()
    src = re.sub(r'PUBLIC_KEY_B64 = "[^"]*"', f'PUBLIC_KEY_B64 = "{public}"', src)
    open(LICENSING_PY, "w", encoding="utf-8", newline="").write(src)
    print(f"Public key written into licensing.py: {public}")


def cmd_issue(args):
    datetime.date.fromisoformat(args.expires)  # validates the date
    unknown = set(args.features) - set(licensing.FEATURES)
    if unknown:
        sys.exit(f"Unknown feature(s): {', '.join(sorted(unknown))}. Choose from: {', '.join(licensing.FEATURES)}")
    payload = {
        "product": "AI Command Centre Lebanon",
        "license_id": str(uuid.uuid4()),
        "customer": args.customer,
        "machine_id": args.machine.strip().upper(),
        "issued": datetime.date.today().isoformat(),
        "expires": args.expires,
        "plan": args.plan,
        "features": sorted(set(args.features)),
        "limits": {"cameras": args.cameras, "drones": args.drones},
    }
    doc = licensing.sign(payload, _load_private_key())
    ok, reason, _ = licensing.verify(doc, machine=payload["machine_id"])
    if not ok:
        sys.exit(f"Self-check failed: {reason} (is the public key in licensing.py from this signing key?)")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", args.customer).strip("_") or "customer"
    out = args.out or f"license-{safe}-{payload['machine_id'][:9]}.lic"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"License written: {os.path.abspath(out)}")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_show(args):
    doc = licensing.load(args.file)
    ok, reason, payload = licensing.verify(doc, machine=(doc.get("license") or {}).get("machine_id"))
    print("Signature/expiry:", "VALID" if ok else reason)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description="AI Command Centre Lebanon license tool (vendor only)")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="create the signing key and embed the public key in the app")
    i.add_argument("--force", action="store_true")
    s = sub.add_parser("issue", help="issue a license for one laptop")
    s.add_argument("--customer", required=True)
    s.add_argument("--machine", required=True, help="Machine ID shown on the app's License page")
    s.add_argument("--expires", required=True, help="YYYY-MM-DD")
    s.add_argument("--plan", default="on-prem")
    s.add_argument("--cameras", type=int, default=4)
    s.add_argument("--drones", type=int, default=1)
    s.add_argument("--features", nargs="+", default=list(licensing.FEATURES))
    s.add_argument("--out")
    sh = sub.add_parser("show", help="inspect a license file")
    sh.add_argument("file")
    args = p.parse_args()
    {"init": cmd_init, "issue": cmd_issue, "show": cmd_show}[args.cmd](args)


if __name__ == "__main__":
    main()
