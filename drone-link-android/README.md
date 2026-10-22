# Drone Link (Android)

Phone app for the DJI controller (RC-N1 with Mini 3 Pro). It connects the drone to AI Security
on the PC: live video, telemetry, and flying from the dashboard's **Drone** page.

```
Drone ⇄ RC-N1 ⇄ Android phone (Drone Link) ⇄ Wi-Fi ⇄ PC (AI Security, port 8765)
```

## 1. Get a DJI App Key (once, free)
1. Sign in or register at https://developer.dji.com/ (top right: Log in / Register).
2. Go to **User Center → Apps → Create App**.
3. Fill in:
   - App Type: **Mobile SDK**
   - App Name: `Drone Link`
   - Software Platform: **Android**
   - Package Name: **`com.aisecurity.dronelink`** (must be exactly this)
   - Category / Description: anything (e.g. "Security monitoring")
4. Confirm the email DJI sends. The app then shows an **App Key**.
5. Create the file `drone-link-android/dji-app-key.properties` containing:
   ```
   DJI_APP_KEY=paste-the-key-here
   ```
   This file is never committed to git.

## 2. Build
```
cd drone-link-android
set JAVA_HOME=C:\Program Files\Microsoft\jdk-17.0.20.101-hotspot
gradlew assembleDebug
```
The app is `app/build/outputs/apk/debug/app-debug.apk`.

## 3. Install on the phone
- On the phone: Settings → About phone → tap **Build number** 7 times → Developer options → **USB debugging** on.
- Connect the phone to the PC by USB and run:
  `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb install -r app\build\outputs\apk\debug\app-debug.apk`
- Or copy the APK to the phone and open it (allow "Install unknown apps").

## 4. First run
1. The phone needs **internet once** so DJI can register the App Key ("DJI SDK: registered").
2. Close DJI Fly (only one app can use the controller at a time).
3. Plug the phone into the RC-N1, turn on the controller and the drone.
4. On the PC: dashboard → **Drone** → a pairing QR code is shown. On the phone tap
   **Scan pairing code** and scan it. Phone and PC must be on the same Wi-Fi.
5. Windows may ask to allow AI Security on the network: allow it on **Private networks**.

## 5. Test in the simulator first (propellers OFF)
Dashboard → Drone → Testing → **Start simulator**. Take off, fly with the keyboard, land.
Then **Stop simulator** before real flights.

## Safety
- STOP on the dashboard (or Space) = hover. **STOP PC CONTROL** on the phone = pilot's sticks take over.
- Pressing the RC's **Pause/RTH** button or moving the flight-mode switch also ends PC control.
- If the PC stops sending (Wi-Fi drop, browser closed) the drone hovers within 0.5 s and control
  returns to the pilot after 1.5 s. DJI's own Return-to-Home still applies on signal loss/low battery.
- Limits enforced on the phone: 120 m height, 500 m from home, speed ≤ 50 %.
- Lebanon: get permission before flying and always keep the drone in sight.
