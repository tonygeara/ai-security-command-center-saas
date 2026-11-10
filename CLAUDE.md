# Notes for Claude

## Keep the feature documents up to date

Whenever a change to the system adds, removes or changes what it can do (edge app, drone app, portal,
website, Supabase backend), or a pending change is merged or released, update both Google Docs in the
owner's Google Drive folder **camera system** in the same piece of work:

- **AI Security Command Center - Features**: every feature, one sentence each, in tables grouped by area.
  https://docs.google.com/document/d/1IqmfR7E4m7ouDCYfAoszsTAOrEAPtVoItyEKqRYOU1I/edit
- **AI Security Command Center - Capabilities and Improvements**: what the system can do, one sentence
  each, then the improvements list (remove items once done, add new ones).
  https://docs.google.com/document/d/19VJxtGZrK_nf4Gi_p7L3lyTxyoe-C0znRNsP2CjM_gw/edit

Edit the existing docs in place with the Google Docs connector (same links); never replace them with new
files. Update the version line, the totals and the "in pull request" / "not merged yet" markers. If the
Google Docs connector isn't available in the session, say so and list the changes the docs need.

## Repository layout

- `edge/`: the Windows edge app (Python/Flask dashboard, launcher, installer). Tests: `edge/tests` (pytest).
  Version in `edge/app/launcher.pyw` and `edge/app/dashboard.py` (must match); release notes in `releases/`.
- `app/`, `lib/`: the Next.js website, customer portal and admin portal (deployed on Vercel).
- `supabase/`: migrations and edge functions for the production project `qfnxwuejfotofuxlyqjd`.
- `drone-link-android/`: the Drone Link Android app (DJI Mobile SDK v5).
