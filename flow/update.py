"""Update channel: a tiny signed manifest on a URL the owner controls. Nothing is downloaded or run automatically;
the app only shows "Update x.y" and opens the download page. The manifest is signed with the same Ed25519 key as the
license keys, so a hijacked host cannot point users at someone else's file. The request carries no identifying data.
"""
from __future__ import annotations
import json
import re
import urllib.request

from . import __version__, license as lic

UPDATE_URL = "https://raw.githubusercontent.com/elharel648/music/main/packaging/latest.json"


def canonical(version: str, url: str, notes: str) -> bytes:
    return f"{version}\n{url}\n{notes}".encode("utf-8")


def parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def verify(manifest: dict, public_key_hex: str | None = None) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex or lic.PUBLIC_KEY_HEX))
        pub.verify(lic._b64d(manifest["sig"]), canonical(manifest["version"], manifest["url"], manifest.get("notes", "")))
        return str(manifest["url"]).startswith("https://")
    except Exception:
        return False


def evaluate(manifest: dict, current: str = __version__, public_key_hex: str | None = None) -> dict:
    """Pure decision: {'available': bool, 'version', 'url', 'notes'}; a bad signature counts as 'no update'."""
    if not verify(manifest, public_key_hex):
        return {"available": False, "reason": "bad signature"}
    newer = parse_version(manifest["version"]) > parse_version(current)
    return {"available": newer, "version": manifest["version"], "url": manifest["url"], "notes": manifest.get("notes", "")}


def check(url: str = UPDATE_URL, timeout: float = 4.0) -> dict | None:
    """Fetch and evaluate the manifest. Any network or parse problem returns None; the app never blocks on this."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FLOW-update-check", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return None
            data = json.loads(r.read(65536).decode("utf-8"))
        return evaluate(data)
    except Exception:
        return None


def sign_manifest(private_key, version: str, url: str, notes: str = "") -> dict:
    return {"version": version, "url": url, "notes": notes, "sig": lic._b64e(private_key.sign(canonical(version, url, notes)))}
