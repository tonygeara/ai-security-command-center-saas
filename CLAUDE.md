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

## Where we left off (24 November 2026)

- **TO PUT BACK: the drones' 500 m distance-from-home limit**, switched off for now on the owner's request (23 Nov,
  V11.19.0): `DRONE_LIMITS["max_distance_m"] = None` in `edge/app/dashboard.py` (set it back to 500; checks, the Drone
  page ring and text follow; update `test_distance_from_home_limit_is_off_for_now`). A reminder to the owner is scheduled
  for 30 Nov 2026 (scheduled task "Re-add the 500 m drone distance limit"). Also on the Capabilities doc improvements list.
- Released and approved 24 Nov (PRs #46, #47; release `edge-v11.19.0`, the first build failed on a Windows-only test port clash fixed in
  `tests/fake_mavlink.py`, then rebuilt by hand): Edge **V11.19.0**: **PX4 / ArduPilot drones over MAVLink** (`mavlink_bridge.py`, pymavlink; each
  `drone-m<N>` slot is a `MavlinkDrone` linked to the PC like a Drone Link phone; saved in `mavlink_drones.json`;
  `/api/mavlink` add/list, `/api/mavlink/<slot>` DELETE, `/api/mavlink/scan` for "Others"; admins only, licence drone
  limit). **Add a drone** page (`/drone-add`, `pages/drone_add.py`, the Drone page's + Add drone opens it): DJI, PX4,
  ArduPilot, MAVLink/MAVSDK, DJI Dock, Virtual ready; Azur, Asylon, Nightingale, Percepto, Sunflower, Autel, FlytBase,
  ROS 2 "on request" (`/api/drone/integration-request` → demo-request edge function); "Others" last (scan). Tests use
  `edge/tests/fake_mavlink.py`. Not yet tried with a real PX4/ArduPilot drone. Also **Remote ID** on Detector drones (`dronedetect.parse_remoteid` / `RemoteIdTracks`):
  receivers send JSON by UDP (switch + port, default 47911, site-network senders only) or HTTP POST
  `/api/remoteid/report` with `X-RemoteID-Token` (open path, token in `drone_detector_settings.json`, admins see it via
  `/api/detector/remoteid-config`, never in settings answers). Remote ID drones = drones `rid:<id>`; one within 40 m of a
  linked drone of ours is that drone; alarm text gives the pilot's position, map shows the pilot. Test sender
  `edge/tools/remoteid_send.py`. **Backup drone switch** (`response_backup`, Drone tab → Drone responses): each response
  also sends the next ready drone (one-stop route "Backup for <camera>", 25 m to the side, +10 m), released home by
  `_release_response_backup` on recall or when the response ends. And the 500 m limit off (above).
- Released and approved 23 Nov (PR #44): Edge **V11.18.1**: Detector drones page fixes: range / on-off / delete weren't saved and renames showed
  the old name (2-s refresh left handlers on stale objects; now looked up by id, list redraw paused only while dragging a
  slider or a select is open). Drag detectors and drones on the map: virtual drone → `uiChoose` Fly there (route to the
  point) / Move there now (new virtual-drone action `move`); real drone → Fly there after a REAL FLIGHT warning (route,
  usual checks). Map frames detectors and drones. `uiChoose(msg, [labels])` added to `pages/dialogs.py`.
- Released and approved 23 Nov (PR #43): Edge **V11.18.0**: Satellite (`satellite`) and Detector drones (`drone_detector`) are per-client licence
  features (off until switched on; Enterprise plan includes both; on-prem licence checkboxes) with Settings → Tabs
  switches (`satellite_tab`, `detector_tab`); `tab_on()` = licensed and switched on; `_tab_gate` blocks pages/APIs,
  nav links hidden, detector idle. Supabase live 23 Nov: migration `20261123120000_satellite_detector_features`
  (set_feature_override accepts them, plan_features), issue-onprem-license v9 and edge-agent-control v18 (FEATURES).
  **doumith has both switched on.**
- Released and approved 23 Nov (PR #42): Edge **V11.17.0**: **Detector drones** tab (`/drone-detector`, `pages/detector.py`, `dronedetect.py`):
  detectors pinned with a range (`drone_detectors.json`), **my drones** list (`my_drones.json`, made when the first
  detector is created; removed drones leave it, new ones are unknown), detection by position (known/virtual drones) and
  by camera with a user-uploaded YOLO ONNX model run by OpenCV DNN (`drone_detector_model.onnx`, every 3 s). Unknown
  drone in range → alarm on every page (`ALARM_HTML` in `pages/dialogs.py`: red overlay + WebAudio siren until
  Acknowledge, `/api/detector/alarm[/ack]`), `speak()` + `warning_sound()` on the PC, Telegram. Tested with 5 virtual
  drones: remove #5, add a new 5th, fly it into a detector → alarm in ~40 s.
- Released and approved 23 Nov (PR #40): Edge **V11.16.0**: Satellite tab → **Live cameras**: public webcams worldwide from the Windy Webcams
  API v3 (`/api/satellite/webcams?bbox=n,e,s,w`, admin-set key in `windy_key.json`, sent by the PC as `x-windy-api-key`,
  cached 5 min because free picture links expire after ~10). Markers + list + viewer (Windy live or timelapse player
  in an iframe), Windy credit on every view. Only owner-published webcams, never exposed private CCTV.
- Released and approved 22 Nov (PR #39): Edge **V11.15.0**: **Satellite** tab next to Dashboard (`/satellite`,
  `pages/satellite.py`, `satview.py`): named pins (`satellite_pins.json`), NASA GIBS imagery in the browser (VIIRS NOAA-20
  / MODIS Terra true colour, fires via GIBS WMS, clouds), day slider (0–30 days), per-pin view; optional NASA FIRMS fire
  alerts within 50 km of each pin (admin-set MAP_KEY in `firms_key.json`, fetched by the PC, never sent to the browser).
- Merged and released 22 Nov (PR #38): Edge **V11.14.2**: self-updates (Check now / Install now / automatic) killed
  themselves: the installer's `taskkill /T` also killed Setup, a child of the program; now `/F /IM` only. CI "Upgrade
  test" now also runs a self-update.
- Merged 22 Nov (PR #36): Edge **V11.14.1**: switching Run patrol off sends those drones home (was: hover).
- Merged 22 Nov (PR #35): Edge **V11.14.0**: **Run patrol** switch beside the Drone Control live view and on the Drone Grid
  (`/api/routes/patrol`, `patrol_mode.json`): every connected/virtual drone flies its own last route (last flown or
  saved on its page) on repeat; STOP / pilot / Stop route leaves that drone alone until the switch is turned on again.
  **Themed dialogs**: every `alert/confirm/prompt` replaced by `uiAlert/uiConfirm/uiPrompt` (edge: `pages/dialogs.py`,
  injected into every HTML page; portal: `lib/dialog.ts`). **Trial countdown** top right + reminder one day before the
  end (edge: from `trial_ends_at` sent by edge-agent-control; portal: `app/portal/layout.tsx`).
- Released: Edge **V11.13.2** (22 Nov): the signed-in role links to that role's dashboard (Windows badge: admins on
  online PCs → portal `/go`; website `/go` sends super admins to `/admin`, others to `/portal`).
- **Plans now set all 13 features** (migrations `20261122120000`, `20261122130000`): Home (4 cameras, phone access,
  replay), Pro (+faces/plates, 1 drone, fly from PC), Business (+3 drones with AI, handoff, Smart patrol, verified
  alarms, 1 DJI Dock), Enterprise (everything, unlimited). A client's own Feature access still wins.
- **14-day free trial** (V11.13.3, PR #33; Supabase part live since 22 Nov, migration `20261122140000`): Trial = Business
  for 14 days (`organizations.trial_ends_at`), then PCs switch off and refuse sign-in (edge-agent-control v17,
  edge-sync v6) and the portal only shows `/choose-plan` (Stripe) until a plan is paid; one trial per email
  (`trial_emails`, manage-users v6). Real Stripe payment through `/choose-plan` not yet tested.
- V11.19.0 approved for Normal clients (24 Nov); doumith is on **Normal**.
- Gran Canaria tender XP1130/2025 (Lot 4): questions only via the Plataforma (deadline passed 20 Nov); bids close 1 Dec.
- Before that: Edge **V11.13.1** (21 Nov, release `edge-v11.13.1`; the V11.13.0 build failed on a Windows file-lock test
  and was never published, so V11.13.1 carries it):
  - Settings → **Updates** (`edge/app/updater.py`, off by default): installs the version the client's **update channel**
    allows, checks GitHub's SHA-256, waits while a drone or dock flies, never downgrades.
  - **Per-client update channels** (admin portal: client page → Updates; Overview → Update channels → Approve):
    Test = newest, Normal = approved version, Pinned = one version. Supabase migration
    `20261121120000_update_channels` applied; `edge-agent-control` v16 returns `updates: {channel, version}`.
    doumith is on **Test**; **V11.13.1 approved** for Normal (21 Nov).
  - Settings → System → **Log out and turn off** (also stops Docker Desktop; the program and Docker start at the next
    Windows sign-in). **Docker Desktop install prompt** when it's missing (`edge/app/docker_setup.py`).
  - No-fly zones save retries on Windows file locks.
  - Not yet tried on real Windows: the silent upgrade, installing Docker (UAC/WSL), stopping Docker.
- Before that: Edge **V11.12.1** (20 Nov, release `edge-v11.12.1`): the version and edition ("V11.12.1 · ONLINE" /
  "ON-PREM") at the top right of every page (`VERSION_LABEL` in `hud_topbar`, `<!--APP_VERSION-->` on the main page).
- Before that: Edge **V11.12.0** (19 Nov, release `edge-v11.12.0`): more DJI Dock control on the Drone page: Look at (map
  click, `camera_look_at`), Aim (video click, `camera_aim`), thermal Temperature readings (IR metering), Orbit (Dock 4
  POI, circle checked against range and no-fly zones), Stop now (emergency stop), dock Siren and Light
  (`/api/docks/<sn>/deterrent`); drone height shown is now above take-off. Unconfirmed on hardware: that emergency stop
  hovers and that siren/light work without debug mode (`docs/DOCK-FIRST-FLIGHT.md` section 8).
- DJI Docks switched on for client **doumith** on 19 Nov (licence switch on, 1 dock).
- Before that: Edge **V11.11.0** (19 Nov, release `edge-v11.11.0`): **DJI Dock 4** with the Matrice 5TD. Dock 4 connects
  through a DJI O4 Ground Station (the gateway; dock 9-131-0 and drone 0-130-0 are its sub-devices), registered by the
  ground station's SN. Battery bays and swaps on the Drone page (Swap battery, `/api/docks/<sn>/battery`), bay-aware
  low-battery and bay-fault alerts, a simulated Dock 4. Not yet flown on a real Dock 4: Dock 4 steps added to
  `docs/DOCK-FIRST-FLIGHT.md`; details in `docs/DJI-CLOUD-API-DOCK-PLAN.md` ("Dock 4").
- Before that: Edge **V11.10.1** (15 Nov): on-prem build fix (V11.10.0's on-prem installer missed the dock modules;
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
- Client install guide (online edition) also in the owner's Drive folder "camera system":
  https://docs.google.com/document/d/1whSFjy_ZTnXFhiF2wVjt0Z8h2noiIHOTRUtiAJbtB1Y/edit . Updated 17 Nov for DJI Docks (19 Nov: Dock 4; 21 Nov: automatic updates, Docker install offer, Log out and turn off)
  (optional dock, allow the app on Private networks, dock setup by an admin, dock media kept 30 days). Keep it and
  `edge/installer/saas-INSTALL.txt` (published with each release as `Online-INSTALL.txt`) the same; the repo copy
  was synced on main (PR #23) and reaches clients with the next release. There is no on-prem guide in Drive; the
  on-prem one is `edge/installer/onprem-INSTALL.txt`.
- Features and Capabilities docs current on 24 Nov (V11.19.0 released and approved 24 Nov; 86 features; 31 capabilities, 20
  improvements; DJI Dock support stays on the improvements list until the first real flight).
- Decided: SaaS is the main product, on-prem for offline/no-cloud clients. Skipped for now: Phase 4
  (Lebanese plates, Arabic UI, WhatsApp, power-cut handling), the AI narrator.
- Decided 15 Nov: **DJI Cloud API for Docks** with the MQTT broker on the edge PC; Drone Link (phone + RC-N1) stays.
- Open items are the improvements list in the Capabilities doc (next: the supervised first dock flight, confirm client creation live,
  test with real equipment, leaked-password protection in Supabase, alerts when something breaks,
  automatic backups).
