"""Measure a folder of finished tracks the way Alma measures a reference, and print what they do.

    python tools/corpus_audio.py "<folder>" --out corpus.jsonl [--limit N] [--summary]

Runs flow.analysis.analyze_reference on every mp3/wav/aif (recursively, skipping folders named in SKIP_DIRS),
appends one JSON line per track to --out as it goes (resumable: tracks already in the file are skipped), and with
--summary prints medians: track length, first kick bar, intro bars, breaks (count, length, kick share), drop bars,
energy delta break vs drop, hats entry relative to the kick, silent bars.
"""
from __future__ import annotations
import json
import os
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flow import analysis  # noqa: E402

EXT = {".mp3", ".wav", ".aif", ".aiff", ".flac", ".m4a"}
SKIP_DIRS = ("techno house", "שירים עם מילים")


def runs(flags):
    out, start = [], None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start + 1, i - start)); start = None
    return out


def measure(ref: dict) -> dict:
    secs = ref["sections"]
    el = ref["elements"]
    kick, hats, energy = el["kick"], el["hats"], el["energy"]
    n = ref["bars"]
    kick_on = runs(kick)
    first_kick = kick_on[0][0] if kick_on else None
    hats_on = runs(hats)
    first_hats = hats_on[0][0] if hats_on else None
    kick_off = runs([not k for k in kick])
    breaks = [(b, ln) for b, ln in kick_off if first_kick and b > first_kick and b + ln - 1 < n and ln >= 4]
    peak = max(energy) if energy else 0
    silent = sum(1 for i, e in enumerate(energy) if e < peak - 20 and (first_kick or 0) < i + 1 < n)
    drops = [s for s in secs if s["label"].startswith("Drop")]
    brks = [s for s in secs if s["label"] == "Breakdown"]
    builds = [s for s in secs if s["label"] == "Build"]
    intro = secs[0]["bars"] if secs else None
    outro = secs[-1]["bars"] if secs and secs[-1]["label"] == "Outro" else None
    drop_e = st.mean([s["energy_db"] for s in drops]) if drops else None
    brk_e = st.mean([s["energy_db"] for s in brks]) if brks else None
    return {
        "file": ref["file"], "bpm": ref["bpm"], "tempo_source": ref["tempo_info"].get("source"), "bars": n, "minutes": round(ref["duration"] / 60, 1),
        "first_kick_bar": first_kick, "hats_after_kick": (first_hats - first_kick) if (first_hats and first_kick) else None,
        "intro_bars": intro, "outro_bars": outro,
        "breaks": len(brks), "break_bars": [s["bars"] for s in brks], "break_kick": [s["kick_ratio"] for s in brks],
        "kick_gaps": breaks, "builds": [s["bars"] for s in builds], "drops": [s["bars"] for s in drops],
        "kick_share": round(sum(kick) / max(1, n), 2),
        "break_minus_drop_db": round(brk_e - drop_e, 1) if (drop_e is not None and brk_e is not None) else None,
        "silent_bars": silent,
        "sections": [(s["label"], s["start"], s["bars"], s["kick_ratio"]) for s in secs],
    }


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 1) if xs else None


def summary(rows: list[dict]) -> str:
    good = [r for r in rows if r.get("bars", 0) >= 64]
    out = [f"{len(good)} tracks (of {len(rows)}; {len(rows) - len(good)} shorter than 64 bars skipped)"]
    out.append(f"length {med([r['minutes'] for r in good])} min · {med([r['bars'] for r in good])} bars · bpm {med([r['bpm'] for r in good])}")
    out.append(f"first kick bar {med([r['first_kick_bar'] for r in good])} · intro {med([r['intro_bars'] for r in good])} bars · hats after kick {med([r['hats_after_kick'] for r in good])} bars")
    out.append(f"breaks per track {med([r['breaks'] for r in good])} · break {med([b for r in good for b in r['break_bars']])} bars · kick share inside breaks {med([k for r in good for k in r['break_kick']])}")
    out.append(f"kick gaps ≥4 bars per track {med([len(r['kick_gaps']) for r in good])} · gap length {med([ln for r in good for _, ln in r['kick_gaps']])} bars")
    out.append(f"drop {med([b for r in good for b in r['drops']])} bars · build {med([b for r in good for b in r['builds']])} bars · outro {med([r['outro_bars'] for r in good])} bars")
    out.append(f"kick share of the whole track {med([r['kick_share'] for r in good])} · break vs drop {med([r['break_minus_drop_db'] for r in good])} dB · silent bars {med([r['silent_bars'] for r in good])}")
    no_break = sum(1 for r in good if r["breaks"] == 0)
    out.append(f"tracks with no kick-less break at all: {no_break} / {len(good)}")
    return "\n".join(out)


def main(argv):
    folder = Path(argv[0])
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else folder / "corpus.jsonl"
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 10 ** 6
    done = {}
    if out.exists():
        for line in out.read_text().splitlines():
            try:
                r = json.loads(line); done[r["file"]] = r
            except Exception:  # noqa: BLE001
                pass
    if "--summary" in argv and "--only" in argv:
        print(summary(list(done.values()))); return 0
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in EXT and not p.name.startswith(".") and not any(k in str(p) for k in SKIP_DIRS))
    todo = [p for p in files if p.name not in done][:limit]
    print(f"{len(files)} tracks, {len(done)} measured, {len(todo)} to go", flush=True)
    with out.open("a") as fh:
        for i, p in enumerate(todo):
            t0 = time.time()
            try:
                ref = analysis.analyze_reference(str(p))
                r = measure(ref)
            except Exception as e:  # noqa: BLE001
                r = {"file": p.name, "error": str(e)[:200], "bars": 0}
            fh.write(json.dumps(r, ensure_ascii=False) + "\n"); fh.flush()
            done[p.name] = r
            print(f"[{i + 1}/{len(todo)}] {p.name[:60]:60} {r.get('bars', 0):4} bars  kick@{r.get('first_kick_bar')}  breaks {r.get('break_bars')}  {time.time() - t0:.0f}s", flush=True)
    if "--summary" in argv:
        print(); print(summary(list(done.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
