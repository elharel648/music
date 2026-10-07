"""Command line: `flow analyze <ref>` · `flow build --ref .. --pack .. [--length 6:30] [--target ableton|stems] [--out DIR]`."""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile

from . import __version__, analysis, pack as packmod, patterns, arrange, export, plugins, license as lic


def parse_length(s: str | None) -> float | None:
    if not s:
        return None
    if ":" in s:
        m, sec = s.split(":", 1)
        return int(m) * 60 + float(sec)
    return float(s)


def run_build(ref_path: str, pack_dir: str, length: float | None, target: str, out: str | None, style: str = "house",
              bpm: float | None = None, midi_synth: str | None = None, sidechain: str | None = None, force: bool = False,
              progress=None, work_dir: str | None = None) -> dict:
    prog = progress or (lambda m, p: print(f"[{p * 100:5.1f}%] {m}"))
    ok, st = lic.can_build()
    if not ok:
        raise SystemExit(f"License: {st.get('reason')}")
    prog("Analyzing the reference", 0.02)
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
    plan = arrange.build_plan(ref, kit, loops, bpm=bpm, length_seconds=length, style=style, midi_roles=midi_roles, sidechain=sidechain)
    prog(f"Plan: {plan['bars']} bars, {len(plan['tracks'])} tracks", 0.4)
    result = {"reference": {k: v for k, v in ref.items() if k != "bar_features"}, "plan": plan, "kit": {k: v["name"] for k, v in kit.items()}}
    if target == "ableton":
        from .ableton_bridge import Live
        live = Live()
        rep = live.apply_plan(plan, progress=lambda m, p: prog(m, 0.4 + 0.6 * p), force=force)
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
        r = run_build(args.ref, args.pack, parse_length(args.length), args.target, args.out, args.style, args.bpm, args.synth, args.sidechain, args.force)
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
