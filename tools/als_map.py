"""Read the arrangement of a Live Set (.als) offline: which track plays on which bar.

A professional template or a finished project is an answer key: every clip sits on a known bar on a
named track. This turns one .als into a bar-by-bar layer map plus the numbers Alma's arrangement
rules should be measured against (first kick bar, breakdown lengths, layers in the drop vs the break).

    python tools/als_map.py "Set.als"            # one set, human table
    python tools/als_map.py --json "Set.als"     # one set, JSON
"""
from __future__ import annotations
import gzip
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROLE_WORDS = [
    ("kick", ("kick", "bd", "bassdrum")),
    ("bass", ("bass", "sub", "808", "rumble")),
    ("hats", ("hat", "hh", "hi-hat", "hihat", "ride", "cymbal")),
    ("clap", ("clap", "snare", "snr", "rim")),
    ("perc", ("perc", "shaker", "tom", "conga", "bongo", "tamb", "drum loop", "top loop", "tops", "loop", "cowbell", "click")),
    ("fx", ("fx", "riser", "uplifter", "downlifter", "impact", "sweep", "noise", "crash", "reverse", "transition", "fill", "white", "build")),
    ("vocal", ("vox", "vocal", "voice", "choir")),
    ("pad", ("pad", "atmos", "ambien", "texture", "drone", "string", "air")),
    ("synth", ("lead", "synth", "arp", "pluck", "stab", "chord", "key", "piano", "organ", "seq", "melody", "mel", "bell", "acid", "saw", "pulse", "theme", "hook", "wobble", "poly", "mono", "hoover", "layer")),
]
ROLES = [r for r, _ in ROLE_WORDS] + ["other"]


def role_of(name: str) -> str:
    """The role whose keyword appears EARLIEST in the name wins: "Bass (fast Kick)" is bass, "Top Kick" is kick."""
    n = name.lower()
    best, best_pos = "other", 10**6
    for role, words in ROLE_WORDS:
        for w in words:
            m = re.search(r"(^|[^a-z])" + re.escape(w) + r"([^a-z]|$)", n)
            pos = m.start(0) + (0 if m.start(0) == 0 else 1) if m else (n.find(w) if len(w) >= 4 and w in n else -1)
            if pos >= 0 and pos < best_pos:
                best, best_pos = role, pos
    return best


CUE_WORDS = [("intro", ("intro", "start")), ("build", ("build", "rise", "riser", "tension")), ("break", ("break", "bridge", "pause", "down")),
             ("drop", ("drop", "main", "peak", "climax", "all in", "chorus", "groove")), ("outro", ("outro", "end", "tail"))]


def cue_kind(name: str) -> str | None:
    n = name.lower()
    for kind, words in CUE_WORDS:
        if any(w in n for w in words):
            return kind
    return None


def cue_sections(s: dict) -> list[dict]:
    """Named sections from the set's own locators, in bar units; empty when the author left no usable cues."""
    cues = [(l["bar"], cue_kind(l["name"]), l["name"]) for l in s["locators"]]
    cues = [c for c in cues if c[1]]
    out = []
    for i, (bar, kind, name) in enumerate(cues):
        end = cues[i + 1][0] if i + 1 < len(cues) else s["bars"] + 1
        if end - bar >= 1:
            out.append({"kind": kind, "name": name, "start": int(round(bar)), "bars": int(round(end - bar))})
    return out


def _val(el, tag: str, default=None):
    c = el.find(tag)
    return c.get("Value") if c is not None else default


def read_set(path: str | Path) -> dict:
    raw = gzip.open(path, "rb").read()
    root = ET.fromstring(raw)
    live = root.find("LiveSet")
    bpm = 120.0
    for ev in live.iter("FloatEvent"):
        pass
    tempo = live.find(".//MasterTrack//Tempo")
    if tempo is None:
        tempo = live.find(".//MainTrack//Tempo")
    if tempo is not None:
        man = tempo.find("Manual")
        if man is not None:
            bpm = float(man.get("Value", bpm))
        else:
            ev = tempo.find(".//FloatEvent")
            if ev is not None:
                bpm = float(ev.get("Value", bpm))
    sig_num, sig_den = 4, 4
    sig = live.find(".//MasterTrack//TimeSignature//Numerator")
    if sig is None:
        sig = live.find(".//MainTrack//TimeSignature//Numerator")
    if sig is not None and sig.find("Manual") is not None:
        sig_num = int(sig.find("Manual").get("Value", 4))
    beats_per_bar = sig_num * 4 / sig_den

    tracks = []
    tr_root = live.find("Tracks")
    for tr in list(tr_root) if tr_root is not None else []:
        kind = tr.tag
        if kind not in ("AudioTrack", "MidiTrack"):
            continue
        name_el = tr.find("Name")
        name = (_val(name_el, "EffectiveName") or _val(name_el, "UserName") or kind) if name_el is not None else kind
        spans = []
        for ev in tr.findall("./DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events/*"):
            if not ev.tag.endswith("Clip"):
                continue
            s = float(ev.get("Time", _val(ev, "CurrentStart", 0)))
            e_end = _val(ev, "CurrentEnd")
            e = float(e_end) if e_end is not None else s
            if ev.find("CurrentStart") is not None:
                s = float(_val(ev, "CurrentStart"))
            if e > s:
                spans.append((s / beats_per_bar + 1.0, e / beats_per_bar + 1.0))  # bars, 1-based, half-open
        spans.sort()
        tracks.append({"name": name, "kind": kind, "role": role_of(name), "spans": spans, "muted": _val(tr.find("DeviceChain/Mixer/Speaker"), "Manual") == "false"})
    locators = []
    for loc in live.iter("Locator"):
        t = _val(loc, "Time")
        if t is None:
            continue
        locators.append({"bar": round(float(t) / beats_per_bar + 1.0, 2), "name": _val(loc, "Name", "")})
    locators.sort(key=lambda l: l["bar"])
    last = max([e for t in tracks for _, e in t["spans"]], default=1.0)
    total = int(round(last - 1.0))
    return {"path": str(path), "bpm": bpm, "beats_per_bar": beats_per_bar, "bars": total, "tracks": tracks, "locators": locators}


# ---------------------------------------------------------------- measurement

def layer_grid(s: dict) -> dict[str, list[int]]:
    """role -> per-bar count of tracks of that role playing (index 0 = bar 1)."""
    n = s["bars"]
    grid = {r: [0] * n for r in ROLES}
    for t in s["tracks"]:
        if t["muted"]:
            continue
        row = grid[t["role"]]
        for a, b in t["spans"]:
            for bar in range(int(a) - 1, min(n, int(round(b)) - 1)):
                if 0 <= bar < n:
                    row[bar] += 1
    return grid


def density(s: dict) -> list[int]:
    """distinct unmuted tracks playing per bar."""
    n = s["bars"]
    d = [0] * n
    for t in s["tracks"]:
        if t["muted"]:
            continue
        on = [False] * n
        for a, b in t["spans"]:
            for bar in range(int(a) - 1, min(n, int(round(b)) - 1)):
                if 0 <= bar < n:
                    on[bar] = True
        for i, v in enumerate(on):
            d[i] += v
    return d


def runs(flags: list[bool]) -> list[tuple[int, int]]:
    """(start_bar, length) of every run of True, 1-based bars."""
    out, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start + 1, i - start)); start = None
    return out


def measure(s: dict) -> dict:
    g = layer_grid(s)
    d = density(s)
    n = s["bars"]
    kick = [v > 0 for v in g["kick"]]
    kick_on = runs(kick)
    kick_off = runs([not k for k in kick])
    first_kick = kick_on[0][0] if kick_on else None
    # breaks = kick-off runs of >= 4 bars that start after the first kick and end before the end
    breaks = [(b, ln) for b, ln in kick_off if first_kick and b > first_kick and b + ln - 1 < n and ln >= 4]
    drops = [(b, ln) for b, ln in kick_on if ln >= 8]
    entries = {}
    for r in ROLES:
        rr = runs([v > 0 for v in g[r]])
        if rr:
            entries[r] = rr[0][0]
    dens_kick_on = [d[i] for i in range(n) if kick[i]]
    dens_kick_off = [d[i] for i in range(n) if not kick[i] and i + 1 > (first_kick or 0)]
    silent = sum(1 for v in d if v == 0)
    silent_inside = sum(1 for i, v in enumerate(d) if v == 0 and (first_kick or 0) < i + 1 < n)
    peak = max(d) if d else 0
    secs = cue_sections(s)
    for sec in secs:
        a, b = sec["start"] - 1, min(n, sec["start"] - 1 + sec["bars"])
        vals = d[a:b] or [0]
        sec["layers"] = round(sum(vals) / len(vals), 1)
        sec["kick"] = round(sum(1 for i in range(a, b) if kick[i]) / max(1, b - a), 2)
    return {
        "sections": secs,
        "bars": n, "bpm": s["bpm"], "tracks": sum(1 for t in s["tracks"] if not t["muted"]),
        "first_kick_bar": first_kick,
        "entry_order": sorted(entries, key=entries.get), "entries": entries,
        "drops": drops, "breaks": breaks,
        "break_lengths": [ln for _, ln in breaks],
        "peak_layers": peak,
        "layers_kick_on": round(sum(dens_kick_on) / len(dens_kick_on), 1) if dens_kick_on else 0,
        "layers_kick_off": round(sum(dens_kick_off) / len(dens_kick_off), 1) if dens_kick_off else 0,
        "silent_bars": silent, "silent_bars_inside": silent_inside,
        "locators": s["locators"],
        "density": d,
        "grid": {r: g[r] for r in ROLES},
    }


def bar_chart(vals: list[int], width: int = 96) -> str:
    if not vals:
        return ""
    step = max(1, len(vals) / width)
    cells = []
    i = 0.0
    blocks = " ▁▂▃▄▅▆▇█"
    hi = max(vals) or 1
    while i < len(vals):
        chunk = vals[int(i):int(i + step)] or [0]
        cells.append(blocks[min(8, round(8 * (sum(chunk) / len(chunk)) / hi))])
        i += step
    return "".join(cells)


def report(s: dict, m: dict) -> str:
    out = [f"{Path(s['path']).name}", f"  {m['bpm']:.0f} BPM · {m['bars']} bars · {m['tracks']} tracks playing · peak {m['peak_layers']} layers"]
    out.append(f"  first kick bar {m['first_kick_bar']} · drops {m['drops']} · breaks {m['breaks']}")
    out.append(f"  layers with kick {m['layers_kick_on']} · without kick {m['layers_kick_off']} · silent bars inside {m['silent_bars_inside']}")
    out.append("  entry order: " + " → ".join(f"{r}@{m['entries'][r]}" for r in m["entry_order"]))
    if m["sections"]:
        out.append("  sections: " + "  ".join(f"{x['kind']}@{x['start']}×{x['bars']} L{x['layers']} k{x['kick']:.0%}" for x in m["sections"]))
    elif m["locators"]:
        out.append("  cues (unclassified): " + ", ".join(f"{l['name'] or '·'}@{l['bar']:.0f}" for l in m["locators"]))
    out.append("  density  " + bar_chart(m["density"]))
    out.append("  kick     " + bar_chart(m["grid"]["kick"]))
    out.append("  bass     " + bar_chart(m["grid"]["bass"]))
    out.append("  synth    " + bar_chart(m["grid"]["synth"]))
    return "\n".join(out)


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print(__doc__); return 2
    for p in paths:
        s = read_set(p)
        m = measure(s)
        if as_json:
            m2 = dict(m); m2["tracks_detail"] = [{"name": t["name"], "role": t["role"], "spans": t["spans"]} for t in s["tracks"]]
            print(json.dumps(m2, ensure_ascii=False))
        else:
            print(report(s, m)); print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
