# Drone 3D site maps

The **3D Maps** tab of the Windows edge dashboard turns a drone flight into:

- a **3D textured model** of the site, viewed in the browser: turn, zoom, top view, and **measure** distances and heights;
- an **orthophoto**: an up-to-date, map-accurate aerial photo shown over the satellite map;
- a PDF **processing report**.

The images are processed on this PC (or another computer you choose) by
[OpenDroneMap](https://opendronemap.org) (NodeODM, free and open source). Nothing is sent to the cloud.

## How it works

1. **Draw the area** on the map and pick the height (default 40 m) and overlap. The page plans a lawn-mower grid
   along the area's longest side and shows the flight lines, number of images, flight time and detail (cm per pixel).
2. **Fly.** The survey is flown as a route, so the usual safety rules apply: drone-control licence, 500 m from home,
   no-fly zones (with detours), the lost-link action (return home), and the drone's low-battery protection. With a
   backup drone it hands over at 25% battery. The gimbal points straight down. Every few metres along the grid
   (the forward overlap), the PC saves a frame from the drone's live video together with the drone's GPS position
   and height (`geo.txt`). Stopping a flight and flying again adds more images.
3. **Optional: full-resolution photos.** Tick *Also take full-resolution photos*: the drone takes a photo on its SD
   card at each capture point (it flies a little slower). After landing, use **Import photos** to add them. Photos
   are about 12 MP against about 0.7 MP for video frames, so the model is much sharper. Each photo carries its own GPS.
4. **Process.** Images are uploaded to the engine in batches. Progress shows on the page, and Telegram says when
   the map is ready. Processing carries on across a dashboard restart. A map takes roughly 10–60 minutes,
   depending on the number of images, the quality setting and the PC.
5. **Open 3D / Report**, or tick *Show the finished aerial map* to see the orthophoto on the map.

## Mapping engine

- Local (default): the `nodeodm` service in `edge/runtime/docker-compose.yml`, profile `mapping`, image pinned
  (`opendronemap/nodeodm:3.6.2`). It is **not** in the normal start: the first processing starts it, which downloads
  it (several GB) the first time. Its working data lives in `%LOCALAPPDATA%\AI-Security-System\mapping-engine`.
- Another computer: run `docker run -p 3000:3000 opendronemap/nodeodm` there and enter `http://<its IP>:3000`
  under *Mapping engine*. Use this for large sites or a slow PC.

## Data

`%LOCALAPPDATA%\AI-Security-System\maps\<id>\`: `survey.json`, `frames\`, `photos\`, `geo.txt`,
`result\model` (OBJ/MTL/texture), `result\tiles` (orthophoto tiles), `result\report.pdf`.
**Delete** on the page removes all of it.

## Roles

Operators may plan, fly, import photos and process maps. Only admins delete maps. Viewers can open them.

## Limits and tips

- At most 60 flight lines (120 waypoints) per map. Fly higher or split the site.
- At least 5 images are needed; 50+ with 75%/70% overlap gives good results. Use 85%/80% around buildings.
- Video frames come from the drone's live stream to this PC: check *Drone* shows video before flying.
  Virtual drones have no camera, so they rehearse the flight without capturing images.
- Fly in steady light and low wind; avoid flying over water or large plain surfaces only.
