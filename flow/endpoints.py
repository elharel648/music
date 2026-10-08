"""Where the packaged app talks to. Filled once the Firebase project exists; empty strings mean "work offline".

FIREBASE_PROJECT = Firebase console › Project settings › General › Project ID
FIREBASE_API_KEY = the web app's apiKey from the same page (public by design; Firestore rules decide what it may do)
SITE_URL         = where the site is published; the app checks <SITE_URL>/latest.json for updates and sends people there
"""
SITE_URL = ""          # the Netlify site, e.g. https://alma.studio (no trailing slash); serves latest.json and the download page
FIREBASE_PROJECT = ""
FIREBASE_API_KEY = ""
