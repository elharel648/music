"""Generate flow/bridge/Alma/__init__.py: the Alma Ableton bridge, forked from AbletonMCP (MIT, Siddharth Ahuja).

  python tools/make_bridge.py "/path/to/AbletonMCP/__init__.py"

Changes vs. upstream: port 9878, binds to 127.0.0.1 only, Alma naming, and commands for mixer volume/pan/sends,
master-track devices and parameters. Everything else is upstream code; the MIT notice is kept.
"""
from __future__ import annotations
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "flow", "bridge", "Alma", "__init__.py")
sys.path.insert(0, ROOT)
from flow.ableton_bridge import BRIDGE_VERSION as ALMA_BRIDGE_VERSION  # single source of truth

NOTICE = '''# Alma Bridge for Ableton Live — a Remote Script that lets the Alma desktop app build arrangements in the Set in front.
# Forked from AbletonMCP by Siddharth Ahuja (https://github.com/ahujasid/ableton-mcp), MIT License:
#   Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
#   documentation files (the "Software"), to deal in the Software without restriction... THE SOFTWARE IS PROVIDED
#   "AS IS", WITHOUT WARRANTY OF ANY KIND. (Full text: https://opensource.org/licenses/MIT)
# Alma additions (c) 2026 Harel Eliyahu. Listens on 127.0.0.1:9878 only.
'''

MAIN_THREAD_ADD = '"create_locator", "set_track_volume", "set_track_pan", "set_send", "load_on_master", "set_master_parameter", "replace_track_clips", "delete_tracks_by_name", "clear_locators"]:'

DISPATCH_ADD = '''                        elif command_type == "set_track_volume":
                            result = self._set_track_volume(params.get("track_index", 0), params.get("db", 0.0))
                        elif command_type == "set_track_pan":
                            result = self._set_track_pan(params.get("track_index", 0), params.get("pan", 0.0))
                        elif command_type == "set_send":
                            result = self._set_send(params.get("track_index", 0), params.get("send_index", 0), params.get("value", 0.0))
                        elif command_type == "load_on_master":
                            result = self._load_on_master(params.get("uri", ""))
                        elif command_type == "replace_track_clips":
                            result = self._replace_track_clips(params.get("track_index", 0), params.get("path", ""), params.get("spans", []),
                                                               params.get("clip_bars", 4), params.get("hits", []), params.get("sweeps", []), params.get("name"))
                        elif command_type == "delete_tracks_by_name":
                            result = self._delete_tracks_by_name(params.get("names", []))
                        elif command_type == "clear_locators":
                            result = self._clear_locators(params.get("names", []))
                        elif command_type == "set_master_parameter":
                            result = self._set_master_parameter(params.get("device_index", 0), params.get("parameter_index", 0), params.get("value", 0.0))
                        elif command_type == "set_tempo":'''

READ_ADD = '''            elif command_type == "get_master_parameters":
                response["result"] = self._get_master_parameters(params.get("device_index", 0))
            elif command_type == "get_track_info":'''

METHODS = '''
    # ---- Alma additions -------------------------------------------------
    def _delete_tracks_by_name(self, names):
        """Remove the tracks a previous Alma build wrote, found by their exact names so the user's own tracks are never touched."""
        wanted = set(str(n) for n in names)
        idx = [i for i, t in enumerate(self._song.tracks) if t.name in wanted]
        for i in reversed(idx):
            self._song.delete_track(i)
        return {"deleted": len(idx)}

    def _clear_locators(self, names):
        """Remove cue points whose names Alma wrote (Intro, Drop, Breakdown...). Live has no delete call: jump to the cue and toggle."""
        wanted = set(str(n) for n in names)
        song = self._song
        original = song.current_song_time
        removed = 0
        for cue in [c for c in song.cue_points if c.name in wanted]:
            song.current_song_time = cue.time
            song.set_or_delete_cue()
            removed += 1
        try:
            song.current_song_time = original
        except Exception:
            pass
        return {"removed": removed}

    def _replace_track_clips(self, track_index, path, spans, clip_bars, hits, sweeps, name):
        """Swap one track's sound after a build: drop every arrangement clip on the track, import the new file into
        slot 0 (the sweep into slot 1) and lay it out again on the same bars. Devices, volume and routing stay."""
        track = self._song.tracks[track_index]
        if not hasattr(track, "delete_clip"):
            raise Exception("Track.delete_clip is unavailable in this Live version (needs Live 11 or newer)")
        for clip in list(track.arrangement_clips):
            track.delete_clip(clip)
        for i in (0, 1):
            if i < len(track.clip_slots) and track.clip_slots[i].has_clip:
                track.clip_slots[i].delete_clip()
        slot = track.clip_slots[0]
        slot.create_audio_clip(path)
        clip = slot.clip
        step = max(1, int(clip_bars or 4))
        n = 0
        for s, e in spans:
            b = s
            while b < e:
                track.duplicate_clip_to_arrangement(clip, (b - 1) * 4.0)
                b += step
                n += 1
        for hb in hits or []:
            track.duplicate_clip_to_arrangement(clip, (float(hb) - 1) * 4.0)
            n += 1
        if sweeps:
            track.clip_slots[1].create_audio_clip(sweeps[0][1])
            sw = track.clip_slots[1].clip
            for sb, _p in sweeps:
                track.duplicate_clip_to_arrangement(sw, (float(sb) - 1) * 4.0)
                n += 1
        if name:
            track.name = str(name)[:60]
        return {"track_index": track_index, "clips": n, "name": track.name}

    @staticmethod
    def _db_to_volume(db):
        """Live's volume slider: 0.85 = 0 dB, 1.0 = +6 dB; below 0 dB roughly 0.025 per dB, curving to -inf."""
        db = float(db)
        if db >= 0:
            return min(1.0, 0.85 + db / 40.0)
        if db >= -18:
            return 0.85 + db * 0.025
        return max(0.0, 0.4 * (10 ** ((db + 18) / 40.0)))

    def _set_track_volume(self, track_index, db):
        track = self._song.tracks[track_index]
        track.mixer_device.volume.value = self._db_to_volume(db)
        return {"track_index": track_index, "db": float(db), "value": float(track.mixer_device.volume.value)}

    def _set_track_pan(self, track_index, pan):
        track = self._song.tracks[track_index]
        track.mixer_device.panning.value = max(-1.0, min(1.0, float(pan)))
        return {"track_index": track_index, "pan": float(track.mixer_device.panning.value)}

    def _set_send(self, track_index, send_index, value):
        track = self._song.tracks[track_index]
        sends = track.mixer_device.sends
        if send_index < 0 or send_index >= len(sends):
            raise IndexError("Send index out of range")
        sends[send_index].value = max(0.0, min(1.0, float(value)))
        return {"track_index": track_index, "send_index": send_index, "value": float(sends[send_index].value)}

    def _load_on_master(self, uri):
        app = self.application()
        item = self._find_browser_item_by_uri(app.browser, uri)
        if not item:
            raise ValueError("Browser item with URI '{0}' not found".format(uri))
        self._song.view.selected_track = self._song.master_track
        app.browser.load_item(item)
        return {"loaded": True, "item_name": item.name, "device_count": len(self._song.master_track.devices)}

    def _get_master_parameters(self, device_index):
        devices = self._song.master_track.devices
        if device_index < 0 or device_index >= len(devices):
            raise IndexError("Device index out of range")
        return {"device": self._serialize_device(devices[device_index], device_index, include_params=True)}

    def _set_master_parameter(self, device_index, parameter_index, value):
        devices = self._song.master_track.devices
        if device_index < 0 or device_index >= len(devices):
            raise IndexError("Device index out of range")
        param = devices[device_index].parameters[parameter_index]
        param.value = float(value)
        return {"device_index": device_index, "parameter_index": parameter_index, "name": param.name, "value": float(param.value)}

    def _get_device_parameters(self, track_index, device_index):'''


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Music/Ableton/User Library/Remote Scripts/AbletonMCP/__init__.py")
    code = open(src, encoding="utf-8").read()
    assert '"create_locator"]:' in code and 'elif command_type == "set_tempo":' in code and 'elif command_type == "get_track_info":' in code
    code = code.replace('"create_locator"]:', MAIN_THREAD_ADD, 1)
    code = code.replace('                        elif command_type == "set_tempo":', DISPATCH_ADD, 1)
    code = code.replace('            elif command_type == "get_track_info":', READ_ADD, 1)
    code = code.replace("    def _get_device_parameters(self, track_index, device_index):", METHODS, 1)
    code = code.replace("DEFAULT_PORT = 9877", "DEFAULT_PORT = 9878", 1)
    code = code.replace("PROTOCOL_VERSION = 1", 'PROTOCOL_VERSION = 1\nALMA_BRIDGE_VERSION = "%s"  # bump when a command is added; the app asks for it and prompts a reinstall' % ALMA_BRIDGE_VERSION, 1)
    code = code.replace('            "passive_listeners": True,', '            "passive_listeners": True,\n            "alma_bridge": ALMA_BRIDGE_VERSION,', 1)
    code = code.replace('HOST = "0.0.0.0"', 'HOST = "127.0.0.1"', 1)
    code = code.replace("AbletonMCP: Listening", "Alma Bridge: Listening")
    code = code.replace("# AbletonMCP/init.py", NOTICE, 1)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(code)
    print("wrote", OUT, len(code.splitlines()), "lines")


if __name__ == "__main__":
    main()
