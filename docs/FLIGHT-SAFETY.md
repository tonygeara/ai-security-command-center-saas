# Flight safety

The flight-safety checks (summary in one row at the top of the **Drone** tab; full settings via
**⚙ Flight safety settings** there, or **Settings → Flight safety**) are the checks made before every automatic flight
(routes, scheduled patrols, alert responses, 3D-map surveys) and before take-off from the PC. A blocked take-off
from the Drone page can be overridden after a confirmation; automatic flights cannot. The pilot stays responsible:
the checks help, they don't replace looking at the sky.

| Check | Source | Without internet |
|---|---|---|
| Weather | [Open-Meteo](https://open-meteo.com) forecast, free, no key: wind at 10 m and 80 m, gusts, rain/snow/thunder, visibility, temperature. Cached 10 minutes | "Weather unknown": allowed by default, or blocked if *Don't fly when the weather is unknown* is ticked |
| Crewed aircraft | ADS-B: online from [airplanes.live](https://airplanes.live), or a local USB receiver running readsb / dump1090 / tar1090 (enter its `aircraft.json` address) | Local receiver works offline. Online: "no traffic data", allowed by default |
| Official airspace | Airports and heliports from [OurAirports](https://ourairports.com) (public domain) as no-fly circles. Airspace polygons from a GeoJSON file (openAIP, aviation authority) | Import `airports.csv` or a GeoJSON file with *Import a file*. The downloaded list is kept for re-imports |
| Radio coverage | Link budget from the controller position, terrain from Open-Meteo's elevation model (90 m), cached | Open ground assumed |
| Shortest route | *Shortest order* on the Drone page: nearest-neighbour + 2-opt, distances measured round no-fly zones, from the home point | Works offline |

## Weather limits (defaults)

Wind 10 m/s (ground or 80 m), gusts 13 m/s, no rain/snow/thunderstorm, visibility 1 km, −10 to 40 °C.
*When outside limits*: **Don't fly** (default) or **Fly, warn** (the route starts and the warning is shown and logged).

## Crewed aircraft

An aircraft is a threat when it is within the alert radius (default 3 km) and below the alert height (default
2000 ft above the site, using the site's ground height from the elevation model). While drones are flying:

- the chosen action runs once per aircraft: **descend to 15 m and hover** (default), **land**, **return home**, or **warn only**;
- any route or response the drone was flying is stopped first;
- a Telegram alert is sent, and the event is logged on the drone.

While a threat is present, take-off and automatic flights are refused (*Don't take off while an aircraft is close*).
Not every helicopter or light aircraft sends ADS-B, so keep watching and listening.

## Official airspace

Default circles: large airport 8 km, medium 5 km, small 3 km, heliport 1 km, seaplane base 2 km. These are cautious
defaults, **not** the law: check the national rules (Lebanon: DGCA). GeoJSON airspace whose floor is above 500 ft is
skipped. A zone can be marked **authorised** (switched off) when the site has permission. Re-importing keeps that
setting. If the site itself is inside an imported zone, the import says so, and every flight is refused until it is
authorised.

Imported zones work like drawn no-fly zones: routes crossing them are refused, auto-fly and return home fly round them,
and you get a warning if a drone flown by hand enters one. They appear on the Drone page map. They are managed only on
Flight safety.

## Radio coverage

`received = EIRP + antenna gain − free-space loss − terrain diffraction (ITU-R P.526 knife edge)`, compared with
the receiver sensitivity. Good ≥ 15 dB margin, weak ≥ 6 dB, else poor. Defaults: 2.4 GHz, 20 dBm EIRP (CE),
−100 dBm sensitivity, controller at 1.5 m. *Show coverage* colours the 500 m range round the controller.
*Check signal* on the Drone page checks each route stop and the middle of each leg. The model knows hills, not
buildings, trees or interference: walk the site to confirm. The phone-to-PC Wi-Fi link is not modelled.

## Files

In the data folder: `flight_safety.json` (settings, site and controller positions), `airports.csv` (OurAirports),
`elevation_cache.json`. Imported zones are stored with the drawn ones in `nofly_zones.json`, with `source` and `enabled`.

## Roles

Operators may use *Shortest order* and *Check signal*. Only admins change limits or import and authorise airspace.
