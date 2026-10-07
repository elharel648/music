"""FLOW desktop app: a pywebview window hosting ui/index.html, with a small Python API behind it."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
import traceback

import webview

from . import __version__, PRODUCT, analysis, pack as packmod, plugins, license as lic, cli as flowcli


def _ui_path() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    for cand in (os.path.join(base, "flow", "ui", "index.html"), os.path.join(base, "ui", "index.html")):
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError("ui/index.html missing from the bundle")


class Api:
    def __init__(self):
        self.window: webview.Window | None = None
        self._busy = False

    # ---- helpers
    def _emit(self, msg: str, pct: float):
        if self.window:
            self.window.evaluate_js(f"window.flowProgress({json.dumps(msg)}, {float(pct)})")

    def _emit_plan(self, view: dict):
        if self.window:
            self.window.evaluate_js(f"window.flowPlan({json.dumps(view, default=str)})")

    # ---- license
    def status(self):
        s = lic.status()
        s.update({"version": __version__, "product": PRODUCT, "machine": lic.machine_id()[:8]})
        return s

    def activate(self, key: str):
        try:
            p = lic.activate(key)
            return {"ok": True, "email": p.get("email"), "expires": p.get("expires")}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    # ---- last session (so a closed app can resume where it stopped)
    def _session_path(self) -> str:
        return os.path.join(lic.data_dir(), "last_session.json")

    def save_session(self, opts: dict):
        try:
            keep = {k: opts.get(k) for k in ("reference", "pack", "length", "target", "out", "style", "bpm", "synth", "sidechain", "finish")}
            with open(self._session_path(), "w") as f:
                json.dump(keep, f)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def load_session(self):
        try:
            p = self._session_path()
            if not os.path.exists(p):
                return None
            with open(p) as f:
                s = json.load(f)
            if not s.get("reference") or not os.path.exists(s["reference"]):
                return None
            packs = [x for x in str(s.get("pack") or "").split(os.pathsep) if x]
            if not packs or not all(os.path.isdir(x) for x in packs):
                return None
            return s
        except Exception:
            return None

    # ---- file pickers
    def pick_reference(self):
        r = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                           file_types=("Audio (*.wav;*.aif;*.aiff;*.mp3;*.flac)", "All files (*.*)"))
        return r[0] if r else None

    def pick_folder(self):
        r = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return r[0] if r else None

    def pick_folders(self):
        """Several folders at once (Cmd-click in the dialog). Returned joined with os.pathsep for scan_pack."""
        r = self.window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=True)
        return os.pathsep.join(r) if r else None

    # ---- analysis
    def analyze(self, path: str, bpm: float | None = None):
        try:
            r = analysis.analyze_reference(path, bpm_hint=bpm or None)
            r.pop("bar_features", None)
            return {"ok": True, "ref": r}
        except Exception as e:
            return {"ok": False, "error": f"{e}"}

    def scan_pack(self, folder: str):
        try:
            pk = packmod.scan_pack(folder)
            pk.pop("_by_role", None)
            pk["samples"] = pk["samples"][:400]
            return {"ok": True, "pack": pk}
        except Exception as e:
            return {"ok": False, "error": f"{e}"}

    def download_icloud(self, folder: str):
        try:
            r = packmod.download_icloud(folder, progress=self._emit)
            return {"ok": r.get("remaining", 0) == 0, **r}
        except Exception as e:
            return {"ok": False, "error": f"{e}"}

    def copy_pack_local(self, folder: str):
        try:
            packmod.download_icloud(folder, progress=self._emit)
            new = packmod.copy_pack_local(folder, progress=self._emit)
            return {"ok": True, "folder": new}
        except Exception as e:
            return {"ok": False, "error": f"{e}"}

    def scan_plugins(self):
        try:
            p = plugins.scan_installed()
            p["all"] = [x["name"] for x in p["all"]][:300]
            return {"ok": True, "plugins": p}
        except Exception as e:
            return {"ok": False, "error": f"{e}"}

    def finish_options(self):
        from . import finish
        return [{"key": k, "name": n, "hint": h, "on": k in finish.DEFAULT_ON} for k, n, h in finish.OPTIONS]

    def bridge_paths(self):
        src = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "flow", "bridge", "FLOW")
        if not os.path.isdir(src):
            src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge", "FLOW")
        home = os.path.expanduser("~")
        if sys.platform == "darwin":
            dst = os.path.join(home, "Music", "Ableton", "User Library", "Remote Scripts", "FLOW")
        elif sys.platform.startswith("win"):
            dst = os.path.join(home, "Documents", "Ableton", "User Library", "Remote Scripts", "FLOW")
        else:
            dst = os.path.join(home, "Ableton", "User Library", "Remote Scripts", "FLOW")
        return src, dst

    def install_bridge(self):
        """Copy the FLOW Bridge Remote Script into Live's User Library. Live must be restarted and the surface enabled."""
        import shutil
        try:
            src, dst = self.bridge_paths()
            if not os.path.isfile(os.path.join(src, "__init__.py")):
                return {"ok": False, "error": "Bridge files are missing from this build."}
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            return {"ok": True, "path": dst,
                    "steps": ["Quit and reopen Ableton Live.", "Settings › Link, Tempo & MIDI › Control Surface: choose FLOW.", "Open File › New Live Set and build again."]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def ableton_status(self):
        try:
            from .ableton_bridge import Live
            live = Live(timeout=4)
            if not live.available():
                return {"ok": False, "reason": "Live is not running or the AbletonMCP control surface is off"}
            return {"ok": True, "fresh": live.is_fresh_set(), "tracks": live.session()["track_count"]}
        except Exception as e:
            return {"ok": False, "reason": f"{e}"}

    # ---- build
    def build(self, opts: dict):
        if self._busy:
            return {"ok": False, "error": "A build is already running"}
        ok, st = lic.can_build()
        if not ok:
            return {"ok": False, "error": st.get("reason") or "License required"}
        self.save_session(opts)
        self._busy = True

        def work():
            try:
                fin = opts.get("finish")
                res = flowcli.run_build(
                    opts["reference"], opts["pack"], flowcli.parse_length(opts.get("length") or None) if isinstance(opts.get("length"), str) else opts.get("length"),
                    opts.get("target", "stems"), opts.get("out") or None, opts.get("style", "house"), opts.get("bpm") or None,
                    opts.get("synth") or None, opts.get("sidechain") or None, bool(opts.get("force")), progress=self._emit,
                    work_dir=opts.get("work_dir") or None, finish_opts=set(fin) if isinstance(fin, list) else None,
                    on_plan=self._emit_plan)
                res.pop("reference", None)
                plan = res.get("plan", {})
                from . import arrange
                summary = {**arrange.plan_view(plan), "export": res.get("export"), "ableton": res.get("ableton"), "kit": res.get("kit")}
                self.window.evaluate_js(f"window.flowDone({json.dumps(summary, default=str)})")
            except BaseException as e:  # SystemExit from license too
                tb = traceback.format_exc(limit=2)
                self.window.evaluate_js(f"window.flowError({json.dumps(str(e) or tb)})")
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def open_path(self, path: str):
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
            elif sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", path])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def main():
    api = Api()
    window = webview.create_window(f"{PRODUCT}", _ui_path(), js_api=api, width=1180, height=860, min_size=(960, 680),
                                   background_color="#F5F4F0")
    api.window = window
    webview.start(debug=False)


if __name__ == "__main__":
    main()
