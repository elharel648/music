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
    bars = {b for a, e in kick["spans"] for b in range(a, e)}
    brk = next(s for s in plan["sections"] if s["label"] == "Breakdown")
    drop = next(s for s in plan["sections"] if s["label"].startswith("Drop") or s["label"] == "Return")
    assert brk["start"] - 1 not in bars and not any(b in bars for b in range(brk["start"], brk["end"]))   # the kick leaves before the breakdown and stays out
    assert drop["start"] in bars                                                                        # and lands on the drop
    assert plan["locators"][0] == ("Intro", 1) and plan["locators"][-1][0] == "End"


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


def test_finish_parameter_mappings():
    from flow import finish
    # EQ Eight defaults: band 2 = 200 Hz sits at 0.389, band 8 = 18 kHz at 0.974 (read back from Live 12)
    assert abs(finish.eq8_freq(200) - 0.3892) < 0.002
    assert abs(finish.eq8_freq(18000) - 0.9739) < 0.002
    assert finish.eq8_freq(10) == 0.0 and finish.eq8_freq(22000) == 1.0
    assert finish.utility_gain(0) == 0.0 and finish.utility_gain(-35) == -1.0 and abs(finish.utility_gain(-3) + 0.0857) < 0.001
    assert finish.reverb_decay(200) == 0.0 and abs(finish.reverb_decay(4000) - 0.525) < 0.002


def test_styles_library_consistent():
    from flow import styles, patterns
    assert len(styles.STYLES) >= 8
    for st in styles.STYLES.values():
        assert set(st.template) == set(styles.SECTIONS), st.key
        for roles in st.template.values():
            assert set(roles) <= styles.ROLES, (st.key, roles)
        for role, pat in st.patterns.items():
            assert role in patterns.PATTERNS, (st.key, role)
            assert set(pat) <= {"beats", "gain", "accent", "every", "pitch_cycle"}, (st.key, role)
        assert st.bpm[0] < st.bpm[1] and 0 < st.duck <= 1 and set(st.vocal_sections) <= set(styles.SECTIONS)
    assert styles.get("afro").key == "afro_house" and styles.get("nope").key == "melodic_techno" and styles.get(None).key == "melodic_techno"
    assert [s["key"] for s in styles.listing()] == list(styles.STYLES)


def test_pattern_for_overrides_and_midi():
    from flow import patterns
    assert patterns.pattern_for("chat", "tech_house")["beats"] != patterns.PATTERNS["chat"]["beats"]
    assert patterns.pattern_for("kick", "tech_house") == patterns.PATTERNS["kick"]
    assert patterns.pattern_for("bass", None) == patterns.PATTERNS["bass"]
    assert len(patterns.midi_notes("synth", 0, 4, style="minimal")) == 2   # every 2nd bar, one hit
    assert len(patterns.midi_notes("bass", 0, 4, style="peak_techno")) == 48


def test_vocal_phrases_and_time_stretch():
    import numpy as np
    from flow import vocal, audio
    sr = 22050
    t = np.arange(sr * 6) / sr
    y = np.zeros_like(t)
    for a, b in ((0.5, 1.6), (3.0, 4.3)):
        m = (t >= a) & (t < b)
        y[m] = 0.5 * np.sin(2 * np.pi * 220 * t[m])
    ph = vocal.split_phrases(y.astype(np.float32), sr)
    assert len(ph) == 2 and abs(ph[0][0] - 0.5) < 0.1 and abs(ph[1][1] - 4.3) < 0.2
    st = audio.time_stretch(np.vstack([y, y]).astype(np.float32), 1.1)
    assert st.shape[0] == 2 and abs(st.shape[1] / len(y) - 1.1) < 0.03


def test_place_vocal_respects_sections_and_style():
    from flow import arrange
    sections = [{"label": "Intro", "start": 1, "end": 17, "bars": 16}, {"label": "Drop", "start": 17, "end": 49, "bars": 32},
                {"label": "Breakdown", "start": 49, "end": 65, "bars": 16}]
    voc = {"name": "v.wav", "phrases": [{"path": "a.wav", "bars": 2, "seconds": 3.8}, {"path": "b.wav", "bars": 4, "seconds": 7.6}]}
    pl = arrange.place_vocal(sections, voc, "house")
    assert pl
    for p in pl:
        assert any(s["start"] <= p["bar"] and p["bar"] + p["bars"] <= s["end"] and s["label"] in ("Drop", "Breakdown") for s in sections)
    assert not any(17 <= p["bar"] < 25 for p in pl)                       # the drop lands first
    assert sum(p["bars"] for p in pl if 17 <= p["bar"] < 49) <= 32 * 0.5  # drops are not wall-to-wall vocal
    peak = arrange.place_vocal(sections, voc, "peak_techno")
    assert peak and all(p["bar"] >= 49 for p in peak)                     # peak techno: breakdown only


def test_update_manifest_signature_and_versions():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from flow import update
    priv = Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    man = update.sign_manifest(priv, "0.7.0", "https://example.com/FLOW-0.7.0.dmg", "Styles and vocal")
    assert update.evaluate(man, current="0.6.0", public_key_hex=pub_hex)["available"] is True
    assert update.evaluate(man, current="0.7.0", public_key_hex=pub_hex)["available"] is False
    assert update.evaluate(man, current="1.0", public_key_hex=pub_hex)["available"] is False
    tampered = dict(man, url="https://evil.example/FLOW.dmg")
    assert update.evaluate(tampered, current="0.6.0", public_key_hex=pub_hex)["available"] is False
    other = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    assert update.evaluate(man, current="0.6.0", public_key_hex=other)["available"] is False
    plain = update.sign_manifest(priv, "0.7.0", "http://example.com/x.dmg", "")
    assert update.evaluate(plain, current="0.6.0", public_key_hex=pub_hex)["available"] is False   # https only
    assert update.check("http://127.0.0.1:9/nothing", timeout=0.5) is None                         # network failure is silent


def test_short_reference_falls_back_to_typical_structure():
    from flow import arrange
    short = {"bars": 26, "sections": [{"label": "Intro", "start": 1, "end": 5, "bars": 4, "kick_ratio": 0}, {"label": "Drop", "start": 5, "end": 27, "bars": 22, "kick_ratio": 1}]}
    secs, note = arrange.reference_sections(short)
    assert note and len(secs) == 7 and secs[0]["label"] == "Intro" and secs[-1]["end"] == 145
    full = {"bars": 144, "sections": [{"label": l, "start": 1, "end": 2, "bars": 1} for l in ("Intro", "Drop", "Outro")]}
    assert arrange.reference_sections(full)[1] is None
    typ, note2 = arrange.reference_sections(full, "typical")
    assert note2 is None and len(typ) == 7


def _fake_pack(tmp_path):
    import numpy as np
    from flow import audio
    sr = 22050
    samples = []
    by_role = {}
    rng = np.random.default_rng(1)
    for role, n, dur in (("kick", 3, 0.4), ("clap", 2, 0.3), ("bass", 2, 0.6)):
        for i in range(n):
            p = str(tmp_path / f"{role}{i}.wav")
            y = (rng.standard_normal((1, int(sr * dur))) * 0.3).astype("float32")
            audio.write(p, y, sr)
            s = {"path": p, "name": f"{role}{i}.wav", "rel": f"{role}{i}.wav", "role": role, "duration": dur, "bpm": None, "key": None, "is_loop": False}
            samples.append(s)
            by_role.setdefault(role, []).append(s)
    return {"samples": samples, "_by_role": by_role, "count": len(samples)}


def test_candidates_overrides_and_kit_view(tmp_path):
    from flow import pack
    pk = _fake_pack(tmp_path)
    cands = pack.candidates(pk, 124)
    assert set(cands) == {"kick", "clap", "bass"} and len(cands["kick"]) == 3
    kit = pack.choose_kit(pk, 124, cands=cands)
    assert kit["kick"]["path"] == cands["kick"][0]["path"]
    other = cands["kick"][2]["path"]
    assert pack.choose_kit(pk, 124, {"kick": other}, cands)["kick"]["path"] == other
    assert "clap" not in pack.choose_kit(pk, 124, {"clap": ""}, cands)            # the user took the role out
    rows = pack.kit_view(pk, 124, {"kick": other}, cands)
    assert [r["role"] for r in rows] == ["kick", "clap", "bass"] and rows[0]["chosen"]["path"] == other and rows[0]["label"] == "Kick"


def test_render_mix_length_and_level(tmp_path):
    import numpy as np, soundfile as sf
    from flow import export, audio
    p = str(tmp_path / "k.wav")
    audio.write(p, (np.ones((1, 2205)) * 0.5).astype("float32"), 22050)
    plan = {"bpm": 120, "bars": 4, "tracks": [{"name": "Kick", "role": "kick", "kind": "audio", "spans": [[1, 5]], "clip_bars": 1, "source": {"path": p, "kind": "oneshot", "bars": None}}]}
    out = str(tmp_path / "mix.wav")
    r = export.render_mix(plan, out, sr=22050, tail_s=1.0)
    info = sf.info(out)
    assert abs(info.frames / info.samplerate - (4 * 2 + 1)) < 0.01 and info.subtype == "PCM_16" and r["bars"] == 4
    y, _ = audio.load(out)
    assert 0.85 < float(np.abs(y).max()) <= 0.9


def test_media_server_serves_only_registered_files_with_ranges(tmp_path):
    import urllib.request, urllib.error
    from flow.app import MediaServer
    f = tmp_path / "a.wav"
    f.write_bytes(bytes(range(256)) * 4)
    srv = MediaServer()
    try:
        url = srv.register(str(f))
        assert url.startswith("http://127.0.0.1:") and url == srv.register(str(f))
        with urllib.request.urlopen(url, timeout=3) as r:
            assert r.status == 200 and len(r.read()) == 1024 and r.headers["Accept-Ranges"] == "bytes"
        req = urllib.request.Request(url, headers={"Range": "bytes=100-199"})
        with urllib.request.urlopen(req, timeout=3) as r:
            body = r.read()
            assert r.status == 206 and len(body) == 100 and body[0] == 100 and r.headers["Content-Range"] == "bytes 100-199/1024"
        try:
            urllib.request.urlopen(url.rsplit("/", 1)[0] + "/deadbeef", timeout=3)
            assert False, "unregistered token must 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.close()


def test_normalize_sections_adds_breakdown_and_trims_intro():
    from flow import arrange
    secs = [{"label": "Intro", "start": 1, "end": 45, "bars": 44, "kick_ratio": .98}, {"label": "Drop", "start": 45, "end": 65, "bars": 20, "kick_ratio": .85},
            {"label": "Drop 2", "start": 65, "end": 77, "bars": 12, "kick_ratio": 1.0}, {"label": "Drop 3", "start": 77, "end": 81, "bars": 4, "kick_ratio": .75}]
    out, notes = arrange.normalize_sections(secs)
    labels = [x["label"] for x in out]
    assert labels[0] == "Intro" and out[0]["bars"] == 16 and labels[1] == "Groove"
    assert "Breakdown" in labels and "Build" in labels and labels.index("Breakdown") < max(i for i, l in enumerate(labels) if l.startswith("Drop"))
    assert all(x["bars"] >= 8 for x in out) and notes
    assert sum(x["bars"] for x in out) == 80 and all(out[i]["end"] == out[i + 1]["start"] for i in range(len(out) - 1))


def test_shape_layers_breathes():
    from flow import arrange
    secs = [{"label": "Intro", "start": 1, "end": 17, "bars": 16, "kick_ratio": 1}, {"label": "Groove", "start": 17, "end": 49, "bars": 32, "kick_ratio": 1},
            {"label": "Drop", "start": 49, "end": 81, "bars": 32, "kick_ratio": 1}]
    wanted = {"atmos": secs, "kick": secs, "shaker_loop": secs, "perc": secs[1:], "bass": secs[1:], "hat_loop": secs[2:], "ohat": secs[2:]}
    sp = arrange.shape_layers(wanted, secs, 80)
    assert sp["atmos"][0][0] == 1 and sp["kick"][0][0] == 9            # the kick waits 8 bars in the intro
    assert sp["ohat"][0][0] == 57                                        # late layers join the drop 8 bars in
    kick_bars = {b for a, e in sp["kick"] for b in range(a, e)}
    assert 32 not in kick_bars and 48 not in kick_bars and 64 not in kick_bars   # phrase breaths and the bar before the drop
    assert 33 in kick_bars and 49 in kick_bars


def test_techno_profile_measured_rules():
    """Techno (158 tracks he plays + 25 pro sets): kick, hats and percussion from bar 1, bass/synth 16 bars later,
    the kick leaves for the whole break, no silent bar before the drop, intros capped like house."""
    from flow import arrange, profiles
    secs = [{"label": "Intro", "start": 1, "end": 17, "bars": 16, "kick_ratio": 1}, {"label": "Groove", "start": 17, "end": 49, "bars": 32, "kick_ratio": 1},
            {"label": "Drop", "start": 49, "end": 81, "bars": 32, "kick_ratio": 1},
            {"label": "Breakdown", "start": 81, "end": 97, "bars": 16, "kick_ratio": 0}, {"label": "Drop 2", "start": 97, "end": 129, "bars": 32, "kick_ratio": 1}]
    wanted = {"atmos": secs, "kick": secs[:3] + secs[4:], "chat": secs, "bass": secs[1:], "synth": secs[1:], "ohat": secs[2:3] + secs[4:]}
    sp = arrange.shape_layers(wanted, secs, 128, profiles.TECHNO)
    kick = {b for a, e in sp["kick"] for b in range(a, e)}
    assert sp["kick"][0][0] == 1 and sp["chat"][0][0] == 1              # DJ intro: kick and hats from bar 1
    assert sp["bass"][0][0] == 33 and sp["synth"][0][0] == 33           # the second group waits a 16-bar phrase into the groove
    assert sp["ohat"][0][0] == 57                                        # late layers 8 bars into the drop
    assert not any(b in kick for b in range(81, 97)) and 80 in kick and 97 in kick   # the kick leaves for the break, no silent bar before it
    out, _ = arrange.normalize_sections([{"label": "Intro", "start": 1, "end": 41, "bars": 40, "kick_ratio": 1}, {"label": "Drop", "start": 41, "end": 73, "bars": 32, "kick_ratio": 1},
                                         {"label": "Breakdown", "start": 73, "end": 89, "bars": 16, "kick_ratio": 0}, {"label": "Drop 2", "start": 89, "end": 121, "bars": 32, "kick_ratio": 1}], profiles.TECHNO)
    assert out[0]["bars"] == 16 and out[1]["label"] == "Groove"          # a 40-bar intro becomes 16 + groove
