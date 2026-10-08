"""Where the packaged app talks to. Filled once the Firebase project exists; empty strings mean "work offline".

FIREBASE_PROJECT = Firebase console › Project settings › General › Project ID
FIREBASE_API_KEY = the web app's apiKey from the same page (public by design; Firestore rules decide what it may do)
"""
FIREBASE_PROJECT = ""
FIREBASE_API_KEY = ""
