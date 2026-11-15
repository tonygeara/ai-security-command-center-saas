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

    def osd(self):
        charging = self.battery < 100
        self.battery = min(100.0, self.battery + 0.5)
        self.send(f"thing/product/{self.sn}/osd", self._msg(data={
            "mode_code": 0, "cover_state": 0, "drone_in_dock": 1, "latitude": self.home[0], "longitude": self.home[1],
            "environment_temperature": round(24 + random.uniform(-0.3, 0.3), 1), "temperature": 28.0,
            "wind_speed": round(random.uniform(1.0, 3.5), 1), "rainfall": 0,
            "network_state": {"type": 2, "quality": 5, "rate": 12000},
            "drone_charge_state": {"state": 1 if charging else 0, "capacity_percent": int(self.battery)}}))
        self.send(f"thing/product/{self.drone_sn}/osd", self._msg(data={
            "mode_code": 14, "latitude": self.home[0], "longitude": self.home[1], "height": 0, "elevation": 0,
            "horizontal_speed": 0, "vertical_speed": 0, "attitude_head": 0,
            "battery": {"capacity_percent": int(self.battery), "remain_flight_time": int(self.battery * 0.4 * 60)}}))

    def on_message(self, topic, payload):
        self.replies = (self.replies + [(topic, payload)])[-20:]
        if topic.endswith("/status_reply") and (payload.get("data") or {}).get("result") == 0:
            self.topo_acked = True

    def tick(self):
        if not self.powered:
            return
        if not self.topo_acked:
            self.topology()
        self.osd()

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
