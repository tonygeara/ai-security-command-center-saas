# AI Security Command Center: Windows Edge app

The local half of the platform: a launcher window, the dashboard (Flask, port 8080) and the
local AI services (Frigate, MQTT, MediaMTX in Docker). The cloud portal lives at the repo root.

```
edge/
  app/launcher.pyw        launcher; starts Docker services + dashboard
  app/browser_mode.py     start page in the browser; shut down; optional stop with the browser
  app/audit.py            tamper-evident audit log
  app/store.py            the database (SQLite): events, sightings, audit log, incidents
  app/bus.py              the event pipeline; app/incidents.py groups it into incidents
  app/web_access.py       sign-in, first admin, users (Flask blueprint)
  app/web_records.py      audit log, incidents, evidence packs, browser presence, shut down (Flask blueprint)
  app/evidence.py         signed evidence packs (build and check)
  app/patterns.py         casing and unusual-activity warnings
  app/coverage.py         camera views on the ground, blind spots, suggested camera (Coverage page)
  app/handoff.py          camera-to-drone handoff (off by default)
  app/cloud_sync.py       phone access: incidents and live pictures to the portal (off by default)
  app/dashboard.py        dashboard web app (http://127.0.0.1:8080)
  runtime/                the ONLY Docker setup (versions pinned)
  installer/              build.ps1 -> Setup.exe
```

## Where things live on a PC

| What | Where |
|---|---|
| Program (installed) | `%LOCALAPPDATA%\Programs\AI Security Command Center` |
| Data: Frigate config + database, events, faces, pairing token, logs | `%LOCALAPPDATA%\AI-Security-System` |

Upgrading or uninstalling the program never touches the data folder.

## How it starts and stops

The program has no window by default. Setup adds it to Windows sign-in (`--background`), so it starts
guarding without opening anything. Opening it from the desktop icon opens the browser on a start page
(`http://127.0.0.1:8089`), which moves on to the dashboard when the system is ready; if it already runs,
the dashboard just opens. Closing the browser leaves the system running. **Settings → System → Shut down**
(admins) asks the launcher (`POST :8089/shutdown`) to stop the dashboard and the Docker services. Stopping
with the browser is an option (Settings → System), using the pages' check-ins (`/api/browser/*`).
`--window` (Start menu: "… - Control window") shows the classic control window.

## Data and the event pipeline

Events, sightings of known faces and plates, the audit log and incidents are kept in one SQLite
database, `ai_security.db` in the data folder (WAL mode). On first start of V11.5 the older
`event_history.csv`, `sightings.jsonl` and `audit_log.jsonl` are imported once and renamed `*.migrated`.

Detections (MQTT), saved events, sightings and drone actions are published once on the pipeline
(`bus.py`); subscribers are the incident tracker and auto-dispatch. An incident is everything at one
camera with no more than 5 minutes of quiet in between (Settings → Incidents).

## Evidence packs and patterns

Settings → Incidents → an incident → **Download evidence pack**: a ZIP with the timeline, snapshots, the
drone's photo/video and GPS track (recorded every 2 s during a response), a readable report, and
`manifest.json` listing every file's SHA-256, signed with this PC's Ed25519 key (`evidence_signing.key`
in the data folder, made on first use; never leaves the PC). The pack carries its own checker
(`verify_evidence.py`, also hashed); the Incidents page can check packs too and shows the key fingerprint.

`patterns.py` listens on the pipeline: the same unknown plate on N separate visits within H hours
(casing), and far more people/vehicles than usual for a camera's hour of the week (after two weeks of
history). Warnings go to Telegram and into the camera's incident. Settings → Patterns.

All Telegram alerts (unknown/known faces and plates, patterns) now go through the pipeline ("alert").

## Coverage, handoff and phone access

**Coverage** (Settings → Coverage): each camera placed on the Drone page gets a view here (facing,
width, range). The page draws the views, a coverage heat map over the site outline, the share of blind
spots and the best place for one more camera; clicking a spot shows which cameras see it and can send a
drone there. 4D LIVE draws the views too. Geometry only: walls and trees are not taken into account.

**Handoff** (off by default; Drone page → Drone response, or the Coverage page): every tracked object's
boxes go on the pipeline ("track"); when Frigate ends an object at a camera with a view, the spot just
past where it left (`coverage.exit_point`) gets the nearest ready drone, with the auto-dispatch rules
(people/vehicles, hours, cooldown). The drone hovers there; it does not chase.

**Phone access** (cloud edition, off by default; Settings → System): incidents at "unknown" and above
go to the portal with one snapshot each, through the `edge-sync` function (device token). The portal's
Incidents page can ask for live pictures of a camera: the PC then uploads one every 3 s for as long as
the page is open (requests last 2 minutes and are renewed). Backend: `supabase/migrations/
20261108120000_phone_access.sql`, `supabase/functions/edge-sync`; portal: `app/portal/incidents`.

## Sign-in and audit log

The first visit asks for an admin account (`/welcome`); nothing else answers until it exists. Every drone
action and every change to users, safety and system settings is written to the database's `audit` table,
each record chained to the one before (`app/audit.py`); Settings → Audit log shows and checks it. Records
are kept a year.

## Build the installer

Needs Python 3.13 and Inno Setup 6 (`winget install -e --id JRSoftware.InnoSetup`).

```
powershell -ExecutionPolicy Bypass -File edge\installer\build.ps1
```

Output: `edge\installer\output\AI-Security-Command-Center-Setup-<version>.exe`.
To release a new version, change `APP_VERSION` in both `app/launcher.pyw` and `app/dashboard.py`.

## Run from source (development)

```
%LOCALAPPDATA%\AI-Security-System\venv\Scripts\pythonw.exe edge\app\launcher.pyw
```

Uses the same data folder as the installed app. Stop the installed app first.

## Docker services

The launcher runs `docker compose -p ai-security -f runtime/docker-compose.yml up -d`.
On first start it removes containers left by older versions (same names, other config
folders); their data folders are not deleted. Ports are bound to 127.0.0.1 except
RTMP 1935, which the drone app pushes to over the LAN.

The 3D mapping engine (`nodeodm`, OpenDroneMap) is in the same file under the `mapping` profile, so
`up -d` does not start or download it. The 3D Maps page starts it when a map is first processed
(`docker compose --profile mapping up -d nodeodm`, port 3000 on 127.0.0.1), and the launcher's Stop
also stops it. See [docs/DRONE-3D-MAPS.md](../docs/DRONE-3D-MAPS.md).

Weather, crewed-aircraft (ADS-B), airspace and radio-coverage checks: [docs/FLIGHT-SAFETY.md](../docs/FLIGHT-SAFETY.md).

## Installer from GitHub

GitHub → Actions → **Edge installer** → **Run workflow** builds both installers on Windows machines (the
standard cloud edition and the on-prem "AI Command Centre Lebanon" edition), runs the tests and publishes them as
one release (`edge-v<version>`) under **Releases**; the admin portal's Overview links to them. The on-prem USB
package's offline AI-services file is not built there (run `build_onprem.ps1` on a PC with Docker for that). Pushing a tag such as `edge-v11.2.0` does the
same. Bump `APP_VERSION` in `app/launcher.pyw` and `app/dashboard.py` first; they must match.
