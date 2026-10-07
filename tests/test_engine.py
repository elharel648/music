import os
import datetime as dt
import numpy as np
import pytest

from flow import analysis, arrange, patterns, export, license as lic

OASIS = "/Users/harel/Desktop/הפקה/tps/TPS - Oasis/TPS - Oasis - Project Files/TPS - Oasis - Project File 01.mp3"


def _fake_ref(bars=72):
    secs = [{"start": 1, "end": 17, "label": "Intro", "kick_ratio": 1.0}, {"start": 17, "end": 33, "label": "Drop", "kick_ratio": 1.0},
            {"start": 33, "end": 49, "label": "Breakdown", "kick_ratio": 0.0}, {"start": 49, "end": 73, "label": "Drop 2", "kick_ratio": 1.0}]
    return {"file": "fake.wav", "bpm": 120.0, "bars": bars, "key": {"tonic": "C", "pc": 0, "mode": "minor", "confidence": 0.9}, "sections": secs}


def test_bpm_and_key_from_name():
    assert analysis.bpm_from_name("Loop 03 (120 BPM).wav") == 120
    assert analysis.key_from_name("Atmosphere 04 Amin.wav") == (9, "minor")
    assert analysis.key_from_name("Bass Shot 01 C.wav") == (0, "unknown")
    assert analysis.key_from_name("Kick 17.wav") is None


def test_scale_sections_sums_and_phrases():
    ref = _fake_ref()
    out = arrange.scale_sections(ref["sections"], 120)
    assert sum(s["bars"] for s in out) == 120
    assert all(s["bars"] % 4 == 0 for s in out)
    assert out[0]["start"] == 1 and out[-1]["end"] == 121


def test_scale_caps_tension_sections():
    secs = [{"start": 1, "end": 17, "label": "Intro"}, {"start": 17, "end": 33, "label": "Drop"},
            {"start": 33, "end": 41, "label": "Breakdown"}, {"start": 41, "end": 49, "label": "Build"}, {"start": 49, "end": 73, "label": "Drop 2"}]
    out = arrange.scale_sections(secs, 176)
    by = {s["label"]: s["bars"] for s in out}
    assert by["Build"] <= 16 and by["Breakdown"] <= 32
    assert sum(s["bars"] for s in out) == 176


def test_target_bars():
    assert arrange.target_bars(None, 120, 72) == 72
    assert arrange.target_bars(6 * 60 + 30, 128, 72) == 208  # 390 s at 128 BPM ≈ 208 bars
    assert arrange.target_bars(30, 120, 72) == 64             # never under two minutes
    assert arrange.target_bars(None, 120, 20) == 64


def test_parse_length():
    from flow.cli import parse_length
    assert parse_length("6:30") == 390 and parse_length("3") == 180 and parse_length("3.5") == 210
    assert parse_length("390") == 390 and parse_length(270) == 270 and parse_length("") is None


def test_build_plan_kick_drops_before_break(tmp_path):
    ref = _fake_ref()
    kit = {"kick": {"path": "x", "name": "Kick.wav", "duration": 0.4, "is_loop": False}}
    loops = {"kick": {"path": "k.wav", "bars": 4, "source": "Kick.wav"}}
    plan = arrange.build_plan(ref, kit, loops, length_seconds=None)
    kick = [t for t in plan["tracks"] if t["role"] == "kick"][0]
    assert kick["spans"] == [(1, 32), (49, 73)]  # kick leaves one bar before the breakdown
    assert plan["locators"][0] == ("Intro", 1) and plan["locators"][-1] == ("End", 73)


def test_midi_notes_in_key():
    notes = patterns.midi_notes("bass", tonic_pc=1, bars=4)  # C#
    assert notes[0]["pitch"] == 37 and len(notes) == 16
    assert all(n["start_time"] < 16 for n in notes)


def test_midi_file_writes(tmp_path):
    ref = _fake_ref()
    kit = {"kick": {"path": "x", "name": "Kick.wav", "duration": 0.4, "is_loop": False}}
    loops = {"kick": {"path": "k.wav", "bars": 4, "source": "Kick.wav"}}
    plan = arrange.build_plan(ref, kit, loops, midi_roles={})
    p = export.write_midi(plan, str(tmp_path / "m.mid"))
    data = open(p, "rb").read()
    assert data[:4] == b"MThd" and b"MTrk" in data and b"Breakdown" in data


def test_license_roundtrip(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    monkeypatch.setattr(lic, "data_dir", lambda: str(tmp_path))
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    monkeypatch.setattr(lic, "PUBLIC_KEY_HEX", pub)
    key = lic.issue_key(priv, "dj@example.com")
    assert lic.verify_key(key)["email"] == "dj@example.com"
    with pytest.raises(ValueError):
        lic.verify_key(key[:-3] + "AAA")
    s = lic.status()
    assert s["state"] == "trial" and s["days_left"] == 14
    lic.activate(key)
    assert lic.status()["state"] == "licensed"
    # expired key (expiry date in the past)
    old = lic.issue_key(priv, "x@y", days=-1)
    with pytest.raises(ValueError):
        lic.verify_key(old)


@pytest.mark.skipif(not os.path.exists(OASIS), reason="Oasis reference not on this machine")
def test_oasis_reference_structure():
    r = analysis.analyze_reference(OASIS)
    assert r["bpm"] == 120
    assert r["key"]["tonic"] == "C#" and r["key"]["mode"] == "minor"
    starts = [s["start"] for s in r["sections"]]
    for must in (17, 33, 49):
        assert any(abs(s - must) <= 1 for s in starts), starts
    assert r["bars"] in (72, 73)


def test_transition_sweeps_cut_spans(tmp_path):
    from flow import transitions
    import numpy as np, soundfile as sf
    loop = tmp_path / "loop.wav"
    sf.write(str(loop), np.random.uniform(-0.3, 0.3, (48000 * 8, 2)).astype("float32"), 48000)  # 4 bars at 120
    plan = {"bpm": 120.0, "sections": [{"label": "Intro", "start": 1, "end": 17}, {"label": "Drop", "start": 17, "end": 49}],
            "tracks": [{"name": "Hat Loop · x", "role": "hat_loop", "kind": "audio", "clip_bars": 4, "spans": [(1, 49)], "source": {"path": str(loop), "kind": "loop"}}]}
    n = transitions.add_sweeps(plan, str(tmp_path))
    t = plan["tracks"][0]
    assert n == 1 and t["spans"] == [(1, 9), (17, 49)] and t["sweeps"][0][0] == 9
    y, sr = sf.read(t["sweeps"][0][1])
    assert abs(len(y) / sr - 16.0) < 0.01  # 8 bars at 120 BPM


def test_finish_options_shape():
    from flow import finish
    keys = {k for k, _, _ in finish.OPTIONS}
    assert finish.DEFAULT_ON <= keys and "transitions" in keys


def test_plan_view_shape():
    ref = _fake_ref()
    kit = {"kick": {"path": "x", "name": "Kick.wav", "duration": 0.4, "is_loop": False}}
    loops = {"kick": {"path": "k.wav", "bars": 4, "source": "Kick.wav"}}
    plan = arrange.build_plan(ref, kit, loops)
    v = arrange.plan_view(plan)
    assert v["bars"] == 72 and v["layers"][0]["i"] == 0 and v["layers"][0]["role"] == "kick"
    assert all(isinstance(a, int) and isinstance(b, int) for a, b in v["layers"][0]["spans"])
    import json
    json.dumps(v)  # must be serializable for the UI
