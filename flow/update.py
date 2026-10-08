"""Update channel: a tiny signed manifest on a URL the owner controls.

The manifest is signed with the same Ed25519 key as the license keys, so a hijacked host cannot point users at someone
else's file. When it carries a `dmg` link and a `sha256`, the app downloads the new build in the background, checks the
hash, and offers "Restart to update": the bundle is staged next to the running one, swapped by a tiny helper after the
app quits, and reopened. Without `dmg` the chip just opens the download page. `min_version` marks builds that must
update before they build again. The check request carries no identifying data.
"""
from __future__ import annotations
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import json
import re
import urllib.request

from . import __version__, endpoints, license as lic

UPDATE_URL = f"{endpoints.SITE_URL}/latest.json" if endpoints.SITE_URL else "https://raw.githubusercontent.com/elharel648/music/main/packaging/latest.json"


def canonical(version: str, url: str, notes: str, dmg: str = "", sha256: str = "", min_version: str = "") -> bytes:
    base = f"{version}\n{url}\n{notes}"
    if dmg or sha256 or min_version:
        base += f"\n{dmg}\n{sha256}\n{min_version}"
    return base.encode("utf-8")


def parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def verify(manifest: dict, public_key_hex: str | None = None) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex or lic.PUBLIC_KEY_HEX))
        pub.verify(lic._b64d(manifest["sig"]), canonical(manifest["version"], manifest["url"], manifest.get("notes", ""),
                                                          manifest.get("dmg", ""), manifest.get("sha256", ""), manifest.get("min_version", "")))
        ok = str(manifest["url"]).startswith("https://")
        return ok and (not manifest.get("dmg") or str(manifest["dmg"]).startswith("https://"))
    except Exception:
        return False


def evaluate(manifest: dict, current: str = __version__, public_key_hex: str | None = None) -> dict:
    """Pure decision: {'available': bool, 'version', 'url', 'notes'}; a bad signature counts as 'no update'."""
    if not verify(manifest, public_key_hex):
        return {"available": False, "reason": "bad signature"}
    newer = parse_version(manifest["version"]) > parse_version(current)
    required = bool(manifest.get("min_version")) and parse_version(manifest["min_version"]) > parse_version(current)
    return {"available": newer, "version": manifest["version"], "url": manifest["url"], "notes": manifest.get("notes", ""),
            "dmg": manifest.get("dmg") or None, "sha256": manifest.get("sha256") or None, "size": manifest.get("size"), "required": newer and required}


def check(url: str = UPDATE_URL, timeout: float = 4.0) -> dict | None:
    """Fetch and evaluate the manifest. Any network or parse problem returns None; the app never blocks on this."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Alma-update-check", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return None
            data = json.loads(r.read(65536).decode("utf-8"))
        return evaluate(data)
    except Exception:
        return None


def sign_manifest(private_key, version: str, url: str, notes: str = "", dmg: str = "", sha256: str = "", size: int | None = None,
                  min_version: str = "") -> dict:
    man = {"version": version, "url": url, "notes": notes}
    if dmg:
        man.update({"dmg": dmg, "sha256": sha256, "size": size, "min_version": min_version or ""})
    man["sig"] = lic._b64e(private_key.sign(canonical(version, url, notes, dmg, sha256, min_version if dmg else "")))
    return man


# ---------------------------------------------------------------- download + install

def updates_dir() -> str:
    d = os.path.join(lic.data_dir(), "updates")
    os.makedirs(d, exist_ok=True)
    return d


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(info: dict, progress=None, timeout: float = 30.0) -> str:
    """Fetch the DMG named by an evaluated manifest into the updates folder, verify its sha256, return the path.
    Already-downloaded and verified files are reused. Raises on any mismatch."""
    dest = os.path.join(updates_dir(), f"Alma-{info['version']}-mac.dmg")
    if os.path.exists(dest) and sha256_of(dest) == info["sha256"]:
        return dest
    tmp = dest + ".part"
    req = urllib.request.Request(info["dmg"], headers={"User-Agent": "Alma-update"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or info.get("size") or 0)
        got, last = 0, -1
        while True:
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if progress and total:
                pct = int(got * 100 / total)
                if pct != last:
                    last = pct
                    progress(pct)
    if sha256_of(tmp) != info["sha256"]:
        os.remove(tmp)
        raise RuntimeError("The downloaded file does not match its signature. Nothing was installed.")
    os.replace(tmp, dest)
    return dest


def bundle_of(executable: str) -> str | None:
    """The .app bundle an executable lives in, or None when running from source."""
    p = os.path.abspath(executable)
    while p and p != os.path.dirname(p):
        if p.endswith(".app"):
            return p
        p = os.path.dirname(p)
    return None


def can_install() -> tuple[bool, str]:
    if sys.platform != "darwin":
        return False, "Self-update is macOS only for now."
    b = bundle_of(sys.executable)
    if not b:
        return False, "Running from source."
    if not os.access(os.path.dirname(b), os.W_OK):
        return False, f"No permission to replace {b}."
    return True, b


def install(dmg_path: str, bundle: str | None = None, relaunch: bool = True) -> dict:
    """Stage the new bundle next to the running one and hand the swap to a helper that waits for this process to quit,
    then reopens the app. Returns {'ok', 'staged', 'helper'}; the caller quits right after."""
    bundle = bundle or bundle_of(sys.executable)
    if not bundle:
        raise RuntimeError("Not running from an app bundle.")
    out = subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noverify", "-plist", dmg_path], capture_output=True, check=True)
    pl = plistlib.loads(out.stdout)
    mount = next(e["mount-point"] for e in pl["system-entities"] if e.get("mount-point"))
    try:
        src = next(os.path.join(mount, n) for n in os.listdir(mount) if n.endswith(".app"))
        parent = os.path.dirname(bundle)
        staged = os.path.join(parent, f".{os.path.basename(bundle)}.update")
        shutil.rmtree(staged, ignore_errors=True)
        subprocess.run(["ditto", src, staged], check=True)
        subprocess.run(["xattr", "-cr", staged], check=False)
    finally:
        subprocess.run(["hdiutil", "detach", mount, "-quiet"], check=False)
    old = os.path.join(parent, f".{os.path.basename(bundle)}.old")
    script = (f'while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.2; done; '
              f'rm -rf "{old}"; mv "{bundle}" "{old}" && mv "{staged}" "{bundle}" && rm -rf "{old}"; '
              f'sleep 0.3; ' + (f'open -n "{bundle}"' if relaunch else 'true'))
    helper = subprocess.Popen(["/bin/sh", "-c", script], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "staged": staged, "helper": helper.pid}
