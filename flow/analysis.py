"""Reference analysis: tempo, grid, key, per-bar energy map, section boundaries and labels.

Everything here is measured, not guessed. The output is the 'Blueprint' the arrangement is built from.
"""
from __future__ import annotations
import os
import re
import numpy as np
from . import audio

PC_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
BANDS = {"sub": (20, 120), "low": (120, 300), "mid": (300, 2000), "high": (2000, 11000)}


def bpm_from_name(name: str) -> float | None:
    m = re.search(r"(\d{2,3}(?:[.,]\d+)?)\s*bpm", name, re.I)
    if m:
        v = float(m.group(1).replace(",", "."))
        if 50 <= v <= 220:
            return v
    return None


def key_from_name(name: str) -> tuple[int, str] | None:
    m = re.search(r"(?<![A-Za-z0-9])([A-G])(#|b)?\s*(min|minor|m\b|maj|major)?(?![A-Za-z])", name)
    if not m:
        return None
    pc = PC_NAMES.index(m.group(1).upper())
    if m.group(2) == "#":
        pc = (pc + 1) % 12
    elif m.group(2) == "b":
        pc = (pc - 1) % 12
    q = (m.group(3) or "").lower()
    mode = "unknown" if not q else ("major" if q.startswith("maj") else "minor")
    return pc, mode


def estimate_tempo(env: np.ndarray, fr: float, lo: float = 60, hi: float = 200, prefer=(100, 140)) -> tuple[float, dict]:
    """Autocorrelation tempo estimate with an octave prior for club music."""
    e = env - env.mean()
    n = len(e)
    ac = np.correlate(e, e, mode="full")[n - 1:]
    ac = ac / (ac[0] + 1e-9)
    cands = np.arange(lo, hi + 0.01, 0.25)
    scores = []
    for bpm in cands:
        lag = 60.0 / bpm * fr
        s = 0.0
        for k, w in ((1, 1.0), (2, 0.6), (4, 0.3)):
            L = lag * k
            i = int(L)
            if i + 1 >= n:
                continue
            frac = L - i
            s += w * ((1 - frac) * ac[i] + frac * ac[i + 1])
        scores.append(s)
    scores = np.array(scores)
    best_i = int(np.argmax(scores))
    best = float(cands[best_i])
    best_score = float(scores[best_i])
    choice = best
    for alt in (best * 2, best / 2):
        if prefer[0] <= alt <= prefer[1] and not (prefer[0] <= best <= prefer[1]):
            j = int(np.argmin(np.abs(cands - alt)))
            if scores[j] >= 0.6 * best_score:
                choice = float(cands[j])
    # most club tracks sit on an integer BPM
    if abs(choice - round(choice)) <= 0.6:
        choice = float(round(choice))
    return choice, {"raw_best": best, "raw_score": round(best_score, 3)}


def grid_origin(env: np.ndarray, fr: float, beat_len: float) -> float:
    """Phase of the beat grid (seconds) that lines up with the most onset energy."""
    step = beat_len / 32
    best, best_s = 0.0, -1.0
    n = len(env)
    for off in np.arange(0, beat_len, step):
        idx = (np.arange(off, n / fr, beat_len) * fr).astype(int)
        idx = idx[idx < n - 1]
        s = float(env[idx].sum())
        if s > best_s:
            best, best_s = float(off), s
    return best if best < 0.3 * beat_len else 0.0


def estimate_key(mono: np.ndarray, sr: int) -> tuple[int, str, float]:
    """Krumhansl key finding on a high-resolution chroma of the 150–3000 Hz band."""
    f, _t, S = audio.power_spectrogram(mono, sr, n_fft=8192, hop=2048)
    mask = (f >= 150) & (f < 3000)
    ff = f[mask]
    pcs = (np.round(12 * np.log2(ff / 440.0)) + 69).astype(int) % 12
    mag = np.log1p(S[mask].mean(axis=1) * 1e3)
    prof = np.array([mag[pcs == pc].sum() for pc in range(12)])
    prof = (prof - prof.mean()) / (prof.std() + 1e-9)
    best = (-2.0, 0, "minor")
    for i in range(12):
        for mode, p in (("major", _MAJ), ("minor", _MIN)):
            c = float(np.corrcoef(np.roll(p, i), prof)[0, 1])
            if c > best[0]:
                best = (c, i, mode)
    return best[1], best[2], round(best[0], 2)


def analyze_reference(path: str, bpm_hint: float | None = None, prefer_range=(100, 140), sr: int = 22050) -> dict:
    y, _ = audio.load(path, sr=sr, mono=True)
    mono = y[0]
    dur = len(mono) / sr
    freqs, times, S = audio.power_spectrogram(mono, sr)
    hop = 512
    fr = sr / hop
    env = audio.onset_envelope(S)
    low_env = audio.onset_envelope(S[(freqs >= 30) & (freqs < 150)])

    hint = bpm_hint or bpm_from_name(os.path.basename(path))
    if hint:
        bpm = float(hint)
        tempo_info = {"source": "hint"}
    else:
        bpm, tempo_info = estimate_tempo(env, fr, prefer=prefer_range)
        tempo_info["source"] = "estimated"
    beat_len = 60.0 / bpm
    bar_len = beat_len * 4
    origin = grid_origin(env, fr, beat_len)
    n_bars = int(np.floor((dur - origin) / bar_len))

    pc, mode, conf = estimate_key(mono, sr)
    name_key = key_from_name(os.path.basename(path))
    if name_key and name_key[1] != "unknown":
        pc, mode, conf = name_key[0], name_key[1], 1.0

    def peaks_of(e):
        thr = e.mean() + 1.0 * e.std()
        p = np.where((e[1:-1] > e[:-2]) & (e[1:-1] >= e[2:]) & (e[1:-1] > thr))[0] + 1
        return p / fr

    onset_times = peaks_of(env)
    low_onsets = peaks_of(low_env)

    bars = []
    band_masks = {k: (freqs >= lo) & (freqs < hi) for k, (lo, hi) in BANDS.items()}
    for b in range(n_bars):
        t0 = origin + b * bar_len
        t1 = t0 + bar_len
        f0, f1 = int(t0 * fr), max(int(t1 * fr), int(t0 * fr) + 1)
        seg = S[:, f0:f1]
        tot = float(seg.sum()) + 1e-12
        row = {"bar": b + 1, "t0": round(t0, 3), "rms_db": round(audio.db(float(seg.mean())), 1)}
        for k, m in band_masks.items():
            row[k] = round(float(seg[m].sum() / tot * 100), 1)
            row[k + "_db"] = round(audio.db(float(seg[m].mean())), 1)
        row["onsets"] = int(((onset_times >= t0) & (onset_times < t1)).sum())
        row["low_onsets"] = int(((low_onsets >= t0) & (low_onsets < t1)).sum())
        bars.append(row)

    # trim the tail (reverb/impact tails after the last real bar): quiet AND no kick
    peak_rms = max(r["rms_db"] for r in bars) if bars else 0
    while len(bars) > 8 and bars[-1]["rms_db"] < peak_rms - 14 and bars[-1]["low_onsets"] == 0:
        bars.pop()
    n_bars = len(bars)

    sections = detect_sections(bars)
    label_sections(sections, bars)
    elements = element_map(bars)
    return {
        "file": os.path.basename(path), "path": path, "duration": round(dur, 2),
        "bpm": round(bpm, 2), "tempo_info": tempo_info, "grid_origin": round(origin, 3),
        "bars": n_bars, "key": {"tonic": PC_NAMES[pc], "pc": pc, "mode": mode, "confidence": conf},
        "sections": sections, "elements": elements, "bar_features": bars,
    }


def _feature_matrix(bars: list[dict]) -> np.ndarray:
    F = np.array([[r["rms_db"], r["sub_db"], r["low_db"], r["mid_db"], r["high_db"], r["onsets"], 3 * min(r["low_onsets"], 4)] for r in bars], dtype=float)
    return (F - F.mean(axis=0)) / (F.std(axis=0) + 1e-9)


def detect_sections(bars: list[dict], min_gap: int = 8) -> list[dict]:
    n = len(bars)
    if n < 12:
        return [{"start": 1, "end": n + 1}]
    F = _feature_matrix(bars)
    cands, nov = [], []
    for b in range(4, n - 3):  # boundary before 0-based bar index b => bar number b+1
        if b % 4 != 0:
            continue
        a = F[max(0, b - 4):b].mean(axis=0)
        c = F[b:b + 4].mean(axis=0)
        cands.append(b)
        nov.append(float(np.linalg.norm(a - c)))
    nov = np.array(nov)
    if len(nov) == 0:
        return [{"start": 1, "end": n + 1}]
    med = np.median(nov)
    mad = np.median(np.abs(nov - med)) + 1e-9
    thr = med + 1.5 * mad
    order = np.argsort(-nov)
    chosen = []
    for i in order:
        if nov[i] < thr or len(chosen) >= 12:
            break
        b = cands[i]
        if all(abs(b - c) >= min_gap for c in chosen):
            chosen.append(b)
    chosen = sorted(chosen)
    starts = [0] + chosen
    sections = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else n
        sections.append({"start": s + 1, "end": e + 1, "novelty": round(float(nov[cands.index(s)]), 2) if s in cands else None})
    return sections


def _kick_present(bars: list[dict]) -> np.ndarray:
    return np.array([r["low_onsets"] >= 3 for r in bars])


def _hats_present(bars: list[dict]) -> np.ndarray:
    hi = np.array([r["high_db"] for r in bars])
    ref = np.percentile(hi, 90)
    return hi > ref - 9


def label_sections(sections: list[dict], bars: list[dict]) -> None:
    kick = _kick_present(bars)
    rms = np.array([r["rms_db"] for r in bars])
    peak = float(np.percentile(rms, 95))
    for s in sections:
        sl = slice(s["start"] - 1, s["end"] - 1)
        s["kick_ratio"] = round(float(kick[sl].mean()), 2)
        s["energy_db"] = round(float(rms[sl].mean()), 1)
        s["bars"] = s["end"] - s["start"]
    drop_n = 0
    last_was_break = False
    for i, s in enumerate(sections):
        is_last = i == len(sections) - 1
        if i == 0:
            s["label"] = "Intro"
            continue
        if s["kick_ratio"] < 0.35:
            nxt = sections[i + 1] if not is_last else None
            if is_last:
                s["label"] = "Outro"
            elif nxt and nxt["kick_ratio"] >= 0.35 and s["bars"] <= 8 and (last_was_break or s["energy_db"] >= peak - 6):
                s["label"] = "Build"
            else:
                s["label"] = "Breakdown"
            last_was_break = True
            continue
        if s["energy_db"] >= peak - 2.5:
            drop_n += 1
            s["label"] = "Drop" if drop_n == 1 else f"Drop {drop_n}"
        elif is_last and s["energy_db"] < peak - 4:
            s["label"] = "Outro"
        else:
            s["label"] = "Groove" if not last_was_break else "Return"
        last_was_break = False


def element_map(bars: list[dict]) -> dict:
    kick = _kick_present(bars)
    hats = _hats_present(bars)
    rms = np.array([r["rms_db"] for r in bars])
    return {
        "kick": [bool(v) for v in kick],
        "hats": [bool(v) for v in hats],
        "energy": [round(float(v), 1) for v in rms],
        "density": [int(r["onsets"]) for r in bars],
    }


def proportions(sections: list[dict]) -> list[dict]:
    total = sum(s["end"] - s["start"] for s in sections)
    return [{"label": s["label"], "bars": s["end"] - s["start"], "share": round((s["end"] - s["start"]) / total, 3)} for s in sections]
