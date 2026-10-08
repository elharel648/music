# Alma site: application, approval, gated download, license keys — all on Firebase

Static page (`index.html`) on Firebase Hosting + the same Firebase project for sign-in (email link), the applicant table (Firestore),
the private download (Storage) and feedback from inside the app. Keys are signed on your Mac by `tools/approve.py`;
no Cloud Functions, no Blaze plan, no card. Nobody downloads anything without a verified email and your approval.

## One-time setup (about 20 minutes)

### 1. Firebase (console.firebase.google.com)
1. Add project (or reuse one). **Authentication › Sign-in method › Email/Password → enable, and turn on "Email link
   (passwordless sign-in)"**.
2. **Firestore Database → Create** (production mode). Rules tab → paste `firebase/firestore.rules` → Publish.
3. **Storage → Get started**. Rules tab → paste `firebase/storage.rules` → Publish.
4. **Project settings › General › Your apps → Web app (</>)**, register "alma site", copy the `firebaseConfig` block into
   `site/index.html` (top of the module script). Copy `apiKey` and `projectId` into `flow/endpoints.py` too.
5. **Project settings › Service accounts → Generate new private key** → save as `keys/firebase-admin.json` (never committed).
6. `uv pip install --python .venv/bin/python firebase-admin` (already done on this Mac).

### 2. Hosting (same project, one command)
Install the CLI once (`brew install firebase-cli`), then from the repo root:
```bash
cd site && firebase login && firebase use <project-id> && firebase deploy
```
That publishes the page at `https://<project-id>.web.app`, and the Firestore + Storage rules from `firebase/` in the same go
(so step 1.2/1.3 can be skipped). The `*.web.app` domain is already an authorized sign-in domain. Custom domain: Hosting ›
Add custom domain, then add it under Authentication › Authorized domains. Put the final URL in `flow/endpoints.py` → `SITE_URL`.

### 3. First release
```bash
.venv/bin/python tools/approve.py release 0.8.0 dist/Alma-0.8.0-mac.dmg
```
Uploads the DMG to `releases/`, points `releases/mac` at it, and writes the signed `site/latest.json`; run `firebase deploy`
in `site/` so installed apps see the update. Rebuild the app after filling `flow/endpoints.py` so feedback lands in Firestore.

## Daily (2 minutes)
```bash
.venv/bin/python tools/approve.py list              # who is waiting, with their note and link
.venv/bin/python tools/approve.py approve someone@x.com        # founding producer: key with no expiry
.venv/bin/python tools/approve.py approve someone@x.com --days 365
.venv/bin/python tools/approve.py feedback          # what they heard, newest first
```
Approve signs the key with `keys/private.pem` and writes it into their profile. Tell them (WhatsApp, email):
"approved — open the same page, your key and the download are there."

## What is and is not protected
- The DMG is readable only by a signed-in user whose profile says `approved: true` (Storage rules check Firestore).
- Keys are Ed25519-signed and verified offline in the app; the private key exists only in `keys/private.pem`.
- Users can edit their own application but cannot set `approved`, `founding` or `key` (Firestore rules).
- Feedback is create-only for the public API key; only the console (and `approve.py feedback`) reads it.
- A beta tester can pass the DMG on. The app still needs a key after 14 days, and keys carry the email they were issued to.
