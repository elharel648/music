"""License key tool for the Alma owner.

  python tools/keygen.py init                 -> creates keys/private.pem (KEEP SECRET, BACK UP) and patches flow/license.py with the public key
  python tools/keygen.py issue EMAIL [--days N] -> prints a key for a customer (perpetual unless --days)
  python tools/keygen.py verify KEY           -> checks a key against the embedded public key
  python tools/keygen.py sign-update VERSION URL [--notes TEXT] -> writes packaging/latest.json (signed) for the in-app update check
"""
from __future__ import annotations
import argparse
import os
import re
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
KEY_DIR = os.path.join(ROOT, "keys")
PRIV = os.path.join(KEY_DIR, "private.pem")
LICENSE_PY = os.path.join(ROOT, "flow", "license.py")


def load_private() -> Ed25519PrivateKey:
    if not os.path.exists(PRIV):
        sys.exit("No private key. Run: python tools/keygen.py init")
    with open(PRIV, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def cmd_init(args):
    os.makedirs(KEY_DIR, exist_ok=True)
    if os.path.exists(PRIV) and not args.force:
        sys.exit(f"{PRIV} exists. Use --force to overwrite (this invalidates every key issued so far).")
    priv = Ed25519PrivateKey.generate()
    with open(PRIV, "wb") as f:
        f.write(priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    os.chmod(PRIV, 0o600)
    pub_hex = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    src = open(LICENSE_PY).read()
    src = re.sub(r'PUBLIC_KEY_HEX = "[0-9a-f]+"', f'PUBLIC_KEY_HEX = "{pub_hex}"', src)
    open(LICENSE_PY, "w").write(src)
    print("private key:", PRIV)
    print("public key embedded in flow/license.py:", pub_hex)


def cmd_issue(args):
    from flow import license as lic
    key = lic.issue_key(load_private(), args.email, args.days, args.seats)
    print(key)


def cmd_verify(args):
    from flow import license as lic
    print(lic.verify_key(args.key))


def cmd_sign_update(args):
    import json
    from flow import update
    man = update.sign_manifest(load_private(), args.version, args.url, args.notes or "")
    out = os.path.join(ROOT, "packaging", "latest.json")
    with open(out, "w") as f:
        json.dump(man, f, indent=1)
    from flow import license as lic
    assert update.verify(man, lic.PUBLIC_KEY_HEX), "signature does not verify against the embedded public key"
    print("wrote", out)
    print("publish it at:", update.UPDATE_URL)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init"); i.add_argument("--force", action="store_true")
    s = sub.add_parser("issue"); s.add_argument("email"); s.add_argument("--days", type=int); s.add_argument("--seats", type=int, default=1)
    v = sub.add_parser("verify"); v.add_argument("key")
    u = sub.add_parser("sign-update"); u.add_argument("version"); u.add_argument("url"); u.add_argument("--notes", default="")
    args = ap.parse_args()
    {"init": cmd_init, "issue": cmd_issue, "verify": cmd_verify, "sign-update": cmd_sign_update}[args.cmd](args)


if __name__ == "__main__":
    main()