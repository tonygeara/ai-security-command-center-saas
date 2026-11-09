"""The event pipeline: everything that happens is published here once, and whoever cares subscribes.

    detection (camera saw a person/vehicle) ─┐
    event     (unknown face/plate saved)     ├─► bus ─► incidents (group into one story per camera)
    sighting  (known face/plate)             │        ├► auto-dispatch (send the nearest drone)
    dispatch / drone (drone actions)         ┘        └► … (evidence packs, alerts: next phases)

Publishing never blocks the caller (MQTT, drone link): messages go on a queue and one worker thread
hands them to the subscribers in order. A subscriber that fails is logged and skipped; the others
still get the message.
"""
import queue
import threading
import time
import traceback


class Bus:
    def __init__(self, name="bus"):
        self.subs = {}  # kind -> [fn]; "*" gets everything
        self.q = queue.Queue(maxsize=10000)
        self.dropped = 0
        self.handled = 0
        self._idle = threading.Event()
        self._idle.set()
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)
        self.thread.start()

    def subscribe(self, kind, fn):
        self.subs.setdefault(kind, []).append(fn)
        return fn

    def publish(self, kind, **data):
        msg = {"kind": kind, "t": data.pop("t", None) or time.time(), **data}
        try:
            self._idle.clear()
            self.q.put_nowait(msg)
        except queue.Full:  # never hold up the camera or the drone link
            self.dropped += 1

    def _run(self):
        while True:
            msg = self.q.get()
            for fn in self.subs.get(msg["kind"], []) + self.subs.get("*", []):
                try:
                    fn(msg)
                except Exception:
                    print(f"Pipeline: {getattr(fn, '__name__', fn)} failed on {msg['kind']}:\n{traceback.format_exc()}")
            self.handled += 1
            if self.q.empty():
                self._idle.set()

    def flush(self, timeout=10):
        """Wait until everything published so far has been handled (tests, shutdown)."""
        end = time.time() + timeout
        while time.time() < end:
            if self.q.empty() and self._idle.wait(0.05) and self.q.empty():
                return True
        return False
