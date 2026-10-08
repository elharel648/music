"""Ableton Live client over the AbletonMCP Remote Script TCP bridge (port 9877).

Writes land in whatever Live Set is in front. We refuse to write into a set that is not fresh unless forced.
"""
from __future__ import annotations
import json
import socket
import urllib.parse
from typing import Callable

HOST = "127.0.0.1"
BRIDGE_VERSION = "3"  # the Alma Bridge this app ships (flow/bridge/Alma); an older one in Live lacks newer commands
PORTS = (9878, 9877)  # Alma Bridge first, then the original AbletonMCP script


class BridgeError(RuntimeError):
    pass


class Live:
    def __init__(self, host: str = HOST, port: int | None = None, timeout: float = 30.0):
        self.host, self.port, self.timeout = host, port, timeout
        self._plugin_cache: dict[str, str] | None = None

    def _connect(self) -> socket.socket:
        ports = (self.port,) if self.port else PORTS
        last = None
        for p in ports:
            try:
                s = socket.create_connection((self.host, p), timeout=self.timeout)
                self.port = p
                return s
            except OSError as e:
                last = e
        raise BridgeError("Ableton Live is not reachable. Open Live, enable the Alma Bridge control surface (Settings › Link, Tempo & MIDI), and keep a Live Set in front.") from last

    @property
    def is_flow_bridge(self) -> bool:
        return self.port == 9878

    def call(self, cmd: str, **params):
        s = self._connect()
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

    def bridge_version(self) -> str:
        """The Alma Bridge version answering in Live: "0" for the original AbletonMCP script or an Alma bridge older than 2."""
        for cmd in ("get_script_info", "get_remote_script_info"):
            try:
                info = self.call(cmd) or {}
                return str(info.get("alma_bridge") or "0")
            except BridgeError:
                continue
        return "0"

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

    # ---- devices
    def add_device(self, track_index: int, uri: str) -> int:
        """Load a device at the end of the track's chain; return its device index."""
        before = len(self.call("get_track_info", track_index=track_index).get("devices", []))
        self.call("load_instrument_or_effect", track_index=track_index, uri=uri)
        after = self.call("get_track_info", track_index=track_index).get("devices", [])
        return max(before, len(after) - 1)

    def set_param(self, track_index: int, device_index: int, name: str, value: float) -> bool:
        """Set a device parameter by (case-insensitive) name. Returns False when the device has no such parameter."""
        r = self.call("get_device_parameters", track_index=track_index, device_index=device_index)
        params = r.get("device", {}).get("parameters") if isinstance(r, dict) and "device" in r else (r.get("parameters", r) if isinstance(r, dict) else r)
        params = params or []
        low = name.lower()
        hit = None
        for i, p in enumerate(params):
            pname = str(p.get("name", "")).lower()
            if pname == low:
                hit = (p.get("index", i), p); break
        if hit is None:
            for i, p in enumerate(params):
                if low in str(p.get("name", "")).lower():
                    hit = (p.get("index", i), p); break
        if hit is None:
            raise BridgeError(f"parameter '{name}' not found on device {device_index}")
        idx, p = hit
        lo, hi = p.get("min"), p.get("max")
        v = float(value)
        if lo is not None and hi is not None:
            v = min(max(v, float(lo)), float(hi))
        self.call("set_device_parameter", track_index=track_index, device_index=device_index, parameter_index=int(idx), value=v)
        return True

    # ---- writes
    def replace_track_clips(self, track_index: int, path: str, spans: list, clip_bars: int, hits: list | None = None,
                            sweeps: list | None = None, name: str | None = None) -> dict:
        """Swap one built track's sound in place: same bars, new file. Devices and mixer settings stay."""
        return self.call("replace_track_clips", track_index=int(track_index), path=path, spans=[[int(a), int(b)] for a, b in spans],
                         clip_bars=int(clip_bars or 4), hits=[float(h) for h in (hits or [])], sweeps=[[float(b), pth] for b, pth in (sweeps or [])], name=name)

    def delete_tracks_by_name(self, names: list[str]) -> int:
        return int((self.call("delete_tracks_by_name", names=list(names)) or {}).get("deleted", 0))

    def clear_locators(self, names: list[str]) -> int:
        return int((self.call("clear_locators", names=list(names)) or {}).get("removed", 0))

    def apply_plan(self, plan: dict, progress: Callable[[str, float], None] | None = None, force: bool = False) -> dict:
        prog = progress or (lambda m, p: None)
        if not force and not self.is_fresh_set():
            raise BridgeError("The Live Set in front is not empty. Open File > New Live Set, then build again.")
        self.call("set_tempo", tempo=float(plan["bpm"]))
        base = self.session()["track_count"]
        tracks = plan["tracks"]
        report = {"tracks": [], "warnings": []}
        total_steps = sum(len(t.get("spans", [])) * 4 + len(t.get("hits", [])) + len(t.get("placements", [])) for t in tracks) + len(tracks) + 2
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
            elif t.get("spans") or t.get("hits"):
                self.call("create_audio_clip", track_index=ti, clip_index=0, path=t["source"]["path"])
            n = 0
            for s, e in t.get("spans", []):
                b = s
                while b < e:
                    self.call("duplicate_session_clip_to_arrangement", track_index=ti, clip_index=0, destination_time=(b - 1) * 4.0)
                    b += clip_bars
                    n += 1
                tick(f"{t['name']}: bars {s}–{e - 1}")
            if t.get("sweeps"):
                self.call("create_audio_clip", track_index=ti, clip_index=1, path=t["sweeps"][0][1])
                for sb, _p in t["sweeps"]:
                    self.call("duplicate_session_clip_to_arrangement", track_index=ti, clip_index=1, destination_time=(sb - 1) * 4.0)
                    n += 1
                tick(f"{t['name']}: sweep into the drop")
            slots: dict[str, int] = {}
            for pl in t.get("placements", []):
                if pl["path"] not in slots:
                    slots[pl["path"]] = 2 + len(slots)
                    self.call("create_audio_clip", track_index=ti, clip_index=slots[pl["path"]], path=pl["path"])
                self.call("duplicate_session_clip_to_arrangement", track_index=ti, clip_index=slots[pl["path"]], destination_time=(pl["bar"] - 1) * 4.0)
                n += 1
                tick(f"{t['name']}: phrase at bar {pl['bar']}")
            for hb in t.get("hits", []):
                self.call("duplicate_session_clip_to_arrangement", track_index=ti, clip_index=0, destination_time=(hb - 1) * 4.0)
                n += 1
                tick(f"{t['name']}: hit at bar {hb}")
            report["tracks"].append({"index": ti, "name": t["name"], "clips": n})
            prog(f"@track:{i}", min(0.98, done / max(total_steps, 1)))
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
