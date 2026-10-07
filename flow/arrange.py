"""Arrangement planning: the reference's structure (scaled to a target length) + the user's kit -> a track plan.

A plan is DAW-agnostic: tracks with spans in bars, one-shot hits in bars, MIDI note patterns, locators.
"""
from __future__ import annotations
import math
from . import patterns

STYLE_TEMPLATES = {
    # which layers live in which section label. Measured kick/hats presence from the reference overrides kick/hats.
    "house": {
        "Intro":     ["atmos", "pad", "kick", "tom", "tom_b", "shaker_loop", "perc"],
        "Groove":    ["atmos", "pad", "kick", "tom", "tom_b", "tom_c", "shaker_loop", "perc", "bass", "synth", "perc_loop", "chat"],
        "Drop":      ["atmos", "pad", "kick", "tom", "tom_b", "tom_c", "shaker_loop", "perc", "bass", "synth", "perc_loop", "chat", "clap", "hat_loop"],
        "Breakdown": ["atmos", "pad", "synth"],
        "Build":     ["atmos", "pad", "synth", "tom", "tom_b", "snare_roll"],
        "Return":    ["atmos", "pad", "kick", "tom", "tom_b", "shaker_loop", "perc", "bass", "synth", "perc_loop"],
        "Drop 2":    ["atmos", "pad", "kick", "tom", "tom_b", "tom_c", "shaker_loop", "perc", "bass", "synth", "perc_loop", "chat", "clap", "hat_loop", "ohat", "perc_loop2"],
        "Outro":     ["atmos", "kick", "shaker_loop", "bass", "perc"],
    },
}
STYLE_TEMPLATES["techno"] = {
    "Intro":     ["atmos", "kick", "chat", "shaker_loop"],
    "Groove":    ["atmos", "kick", "chat", "shaker_loop", "bass", "perc_loop", "perc"],
    "Drop":      ["atmos", "kick", "chat", "ohat", "shaker_loop", "bass", "perc_loop", "perc", "clap", "synth"],
    "Breakdown": ["atmos", "pad", "synth", "chat"],
    "Build":     ["atmos", "pad", "synth", "chat", "snare_roll"],
    "Return":    ["atmos", "kick", "chat", "shaker_loop", "bass", "perc_loop"],
    "Drop 2":    ["atmos", "kick", "chat", "ohat", "shaker_loop", "bass", "perc_loop", "perc_loop2", "perc", "clap", "synth", "hat_loop"],
    "Outro":     ["atmos", "kick", "chat", "bass"],
}
STYLE_TEMPLATES["afro"] = STYLE_TEMPLATES["house"]

LOOP_ROLES = {"shaker_loop", "hat_loop", "perc_loop", "perc_loop2", "pad", "atmos"}
ONESHOT_ROLES = {"kick", "clap", "ohat", "chat", "tom", "tom_b", "tom_c", "perc", "bass", "synth", "snare_roll"}
MELODIC = {"bass", "synth"}


def target_bars(length_seconds: float | None, bpm: float, ref_bars: int) -> int:
    if not length_seconds:
        return ref_bars
    bars = length_seconds * bpm / 240.0
    return max(16, int(round(bars / 8.0)) * 8)


CAPS = {"Build": 16, "Breakdown": 32}  # tension sections do not grow with the track; drops, intros and outros do


def _phrase(bars: float) -> int:
    unit = 8 if bars >= 16 else 4
    return max(4, int(round(bars / unit)) * unit)


def scale_sections(sections: list[dict], total: int) -> list[dict]:
    """Scale section lengths to `total` bars: proportional, snapped to phrases, builds/breakdowns capped."""
    ref_total = sum(s["end"] - s["start"] for s in sections)
    out = []
    for s in sections:
        ideal = (s["end"] - s["start"]) / ref_total * total
        bars = _phrase(min(ideal, CAPS.get(s["label"], 10 ** 6)))
        out.append({"label": s["label"], "bars": bars, "kick_ratio": s.get("kick_ratio", 1.0)})
    diff = total - sum(s["bars"] for s in out)
    growable = [i for i, s in enumerate(out) if s["label"] not in CAPS] or list(range(len(out)))
    order = sorted(growable, key=lambda i: -out[i]["bars"])
    i = 0
    while diff != 0 and order:
        j = order[i % len(order)]
        step = 4 if diff > 0 else -4
        if out[j]["bars"] + step >= 4:
            out[j]["bars"] += step
            diff -= step
        i += 1
        if i > 1000:
            break
    start = 1
    for s in out:
        s["start"] = start
        s["end"] = start + s["bars"]
        start = s["end"]
    return out


def build_plan(ref: dict, kit: dict, loops: dict, bpm: float | None = None, length_seconds: float | None = None,
               style: str = "house", midi_roles: dict | None = None, sidechain: str | None = None) -> dict:
    """Return the plan. midi_roles: {'bass': {'name': 'Serum', 'uri': ...}, ...} makes those roles MIDI tracks."""
    bpm = bpm or ref["bpm"]
    midi_roles = midi_roles or {}
    tmpl = STYLE_TEMPLATES.get(style, STYLE_TEMPLATES["house"])
    total = target_bars(length_seconds, bpm, ref["bars"])
    sections = scale_sections(ref["sections"], total)
    tonic = ref["key"]["pc"]

    def source(role):
        if role in loops:
            return {"path": loops[role]["path"], "bars": loops[role]["bars"], "kind": "loop", "name": loops[role]["source"]}
        s = kit.get(role)
        if not s:
            return None
        bars = max(1, int(round(s["duration"] / (240.0 / bpm)))) if s.get("is_loop") else None
        return {"path": s["path"], "bars": bars, "kind": "loop" if s.get("is_loop") else "oneshot", "name": s["name"]}

    # which roles exist at all
    roles = []
    for sec_roles in tmpl.values():
        for r in sec_roles:
            if r not in roles and (r in loops or r in kit):
                roles.append(r)

    tracks = []
    for role in roles:
        src = source(role)
        if not src:
            continue
        spans = []
        for s in sections:
            label = s["label"] if s["label"] in tmpl else ("Drop 2" if s["label"].startswith("Drop") else "Groove")
            wanted = role in tmpl[label]
            if role == "kick" and s["kick_ratio"] < 0.35:
                wanted = False
            if role == "kick" and s["label"] in ("Intro",) and s["kick_ratio"] >= 0.35:
                wanted = True
            if not wanted:
                continue
            start, end = s["start"], s["end"]
            # reference habit: the kick (and bass) drop out for the last bar before a breakdown/build
            nxt = sections[sections.index(s) + 1] if sections.index(s) + 1 < len(sections) else None
            if role in ("kick",) and nxt and nxt["label"] in ("Breakdown", "Build") and end - start > 4:
                end -= 1
            if spans and spans[-1][1] == start:
                spans[-1] = (spans[-1][0], end)
            else:
                spans.append((start, end))
        if not spans:
            continue
        t = {"name": _track_name(role, src["name"]), "role": role, "spans": spans, "source": src}
        if role in midi_roles:
            t["kind"] = "midi"
            t["plugin"] = midi_roles[role]
            t["notes"] = patterns.midi_notes(role, tonic, 4)
            t["clip_bars"] = 4
        else:
            t["kind"] = "audio"
            t["clip_bars"] = src["bars"] or 4
        tracks.append(t)

    # FX one-shots at section edges
    fx_tracks = []
    drops = [s for s in sections if s["label"].startswith("Drop") or s["label"] == "Return"]
    breaks = [s for s in sections if s["label"] in ("Breakdown",)]
    def stem(name):
        return name.rsplit(".", 1)[0]

    if kit.get("impact"):
        hits = sorted({round(s["start"] - 0.125, 3) for s in drops + breaks if s["start"] > 1} | {sections[-1]["end"] - 0.125})
        fx_tracks.append({"name": f"Impact · {stem(kit['impact']['name'])}", "role": "impact", "kind": "audio", "hits": hits, "source": source("impact")})
    if kit.get("uplifter"):
        up_bars = max(2, int(round(kit["uplifter"]["duration"] / (240.0 / bpm))))
        hits = sorted({max(1, s["start"] - up_bars) for s in drops if s["start"] > 1})
        fx_tracks.append({"name": f"Uplifter · {stem(kit['uplifter']['name'])}", "role": "uplifter", "kind": "audio", "hits": hits, "source": source("uplifter")})
    if kit.get("downlifter"):
        hits = sorted({s["start"] for s in drops if s["start"] > 1})
        fx_tracks.append({"name": f"Downlifter · {stem(kit['downlifter']['name'])}", "role": "downlifter", "kind": "audio", "hits": hits, "source": source("downlifter")})

    locators = [(s["label"], s["start"]) for s in sections] + [("End", sections[-1]["end"])]
    return {
        "bpm": bpm, "bars": total, "key": ref["key"], "style": style, "sections": sections,
        "tracks": tracks + fx_tracks, "locators": locators, "sidechain": sidechain,
        "reference": {"file": ref["file"], "bars": ref["bars"], "bpm": ref["bpm"]},
        "placeholders": [t["name"] for t in tracks if t["role"] in MELODIC],
    }


def _track_name(role: str, src_name: str) -> str:
    pretty = {"kick": "Kick", "clap": "Clap", "ohat": "Open Hat", "chat": "Closed Hat", "tom": "Tom", "tom_b": "Tom B", "tom_c": "Tom C",
              "perc": "Perc", "shaker_loop": "Shaker Loop", "hat_loop": "Hat Loop", "perc_loop": "Perc Loop", "perc_loop2": "Perc Loop 2",
              "bass": "Bass", "synth": "Synth", "pad": "Pad", "atmos": "Atmosphere", "snare_roll": "Build Roll"}
    base = src_name.rsplit(".", 1)[0]
    return f"{pretty.get(role, role.title())} · {base}"


def seconds(bars: float, bpm: float) -> float:
    return bars * 240.0 / bpm


def describe(plan: dict) -> list[str]:
    """Human-readable build steps (what enters where), for the report and the UI."""
    lines = []
    for s in plan["sections"]:
        here = [t["name"].split(" · ")[0] for t in plan["tracks"] if any(a <= s["start"] < b for a, b in t.get("spans", []))]
        lines.append(f"{s['label']} · bars {s['start']}–{s['end'] - 1} ({s['bars']} bars): " + (", ".join(here) if here else "FX only"))
    return lines
