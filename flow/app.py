"""FLOW desktop app: a pywebview window hosting ui/index.html, with a small Python API behind it."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
import traceback

import webview
import uuid
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, PRODUCT, analysis, pack as packmod, plugins, license as lic, cli as flowcli, styles as stylelib


def _ui_path() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    for cand in (os.path.join(base, "flow", "ui", "index.html"), os.path.join(base, "ui", "index.html")):
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError("ui/index.html missing from the bundle")


class _MediaHandler(BaseHTTPRequestHandler):
    """Serves only files the app registered, by unguessable token, with HTTP Range support (WebKit needs it to seek)."""

    def do_GET(self):
        self._serve(head=False)

    def do_HEAD(self):
        self._serve(head=True)

    def _serve(self, head: bool):
        tok = self.path.split("/m/", 1)[1].split("?", 1)[0] if "/m/" in self.path else ""
        path = self.server.files.get(tok)  # type: ignore[attr-defined]
        if not path or not os.path.isfile(path):
            self.send_error(404)
            return
        size = os.path.getsize(path)
        start, end, status = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            try:
                if a:
                    start = int(a)
                    end = int(b) if b else size - 1
                else:
                    start = max(0, size - int(b))
                end = min(end, size - 1)
                status = 206 if start <= end else 200
            except ValueError:
                start, end, status = 0, size - 1, 200
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head:
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(1 << 16, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


class MediaServer:
    """Loopback-only, random port, token URLs. The UI plays previews and auditions sounds through it."""

    def __init__(self):
        self.files: dict[str, str] = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _MediaHandler)
        self.httpd.files = self.files  # type: ignore[attr-defined]
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def register(self, path: str) -> str:
        for tok, p in self.files.items():
            if p == path:
                return f"http://127.0.0.1:{self.port}/m/{tok}"
        tok = uuid.uuid4().hex
        self.files[tok] = path
        return f"http://127.0.0.1:{self.port}/m/{tok}"

    def close(self):
        self.httpd.shutdown()


class Api:
    def __init__(self):
        self.window: webview.Window | None = None
        self._busy = False
        self._packs: dict[str, dict] = {}
        self._pack_folders: list[str] = []
        self._ctx: dict | None = None
        self._ctx_key: str | None = None
        self._kit_cache: dict[tuple, dict] = {}
        self.media = MediaServer()

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
            keep = {k: opts.get(k) for k in ("reference", "pack", "length", "target", "out", "style", "bpm", "synth", "sidechain", "finish", "vocal", "structure", "kit")}
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

    def pick_vocal(self):
        r = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                           file_types=("Audio (*.wav;*.aif;*.aiff;*.mp3;*.flac)", "All files (*.*)"))
        return r[0] if r else None

    def analyze_vocal(self, path: str):
        try:
            from . import vocal
            return {"ok": True, "vocal": vocal.analyze(path)}
        except Exception as e:
            return {"ok": False, "error": f"{e}"}

    def styles(self):
        return stylelib.listing()

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
            self._ref_path = os.path.realpath(path)
            return {"ok": True, "ref": r}
        except Exception as e:
            return {"ok": False, "error": f"{e}"}

    def scan_pack(self, folder: str):
        try:
            pk = packmod.scan_pack(folder)
            self._packs[folder] = pk
            self._pack_folders = list(pk.get("folders") or [folder])
            self._kit_cache = {k: v for k, v in self._kit_cache.items() if k[0] != folder}
            view = {k: v for k, v in pk.items() if k != "_by_role"}
            view["samples"] = pk["samples"][:400]
            return {"ok": True, "pack": view}
        except Exception as e:
            return {"ok": False, "error": f"{e}"}

    def kit_options(self, folder: str, bpm: float | None = None, overrides: dict | None = None):
        """The kit FLOW proposes from the user's pack, with every candidate per role, so the user can swap any of them."""
        try:
            pk = self._packs.get(folder) or packmod.scan_pack(folder)
            self._packs[folder] = pk
            bpm = float(bpm or pk.get("bpm_hint") or 124)
            key = (folder, round(bpm))
            if key not in self._kit_cache:
                self._kit_cache[key] = packmod.candidates(pk, bpm)
            rows = packmod.kit_view(pk, bpm, overrides or {}, self._kit_cache[key])
            return {"ok": True, "kit": rows, "bpm": bpm}
        except Exception as e:
            return {"ok": False, "error": f"{e}"}

    def audition_url(self, path: str):
        """A playable URL for one of the user's own sounds (only files inside the chosen pack folders or FLOW's work folder)."""
        try:
            real = os.path.realpath(path)
            roots = [os.path.realpath(f) for f in self._pack_folders]
            if self._ctx:
                roots.append(os.path.realpath(self._ctx["work"]))
            ok_ref = getattr(self, "_ref_path", None) == real
            if not (ok_ref or any(real == r or real.startswith(r + os.sep) for r in roots)) or not os.path.isfile(real):
                return {"ok": False, "error": "Not one of your sounds"}
            return {"ok": True, "url": self.media.register(real)}
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

    # ---- prepare, preview, build
    def _prep_key(self, opts: dict) -> str:
        return json.dumps({k: opts.get(k) for k in flowcli.PREP_KEYS}, sort_keys=True, default=str)

    def _prepare(self, opts: dict) -> dict:
        key = self._prep_key(opts)
        if self._ctx is not None and self._ctx_key == key:
            from . import arrange
            self._emit_plan(arrange.plan_view(self._ctx["plan"]))
            self._emit("Using the arrangement you listened to", 0.4)
            return self._ctx
        fin = opts.get("finish")
        length = flowcli.parse_length(opts.get("length") or None) if isinstance(opts.get("length"), str) else opts.get("length")
        ctx = flowcli.prepare(opts["reference"], opts["pack"], length, opts.get("style", "house"), opts.get("bpm") or None, opts.get("synth") or None,
                              progress=self._emit, work_dir=opts.get("work_dir") or None, finish_opts=set(fin) if isinstance(fin, list) else None,
                              on_plan=self._emit_plan, vocal=opts.get("vocal") or None, structure=opts.get("structure") or "reference",
                              kit_overrides=opts.get("kit") or None)
        self._ctx, self._ctx_key = ctx, key
        return ctx

    def _run(self, fn):
        if self._busy:
            return {"ok": False, "error": "FLOW is still working on the previous step"}
        ok, st = lic.can_build()
        if not ok:
            return {"ok": False, "error": st.get("reason") or "License required"}
        self._busy = True

        def work():
            try:
                fn()
            except BaseException as e:  # SystemExit from license too
                tb = traceback.format_exc(limit=2)
                self.window.evaluate_js(f"window.flowError({json.dumps(str(e) or tb)})")
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def preview(self, opts: dict):
        """Prepare the arrangement and render a mix to listen to. Nothing is written to a DAW."""
        self.save_session(opts)

        def go():
            ctx = self._prepare(opts)
            self._emit_preview(ctx, lambda m, p: self._emit(m, 0.4 + 0.6 * p))

        return self._run(go)

    def _emit_preview(self, ctx: dict, progress):
        """Render the mix once per prepared arrangement; later calls reuse the file."""
        res = ctx.get("preview")
        if not res:
            res = flowcli.render_preview(ctx, progress=progress)
            res["url"] = self.media.register(res["path"])
            res["structure"] = ctx["plan"].get("structure")
            res["used"] = len(ctx["kit"])
            ctx["preview"] = res
        self.window.evaluate_js(f"window.flowPreview({json.dumps(res, default=str)})")

    def build(self, opts: dict):
        self.save_session(opts)

        def go():
            ctx = self._prepare(opts)
            res = flowcli.commit(ctx, opts.get("target", "stems"), opts.get("out") or None, opts.get("sidechain") or None, bool(opts.get("force")),
                                 progress=lambda m, p: self._emit(m, 0.4 + 0.6 * p))
            res.pop("reference", None)
            from . import arrange
            summary = {**arrange.plan_view(res.get("plan", {})), "export": res.get("export"), "ableton": res.get("ableton"), "kit": res.get("kit")}
            self.window.evaluate_js(f"window.flowDone({json.dumps(summary, default=str)})")
            # the track is written; now, quietly, the mix of exactly that, so it can be played from the map
            try:
                self._emit_preview(ctx, lambda m, p: None)
            except Exception:
                pass

        return self._run(go)

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


def _update_check(api: "Api"):
    """Once, shortly after launch, off the UI thread. A missing network or a bad manifest is silently nothing."""
    from . import update
    try:
        res = update.check()
        if res and res.get("available") and api.window:
            api.window.evaluate_js(f"window.flowUpdate({json.dumps(res)})")
    except Exception:
        pass


def main():
    api = Api()
    window = webview.create_window(f"{PRODUCT}", _ui_path(), js_api=api, width=1180, height=860, min_size=(960, 680),
                                   background_color="#EBEBEE")
    api.window = window
    threading.Timer(2.5, _update_check, args=(api,)).start()
    webview.start(debug=False)


if __name__ == "__main__":
    main()
