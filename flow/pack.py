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
    """Walk a folder; return {'samples': [...], 'by_role': {...}, 'bpm_hint': ..., 'key_hint': ...}."""
    samples = []
    for root, _dirs, files in os.walk(folder):
        for fn in sorted(files):
            if fn.startswith(".") or not fn.lower().endswith(audio.AUDIO_EXT):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, folder)
            try:
                dur = audio.duration(path)
            except Exception:
                continue
            text = rel.replace(os.sep, " ")
            role = _role_from_text(fn) or _role_from_text(text) or ("loop" if dur > 3.5 else "oneshot")
            b = bpm_from_name(fn) or bpm_from_name(text)
            k = key_from_name(fn)
            is_loop = ("loop" in text.lower()) or (b is not None and dur >= 3.0) or dur >= 6.0
            samples.append({"path": path, "name": fn, "rel": rel, "role": role, "duration": round(dur, 3),
                            "bpm": b, "key": {"pc": k[0], "mode": k[1]} if k else None, "is_loop": bool(is_loop)})
            if len(samples) >= max_files:
                break
    by_role: dict[str, list] = {}
    for s in samples:
        by_role.setdefault(s["role"], []).append(s)
    bpms = [s["bpm"] for s in samples if s["bpm"]]
    bpm_hint = max(set(bpms), key=bpms.count) if bpms else None
    keys = [s["key"]["pc"] for s in samples if s["key"]]
    key_hint = max(set(keys), key=keys.count) if keys else None
    return {"folder": folder, "count": len(samples), "samples": samples, "by_role": {k: len(v) for k, v in by_role.items()},
            "bpm_hint": bpm_hint, "key_hint": key_hint, "_by_role": by_role}


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


def choose_kit(pack: dict, bpm: float) -> dict:
    """Pick one sample per role. Loops only when their BPM matches the target (no time-stretching here)."""
    by_role = pack["_by_role"]
    kit: dict[str, dict] = {}

    def pick(role, score_fn=None, want_loop=None):
        cands = by_role.get(role, [])
        if want_loop is not None:
            cands = [c for c in cands if c["is_loop"] == want_loop]
        if want_loop:
            cands = [c for c in cands if c["bpm"] is None or abs(c["bpm"] - bpm) / bpm < 0.02]
        if not cands:
            return None
        if score_fn is None or len(cands) == 1:
            return cands[0]
        scored = []
        for c in cands[:12]:
            try:
                scored.append((score_fn(_features(c["path"])), c))
            except Exception:
                continue
        return max(scored, key=lambda x: x[0])[1] if scored else cands[0]

    kit["kick"] = pick("kick", lambda f: f["low"] - 0.3 * f["high"], want_loop=False)
    kit["clap"] = pick("clap", lambda f: f["peak"], want_loop=False)
    kit["ohat"] = pick("ohat", lambda f: f["high"], want_loop=False)
    kit["chat"] = pick("chat", lambda f: f["high"], want_loop=False)
    kit["tom"] = pick("tom", lambda f: f["low"], want_loop=False)
    kit["perc"] = pick("perc", None, want_loop=False)
    kit["shaker_loop"] = pick("shaker", None, want_loop=True)
    kit["hat_loop"] = pick("chat", None, want_loop=True) or pick("ohat", None, want_loop=True)
    kit["perc_loop"] = pick("perc", None, want_loop=True) or pick("top", None, want_loop=True)
    perc_loops = [c for c in by_role.get("perc", []) + by_role.get("top", []) if c["is_loop"]]
    kit["perc_loop2"] = perc_loops[1] if len(perc_loops) > 1 else None
    kit["bass"] = pick("bass", lambda f: f["low"], want_loop=False) or pick("bass", None, want_loop=True)
    kit["synth"] = pick("synth", lambda f: -abs(f["centroid"] - 1500), want_loop=False) or pick("synth", None, want_loop=True)
    kit["pad"] = pick("pad", None, want_loop=True) or pick("pad", None)
    kit["atmos"] = pick("atmos", None) or (by_role.get("pad", [None])[1] if len(by_role.get("pad", [])) > 1 else None)
    kit["impact"] = pick("impact", None)
    kit["uplifter"] = pick("uplifter", None)
    kit["downlifter"] = pick("downlifter", None)
    return {k: v for k, v in kit.items() if v}
