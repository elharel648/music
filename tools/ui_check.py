"""Drive the real UI (the demo build, with a fake backend) in a headless browser and assert how it behaves.

    uv pip install --python .venv/bin/python playwright && .venv/bin/python -m playwright install chromium     # once
    .venv/bin/python tools/ui_check.py            # exit code 0 = every check passed

What it guards (each one is a bug that has shipped or nearly shipped):
  - the structure switch: locked and honest with no reference, enabled and reversible once there is one, the knob always on the
    active side; the Live | Stems + MIDI switch through every click path
  - the tempo slider: the cap stays under the pointer while dragging (no easing), a generous grab area, live bars readout, one
    expensive update on release, both ends of the 80-180 range
  - the four circles share one centre line and one size, at the normal and the smallest window
  - a full build, a rebuild in place, the license view, the self-update chip, the kit list (mouse and keyboard)
"""
from __future__ import annotations
import asyncio
import functools
import http.server
import os
import subprocess
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "flow", "ui")
FAILS: list[str] = []


def check(ok: bool, what: str, detail: str = ""):
    print(("  ok    " if ok else "  FAIL  ") + what + ((" — " + detail) if (detail and not ok) else ""))
    if not ok:
        FAILS.append(what)


async def fresh(browser, base, w=1180, h=860, q=""):
    pg = await browser.new_page(viewport={"width": w, "height": h})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(f"{base}/demo.html?{q}")
    await pg.wait_for_timeout(1400)
    return pg, errs


async def load(pg, ref=True, pack=True):
    if ref:
        await pg.evaluate("document.getElementById('pickRef').click()")
        await pg.wait_for_timeout(2700)
    if pack:
        await pg.evaluate("document.getElementById('pickPack').click()")
        await pg.wait_for_timeout(3800)


SW = """(id)=>{ const sw=document.getElementById(id); const bs=[...sw.querySelectorAll('button')]; const pill=sw.querySelector('.pill'); const i=pill.querySelector('i');
  return {on: bs.map(b=>b.classList.contains('on')?'1':'0').join(''), off: sw.classList.contains('off'), knobRight: (i.getBoundingClientRect().left-pill.getBoundingClientRect().left)>8, state: id==='structSeg'?S.structure:S.target}; }"""


async def toggles(browser, base):
    print("switches")
    pg, errs = await fresh(browser, base)
    st = await pg.evaluate(f"({SW})('structSeg')")
    check(st["off"] and st["on"] == "01" and st["knobRight"], "no reference: locked on Typical, knob on the Typical side", str(st))
    for sel in ("#structSeg .pill", "#structSeg button[data-v=reference]", "#structSeg button[data-v=typical]"):
        await pg.evaluate(f"document.querySelector('{sel}').click()")
        await pg.wait_for_timeout(300)
    st2 = await pg.evaluate(f"({SW})('structSeg')")
    check(st2 == st, "no reference: clicking cannot change or strand it", str(st2))
    await load(pg, pack=False)
    st = await pg.evaluate(f"({SW})('structSeg')")
    check((not st["off"]) and st["on"] == "10" and not st["knobRight"], "reference loaded: enabled, Reference on", str(st))
    for tag, sel, want in (("pill", "#structSeg .pill", "01"), ("pill again", "#structSeg .pill", "10"), ("Typical label", "#structSeg button[data-v=typical]", "01"), ("Reference label", "#structSeg button[data-v=reference]", "10")):
        await pg.evaluate(f"document.querySelector('{sel}').click()")
        await pg.wait_for_timeout(300)
        s = await pg.evaluate(f"({SW})('structSeg')")
        check(s["on"] == want and s["knobRight"] == (want == "01"), f"structure switch: {tag} -> {want} and the knob agrees", str(s))
    for tag, sel, want in (("pill", "#targetSeg .pill", "01"), ("pill again", "#targetSeg .pill", "10"), ("Stems label", "#targetSeg button[data-v=stems]", "01"), ("Live label", "#targetSeg button[data-v=ableton]", "10")):
        await pg.evaluate(f"document.querySelector('{sel}').click()")
        await pg.wait_for_timeout(300)
        s = await pg.evaluate(f"({SW})('targetSeg')")
        check(s["on"] == want and s["knobRight"] == (want == "01"), f"target switch: {tag} -> {want} and the knob agrees", str(s))
    await pg.evaluate("document.querySelector('#targetSeg button[data-v=stems]').click()")
    await pg.wait_for_timeout(500)
    check(await pg.evaluate("document.getElementById('targetHint').textContent.trim()===''"), "Stems + MIDI shows no explanatory sentence under the plate")
    await pg.evaluate("document.querySelector('#targetSeg button[data-v=ableton]').click()")
    await pg.wait_for_timeout(300)
    r = await pg.evaluate("(()=>{ const p=document.querySelector('#structSeg .pill').getBoundingClientRect(); return [p.x+p.width/2, p.y+p.height/2]; })()")
    before = await pg.evaluate(f"({SW})('structSeg')")
    await pg.mouse.click(r[0], r[1])
    await pg.wait_for_timeout(350)
    after = await pg.evaluate(f"({SW})('structSeg')")
    check(before["on"] != after["on"], "a real mouse click on the pill flips it")
    check(not errs, "no script errors", str(errs))
    await pg.close()


async def slider(browser, base):
    print("tempo slider")
    pg, errs = await fresh(browser, base)
    await load(pg)
    await pg.evaluate("window.__ch=0; document.getElementById('bpmIn').addEventListener('change',()=>window.__ch++);")
    t = await pg.evaluate("document.getElementById('bpmTrack').getBoundingClientRect().toJSON()")
    y = t["y"] + t["height"] / 2
    await pg.mouse.move(t["x"] + t["width"] * 0.45, y - 9)   # grabbed from above the 4px track
    await pg.mouse.down()
    lag, vals, bars, trans = [], [], [], ""
    for i in range(41):
        x = t["x"] + 11 + (t["width"] - 22) * (0.2 + 0.6 * i / 40)
        await pg.mouse.move(x, y - 9 + ((i % 3) - 1) * 4)
        await pg.wait_for_timeout(16)
        c = await pg.evaluate("(()=>{ const c=document.getElementById('bpmCap').getBoundingClientRect(); return [c.left+c.width/2, document.getElementById('bpmVal').textContent, document.getElementById('lcdSub').textContent, getComputedStyle(document.getElementById('bpmCap')).transitionDuration]; })()")
        lag.append(abs(c[0] - x)); vals.append(int(c[1])); bars.append(c[2]); trans = c[3]
    await pg.mouse.up()
    await pg.wait_for_timeout(450)
    end = await pg.evaluate("({inval: document.getElementById('bpmIn').value, ch: window.__ch})")
    check(max(lag) < 1.0, "the cap stays under the pointer while dragging", f"max error {max(lag):.2f}px")
    check(trans in ("0s", "0s, 0s"), "no easing while dragging", trans)
    check(all(a <= b for a, b in zip(vals, vals[1:])), "values never go backwards")
    check(len(set(bars)) > 1, "the bars readout follows the hand live")
    check(end["ch"] == 1 and end["inval"] == str(vals[-1]), "one expensive update, on release", str(end))
    for fx, want in ((-60, "80"), (t["width"] + 60, "180")):
        await pg.mouse.move(t["x"] + t["width"] / 2, y)
        await pg.mouse.down()
        await pg.mouse.move(t["x"] + fx, y, steps=6)
        await pg.mouse.up()
        await pg.wait_for_timeout(350)
        e = await pg.evaluate("(()=>{ const c=document.getElementById('bpmCap').getBoundingClientRect(), t=document.getElementById('bpmTrack').getBoundingClientRect(); return {val:document.getElementById('bpmVal').textContent, inside: c.left>=t.left-.5 && c.right<=t.right+.5}; })()")
        check(e["val"] == want and e["inside"], f"end stop {want} holds and the cap stays inside the track", str(e))
    check(not errs, "no script errors", str(errs))
    await pg.close()


async def circles(browser, base):
    print("the four circles")
    for w, h in ((1180, 860), (960, 680)):
        pg, errs = await fresh(browser, base, w, h)
        await load(pg)
        m = await pg.evaluate("""(()=>{ const q=s=>document.querySelector(s).getBoundingClientRect(); const c=r=>Math.round(r.top+r.height/2); const d=q('.well.dir');
          return {centres:[c(q('#refDisc')), c(q('#knob')), c(q('.big'))], sizes:[q('#refDisc').width, q('#knob').width, q('.big').width].map(Math.round), drowIn: q('.mod[data-m=dir] .drow').bottom<=d.bottom, listIn: q('#kitList').bottom < q('#vocalRow').top}; })()""")
        check(len(set(m["centres"])) == 1 and len(set(m["sizes"])) == 1, f"{w}x{h}: one centre line, one size", str(m))
        check(m["drowIn"] and m["listIn"], f"{w}x{h}: nothing is clipped", str(m))
        check(not errs, f"{w}x{h}: no script errors", str(errs))
        await pg.close()


async def flows(browser, base):
    print("build, rebuild, license, update, kit list")
    pg, errs = await fresh(browser, base)
    await load(pg)
    await pg.evaluate("startBuild()")
    for _ in range(80):
        await pg.wait_for_timeout(250)
        if await pg.evaluate("S.built"):
            break
    lab = await pg.evaluate("document.querySelector('#buildBtn .a')?.textContent")
    check(lab == "DONE", "a finished build says DONE", str(lab))
    await pg.evaluate("setActive('dir'); stepStyle(1); checkTarget()")
    await pg.wait_for_timeout(900)
    await pg.evaluate("startBuild()")
    for _ in range(80):
        await pg.wait_for_timeout(250)
        if await pg.evaluate("S.built"):
            break
    stopped = await pg.evaluate("!document.getElementById('stopCard').classList.contains('hidden')")
    check(not stopped, "a second build replaces the first in place (no 'empty set' stop)")
    await pg.evaluate("setActive('snd')")
    await pg.evaluate("document.getElementById('kitList').focus()")
    for k in ("ArrowDown", "ArrowDown", "Enter"):
        await pg.keyboard.press(k)
        await pg.wait_for_timeout(120)
    check(await pg.evaluate("!!document.querySelector('#kitList .kl-row.open')"), "the kit list opens a role from the keyboard")
    check(not errs, "no script errors", str(errs))
    await pg.close()

    pg, errs = await fresh(browser, base)
    await pg.evaluate("document.getElementById('statusText').click()")
    await pg.wait_for_timeout(300)
    check(await pg.evaluate("document.querySelector('#gateBox h2').textContent") == "Enter your license key.", "the trial chip opens the key view")
    await pg.fill("#keyInput", "ALMA-abc.def")
    await pg.evaluate("document.getElementById('activateBtn').click()")
    await pg.wait_for_timeout(1100)
    check(await pg.evaluate("document.querySelector('#gateBox h2').textContent") == "Licensed.", "a key activates and the view says Licensed")
    await pg.close()

    pg, errs = await fresh(browser, base, q="update=1")
    await pg.wait_for_timeout(5600)
    check(await pg.evaluate("document.getElementById('updTxt').textContent") == "Restart to update", "the update chip reaches 'Restart to update'")
    await pg.close()


async def main():
    from playwright.async_api import async_playwright
    py = os.path.join(ROOT, ".venv", "bin", "python")
    subprocess.run([py if os.path.exists(py) else sys.executable, os.path.join(ROOT, "tools", "make_demo.py")], check=True, capture_output=True)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass

    handler = functools.partial(Quiet, directory=UI)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        for fn in (toggles, slider, circles, flows):
            await fn(browser, base)
        await browser.close()
    srv.shutdown()
    print(f"\n{'FAILED: ' + str(len(FAILS)) + ' check(s)' if FAILS else 'all checks passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
