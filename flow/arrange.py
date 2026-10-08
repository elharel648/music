"""Arrangement planning: the reference's structure (scaled to a target length) + the user's kit -> a track plan.

A plan is DAW-agnostic: tracks with spans in bars, one-shot hits in bars, MIDI note patterns, locators.
"""
from __future__ import annotations
import math
import numpy as np
from . import patterns, profiles, styles as stylelib

STYLE_TEMPLATES = {k: st.template for k, st in stylelib.STYLES.items()}  # kept for the CLI and older callers

LOOP_ROLES = {"shaker_loop", "hat_loop", "perc_loop", "perc_loop2", "pad", "atmos"}
ONESHOT_ROLES = {"kick", "clap", "ohat", "chat", "tom", "tom_b", "tom_c", "perc", "bass", "synth", "snare_roll"}
MELODIC = {"bass", "synth"}


MIN_SECONDS = 120.0  # a Alma track is never shorter than two minutes
SHORT_REF_BARS = 48  # below this (or fewer than 3 sections) the reference is a clip, not a track: use a typical structure
TYPICAL_STRUCTURE = [("Intro", 16, 1.0), ("Groove", 24, 1.0), ("Drop", 32, 1.0), ("Breakdown", 16, 0.0), ("Build", 8, 0.0), ("Drop 2", 32, 1.0), ("Outro", 16, 1.0)]


def reference_usable(ref: dict) -> bool:
    return int(ref.get("bars") or 0) >= SHORT_REF_BARS and len(ref.get("sections") or []) >= 3


def reference_sections(ref: dict, structure: str = "reference") -> tuple[list[dict], str | None]:
    """The reference's own sections ('reference'), or a typical club structure ('typical').
    A reference too short to carry a structure falls back to 'typical' with a note."""
    secs = ref.get("sections") or []
    if structure == "reference" and reference_usable(ref):
        return secs, None
    if structure == "typical":
        start, out = 1, []
        for label, bars, kr in TYPICAL_STRUCTURE:
            out.append({"label": label, "start": start, "end": start + bars, "bars": bars, "kick_ratio": kr})
            start += bars
        return out, None
    start, out = 1, []
    for label, bars, kr in TYPICAL_STRUCTURE:
        out.append({"label": label, "start": start, "end": start + bars, "bars": bars, "kick_ratio": kr})
        start += bars
    return out, f"The reference is {ref.get('bars', 0)} bars with {len(secs)} section{'s' if len(secs) != 1 else ''}: a clip, not a track. Alma used a typical structure instead."


def target_bars(length_seconds: float | None, bpm: float, ref_bars: int) -> int:
    floor = int(round(MIN_SECONDS * bpm / 240.0 / 8.0)) * 8
    if not length_seconds:
        return max(ref_bars, floor)
    bars = length_seconds * bpm / 240.0
    return max(floor, int(round(bars / 8.0)) * 8)


CAPS = profiles.HOUSE.caps  # tension sections, intros and outros do not grow with the track; drops and grooves do


def _phrase(bars: float) -> int:
    unit = 8 if bars >= 16 else 4
    return max(4, int(round(bars / unit)) * unit)


def scale_sections(sections: list[dict], total: int, caps: dict[str, int] | None = None) -> list[dict]:
    caps = caps or CAPS
    """Scale section lengths to `total` bars: proportional, snapped to phrases, builds/breakdowns capped."""
    ref_total = sum(s["end"] - s["start"] for s in sections)
    out = []
    for s in sections:
        ideal = (s["end"] - s["start"]) / ref_total * total
        bars = _phrase(min(ideal, caps.get(s["label"], 10 ** 6)))
        out.append({"label": s["label"], "bars": bars, "kick_ratio": s.get("kick_ratio", 1.0)})
    diff = total - sum(s["bars"] for s in out)
    growable = [i for i, s in enumerate(out) if s["label"] not in caps] or list(range(len(out)))
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


MIN_SECTION = 8


def normalize_sections(secs: list[dict], profile: profiles.Profile = profiles.HOUSE) -> tuple[list[dict], list[str]]:
    """A structure a DJ would recognise, whatever the reference did: no slivers, an intro that does not drag,
    at least one breakdown + build before the biggest drop, an outro. Returns (sections, notes)."""
    out = [dict(x) for x in secs]
    notes: list[str] = []

    def relabel(x, label, kr):
        x["label"] = label
        x["kick_ratio"] = kr

    # slivers join their neighbour
    merged: list[dict] = []
    for x in out:
        if merged and (x["end"] - x["start"]) < MIN_SECTION:
            merged[-1]["end"] = x["end"]
        else:
            merged.append(x)
    out = merged
    # an intro longer than 24 bars is an intro and a groove
    over, keep = profile.intro_split
    if out and out[0]["label"] == "Intro" and (out[0]["end"] - out[0]["start"]) > over:
        a = out[0]
        cut = a["start"] + keep
        out = [dict(a, end=cut), dict(a, label="Groove", start=cut)] + out[1:]
    # a breakdown must exist before the last drop
    drops = [i for i, x in enumerate(out) if x["label"].startswith("Drop")]
    has_break = any(x["label"] in ("Breakdown", "Build") for x in out)
    if drops and not has_break:
        size = lambda x: x["end"] - x["start"]
        # best host: the section right before the last drop, else the longest section before any drop, else the longest drop itself
        cands = [i for i in range(drops[-1]) if size(out[i]) >= 24 and not out[i]["label"].startswith("Drop")]
        host = (drops[-1] - 1) if (drops[-1] > 0 and size(out[drops[-1] - 1]) >= 24 and not out[drops[-1] - 1]["label"].startswith("Drop")) else (max(cands, key=lambda i: size(out[i])) if cands else None)
        if host is not None:
            prev = out[host]
            b0 = prev["end"] - 16
            out[host] = dict(prev, end=b0)
            out[host + 1:host + 1] = [dict(prev, label="Breakdown", start=b0, end=b0 + 8, kick_ratio=0.0), dict(prev, label="Build", start=b0 + 8, end=b0 + 16, kick_ratio=0.0)]
            notes.append("The reference never drops the kick; Alma opened a breakdown and a build before the drop.")
        else:
            big = max(drops, key=lambda i: size(out[i]))
            d = out[big]
            if size(d) >= 32:
                mid = d["start"] + ((size(d) // 2) // 8) * 8
                out[big:big + 1] = [dict(d, end=mid), dict(d, label="Breakdown", start=mid, end=mid + 8, kick_ratio=0.0), dict(d, label="Build", start=mid + 8, end=mid + 16, kick_ratio=0.0), dict(d, label="Drop 2" if d["label"] == "Drop" else d["label"], start=mid + 16)]
                notes.append("The reference never drops the kick; Alma split the drop around a breakdown and a build.")
    # the end is an outro
    if out and out[-1]["label"].startswith("Drop") and (out[-1]["end"] - out[-1]["start"]) >= 24:
        d = out[-1]
        cut = d["end"] - 8
        out[-1] = dict(d, end=cut)
        out.append(dict(d, label="Outro", start=cut))
    for x in out:
        x["bars"] = x["end"] - x["start"]
    return out, notes


ENTRY_ORDER = ["atmos", "pad", "kick", "chat", "shaker_loop", "perc", "tom", "bass", "hat_loop", "perc_loop", "synth", "clap", "tom_b", "tom_c", "ohat", "perc_loop2", "snare_roll"]
LATE_IN_DROP = {"ohat", "perc_loop2", "hat_loop", "tom_c"}
BREATHERS = {"kick", "bass"}
RESTERS = ["hat_loop", "perc_loop", "shaker_loop", "perc_loop2", "ohat", "chat"]
DRUMS = {"kick", "clap", "chat", "ohat", "tom", "tom_b", "tom_c", "perc", "hat_loop", "perc_loop", "perc_loop2", "shaker_loop", "bass"}


def shape_layers(wanted: dict[str, list[dict]], sections: list[dict], total: int, profile: profiles.Profile = profiles.HOUSE) -> dict[str, list[tuple[int, int]]]:
    """From 'which sections each role belongs to' to spans that breathe: staggered entries every phrase,
    the kick and bass resting on the last bar of each 16-bar phrase, drums silent on the bar before a drop,
    percussion loops taking turns to rest, outros thinning out."""
    active = {r: np.zeros(total + 2, dtype=bool) for r in wanted}
    for r, secs in wanted.items():
        for sct in secs:
            active[r][sct["start"]:sct["end"]] = True
    rank = {r: i for i, r in enumerate(ENTRY_ORDER)}
    p = profile
    prev_roles: set[str] = set()
    for si, sct in enumerate(sections):
        here = {r for r, secs in wanted.items() if sct in secs}
        new = sorted(here - prev_roles, key=lambda r: rank.get(r, 99))
        bars = sct["end"] - sct["start"]
        label = sct["label"]
        is_drop = label.startswith("Drop") or label == "Return"
        if is_drop:
            for r in new:
                if r in LATE_IN_DROP and bars >= 24:
                    active[r][sct["start"]:sct["start"] + 8] = False
        elif label == "Outro":
            leaving = sorted(here, key=lambda r: -rank.get(r, 99))
            for i, r in enumerate(leaving[:-2]):
                cut = sct["end"] - (i + 1) * 4
                if cut > sct["start"] + 4:
                    active[r][cut:sct["end"]] = False
        elif label == "Breakdown":
            if p.break_kick == "half" and "kick" in here and bars >= 8:
                active["kick"][sct["start"]:sct["start"] + bars // 2] = False
        elif label != "Build":
            phrase = p.entry_phrase if bars >= 2 * p.entry_phrase else max(4, (bars // 8) * 2)
            kick_delay = int(round(bars * p.intro_kick_frac / 4)) * 4 if (label == "Intro" and bars >= 16) else 0
            for r in new:
                g = p.group_of(r)
                delay = g * phrase
                if label == "Intro" and r == "kick":
                    delay = max(delay, kick_delay)
                elif label == "Intro" and g == 0 and r not in ("atmos", "pad"):
                    delay = kick_delay                   # bass and percussion arrive with the kick, never before it
                elif label == "Intro" and g >= 1:
                    delay = kick_delay + g * phrase      # after the kick, the next layers wait a phrase (corpus: hats/claps/synths at kick +16)
                if delay and delay < bars:
                    active[r][sct["start"]:sct["start"] + delay] = False
                elif delay >= bars:
                    active[r][sct["start"]:sct["end"]] = False
        # phrase breaths inside grooves and drops
        if is_drop or label in ("Groove",):
            for k in range(1, bars // 16 + 1):
                b = sct["start"] + 16 * k - 1
                if b < sct["end"] - 1:
                    for r in BREATHERS:
                        if r in active:
                            active[r][b] = False
            for ri, r in enumerate(RESTERS):
                if r not in active:
                    continue
                for k in range(1, bars // 8 + 1):
                    b = sct["start"] + 8 * k - 1
                    if (k + ri) % 2 == 0 and sct["start"] + 8 <= b < sct["end"] - 1:
                        active[r][b] = False
        # the bar before a drop is silent for kick and bass; the impact lands on the drop
        nxt = sections[si + 1] if si + 1 < len(sections) else None
        if p.silent_before_drop and nxt and (nxt["label"].startswith("Drop") or nxt["label"] in ("Breakdown", "Build")) and label not in ("Build",) and bars > 4:
            for r in BREATHERS:
                if r in active:
                    active[r][nxt["start"] - 1] = False
        prev_roles = here
    spans: dict[str, list[tuple[int, int]]] = {}
    for r, a in active.items():
        out: list[tuple[int, int]] = []
        b = 1
        while b <= total:
            if a[b]:
                e = b
                while e <= total and a[e]:
                    e += 1
                out.append((b, e))
                b = e
            else:
                b += 1
        spans[r] = out
    return spans


def build_plan(ref: dict, kit: dict, loops: dict, bpm: float | None = None, length_seconds: float | None = None,
               style: str = "house", midi_roles: dict | None = None, sidechain: str | None = None, vocal: dict | None = None,
               structure: str = "reference") -> dict:
    """Return the plan. midi_roles: {'bass': {'name': 'Serum', 'uri': ...}, ...} makes those roles MIDI tracks.
    vocal: the output of flow.vocal.prepare (phrases already at the project tempo and key), placed where the style wants it."""
    bpm = bpm or ref["bpm"]
    midi_roles = midi_roles or {}
    st = stylelib.get(style)
    style = st.key
    tmpl = st.template
    structure = structure if structure in ("reference", "typical") else "reference"
    ref_secs, note = reference_sections(ref, structure)
    prof = profiles.for_style(st)
    ref_secs, shape_notes = normalize_sections(ref_secs, prof)
    total = target_bars(length_seconds, bpm, ref["bars"] if note is None else sum(s["bars"] for s in ref_secs))
    sections = scale_sections(ref_secs, total, prof.caps)
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

    # which sections each role belongs to, then the shaping that makes it breathe
    wanted: dict[str, list[dict]] = {}
    for role in roles:
        if not source(role):
            continue
        secs_for = []
        for sct in sections:
            label = sct["label"] if sct["label"] in tmpl else ("Drop 2" if sct["label"].startswith("Drop") else "Groove")
            ok = role in tmpl[label]
            if role == "kick" and sct["kick_ratio"] < 0.35 and not (prof.break_kick == "half" and sct["label"] in ("Breakdown", "Build")):
                ok = False
            if role == "kick" and sct["label"] == "Intro" and sct["kick_ratio"] >= 0.35:
                ok = True
            if ok:
                secs_for.append(sct)
        if secs_for:
            wanted[role] = secs_for
    shaped = shape_layers(wanted, sections, total, prof)
    tracks = []
    for role in roles:
        src = source(role)
        spans = shaped.get(role) or []
        if not src or not spans:
            continue
        t = {"name": _track_name(role, src["name"]), "role": role, "spans": spans, "source": src}
        if role in midi_roles:
            t["kind"] = "midi"
            t["plugin"] = midi_roles[role]
            t["notes"] = patterns.midi_notes(role, tonic, 4, style=style)
            t["clip_bars"] = 4
        else:
            t["kind"] = "audio"
            t["clip_bars"] = src["bars"] or 4
        tracks.append(t)

    if vocal and vocal.get("phrases"):
        placements = place_vocal(sections, vocal, style)
        if placements:
            ph0 = vocal["phrases"][0]
            tracks.append({"name": f"Vocal · {vocal['name'].rsplit('.', 1)[0]}", "role": "vocal", "kind": "audio", "spans": [], "placements": placements,
                           "source": {"path": ph0["path"], "bars": None, "kind": "oneshot", "name": vocal["name"]}, "clip_bars": 4})

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
        "notes": ([note] if note else []) + shape_notes, "profile": prof.key,
        "structure": "reference" if (structure == "reference" and note is None) else "typical",
    }


def place_vocal(sections: list[dict], vocal: dict, style: str) -> list[dict]:
    """Phrases, in order, cycling, in the sections the style wants a vocal in. Drops get it after their first
    8 bars and at most half their length; breakdowns from bar one. Phrases sit on a 2-bar grid and never cross a section edge."""
    st = stylelib.get(style)
    phrases = vocal.get("phrases") or []
    if not phrases:
        return []
    out, k = [], 0
    for s in sections:
        label = s["label"] if s["label"] in stylelib.SECTIONS else ("Drop 2" if s["label"].startswith("Drop") else "Groove")
        if label not in st.vocal_sections:
            continue
        is_drop = label.startswith("Drop") or label == "Return"
        lead = min(8, max(0, s["bars"] - 8)) if is_drop else 0
        budget = s["bars"] if label == "Breakdown" else max(2, int(s["bars"] * 0.5))
        bar, used = s["start"] + lead, 0
        while bar < s["end"]:
            ph = phrases[k % len(phrases)]
            if bar + ph["bars"] > s["end"] or used + ph["bars"] > budget:
                break
            out.append({"bar": int(bar), "path": ph["path"], "bars": int(ph["bars"]), "phrase": k % len(phrases)})
            k += 1
            used += ph["bars"]
            bar += ph["bars"] + (4 if k % 2 == 0 else 0)   # a breath after every second phrase
            bar += (bar - s["start"]) % 2
    return out


def _track_name(role: str, src_name: str) -> str:
    pretty = {"kick": "Kick", "clap": "Clap", "ohat": "Open Hat", "chat": "Closed Hat", "tom": "Tom", "tom_b": "Tom B", "tom_c": "Tom C",
              "perc": "Perc", "shaker_loop": "Shaker Loop", "hat_loop": "Hat Loop", "perc_loop": "Perc Loop", "perc_loop2": "Perc Loop 2",
              "bass": "Bass", "synth": "Synth", "pad": "Pad", "atmos": "Atmosphere", "snare_roll": "Build Roll", "vocal": "Vocal"}
    base = src_name.rsplit(".", 1)[0]
    return f"{pretty.get(role, role.title())} · {base}"


def seconds(bars: float, bpm: float) -> float:
    return bars * 240.0 / bpm


def plan_view(plan: dict) -> dict:
    """Everything the UI needs to draw the arrangement: sections and one record per track, in plan order.
    `layers[i]` is plan['tracks'][i], so a '@track:i' progress event maps straight onto it."""
    layers = []
    for i, t in enumerate(plan.get("tracks", [])):
        spans = [[int(a), int(b)] for a, b in t.get("spans", [])] + [[int(p["bar"]), int(p["bar"] + p["bars"])] for p in t.get("placements", [])]
        layers.append({"i": i, "name": t["name"].split(" · ")[0], "role": t["role"], "spans": spans,
                       "hits": [float(h) for h in t.get("hits", [])],
                       "sweeps": [int(b) for b, _p in t.get("sweeps", [])], "sweep_bars": int(t.get("sweep_bars") or 8)})
    return {"bars": int(plan.get("bars") or 0), "bpm": float(plan.get("bpm") or 120),
            "sections": [{"label": s["label"], "start": s["start"], "end": s["end"], "bars": s["bars"]} for s in plan.get("sections", [])],
            "layers": layers, "rows": describe_rows(plan), "steps": describe(plan), "placeholders": plan.get("placeholders", []), "notes": plan.get("notes", []),
            "structure": plan.get("structure", "reference"), "style": plan.get("style"), "style_name": plan.get("style_name"),
            "reference": {"bars": plan.get("reference", {}).get("bars"), "bpm": plan.get("reference", {}).get("bpm")}}


def describe_rows(plan: dict) -> list[dict]:
    """Structured build steps: one row per section with the layers present at its first bar."""
    rows = []
    prev: set[str] = set()
    for s in plan["sections"]:
        here = [t["name"].split(" · ")[0] for t in plan["tracks"] if any(a <= s["start"] < b for a, b in t.get("spans", []))]
        cur = set(here)
        rows.append({"label": s["label"], "start": s["start"], "end": s["end"], "bars": s["bars"], "layers": here,
                     "enter": [h for h in here if h not in prev], "leave": sorted(prev - cur)})
        prev = cur
    return rows


def describe(plan: dict) -> list[str]:
    """Human-readable build steps (what enters where), for the report and the UI."""
    lines = []
    for s in plan["sections"]:
        here = [t["name"].split(" · ")[0] for t in plan["tracks"] if any(a <= s["start"] < b for a, b in t.get("spans", []))]
        lines.append(f"{s['label']} · bars {s['start']}–{s['end'] - 1} ({s['bars']} bars): " + (", ".join(here) if here else "FX only"))
    return lines
