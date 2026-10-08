"""How a style's arrangement breathes: measured from real sets, not guessed.

TECHNO comes from 25 professional techno / melodic techno Live Sets (PML bundle, Barbour Comino, Berlin Techno, Anyma;
read offline with tools/corpus.py, 2026-10): kick at bar 17 of a 32-bar intro, hats/claps/synths joining 16 bars after
the kick, 16-bar breaks that keep the bass and the synth and bring the kick back halfway, builds that are a density
ramp with the kick in (90%), no silent bars anywhere. HOUSE is the earlier hand-written behaviour until a house corpus
is measured.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    key: str
    intro_split: tuple[int, int]      # an intro longer than [0] becomes an Intro of [1] bars + a Groove
    intro_kick_frac: float            # the kick waits this fraction of an Intro of 16+ bars (rounded to 4 bars)
    entry_phrase: int                 # new layer groups join this many bars apart in grooves and drops
    entry_groups: tuple[frozenset, ...]
    break_kick: str                   # "out" (kick leaves), "half" (kick returns halfway through the break)
    silent_before_drop: bool          # kick and bass skip the bar before a drop / break
    caps: dict[str, int]              # section lengths that do not grow with the track
    source: str

    def group_of(self, role: str) -> int:
        for i, g in enumerate(self.entry_groups):
            if role in g:
                return i
        return len(self.entry_groups) - 1


HOUSE = Profile(
    key="house", intro_split=(24, 16), intro_kick_frac=0.5, entry_phrase=8,
    entry_groups=(frozenset({"atmos", "pad", "kick"}), frozenset({"chat", "shaker_loop", "perc", "tom", "bass"}),
                  frozenset({"hat_loop", "perc_loop", "synth", "clap"}), frozenset({"tom_b", "tom_c", "ohat", "perc_loop2", "snare_roll"})),
    break_kick="out", silent_before_drop=True, caps={"Build": 16, "Breakdown": 32, "Intro": 24, "Outro": 24},
    source="hand-written; measure a house corpus before trusting it")

TECHNO = Profile(
    key="techno", intro_split=(32, 32), intro_kick_frac=0.5, entry_phrase=16,
    entry_groups=(frozenset({"atmos", "pad", "kick", "bass", "perc", "tom", "shaker_loop"}),
                  frozenset({"chat", "hat_loop", "clap", "synth", "perc_loop"}),
                  frozenset({"ohat", "perc_loop2", "tom_b", "tom_c", "snare_roll"})),
    break_kick="half", silent_before_drop=False, caps={"Build": 16, "Breakdown": 16, "Intro": 32, "Outro": 16},
    source="25 professional techno Live Sets, tools/corpus.py, 2026-10-08")

BY_GROUP = {"House": HOUSE, "Techno": TECHNO}


def for_style(style) -> Profile:
    return BY_GROUP.get(getattr(style, "group", ""), HOUSE)
