# DJI Cloud API: Dock support (plan)

Status: **Phase 1 started** (decided 15 November 2026). Drone Link (phone + RC-N1) stays as it is;
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
the PC need this branch merged. Still to do in Phase 1: docks counted in the licence, and health (HMS) alerts. Docks become full drone slots (own Drone page, routes, responses) in Phase 3-4,
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
- `live_start_push` / `live_stop_push` with RTMP to `rtmp://PC:1935/<slot>`; lens switch (wide / zoom /
  **thermal**) and quality from the Drone page.
- Frigate camera per dock slot (same as Drone Link slots), so detection, tracking, evidence and incidents
  work unchanged. The dock's own outdoor camera can be added as a normal camera.

### Phase 3: missions and patrols
- Convert routes (manual routes, Smart patrol from `risk_patrol.py`, patrol schedules) into DJI
  **WPML/KMZ** waylines, served to the dock over HTTP with a checksum; respect no-fly zones (`nofly.py`),
  height/distance limits and `FLIGHT-SAFETY.md`.
- `flighttask_prepare` → `flighttask_execute`, progress events, return home, cancel; preflight checks from
  dock state (wind, rain, battery, cover, drone charged).
- **Alarm response**: a verified alarm (`alarm_verify.py`) or an incident can launch the dock to that spot
  ("fly to point"), stream video and return; confirm-first on Telegram unless auto-start is on.

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
