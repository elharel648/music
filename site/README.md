# Alma site: application, approval, gated download, license keys

Static page (`index.html`) on Netlify + a Supabase project for sign-in, the applicant table, the private download
bucket, and one edge function that issues keys. Nobody downloads anything without a verified email and your approval.

## One-time setup (about 30 minutes, needs your accounts)

### 1. Supabase (free tier)
1. supabase.com → New project. Note **Project URL** and **anon key** (Project Settings › API).
2. SQL Editor → paste `supabase/schema.sql` → Run.
3. Authentication › Providers › Email: keep **Magic link** on, turn **Confirm email** on. Authentication › URL Configuration:
   Site URL = your Netlify URL, add it to Redirect URLs too.
4. Storage: the `releases` bucket is created by the SQL (private). Upload `dist/Alma-0.8.0-mac.dmg` into it.
   Then Table Editor › `releases` → Insert row: `version` = `0.8.0`, `platform` = `mac`, `path` = `Alma-0.8.0-mac.dmg`.
5. Edge function, from the repo root (install the CLI once: `brew install supabase/tap/supabase`):
   ```bash
   supabase login && supabase link --project-ref <ref> && supabase functions deploy issue --project-ref <ref> && supabase secrets set ALMA_PRIVATE_SEED_HEX=$(.venv/bin/python tools/keygen.py export-seed) ALMA_PUBLIC_KEY_HEX=$(grep -o 'PUBLIC_KEY_HEX = "[0-9a-f]*"' flow/license.py | cut -d'"' -f2) --project-ref <ref>
   ```
   (The edge function lives in `site/supabase/functions/issue`; run the command with `--workdir site` if the CLI does not find it.)

### 2. Netlify
New site from Git → repo `elharel648/music`, base directory `site`, publish directory `site`. Custom domain when you have one.

### 3. Paste the two values
- `site/index.html`: `SUPABASE_URL`, `SUPABASE_ANON` (top of the `<script type="module">`).
- `flow/endpoints.py`: the same two. Rebuild the app so feedback from inside Alma lands in the `feedback` table.

## Daily (2 minutes)
- Table Editor › `profiles`: new applicants have `applied_at` set and `approved` unchecked. Read `about` and `link`.
  Tick `approved`. That is the whole approval.
- Tell them (WhatsApp, email): "approved — open the same page, your key and download are there." The page issues the
  key on their next visit; founders (`founding` = true) get a key with no expiry, everyone else 365 days.
- Table Editor › `feedback`: what they heard, with the build that produced it (`payload.plan`, `payload.log`).

## New release
Upload the new DMG to the `releases` bucket, insert a `releases` row with the new version. Approved users see it on
their next visit; the app's own update check uses `packaging/latest.json` (signed, `tools/keygen.py sign-update`).

## What is and is not protected
- Download links are signed and expire after an hour; the bucket is private; only approved + signed-in users get one.
- Keys are Ed25519-signed and verified offline in the app; the private seed exists only in `keys/private.pem` on your Mac
  and as a Supabase secret. Never commit it.
- A beta tester can share the DMG. The app still needs a key after 14 days, and keys carry the email they were issued to.
