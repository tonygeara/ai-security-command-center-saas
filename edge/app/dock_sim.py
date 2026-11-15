"""A simulated DJI Dock with its drone, for tests, training and demos (no broker or hardware needed).

It sends the hub what a real dock sends over MQTT (DJI Cloud API): its topology (update_topo, with the drone in it),
dock telemetry (cover, weather, drone charging) and the drone's telemetry, once a second, and takes the hub's
replies. Phase 1 has no flying: the drone stays in the dock and charges.
"""
import random
import threading
import time
import uuid

MODELS = {  # simulated model -> (dock domain, type, sub_type), (drone domain, type, sub_type)
    "dock3": ((3, 3, 0), (0, 100, 1)),   # Dock 3 with Matrice 4TD
    "dock2": ((3, 2, 0), (0, 91, 1)),    # Dock 2 with Matrice 3TD
}


class SimulatedDock:
    def __init__(self, sn, send, home, model="dock3", period=1.0):
        self.sn = sn
        self.drone_sn = sn + "-UAV"
        self.send = send            # send(topic, dict): into the hub
        self.home = (float(home[0]), float(home[1]))
        self.model = model if model in MODELS else "dock3"
        self.period = period
        self.battery = 64.0
        self.powered = True
        self.topo_acked = False
        self.streaming = None       # video_id the PC asked it to stream
        self.fault = ""             # test alerts: "", offline, cover, rain, wind, hot, battery, hms
        self.replies = []           # last replies from the hub (tests look at them)
        self.stop_event = threading.Event()
        self.thread = None

    def _msg(self, method=None, data=None, **extra):
        return {"tid": str(uuid.uuid4()), "bid": str(uuid.uuid4()), "timestamp": int(time.time() * 1000),
                **({"method": method} if method else {}), "data": data or {}, **extra}

    def topology(self):
        (dd, dt, ds), (ud, ut, us) = MODELS[self.model]
        self.send(f"sys/product/{self.sn}/status", self._msg("update_topo", {
            "domain": dd, "type": dt, "sub_type": ds, "version": "1.0.0", "device_secret": "sim", "nonce": "sim",
            "sub_devices": [{"sn": self.drone_sn, "domain": ud, "type": ut, "sub_type": us, "index": "A",
                             "device_secret": "sim", "nonce": "sim", "version": "1.0.0"}]}))

    def go_offline(self):
        self.send(f"sys/product/{self.sn}/status", self._msg("update_topo", {}))

    def capacity(self):
        """What it can stream (DJI live_capacity): the drone's camera with wide/zoom/thermal, and the dock's own camera."""
        self.send(f"thing/product/{self.sn}/state", self._msg(data={"live_capacity": {
            "available_video_number": 2, "coexist_video_number_max": 1, "device_list": [
                {"sn": self.drone_sn, "available_video_number": 1, "coexist_video_number_max": 1, "camera_list": [
                    {"camera_index": "99-0-0", "available_video_number": 1, "coexist_video_number_max": 1,
                     "video_list": [{"video_index": "normal-0", "video_type": "normal", "switchable_video_types": ["wide", "zoom", "ir"]}]}]},
                {"sn": self.sn, "available_video_number": 1, "coexist_video_number_max": 1, "camera_list": [
                    {"camera_index": "165-0-7", "available_video_number": 1, "coexist_video_number_max": 1,
                     "video_list": [{"video_index": "normal-0", "video_type": "normal", "switchable_video_types": []}]}]}]}}))

    def osd(self):
        f = self.fault
        if f == "battery":
            self.battery, charging = 12.0, False
        else:
            charging = self.battery < 100
            self.battery = min(100.0, self.battery + 0.5)
        self.send(f"thing/product/{self.sn}/osd", self._msg(data={
            "mode_code": 0, "cover_state": 3 if f == "cover" else 0, "drone_in_dock": 1, "latitude": self.home[0], "longitude": self.home[1],
            "environment_temperature": 47.5 if f == "hot" else round(24 + random.uniform(-0.3, 0.3), 1), "temperature": 28.0,
            "wind_speed": 14.2 if f == "wind" else round(random.uniform(1.0, 3.5), 1), "rainfall": 3 if f == "rain" else 0,
            "network_state": {"type": 2, "quality": 5, "rate": 12000},
            "drone_charge_state": {"state": 1 if charging else 0, "capacity_percent": int(self.battery)}}))
        self.send(f"thing/product/{self.drone_sn}/osd", self._msg(data={
            "mode_code": 14, "latitude": self.home[0], "longitude": self.home[1], "height": 0, "elevation": 0,
            "horizontal_speed": 0, "vertical_speed": 0, "attitude_head": 0,
            "battery": {"capacity_percent": int(self.battery), "remain_flight_time": int(self.battery * 0.4 * 60)}}))

    def hms(self):
        """A DJI health message about the dock, repeated while it lasts, as real docks do."""
        (dd, dt, ds), _ = MODELS[self.model]
        self.send(f"thing/product/{self.sn}/events", self._msg("hms", {"list": [
            {"level": 2, "module": 3, "in_the_sky": 0, "code": "0x19110000", "device_type": f"{dd}-{dt}-{ds}", "imminent": 0,
             "args": {"component_index": 0, "sensor_index": 0}}]}, need_reply=0))

    def set_fault(self, fault):
        """Test alerts on a simulated dock; "" clears. offline: the dock goes silent (no goodbye, like a power cut)."""
        self.fault = fault
        if fault != "offline":
            self.topo_acked = False  # back from silence: introduce itself again

    def on_message(self, topic, payload):
        self.replies = (self.replies + [(topic, payload)])[-20:]
        if topic.endswith("/services"):  # a command: say it's done (there is no real picture to send)
            method, data = payload.get("method"), payload.get("data") or {}
            if method == "live_start_push":
                self.streaming = data.get("video_id")
            elif method == "live_stop_push":
                self.streaming = None
            self.send(topic + "_reply", {"tid": payload.get("tid"), "bid": payload.get("bid"), "method": method,
                                         "timestamp": int(time.time() * 1000), "data": {"result": 0}})
            return
        if topic.endswith("/status_reply") and (payload.get("data") or {}).get("result") == 0:
            self.topo_acked = True

    def tick(self):
        if not self.powered or self.fault == "offline":
            return
        if not self.topo_acked:
            self.topology()
            self.capacity()
        self.osd()
        if self.fault == "hms":
            self.hms()

    def start(self):
        self.thread = threading.Thread(target=self._run, name=f"sim-dock-{self.sn}", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def set_power(self, on):
        self.powered = bool(on)
        self.topo_acked = False
        if not on:
            self.go_offline()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - a demo must never take the dashboard down
                pass
            self.stop_event.wait(self.period)
