"""Rhythm patterns per role (beat offsets inside a bar, 0-4) and loop rendering from one-shots.

Patterns are genre conventions for 4/4 club music, taken from how reference projects place their hits.
They are deliberately simple: the structure comes from the reference, the patterns are a starting point.
"""
from __future__ import annotations
import os
import numpy as np
from . import audio, styles as stylelib

# (beats within a bar, every_n_bars, bar_offset)
PATTERNS = {
    "kick":  {"beats": [0, 1, 2, 3]},
    "clap":  {"beats": [1, 3]},
    "ohat":  {"beats": [0.5, 1.5, 2.5, 3.5], "gain": 0.8},
    "chat":  {"beats": [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5], "gain": 0.6, "accent": [0.5, 1.5, 2.5, 3.5]},
    "tom":   {"beats": [0, 0.76], "gain": 0.9},
    "tom_b": {"beats": [1.5], "gain": 0.8},
    "tom_c": {"beats": [3.5], "gain": 0.8, "every": 2},
    "perc":  {"beats": [3.5], "every": 2},
    "snare_roll": {"roll": True},
    "bass":  {"beats": [0.5, 1.5, 2.5, 3.5], "gain": 0.9, "pitch_cycle": [0, 0, 0, 0, 0, 0, 0, 7]},
    "synth": {"beats": [0, 1.5, 3, 3.5], "gain": 0.8, "pitch_cycle": [0, 3, 7, 10, 0, 3, 7, 12, 0, 3, 7, 10, 12, 10, 7, 3]},
}
MIDI_ROOT = {"bass": 36, "synth": 60}  # C1 for bass, C3 for synth (Live's C3 = 60)


def pattern_for(role: str, style: str | None = None) -> dict:
    """The pattern for `role` in `style`: the default, with the style's overrides on top."""
    base = PATTERNS.get(role, PATTERNS["perc"])
    over = stylelib.get(style).patterns.get(role) if style else None
    return {**base, **over} if over else base


def midi_notes(role: str, tonic_pc: int, bars: int = 4, style: str | None = None) -> list[dict]:
    """Notes in beats for a MIDI clip of `bars` bars, following the same pattern as the audio render."""
    p = pattern_for(role, style)
    root = MIDI_ROOT[role] + tonic_pc
    notes, k = [], 0
    every = p.get("every", 1)
    for b in range(bars):
        if every > 1 and (b % every) != every - 1:
            continue
        for beat in p["beats"]:
            st = p.get("pitch_cycle", [0])
            pitch = root + st[k % len(st)]
            k += 1
            notes.append({"pitch": int(pitch), "start_time": b * 4 + beat, "duration": 0.45 if role == "bass" else 0.3, "velocity": 100, "mute": False})
    return notes


def render_loop(role: str, sample_path: str, bpm: float, bars: int = 4, sr: int = 48000, transpose: float = 0.0, style: str | None = None) -> np.ndarray:
    """Render a `bars`-bar loop at `bpm` from a one-shot. Returns (2, n) float32."""
    y, _ = audio.load(sample_path, sr=sr)
    if y.shape[0] == 1:
        y = np.vstack([y, y])
    if transpose:
        y = audio.pitch_shift_resample(y, transpose)
    p = pattern_for(role, style)
    bar_len = 240.0 / bpm
    n = int(bar_len * bars * sr)
    buf = np.zeros((2, n), dtype=np.float32)
    gain = p.get("gain", 1.0)
    if p.get("roll"):
        # build roll: 8ths, then 16ths in the last bar, rising velocity
        hits = []
        for b in range(bars):
            div = 16 if b == bars - 1 else 8
            for i in range(div):
                hits.append((b * 4 + i * 4 / div, 0.4 + 0.6 * (b * 4 + i * 4 / div) / (bars * 4)))
        for t_beats, g in hits:
            _place(buf, y, t_beats * bar_len / 4, sr, g * gain)
        return _norm(buf)
    k = 0
    every = p.get("every", 1)
    for b in range(bars):
        if every > 1 and (b % every) != every - 1:
            continue
        for beat in p["beats"]:
            s = y
            if "pitch_cycle" in p:
                st = p["pitch_cycle"][k % len(p["pitch_cycle"])]
                k += 1
                if st:
                    s = audio.pitch_shift_resample(y, st)
            g = gain * (1.0 if beat in p.get("accent", [beat]) else 0.7)
            _place(buf, s, b * bar_len + beat * bar_len / 4, sr, g)
    return _norm(buf)


def _place(buf, s, t, sr, g):
    i0 = int(t * sr)
    i1 = min(buf.shape[1], i0 + s.shape[1])
    if i1 > i0:
        buf[:, i0:i1] += s[:, : i1 - i0] * g


def _norm(buf):
    peak = float(np.abs(buf).max())
    if peak > 0.98:
        buf *= 0.98 / peak
    return buf


def render_kit_loops(kit: dict, bpm: float, out_dir: str, transpose: dict | None = None, sr: int = 48000, style: str | None = None) -> dict:
    """Render loops for every one-shot role in the kit. Returns role -> {path, bars}."""
    os.makedirs(out_dir, exist_ok=True)
    out = {}
    roles = {"kick": "kick", "clap": "clap", "ohat": "ohat", "chat": "chat", "tom": "tom", "perc": "perc", "bass": "bass", "synth": "synth"}
    for role, pat in roles.items():
        s = kit.get(role)
        if not s or s.get("is_loop"):
            continue
        tr = (transpose or {}).get(role, 0.0)
        y = render_loop(pat, s["path"], bpm, 4, sr, tr, style)
        name = f"{os.path.splitext(s['name'])[0]} - {pat} {style or 'house'} 4bar.wav".replace("/", "-")
        path = os.path.join(out_dir, name)
        audio.write(path, y, sr)
        out[role] = {"path": path, "bars": 4, "source": s["name"]}
    if kit.get("tom") and not kit["tom"].get("is_loop"):
        for extra in ("tom_b", "tom_c"):
            y = render_loop(extra, kit["tom"]["path"], bpm, 4, sr, 0.0, style)
            path = os.path.join(out_dir, f"{os.path.splitext(kit['tom']['name'])[0]} - {extra} 4bar.wav")
            audio.write(path, y, sr)
            out[extra] = {"path": path, "bars": 4, "source": kit["tom"]["name"]}
    if kit.get("snare") or kit.get("clap"):
        src = kit.get("snare") or kit["clap"]
        y = render_loop("snare_roll", src["path"], bpm, 4, sr)
        path = os.path.join(out_dir, f"{os.path.splitext(src['name'])[0]} - build roll 4bar.wav")
        audio.write(path, y, sr)
        out["snare_roll"] = {"path": path, "bars": 4, "source": src["name"]}
    return out
