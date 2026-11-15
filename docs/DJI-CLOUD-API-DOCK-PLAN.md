# DJI Cloud API: Dock support (plan)

Status: **Phases 1 and 2 built, Phase 3 planned** (decided 15 November 2026; not merged yet). Drone Link (phone + RC-N1) stays as it is;
docks are added next to it as a new kind of drone slot.

Done so far (not merged yet): `edge/app/dock.py` (broker files, hub, MQTT client, Pilot 2 setup page on LAN
port 8767), `edge/app/dock_sim.py` (simulated Dock 3 + Matrice 4TD), the `dock-mqtt` broker in
`edge/runtime/docker-compose.yml` (LAN port 1884, passwords written by the launcher), and the **DJI Docks**
panel on the Drone page (Found → Register, rename, remove; admin setup with Cloud API keys and the Pilot 2
link/QR; simulated dock); registered docks in the Drone page's fleet bar and on its map (dock marker, and the
drone with its height when it is out; a click on either shows the other). Tests: `edge/tests/test_docks.py`.
Licence switch **`drone_dock`** ("DJI Docks"): off for every client until switched on, in the admin portal
(client → Feature access) or ticked on an on-prem licence. Supabase part is live (15 Nov: `set_feature_override`
accepts it; `issue-onprem-license` and `edge-agent-control` redeployed with it in `license.ts`); the portal and
the PC need this branch merged.
Health alerts (`dock.DockHealth`, checked every 5 s): offline (1 min), cover fault, heavy rain, wind ≥ 12 m/s,
≥ 45 °C or ≤ -20 °C, drone in the dock < 20 % and not charging, and DJI HMS cautions/warnings; each with an
all-clear. Shown on the dock cards, in the fleet bar and a Health list on the Drone page, sent to Telegram (text)
and the audit log. DJI's texts are used if their hms.json is put in the data folder, else the code. Simulated
docks have a "Test a problem" menu.
Dock count: "DJI Docks (max)" on the admin licence form; online clients get it as the drone_dock limit, on-prem
licences as limits.docks (column client_licenses.docks and issue-onprem-license live since 15 Nov). The PC refuses
to register more real docks than that (simulated docks don't count); if the licence is lowered, the newest docks
show "over licence" and are no longer watched. A dock has its own drone, so docks don't use the drone count.
Switching a feature on/off in a client's Feature access now keeps its limit. **Phase 1 is complete.** Docks become full drone slots (own Drone page, routes, responses) in Phase 3-4,
when they can fly.

## Goal

A DJI Dock at the client's site, connected to the edge PC, so the system can launch a drone with no pilot:
scheduled patrols, flying to an alarm to check it, and live video into the same AI pipeline (detection,
tracking, evidence, incidents) that Drone Link uses today.

## Hardware

| Dock | Drone | Notes |
|---|---|---|
| **Dock 3** | Matrice 4D / **4TD** (thermal) | Current generation; first choice. |
| Dock 2 | Matrice 3D / **3TD** (thermal) | Previous generation; fine if cheaper. |
| Dock 1 | Matrice 30 / 30T | End of life; avoid. |

Also needed for setup: a DJI RC Plus / RC Plus 2 with DJI Pilot 2 (to configure the dock), wired Ethernet
from the dock to the site's network, and mains power. Before buying, confirm the model on DJI's current
Cloud API "Supported Products" page and check permission rules for automated flights in Lebanon.

Bonus: once Phase 1 exists, enterprise drones flown with **Pilot 2** (Matrice 30T, Mavic 3E/3T,
Matrice 4E/4T) can report to the system the same way, without Drone Link.

## How it fits the current system

```
Dock ──Ethernet── site LAN ── edge PC (AI Security)
                               ├─ MQTT broker (new, bundled Mosquitto, port 1883/8883)
                               ├─ dock.py (new): Cloud API client: telemetry, commands, missions
                               ├─ HTTP endpoints for the dock / Pilot 2 (binding page, wayline files)
                               ├─ go2rtc RTMP :1935/<slot>  ← dock pushes live video here (existing path)
                               └─ Frigate / AI / Drone page (unchanged, slot = "dock1", "dock2"…)
Phone ── RC-N1 ── Mini 3 Pro ──── Drone Link :8765 (unchanged)
```

- The **edge PC hosts the broker**, like it hosts Drone Link today: works the same for the Online and
  On-prem editions, video stays on the LAN, nothing new runs in Supabase. A cloud broker for docks on
  another network is a later option (Phase 6).
- In `dashboard.py` a drone slot gets a `kind`: `link` (phone), `virtual` (simulator) or `dock`. The
  Drone page, grid, HUD, tracking, handoff and patrols read telemetry from the slot as now.
- Licence: a new per-client feature **`drone_dock`** (with a limit = number of docks), added to
  `set_feature_override`, the admin portal's Feature access, the on-prem licence feature list and
  `licensing.py`. Docks count against the licence's drone limit like Drone Link slots.

## Phases

### Phase 0: preparation (owner)
- Register a **Cloud API** app at developer.dji.com (gives App ID, App Key, App License).
- Choose and order the dock (table above). Software work in Phases 1-3 can start before it arrives,
  using a dock simulator.

### Phase 1: connect and see (no flying)
- Bundle **Mosquitto** in both installers; start/stop it with the app; per-site username/password.
- `edge/app/dock.py`: MQTT client (paho-mqtt) for the Cloud API topics: `sys/product/{sn}/status`
  (dock + drone online, topology), `thing/product/{sn}/osd` and `/state` (telemetry, battery, dock
  temperature, wind, rain, cover state), `/events`, `/services` + `/services_reply`, `/requests`.
- **Binding page** served by the edge app for Pilot 2's "third-party cloud" (JSBridge): sets the MQTT
  address and credentials on the dock/RC and binds it to this site.
- Docks appear as drone slots on the Drone page and in Setup → Drones; status, map position, battery,
  weather and dock health (HMS messages turned into alerts).
- `drone_dock` licence feature (Supabase migration + admin portal + on-prem licence).
- `dock_sim.py`: a fake dock publishing on MQTT, for tests (`edge/tests`) and for the virtual drone demo.

### Phase 2: live video into the AI
Status: **built** (15 Nov, not merged yet). The dock reports what it can stream (`live_capacity` on its state topic);
the Drone page's dock card has **▶ Drone video** / **▶ Dock camera**, a lens menu (wide / zoom / thermal) and Stop.
The PC sends `live_start_push` (RTMP to `rtmp://PC:1935/<slot>`), `live_lens_change` and `live_stop_push` on
`thing/product/{gateway}/services` and waits for `services_reply`. Registering a real dock adds a Frigate camera named
after its slot (`dock1`…; removed with the dock), so its picture gets detection, tracking, events and incidents; dock
cameras don't use a camera or drone place on the licence and aren't in the morning "cameras offline" report.
Operators may start/stop video; simulated docks answer the commands but have no picture. To check with hardware: DJI's
exact result codes and camera indexes, and the stream reaching MediaMTX and Frigate.

- `live_start_push` / `live_stop_push` with RTMP to `rtmp://PC:1935/<slot>`; lens switch (wide / zoom /
  **thermal**) and quality from the Drone page.
- Frigate camera per dock slot (same as Drone Link slots), so detection, tracking, evidence and incidents
  work unchanged. The dock's own outdoor camera can be added as a normal camera.

### Phase 3: patrols and alarm launches (the dock flies by itself)
Status: **3a built** (15 Nov, not merged yet); 3c and 3b planned. The first phase where a drone takes off with nobody
on site.

3a as built: `edge/app/dock_wayline.py` (route → KMZ: detours round no-fly zones, height 20-120 m above the dock, speed
1-12 m/s, hover at stops, gimbal 45° down, finish and lost link = return to dock; drone and camera type numbers from
the dock's topology and live_capacity). The KMZ is served once at `http://PC:8767/wayline/<secret>.kmz` (15 min) with
its MD5. `dock.py`: `start_mission` (flighttask_prepare → flighttask_execute, undo if execute fails), `return_home`,
flighttask_progress → mission status/percent/stop. Dashboard: `dock_flight_problem` (pre-flight check),
`POST /api/docks/<sn>/mission` (operators: fly a saved route / return to dock), `POST /api/docks/<sn>/settings`
(admins: Automatic flights with the permission confirmation recorded, range 50-2000 m), `dock_missions_tick` (video
on after take-off, Telegram + audit at the end, video off after landing), docks return home on a crewed-aircraft
threat. Drone page: route picker + Fly route, Return to dock, mission on the card, fleet bar and map. The simulator
downloads and flies the KMZ. Tests: `edge/tests/test_docks.py`.

**Principle: docks join the existing machinery, they don't get a copy of it.** Routes, Smart patrol, patrol
schedules, drone responses (auto-send, handoff, Telegram/dashboard "send a drone") and drone-verified alarms already
pick "a ready drone" through `_pick_drone` / `_route_problem` / `_drone_ready_problem`. A dock becomes one more kind of
drone there, with its own readiness check and its own way of flying. Drone Link drones keep working unchanged.

**How a dock flies a mission: DJI waylines, not live commands.** The PC turns the route into a DJI WPML/KMZ flight plan,
the dock downloads it, and the drone flies it on its own. If the PC, Wi-Fi or internet drops mid-flight, the dock
finishes or returns home by itself (DJI's own lost-link behaviour), which live "go to" commands can't guarantee.
Live steering (fly-to-point, sticks) is Phase 4.

#### Steps
**3a. Fly a route from a dock (started by an operator)**
- `dock_wayline.py`: route → KMZ (`wpmz/template.kml` + `wpmz/waylines.wpml`): stops, height, speed, pause
  (hover action), gimbal down 45°, end action (return to the dock; "hover/land at the last stop" are not offered for
  docks), lost-link action = return home. Height and speed limits from the route; detours round no-fly zones are added
  as extra points, using `nofly.detour` as for Drone Link.
- The KMZ is served on the LAN page server (port 8767) at a one-time secret URL with its MD5 fingerprint.
- Services: `flighttask_prepare` (immediate task, return-home height, out-of-control action = return home) →
  `flighttask_execute`; `flighttask_progress` events (current stop, %, status) shown on the dock card, the map
  (drone position and route) and the existing route status; **Stop** = `return_home`; `flighttask_undo` for a
  prepared task that hasn't started.
- Video starts automatically when the drone leaves the dock (Phase 2), so the AI watches the patrol.
- **Dock pre-flight check** (all must pass; the reasons are shown and logged):
  dock online and registered, within the licence's dock count, `drone_dock` on, the dock's **Automatic flights**
  switch on (see Safety), dock idle (not debugging or updating), cover OK, drone in the dock with battery ≥ the
  response minimum, no active dock health *warning*, dock wind and rain sensors within limits, plus the existing
  checks: weather forecast, crewed aircraft (ADS-B), no-fly zones and airspace, every stop within the dock's range.
- Simulator: the simulated dock "flies" the KMZ (moves the drone along it, sends progress, returns and lands), so the
  whole flow can be tried and tested without hardware.

**3b. Scheduled patrols and Smart patrol from a dock**
- A dock can be chosen as the drone of a patrol schedule, or "any ready drone" includes docks.
- Same confirm-first rule as today: Telegram asks Start / Skip at patrol time unless "start without asking" is on.
- The patrol report (what was seen, photos) goes to Telegram as for Drone Link patrols.

**3c. Alarm launches**
- Wherever the system can send a drone to a camera or a spot (auto-send on detections, camera-to-drone handoff,
  Telegram, the dashboard, the Coverage page), a ready dock can be chosen; "nearest ready drone" counts docks by
  their distance to the target.
- The dock flies a one-stop mission to the camera's location (or the clicked spot) at the response height, hovers for
  the response time with video on, then returns to the dock.
- **Confirm-first by default**: Telegram asks "Launch Roof dock to Gate camera? Launch / Don't" (expires after a few
  minutes). A per-site "launch docks without asking" switch (admins, off by default, with a warning) allows fully
  automatic launches.
- Drone-verified alarms (`alarm_verify.py`) work unchanged: the dock's camera AI can verify the intrusion.
- Air traffic during a flight: the existing crewed-aircraft action becomes **return home** for docks.

#### Safety and permissions
- **Automatic flights switch per dock** (admins, off by default). Turning it on asks the admin to confirm that the
  site has permission for automated flights (Lebanon: DGCA) and records who confirmed and when.
- Range per dock (admins): default 500 m from the dock, like Drone Link; at most 2 km.
- Every launch, stop, return and refusal is in the audit log; operators can launch and stop, admins change settings.
- The pilot-on-site override stays with DJI: Pilot 2 on the RC Plus can always take control.

#### To check with real hardware before using it for real
- KMZ accepted by the dock (WPML version, drone enum values for the Matrice 4TD/3TD, heights relative to the dock).
- Progress event fields, return-home behaviour, and how long prepare → take-off takes (target: under 60 s for alarms).
- First flights: short route over open ground, with someone holding the RC Plus.

#### Order and size
3a first (it carries most of the work: KMZ, mission control, pre-flight, simulator flying), then 3c (alarm launches,
the most valuable for security), then 3b (schedules, mostly wiring). Each step ends with tests, the docs updated and a
commit; nothing flies on real hardware until you've done the first supervised test flight.

### Phase 4: live control from the dashboard
- DRC (drone remote control) mode over MQTT: keyboard/stick control, gimbal, photo/record and fly-to-point
  from the existing Drone page controls, with the same STOP = hover behaviour and limits as Drone Link.
- Take control / give back control, and the pilot-on-RC override where present.

### Phase 5: media
- Photos/videos from missions: the dock uploads to S3-compatible storage with temporary credentials.
  Plan: a local **MinIO** on the edge PC (both editions); optional copy to the cloud later.
  To check: whether Supabase Storage's S3 endpoint can serve the dock's credential request; otherwise keep
  MinIO.

### Phase 6: portal and remote docks (later)
- Docks listed under the client's Devices in the portal with status and health; mission history.
- Optional cloud MQTT broker for docks that are not on the same network as an edge PC.

## Testing
- Unit/integration tests against `dock_sim.py` in `edge/tests` (no hardware).
- With hardware: bind, telemetry, video, a short wayline over the site in a safe area, alarm launch,
  DRC control, weather/no-fly refusals, network loss (dock must return home on its own).

## Open questions
- Which dock and drone to buy (Dock 3 + Matrice 4TD recommended).
- Media storage: local MinIO only, or also in the cloud?
- Lebanon: permission needed for automated (pilotless / beyond-sight) flights.
- Exact topic/service names and firmware versions: check against DJI's current Cloud API docs when
  starting each phase (they change between releases).
