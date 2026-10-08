"""A vocal, optional: cut into phrases, fitted to the project's tempo and key, placed where the style wants it.

Tempo comes from the file name ("122 BPM") when present; without it the vocal is taken as already at the project
tempo. Key comes from the file name or from the audio. Pitch moves of up to 3 semitones are applied (sampler-style,
with the duration change undone by the stretch); larger moves are left alone and reported, because a vocal shifted
that far stops sounding like a person.
"""
from __future__ import annotations
import math
import os
import numpy as np
from . import audio, analysis

MAX_PHRASES = 6        # Live session slots are finite; phrases cycle beyond this
MAX_SHIFT = 3          # semitones
MIN_PHRASE_S = 0.45
GAP_S = 0.32


def split_phrases(mono: np.ndarray, sr: int, hop: int = 512) -> list[tuple[float, float]]:
    """(start, end) seconds of the sung phrases: RMS above a threshold relative to the peak, gaps merged, short bits dropped."""
    n = len(mono)
    if n < hop * 4:
        return []
    frames = n // hop
    x = mono[: frames * hop].reshape(frames, hop)
    rms = np.sqrt((x.astype(np.float64) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    thr = max(db.max() - 32.0, -52.0)
    active = db > thr
    out: list[list[float]] = []
    t = hop / sr
    cur = None
    for i, a in enumerate(active):
        if a and cur is None:
            cur = [i * t, (i + 1) * t]
        elif a:
            cur[1] = (i + 1) * t
        elif cur is not None and (i * t - cur[1]) > GAP_S:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    merged: list[list[float]] = []
    for s, e in out:
        if merged and s - merged[-1][1] <= GAP_S:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(max(0.0, s - 0.04), min(n / sr, e + 0.12)) for s, e in merged if (e - s) >= MIN_PHRASE_S]


def analyze(path: str) -> dict:
    """Cheap look at a vocal file: phrases, tempo hint, key."""
    y, sr = audio.load(path, sr=22050, mono=True)
    mono = y[0]
    name = os.path.basename(path)
    bpm = analysis.bpm_from_name(name) or analysis.bpm_from_name(os.path.basename(os.path.dirname(path)))
    k = analysis.key_from_name(name)
    key = {"pc": k[0], "mode": k[1], "source": "name", "confidence": 1.0} if k else None
    if not key:
        pc, mode, conf = analysis.estimate_key(mono[: sr * 90], sr)
        key = {"pc": pc, "mode": mode, "source": "audio", "confidence": conf} if conf >= 0.45 else None
    phrases = split_phrases(mono, sr)
    return {"path": path, "name": name, "duration": round(len(mono) / sr, 2), "bpm": bpm, "key": key,
            "phrases": [{"start": round(s, 3), "end": round(e, 3)} for s, e in phrases], "count": len(phrases)}


def prepare(info: dict, bpm: float, key_pc: int | None, work_dir: str, sr: int = 48000, progress=None) -> dict:
    """Render the phrases as files at the project tempo and key. Returns {name, phrases:[{path, seconds, bars}], notes:[...]}."""
    prog = progress or (lambda m, p: None)
    os.makedirs(work_dir, exist_ok=True)
    y, _ = audio.load(info["path"], sr=sr)
    if y.shape[0] == 1:
        y = np.vstack([y, y])
    n0 = y.shape[1]
    notes: list[str] = []
    rate = 1.0
    if info.get("bpm") and abs(info["bpm"] - bpm) / bpm > 0.004:
        rate = float(info["bpm"]) / float(bpm)
        notes.append(f"stretched from {info['bpm']:.0f} to {bpm:.0f} BPM")
    shift = 0
    if key_pc is not None and info.get("key") and info["key"].get("pc") is not None:
        d = (key_pc - info["key"]["pc"]) % 12
        d = d if d <= 6 else d - 12
        if d and abs(d) <= MAX_SHIFT:
            shift = d
            notes.append(f"moved {d:+d} semitones into the reference key")
        elif d:
            notes.append(f"left in its own key ({abs(d)} semitones away; too far to shift cleanly)")
    if shift:
        prog("Vocal: fitting the key", 0.0)
        y = audio.pitch_shift_resample(y, shift)
    target = int(round(n0 * rate))
    if abs(y.shape[1] - target) > sr * 0.01:
        prog("Vocal: fitting the tempo", 0.0)
        y = audio.time_stretch(y, target / y.shape[1])
    scale = y.shape[1] / n0
    bar_len = 240.0 / bpm
    phrases = []
    base = os.path.splitext(info["name"])[0]
    for i, ph in enumerate(info["phrases"][:MAX_PHRASES]):
        a, b = int(ph["start"] * sr * scale), int(ph["end"] * sr * scale)
        seg = y[:, a:b].copy()
        if seg.shape[1] < sr * 0.2:
            continue
        fi, fo = min(seg.shape[1] // 2, int(sr * 0.01)), min(seg.shape[1] // 2, int(sr * 0.04))
        seg[:, :fi] *= np.linspace(0, 1, fi, dtype=np.float32)
        seg[:, -fo:] *= np.linspace(1, 0, fo, dtype=np.float32)
        peak = float(np.abs(seg).max())
        if peak > 0:
            seg *= 0.7 / peak
        path = os.path.join(work_dir, f"{base} - phrase {i + 1:02d}.wav")
        audio.write(path, seg, sr)
        secs = seg.shape[1] / sr
        phrases.append({"path": path, "seconds": round(secs, 3), "bars": max(1, math.ceil(secs / bar_len - 0.08))})
    prog(f"Vocal: {len(phrases)} phrases ready", 1.0)
    return {"name": info["name"], "phrases": phrases, "notes": notes, "bpm": bpm, "shift": shift, "rate": rate}
