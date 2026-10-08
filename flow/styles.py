"""The style library: which layers live in which section, how the patterns groove, how hard the duck pumps.

Structure (section order and lengths) always comes from the reference. A style decides what plays inside it.
Pattern entries override flow.patterns.PATTERNS per role (same shape); anything not listed keeps the default.
"""
from __future__ import annotations
from dataclasses import dataclass, field

SECTIONS = ("Intro", "Groove", "Drop", "Breakdown", "Build", "Return", "Drop 2", "Outro")
ROLES = {"kick", "clap", "ohat", "chat", "tom", "tom_b", "tom_c", "perc", "shaker_loop", "hat_loop", "perc_loop", "perc_loop2",
         "bass", "synth", "pad", "atmos", "snare_roll"}

OFF8 = [0.5, 1.5, 2.5, 3.5]
ALL16 = [i / 4 for i in range(16)]


@dataclass(frozen=True)
class Style:
    key: str
    name: str
    group: str
    bpm: tuple[int, int]
    blurb: str
    template: dict[str, list[str]]
    patterns: dict[str, dict] = field(default_factory=dict)
    duck: float = 0.55          # Auto Pan amount for the sidechain pump (0..1)
    reverb: float = 1.0         # scale on the Space move (wet and decay)
    vocal_sections: tuple[str, ...] = ("Breakdown", "Drop", "Drop 2")


def _t(intro, groove, drop, breakdown, build, ret, drop2, outro):
    return {"Intro": intro, "Groove": groove, "Drop": drop, "Breakdown": breakdown, "Build": build, "Return": ret, "Drop 2": drop2, "Outro": outro}


STYLES: dict[str, Style] = {}


def _add(s: Style):
    STYLES[s.key] = s


_add(Style("house", "House", "House", (120, 128),
     "Classic 4/4. Claps and open hats on the drop, toms and pads from the start, bass from the groove.",
     _t(["atmos", "pad", "kick", "tom", "tom_b", "shaker_loop", "perc"],
        ["atmos", "pad", "kick", "tom", "tom_b", "tom_c", "shaker_loop", "perc", "bass", "synth", "perc_loop", "chat"],
        ["atmos", "pad", "kick", "tom", "tom_b", "tom_c", "shaker_loop", "perc", "bass", "synth", "perc_loop", "chat", "clap", "hat_loop"],
        ["atmos", "pad", "synth"],
        ["atmos", "pad", "synth", "tom", "tom_b", "snare_roll"],
        ["atmos", "pad", "kick", "tom", "tom_b", "shaker_loop", "perc", "bass", "synth", "perc_loop"],
        ["atmos", "pad", "kick", "tom", "tom_b", "tom_c", "shaker_loop", "perc", "bass", "synth", "perc_loop", "chat", "clap", "hat_loop", "ohat", "perc_loop2"],
        ["atmos", "kick", "shaker_loop", "bass", "perc"])))

_add(Style("deep_house", "Deep House", "House", (118, 124),
     "Warm and low. Pads the whole way, soft claps, off-beat hats, a bass that walks.",
     _t(["atmos", "pad", "kick", "chat", "shaker_loop"],
        ["atmos", "pad", "kick", "chat", "shaker_loop", "bass", "perc"],
        ["atmos", "pad", "kick", "chat", "ohat", "shaker_loop", "bass", "perc", "clap", "synth", "perc_loop"],
        ["atmos", "pad", "synth", "chat"],
        ["atmos", "pad", "synth", "chat", "snare_roll"],
        ["atmos", "pad", "kick", "chat", "shaker_loop", "bass", "perc"],
        ["atmos", "pad", "kick", "chat", "ohat", "shaker_loop", "bass", "perc", "clap", "synth", "perc_loop", "hat_loop", "perc_loop2"],
        ["atmos", "pad", "kick", "bass", "chat"]),
     patterns={"chat": {"beats": OFF8, "gain": 0.55, "accent": OFF8}, "clap": {"beats": [1, 3], "gain": 0.8},
               "bass": {"beats": OFF8, "gain": 0.85, "pitch_cycle": [0, 0, 0, 0, 0, 0, 0, 5]},
               "synth": {"beats": [1.5, 3.5], "gain": 0.7, "pitch_cycle": [0, 3, 7, 10]}},
     duck=0.45, reverb=1.2, vocal_sections=("Groove", "Breakdown", "Drop 2")))

_add(Style("tech_house", "Tech House", "House", (124, 130),
     "Driving and percussive. Bass is the lead, tight claps, rolling hats, barely a pad.",
     _t(["kick", "chat", "shaker_loop", "perc"],
        ["kick", "chat", "shaker_loop", "perc", "bass", "perc_loop", "atmos"],
        ["kick", "chat", "ohat", "clap", "shaker_loop", "perc", "perc_loop", "bass", "synth", "hat_loop", "atmos"],
        ["atmos", "synth", "chat", "perc_loop"],
        ["atmos", "synth", "chat", "perc_loop", "snare_roll"],
        ["kick", "chat", "shaker_loop", "perc", "bass", "perc_loop", "atmos"],
        ["kick", "chat", "ohat", "clap", "shaker_loop", "perc", "perc_loop", "bass", "synth", "hat_loop", "atmos", "perc_loop2", "tom"],
        ["kick", "chat", "bass", "perc"]),
     patterns={"chat": {"beats": ALL16, "gain": 0.55, "accent": OFF8},
               "bass": {"beats": [0.5, 1.5, 1.75, 2.5, 3.5, 3.75], "gain": 0.95, "pitch_cycle": [0] * 11 + [12]},
               "perc": {"beats": [1.75, 3.5], "every": 1}, "synth": {"beats": [0.75, 2.75], "gain": 0.75, "pitch_cycle": [0, 0, 3, 5]}},
     duck=0.65, reverb=0.7, vocal_sections=("Drop", "Drop 2")))

_add(Style("afro_house", "Afro House", "House", (118, 125),
     "Percussion first. Shakers and toms from bar one, bass comes late, claps stay sparse. Built for chants.",
     _t(["atmos", "shaker_loop", "perc", "tom", "pad"],
        ["atmos", "pad", "kick", "shaker_loop", "perc", "tom", "tom_b", "perc_loop"],
        ["atmos", "pad", "kick", "shaker_loop", "perc", "tom", "tom_b", "tom_c", "perc_loop", "bass", "synth", "chat"],
        ["atmos", "pad", "synth", "shaker_loop", "tom"],
        ["atmos", "pad", "synth", "shaker_loop", "tom", "tom_b", "snare_roll"],
        ["atmos", "pad", "kick", "shaker_loop", "perc", "tom", "tom_b", "perc_loop", "bass"],
        ["atmos", "pad", "kick", "shaker_loop", "perc", "tom", "tom_b", "tom_c", "perc_loop", "bass", "synth", "chat", "clap", "perc_loop2", "ohat"],
        ["atmos", "kick", "shaker_loop", "perc", "tom"]),
     patterns={"tom": {"beats": [0, 0.75, 2.5], "gain": 0.9}, "tom_b": {"beats": [1.5, 3.25], "gain": 0.8}, "tom_c": {"beats": [2.75], "gain": 0.8, "every": 2},
               "perc": {"beats": [1.75, 3.5], "every": 1, "gain": 0.8}, "clap": {"beats": [1, 3], "gain": 0.7},
               "chat": {"beats": OFF8, "gain": 0.5, "accent": OFF8},
               "bass": {"beats": [0.5, 1.75, 2.5, 3.75], "gain": 0.9, "pitch_cycle": [0, 0, 7, 5, 0, 0, 7, 3]},
               "synth": {"beats": [0, 1.5, 2.75], "gain": 0.7, "pitch_cycle": [0, 3, 7, 0, 3, 10, 7, 5]}},
     duck=0.45, reverb=1.1, vocal_sections=("Groove", "Breakdown", "Drop", "Drop 2")))

_add(Style("progressive", "Progressive House", "House", (122, 128),
     "Layers that keep arriving. Pads and plucks, long builds, a bass that moves with the chords.",
     _t(["atmos", "pad", "kick", "chat", "shaker_loop"],
        ["atmos", "pad", "kick", "chat", "shaker_loop", "bass", "perc"],
        ["atmos", "pad", "kick", "chat", "shaker_loop", "bass", "perc", "synth", "clap", "ohat", "perc_loop", "hat_loop"],
        ["atmos", "pad", "synth"],
        ["atmos", "pad", "synth", "chat", "shaker_loop", "snare_roll", "perc"],
        ["atmos", "pad", "kick", "chat", "shaker_loop", "bass", "perc", "synth"],
        ["atmos", "pad", "kick", "chat", "shaker_loop", "bass", "perc", "synth", "clap", "ohat", "perc_loop", "hat_loop", "tom", "perc_loop2"],
        ["atmos", "pad", "kick", "bass", "chat"]),
     patterns={"bass": {"beats": OFF8, "gain": 0.9, "pitch_cycle": [0, 0, 0, 0, 7, 7, 5, 5]},
               "synth": {"beats": [0, 1, 2, 3], "gain": 0.6, "pitch_cycle": [0, 3, 7, 3, 0, 5, 7, 10]}},
     duck=0.5, reverb=1.25))

_add(Style("melodic_techno", "Melodic Techno", "Techno", (120, 126),
     "Pads and arpeggios carry it. Long breakdowns, a rolling off-beat bass, hats kept subtle, big space.",
     _t(["atmos", "pad", "kick", "chat", "bass", "shaker_loop"],
        ["atmos", "pad", "kick", "chat", "bass", "shaker_loop"],
        ["atmos", "pad", "kick", "chat", "ohat", "bass", "synth", "shaker_loop", "clap", "perc_loop"],
        ["atmos", "pad", "synth", "bass"],
        ["atmos", "pad", "synth", "bass", "kick", "clap", "snare_roll", "chat"],
        ["atmos", "pad", "kick", "chat", "bass", "synth", "shaker_loop"],
        ["atmos", "pad", "kick", "chat", "ohat", "bass", "synth", "shaker_loop", "clap", "perc_loop", "perc", "hat_loop"],
        ["atmos", "pad", "kick", "bass"]),
     patterns={"bass": {"beats": OFF8, "gain": 0.9, "pitch_cycle": [0, 0, 0, 0, 0, 0, -2, -2]},
               "synth": {"beats": [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5], "gain": 0.6, "pitch_cycle": [0, 7, 12, 7, 0, 7, 12, 15]},
               "chat": {"beats": ALL16, "gain": 0.4, "accent": OFF8}, "clap": {"beats": [1, 3], "gain": 0.6}, "perc": {"beats": [3.5], "every": 2}},
     duck=0.6, reverb=1.5, vocal_sections=("Breakdown", "Drop 2")))

_add(Style("peak_techno", "Peak Techno", "Techno", (128, 140),
     "Kick first, always. A rumbling bass under everything, 16th hats, stabs only on the drops, short breaks.",
     _t(["kick", "chat", "atmos", "bass", "shaker_loop"],
        ["kick", "chat", "atmos", "bass", "shaker_loop"],
        ["kick", "chat", "ohat", "atmos", "bass", "shaker_loop", "perc_loop", "clap", "synth", "perc"],
        ["atmos", "synth", "chat", "bass"],
        ["atmos", "synth", "chat", "bass", "kick", "clap", "snare_roll"],
        ["kick", "chat", "atmos", "bass", "shaker_loop", "perc_loop"],
        ["kick", "chat", "ohat", "atmos", "bass", "shaker_loop", "perc_loop", "clap", "synth", "perc", "hat_loop", "perc_loop2", "tom"],
        ["kick", "chat", "bass", "atmos"]),
     patterns={"bass": {"beats": [b for b in ALL16 if b % 1 != 0], "gain": 0.8, "pitch_cycle": [0]},
               "chat": {"beats": ALL16, "gain": 0.6, "accent": OFF8}, "clap": {"beats": [1, 3], "gain": 0.6},
               "synth": {"beats": [0, 2.5], "gain": 0.7, "pitch_cycle": [0, 0, 0, 3]}, "perc": {"beats": [3.5], "every": 1, "gain": 0.7},
               "tom": {"beats": [2.75], "gain": 0.8, "every": 2}},
     duck=0.7, reverb=0.8, vocal_sections=("Breakdown",)))

_add(Style("minimal", "Minimal", "Techno", (122, 128),
     "As little as possible. Micro percussion, a bass of two notes, no pads, everything tight and dry.",
     _t(["kick", "chat", "bass", "perc"],
        ["kick", "chat", "bass", "perc"],
        ["kick", "chat", "bass", "perc", "clap", "shaker_loop", "synth"],
        ["atmos", "synth", "chat", "bass"],
        ["atmos", "synth", "chat", "bass", "kick", "snare_roll"],
        ["kick", "chat", "bass", "perc"],
        ["kick", "chat", "bass", "perc", "clap", "shaker_loop", "synth", "ohat", "perc_loop"],
        ["kick", "chat", "bass"]),
     patterns={"chat": {"beats": OFF8, "gain": 0.5, "accent": OFF8}, "clap": {"beats": [1, 3], "gain": 0.5}, "perc": {"beats": [2.75], "every": 1, "gain": 0.7},
               "bass": {"beats": [0.5, 2.5], "gain": 0.9, "pitch_cycle": [0, 0, 0, 0, 0, 0, 0, 3]},
               "synth": {"beats": [1.75], "every": 2, "gain": 0.6, "pitch_cycle": [0, 3]}, "ohat": {"beats": [1.5, 3.5], "gain": 0.6}},
     duck=0.5, reverb=0.6, vocal_sections=("Drop 2",)))

# backwards compatibility: older sessions and the CLI used 'afro'
ALIASES = {"afro": "afro_house", "techno": "peak_techno"}
DEFAULT = "house"


def get(key: str | None) -> Style:
    key = ALIASES.get(key or DEFAULT, key or DEFAULT)
    return STYLES.get(key, STYLES[DEFAULT])


def listing() -> list[dict]:
    return [{"key": s.key, "name": s.name, "group": s.group, "bpm": list(s.bpm), "blurb": s.blurb, "template": s.template,
             "vocal_sections": list(s.vocal_sections)} for s in STYLES.values()]
