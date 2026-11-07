# AI Security Command Center: Windows Edge app

The local half of the platform: a launcher window, the dashboard (Flask, port 8080) and the
local AI services (Frigate, MQTT, MediaMTX in Docker). The cloud portal lives at the repo root.

```
edge/
  app/launcher.pyw        launcher; starts Docker services + dashboard
  app/browser_mode.py     start page in the browser; stops the system when the browser closes
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

The program has no window by default: it opens the browser on a start page (`http://127.0.0.1:8089`), which
moves on to the dashboard when the system is ready. Each dashboard page checks in (`/api/browser/*`); when no
page has been open for 15 seconds the launcher stops the dashboard and the Docker services and exits.
`AI-Security-Command-Center.exe --window` (Start menu: "… - Control window") shows the control window instead
and never stops on its own. A start error also opens the window.

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
