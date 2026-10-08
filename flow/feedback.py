"""Send what the user heard, together with what Alma built, to the maker.

Beta feedback is only useful next to the plan that produced it: version, style, the sections and spans, the last log
lines. When FEEDBACK_URL is set (a Supabase REST endpoint with an insert-only policy) the report is posted there;
otherwise, or when the network fails, it is written to the Desktop so it can be sent by hand. Nothing is sent without
the user pressing Send.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import platform
import urllib.request

from . import __version__, license as lic

FEEDBACK_URL = os.environ.get("ALMA_FEEDBACK_URL", "")   # e.g. https://<project>.supabase.co/rest/v1/feedback
FEEDBACK_KEY = os.environ.get("ALMA_FEEDBACK_KEY", "")   # the project's anon key; the table only allows inserts
TIMEOUT = 12.0


def report(note: str, plan: dict | None, log: list[str], extra: dict | None = None) -> dict:
    st = lic.status()
    return {
        "note": (note or "").strip()[:4000],
        "version": __version__, "machine": lic.machine_id()[:12], "email": st.get("email"), "license": st.get("state"),
        "os": f"{platform.system()} {platform.release()} {platform.machine()}",
        "sent_at": dt.datetime.now().isoformat(timespec="seconds"),
        "plan": plan or {}, "log": log[-120:], **(extra or {}),
    }


def post(rep: dict) -> None:
    body = json.dumps(rep, default=str).encode()
    req = urllib.request.Request(FEEDBACK_URL, data=body, method="POST", headers={
        "Content-Type": "application/json", "apikey": FEEDBACK_KEY, "Authorization": f"Bearer {FEEDBACK_KEY}", "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        if r.status not in (200, 201, 204):
            raise RuntimeError(f"feedback endpoint answered {r.status}")


def save_local(rep: dict) -> str:
    desk = os.path.join(os.path.expanduser("~"), "Desktop")
    folder = desk if os.path.isdir(desk) else lic.data_dir()
    path = os.path.join(folder, f"Alma feedback {dt.datetime.now():%Y-%m-%d %H%M}.json")
    with open(path, "w") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    return path


def send(note: str, plan: dict | None, log: list[str], extra: dict | None = None) -> dict:
    rep = report(note, plan, log, extra)
    if FEEDBACK_URL and FEEDBACK_KEY:
        try:
            post(rep)
            return {"ok": True, "sent": True}
        except Exception as e:  # noqa: BLE001 - fall back to a file, never lose the note
            rep["send_error"] = str(e)[:200]
    path = save_local(rep)
    return {"ok": True, "sent": False, "path": path}
