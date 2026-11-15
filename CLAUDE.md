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

## Releases and deployment

- Edge installers: merging a new `APP_VERSION` to main builds and publishes both editions automatically
  (`.github/workflows/edge-installer.yml`, release `edge-v<version>` with `Online-INSTALL.txt` and
  `On-prem-INSTALL.txt`). Same version again: run the workflow by hand (workflow_dispatch). Each release also gets
  copies without the version in the name and is marked "latest"; the admin portal's Installers section links to
  `releases/latest/download/...`, so it always offers the newest published installers and install guides.
- The admin portal reads the latest version from `edge/app/launcher.pyw` at build time (`next.config.mjs`).
- Supabase migrations and edge functions are applied/deployed directly to production after tests; keep the
  repo copies identical to what is deployed (`supabase/functions/*/license.ts` copies must match).
- Run the edge tests before merging: `edge/tests` (pytest, ~12 minutes; on Linux stub `winsound`).

## Where we left off (15 November 2026)

- Released: Edge **V11.10.1** (15 Nov): on-prem build fix (V11.10.0's on-prem installer missed the dock modules;
  `edge/tests/test_packaging.py` now checks every module is in the on-prem build), on-prem installer renamed
  `On-prem-AI-Command-Centre-Setup-<version>.exe` (app name and install ID unchanged), admin portal links always the
  latest published installers. V11.10.0 (release `edge-v11.10.0`): **DJI Docks** through DJI Cloud API, Phases 1-5
  (registration, health alerts, live video into the AI, route flights, alarm launches with Launch/Don't, scheduled
  patrols, live control, photos/videos saved on the PC), next to Drone Link. Off per client until the **DJI Docks**
  licence switch and a dock count are set (Supabase part live since 15 Nov). Plan and details:
  `docs/DJI-CLOUD-API-DOCK-PLAN.md`. **Not yet flown on a real dock**: do the supervised first flight in
  `docs/DOCK-FIRST-FLIGHT.md` before switching docks on for a client, and fix what it finds (DJI codes, flight plan
  format in `edge/app/dock_wayline.py`, STS token for media).
- Before that: V11.9.0 (one sign-in with portal accounts, every feature a per-client licence switch, Block/Unblock
  client, Users grouped by client, Windows settings-save retry). Website: demo request form (emails via Resend to the
  super admins), no public sign-in/sign-up links (`/login` still works).
- Roles: super admin (owner) > client Admin (manages own Editors/Viewers within the licence's user
  limit) > Editor / Viewer. Super admin manages everything in Admin (Clients, Licences, Devices, Users,
  Demo requests).
- Client install guide also in the owner's Drive folder "camera system":
  https://docs.google.com/document/d/1whSFjy_ZTnXFhiF2wVjt0Z8h2noiIHOTRUtiAJbtB1Y/edit
- Decided: SaaS is the main product, on-prem for offline/no-cloud clients. Skipped for now: Phase 4
  (Lebanese plates, Arabic UI, WhatsApp, power-cut handling), the AI narrator.
- Decided 15 Nov: **DJI Cloud API for Docks** with the MQTT broker on the edge PC; Drone Link (phone + RC-N1) stays.
- Open items are the improvements list in the Capabilities doc (next: the supervised first dock flight, confirm client creation live,
  test with real equipment, leaked-password protection in Supabase, alerts when something breaks,
  automatic backups).
