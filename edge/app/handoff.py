"""Camera-to-drone handoff: when someone leaves a camera's view, a drone goes to where they went.

Off until the owner switches it on (Drone page → Drone response, or the Coverage page). It follows
the same rules as auto-dispatch: the person/vehicle choices, the time window and the per-camera
cooldown, and only cameras with a place and a view on the map (Coverage page) take part.

How: the pipeline carries every tracked object's box ("track" messages from Frigate). When Frigate
says an object ended (left the picture), its first and last boxes and the camera's view give a rough
spot on the ground just past where it left (coverage.exit_point). The nearest ready drone flies
there, round no-fly zones, and hovers with its camera on it, like any drone response (it does not
chase). The incident shows the handoff; Telegram gets a message with a Recall button.
"""
import threading
import time

VEHICLES = ("car", "motorcycle", "truck", "bus")
MIN_SEEN_S = 2.0     # ignore objects seen for less than this (flicker, false starts)
MAX_OBJECTS = 2000


class Handoff:
    def __init__(self, settings, cameras, frame_size, send, publish, in_window, allowed, run_async=True):
        self.settings = settings        # () -> response settings
        self.cameras = cameras          # () -> {camera: {"lat", "lon", "view"}}
        self.frame_size = frame_size    # (camera) -> (width, height)
        self.send = send                # (lat, lon, by) -> {"ok", ...}
        self.publish = publish          # (kind, **data)
        self.in_window = in_window      # (start, end) -> bool
        self.allowed = allowed          # () -> bool (licence lets the PC fly)
        self.objects = {}               # object id -> {"camera", "label", "first", "last", "t0", "t1", "moved"}
        self.last_at = {}               # camera -> time of the last handoff
        self.log = []                   # recent decisions (for the page and tests)
        self.run_async = run_async      # sending waits for the drone's answer: never hold up the pipeline

    def attach(self, bus):
        bus.subscribe("track", self.on_track)

    def _note(self, text):
        self.log = (self.log + [{"t": time.time(), "text": text}])[-20:]

    def on_track(self, m):
        oid, box = m.get("object_id"), m.get("box")
        if not oid or not box:
            return
        o = self.objects.get(oid)
        if o is None:
            if m.get("type") == "end":
                return
            if len(self.objects) > MAX_OBJECTS:
                cutoff = m["t"] - 600
                self.objects = {k: v for k, v in self.objects.items() if v["t1"] >= cutoff}
            o = self.objects[oid] = {"camera": m.get("camera"), "label": m.get("label"), "first": box, "last": box,
                                     "t0": m["t"], "t1": m["t"], "stationary": bool(m.get("stationary"))}
        o["last"], o["t1"] = box, m["t"]
        o["stationary"] = bool(m.get("stationary"))
        if m.get("false_positive") is False:
            o["real"] = True
        if m.get("type") == "end":
            self.objects.pop(oid, None)
            if self.run_async:
                threading.Thread(target=self.left, args=(o,), daemon=True).start()
            else:
                self.left(o)

    def left(self, o):
        cfg = self.settings()
        camera, label = o["camera"], str(o["label"] or "")
        if not cfg.get("handoff") or not self.allowed():
            return None
        vehicle = label in VEHICLES
        if not ((label == "person" and cfg.get("auto_person", True)) or (vehicle and cfg.get("auto_vehicle", True))):
            return None
        if not o.get("real") or o["stationary"] or o["t1"] - o["t0"] < MIN_SEEN_S:
            return None
        cam = self.cameras().get(camera)
        if not cam:
            return None
        if not self.in_window(cfg.get("auto_from", "00:00"), cfg.get("auto_to", "00:00")):
            return None
        if time.time() - self.last_at.get(camera, 0) < float(cfg.get("auto_cooldown_min", 10)) * 60:
            return None
        import coverage
        w, h = self.frame_size(camera)
        spot = coverage.exit_point(cam, cam["view"], o["first"], o["last"], w, h)
        what = "Person" if label == "person" else "Vehicle"
        self.last_at[camera] = time.time()
        r = self.send(spot["lat"], spot["lon"], f"handoff: {what.lower()} left {camera} ({spot['exit']})")
        if r.get("ok"):
            text = (f"🛰 {what} left {camera}'s view ({spot['exit']}, about {int(spot['distance_m'])} m out, heading "
                    f"{int(spot['bearing'])}°). {r.get('message') or 'A drone is on its way.'}")
        else:
            text = f"🛰 {what} left {camera}'s view, but no drone could be sent: {r.get('error')}"
        self._note(text)
        self.publish("alert", alert="handoff", camera=camera, text=text, key=f"handoff:{camera}:{int(time.time())}",
                     buttons=[[{"text": "🏠 Recall drone", "callback_data": "home"}]] if r.get("ok") else None)
        return {**r, "spot": spot}
