"""Sample pack scanning and role classification. Never trusts filenames alone: audio features break ties."""
from __future__ import annotations
import os
import re
import numpy as np
from . import audio
from .analysis import bpm_from_name, key_from_name

ROLE_KEYWORDS = [
    ("kick", r"\bkick|\bbd\b|bassdrum"),
    ("clap", r"clap"),
    ("snare", r"snare|\bsd\b|rim"),
    ("ohat", r"open\s*hat|\bohh?\b|open_hat"),
    ("chat", r"closed\s*hat|hi-?hat|\bhat\b|\bhh\b|\bchh\b"),
    ("shaker", r"shaker|shake|cabasa|maracas"),
    ("tom", r"\btom"),
    ("perc", r"perc|conga|bongo|cowbell|wood|rimshot|djembe|tabla"),
    ("top", r"top\s*loop|\btop\b"),
    ("bass", r"\bbass|\bsub\b|808"),
    ("vocal", r"vocal|vox|voice|chant"),
    ("pad", r"\bpad|atmos|texture"),
    ("atmos", r"ambien|drone|noise\s*bed"),
    ("impact", r"impact|crash|hit\b|boom"),
    ("uplifter", r"uplift|riser|rise|sweep\s*up|build"),
    ("downlifter", r"downlift|downsweep|fall|drop\s*fx"),
    ("fx", r"\bfx\b|effect|sfx|whoosh|transition"),
    ("synth", r"synth|lead|stab|chord|pluck|arp|keys|piano|organ|melod"),
]
DRUM_ROLES = {"kick", "clap", "snare", "ohat", "chat", "shaker", "tom", "perc"}


def _role_from_text(text: str) -> str | None:
    t = text.lower()
    for role, pat in ROLE_KEYWORDS:
        if re.search(pat, t):
            return role
    return None


def scan_pack(folder: str, bpm: float | None = None, max_files: int = 2000) -> dict:
    """Walk one folder, or several joined by os.pathsep; return samples, roles, hints and warnings."""
    folders = [f for f in str(folder).split(os.pathsep) if f.strip()]
    samples = []
    icloud = 0
    for base in folders:
        for root, _dirs, files in os.walk(base):
            for fn in sorted(files):
                if fn.endswith(".icloud"):
                    icloud += 1
                    continue
                if fn.startswith(".") or not fn.lower().endswith(audio.AUDIO_EXT):
                    continue
                path = os.path.join(root, fn)
                if _is_dataless(path):  # iCloud placeholder: opening it would stall on a download
                    icloud += 1
                    continue
                rel = os.path.relpath(path, base)
                d = _describe(path, fn, rel)
                if d:
                    samples.append(d)
                if len(samples) >= max_files:
                    break
    by_role: dict[str, list] = {}
    for s in samples:
        by_role.setdefault(s["role"], []).append(s)
    bpms = [s["bpm"] for s in samples if s["bpm"]]
    bpm_hint = max(set(bpms), key=bpms.count) if bpms else None
    keys = [s["key"]["pc"] for s in samples if s["key"]]
    key_hint = max(set(keys), key=keys.count) if keys else None
    has_kick = bool(by_role.get("kick"))
    has_drums = any(r in by_role for r in DRUM_ROLES)
    warnings = []
    if icloud:
        warnings.append(f"{icloud} files are still in iCloud and not on this Mac. In Finder: right-click the folder › Download Now, then scan again.")
    if not samples:
        warnings.append("No audio files in this folder.")
    elif not has_drums:
        warnings.append("No drums found. Choose the pack's TOP folder (the one that contains Drums, Loops and FX), or several folders at once.")
    elif not has_kick:
        warnings.append("No kick drum found. FLOW builds the groove around a kick; add one or choose the pack's top folder.")
    return {"folder": folder, "folders": folders, "count": len(samples), "samples": samples, "by_role": {k: len(v) for k, v in by_role.items()},
            "bpm_hint": bpm_hint, "key_hint": key_hint, "has_kick": has_kick, "has_drums": has_drums, "warnings": warnings,
            "_by_role": by_role}


SF_DATALESS = 0x40000000  # macOS: file content lives in iCloud, not on disk


def dataless_files(folder: str) -> list[str]:
    out = []
    for base in [f for f in str(folder).split(os.pathsep) if f.strip()]:
        for root, _dirs, files in os.walk(base):
            for fn in files:
                if fn.lower().endswith(audio.AUDIO_EXT) and _is_dataless(os.path.join(root, fn)):
                    out.append(os.path.join(root, fn))
    return out


def download_icloud(folder: str, progress=None, timeout: float = 600.0) -> dict:
    """macOS: ask iCloud to download every placeholder in the folder(s) and wait until they are local."""
    import subprocess, time, platform
    files = dataless_files(folder)
    if not files:
        return {"requested": 0, "remaining": 0}
    if platform.system() != "Darwin":
        return {"requested": len(files), "remaining": len(files), "error": "Automatic download is only available on macOS."}
    for i, f in enumerate(files):
        try:
            subprocess.run(["brctl", "download", f], check=False, capture_output=True, timeout=30)
        except Exception:
            pass
        if progress and i % 10 == 0:
            progress(f"Asking iCloud for {len(files)} files…", 0.05)
    t0 = time.time()
    remaining = files
    while remaining and time.time() - t0 < timeout:
        time.sleep(1.5)
        remaining = [f for f in files if _is_dataless(f)]
        if progress:
            progress(f"Downloading from iCloud: {len(files) - len(remaining)}/{len(files)}", 1 - len(remaining) / len(files))
    return {"requested": len(files), "remaining": len(remaining)}


def copy_pack_local(folder: str, dest_root: str | None = None, progress=None) -> str:
    """Copy the pack to a folder that iCloud does not evict (default ~/Music/FLOW Samples/<name>). Returns the new path(s)."""
    import shutil
    dest_root = dest_root or os.path.join(os.path.expanduser("~"), "Music", "FLOW Samples")
    os.makedirs(dest_root, exist_ok=True)
    outs = []
    for base in [f for f in str(folder).split(os.pathsep) if f.strip()]:
        name = os.path.basename(base.rstrip("/\\")) or "Pack"
        dst = os.path.join(dest_root, name)
        if os.path.abspath(dst) == os.path.abspath(base):
            outs.append(base)
            continue
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        if progress:
            progress(f"Copying {name} to {dest_root}", 0.5)
        shutil.copytree(base, dst, ignore=shutil.ignore_patterns(".*", "*.asd"))
        outs.append(dst)
    return os.pathsep.join(outs)


def _is_dataless(path: str) -> bool:
    try:
        st = os.stat(path)
    except OSError:
        return True
    flags = getattr(st, "st_flags", 0)
    return bool(flags & SF_DATALESS)


def _describe(path: str, fn: str, rel: str) -> dict | None:
    try:
        dur = audio.duration(path)
    except Exception:
        return None
    text = rel.replace(os.sep, " ")
    role = _role_from_text(fn) or _role_from_text(text) or ("loop" if dur > 3.5 else "oneshot")
    b = bpm_from_name(fn) or bpm_from_name(text)
    k = key_from_name(fn)
    is_loop = ("loop" in text.lower()) or (b is not None and dur >= 3.0) or dur >= 6.0
    return {"path": path, "name": fn, "rel": rel, "role": role, "duration": round(dur, 3),
            "bpm": b, "key": {"pc": k[0], "mode": k[1]} if k else None, "is_loop": bool(is_loop)}


def _features(path: str) -> dict:
    y, sr = audio.load(path, sr=22050, mono=True)
    m = y[0][: sr * 8]
    if len(m) < 512:
        return {"low": 0, "high": 0, "centroid": 0, "peak": 0}
    f, _t, S = audio.power_spectrogram(m, sr, n_fft=1024, hop=256)
    spec = S.mean(axis=1)
    tot = spec.sum() + 1e-12
    low = float(spec[(f >= 30) & (f < 150)].sum() / tot)
    high = float(spec[f >= 4000].sum() / tot)
    centroid = float((spec * f).sum() / tot)
    return {"low": low, "high": high, "centroid": centroid, "peak": float(np.abs(m).max())}


ROLE_LABELS = {"kick": "Kick", "clap": "Clap", "chat": "Closed hat", "ohat": "Open hat", "tom": "Tom", "perc": "Perc", "shaker_loop": "Shaker loop",
               "hat_loop": "Hat loop", "perc_loop": "Perc loop", "perc_loop2": "Perc loop 2", "bass": "Bass", "synth": "Synth", "pad": "Pad",
               "atmos": "Atmosphere", "impact": "Impact", "uplifter": "Uplifter", "downlifter": "Downlifter"}
KIT_ROLES = list(ROLE_LABELS)
MAX_CANDIDATES = 24


def candidates(pack: dict, bpm: float) -> dict[str, list[dict]]:
    """Every sample in the pack that could play each role, best first. Loops only when their BPM matches (no stretching)."""
    by_role = pack["_by_role"]

    def pool(role, want_loop=None):
        c = list(by_role.get(role, []))
        if want_loop is not None:
            c = [x for x in c if x["is_loop"] == want_loop]
        if want_loop:
            c = [x for x in c if x["bpm"] is None or abs(x["bpm"] - bpm) / bpm < 0.02]
        return c

    def ranked(cands, score_fn):
        if not cands:
            return []
        if score_fn is None or len(cands) == 1:
            return cands[:MAX_CANDIDATES]
        scored = []
        for c in cands[:12]:
            try:
                scored.append((score_fn(_features(c["path"])), c))
            except Exception:
                scored.append((float("-inf"), c))
        scored.sort(key=lambda x: -x[0])
        return ([c for _, c in scored] + cands[12:])[:MAX_CANDIDATES]

    def first(*lists):
        for lst in lists:
            if lst:
                return lst
        return []

    out = {}
    out["kick"] = ranked(pool("kick", False), lambda f: f["low"] - 0.3 * f["high"])
    out["clap"] = ranked(pool("clap", False), lambda f: f["peak"])
    out["ohat"] = ranked(pool("ohat", False), lambda f: f["high"])
    out["chat"] = ranked(pool("chat", False), lambda f: f["high"])
    out["tom"] = ranked(pool("tom", False), lambda f: f["low"])
    out["perc"] = ranked(pool("perc", False), None)
    out["shaker_loop"] = ranked(pool("shaker", True), None)
    out["hat_loop"] = ranked(pool("chat", True) + pool("ohat", True), None)
    perc_loops = pool("perc", True) + pool("top", True)
    out["perc_loop"] = ranked(perc_loops, None)
    out["perc_loop2"] = ranked(perc_loops[1:] + perc_loops[:1], None) if len(perc_loops) > 1 else []
    out["bass"] = ranked(first(pool("bass", False), pool("bass", True)), lambda f: f["low"])
    out["synth"] = ranked(first(pool("synth", False), pool("synth", True)), lambda f: -abs(f["centroid"] - 1500))
    out["pad"] = ranked(first(pool("pad", True), pool("pad")), None)
    out["atmos"] = ranked(first(pool("atmos"), pool("pad")[1:]), None)
    out["impact"] = ranked(pool("impact"), None)
    out["uplifter"] = ranked(pool("uplifter"), None)
    out["downlifter"] = ranked(pool("downlifter"), None)
    return {k: v for k, v in out.items() if v}


def choose_kit(pack: dict, bpm: float, overrides: dict | None = None, cands: dict | None = None) -> dict:
    """One sample per role: the user's pick where there is one, otherwise the best candidate."""
    cands = cands if cands is not None else candidates(pack, bpm)
    by_path = {s["path"]: s for s in pack.get("samples", [])}
    overrides = overrides or {}
    kit: dict[str, dict] = {}
    for role, lst in cands.items():
        ov = overrides.get(role)
        if ov == "":
            continue                      # the user took this role out
        if ov and ov in by_path:
            kit[role] = by_path[ov]
        else:
            kit[role] = lst[0]
    if kit.get("perc_loop2") and kit.get("perc_loop") and kit["perc_loop2"]["path"] == kit["perc_loop"]["path"]:
        alt = next((c for c in cands["perc_loop2"] if c["path"] != kit["perc_loop"]["path"]), None)
        if alt:
            kit["perc_loop2"] = alt
        else:
            kit.pop("perc_loop2")
    return kit


def kit_view(pack: dict, bpm: float, overrides: dict | None = None, cands: dict | None = None) -> list[dict]:
    """Rows for the UI: role, label, the chosen sample and every candidate, in kit order."""
    cands = cands if cands is not None else candidates(pack, bpm)
    kit = choose_kit(pack, bpm, overrides, cands)

    def summ(x):
        return {"name": x["name"], "path": x["path"], "rel": x.get("rel"), "duration": x["duration"], "bpm": x["bpm"], "is_loop": x["is_loop"]}

    rows = []
    for role in KIT_ROLES:
        if role not in cands:
            continue
        ch = kit.get(role)
        rows.append({"role": role, "label": ROLE_LABELS[role], "chosen": summ(ch) if ch else None, "candidates": [summ(c) for c in cands[role]]})
    return rows
