"""Run the Alma beta from this Mac: see who applied, approve them (which signs their key), publish a release.

    .venv/bin/python tools/approve.py list                    # applicants waiting, newest first
    .venv/bin/python tools/approve.py approve <email>         # founding producer: key with no expiry
    .venv/bin/python tools/approve.py approve <email> --days 365
    .venv/bin/python tools/approve.py revoke <email>          # approved = false (the key stays valid offline until it expires)
    .venv/bin/python tools/approve.py release 0.8.1 dist/Alma-0.8.1-mac.dmg   # upload + point releases/mac at it
    .venv/bin/python tools/approve.py feedback [--limit 20]   # latest feedback notes

Needs keys/firebase-admin.json: Firebase console › Project settings › Service accounts › Generate new private key.
The license private key is keys/private.pem (tools/keygen.py). Neither file is committed.
"""
from __future__ import annotations
import argparse
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
CRED = os.path.join(ROOT, "keys", "firebase-admin.json")


def fb():
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore, storage
    except ImportError:
        sys.exit("pip install firebase-admin   (into .venv)")
    if not os.path.exists(CRED):
        sys.exit(f"missing {CRED}: Firebase console › Project settings › Service accounts › Generate new private key")
    if not firebase_admin._apps:
        cred = credentials.Certificate(CRED)
        import json
        project = json.load(open(CRED))["project_id"]
        firebase_admin.initialize_app(cred, {"storageBucket": os.environ.get("ALMA_BUCKET", f"{project}.firebasestorage.app")})
    return firestore.client(), storage.bucket()


LINK_DAYS = 30   # a signed download link is valid this long; release/refresh rewrites every approved profile's link


def _signed_link(bucket, db) -> tuple[str, str] | None:
    rel = db.collection("releases").document("mac").get().to_dict()
    if not rel:
        return None
    blob = bucket.blob(f"releases/{rel['path']}")
    url = blob.generate_signed_url(expiration=dt.timedelta(days=LINK_DAYS), version="v4", response_disposition=f'attachment; filename="{rel["path"]}"')
    return url, rel["version"]


def _profile_by_email(db, email: str):
    hits = list(db.collection("profiles").where("email", "==", email.strip().lower()).limit(1).stream())
    if not hits:
        hits = list(db.collection("profiles").where("email", "==", email.strip()).limit(1).stream())
    if not hits:
        sys.exit(f"no applicant with email {email}")
    return hits[0]


def cmd_list(args):
    db, _ = fb()
    rows = [d for d in db.collection("profiles").stream()]
    rows.sort(key=lambda d: str(d.to_dict().get("applied_at") or ""), reverse=True)
    pending = [d for d in rows if d.to_dict().get("applied_at") and not d.to_dict().get("approved")]
    approved = [d for d in rows if d.to_dict().get("approved")]
    print(f"{len(pending)} waiting · {len(approved)} approved · {len(rows)} signed in\n")
    for d in pending:
        p = d.to_dict()
        print(f"  {p.get('email'):34} {p.get('name') or '':20} {p.get('link') or ''}")
        if p.get("about"):
            print(f"  {'':34} {str(p['about'])[:110]}")
    if args.all:
        print("\napproved:")
        for d in approved:
            p = d.to_dict()
            print(f"  {p.get('email'):34} {p.get('name') or '':20} {'founding' if p.get('founding') else ''} key {'yes' if p.get('key') else 'no'}")


def cmd_approve(args):
    from flow import license as lic
    from keygen import load_private
    db, bucket = fb()
    doc = _profile_by_email(db, args.email)
    p = doc.to_dict()
    key = p.get("key") or lic.issue_key(load_private(), p["email"], args.days)
    link = _signed_link(bucket, db)
    doc.reference.set({"approved": True, "approved_at": dt.datetime.now(dt.timezone.utc), "founding": args.days is None, "key": key,
                       "download_url": link[0] if link else None, "download_version": link[1] if link else None,
                       "download_until": dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=LINK_DAYS)}, merge=True)
    print(f"approved {p['email']} ({p.get('name')}) · {'founding, no expiry' if args.days is None else f'{args.days} days'}")
    print(f"tell them: approved — open the same page, your key and the download are there.")


def cmd_revoke(args):
    db, _ = fb()
    doc = _profile_by_email(db, args.email)
    doc.reference.set({"approved": False}, merge=True)
    print("revoked", args.email)


def cmd_release(args):
    """Upload the DMG, point releases/mac at it, and write the signed update manifest the installed apps poll."""
    import json
    from flow import update, endpoints
    from keygen import load_private
    db, bucket = fb()
    name = os.path.basename(args.dmg)
    blob = bucket.blob(f"releases/{name}")
    blob.upload_from_filename(args.dmg, content_type="application/x-apple-diskimage")
    db.collection("releases").document("mac").set({"version": args.version, "path": name, "published_at": dt.datetime.now(dt.timezone.utc)})
    print(f"released {args.version}: gs://{bucket.name}/releases/{name}")
    cmd_refresh(args)
    site = endpoints.SITE_URL or "https://SITE-URL-NOT-SET"
    man = update.sign_manifest(load_private(), args.version, f"{site}/#access", args.notes or "")
    for out in (os.path.join(ROOT, "site", "latest.json"), os.path.join(ROOT, "packaging", "latest.json")):
        with open(out, "w") as f:
            json.dump(man, f, indent=1)
    print("update manifest written to site/latest.json — run `firebase deploy --only hosting` in site/ so it is served; running apps show 'Update' on next launch")
    if not endpoints.SITE_URL:
        print("WARNING: flow/endpoints.py SITE_URL is empty; the manifest points nowhere useful yet")


def cmd_refresh(args):
    """Rewrite every approved profile's signed download link (after a release, or when links are about to expire)."""
    db, bucket = fb()
    link = _signed_link(bucket, db)
    n = 0
    for d in db.collection("profiles").where("approved", "==", True).stream():
        d.reference.set({"download_url": link[0], "download_version": link[1], "download_until": dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=LINK_DAYS)}, merge=True)
        n += 1
    print(f"download links refreshed for {n} approved producers ({link[1]}, {LINK_DAYS} days)")


def cmd_feedback(args):
    from google.cloud.firestore_v1 import Query
    db, _ = fb()
    for d in db.collection("feedback").order_by("created", direction=Query.DESCENDING).limit(args.limit).stream():
        p = d.to_dict()
        print(f"— {p.get('created')} · {p.get('email') or 'trial'} · v{p.get('version')}\n  {p.get('note')}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list"); l.add_argument("--all", action="store_true")
    a = sub.add_parser("approve"); a.add_argument("email"); a.add_argument("--days", type=int)
    r = sub.add_parser("revoke"); r.add_argument("email")
    rel = sub.add_parser("release"); rel.add_argument("version"); rel.add_argument("dmg"); rel.add_argument("--notes", default="")
    f = sub.add_parser("feedback"); f.add_argument("--limit", type=int, default=20)
    sub.add_parser("refresh")
    args = ap.parse_args()
    {"list": cmd_list, "approve": cmd_approve, "revoke": cmd_revoke, "release": cmd_release, "feedback": cmd_feedback, "refresh": cmd_refresh}[args.cmd](args)


if __name__ == "__main__":
    main()
