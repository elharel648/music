"""Finish moves: make the built set sound like one continuous track using the DAW's own devices.

Every move is optional (the user picks), parameter names are looked up at runtime so a missing
parameter degrades to a warning instead of a crash. No DSP is written here: Ableton's devices do the work.
"""
from __future__ import annotations
from typing import Callable
from . import styles as stylelib

OPTIONS = [
    ("gain", "Gain staging", "Every track at a sensible level relative to the kick, with Utility."),
    ("lowcut", "Clean low end", "A high-pass on everything that is not kick or bass, so the low end stays clear."),
    ("duck", "Sidechain pump", "Your sidechain plug-in on every track except the kick; without one, Ableton's Auto Pan does the ducking."),
    ("space", "Space", "Reverb on pads, atmospheres, claps and synth; a short delay on the synth."),
    ("glue", "Drum glue", "Drum Buss on claps, percussion and toms for weight and punch."),
    ("transitions", "Transition sweeps", "The eight bars before each drop get a rising high-pass sweep on every loop."),
]
DEFAULT_ON = {"gain", "lowcut", "duck", "space", "glue", "transitions"}

# starting balance in dB relative to the kick (0). A starting point, not a mix.
GAIN_DB = {"kick": 0, "bass": -3, "clap": -6, "snare_roll": -8, "chat": -12, "ohat": -12, "hat_loop": -11, "shaker_loop": -12,
           "perc": -9, "perc_loop": -9, "perc_loop2": -10, "tom": -8, "tom_b": -9, "tom_c": -9, "synth": -8, "pad": -14, "atmos": -14,
           "impact": -6, "uplifter": -8, "downlifter": -8, "vocal": -5}
LOWCUT_HZ = {"clap": 180, "snare_roll": 150, "chat": 300, "ohat": 300, "hat_loop": 250, "shaker_loop": 250, "perc": 150, "perc_loop": 140,
             "perc_loop2": 140, "tom": 90, "tom_b": 90, "tom_c": 90, "synth": 160, "pad": 200, "atmos": 200, "impact": 60,
             "uplifter": 200, "downlifter": 120, "vocal": 150}
SPACE = {"vocal": ("reverb", 0.22, 1.8), "pad": ("reverb", 0.28, 4.0), "atmos": ("reverb", 0.30, 5.0), "clap": ("reverb", 0.18, 1.6), "synth": ("delay", 0.16, None), "tom": ("reverb", 0.12, 1.2)}
GLUE_ROLES = {"clap", "perc", "perc_loop", "perc_loop2", "tom", "tom_b", "tom_c", "shaker_loop", "hat_loop"}
NO_DUCK = {"kick", "impact", "uplifter", "downlifter", "snare_roll"}

# Live's API exposes most device parameters normalized (0..1 or -1..1); these map real units onto that.
# Verified against EQ Eight's default band frequencies (40/200/1000/5000/100/10000/5000/18000 Hz) and Utility's Bass Freq (120 Hz in 50..500).
import math


def eq8_freq(hz: float) -> float:
    """EQ Eight frequency: 10 Hz..22 kHz, logarithmic, as 0..1."""
    return min(1.0, max(0.0, math.log(hz / 10.0) / math.log(2200.0)))


def utility_gain(db: float) -> float:
    """Utility Gain: -35..+35 dB as -1..1 (0 = 0 dB)."""
    return min(1.0, max(-1.0, db / 35.0))


def reverb_decay(ms: float) -> float:
    """Reverb Decay Time: 200 ms..60 s, logarithmic, as 0..1."""
    return min(1.0, max(0.0, math.log(ms / 200.0) / math.log(300.0)))


AUTOPAN_QUARTER = 7.0  # index into Live's beat-division list: 8,4,2,1,1/2,1/2T,1/2D,1/4,...

URIS = {
    "utility": "query:AudioFx#Utility", "eq8": "query:AudioFx#EQ%20Eight", "autopan": "query:AudioFx#Auto%20Pan",
    "reverb": "query:AudioFx#Reverb", "delay": "query:AudioFx#Delay", "drumbuss": "query:AudioFx#Drum%20Buss",
}


def apply(live, plan: dict, base_index: int, options: set[str], sidechain: str | None, progress: Callable[[str, float], None] | None = None) -> list[str]:
    """Apply the chosen moves to the tracks FLOW built (plan['tracks'][i] lives at track base_index + i)."""
    prog = progress or (lambda m, p: None)
    warnings: list[str] = []
    tracks = plan["tracks"]
    n = max(1, len(tracks))
    st = stylelib.get(plan.get("style"))
    sc_uri = live.find_plugin(sidechain) if (sidechain and "duck" in options) else None
    if "duck" in options and sidechain and not sc_uri:
        warnings.append(f"Sidechain plug-in {sidechain} not found in Live's browser; using Auto Pan instead.")

    for i, t in enumerate(tracks):
        ti = base_index + i
        role = t["role"]
        prog(f"Finish: {t['name']}", i / n)
        try:
            if "gain" in options and role in GAIN_DB and GAIN_DB[role] != 0:
                d = live.add_device(ti, URIS["utility"])
                live.set_param(ti, d, "Gain", utility_gain(GAIN_DB[role]))
            if "lowcut" in options and role in LOWCUT_HZ:
                d = live.add_device(ti, URIS["eq8"])
                live.set_param(ti, d, "1 Filter On A", 1.0)
                live.set_param(ti, d, "1 Filter Type A", 1.0)      # 12 dB low cut (0 = 48 dB)
                live.set_param(ti, d, "1 Frequency A", eq8_freq(LOWCUT_HZ[role]))
            if "duck" in options and role not in NO_DUCK:
                if sc_uri:
                    live.add_device(ti, sc_uri)
                else:
                    d = live.add_device(ti, URIS["autopan"])
                    live.set_param(ti, d, "Waveform", 2.0)        # saw down: dip on the beat, recover before the next
                    live.set_param(ti, d, "Phase", 180.0)         # both channels together: volume, not panning
                    live.set_param(ti, d, "Amount", float(st.duck))
                    live.set_param(ti, d, "LFO Type", 1.0)        # sync to the beat
                    live.set_param(ti, d, "Sync Rate", AUTOPAN_QUARTER)
                    live.set_param(ti, d, "Shape", 0.5)
            if "space" in options and role in SPACE:
                kind, wet, decay = SPACE[role]
                d = live.add_device(ti, URIS["reverb" if kind == "reverb" else "delay"])
                live.set_param(ti, d, "Dry/Wet", min(0.5, float(wet) * (st.reverb if kind == "reverb" else 1.0)))
                if decay:
                    live.set_param(ti, d, "Decay Time", reverb_decay(decay * 1000.0 * st.reverb))
            if "glue" in options and role in GLUE_ROLES:
                d = live.add_device(ti, URIS["drumbuss"])
                live.set_param(ti, d, "Drive", 0.25)
                live.set_param(ti, d, "Dry/Wet", 0.7)
        except Exception as e:  # one failing move never kills the build
            warnings.append(f"{t['name']}: {e}")
    prog("Finish: done", 1.0)
    return warnings
