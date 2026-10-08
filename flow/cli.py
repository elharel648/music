"""Command line: `flow analyze <ref>` · `flow build --ref .. --pack .. [--length 6:30] [--target ableton|stems] [--out DIR]`."""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile

from . import __version__, analysis, pack as packmod, patterns, arrange, export, plugins, license as lic, styles as stylelib


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


PREP_KEYS = ("reference", "pack", "length", "style", "bpm", "synth", "finish", "vocal", "structure", "kit")


def prepare(ref_path: str, pack_dir: str, length: float | None, style: str = "house", bpm: float | None = None, midi_synth: str | None = None,
            progress=None, work_dir: str | None = None, finish_opts: set[str] | None = None, on_plan=None, vocal: str | None = None,
            structure: str = "reference", kit_overrides: dict | None = None) -> dict:
    """Everything up to the plan: measure, choose from the user's sounds, render loops, place the vocal, plan, sweeps.
    Returns a context that `commit` writes to a DAW and `render_preview` turns into a mix to listen to."""
    from . import finish as finishmod, transitions
    finish_opts = set(finish_opts) if finish_opts is not None else set(finishmod.DEFAULT_ON)
    prog = progress or (lambda m, p: None if m.startswith("@") else print(f"[{p * 100:5.1f}%] {m}"))
    ok, st = lic.can_build()
    if not ok:
        raise SystemExit(f"License: {st.get('reason')}")
    prog("Measuring the reference", 0.02)
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
    kit = packmod.choose_kit(pk, bpm, overrides=kit_overrides)
    prog(f"From your sounds: {len(kit)} roles", 0.22)
    work = work_dir or os.path.join(tempfile.gettempdir(), "FLOW loops")
    transpose = {}
    for role in ("bass", "synth"):
        s_ = kit.get(role)
        if s_ and s_.get("key") and s_["key"].get("pc") is not None:
            d = (ref["key"]["pc"] - s_["key"]["pc"]) % 12
            transpose[role] = d if d <= 6 else d - 12
    style = stylelib.get(style).key
    loops = patterns.render_kit_loops(kit, bpm, work, transpose=transpose, style=style)
    prog(f"Rendered {len(loops)} pattern loops ({stylelib.get(style).name})", 0.3)
    voc = None
    if vocal:
        from . import vocal as vocmod
        info = vocmod.analyze(vocal)
        voc = vocmod.prepare(info, bpm, ref["key"]["pc"], work, progress=lambda m, p: prog(m, 0.32))
        prog(f"Vocal: {len(voc['phrases'])} phrases" + (" · " + "; ".join(voc["notes"]) if voc["notes"] else ""), 0.33)
    midi_roles = {}
    if midi_synth:
        midi_roles = {"bass": {"name": midi_synth}, "synth": {"name": midi_synth}}
    plan = arrange.build_plan(ref, kit, loops, bpm=bpm, length_seconds=length, style=style, midi_roles=midi_roles,
                              sidechain=None, vocal=voc, structure=structure)
    if "transitions" in finish_opts:
        n_sw = transitions.add_sweeps(plan, work, progress=lambda m, p: prog(m, 0.36))
        prog(f"Transition sweeps rendered: {n_sw}", 0.38)
    plan["finish"] = sorted(finish_opts)
    prog(f"Arranged: {plan['bars']} bars, {len(plan['tracks'])} tracks", 0.4)
    if on_plan:
        on_plan(arrange.plan_view(plan))
    return {"ref": ref, "pack": pk, "kit": kit, "loops": loops, "plan": plan, "work": work, "bpm": bpm, "ref_path": ref_path, "finish_opts": finish_opts}


def commit(ctx: dict, target: str, out: str | None = None, sidechain: str | None = None, force: bool = False, progress=None) -> dict:
    """Write the prepared plan: into the Live Set in front, or as stems + MIDI + Blueprint."""
    from . import finish as finishmod
    prog = progress or (lambda m, p: None if m.startswith("@") else print(f"[{p * 100:5.1f}%] {m}"))
    plan, ref, kit, finish_opts = ctx["plan"], ctx["ref"], ctx["kit"], ctx["finish_opts"]
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
        out_dir = out or os.path.join(os.path.dirname(ctx["ref_path"]), "FLOW export")
        exp = export.export_all(plan, ref, out_dir, progress=lambda m, p: prog(m, 0.4 + 0.6 * p))
        result["export"] = exp
    return result


def render_preview(ctx: dict, path: str | None = None, progress=None) -> dict:
    path = path or os.path.join(ctx["work"], "FLOW preview.wav")
    return export.render_mix(ctx["plan"], path, progress=progress)


def run_build(ref_path: str, pack_dir: str, length: float | None, target: str, out: str | None, style: str = "house",
              bpm: float | None = None, midi_synth: str | None = None, sidechain: str | None = None, force: bool = False,
              progress=None, work_dir: str | None = None, finish_opts: set[str] | None = None, on_plan=None, vocal: str | None = None,
              structure: str = "reference", kit_overrides: dict | None = None) -> dict:
    ctx = prepare(ref_path, pack_dir, length, style, bpm, midi_synth, progress, work_dir, finish_opts, on_plan, vocal, structure, kit_overrides)
    return commit(ctx, target, out, sidechain, force, progress)


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
    b.add_argument("--style", choices=sorted(stylelib.STYLES) + sorted(stylelib.ALIASES), default="house")
    b.add_argument("--vocal", help="an acapella, chant or hook to cut into phrases and place")
    b.add_argument("--structure", choices=["reference", "typical"], default="reference", help="follow the reference's sections, or a typical club structure")
    b.add_argument("--bpm", type=float)
    b.add_argument("--synth", help="installed synth to drive bass/synth as MIDI (Ableton target), e.g. Serum")
    b.add_argument("--sidechain", help="sidechain plug-in to load on every non-kick track, e.g. 'Kickstart 2'")
    b.add_argument("--force", action="store_true", help="write even if the Live Set in front is not empty")
    b.add_argument("--finish", help="comma-separated finish moves (gain,lowcut,duck,space,glue,transitions); 'none' for a bare skeleton")
    pv = sub.add_parser("preview", help="Render a mix of the arrangement to listen to, without writing to a DAW")
    for arg, kw in (("--ref", {"required": True}), ("--pack", {"required": True}), ("--length", {}), ("--style", {"default": "house"}), ("--vocal", {}),
                    ("--structure", {"choices": ["reference", "typical"], "default": "reference"}), ("--bpm", {"type": float}), ("--out", {"required": True})):
        pv.add_argument(arg, **kw)
    sub.add_parser("plugins", help="List installed plug-ins FLOW recognizes")
    sub.add_parser("license", help="Show trial / license status")
    k = sub.add_parser("activate", help="Activate with a license key")
    k.add_argument("key")
    ap.add_argument("--version", action="version", version=f"FLOW {__version__}")
    args = ap.parse_args(argv)
    if args.cmd == "analyze":
        r = analysis.analyze_reference(args.ref, bpm_hint=args.bpm)
        r.pop("bar_features", None)
        r.pop("overview", None)
        print(json.dumps(r, indent=1))
        return 0
    if args.cmd == "build":
        fin = None if args.finish is None else (set() if args.finish == "none" else {x.strip() for x in args.finish.split(",") if x.strip()})
        r = run_build(args.ref, args.pack, parse_length(args.length), args.target, args.out, args.style, args.bpm, args.synth, args.sidechain, args.force, finish_opts=fin, vocal=args.vocal, structure=args.structure)
        r.get("reference", {}).pop("overview", None)
        print(json.dumps({k: v for k, v in r.items() if k != "plan"}, indent=1, default=str))
        for line in arrange.describe(r["plan"]):
            print(" -", line)
        return 0
    if args.cmd == "preview":
        ctx = prepare(args.ref, args.pack, parse_length(args.length), args.style, args.bpm, vocal=args.vocal, structure=args.structure)
        r = render_preview(ctx, args.out)
        print(json.dumps(r, indent=1))
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
