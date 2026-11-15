# DJI Dock: first supervised flight (checklist)

Everything for DJI Docks (V11.10) was built from DJI's Cloud API documentation and tested against a simulated dock.
Before a dock flies by itself on a client site, go through this once with the real dock, in this order, with someone
holding the DJI RC Plus (Pilot 2) the whole time. Stop at the first step that doesn't behave as described and note
what the Drone page, the audit log and Pilot 2 say.

## 0. Before going on site
- [ ] DJI developer account: an app of type **Cloud API** (App ID, App Key, App License).
- [ ] Dock firmware up to date (DJI Pilot 2 → Dock), drone charged, RC Plus charged.
- [ ] The client's licence: **DJI Docks** switched on and **DJI Docks (max)** ≥ 1 (admin portal → licence form;
      on-prem: ticked on a new licence file).
- [ ] Permission for automated flights at this site (Lebanon: DGCA) and an open, clear test area.
- [ ] The PC and the dock on the same network (dock by Ethernet). Windows asked "allow AI Security on the network":
      allowed on **Private networks**. Ports used: **1884** (dock broker), **8767** (Pilot 2 setup page and flight
      plans), **8769** (photos and videos), **1935** (video).

## 1. Connect (nothing flies)
- [ ] Drone page → DJI Docks → **Set up a dock**: paste the three Cloud API values → *Keys saved*.
- [ ] Pilot 2 on the RC Plus (connected to the dock) → Cloud Service → Open Platform → the link or QR code from that
      panel. Expect "Cloud API keys: accepted" and "Connected to the PC".
- [ ] The dock appears under **Found** within a minute; **Register** it. Its card shows cover, drone in dock, battery,
      temperature, wind.
- [ ] Health: unplug the dock's network for 2 minutes → "offline" alert on the page and Telegram, then "back online".

## 2. Video (nothing flies)
- [ ] **▶ Dock camera**: the dock's own picture plays under the cards within ~10 s.
- [ ] **▶ Drone video** with the drone in the dock (if DJI allows it there), lens menu wide/zoom/thermal.
- [ ] Frigate restarted once after registering (about 20 s) and shows a camera named `dock1`.

## 3. First route (short, supervised)
- [ ] Draw a route of **2 stops about 40 m from the dock**, height 30 m, pause 5 s. Save it.
- [ ] Admin: **Automatic flights: ON** (confirm the permission), **Range 100 m** for this test.
- [ ] **🛫 Fly route**. Expect: "route started" on Telegram, the cover opens, take-off within ~60 s, video starts by
      itself, the drone and dashed route on the map, stops reached, return and landing, "finished and is back in the
      dock" on Telegram.
- [ ] Fly it again and press **⏹ Return to dock** halfway: it turns back and lands.
- [ ] If the dock refuses the flight plan: note the message ("The dock refused (flighttask_prepare, DJI code …)").
      That is the flight plan format to adjust (`edge/app/dock_wayline.py`).

## 4. Live control (in the air, supervised)
- [ ] During a route: **📍 Fly to a point** → click the map 30 m away: it goes there and holds.
- [ ] **🎮 Keyboard: ON**, gentle W for a second, release: it stops and holds. Space holds. **Keyboard: OFF**.
- [ ] **📷 Photo**: the photo appears under "Photos and videos from the docks" within a minute.
- [ ] **⏹ Return to dock**.

## 5. Alarm launch
- [ ] Put a camera's place on the map ~50 m from the dock. Dashboard → send the drone to that camera.
- [ ] Telegram (and the Drone page) asks **🚁 Launch / ✋ Don't**: Launch. It flies there at the response height,
      "is over <camera>", hovers for the response time, returns.
- [ ] With drone-verified alarms on: someone walks under it → "Intrusion verified by drone AI".

## 6. Schedule
- [ ] A patrol schedule a few minutes ahead, drone = this dock, "asks first": Telegram asks Start / Skip at that time.

## After the test
- Set the range back to what the site needs (default 500 m).
- Leave **Launch docks without asking** off unless the client explicitly wants fully automatic launches.
- Send the notes (what worked, any DJI codes) so the details can be corrected before other sites use docks.
