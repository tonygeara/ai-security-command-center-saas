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

## Keep this file up to date (standing instruction from the owner)

After every change that is merged, released or approved, update "Where we left off" below in the same piece of work:
move the item to "Released and approved <date>", update the approved version, the docs totals and the date heading.
Then get CLAUDE.md onto main without asking: open a pull request with only the CLAUDE.md change and merge it (a
CLAUDE.md-only change builds no installer). Never wait for the owner to ask for it.

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

## Where we left off (28 November 2026)

- **TO PUT BACK: the drones' 500 m distance-from-home limit**, switched off for now on the owner's request (23 Nov,
  V11.19.0): `DRONE_LIMITS["max_distance_m"] = None` in `edge/app/dashboard.py` (set it back to 500; checks, the Drone
  page ring and text follow; update `test_distance_from_home_limit_is_off_for_now`). A reminder to the owner is scheduled
  for 30 Nov 2026 (scheduled task "Re-add the 500 m drone distance limit"). Also on the Capabilities doc improvements list.
- **TO DO BY THE OWNER: verify an email domain for the reports** (Capabilities improvement 14). Reports by email are
  released (V11.27.0), but Resend's test sender only reaches the Resend account's own address: verify the website's domain
  in Resend and set `REPORT_FROM_EMAIL` (e.g. `AI Security Command Center <reports@…>`) as a secret of the edge-sync
  function. Until then PCs say "email is not set up yet by your provider". The page-tour list of 28 Nov is otherwise done.
- Released and approved 28 Nov (PRs #73, #71 closed and reopened as #73; release `edge-v11.27.0`): Edge **V11.27.0**:
  **reports by email** (Settings → Reports → Email, online PCs paired with the portal): `reports.py` `email: {on, to[]}`;
  `report_email_available()`, `_edge_sync()`, `send_report_email()` in `deliver_report()` (problems in the reply, Drone page
  events and audit; the report is still kept and sent to Telegram); `/api/reports/people` (admins, `ADMIN_ONLY_READ`).
  Cloud: edge-sync **v7** (deployed 28 Nov, repo copy identical): `report_people` (the company's portal accounts, blocked
  ones left out) and `report_email` (only those addresses → `not_member`, trial over → `trial_expired`, PDF ≤ 4 MB, 12 a
  day per PC counted in `audit_logs` `report_emailed`, Resend from `REPORT_FROM_EMAIL` / `DEMO_FROM_EMAIL` / test sender,
  sender refusal → `sender_not_verified`). Test `test_reports_by_email_through_the_portal`.
- Released and approved 28 Nov (PR #70, release `edge-v11.26.0`): Edge **V11.26.0**: duplicates merged and the same words.
  One Add a drone list (`/drone-add` gained "DJI Fly live stream (video only)", RTMP via `/api/setup/drone(s)`; the Devices
  tab's Drone tab, `#drone` and the Dashboard's + Add drone open it). Settings → AI & devices = the Dashboard's working
  switches (`/api/camera|drone|drone/tracking|object_ai/*`; the old saved `camera_ai`/`face_ai`/`lpr`/`drone_*` keys were
  never read); "Object AI" → "Other objects list". GPS dispatch panel and `/api/gps-dispatch/*` removed (never flew; camera
  positions only on the Drone page). Settings tile "Incidents & events" (pages link each other; Dashboard Event history →
  `/settings/events`). PC Users page lists portal accounts (`/api/users` → `portal`, `portal_users` from `_portal_load`).
  Admin portal: Clients is the one list ("No details yet" filter, Revoke on the client page via `RevokeLicense.tsx`);
  `/admin/licenses` is only the form (redirects to Clients without new/edit/renew/org); no Licences menu item.
  Wording: "Licence" in visible edge text, guides and messages (`licensing.py` reasons; keys, routes, file names and
  DJI's "App License" unchanged); "AI Security Command Center" on the website; Licence page shows the online licence on
  paired PCs (`/api/license` → `online` from `_online_licence()`); portal "Features" card (plan_features + overrides);
  voice asks for the "number plate". Tests `test_merged_pages.py`.
- Released and approved 28 Nov (PR #68, release `edge-v11.25.1`): Edge **V11.25.1**: (1) one-off trips keep the drone's patrol
  route: `fly_route(..., oneoff=True)` skips `remember_last_route` (response backup, intercept "Watch …", and `/api/routes/fly`
  with `"oneoff": true` from Fleet Send to and map drags on Fleet / Drone page / Detector drones). (2) Admin portal version
  list: the repo is public; GitHub's unsigned limit (60/h per address, shared on Vercel) emptied it. `lib/releases.ts`
  (parser, URL), `lib/useEdgeVersions.ts` (the admin's browser fetches it when the server got none), optional
  `GITHUB_TOKEN` on Vercel. Tests in `test_fleet.py`.
- Released and approved 28 Nov (PR #66, release `edge-v11.25.0`): Edge **V11.25.0**: **Reports** (Settings tile → `/reports`,
  `pages/reports.py`; `edge/app/reports.py` settings / schedule / figures / text / PDF layout; `edge/app/pdfmini.py` small
  PDF writer, Helvetica/WinAnsi so non-Latin text shows "?"). Daily / weekly (weekday) / monthly (day, clamped) with times,
  ticked sections, compared with the previous period; `deliver_report()` saves `DATA/reports/<kind>-report-<date>.pdf`
  (kept 400 days) and `send_report_telegram()` (sendMessage + sendDocument via `_tg`, bypasses intruder-warnings-only).
  `_reports_worker` replaced `_briefing_worker` (late limits daily 2 h, weekly 2 d, monthly 5 d; `mark_handled` on first
  start and on save; daily tidy: sightings, reports, logs). Until first saved, daily follows `briefing_enabled/time`. New logs
  (`_report_tracker_worker`, 400 days): `flight_log.jsonl` (`_track_flights`, ≥15 s), `detector_alarms.jsonl`
  (`_detector_event`), `uptime_log.jsonl` (every 10 min: PC minutes, cameras with no picture). API `/api/reports` (GET all,
  POST admins), `/api/reports/send` (operators), `/api/reports/preview`, `/api/reports/file/<name>` (`NAME_RX`). Drone
  page briefing fields → link to Reports; "Send daily report now" (`/api/assistant/briefing`). Tests `test_reports.py`.
- Released and approved 27 Nov (PR #63, release `edge-v11.24.0`): Edge **V11.24.0**: (1) **Detectors switch on the Fleet page**
  (`flDet`, localStorage `fleetDetectors`; `/api/fleet` → `detectors: {on, detectors[{…, sees}], unknown}` from
  `_fleet_detectors()`, empty while the Detector drones tab is off): range circles (green, red while it sees an unknown
  drone, dashed when off) and unknown drones. (2) **Fly despite the weather, after asking**: `flight_conditions(loc,
  ignore_weather)` turns weather problems into warnings (crewed aircraft still block); routes: `fly_route(...,
  ignore_weather)` answers `weather_override: true` when only the weather blocks, `/api/routes/fly` takes `ignore_weather`
  (kept in the run for backup hand-over); take-off: `can_force` / `args.force` now weather-only. Pages use `uiFly(url, body)`
  / `uiWeatherOk(d)` from `pages/dialogs.py` (Fleet, Drone, Detector drones). Audit "drone: flight / take-off despite the
  weather". Automatic flights never override. Tests `edge/tests/test_weather_override.py`.
- Released and approved 27 Nov (PR #61, release `edge-v11.23.0`): Edge **V11.23.0**: **Fleet** tab (`/fleet`, `pages/fleet.py` BODY, nav "Fleet") and a **Fleet card on
  the Dashboard** (`pages/fleet.py` CARD, injected at `<!--FLEET_CARD-->` in `pages/main_page.py`). `/api/fleet`
  (`_fleet_drone`): per drone job (patrol / response / watching / backup / standby / flying / ready / offline), job text,
  target with `distance_m` (route stop: the run counts stops from 1, so stop = `index - 1`; response camera; intruder), live
  position, battery, height, speed, heading, current route, patrol route (`last_route_of`), pin; plus docks, intruders,
  no-fly zones. `/api/fleet/stop-all` (hover every flying drone, routes stopped) and `/api/fleet/home-all` (intercepts
  released, response recalled, routes `stop_home`, else `_go_home_safe`); both hold Run patrol for those drones; operators
  and admins. Page: per-drone Take off / Hover / Home / Land / Send to (map click) / Patrol route editor (click stops, drag
  them, height, speed, repeat → `POST /api/routes?drone=` saves it as that drone's route, optionally fly now) / Fly patrol /
  Stop route / Find / Open; drag a drone (virtual: fly or move now; real: REAL FLIGHT fly there; offline: move pin);
  filters; Send ticked drones to a spot (20 m apart). Tested with virtual drones.
- Released and approved 27 Nov (PRs #58, #59; release `edge-v11.22.2`, the first build failed on a Windows file lock in
  `mapping._write_json`, fixed by `_replace` retries in `mapping.py` and `dronedetect.py`, then rebuilt by hand): Edge
  **V11.22.2**: distance lines on Detector drones: detector→drone lines labelled with the distance (`dt-dist`);
  `intercept_status()` returns each of our drones' live position, height and `distance_m` to the intruder; `drawChase()`
  draws a blue dashed line from each drone sent (backup included) to the intruder, labelled "<drone> · <distance>".
- Released and approved 26 Nov (PR #57, release `edge-v11.22.1`): Edge **V11.22.1**: drones on the Drone page's **3D MAP** view (`pages/maps.py`, embedded as
  `/maps-embed?drone=<slot>`): `loadDrones()` every 2 s from `/api/drone/links` + `/api/drone/pin` draws every live drone
  (page's own drone big and blue with a permanent label, others orange) and pinned drones (dashed); `focusDrone(slot)`
  used by the parent's Find drone and when the 3D view is switched on. The full /maps page shows them too.
- Released and approved 26 Nov (PR #55, release `edge-v11.22.0`): Edge **V11.22.0**: (1) **Telegram: intruder warnings only** (customer setting `telegram_intruders_only`,
  default **on**, Settings → System): `_telegram_allowed()` gates `send_telegram` (new `warning=` arg), `queue_telegram_alert`
  (passes only `INTRUDER_ALERT_KINDS` unknown_face / unknown_vehicle / verified_alarm) and `send_telegram_album`; always
  sent: warnings (`warning=True`: unknown-drone detector alarms, "person seen, drone sent"), questions (messages with
  buttons) and replies to the owner (`_tg_reply.on` set in the Telegram poller). `_send_telegram_real` kept for tests.
  (2) **Drone page map** (`pages/drone_control.py`): `ensureMap()` always shows the map (drone → pin → site → last view →
  world); **Find drone**; **Pin drone** (`/api/drone/pin`, `drone_pins.json`, dashed marker, routes measured from it, also a
  `_site_location` fallback); drag the drone (`dropDrone`: virtual → fly / move now, real → REAL FLIGHT fly there, pin →
  move pin); map 360 px; `IS_VIRTUAL` injected by `drone_control_page`.
- Released and approved 25 Nov (PR #53, release `edge-v11.21.0`): Edge **V11.21.0**: **send drones to an unknown drone** (Detector drones panel "Send drones to an unknown
  drone"; `dashboard.py`: `intercept_start` / `intercept_tick` / `intercept_release` / `intercept_status`, `_intercept`;
  settings `intercept_auto`, `intercept_drones` (none: nearest ready drone of ours), `intercept_alt_m` 50,
  `intercept_standoff_m` 40). Called from `detector_tick` for every intruder seen (position, Remote ID, sensor fix keyed by
  place `fix@…`, camera-only → the detector's spot `cam:<id>`): one-stop routes named "Watch <label>" (`fly_route`, usual
  checks, end hover), on the drone's own side at the hold distance, +5 m per extra drone; follows when it moved ≥40 m (every
  ≥10 s); home (`stop_home` / `_go_home_safe`) after 60 s unseen, 15 min, or Recall. API `/api/detector/intercept` POST
  send now / DELETE recall (operators, admins). Tested with virtual drones only.
- Released and approved 25 Nov (PR #51, release `edge-v11.20.1`): Edge **V11.20.1**: Detector drones map drawn like a live radar (`pages/detector.py`: `drawRadar`, `sweep`;
  `radarLayer` under the pins): radar-green circle (`RADAR_GREEN` #29ff7a) with rings at 1/3 and 2/3 and cross-lines, a
  sweep wedge turning every `SWEEP_MS` 4 s (40° fading trail, ~20 fps, paused when the tab is hidden); red (`RADAR_RED`)
  while the detector sees an intruder; switched-off detectors dashed, no sweep. Pins green (acoustic orange, RF purple).
- Released and approved 24 Nov (PR #49, release `edge-v11.20.0`): Edge **V11.20.0**: **acoustic and passive RF drone sensors** on Detector drones. A detector's `sensor`
  is "" / "acoustic" / "rf" (`dronedetect.SENSOR_KINDS`); sensors report JSON (`{"sensor": name or id, "detected",
  "confidence", "bearing", "distance_m", "type", "protocol", "freq_mhz", "rssi_dbm"}`) on the Remote ID UDP port or HTTP
  `/api/sensors/report` (open path, same token, `X-Sensor-Token`); `dronedetect.split_payload` separates sensor and
  Remote ID messages; `SensorHits` keeps each sensor's latest report (8 s); `locate()` crosses two sensors' bearings
  (within both ranges, not near-parallel) or uses one sensor's distance → drones `fix:<n>` (estimated, no alarm of their
  own); a sensor that starts hearing (quiet 60 s before, confidence ≥ `sensor_min_conf` 0.6) raises the alarm (kind
  acoustic / rf) unless its bearing points (±12°) at one of our flying drones in range. Test sender
  `edge/tools/sensor_send.py`. Listening only, no jamming. Not yet tried with real sensors.
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
  edge-sync v6, now v7) and the portal only shows `/choose-plan` (Stripe) until a plan is paid; one trial per email
  (`trial_emails`, manage-users v6). Real Stripe payment through `/choose-plan` not yet tested.
- V11.27.0 approved for Normal clients (28 Nov); doumith is on **Normal**.
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
- Features and Capabilities docs current on 28 Nov (V11.27.0 released and approved 28 Nov; 90 features; 31 capabilities, 20
  improvements; DJI Dock support stays on the improvements list until the first real flight).
- Decided: SaaS is the main product, on-prem for offline/no-cloud clients. Skipped for now: Phase 4
  (Lebanese plates, Arabic UI, WhatsApp, power-cut handling), the AI narrator.
- Decided 15 Nov: **DJI Cloud API for Docks** with the MQTT broker on the edge PC; Drone Link (phone + RC-N1) stays.
- Open items are the improvements list in the Capabilities doc (next: the supervised first dock flight, confirm client creation live,
  test with real equipment, leaked-password protection in Supabase, alerts when something breaks,
  automatic backups).
