"""Assemble site/.deploy and publish it. Until launch the root is a holding page; the real site lives under a private path.

    .venv/bin/python tools/deploy_site.py            # private: holding page at /, site at /p/<token>/
    .venv/bin/python tools/deploy_site.py --public   # launch: the site at /
The token lives in keys/site-token (created once, never committed). latest.json is always at the root.
"""
import os, secrets, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE, OUT = os.path.join(ROOT, "site"), os.path.join(ROOT, "site", ".deploy")
TOK = os.path.join(ROOT, "keys", "site-token")
public = "--public" in sys.argv
if not os.path.exists(TOK):
    os.makedirs(os.path.dirname(TOK), exist_ok=True); open(TOK, "w").write(secrets.token_urlsafe(9))
token = open(TOK).read().strip()
shutil.rmtree(OUT, ignore_errors=True)
files = ["index.html", "mark.svg", "img", "demo"]
dest = OUT if public else os.path.join(OUT, "p", token)
os.makedirs(dest, exist_ok=True)
for f in files:
    s, d = os.path.join(SITE, f), os.path.join(dest, f)
    shutil.copytree(s, d) if os.path.isdir(s) else shutil.copy(s, d)
if not public:
    html = open(os.path.join(dest, "index.html")).read().replace("<head>", '<head>\n<meta name="robots" content="noindex,nofollow">', 1)
    open(os.path.join(dest, "index.html"), "w").write(html)
    shutil.copy(os.path.join(SITE, "holding.html"), os.path.join(OUT, "index.html")); shutil.copy(os.path.join(SITE, "mark.svg"), OUT)
for f in ("latest.json",):
    if os.path.exists(os.path.join(SITE, f)): shutil.copy(os.path.join(SITE, f), OUT)
r = subprocess.run(["firebase", "deploy", "--only", "hosting", "--project", "alma-e5db0", "--non-interactive"], cwd=SITE, capture_output=True, text=True)
print("deployed" if "Deploy complete" in r.stdout else r.stdout[-800:] + r.stderr[-800:])
print("root: https://alma-e5db0.web.app/  (holding page)" if not public else "root: https://alma-e5db0.web.app/")
if not public: print(f"private site: https://alma-e5db0.web.app/p/{token}/")
