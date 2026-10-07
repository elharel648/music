"""Scan the plug-ins installed on this computer and suggest which ones FLOW can use."""
from __future__ import annotations
import os
import platform

SYNTHS = ["Serum", "Serum 2", "Sylenth1", "Diva", "Massive", "Massive X", "Spire", "Vital", "Pigments", "Analog Lab V", "Analog Lab",
          "Omnisphere", "Phase Plant", "Hive", "Repro-1", "Repro-5", "Zebra2", "Avenger", "Nexus", "Kontakt", "FM8", "Monark", "Operator"]
SIDECHAIN = ["Kickstart 2", "Kickstart", "ShaperBox 2", "ShaperBox 3", "LFOTool", "Pump", "VolumeShaper", "Trackspacer", "Duck"]
REVERB = ["ValhallaRoom", "ValhallaVintageVerb", "ValhallaPlate", "ValhallaShimmer", "FabFilter Pro-R", "FabFilter Pro-R 2", "Pro-R", "Raum", "Blackhole"]
DELAY = ["ValhallaDelay", "FabFilter Timeless 3", "Echoboy", "Replika", "H-Delay"]


def plugin_dirs() -> list[tuple[str, str]]:
    sysname = platform.system()
    home = os.path.expanduser("~")
    if sysname == "Darwin":
        return [("VST3", "/Library/Audio/Plug-Ins/VST3"), ("VST3", f"{home}/Library/Audio/Plug-Ins/VST3"),
                ("AU", "/Library/Audio/Plug-Ins/Components"), ("AU", f"{home}/Library/Audio/Plug-Ins/Components"),
                ("VST", "/Library/Audio/Plug-Ins/VST"), ("VST", f"{home}/Library/Audio/Plug-Ins/VST")]
    if sysname == "Windows":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        cf = os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files")
        return [("VST3", os.path.join(cf, "VST3")), ("VST", os.path.join(pf, "Steinberg", "VstPlugins")),
                ("VST", os.path.join(pf, "VstPlugins")), ("VST", os.path.join(cf, "VST2"))]
    return [("VST3", "/usr/lib/vst3"), ("VST3", f"{home}/.vst3"), ("VST", f"{home}/.vst")]


def scan_installed() -> dict:
    found: dict[str, dict] = {}
    for fmt, d in plugin_dirs():
        if not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for e in entries:
            name, ext = os.path.splitext(e)
            if ext.lower() not in (".vst3", ".component", ".vst", ".dll"):
                continue
            if name.startswith("WaveShell") or "AUHook" in name:
                continue
            rec = found.setdefault(name, {"name": name, "formats": [], "path": os.path.join(d, e)})
            if fmt not in rec["formats"]:
                rec["formats"].append(fmt)
    names = sorted(found)

    def pick(cands):
        hits = []
        for c in cands:
            for n in names:
                if n.lower() == c.lower() or n.lower().startswith(c.lower() + " ") or n.lower() == c.lower().replace(" ", ""):
                    if n not in hits:
                        hits.append(n)
        return hits

    return {"count": len(names), "all": [found[n] for n in names],
            "synths": pick(SYNTHS), "sidechain": pick(SIDECHAIN), "reverb": pick(REVERB), "delay": pick(DELAY)}
