"""Ableton Live client over the AbletonMCP Remote Script TCP bridge (port 9877).

Writes land in whatever Live Set is in front. We refuse to write into a set that is not fresh unless forced.
"""
from __future__ import annotations
import json
import socket
import urllib.parse
from typing import Callable

HOST, PORT = "127.0.0.1", 9877


class BridgeError(RuntimeError):
    pass


class Live:
    def __init__(self, host: str = HOST, port: int = PORT, timeout: float = 30.0):
        self.host, self.port, self.timeout = host, port, timeout
        self._plugin_cache: dict[str, str] | None = None

    def call(self, cmd: str, **params):
        try:
            s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise BridgeError("Ableton Live is not reachable. Open Live, enable the AbletonMCP control surface, and keep a Live Set in front.") from e
        with s:
            s.sendall(json.dumps({"type": cmd, "params": params}).encode())
            s.settimeout(self.timeout)
            data = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
                try:
                    obj = json.loads(data.decode())
                    break
                except Exception:
                    continue
        if not data:
            raise BridgeError(f"{cmd}: empty reply from Live")
        if obj.get("status") != "success":
            raise BridgeError(f"{cmd}: {obj.get('message') or obj}")
        return obj.get("result")

    # ---- reads
    def available(self) -> bool:
        try:
            self.call("get_session_info")
            return True
        except BridgeError:
            return False

    def session(self) -> dict:
        return self.call("get_session_info")

    def track_names(self) -> list[str]:
        n = self.session()["track_count"]
        return [self.call("get_track_info", track_index=i)["name"] for i in range(n)]

    def is_fresh_set(self) -> bool:
        names = self.track_names()
        return len(names) <= 4 and all(n.split("-", 1)[-1].strip() in ("MIDI", "Audio") or n.endswith("MIDI") or n.endswith("Audio") for n in names)

    def browser_items(self, path: str) -> list[dict]:
        r = self.call("get_browser_items_at_path", path=path)
        return r.get("items", []) if isinstance(r, dict) else []

    def plugin_uris(self) -> dict[str, str]:
        """name -> uri for every installed plug-in Live knows (VST3 first, then AU)."""
        if self._plugin_cache is not None:
            return self._plugin_cache
        found: dict[str, str] = {}
        for fmt in ("VST3", "AUv2", "VST"):
            try:
                vendors = self.browser_items(f"plugins/{fmt}")
            except BridgeError:
                continue
            for v in vendors:
                if not v.get("is_folder"):
                    if v.get("is_loadable"):
                        found.setdefault(v["name"], v["uri"])
                    continue
                try:
                    for it in self.browser_items(f"plugins/{fmt}/{v['name']}"):
                        if it.get("is_loadable"):
                            found.setdefault(it["name"], it["uri"])
                except BridgeError:
                    continue
        self._plugin_cache = found
        return found

    def find_plugin(self, name: str) -> str | None:
        uris = self.plugin_uris()
        if name in uris:
            return uris[name]
        low = name.lower()
        for n, u in uris.items():
            if n.lower() == low or low in n.lower():
                return u
        return None

    # ---- writes
    def apply_plan(self, plan: dict, progress: Callable[[str, float], None] | None = None, force: bool = False) -> dict:
        prog = progress or (lambda m, p: None)
        if not force and not self.is_fresh_set():
            raise BridgeError("The Live Set in front is not empty. Open File > New Live Set, then build again.")
        self.call("set_tempo", tempo=float(plan["bpm"]))
        base = self.session()["track_count"]
        tracks = plan["tracks"]
        report = {"tracks": [], "warnings": []}
        total_steps = sum(len(t.get("spans", [])) * 4 + len(t.get("hits", [])) for t in tracks) + len(tracks) + 2
        done = 0

        def tick(msg):
            nonlocal done
            done += 1
            prog(msg, min(0.98, done / max(total_steps, 1)))

        for i, t in enumerate(tracks):
            ti = base + i
            if t.get("kind") == "midi":
                self.call("create_midi_track", index=-1)
            else:
                self.call("create_audio_track", index=-1)
            self.call("set_track_name", track_index=ti, name=t["name"][:60])
            tick(f"Track {t['name']}")
        prog("Placing clips", done / total_steps)
        for i, t in enumerate(tracks):
            ti = base + i
            clip_bars = t.get("clip_bars") or 4
            if t.get("kind") == "midi":
                self.call("create_clip", track_index=ti, clip_index=0, length=float(clip_bars * 4))
                self.call("add_notes_to_clip", track_index=ti, clip_index=0, notes=t["notes"])
                self.call("set_clip_name", track_index=ti, clip_index=0, name=t["name"][:40])
                uri = t.get("plugin", {}).get("uri") or self.find_plugin(t.get("plugin", {}).get("name", ""))
                if uri:
                    try:
                        self.call("load_instrument_or_effect", track_index=ti, uri=uri)
                    except BridgeError as e:
                        report["warnings"].append(f"{t['name']}: could not load {t['plugin'].get('name')} ({e})")
                else:
                    report["warnings"].append(f"{t['name']}: plug-in {t.get('plugin', {}).get('name')} not found in Live's browser")
            else:
                self.call("create_audio_clip", track_index=ti, clip_index=0, path=t["source"]["path"])
            n = 0
            for s, e in t.get("spans", []):
                b = s
                while b < e:
                    self.call("duplicate_session_clip_to_arrangement", track_index=ti, clip_index=0, destination_time=(b - 1) * 4.0)
                    b += clip_bars
                    n += 1
                tick(f"{t['name']}: bars {s}–{e - 1}")
            for hb in t.get("hits", []):
                self.call("duplicate_session_clip_to_arrangement", track_index=ti, clip_index=0, destination_time=(hb - 1) * 4.0)
                n += 1
                tick(f"{t['name']}: hit at bar {hb}")
            report["tracks"].append({"index": ti, "name": t["name"], "clips": n})
        # sidechain / effects
        sc = plan.get("sidechain")
        if sc:
            uri = self.find_plugin(sc)
            if uri:
                for i, t in enumerate(tracks):
                    if t["role"] in ("kick", "impact", "uplifter", "downlifter", "snare_roll"):
                        continue
                    try:
                        self.call("load_instrument_or_effect", track_index=base + i, uri=uri)
                    except BridgeError as e:
                        report["warnings"].append(f"{t['name']}: sidechain {sc} failed ({e})")
                tick(f"Sidechain: {sc} on every non-kick track")
            else:
                report["warnings"].append(f"Sidechain plug-in {sc} not found in Live's browser")
        try:
            self.call("switch_to_arrangement_view")
        except BridgeError:
            pass
        failed = []
        for name, bar in plan["locators"]:
            try:
                self.call("create_locator", name=name, time=(bar - 1) * 4.0)
            except BridgeError:
                failed.append(f"{name} @ bar {bar}")
        if failed:
            report["warnings"].append("Locators could not be created by the bridge; add by hand: " + ", ".join(failed))
        prog("Done. Save the set (Cmd+S).", 1.0)
        return report
