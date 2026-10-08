"""Trial + license keys. Keys are Ed25519-signed tokens verified offline; the private key never ships.

Format of a key:  ALMA-<base64url(payload json)>.<base64url(signature)>
payload: {"email": ..., "issued": "YYYY-MM-DD", "expires": "YYYY-MM-DD" | null, "product": "Alma", "seats": 1}
"""
from __future__ import annotations
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import platform
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey, Ed25519PrivateKey
from cryptography.exceptions import InvalidSignature

TRIAL_DAYS = 14
PRODUCT = "Alma"
# Public key (hex). Replaced by tools/keygen.py --init; the matching private key stays with the owner.
PUBLIC_KEY_HEX = "e075583bfade38e3f2c167acd3c4c677c856f7c1798f304d6480a24b3d3a0a1b"
_STATE_SALT = b"flow-state-v1"


def data_dir() -> str:
    s = platform.system()
    home = os.path.expanduser("~")
    if s == "Darwin":
        d = os.path.join(home, "Library", "Application Support", PRODUCT)
    elif s == "Windows":
        d = os.path.join(os.environ.get("APPDATA", home), PRODUCT)
    else:
        d = os.path.join(home, ".config", "flow")
    os.makedirs(d, exist_ok=True)
    return d


def machine_id() -> str:
    raw = f"{platform.node()}|{uuid.getnode()}|{platform.machine()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _state_path() -> str:
    return os.path.join(data_dir(), "state.json")


def _sign_state(payload: dict) -> str:
    msg = json.dumps(payload, sort_keys=True).encode()
    return hmac.new(_STATE_SALT + machine_id().encode(), msg, hashlib.sha256).hexdigest()


def load_state() -> dict:
    p = _state_path()
    if os.path.exists(p):
        try:
            with open(p) as f:
                obj = json.load(f)
            payload, mac = obj.get("payload", {}), obj.get("mac", "")
            if hmac.compare_digest(mac, _sign_state(payload)) and payload.get("machine") == machine_id():
                return payload
        except Exception:
            pass
        # tampered or moved between machines: restart the clock at the earliest plausible date (today) but mark it
        payload = {"first_run": dt.date.today().isoformat(), "machine": machine_id(), "tampered": True, "key": None}
        save_state(payload)
        return payload
    payload = {"first_run": dt.date.today().isoformat(), "machine": machine_id(), "key": None}
    save_state(payload)
    return payload


def save_state(payload: dict) -> None:
    with open(_state_path(), "w") as f:
        json.dump({"payload": payload, "mac": _sign_state(payload)}, f)


def verify_key(key: str, public_key_hex: str | None = None) -> dict:
    """Return the payload if the key is valid for this product and not expired; raise ValueError otherwise."""
    public_key_hex = public_key_hex or PUBLIC_KEY_HEX
    key = key.strip()
    if not (key.startswith("ALMA-") or key.startswith("FLOW-")) or "." not in key:
        raise ValueError("That is not a Alma license key.")
    body, sig = key[5:].split(".", 1)
    payload_b = _b64d(body)
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex)).verify(_b64d(sig), payload_b)
    except (InvalidSignature, ValueError):
        raise ValueError("Invalid license key signature.")
    payload = json.loads(payload_b.decode())
    if payload.get("product") != PRODUCT:
        raise ValueError("This key is for a different product.")
    exp = payload.get("expires")
    if exp and dt.date.fromisoformat(exp) < dt.date.today():
        raise ValueError(f"This license expired on {exp}.")
    return payload


def issue_key(private_key: Ed25519PrivateKey, email: str, days: int | None = None, seats: int = 1) -> str:
    today = dt.date.today()
    payload = {"email": email, "issued": today.isoformat(), "expires": (today + dt.timedelta(days=days)).isoformat() if days else None,
               "product": PRODUCT, "seats": seats}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return "ALMA-" + _b64e(body) + "." + _b64e(private_key.sign(body))


def activate(key: str) -> dict:
    payload = verify_key(key)
    st = load_state()
    st["key"] = key.strip()
    save_state(st)
    return payload


def status() -> dict:
    st = load_state()
    if st.get("key"):
        try:
            p = verify_key(st["key"])
            return {"state": "licensed", "email": p.get("email"), "expires": p.get("expires"), "days_left": None}
        except ValueError as e:
            return {"state": "expired", "reason": str(e), "days_left": 0}
    first = dt.date.fromisoformat(st["first_run"])
    used = (dt.date.today() - first).days
    left = max(0, TRIAL_DAYS - used)
    return {"state": "trial" if left > 0 else "expired", "days_left": left, "first_run": st["first_run"],
            "reason": None if left > 0 else "Your 14-day trial has ended."}


def can_build() -> tuple[bool, dict]:
    s = status()
    return s["state"] in ("trial", "licensed"), s
