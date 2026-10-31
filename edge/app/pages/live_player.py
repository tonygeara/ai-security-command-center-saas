"""The live video player added to pages that show cameras or drones."""
LIVE_PLAYER_HTML = r"""
<style>
.live-slot{position:relative;width:100%;height:100%;background:#000;overflow:hidden}
.live-slot video-stream,.live-slot video,.live-slot>img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;display:block;background:#000}
.live-slot canvas{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:2}
.live-slot video-stream div{display:none!important}  /* go2rtc's raw status text; our tag shows status */
.live-mode{position:absolute;right:12px;top:10px;z-index:3;font:bold 9px Arial,sans-serif;letter-spacing:1px;color:#2aea88;
  background:rgba(3,16,26,.8);border:1px solid #155879;padding:4px 7px;border-radius:3px}
.live-mode.compat{color:#ffb23c}
</style>
<script type="module">
const cfg = await fetch("/api/live/config", {cache: "no-store"}).then(r => r.json()).catch(() => null);

function setMode(slot, text, compat) {
    let tag = slot.querySelector(".live-mode");
    if (!tag) { tag = document.createElement("div"); tag.className = "live-mode"; slot.appendChild(tag); }
    tag.textContent = text;
    tag.classList.toggle("compat", !!compat);
}

function useFallback(slot, why, cam) {
    if (cam && cam.fallback === null) {  // extra cameras/drones: no MJPEG feed to fall back to
        setMode(slot, "NO VIDEO", true);
        console.info("Live view unavailable:", why);
        return;
    }
    slot.querySelector("video-stream")?.remove();
    if (!slot.querySelector(":scope > img")) {
        const img = new Image();
        img.alt = "Live camera";
        img.src = (cam && cam.fallback) || (cfg && cfg.fallback) || "/video_feed";
        slot.prepend(img);
    }
    slot.dataset.mode = "mjpeg";
    setMode(slot, "COMPATIBILITY MODE", true);
    console.info("Live view fallback:", why);
}

function drawOverlays(slot, cam) {
    const canvas = document.createElement("canvas");
    slot.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    let items = [];
    const render = () => {
        const w = slot.clientWidth, h = slot.clientHeight, dpr = window.devicePixelRatio || 1;
        canvas.width = w * dpr; canvas.height = h * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);
        if (slot.dataset.mode !== "direct") return;  // the MJPEG fallback has boxes drawn in
        // Boxes arrive in Frigate's detect resolution; the video is scaled to fit the slot.
        const v = slot.querySelector("video");
        const vw = cam.width || 1280, vh = cam.height || 720;
        const ar = (v && v.videoWidth && v.videoHeight) ? v.videoWidth / v.videoHeight : vw / vh;
        const dispW = Math.min(w, h * ar), dispH = dispW / ar, s = dispW / vw, sy = dispH / vh;
        const ox = (w - dispW) / 2, oy = (h - dispH) / 2;
        for (const it of items) {
            const color = it.known ? "#00dc50" : "#ffa500";
            let X = ox + 18, Y = oy + 18, W = dispW - 36, H = dispH - 36;  // no box: frame the view
            if (Array.isArray(it.box) && it.box.length === 4) {
                const [x1, y1, x2, y2] = it.box.map(Number);
                X = ox + x1 * s; Y = oy + y1 * sy; W = (x2 - x1) * s; H = (y2 - y1) * sy;
            }
            ctx.lineWidth = 3; ctx.strokeStyle = color; ctx.strokeRect(X, Y, W, H);
            let label = String(it.label || (it.kind === "face" ? "PERSON" : "VEHICLE"));
            if (it.plate) label += " | " + it.plate;
            ctx.font = "bold 13px Arial, sans-serif";
            const tw = ctx.measureText(label).width + 12, ty = Math.max(0, Y - 20);
            ctx.fillStyle = color; ctx.fillRect(X, ty, tw, 20);
            ctx.fillStyle = "#000"; ctx.fillText(label, X + 6, ty + 15);
        }
    };
    const poll = async () => {
        if (slot.dataset.mode === "direct" && !document.hidden) {
            try {
                const st = await fetch(cam.overlays || "/api/status", {cache: "no-store"}).then(r => r.json());
                items = st.targets  // drone: every tracked person/vehicle
                    ? st.targets.map(t => ({...t, kind: t.type === "person" ? "face" : "vehicle"}))
                    : [...(st.active_faces || []).map(f => ({...f, kind: "face"})),
                       ...(st.active_vehicles || []).map(v => ({...v, kind: "vehicle"}))];
            } catch (e) { items = []; }
        }
        render();
    };
    (slot._timers = slot._timers || []).push(setInterval(poll, 700));
    window.addEventListener("resize", render);
    slot._cleanup = () => window.removeEventListener("resize", render);
    poll();
}

async function attach(slot) {
    const key = slot.dataset.liveCamera || "main";
    // A camera added after this page loaded isn't in cfg yet: play its relay stream by name.
    const cam = (cfg && cfg.cameras && cfg.cameras[key])
        || (key !== "main" ? {stream: key, fallback: null, overlays: null, fallback_on_timeout: false} : cfg);
    if (!cfg || !cfg.go2rtc || !cam) return useFallback(slot, "no live config", cam);
    try { await import(cfg.go2rtc + "/video-stream.js"); }
    catch (e) { return useFallback(slot, "relay player unavailable", cam); }
    const el = document.createElement("video-stream");
    el.mode = "mse";          // MSE over WebSocket works through Docker's localhost-only ports
    el.background = false;    // pause while the page is hidden, to save CPU
    el.src = cfg.go2rtc.replace(/^http/, "ws") + "/api/ws?src=" + encodeURIComponent(cam.stream);
    slot.prepend(el);
    slot.dataset.mode = "direct";
    setMode(slot, "CONNECTING…", true);
    const started = Date.now();
    if (!slot._fullscreenBound) {  // double-click any live feed for full screen
        slot.addEventListener("dblclick", () => slot.requestFullscreen?.());
        slot._fullscreenBound = true;
    }
    const check = setInterval(() => {
        if (!slot.isConnected || slot.dataset.mode === undefined) { clearInterval(check); return; }
        const v = el.querySelector("video");
        if (v && v.controls) v.controls = false;  // no browser player bar over the camera
        if (v && v.currentTime > 0 && !v.paused) {
            setMode(slot, "● REAL-TIME");
            if (cam.fallback_on_timeout !== false) clearInterval(check);
            return;
        }
        if (Date.now() - started > 8000) {
            if (cam.fallback_on_timeout !== false) { clearInterval(check); useFallback(slot, "no video from relay", cam); }
            else setMode(slot, "WAITING FOR VIDEO", true);  // the player keeps retrying on its own
        }
    }, 1000);
    if (cam.overlays) drawOverlays(slot, cam);
}

// Panels with data-live-deferred are started by their Live feed switch instead.
document.querySelectorAll("[data-live-camera]:not([data-live-deferred])").forEach(attach);
// The multi-camera grid adds tiles after load and attaches them with this.
window.attachLiveCamera = attach;

// Stop a live view completely: closes the relay connection or MJPEG stream and its timers.
function detach(slot) {
    (slot._timers || []).forEach(clearInterval);
    slot._timers = [];
    if (slot._cleanup) { slot._cleanup(); slot._cleanup = null; }
    slot.querySelectorAll("video-stream, canvas, .live-mode").forEach(el => el.remove());
    const img = slot.querySelector(":scope > img");
    if (img) { img.src = "data:,"; img.remove(); }
    delete slot.dataset.mode;
}
window.detachLiveCamera = detach;
window.dispatchEvent(new Event("live-player-ready"));
</script>
"""
