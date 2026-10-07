"""Transition sweeps: the bars before a drop get a rising high-pass + gain ramp, rendered from the track's own loop.

Rendered offline with scipy (one biquad, time-varying cutoff) so it is identical in every DAW.
"""
from __future__ import annotations
import os
import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi
from . import audio

SWEEP_BARS = 8
F_START, F_END = 40.0, 1800.0


def render_sweep(src_path: str, bpm: float, out_path: str, bars: int = SWEEP_BARS, sr: int = 48000, loop_bars: int | None = None) -> str:
    y, _ = audio.load(src_path, sr=sr)
    if y.shape[0] == 1:
        y = np.vstack([y, y])
    bar_len = 240.0 / bpm
    n = int(bar_len * bars * sr)
    tile = y[:, : int(bar_len * (loop_bars or max(1, round(y.shape[1] / sr / bar_len))) * sr)]
    if tile.shape[1] == 0:
        tile = y
    reps = int(np.ceil(n / tile.shape[1]))
    buf = np.tile(tile, (1, reps))[:, :n].astype(np.float32)
    # time-varying high-pass in 1/16-note blocks, exponential cutoff rise, plus a gentle gain ramp
    block = int(bar_len / 16 * sr)
    out = np.zeros_like(buf)
    zi = None
    for b0 in range(0, n, block):
        b1 = min(n, b0 + block)
        t = b0 / n
        fc = F_START * (F_END / F_START) ** (t ** 1.6)
        sos = butter(2, fc, btype="highpass", fs=sr, output="sos")
        if zi is None:
            zi = np.stack([sosfilt_zi(sos) * 0.0 for _ in range(2)])
        for c in range(2):
            out[c, b0:b1], zi[c] = sosfilt(sos, buf[c, b0:b1], zi=zi[c])
        out[:, b0:b1] *= 10 ** ((-6.0 * (1 - t)) / 20.0)
    peak = float(np.abs(out).max())
    if peak > 0.98:
        out *= 0.98 / peak
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    audio.write(out_path, out, sr)
    return out_path


def add_sweeps(plan: dict, work_dir: str, progress=None) -> int:
    """For every drop that follows another section, cut the last SWEEP_BARS bars of each loop track and
    replace them with a swept render. Mutates the plan: t['spans'] shrink, t['sweeps'] = [(bar, path)]."""
    bpm = plan["bpm"]
    drops = [s for s in plan["sections"] if (s["label"].startswith("Drop") or s["label"] == "Return") and s["start"] > SWEEP_BARS]
    count = 0
    for t in plan["tracks"]:
        if t.get("kind") == "midi" or t["role"] in ("kick", "impact", "uplifter", "downlifter", "snare_roll", "bass"):
            continue
        spans = t.get("spans", [])
        if not spans:
            continue
        new_spans, sweeps = [], []
        for s, e in spans:
            cur = s
            for d in drops:
                ws, we = d["start"] - SWEEP_BARS, d["start"]
                if cur < ws < e and we <= e:  # the window sits inside this span
                    new_spans.append((cur, ws))
                    sweeps.append(ws)
                    cur = we
            if cur < e:
                new_spans.append((cur, e))
        if sweeps:
            name = "".join(c for c in t["name"] if c.isalnum() or c in " -_")[:60]
            path = os.path.join(work_dir, f"{name} - sweep {SWEEP_BARS}bar.wav")
            render_sweep(t["source"]["path"], bpm, path, loop_bars=t.get("clip_bars") or None)
            t["spans"] = new_spans
            t["sweeps"] = [(b, path) for b in sweeps]
            t["sweep_bars"] = SWEEP_BARS
            count += len(sweeps)
            if progress:
                progress(f"Sweep: {t['name']}", 0.0)
    return count
