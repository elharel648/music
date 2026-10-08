"""Measure every Live Set under a folder and print what real arrangements do, side by side.

    python tools/corpus.py "<folder with .als files>" [--json out.json]

Variants of the same project (Suite/Standard/Massive versions, copies) are collapsed to the largest one.
"""
from __future__ import annotations
import json
import re
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from als_map import read_set, measure, report  # noqa: E402

SKIP = ("backup", "._")


def dedupe(paths: list[Path]) -> list[Path]:
    by_key: dict[str, Path] = {}
    for p in paths:
        key = re.sub(r"\(.*?\)|\bv\s?\d(\.\d+)?\b|standard|suite|massive|serum|diva|operator|version|template|project|copy|עותק של|w\b|\d+", "", p.stem.lower())
        key = re.sub(r"[^a-z]+", " ", key).strip() or p.stem.lower()
        key = str(p.parent) + "|" + key
        if key not in by_key or p.stat().st_size > by_key[key].stat().st_size:
            by_key[key] = p
    return sorted(by_key.values())


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 1) if xs else None


def main(argv: list[str]) -> int:
    folder = Path(argv[0])
    out_json = argv[argv.index("--json") + 1] if "--json" in argv else None
    paths = [p for p in folder.rglob("*.als") if not any(k in str(p).lower() for k in SKIP)]
    paths = dedupe(paths)
    rows = []
    for p in paths:
        try:
            s = read_set(p)
        except Exception as e:  # noqa: BLE001
            print(f"skip {p.name}: {e}", file=sys.stderr); continue
        if s["bars"] < 32:
            print(f"skip {p.name}: {s['bars']} bars (not an arrangement)", file=sys.stderr); continue
        m = measure(s)
        m["name"] = p.stem
        rows.append(m)
        print(report(s, m)); print()
    if not rows:
        return 1
    print("=" * 100)
    print(f"{'set':44} {'bars':>5} {'1stK':>5} {'intro':>5} {'brk#':>4} {'brkLen':>7} {'L on':>5} {'L off':>5} {'peak':>4} {'sil':>4}")
    for m in rows:
        intro = next((x["bars"] for x in m["sections"] if x["kind"] == "intro"), None)
        brks = [x["bars"] for x in m["sections"] if x["kind"] == "break"] or m["break_lengths"]
        print(f"{m['name'][:44]:44} {m['bars']:5} {str(m['first_kick_bar']):>5} {str(intro):>5} {len(brks):4} {str(brks)[:7]:>7} {m['layers_kick_on']:5} {m['layers_kick_off']:5} {m['peak_layers']:4} {m['silent_bars_inside']:4}")
    print("-" * 100)
    intros = [next((x["bars"] for x in m["sections"] if x["kind"] == "intro"), None) for m in rows]
    brk_lens = [b for m in rows for b in ([x["bars"] for x in m["sections"] if x["kind"] == "break"] or m["break_lengths"])]
    drop_lens = [x["bars"] for m in rows for x in m["sections"] if x["kind"] == "drop"]
    build_lens = [x["bars"] for m in rows for x in m["sections"] if x["kind"] == "build"]
    outro_lens = [x["bars"] for m in rows for x in m["sections"] if x["kind"] == "outro"]
    print(f"median bars {med([m['bars'] for m in rows])} · first kick {med([m['first_kick_bar'] for m in rows])} · intro {med(intros)} · "
          f"break {med(brk_lens)} · build {med(build_lens)} · drop {med(drop_lens)} · outro {med(outro_lens)}")
    print(f"median layers with kick {med([m['layers_kick_on'] for m in rows])} · without {med([m['layers_kick_off'] for m in rows])} · peak {med([m['peak_layers'] for m in rows])} · breaks per track {med([len([x for x in m['sections'] if x['kind']=='break']) or len(m['breaks']) for m in rows])}")
    # entry order: median entry bar per role across sets, relative to first kick
    roles = {}
    for m in rows:
        fk = m["first_kick_bar"] or 1
        for r, b in m["entries"].items():
            roles.setdefault(r, []).append(b - fk)
    print("median entry bar relative to the kick: " + "  ".join(f"{r}:{med(v):+}" for r, v in sorted(roles.items(), key=lambda kv: med(kv[1]) or 0)))
    # section-level layer ratios
    for kind in ("intro", "build", "break", "drop", "outro"):
        xs = [x["layers"] for m in rows for x in m["sections"] if x["kind"] == kind]
        ks = [x["kick"] for m in rows for x in m["sections"] if x["kind"] == kind]
        if xs:
            print(f"{kind:6} layers {med(xs)}  kick present {med(ks):.0%}  (n={len(xs)})")
    if out_json:
        Path(out_json).write_text(json.dumps([{k: v for k, v in m.items() if k not in ('density', 'grid')} for m in rows], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
