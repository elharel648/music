"""Command line: `flow analyze <ref>` · `flow build --ref .. --pack .. [--length 6:30] [--target ableton|stems] [--out DIR]`."""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile

from . import __version__, analysis, pack as packmod, patterns, arrange, export, plugins, license as lic


def parse_length(s) -> float | None:
    """'6:30' -> 390 s · '6' or '6.5' -> minutes (small numbers are minutes) · '390' -> seconds · numbers pass through."""
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(",", ".")
    if ":" in s:
        m, sec = s.split(":", 1)
        return int(m) * 60 + float(sec or 0)
    v = float(s)
    return v * 60 if v <= 20 else v


def run_build(ref_path: str, pack_dir: str, length: float | None, target: str, out: str | None, style: str = "house",
              bpm: float | None = None, midi_synth: str | None = None, sidechain: str | None = None, force: bool = False,
              progress=None, work_dir: str | None = None, finish_opts: set[str] | None = None) -> dict:
    from . import finish as finishmod, transitions
    finish_opts = set(finish_opts) if finish_opts is not None else set(finishmod.DEFAULT_ON)
    prog = progress or (lambda m, p: print(f"[{p * 100:5.1f}%] {m}"))
    ok, st = lic.can_build()
    if not ok:
        raise SystemExit(f"License: {st.get('reason')}")
    prog("Analyzing the reference", 0.02)
    pk = packmod.scan_pack(pack_dir)
    if any("iCloud" in w for w in pk.get("warnings", [])):
        prog("Some sounds are still in iCloud. Downloading them now…", 0.03)
        packmod.download_icloud(pack_dir, progress=lambda m, p: prog(m, 0.03 + 0.07 * p))
        pk = packmod.scan_pack(pack_dir)
    ref = analysis.analyze_reference(ref_path, bpm_hint=bpm or pk.get("bpm_hint"))
    bpm = bpm or ref["bpm"]
    prog(f"Reference: {ref['bpm']:.0f} BPM, {ref['key']['tonic']} {ref['key']['mode']}, {ref['bars']} bars, {len(ref['sections'])} sections", 0.15)
    if pk.get("warnings"):
        raise RuntimeError(" ".join(pk["warnings"]) + f" (folder: {pack_dir})")
    kit = packmod.choose_kit(pk, bpm)
    prog(f"Kit: {', '.join(sorted(kit))}", 0.22)
    work = work_dir or os.path.join(out or tempfile.gettempdir(), "FLOW loops")
    transpose = {}
    for role in ("bass", "synth"):
        s = kit.get(role)
        if s and s.get("key") and s["key"].get("pc") is not None:
            d = (ref["key"]["pc"] - s["key"]["pc"]) % 12
            transpose[role] = d if d <= 6 else d - 12
    loops = patterns.render_kit_loops(kit, bpm, work, transpose=transpose)
    prog(f"Rendered {len(loops)} pattern loops", 0.35)
    midi_roles = {}
    if midi_synth:
        midi_roles = {"bass": {"name": midi_synth}, "synth": {"name": midi_synth}}
    plan = arrange.build_plan(ref, kit, loops, bpm=bpm, length_seconds=length, style=style, midi_roles=midi_roles,
                              sidechain=None)  # ducking is a finish move now
    if "transitions" in finish_opts:
        n_sw = transitions.add_sweeps(plan, work, progress=lambda m, p: prog(m, 0.38))
        prog(f"Transition sweeps rendered: {n_sw}", 0.39)
    plan["finish"] = sorted(finish_opts)
    prog(f"Plan: {plan['bars']} bars, {len(plan['tracks'])} tracks", 0.4)
    result = {"reference": {k: v for k, v in ref.items() if k != "bar_features"}, "plan": plan, "kit": {k: v["name"] for k, v in kit.items()}}
    if target == "ableton":
        from .ableton_bridge import Live
        live = Live()
        base = live.session()["track_count"]
        rep = live.apply_plan(plan, progress=lambda m, p: prog(m, 0.4 + 0.45 * p), force=force)
        moves = finish_opts - {"transitions"}
        if moves:
            warns = finishmod.apply(live, plan, base, moves, sidechain, progress=lambda m, p: prog(m, 0.85 + 0.15 * p))
            rep.setdefault("warnings", []).extend(warns)
            rep["finish"] = sorted(moves)
        result["ableton"] = rep
    else:
        out_dir = out or os.path.join(os.path.dirname(ref_path), "FLOW export")
        exp = export.export_all(plan, ref, out_dir, progress=lambda m, p: prog(m, 0.4 + 0.6 * p))
        result["export"] = exp
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="flow", description=f"FLOW {__version__}: reference in, your sounds in, an arrangement out.")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("analyze", help="Measure a reference track")
    a.add_argument("ref")
    a.add_argument("--bpm", type=float)
    b = sub.add_parser("build", help="Build the arrangement")
    b.add_argument("--ref", required=True)
    b.add_argument("--pack", required=True)
    b.add_argument("--length", help="target length, e.g. 6:30 or 390")
    b.add_argument("--target", choices=["ableton", "stems"], default="stems")
    b.add_argument("--out")
    b.add_argument("--style", choices=sorted(arrange.STYLE_TEMPLATES), default="house")
    b.add_argument("--bpm", type=float)
    b.add_argument("--synth", help="installed synth to drive bass/synth as MIDI (Ableton target), e.g. Serum")
    b.add_argument("--sidechain", help="sidechain plug-in to load on every non-kick track, e.g. 'Kickstart 2'")
    b.add_argument("--force", action="store_true", help="write even if the Live Set in front is not empty")
    b.add_argument("--finish", help="comma-separated finish moves (gain,lowcut,duck,space,glue,transitions); 'none' for a bare skeleton")
    sub.add_parser("plugins", help="List installed plug-ins FLOW recognizes")
    sub.add_parser("license", help="Show trial / license status")
    k = sub.add_parser("activate", help="Activate with a license key")
    k.add_argument("key")
    ap.add_argument("--version", action="version", version=f"FLOW {__version__}")
    args = ap.parse_args(argv)
    if args.cmd == "analyze":
        r = analysis.analyze_reference(args.ref, bpm_hint=args.bpm)
        r.pop("bar_features", None)
        print(json.dumps(r, indent=1))
        return 0
    if args.cmd == "build":
        fin = None if args.finish is None else (set() if args.finish == "none" else {x.strip() for x in args.finish.split(",") if x.strip()})
        r = run_build(args.ref, args.pack, parse_length(args.length), args.target, args.out, args.style, args.bpm, args.synth, args.sidechain, args.force, finish_opts=fin)
        print(json.dumps({k: v for k, v in r.items() if k != "plan"}, indent=1, default=str))
        for line in arrange.describe(r["plan"]):
            print(" -", line)
        return 0
    if args.cmd == "plugins":
        print(json.dumps({k: v for k, v in plugins.scan_installed().items() if k != "all"}, indent=1))
        return 0
    if args.cmd == "license":
        print(json.dumps(lic.status(), indent=1))
        return 0
    if args.cmd == "activate":
        print(json.dumps(lic.activate(args.key), indent=1))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
