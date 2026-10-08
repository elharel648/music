"""How a style's arrangement breathes: measured from real sets, not guessed.

TECHNO is measured twice. 158 finished techno tracks Harel plays (tools/corpus_audio.py, 2026-10): the kick is there
from bar 1 in 79% of them (DJ intros: kick + hats + percussion, 16 bars), 2 kick-less breaks per track of 8-16 bars,
the first around bar 33-43, breaks 8 dB under the drops, drops 24 bars, no silent bars. 25 professional Live Sets
(tools/corpus.py) give what happens inside the sections: bass, synths and pads stay through a break, the next layer
group joins 16 bars after the kick, builds carry the kick. Where the two disagree (studio intros wait 16 bars for the
kick; DJ mixes do not) the tracks he plays win. HOUSE is the earlier hand-written behaviour until a house corpus is
measured.
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
    build_kick: bool                  # the build carries the kick even when the reference's build does not
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
    break_kick="out", build_kick=False, silent_before_drop=True, caps={"Build": 16, "Breakdown": 32, "Intro": 24, "Outro": 24},
    source="hand-written; measure a house corpus before trusting it")

TECHNO = Profile(
    key="techno", intro_split=(24, 16), intro_kick_frac=0.0, entry_phrase=16,
    entry_groups=(frozenset({"atmos", "kick", "chat", "shaker_loop", "perc", "hat_loop"}),
                  frozenset({"pad", "bass", "clap", "synth", "perc_loop", "tom"}),
                  frozenset({"ohat", "perc_loop2", "tom_b", "tom_c", "snare_roll"})),
    break_kick="out", build_kick=True, silent_before_drop=False, caps={"Build": 16, "Breakdown": 16, "Intro": 24, "Outro": 16},
    source="158 techno tracks Harel plays (DJ extended mixes), tools/corpus_audio.py, 2026-10-08; "
           "layer order inside sections from 25 professional Live Sets, tools/corpus.py")

BY_GROUP = {"House": HOUSE, "Techno": TECHNO}


def for_style(style) -> Profile:
    return BY_GROUP.get(getattr(style, "group", ""), HOUSE)
