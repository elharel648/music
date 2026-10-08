"""Universal output for any DAW: full-length stems + a Standard MIDI File with markers + a report.

Logic, FL Studio, Cubase, Studio One, Bitwig, Reaper: drag the stems in (they all start at bar 1 at the
project tempo), import the MIDI file for markers and the bass/synth patterns.
"""
from __future__ import annotations
import json
import os
import struct
import numpy as np
from . import audio, arrange, patterns as patmod

GM = {"kick": 36, "clap": 39, "snare_roll": 38, "chat": 42, "ohat": 46, "tom": 45, "tom_b": 47, "tom_c": 43, "perc": 63, "shaker_loop": 70}


def _load_stereo(path: str, sr: int, cache: dict) -> np.ndarray:
    if path not in cache:
        y, _ = audio.load(path, sr=sr)
        cache[path] = np.vstack([y, y]) if y.shape[0] == 1 else y
    return cache[path]


def _place_track(buf: np.ndarray, t: dict, bar_len: float, sr: int, cache: dict, gain: float = 1.0) -> None:
    """Add one track's clips (spans, hits, sweeps, placements) into buf at bar positions."""
    n = buf.shape[1]
    y = _load_stereo(t["source"]["path"], sr, cache)
    clip_bars = t.get("clip_bars") or max(1, int(round(y.shape[1] / sr / bar_len)))
    for s, e in t.get("spans", []):
        b = s
        while b < e:
            i0 = int((b - 1) * bar_len * sr)
            take = min(y.shape[1], int(min(clip_bars, e - b) * bar_len * sr) if t["source"]["kind"] != "oneshot" else y.shape[1])
            i1 = min(n, i0 + take)
            if i1 > i0:
                buf[:, i0:i1] += y[:, : i1 - i0] * gain
            b += clip_bars
    for hb in t.get("hits", []):
        i0 = int((hb - 1) * bar_len * sr)
        i1 = min(n, i0 + y.shape[1])
        if i1 > i0:
            buf[:, i0:i1] += y[:, : i1 - i0] * gain
    for sb, sp in t.get("sweeps", []):
        sw = _load_stereo(sp, sr, cache)
        i0 = int((sb - 1) * bar_len * sr)
        i1 = min(n, i0 + sw.shape[1])
        if i1 > i0:
            buf[:, i0:i1] += sw[:, : i1 - i0] * gain
    for pl in t.get("placements", []):
        yp = _load_stereo(pl["path"], sr, cache)
        i0 = int((pl["bar"] - 1) * bar_len * sr)
        i1 = min(n, i0 + yp.shape[1])
        if i1 > i0:
            buf[:, i0:i1] += yp[:, : i1 - i0] * gain


def render_stems(plan: dict, out_dir: str, sr: int = 48000, progress=None, tail_s: float = 8.0) -> list[str]:
    bpm = plan["bpm"]
    bar_len = 240.0 / bpm
    n = int((plan["bars"] * bar_len + tail_s) * sr)
    os.makedirs(out_dir, exist_ok=True)
    written = []
    cache: dict[str, np.ndarray] = {}
    tracks = plan["tracks"]
    for i, t in enumerate(tracks):
        buf = np.zeros((2, n), dtype=np.float32)
        _place_track(buf, t, bar_len, sr, cache)
        peak = float(np.abs(buf).max())
        if peak > 0.98:
            buf *= 0.98 / peak
        safe = "".join(c for c in t["name"] if c not in '/\\:*?"<>|')
        path = os.path.join(out_dir, f"{i + 1:02d} {safe}.wav")
        audio.write(path, buf, sr)
        written.append(path)
        if progress:
            progress(f"Stem {i + 1}/{len(tracks)}: {t['name']}", (i + 1) / len(tracks))
            progress(f"@track:{i}", (i + 1) / len(tracks))
    return written


def render_mix(plan: dict, path: str, sr: int = 44100, progress=None, tail_s: float = 4.0) -> dict:
    """A quick stereo mix of the whole arrangement to listen to before anything is written to a DAW.
    Balance follows the Finish gain staging; no effects. 16-bit so every browser engine plays it."""
    import soundfile as sf
    from . import finish as finishmod
    bpm = plan["bpm"]
    bar_len = 240.0 / bpm
    n = int((plan["bars"] * bar_len + tail_s) * sr)
    mix = np.zeros((2, n), dtype=np.float32)
    cache: dict[str, np.ndarray] = {}
    tracks = plan["tracks"]
    for i, t in enumerate(tracks):
        gain = 10 ** (finishmod.GAIN_DB.get(t["role"], -6) / 20.0)
        _place_track(mix, t, bar_len, sr, cache, gain=gain)
        if progress:
            progress(f"Mixing {t['name']}", (i + 1) / len(tracks))
            progress(f"@track:{i}", (i + 1) / len(tracks))
    peak = float(np.abs(mix).max())
    if peak > 0:
        mix *= 0.89 / peak
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    sf.write(path, mix.T, sr, subtype="PCM_16")
    return {"path": path, "seconds": round(n / sr, 3), "bars": int(plan["bars"]), "bpm": float(bpm)}


# ---- minimal Standard MIDI File writer (format 1)
def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def _track(events: list[tuple[int, bytes]]) -> bytes:
    events.sort(key=lambda e: e[0])
    data, last = b"", 0
    for tick, ev in events:
        data += _vlq(tick - last) + ev
        last = tick
    data += _vlq(0) + b"\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(data)) + data


def _ascii(name: str) -> bytes:
    return name.replace("·", "-").encode("ascii", "replace")


def write_midi(plan: dict, path: str, tpq: int = 480) -> str:
    bpm = plan["bpm"]
    bar = tpq * 4
    tracks = []
    meta = [(0, b"\xff\x51\x03" + struct.pack(">I", int(60_000_000 / bpm))[1:]), (0, b"\xff\x58\x04\x04\x02\x18\x08"),
            (0, b"\xff\x03" + _vlq(4) + b"Alma")]
    for name, b in plan["locators"]:
        nm = _ascii(name)
        meta.append(((b - 1) * bar, b"\xff\x06" + _vlq(len(nm)) + nm))
    tracks.append(_track(meta))
    # drums on channel 10 (0x99), melodic roles on their own channels
    drums = []
    ch = 0
    for t in plan["tracks"]:
        role = t["role"]
        if t.get("kind") == "midi" or role in ("bass", "synth"):
            nm = _ascii(t["name"])
            ev = [(0, b"\xff\x03" + _vlq(len(nm)) + nm)]
            notes = t.get("notes") or []
            clip_bars = t.get("clip_bars") or 4
            for s, e in t.get("spans", []):
                b = s
                while b < e:
                    base = (b - 1) * bar
                    for nt in notes:
                        on = base + int(nt["start_time"] * tpq)
                        off = on + int(nt["duration"] * tpq)
                        if (b - 1) * bar + int(nt["start_time"] * tpq) >= (e - 1) * bar:
                            continue
                        ev.append((on, bytes([0x90 | ch, nt["pitch"], nt["velocity"]])))
                        ev.append((off, bytes([0x80 | ch, nt["pitch"], 0])))
                    b += clip_bars
            tracks.append(_track(ev))
            ch = (ch + 1) % 9
        elif role in GM:
            p = patmod.pattern_for(role, plan.get("style"))
            beats = p.get("beats", [0])
            every = p.get("every", 1)
            for s, e in t.get("spans", []):
                for b in range(s, e):
                    if every > 1 and ((b - s) % every) != every - 1:
                        continue
                    for beat in beats:
                        on = (b - 1) * bar + int(beat * tpq)
                        drums.append((on, bytes([0x99, GM[role], 100])))
                        drums.append((on + tpq // 4, bytes([0x89, GM[role], 0])))
    if drums:
        drums.insert(0, (0, b"\xff\x03" + _vlq(5) + b"Drums"))
        tracks.append(_track(drums))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), tpq)
    with open(path, "wb") as f:
        f.write(header + b"".join(tracks))
    return path


def write_report(plan: dict, ref: dict, path: str) -> str:
    secs = plan["sections"]
    total = plan["bars"]
    strip = "".join(
        f'<div style="flex:0 0 {s["bars"] / total * 100:.2f}%;display:flex;flex-direction:column;gap:6px;min-width:0">'
        f'<div style="height:{44 + 90 * (1 if s["label"].startswith("Drop") else 0.4 if s["label"] in ("Breakdown", "Build") else 0.7):.0f}px;'
        f'border-radius:14px;background:{"#5C5BE0" if s["label"].startswith("Drop") else "#E4E3F8"}"></div>'
        f'<div style="font:600 11px Manrope,system-ui;letter-spacing:.12em;color:#6B6B75;text-align:center">{s["label"].upper()}</div>'
        f'<div style="font:500 11px ui-monospace,monospace;color:#8A8A93;text-align:center">{s["start"]}–{s["end"] - 1}</div></div>'
        for s in secs)
    rows = "".join(f"<tr><td>{t['name']}</td><td>{t.get('kind', 'audio')}</td><td>{', '.join(f'{a}–{b - 1}' for a, b in t.get('spans', [])) or ', '.join(str(h) for h in t.get('hits', []))}</td></tr>" for t in plan["tracks"])
    steps = "".join(f"<li>{line}</li>" for line in arrange.describe(plan))
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Alma blueprint · {ref['file']}</title>
<style>body{{margin:0;background:#F7F6F3;color:#17171C;font-family:Manrope,system-ui,sans-serif}} .wrap{{max-width:1100px;margin:0 auto;padding:40px 24px}}
h1{{font-size:28px;margin:0 0 6px}} .meta{{color:#6B6B75;margin-bottom:28px}} .card{{background:#fff;border:1px solid rgba(20,20,30,.06);border-radius:20px;padding:24px;margin-bottom:20px}}
table{{width:100%;border-collapse:collapse;font-size:13px}} td{{padding:8px 6px;border-top:1px solid rgba(20,20,30,.06)}} .eyebrow{{font-size:11px;letter-spacing:.18em;color:#6B6B75;font-weight:700;margin-bottom:12px}}
ol li{{margin:6px 0}}</style></head><body><div class="wrap">
<h1>Blueprint · {ref['file']}</h1><div class="meta">{plan['bpm']:.0f} BPM · {ref['key']['tonic']} {ref['key']['mode']} · {plan['bars']} bars · style: {plan['style']} · made with Alma</div>
<div class="card"><div class="eyebrow">STRUCTURE</div><div style="display:flex;gap:8px;align-items:flex-end">{strip}</div></div>
<div class="card"><div class="eyebrow">BUILD STEPS</div><ol>{steps}</ol></div>
<div class="card"><div class="eyebrow">TRACKS</div><table>{rows}</table></div>
<div class="meta">Placeholders to replace by ear: {', '.join(plan.get('placeholders', [])) or 'none'}. Reference structure measured from audio; patterns are genre defaults.</div>
</div></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def export_all(plan: dict, ref: dict, out_dir: str, progress=None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    stems = render_stems(plan, os.path.join(out_dir, "Stems"), progress=progress)
    midi = write_midi(plan, os.path.join(out_dir, "Alma markers and patterns.mid"))
    report = write_report(plan, ref, os.path.join(out_dir, "Blueprint.html"))
    with open(os.path.join(out_dir, "blueprint.json"), "w") as f:
        json.dump({"plan": {k: v for k, v in plan.items()}, "reference": {k: v for k, v in ref.items() if k != "bar_features"}}, f, indent=1, default=str)
    with open(os.path.join(out_dir, "README.txt"), "w") as f:
        f.write(
            f"Alma export · {ref['file']} · {plan['bpm']:.0f} BPM · {plan['bars']} bars\n\n"
            "HOW TO USE IN ANY DAW\n"
            f"1. Create a new project at {plan['bpm']:.0f} BPM.\n"
            "2. Drag every file from Stems/ onto new tracks, all starting at bar 1. They are already arranged.\n"
            "3. Import 'Alma markers and patterns.mid': it carries the section markers and MIDI patterns for bass/synth/drums.\n"
            "   Logic: File > Import > MIDI File.  FL Studio: drag onto the playlist.  Cubase/Studio One/Reaper: File > Import.\n"
            "4. Open Blueprint.html for the structure and the build steps.\n\n"
            "Ableton Live users: use Alma's 'Build in Ableton' target instead; it writes a real editable Set.\n")
    return {"stems": stems, "midi": midi, "report": report, "folder": out_dir}
