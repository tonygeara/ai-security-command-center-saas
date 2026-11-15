"""The Drone page: flying, routes, no-fly zones, responses."""
BODY = r"""
<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">
<style>
.dc-grid{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(330px,1fr);gap:16px;align-items:start}
.dc-video{aspect-ratio:16/9;position:relative;background:#000}
.dc-hud{position:absolute;left:10px;bottom:10px;z-index:4;display:flex;gap:6px;flex-wrap:wrap}
.dc-hud span{background:rgba(3,16,26,.85);border:1px solid #155879;color:#9edfff;padding:5px 8px;border-radius:3px;font:bold 11px Arial,sans-serif;letter-spacing:.5px}
.dc-hud span b{color:#fff}
.dc-btns{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.dc-btns .hud-btn{min-height:44px}
.dc-big{font-size:12px!important}
.hud-btn.warn{color:#ffcf7a;border-color:#7a5a12;background:rgba(125,90,12,.14)}
.dc-tel{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.dc-tel div{background:#05131d;border:1px solid #153c56;border-radius:4px;padding:8px 10px}
.dc-tel small{display:block;color:#6d8b9d;font-size:9px;letter-spacing:1.5px;text-transform:uppercase}
.dc-tel b{color:#e9f8ff;font-size:15px}
#dcMap{height:260px;border:1px solid #155879;border-radius:5px;background:#020a10}
.nf-chip{display:inline-flex;align-items:center;gap:6px;border:1px solid #7a2935;background:rgba(125,12,28,.18);color:#ffb3bb;border-radius:12px;padding:2px 4px 2px 10px;font-size:12px}
.nf-chip button{background:none;border:0;color:#ff7b86;cursor:pointer;font-weight:bold;padding:0 6px}
.nf-chip button.armed{background:#7a1020;color:#fff;border-radius:10px}
.dc-keys{display:grid;grid-template-columns:repeat(2,1fr);gap:4px 14px;font-size:12px;color:#9edfff}
.dc-keys kbd{display:inline-block;min-width:22px;text-align:center;padding:2px 5px;border:1px solid #155879;border-radius:3px;background:#020a10;color:#5bd9ff;font:bold 11px Arial}
.dc-ctl-on{box-shadow:0 0 0 2px #26ee89 inset}
.dc-pair{display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.dc-pair .qr{background:#fff;border-radius:4px;padding:4px}
.dc-fleet{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 14px}
.dc-fleet a,.dc-fleet button{display:flex;align-items:center;gap:7px;padding:8px 12px;border:1px solid #155879;border-radius:4px;background:#05131d;color:#9edfff;text-decoration:none;font:bold 12px Arial,sans-serif;letter-spacing:.5px;cursor:pointer}
.dc-fleet a.on{border-color:#5bd9ff;background:rgba(53,202,255,.14);color:#fff;box-shadow:0 0 0 1px #5bd9ff inset}
.dc-fleet a small{color:#6d8b9d;font-weight:normal}
.dc-fleet i{width:8px;height:8px;border-radius:50%;background:#53636d;display:inline-block}
.dc-fleet i.ok{background:#26ee89}.dc-fleet i.half{background:#ffb23c}
.dc-fleet button:disabled{opacity:.5;cursor:not-allowed}
.vcam-x{position:absolute;left:50%;top:50%;width:46px;height:46px;margin:-23px 0 0 -23px;border:2px solid rgba(91,217,255,.85);border-radius:50%;z-index:500;pointer-events:none}
.vcam-tag{position:absolute;right:10px;top:10px;z-index:500;background:rgba(3,16,26,.85);border:1px solid #7a5a12;color:#ffcf7a;padding:4px 8px;border-radius:3px;font:bold 10px Arial;letter-spacing:1px}
#l4d{display:none;position:relative;height:460px;border:1px solid #155879;border-radius:5px;background:#020a10;overflow:hidden}
#l4dBar{display:none;gap:6px;flex-wrap:wrap;margin-top:8px}
.l4d-switch{display:flex;align-items:center;gap:7px;margin:0;color:#5bd9ff;font:bold 10px Arial;letter-spacing:1.5px;cursor:pointer}
.l4d-chip{display:inline-flex;align-items:center;gap:8px;border:1px solid #155879;border-radius:14px;background:#05131d;padding:3px 4px 3px 8px;font-size:12px;color:#cfeeff}
.l4d-chip label{display:flex;align-items:center;gap:6px;margin:0;text-transform:none;letter-spacing:0;font-size:12px;cursor:pointer}
.l4d-chip label input.toggle{width:34px;height:18px}.l4d-chip label input.toggle::after{width:12px;height:12px}
.l4d-chip i{width:9px;height:9px;border-radius:50%;display:inline-block}
.l4d-chip button,.l4d-reset{border:1px solid #155879;background:#020a10;color:#9edfff;border-radius:10px;padding:3px 9px;font:bold 10px Arial;cursor:pointer}
.l4d-chip button.on{background:#25c7ff;color:#02131d;border-color:#45d0ff}
.l4d-chip button.l4d-go{display:flex;align-items:center;gap:6px;border:0;background:none;color:#cfeeff;font:12px Arial;padding:2px 2px;cursor:pointer}
.l4d-chip button.l4d-go:hover{color:#fff;text-decoration:underline}
.fs-strip{display:flex;align-items:stretch;gap:0;margin:0 0 14px;border:1px solid #155879;border-radius:5px;background:#05131d;overflow-x:auto;white-space:nowrap;scrollbar-width:thin}
.fs-cell{display:flex;align-items:center;gap:7px;padding:8px 14px;border-right:1px solid #123447;color:#9edfff;font-size:12px}
.fs-cell b{color:#e9f8ff}.fs-cell.bad{color:#ff9ea8;background:rgba(125,12,28,.16)}.fs-cell.warn{color:#ffcf7a;background:rgba(125,90,12,.12)}
.fs-cell.ok{color:#7dffc1}.fs-link{margin-left:auto;border-right:0;color:#5bd9ff;text-decoration:none}.fs-link:hover{color:#fff}
#m3d{display:none;width:100%;height:760px;border:1px solid #155879;border-radius:5px;background:#020a10}
.dc-fleet button.dk-chip{border-color:#7a5a12;color:#ffcf7a}.dc-fleet button.dk-chip small{color:#9a8a6a;font-weight:normal}
.dk-card.dk-bad{border-color:#a3303f;box-shadow:0 0 0 1px #a3303f inset}.dk-card.dk-careful{border-color:#7a5a12}
.dk-alert{margin:0 0 6px;padding:5px 8px;border-radius:3px;font-size:12px;line-height:1.35}
.dk-alert.warning{background:rgba(125,12,28,.25);color:#ffb3bb;border:1px solid #7a2935}
.dk-alert.caution{background:rgba(125,90,12,.18);color:#ffcf7a;border:1px solid #7a5a12}
.dk-health{margin-top:12px;max-height:160px;overflow:auto;font-size:12px}
.dk-health div{padding:3px 0;border-bottom:1px solid #0f2a3b;color:#9edfff}.dk-health div.on{color:#ffb3bb}.dk-health small{color:#6d8b9d;margin-right:8px}
.dk-videos{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:10px;margin-top:10px}
.dk-video{border:1px solid #155879;border-radius:5px;background:#000;overflow:hidden}
.dk-video .dk-vhead{display:flex;align-items:center;gap:8px;padding:6px 10px;background:#05131d;color:#9edfff;font:bold 12px Arial}
.dk-video .dk-vbody{aspect-ratio:16/9;position:relative}
.dk-video .dk-sim{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#ffcf7a;font:bold 12px Arial;letter-spacing:1px;text-align:center;padding:10px}
.dk-launch{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 10px;padding:10px 12px;border:1px solid #a3303f;border-radius:5px;background:rgba(125,12,28,.22);color:#ffd5da}
.dk-launch b{color:#fff}
.dk-card.flash{box-shadow:0 0 0 2px #ffb23c}
.dk-mark{width:22px;height:22px;border:2px solid #ffb23c;border-radius:4px;background:rgba(3,16,26,.9);color:#ffcf7a;font:bold 12px/18px Arial;text-align:center}
.dk-mark.off{border-color:#53636d;color:#8aa0ad}
.dk-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}
.dk-card{border:1px solid #155879;border-radius:5px;background:#05131d;padding:10px 12px}
.dk-card.found{border-style:dashed;border-color:#7a5a12}
.dk-card h4{margin:0 0 4px;font:bold 13px Arial,sans-serif;color:#e9f8ff;display:flex;align-items:center;gap:7px}
.dk-card .dk-sub{color:#6d8b9d;font-size:11px;margin-bottom:8px;word-break:break-all}
.dk-tags{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px}
.dk-tags span{border:1px solid #153c56;border-radius:3px;padding:2px 6px;font-size:11px;color:#9edfff}
.dk-setup{margin-top:14px;border-top:1px solid #123447;padding-top:12px}
.dk-setup summary{cursor:pointer;color:#5bd9ff;font:bold 12px Arial;letter-spacing:.5px}
.dk-form{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;margin:10px 0}
.dk-form input{width:100%;box-sizing:border-box}
.dk-pilot{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;margin-top:10px}
.dk-pilot .qr{background:#fff;border-radius:4px;padding:4px}
.dk-pilot code{word-break:break-all}
@media(max-width:1000px){.dc-grid{grid-template-columns:1fr}}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Drone</div><h1 class="page-title">Drone Control</h1>
<div class="page-sub">Fly the drone from this PC through the Drone Link app on the controller's phone. Keep the drone in sight — the pilot's controller can take over at any time.</div></div>
<div class="actions"><span class="state" id="linkState"><i class="dot bad"></i>PHONE NOT CONNECTED</span>
<button class="hud-btn danger" id="rmDrone" style="display:none" onclick="removeDrone()" title="Admins only">🗑 Remove this drone</button></div></div>
<div class="dc-fleet" id="fleet"></div>
<div class="fs-strip" id="fsStrip"><span class="fs-cell" id="fsVerdict"><i class="dot warn"></i>Flight safety: checking…</span>
<span class="fs-cell" id="fsWx">☁ –</span><span class="fs-cell" id="fsAc">✈ –</span><span class="fs-cell" id="fsZones">🛇 –</span>
<a class="fs-cell fs-link" href="/safety">⚙ Flight safety settings</a></div>

<section class="panel" id="pairPanel"><div class="panel-head"><div class="panel-title">⌁ Connect the phone</div><div class="live">PAIRING</div></div>
<div class="panel-body dc-pair"><div class="qr" id="pairQr"></div><div style="flex:1;min-width:240px">
<div class="muted">1. Plug the Android phone into the RC-N1 controller and turn on the drone.<br>2. Open <b>Drone Link</b> on the phone and tap <b>Scan pairing code</b>.<br>3. Scan this QR code. The phone and this PC must be on the same Wi-Fi.</div>
<div class="muted" style="margin-top:10px">PC address: <code id="pairAddr">…</code></div>
<div class="actions" style="margin-top:12px"><button class="hud-btn danger" onclick="resetPair()">New pairing code</button></div>
<div id="pairMsg" class="hud-msg"></div></div></div></section>

<div class="dc-grid">
<div>
<section class="panel"><div class="panel-head"><div class="panel-title">✈ Live view</div><div class="live" id="flyState">ON GROUND</div></div>
<div class="dc-video"><div class="live-slot" data-live-camera="drone"></div>
<div class="dc-hud"><span>ALT <b id="hAlt">–</b> m</span><span>DIST <b id="hDist">–</b> m</span><span>SPD <b id="hSpd">–</b> m/s</span><span>BAT <b id="hBat">–</b>%</span><span>GPS <b id="hGps">–</b></span><span>SIGNAL <b id="hSig">–</b></span></div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">⌖ Map</div><div class="actions" style="align-items:center;gap:10px"><div class="live" id="mapState"></div>
<label class="l4d-switch" title="Plan, fly and view 3D site maps"><input type="checkbox" class="toggle" id="m3dOn" onchange="toggle3d(this.checked)"> 3D MAP</label>
<label class="l4d-switch" title="Watch every drone fly in 3D, live"><input type="checkbox" class="toggle" id="l4dOn" onchange="toggle4d(this.checked)"> 4D LIVE</label></div></div>
<div class="panel-body"><div id="dcMap"></div><iframe id="m3d" title="3D site maps"></iframe><div id="l4d"></div><div id="l4dBar"></div><div class="muted" id="coords" style="margin-top:8px"></div></div></section>
</div>
<div>
<section class="panel"><div class="panel-head"><div class="panel-title">◉ Flight</div><div class="live" id="modeState"></div></div>
<div class="panel-body">
<div class="dc-btns">
<button class="hud-btn primary dc-big" onclick="takeoff()">Take off</button>
<button class="hud-btn warn dc-big" onclick="cmd('land')">Land</button>
<button class="hud-btn warn dc-big" onclick="cmd('go_home',{},'Fly back to the home point and land?')">Return home</button>
<button class="hud-btn danger dc-big" style="grid-column:1/-1;min-height:52px" onclick="stopAll()">■ STOP — hover in place (Space)</button>
<button class="hud-btn" onclick="cmd('cancel_land')">Cancel landing</button>
<button class="hud-btn primary dc-big" id="confirmLand" style="grid-column:1/-1;display:none" onclick="cmd('confirm_land')">▼ Confirm landing — drone is waiting just above the ground</button>
<button class="hud-btn" onclick="cmd('cancel_go_home')">Cancel return</button>
<button class="hud-btn" id="ctlBtn" onclick="toggleControl()">Keyboard control: OFF</button>
</div>
<label for="speed">Speed limit <span id="speedVal" class="muted"></span></label>
<input id="speed" type="range" min="0.1" max="0.5" step="0.05" value="0.3" style="width:100%" oninput="speedVal.textContent=Math.round(this.value*100)+'%'">
<div class="dc-keys" style="margin-top:12px">
<div><kbd>W</kbd><kbd>S</kbd> forward / back</div><div><kbd>A</kbd><kbd>D</kbd> left / right</div>
<div><kbd>↑</kbd><kbd>↓</kbd> up / down (hold ↑ on the ground: take off · hold ↓ near the ground: land)</div><div><kbd>←</kbd><kbd>→</kbd> turn</div>
<div><kbd>Space</kbd> stop &amp; hover</div><div>🎮 Gamepad works too</div></div>
<div id="cmdMsg" class="hud-msg"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">🗺️ Auto-fly route</div><div class="live" id="routeState"></div></div>
<div class="panel-body">
<div class="muted">Click the map to add stops; the drone takes off if needed and flies through them in order (one stop = fly to a point). Every stop must be within <span id="routeMax">500</span> m of home. STOP, any flying key or the controller cancels it.</div>
<div class="actions" style="margin-top:10px"><button class="hud-btn" onclick="undoPoint()">Undo</button><button class="hud-btn" onclick="clearRoute()">Clear</button>
<button class="hud-btn" onclick="shortestOrder()" title="Reorder the stops to fly the shortest distance">Shortest order</button>
<button class="hud-btn" onclick="checkSignal()" title="Expected controller signal at each stop">Check signal</button>
<select id="routeSel" onchange="loadRoute(this.value)" style="flex:1;min-width:140px"><option value="">Saved routes…</option></select></div>
<div style="margin-top:10px;border:1px solid #5a1b25;border-radius:4px;padding:8px 10px;background:rgba(122,16,32,.08)">
<b style="color:#ff7b86;font-size:11px;letter-spacing:1.5px">⛔ NO-FLY ZONES</b> <span class="muted">Areas every drone stays out of (neighbours, roads, a helipad). Routes crossing them are refused; auto-fly, drone responses and return home fly round them. The dashed circle is this drone's <span class="nf-range">500</span> m range from its home point: keep route stops inside it.</span>
<div class="actions" style="margin-top:6px"><button class="hud-btn" id="nfDrawBtn" onclick="nfDraw()">＋ Draw a zone</button>
<input id="nfName" placeholder="Zone name, e.g. Neighbour" style="flex:1;min-width:120px;display:none"><button class="hud-btn primary" id="nfSaveBtn" style="display:none" onclick="nfSave()">Save zone</button>
<button class="hud-btn" id="nfUndoBtn" style="display:none" onclick="nfUndo()">Undo corner</button><button class="hud-btn" id="nfCancelBtn" style="display:none" onclick="nfCancel()">Cancel</button></div>
<div id="nfList" style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap"></div><div id="nfMsg" class="hud-msg"></div>
<div id="mapCache" class="muted" style="margin-top:6px;font-size:11px"></div></div>
<div id="routeInfo" class="muted" style="margin-top:8px">No stops yet.</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:0 10px">
<div><label for="rtAlt">Height (m)</label><input id="rtAlt" type="number" min="10" max="120" value="30" oninput="routeInfo()"></div>
<div><label for="rtSpeed">Speed (m/s)</label><input id="rtSpeed" type="number" min="1" max="8" value="5" oninput="routeInfo()"></div>
<div><label for="rtPause">Pause (s)</label><input id="rtPause" type="number" min="0" max="120" value="5" oninput="routeInfo()"></div>
<div><label for="rtEnd">At the end</label><select id="rtEnd"><option value="home">Return home</option><option value="hover">Hover at last stop</option><option value="land">Land at last stop</option></select></div>
</div>
<label style="margin-top:10px;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0"><input type="checkbox" id="rtLoop" onchange="routeInfo()"> <b>Repeat the route again and again</b> until you press Stop route</label>
<label style="margin-top:6px;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;flex-wrap:wrap"><input type="checkbox" id="rtRelay"> Relay: at
<input id="rtSwap" type="number" min="20" max="50" value="20" style="width:64px">% battery the drone returns home and the next ready drone takes off and continues the patrol</label>
<label style="margin-top:6px;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;flex-wrap:wrap"><input type="checkbox" id="rtNoBat" onchange="noBatUi()"> <b>Keep patrolling whatever the battery level</b>: repeats the route non-stop, no return home or swap by the PC</label>
<div id="noBatNote" class="hud-msg bad" style="display:none">The PC will not bring the drone home for battery. The drone's own low-battery protection still takes over (DJI: return home, then forced landing when critical) and the patrol stops there. Watch the battery yourself.</div>
<div class="muted" style="margin-top:4px">A continuous patrol always sends the drone home at that battery level; without relay the patrol then ends. Each drone needs its own phone and controller (or use virtual drones).</div>
<label style="margin-top:8px;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;flex-wrap:wrap"><input type="checkbox" id="rtLostOn" checked onchange="$('rtLost').disabled=!this.checked">
<b>If the PC link drops</b> mid-patrol the drone will <select id="rtLost" style="width:auto"><option value="home">return home</option><option value="hover">hover</option><option value="land">land where it is</option></select></label>
<div class="muted" style="margin-top:2px">Done by the phone itself, so it works even with the PC unreachable. Off: the drone hovers and hands control back to the pilot. If the controller's own signal is lost, the drone follows its DJI Fly setting (return home by default).</div>
<div class="actions" style="margin-top:12px"><input id="rtName" placeholder="Route name" style="flex:1;min-width:120px"><button class="hud-btn" onclick="saveRoute()">Save</button><button class="hud-btn danger" onclick="deleteRoute()">Delete</button></div>
<label style="margin-top:8px;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;flex-wrap:wrap">Backup drone
<select id="rtBackup" style="flex:1;min-width:160px"><option value="">None</option></select></label>
<div class="muted" style="margin-top:4px">At the battery level above, this drone flies home and the backup takes off and continues from the same stop (they then swap roles). A backup drone is reserved: it can't fly its own route meanwhile.</div>
<div id="backupNote" class="hud-msg bad" style="display:none"></div>
<div class="actions" style="margin-top:8px"><button class="hud-btn primary" id="flyRouteBtn" onclick="flyRoute()">Fly route</button><button class="hud-btn danger" onclick="stopRoute()">Stop route</button></div>
<div id="routeMsg" class="hud-msg"></div>
<div id="patrolReport" class="hud-msg" style="display:none;white-space:pre-line;border-left:3px solid #36cfff;padding-left:8px"></div>
<div style="margin-top:16px;border-top:1px solid #123447;padding-top:12px"><b style="color:#5bd9ff;font-size:11px;letter-spacing:1.5px">🗓 SCHEDULED PATROLS</b>
<div class="muted" style="margin-top:6px">Runs a saved route on chosen days. <b>Ask first</b> sends you a Telegram Start/Skip message; <b>auto-start</b> flies after the safety checks. The drone and controller must be on and connected at patrol time, and a pilot must be able to take over.</div>
<div id="schedList" style="margin-top:8px"></div>
<div class="actions" style="margin-top:8px;align-items:center"><select id="scRoute" style="flex:1;min-width:120px"></select><input id="scTime" type="time" value="02:00" style="width:110px">
<span id="scDays" style="display:flex;gap:4px;flex-wrap:wrap"></span><select id="scDrone" style="min-width:120px" title="Which drone flies it"><option value="">Any ready drone</option></select></div>
<div class="actions" style="margin-top:8px;align-items:center"><label style="margin:0;display:flex;gap:6px;align-items:center;text-transform:none;letter-spacing:0"><input type="checkbox" id="scAuto"> Auto-start (no confirmation)</label>
<button class="hud-btn primary" onclick="addSched()">Add schedule</button></div>
<div id="schedMsg" class="hud-msg"></div></div>

</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">🚨 Drone response &amp; Telegram</div><div class="live" id="respState"></div></div>
<div class="panel-body">
<div class="muted">When a camera sees an unknown person or vehicle, the Telegram alert gets a <b>Send drone</b> button, which sends the nearest ready drone. Set each camera's place on the map so the drone knows where to fly.</div>
<div id="respCams" style="margin-top:10px"></div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0 10px">
<div><label for="rAlt">Height (m)</label><input id="rAlt" type="number" min="10" max="120"></div>
<div><label for="rSpeed">Speed (m/s)</label><input id="rSpeed" type="number" min="1" max="8"></div>
<div><label for="rHover">Hover (s)</label><input id="rHover" type="number" min="10" max="600"></div>
<div><label for="rBatt">Min battery %</label><input id="rBatt" type="number" min="20" max="90"></div>
<div><label for="rBrief">Morning briefing</label><input id="rBrief" type="time"></div>
<div style="display:flex;flex-direction:column;justify-content:flex-end;gap:6px;padding-bottom:4px">
<label style="margin:0;display:flex;gap:6px;align-items:center"><input type="checkbox" id="rReturn"> Auto return home</label>
<label style="margin:0;display:flex;gap:6px;align-items:center"><input type="checkbox" id="rBriefOn"> Send briefing</label></div>
</div>
<div id="respAutoBox" style="margin-top:12px;border:1px solid #155879;border-radius:4px;padding:8px 10px;background:rgba(14,88,128,.08)">
<label style="margin:0;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;flex-wrap:wrap"><input type="checkbox" id="rAuto" onchange="autoWarn(this)">
<b>Auto-send the nearest drone</b> when a camera sees a
<span style="display:inline-flex;gap:4px;align-items:center"><input type="checkbox" id="rAutoP"> person</span>
<span style="display:inline-flex;gap:4px;align-items:center"><input type="checkbox" id="rAutoV"> vehicle</span>
between <input id="rFrom" type="time" style="width:110px"> and <input id="rTo" type="time" style="width:110px"></label>
<div class="muted" style="margin-top:4px">It picks the closest drone that is ready (connected, enough battery, not on a route or held as a backup), flies round no-fly zones and sends you a Telegram alert with a Recall button. Each camera triggers it at most once every
<input id="rCool" type="number" min="1" max="120" style="width:60px"> min. Only cameras with a map location count. Same start and end time = all day.</div>
<label style="margin:10px 0 0;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;flex-wrap:wrap"><input type="checkbox" id="rHandoff" onchange="handoffWarn(this)">
<b>Camera-to-drone handoff</b>: when a person or vehicle leaves a camera's view, send the nearest drone to where they went</label>
<div class="muted" style="margin-top:4px">Uses the same people/vehicle choices, hours and cooldown as above. Only cameras placed and pointed on the <a href="/coverage" style="color:#5bd9ff">Coverage</a> page take part. The drone flies to the estimated spot and hovers there with its camera; it does not chase.</div></div>
<div class="actions" style="margin-top:12px"><button class="hud-btn primary" onclick="saveResp()">Save</button><button class="hud-btn danger" onclick="recallResp()">Recall drone</button>
<button class="hud-btn" onclick="briefNow()">Send briefing now</button></div>
<div id="respMsg" class="hud-msg"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">▣ Camera</div></div>
<div class="panel-body"><div class="dc-btns">
<button class="hud-btn" onclick="cmd('gimbal',{pitch:0})">Look ahead</button>
<button class="hud-btn" onclick="cmd('gimbal',{pitch:-45})">Tilt 45°</button>
<button class="hud-btn" onclick="cmd('gimbal',{pitch:-90})">Look down</button>
<button class="hud-btn" onclick="cmd('photo')">Photo</button>
<button class="hud-btn" onclick="cmd('record_start')">Record</button>
<button class="hud-btn" onclick="cmd('record_stop')">Stop rec</button>
</div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">◷ Telemetry</div></div>
<div class="panel-body"><div class="dc-tel">
<div><small>Height</small><b id="tAlt">–</b></div><div><small>Distance home</small><b id="tDist">–</b></div>
<div><small>Speed</small><b id="tSpd">–</b></div><div><small>Heading</small><b id="tHdg">–</b></div>
<div><small>Battery</small><b id="tBat">–</b></div><div><small>GPS satellites</small><b id="tGps">–</b></div>
<div><small>Flight mode</small><b id="tMode">–</b></div><div><small>Control</small><b id="tCtl">–</b></div>
</div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">⚙ Testing</div><div class="live" id="simState"></div></div>
<div class="panel-body"><div class="muted">Simulator: the drone stays on the ground with motors locked while it pretends to fly. <b>Remove the propellers first.</b></div>
<div class="actions" style="margin-top:10px"><button class="hud-btn" onclick="simOn()">Start simulator</button><button class="hud-btn" onclick="cmd('sim_off')">Stop simulator</button>
<button class="hud-btn" onclick="cmd('stream_on')">Restart video</button></div>
<div id="events" class="muted" style="margin-top:12px;max-height:150px;overflow:auto"></div></div></section>
</div></div>
<section class="panel" id="dockPanel" style="margin-top:16px"><div class="panel-head"><div class="panel-title">🛬 DJI Docks</div><div class="live" id="dockState">…</div></div>
<div class="panel-body"><div class="muted" style="margin-bottom:10px">A dock launches its drone with no pilot on site (DJI Cloud API). It connects to this PC over the site network; once it shows under <b>Found</b>, register it. With <b>Automatic flights</b> on (admins), operators can fly a saved route from the dock: it takes off, flies the route with video on, and lands back in the dock.</div>
<div id="dockLaunches"></div>
<div class="dk-list" id="dockList"></div>
<div id="dockMsg" class="hud-msg"></div>
<div class="dk-videos" id="dockVideos"></div>
<div class="dk-health" id="dockHealth"></div>
<details class="dk-setup" id="dockSetup" style="display:none"><summary>Set up a dock (admins)</summary>
<div class="muted" style="margin-top:10px"><b>1. DJI Cloud API keys</b> (once): developer.dji.com → Apps → Create App, App Type <b>Cloud API</b>. Paste the three values here.</div>
<div class="dk-form"><label>App ID<input id="dkAppId" autocomplete="off"></label>
<label>App Key<input id="dkAppKey" type="password" autocomplete="new-password" placeholder="unchanged"></label>
<label>App License<input id="dkAppLic" type="password" autocomplete="new-password" placeholder="unchanged"></label></div>
<div class="actions"><button class="hud-btn" onclick="dockSaveKeys()">Save keys</button><span class="muted" id="dkKeysState"></span></div>
<div class="muted" style="margin-top:14px"><b>2. Connect the dock</b>: on the dock's DJI RC Plus (connected to the dock and to this site's network), open <b>DJI Pilot 2 → Cloud Service → Open Platform</b> and enter this link, or scan the QR code. Pilot 2 then sends this PC's address to the dock.</div>
<div class="dk-pilot"><div class="qr" id="dkQr"></div><div style="flex:1;min-width:240px">
<div class="muted">Link: <code id="dkLink">…</code></div><div class="muted" style="margin-top:6px">Dock broker: <code id="dkBroker">…</code></div>
<div class="muted" style="margin-top:6px">Keep this link private: it carries the dock password. Making a new link stops the old one working (docks already connected stay connected).</div>
<div class="actions" style="margin-top:10px"><button class="hud-btn danger" onclick="dockNewLink()">New link</button></div></div></div>
<div class="muted" style="margin-top:14px"><b>3. Alarm launches</b>: when a drone is sent to a camera (automatic dispatch, handoff, Telegram, the dashboard), the nearest ready dock can go. By default the system asks first (Telegram and this page, “Launch / Don't”, expires after 5 min).</div>
<label class="muted" style="display:flex;gap:8px;align-items:center;margin-top:8px"><input type="checkbox" id="dkNoAsk" onchange="dockNoAsk(this)"> Launch docks <b>without asking</b> (the drone takes off by itself as soon as an alarm needs it)</label>
<div class="muted" style="margin-top:14px"><b>No dock yet?</b> Add a simulated Dock 3 with a Matrice 4TD to try the steps (it appears under Found at the map's centre).</div>
<div class="actions" style="margin-top:8px"><button class="hud-btn" id="dkSimBtn" onclick="dockSimulate()">+ Simulated dock</button></div>
</details></div></section>
</main>
<script src="/vendor/leaflet/leaflet.js"></script><script src="/mapsearch.js"></script>
<script>
const DRONE='drone';
{const f=window.fetch.bind(window);
 window.fetch=(u,o)=>f(typeof u==='string'&&/^\/api\/(drone\/|routes|response\/dispatch)/.test(u)?u+(u.includes('?')?'&':'?')+'drone='+encodeURIComponent(DRONE):u,o)}
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const fmt=(v,d=1)=>v==null||isNaN(v)?'–':Number(v).toFixed(d);
async function loadFleet(){try{const d=await fetch('/api/drone/links',{cache:'no-store'}).then(r=>r.json());if(!d.ok)return;
  const many=d.drones.length>1;droneNames=Object.fromEntries(d.drones.map(x=>[x.drone,x.label]));
  const bk=$('rtBackup');if(bk){const v=bk.value;bk.innerHTML='<option value="">None</option>'+d.drones.filter(x=>x.drone!==DRONE).map(x=>
    `<option value="${esc(x.drone)}" ${x.mission==='route'||x.mission==='backup'?'disabled':''}>${esc(x.label)}${x.mission==='route'?' (flying a route)':x.mission==='backup'?' (backup for another route)':x.drone_connected?'':' (offline)'}</option>`).join('');
    bk.value=[...bk.options].some(o=>o.value===v&&!o.disabled)?v:''}
  const sel=$('scDrone');if(sel&&sel.options.length!==d.drones.length+1){const v=sel.value;sel.innerHTML='<option value="">Any ready drone</option>'+d.drones.map(x=>`<option value="${esc(x.drone)}">${esc(x.label)}</option>`).join('');sel.value=v;sel.style.display=many?'':'none'}
  $('fleet').innerHTML=d.drones.map(x=>{const dot=x.drone_connected?'ok':x.phone_connected?'half':'';
    const info=x.over_limit?'over licence':x.mission?(x.mission==='route'?'on route':x.mission==='backup'?'backup':'responding'):x.drone_connected?(x.flying?'flying':'ready')+(x.battery!=null?' · '+x.battery+'%':''):x.phone_connected?'drone off':'not paired';
    return `<a href="/drone-control?drone=${encodeURIComponent(x.drone)}" class="${x.drone===DRONE?'on':''}"><i class="${dot}"></i>${esc(x.label)} <small>${esc(info)}</small></a>`}).join('')
    +`<span id="fleetDocks" style="display:contents"></span>`
    +`<button onclick="addDroneSlot()" ${d.can_add?'':'disabled'} title="${esc(d.message||'')}">+ Add drone <small>${d.used??'?'} of ${d.limit??'∞'}</small></button>`
    +`<a href="/drone-grid">▦ Grid view</a>`;
  if(!many&&!d.can_add)$('fleet').querySelector('button').style.display='none';
  $('fleet').querySelector('a[href="/drone-grid"]').style.display=many?'':'none';
  others=d.drones.filter(x=>x.drone!==DRONE&&x.lat&&x.lon);if(typeof drawOthers==='function')drawOthers();
  if(typeof drawDockFleet==='function')drawDockFleet()}catch(e){}}
async function addDroneSlot(){if(!confirm('Add another drone? It gets its own pairing QR code and video. Frigate restarts (about 20 s).'))return;
  const d=await fetch('/api/drone/add',{method:'POST'}).then(r=>r.json());
  if(d.ok){location.href='/drone-control?drone='+encodeURIComponent(d.name)}else alert(d.error||'Could not add a drone.')}
let others=[],oMarks=[],droneNames={};
let vcam=null;
function vcamUpdate(t){if(!$('vcam')||typeof L==='undefined'||!t.lat)return;
  const z=t.altitude>90?16:t.altitude>45?17:t.altitude>15?18:19;
  if(!vcam){vcam=L.map('vcam',{zoomControl:false,attributionControl:false,dragging:false,scrollWheelZoom:false,doubleClickZoom:false,boxZoom:false,keyboard:false,touchZoom:false});
    L.tileLayer('/tiles/sat/{z}/{x}/{y}',{maxZoom:19}).addTo(vcam);vcam.setView([t.lat,t.lon],z)}
  else vcam.setView([t.lat,t.lon],z,{animate:false})}
function drawOthers(){if(!map||!window.L)return;oMarks.forEach(m=>m.remove());
  oMarks=others.map(x=>L.circleMarker([x.lat,x.lon],{radius:7,color:'#ffb23c',fillColor:'#ffb23c',fillOpacity:.8}).bindTooltip(x.label,{permanent:true,direction:'right',className:''}).addTo(map))}
let st={},control=false,map=null,dMark=null,hMark=null,trail=null,keys=new Set(),lastStickZero=true;
function msg(t,ok){const e=$('cmdMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
async function cmd(c,args,confirmText){if(confirmText&&!confirm(confirmText))return;msg(c.replace('_',' ')+'…');
  try{const r=await fetch('/api/drone/command',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({cmd:c,args:args||{}})});const d=await r.json();
    if(!d.ok&&d.can_force&&confirm('⚠ '+d.error+'\n\nTake off anyway? You are responsible for the flight.'))return cmd(c,{...(args||{}),force:true});
    msg(d.ok?c.replace(/_/g,' ')+': done':d.error||'Failed',d.ok);return d.ok}catch(e){msg('Lost contact with the system',false)}}
function takeoff(){const sim=(st.telemetry||{}).simulator;
  cmd('takeoff',{},sim?'SIMULATOR take-off (motors stay locked). Continue?':'⚠ REAL TAKE-OFF: the simulator is OFF and the motors WILL start. Propellers on, people clear, drone in sight, pilot holding the controller?')}
async function stopAll(){keys.clear();await sendStick(true);cmd('hover')}
async function toggleControl(){if(!control){if(!(await cmd('control_on',{speed:+$('speed').value})))return;control=true}
  else{await sendStick(true);await cmd('control_off');control=false}
  $('ctlBtn').textContent='Keyboard control: '+(control?'ON':'OFF');$('ctlBtn').classList.toggle('dc-ctl-on',control)}
function stickFromInputs(){let x=0,y=0,z=0,r=0;
  if(keys.has('KeyA'))x-=1;if(keys.has('KeyD'))x+=1;if(keys.has('KeyW'))y+=1;if(keys.has('KeyS'))y-=1;
  if(keys.has('ArrowUp'))z+=1;if(keys.has('ArrowDown'))z-=1;if(keys.has('ArrowLeft'))r-=1;if(keys.has('ArrowRight'))r+=1;
  const gp=(navigator.getGamepads?[...navigator.getGamepads()]:[]).find(g=>g&&g.connected);
  if(gp){const dz=v=>Math.abs(v)<0.12?0:v;r+=dz(gp.axes[0]);z+=-dz(gp.axes[1]);x+=dz(gp.axes[2]);y+=-dz(gp.axes[3]);
    if(gp.buttons[1]&&gp.buttons[1].pressed){stopAll()}}
  const c=v=>Math.max(-1,Math.min(1,v));return{x:c(x),y:c(y),z:c(z),r:c(r)}}
async function sendStick(zero){const s=zero?{x:0,y:0,z:0,r:0}:stickFromInputs();const isZero=!s.x&&!s.y&&!s.z&&!s.r;
  if(isZero&&lastStickZero&&!zero)return;lastStickZero=isZero;
  try{await fetch('/api/drone/stick',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(s)})}catch(e){}}
setInterval(()=>{if(control&&document.hasFocus())sendStick(false)},100);
window.addEventListener('blur',()=>{keys.clear();if(control)sendStick(true)});
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'&&e.target.type!=='range')return;
  if(e.code==='Space'){e.preventDefault();stopAll();return}
  if(['KeyW','KeyA','KeyS','KeyD','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.code)){e.preventDefault();
    if(control)keys.add(e.code);else msg('Click “Keyboard control: OFF” to turn it ON first — then W/A/S/D and the arrow keys fly the drone.',false)}});
document.addEventListener('keyup',e=>keys.delete(e.code));
function initMap(lat,lon){if(map||typeof L==='undefined')return;map=L.map('dcMap',{zoomControl:true}).setView([lat,lon],18);
  L.tileLayer('/tiles/osm/{z}/{x}/{y}',{maxZoom:20,attribution:'© OpenStreetMap'}).addTo(map);window.addMapSearch&&addMapSearch(map);
  trail=L.polyline([],{color:'#36cfff',weight:2}).addTo(map);
  map.on('click',e=>mapClick(e.latlng.lat,e.latlng.lng));drawNofly()}
// A click on the flat map or on the ground in 4D live: a zone corner while drawing a zone, a camera's place, else a route stop.
function mapClick(lat,lon){nfPts?nfAdd(lat,lon):locFor?saveCamLoc(lat,lon):addPoint(lat,lon)}
function distM(a,b,c,d){const R=6371000,p1=a*Math.PI/180,p2=c*Math.PI/180,dp=(c-a)*Math.PI/180,dl=(d-b)*Math.PI/180;
  const x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))}
function drone_icon(hdg){return L.divIcon({className:'',iconSize:[26,26],iconAnchor:[13,13],html:`<div style="transform:rotate(${hdg||0}deg);color:#25c7ff;font-size:24px;line-height:26px;text-align:center;text-shadow:0 0 6px #000">▲</div>`})}
function render(){const t=st.telemetry||{};const on=st.phone_connected,fresh=st.telemetry_fresh;
  $('linkState').innerHTML=!st.allowed?'<i class="dot bad"></i>NOT LICENSED':on?(t.drone_connected?'<i class="dot good"></i>DRONE LINKED':'<i class="dot warn"></i>PHONE CONNECTED · DRONE OFF'):'<i class="dot bad"></i>PHONE NOT CONNECTED';
  $('pairPanel').style.display=on?'none':'';
  $('flyState').textContent=t.flying?'IN FLIGHT':(t.motors_on?'MOTORS ON':'ON GROUND');
  $('modeState').textContent=t.simulator?'SIMULATOR':'';$('simState').textContent=t.simulator?'SIMULATOR ON':'';
  const sp=t.speed;[['hAlt','tAlt',t.altitude,' m'],['hDist','tDist',t.distance_home,' m'],['hSpd','tSpd',sp,' m/s']].forEach(([a,b,v,u])=>{$(a).textContent=fmt(v);$(b).textContent=fmt(v)+(v==null?'':u)});
  $('hBat').textContent=t.battery??'–';$('tBat').textContent=t.battery==null?'–':t.battery+'%';$('hGps').textContent=t.gps_satellites??'–';$('tGps').textContent=t.gps_satellites??'–';
  $('hSig').textContent=t.signal==null?'–':t.signal+'%';$('tHdg').textContent=t.heading==null?'–':Math.round((t.heading+360)%360)+'°';$('tMode').textContent=t.flight_mode||'–';
  $('tCtl').textContent=t.control||'–';$('confirmLand').style.display=t.landing_confirm_needed?'':'none';
  if(control&&t.control&&t.control!=='PC'){control=false;$('ctlBtn').textContent='Keyboard control: OFF';$('ctlBtn').classList.remove('dc-ctl-on');msg(/LANDING|GO_HOME/.test(t.flight_mode||'')?'Keyboard control ended: the drone is landing / returning home by itself.':'The pilot took control on the remote controller.',false)}
  if(t.lat&&t.lon){initMap(t.lat,t.lon);if(map){const p=[t.lat,t.lon];dMark=dMark||L.marker(p).addTo(map);dMark.setLatLng(p).setIcon(drone_icon(t.heading));
    trail.addLatLng(p);if(t.home_lat&&t.home_lon){hMark=hMark||L.circleMarker([t.home_lat,t.home_lon],{radius:7,color:'#2aea88'}).bindTooltip('Home').addTo(map);hMark.setLatLng([t.home_lat,t.home_lon]);
      // The range ring: every route stop must be inside it.
      rCircle=rCircle||L.circle([t.home_lat,t.home_lon],{radius:rMax,color:'#36cfff',weight:1.5,dashArray:'8 6',fillColor:'#36cfff',fillOpacity:.04,interactive:false}).addTo(map);
      rCircle.setLatLng([t.home_lat,t.home_lon]).setRadius(rMax)}}
    $('coords').textContent=t.lat.toFixed(6)+', '+t.lon.toFixed(6)}
  $('mapState').textContent=typeof L==='undefined'?'MAP NEEDS INTERNET':'';
  const m=t.mission;if(m)$('flyState').textContent='AUTO-FLY · '+m.state+(m.distance>=0?' · '+Math.round(m.distance)+' m to stop':'');
  vcamUpdate(t);
  $('events').innerHTML=(st.events||[]).slice().reverse().map(e=>`<div>${new Date(e.at*1000).toLocaleTimeString()} · ${esc(e.msg)}</div>`).join('')}
const DAYS=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];let scheds=[];
function scmsg(t,ok){const e=$('schedMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
function renderScheds(){const names=Object.keys(routes);$('scRoute').innerHTML=names.length?names.map(n=>`<option>${esc(n)}</option>`).join(''):'<option value="">Save a route first</option>';
  if(!$('scDays').children.length)$('scDays').innerHTML=DAYS.map((d,i)=>`<label style="margin:0;display:flex;gap:3px;align-items:center;text-transform:none;letter-spacing:0;font-size:12px"><input type="checkbox" data-day="${i}" checked>${d}</label>`).join('');
  $('schedList').innerHTML=scheds.map((s,i)=>`<div class="hud-row"><div><b>${esc(s.route)}</b> at ${esc(s.time)}<div class="muted">${s.days.length===7?'Every day':s.days.map(d=>DAYS.at(d)).join(', ')} · ${s.auto_start?'auto-start':'asks first on Telegram'}${s.drone?' · '+esc(droneNames[s.drone]||s.drone):''}${s.enabled?'':' · paused'}</div></div>
    <div class="actions"><button class="hud-btn" onclick="toggleSched(${i})">${s.enabled?'Pause':'Resume'}</button><button class="hud-btn danger" onclick="delSched(${i})">Delete</button></div></div>`).join('')||'<p class="muted">No scheduled patrols.</p>'}
async function saveScheds(note){const d=await fetch('/api/response/settings',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({patrol_schedules:scheds})}).then(r=>r.json());
  if(d.ok){scheds=d.settings.patrol_schedules;scmsg(note,true)}else scmsg(d.error,false);renderScheds()}
function addSched(){const route=$('scRoute').value,days=[...$('scDays').querySelectorAll('input:checked')].map(x=>+x.dataset.day);
  if(!route){scmsg('Save a route first.',false);return}if(!days.length){scmsg('Choose at least one day.',false);return}
  const auto=$('scAuto').checked;if(auto&&!confirm('Auto-start flies the drone with no confirmation at '+$('scTime').value+'. Only use it when the drone and controller are on, the area is clear, and a pilot can take over. Continue?'))return;
  scheds=[...scheds,{route,time:$('scTime').value,days,enabled:true,auto_start:auto,drone:$('scDrone').value}];saveScheds('Schedule added.')}
function toggleSched(i){scheds=scheds.map((s,j)=>j===i?{...s,enabled:!s.enabled}:s);saveScheds('Updated.')}
function delSched(i){if(!confirm('Delete this schedule?'))return;scheds=scheds.filter((s,j)=>j!==i);saveScheds('Deleted.')}
async function loadScheds(){try{const d=await fetch('/api/response/settings').then(r=>r.json());scheds=d.settings.patrol_schedules||[];renderScheds()}catch(e){}}
let route=[],routes={},rLine=null,rMarks=[],rMax=500,filledRun='',rCircle=null;
let nfZones=[],nfPts=null,nfLayers=[],nfTmp=null,nfArm='';
function nfmsg(t,ok){const e=$('nfMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
function nfButtons(){const on=!!nfPts;$('nfDrawBtn').style.display=on?'none':'';['nfName','nfSaveBtn','nfUndoBtn','nfCancelBtn'].forEach(id=>$(id).style.display=on?'':'none')}
async function loadNofly(){try{const d=await fetch('/api/nofly?drone='+encodeURIComponent(DRONE)).then(r=>r.json());nfZones=d.zones||[];
  if(d.max_distance_m)document.querySelectorAll('.nf-range').forEach(e=>e.textContent=d.max_distance_m);
  if(d.map_cache)$('mapCache').textContent='Offline map: '+d.map_cache.tiles+' tiles saved ('+d.map_cache.mb+' MB). Pan and zoom round the site once while online to save it for use without internet.';
  if(!map&&d.centre)initMap(d.centre[0],d.centre[1]);drawNofly()}catch(e){}}
function drawNofly(){
  $('nfList').innerHTML=nfZones.length?nfZones.map(z=>`<span class="nf-chip">⛔ ${esc(z.name)}<button type="button" class="${nfArm===z.id?'armed':''}" title="Delete this zone" onclick="nfDel('${esc(z.id)}')">${nfArm===z.id?'Delete?':'✕'}</button></span>`).join(''):'<span class="muted">No zones yet.</span>';
  if(!map||typeof L==='undefined')return;nfLayers.forEach(l=>map.removeLayer(l));
  nfLayers=nfZones.map(z=>L.polygon(z.points.map(p=>[p.lat,p.lon]),{color:'#ff4d6a',weight:2,fillColor:'#ff4d6a',fillOpacity:.25}).bindTooltip('⛔ No-fly: '+z.name).addTo(map));
  if(nfTmp){map.removeLayer(nfTmp);nfTmp=null}
  if(nfPts&&nfPts.length)nfTmp=(nfPts.length>2?L.polygon(nfPts,{color:'#ff4d6a',dashArray:'4 4',fillOpacity:.12}):L.polyline(nfPts,{color:'#ff4d6a',dashArray:'4 4'})).addTo(map)}
function nfDraw(){if(!map){nfmsg('The map shows once a drone is connected or a camera location is saved.',false);return}
  nfPts=[];nfButtons();nfmsg('Click the map to place each corner of the zone (3 or more), give it a name, then press Save zone.',null)}
function nfAdd(lat,lon){nfPts.push([lat,lon]);drawNofly();nfmsg(nfPts.length+' corner'+(nfPts.length>1?'s':'')+(nfPts.length<3?' (at least 3)':'')+'.',null)}
function nfUndo(){if(nfPts&&nfPts.length){nfPts.pop();drawNofly()}}
function nfCancel(){nfPts=null;nfButtons();drawNofly();nfmsg('',null)}
async function nfSave(){if(!nfPts||nfPts.length<3){nfmsg('Place at least 3 corners on the map.',false);return}
  const d=await fetch('/api/nofly',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:$('nfName').value,points:nfPts.map(p=>({lat:p[0],lon:p[1]}))})}).then(r=>r.json());
  if(!d.ok){nfmsg(d.error,false);return}nfZones=d.zones;nfPts=null;$('nfName').value='';nfButtons();drawNofly();
  nfmsg('Zone “'+d.zone.name+'” saved. Routes crossing it are refused and auto-fly flies round it.',true)}
async function nfDel(id){if(nfArm!==id){nfArm=id;drawNofly();setTimeout(()=>{if(nfArm===id){nfArm='';drawNofly()}},4000);return}
  nfArm='';const d=await fetch('/api/nofly',{method:'DELETE',headers:{'content-type':'application/json'},body:JSON.stringify({id})}).then(r=>r.json());
  if(d.ok){nfZones=d.zones;nfmsg('Zone deleted.',true)}drawNofly()}
loadNofly();setInterval(loadNofly,15000);
function rtmsg(t,ok){const e=$('routeMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
function addPoint(lat,lon){if(route.length>=25){rtmsg('25 stops maximum.',false);return}route.push({lat,lon});drawRoute()}
function undoPoint(){route.pop();drawRoute()}
function clearRoute(){route=[];drawRoute()}
function homePos(){const t=st.telemetry||{};return t.home_lat?[t.home_lat,t.home_lon]:(t.lat?[t.lat,t.lon]:null)}
function routeInfo(){const h=homePos();let len=0,far=[];
  route.forEach((p,i)=>{const prev=i?route[i-1]:(h?{lat:h[0],lon:h[1]}:null);if(prev)len+=distM(prev.lat,prev.lon,p.lat,p.lon);
    if(h&&distM(h[0],h[1],p.lat,p.lon)>rMax)far.push(i+1)});
  if(h&&route.length&&$('rtEnd').value==='home'){const l=route[route.length-1];len+=distM(l.lat,l.lon,h[0],h[1])}
  const sp=+$('rtSpeed').value||5,mins=(len/sp+(+$('rtAlt').value||30)/2+route.length*(+$('rtPause').value||0)+30)/60;
  $('routeInfo').innerHTML=route.length?`<b>${route.length}</b> stop${route.length>1?'s':''} · <b>${Math.round(len)} m</b> · about <b>${mins.toFixed(1)} min</b> (≈ ${Math.ceil(mins*3.5)}% battery)`+
    (far.length?` · <span style="color:#ff8a8a">stop ${far.join(', ')} beyond ${rMax} m</span>`:'')+(h?'':' · <span style="color:#ffbd66">drone position unknown</span>'):'No stops yet.'}
function drawRoute(){routeInfo();if(!map||typeof L==='undefined')return;rMarks.forEach(m=>map.removeLayer(m));rMarks=[];
  rLine=rLine||L.polyline([],{color:'#ffd23f',weight:3}).addTo(map);rLine.setLatLngs(route.map(p=>[p.lat,p.lon]));
  route.forEach((p,i)=>rMarks.push(L.marker([p.lat,p.lon],{icon:L.divIcon({className:'',iconSize:[22,22],iconAnchor:[11,11],
    html:`<div style="width:22px;height:22px;border-radius:50%;background:#ffd23f;color:#111;font:bold 12px Arial;display:flex;align-items:center;justify-content:center;box-shadow:0 0 6px #000">${i+1}</div>`})}).addTo(map)))}
async function shortestOrder(){if(route.length<3){rtmsg('Add at least 3 stops to reorder.',false);return}
  const d=await fetch('/api/routes/optimize',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({points:route,loop:$('rtLoop').checked,drone:DRONE})}).then(r=>r.json());
  if(!d.ok){rtmsg(d.error,false);return}
  if(d.after_m>=d.before_m){rtmsg(`The stops are already in the shortest order (${d.before_m} m${d.from_home?' from home':''}).`,true);return}
  route=d.points;drawRoute();rtmsg(`Reordered: ${d.before_m} m → ${d.after_m} m (${Math.round((1-d.after_m/d.before_m)*100)}% shorter${d.from_home?', from the home point':''}). Save the route to keep the new order.`,true)}
let sigMarks=[];
async function checkSignal(){if(!route.length){rtmsg('Add stops first.',false);return}
  const d=await fetch('/api/rf/check',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({points:route,alt:+$('rtAlt').value})}).then(r=>r.json());
  if(!d.ok){rtmsg(d.error,false);return}
  sigMarks.forEach(m=>map&&map.removeLayer(m));sigMarks=[];const col={good:'#26ee89',weak:'#ffd23f',poor:'#ff4d6a'};
  if(map)d.results.forEach(r=>sigMarks.push(L.circleMarker([r.lat,r.lon],{radius:9,color:col[r.quality],weight:3,fill:false})
    .bindTooltip(`Signal ${r.quality} (${r.margin_db>0?'+':''}${r.margin_db} dB)`).addTo(map)));
  rtmsg(d.summary,d.worst.quality==='good')}
// 4D live: the map's switch swaps the flat map for the live 3D view (drones, trails, routes, zones, aircraft).
let l4d=null;
function storeGet(k){try{return localStorage.getItem(k)}catch(e){return null}}
function storeSet(k,v){try{localStorage.setItem(k,v)}catch(e){}}
// 3D MAP: the 3D site-maps tool (plan an area, fly it, process, open the model) in place of the flat map.
// Back on a view that was already open: go to the place last looked at (search, Locate me, moving any map or 4D).
function goFocus(m){const f=window.mapFocus&&mapFocus.get();if(f&&m)m.setView([f.lat,f.lon],f.zoom||m.getZoom())}
function toggle3d(on){$('m3dOn').checked=on;storeSet('m3d-on',on?'1':'0');
  if(on&&$('l4dOn').checked)toggle4d(false);
  const f=$('m3d');if(on&&!f.src)f.src='/maps-embed';else if(on)try{goFocus(f.contentWindow.map)}catch(e){}
  f.style.display=on?'block':'none';$('dcMap').style.display=on||$('l4dOn').checked?'none':'';
  if(!on&&map&&!$('l4dOn').checked)setTimeout(()=>{map.invalidateSize();goFocus(map)},50)}
if(storeGet('m3d-on')==='1')setTimeout(()=>toggle3d(true),300);
async function toggle4d(on){$('l4dOn').checked=on;storeSet('l4d-on',on?'1':'0');
  if(on&&$('m3dOn').checked)toggle3d(false);
  $('dcMap').style.display=on?'none':'';$('l4d').style.display=on?'block':'none';$('l4dBar').style.display=on?'flex':'none';
  if(!on){if(l4d)l4d.stop();if(map&&!$('m3dOn').checked)setTimeout(()=>{map.invalidateSize();goFocus(map)},50);return}
  try{l4d=l4d||await import('/live4d.js');l4d.start($('l4d'),$('l4dBar'),DRONE,{click:mapClick,draft:()=>({route,alt:+$('rtAlt').value||30,zone:nfPts})})}
  catch(e){$('l4d').innerHTML='<p class="muted" style="padding:14px">The 3D view could not start in this browser: '+esc(e.message||e)+'</p>'}}
if(storeGet('l4d-on')==='1'&&storeGet('m3d-on')!=='1')setTimeout(()=>toggle4d(true),300);
// Admins can remove a drone: virtual drones are deleted, added drones removed from the plan, the first drone unpaired.
if(typeof IS_ADMIN!=='undefined'&&IS_ADMIN){const b=$('rmDrone');b.style.display='';
  b.textContent=DRONE==='drone'?'🗑 Unpair this drone':'🗑 Remove this drone'}
async function removeDrone(){const name=document.title.split(' · ')[0];
  const first=DRONE==='drone';
  if(!confirm(first?`Unpair ${name}? Its phone is disconnected and gets a new pairing code (the first drone slot always stays).`
    :`Remove ${name}? ${DRONE.startsWith('drone-v')?'The virtual drone is deleted.':'It is removed from this PC and its plan slot is freed; pairing it again needs a new QR scan.'}`))return;
  const d=await fetch('/api/drone/remove',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({drone:DRONE})}).then(async r=>{try{return await r.json()}catch(e){return {ok:false,error:'HTTP '+r.status}}});
  if(!d.ok){alert(d.error||'Could not remove it.');return}
  alert(d.message);location.href=d.removed?'/drone-control':location.href}
let acMarks=[];
// The one-row flight-safety strip: verdict, weather, aircraft, airspace (full settings on Flight safety).
function renderStrip(d){const c=d.conditions,v=$('fsVerdict'),w=d.weather||{},r=w.reading,t=d.traffic||{},s=d.settings||{};
  v.className='fs-cell '+(c.problem?'bad':c.warnings.length?'warn':'ok');v.title=c.problem||c.warnings.join(' ')||'No weather or air-traffic problem found.';
  v.innerHTML=c.problem?'⛔ <b>On hold</b> '+esc(c.problem.length>90?c.problem.slice(0,88)+'…':c.problem):c.warnings.length?'⚠ <b>Warnings</b> '+esc(c.warnings[0]):'✔ <b>Clear to fly</b>';
  const wx=$('fsWx');wx.className='fs-cell'+((w.issues||[]).length?' warn':'');
  wx.innerHTML=!w.enabled?'☁ Weather check off':!r?'☁ Weather unknown':`☁ <b>${r.wind_ms==null?'–':(+r.wind_ms).toFixed(1)}</b> m/s · gusts <b>${r.gust_ms==null?'–':(+r.gust_ms).toFixed(1)}</b> · ${esc(r.text)} · ${r.temp_c==null?'':Math.round(r.temp_c)+' °C'}`;
  const ac=$('fsAc'),th=(t.threats||[]).length;ac.className='fs-cell'+(th?' bad':'');
  ac.innerHTML=!(s.traffic||{}).enabled?'✈ Air traffic watch off':!t.fresh?'✈ No traffic data':`✈ <b>${(t.aircraft||[]).length}</b> aircraft${th?` · <b>${th} close</b>`:''}`;
  const z=d.zones||[],on=z.filter(x=>x.enabled!==false),imp=on.filter(x=>x.source).length;
  $('fsZones').innerHTML=`🛇 <b>${on.length}</b> no-fly zone${on.length===1?'':'s'}${imp?` (${imp} official)`:''}`}
async function loadSafety(){try{const d=await fetch('/api/safety',{cache:'no-store'}).then(r=>r.json());if(!d.ok)return;
  renderStrip(d);
  if(!map)return;acMarks.forEach(m=>map.removeLayer(m));acMarks=[];const th=new Set((d.traffic.threats||[]).map(a=>a.hex));
  (d.traffic.fresh?d.traffic.aircraft:[]).forEach(a=>acMarks.push(L.marker([a.lat,a.lon],{icon:L.divIcon({className:'',iconSize:[24,24],iconAnchor:[12,12],
    html:`<div style="transform:rotate(${(a.track||0)-45}deg);font-size:18px;line-height:24px;text-align:center;color:${th.has(a.hex)?'#ff4d6a':'#ffd23f'};text-shadow:0 0 4px #000">✈</div>`})})
    .bindTooltip(`${esc(a.call||a.hex)} · ${(a.dist_m/1000).toFixed(1)} km · ${a.height_ft==null?'?':Math.round(a.height_ft/100)*100} ft`).addTo(map)))}catch(e){}}
setInterval(loadSafety,10000);setTimeout(loadSafety,1500);
async function loadRoutes(){try{const d=await fetch('/api/routes').then(r=>r.json());routes=d.routes||{};rMax=d.max_distance_m||500;$('routeMax').textContent=rMax;if(rCircle)rCircle.setRadius(rMax);
  const sel=$('routeSel'),cur=sel.value;sel.innerHTML='<option value="">Saved routes…</option>'+Object.keys(routes).map(n=>`<option>${esc(n)}</option>`).join('');sel.value=cur;
  if(typeof renderScheds==='function'&&$('scRoute'))renderScheds();
  const bf=d.backup_for;$('backupNote').style.display=bf?'':'none';$('flyRouteBtn').disabled=!!bf;
  if(bf)$('backupNote').textContent='This drone is the backup for '+bf.label+' on route “'+bf.name+'”. It can\'t fly its own route until that route ends. Its route is shown on the map.';
  const r=d.run||{};
  // A backup (or a drone that took over) shows the route it covers, filled once per run so later edits stay.
  const cover=bf&&bf.route?bf:(r.active&&r.route?r:null);
  if(cover&&cover.id&&cover.id!==filledRun){filledRun=cover.id;loadRoute(cover.name,cover.route)}
  $('patrolReport').style.display=!r.active&&r.report?'':'none';if(r.report)$('patrolReport').textContent=r.report;$('routeState').textContent=r.active?('ROUTE '+r.name+' · '+r.message):(r.message||'')}catch(e){}}
function loadRoute(n,given){const r=given||routes[n];if(!r)return;route=r.points.map(p=>({...p}));$('rtAlt').value=r.alt;$('rtSpeed').value=r.speed;$('rtPause').value=r.pause;$('rtEnd').value=r.end;$('rtLoop').checked=!!r.loop;$('rtRelay').checked=!!r.relay;$('rtSwap').value=r.swap_at||20;$('rtNoBat').checked=!!r.ignore_battery;noBatUi();$('rtLostOn').checked=r.lost_link_on!==false;$('rtLost').value=r.lost_link||'home';$('rtLost').disabled=!$('rtLostOn').checked;$('rtName').value=n;drawRoute();
  if(map&&route.length)map.fitBounds(route.map(p=>[p.lat,p.lon]),{padding:[30,30]})}
function routeBody(){return{points:route,alt:+$('rtAlt').value,speed:+$('rtSpeed').value,pause:+$('rtPause').value,end:$('rtEnd').value,
  loop:$('rtLoop').checked,relay:$('rtRelay').checked,swap_at:+$('rtSwap').value||20,ignore_battery:$('rtNoBat').checked,lost_link_on:$('rtLostOn').checked,lost_link:$('rtLost').value,backup:$('rtNoBat').checked?'':$('rtBackup').value}}
// Ignoring the battery means no swap, so relay and backup are switched off while it is ticked.
function noBatUi(){const on=$('rtNoBat').checked;['rtRelay','rtSwap','rtBackup'].forEach(id=>$(id).disabled=on);$('noBatNote').style.display=on?'':'none';
  if(on)$('rtLoop').checked=true;$('rtLoop').disabled=on;routeInfo()}
async function saveRoute(){if(!route.length){rtmsg('Draw at least one stop.',false);return}const d=await fetch('/api/routes',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({...routeBody(),name:$('rtName').value})}).then(r=>r.json());
  rtmsg(d.ok?'Route “'+d.name+'” saved.':d.error,d.ok);await loadRoutes();if(d.ok)$('routeSel').value=d.name}
async function deleteRoute(){const n=$('routeSel').value;if(!n||!confirm('Delete route “'+n+'”?'))return;await fetch('/api/routes',{method:'DELETE',headers:{'content-type':'application/json'},body:JSON.stringify({name:n})});rtmsg('Deleted.',true);loadRoutes()}
async function flyRoute(){if(!route.length){rtmsg('Click the map to add stops, or choose a saved route.',false);return}const sim=(st.telemetry||{}).simulator;
  if(!confirm((sim?'SIMULATOR: ':'REAL FLIGHT: the drone takes off if it is on the ground. ')+'Fly '+route.length+' stop'+(route.length>1?'s':'')+' at '+$('rtAlt').value+' m'
    +($('rtLoop').checked?', repeating the route until you press Stop route':'')+'? Keep the drone in sight.'))return;
  const d=await fetch('/api/routes/fly',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({...routeBody(),name:$('rtName').value||$('routeSel').value||'route'})}).then(r=>r.json());
  rtmsg(d.message||d.error,d.ok);loadRoutes()}
async function stopRoute(){const d=await fetch('/api/routes/stop',{method:'POST'}).then(r=>r.json());rtmsg(d.ok?'Route stopped, drone hovering.':d.error,d.ok);loadRoutes()}
setInterval(loadRoutes,3000);
let resp=null,locFor='',camMarks={};
function rmsg(t,ok){const e=$('respMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
async function loadResp(){try{const d=await fetch('/api/response/settings').then(r=>r.json());resp=d;const c=d.settings;
  $('rAlt').value=c.altitude_m;$('rSpeed').value=c.speed_ms;$('rHover').value=c.hover_seconds;$('rBatt').value=c.min_battery;$('rBrief').value=c.briefing_time;
  $('rReturn').checked=!!c.auto_return;$('rBriefOn').checked=!!c.briefing_enabled;
  if(document.activeElement?.closest?.('#respAutoBox')==null){$('rAuto').checked=!!c.auto_dispatch;$('rAutoP').checked=!!c.auto_person;$('rAutoV').checked=!!c.auto_vehicle;
    $('rFrom').value=c.auto_from;$('rTo').value=c.auto_to;$('rCool').value=c.auto_cooldown_min;$('rHandoff').checked=!!c.handoff}renderResp()}catch(e){}}
function handoffWarn(el){if(el.checked&&!confirm('Handoff flies a drone with no confirmation when someone leaves a camera\'s view in that time window. Only use it when the drones and controllers stay on, the area is safe to fly and a pilot can take over. Turn it on?'))el.checked=false}
function autoWarn(el){if(el.checked&&!confirm('Auto-send flies a drone with no confirmation when a camera sees someone in that time window. Only use it when the drones and controllers stay on, the area is safe to fly and a pilot can take over. Turn it on?'))el.checked=false}
function renderResp(){if(!resp)return;const locs=resp.settings.camera_locations||{},r=resp.response||{};
  $('respState').textContent=r.active?('RESPONDING: '+r.camera+' · '+r.phase):(resp.telegram?'TELEGRAM READY':'TELEGRAM NOT SET UP');
  $('respCams').innerHTML=(resp.cameras||[]).filter(n=>!/^drone/i.test(n)).map(n=>{const l=locs[n];return `<div class="hud-row"><div><b>${esc(n)}</b><div class="muted">${l?('📍 '+l.lat.toFixed(5)+', '+l.lon.toFixed(5)):'No location yet'}</div></div>
    <div class="actions"><button class="hud-btn" onclick="pickLoc('${esc(n)}')">${locFor===n?'Click the map…':(l?'Move':'Set on map')}</button>${l?`<button class="hud-btn primary" onclick="sendTo('${esc(n)}')">Send drone</button>`:''}</div></div>`}).join('')||'<p class="muted">No cameras yet.</p>';
  if(map&&typeof L!=='undefined'){for(const [n,l] of Object.entries(locs)){camMarks[n]=camMarks[n]||L.marker([l.lat,l.lon],{icon:L.divIcon({className:'',iconSize:[24,24],iconAnchor:[12,12],html:'<div style="font-size:20px;line-height:24px;text-shadow:0 0 6px #000">📹</div>'})}).bindTooltip(n).addTo(map);camMarks[n].setLatLng([l.lat,l.lon])}}}
function pickLoc(n){locFor=n;rmsg('Click the camera\'s position on the map.');renderResp()}
async function saveCamLoc(lat,lon){const n=locFor;locFor='';const locs={...(resp.settings.camera_locations||{}),[n]:{lat,lon}};
  const d=await fetch('/api/response/settings',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({camera_locations:locs})}).then(r=>r.json());
  if(d.ok){resp.settings=d.settings;rmsg('Location of '+n+' saved.',true)}else rmsg(d.error,false);renderResp()}
async function saveResp(){const body={altitude_m:+$('rAlt').value,speed_ms:+$('rSpeed').value,hover_seconds:+$('rHover').value,min_battery:+$('rBatt').value,
  briefing_time:$('rBrief').value,auto_return:$('rReturn').checked,briefing_enabled:$('rBriefOn').checked,
  auto_dispatch:$('rAuto').checked,auto_person:$('rAutoP').checked,auto_vehicle:$('rAutoV').checked,auto_from:$('rFrom').value,auto_to:$('rTo').value,auto_cooldown_min:+$('rCool').value||10,handoff:$('rHandoff').checked};
  const d=await fetch('/api/response/settings',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
  if(d.ok){resp.settings=d.settings;rmsg('Saved.',true);loadResp()}else rmsg(d.error,false)}
async function sendTo(n){const sim=(st.telemetry||{}).simulator;
  if(!confirm((sim?'SIMULATOR: ':'REAL FLIGHT: the drone takes off if it is on the ground. ')+'Send the drone to '+n+'? Keep it in sight.'))return;
  const d=await fetch('/api/response/dispatch',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({camera:n})}).then(r=>r.json());rmsg(d.message||d.error,d.ok);loadResp()}
async function recallResp(){const d=await fetch('/api/response/recall',{method:'POST'}).then(r=>r.json());rmsg(d.ok?'Drone returning home.':d.error,d.ok);loadResp()}
async function briefNow(){const d=await fetch('/api/assistant/briefing',{method:'POST'}).then(r=>r.json());rmsg(d.ok?'Briefing sent to Telegram.':d.error,d.ok)}
setInterval(()=>{if(!locFor)loadResp()},5000);
async function poll(){try{st=await fetch('/api/drone/link',{cache:'no-store'}).then(r=>r.json());render()}catch(e){}}
async function loadPair(){try{const d=await fetch('/api/drone/link/pair').then(r=>r.json());if(!d.ok){$('pairMsg').className='hud-msg bad';$('pairMsg').textContent=d.error;return}
  $('pairQr').innerHTML=d.qr;$('pairAddr').textContent=d.host+':'+d.port}catch(e){}}
async function resetPair(){if(!confirm('Make a new pairing code? The phone will have to scan again.'))return;await fetch('/api/drone/link/pair/reset',{method:'POST'});loadPair()}
function simOn(){if(!confirm('Start the simulator? Remove the propellers first.'))return;
  const go=(lat,lon)=>cmd('sim_on',{lat,lon});const t=st.telemetry||{};
  if(t.lat&&t.lon)return go(t.lat,t.lon);navigator.geolocation?navigator.geolocation.getCurrentPosition(p=>go(p.coords.latitude,p.coords.longitude),()=>go(33.8938,35.5018)):go(33.8938,35.5018)}
// ---- DJI Docks ----
const DK_ADMIN=typeof IS_ADMIN!=='undefined'&&IS_ADMIN;
function dkMsg(t,ok){const e=$('dockMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t||''}
async function dkPost(url,body,method){const r=await fetch(url,{method:method||'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body||{})});
  let d={};try{d=await r.json()}catch(e){}return d.ok?d:{ok:false,error:d.error||('Failed ('+r.status+')')}}
let dkFull=false;
function dkCard(x,found){const tags=[];if(x.over_limit)tags.push('OVER LICENCE');
  if(x.drone_model)tags.push((x.drone_in_dock===false?'✈ ':'⌂ ')+esc(x.drone_model)+(x.drone_in_dock===false?' out':' in dock'));
  if(x.battery!=null)tags.push('🔋 '+x.battery+'%'+(x.charging?' charging':''));
  if(x.cover)tags.push(x.cover==='cover fault'?'Cover fault':'Cover '+esc(x.cover));if(x.mode)tags.push(esc(x.mode));
  if(x.temperature!=null)tags.push('🌡 '+fmt(x.temperature)+' °C');if(x.wind!=null)tags.push('💨 '+fmt(x.wind)+' m/s');
  if(x.rain&&x.rain!=='none')tags.push('🌧 '+esc(x.rain));if(x.simulated)tags.push('SIMULATED');
  const dot=x.online?'good':'bad',al=x.alerts||[];
  const sev=al.some(a=>a.level==='warning')?' dk-bad':al.length?' dk-careful':'';
  const alerts=al.map(a=>`<div class="dk-alert ${esc(a.level)}">${a.level==='warning'?'⚠':'●'} ${esc(a.text)}</div>`).join('');
  const faults=[['','Test a problem…'],['offline','Goes offline (alert after 1 min)'],['cover','Cover fault'],['rain','Heavy rain'],['wind','Strong wind'],['hot','Too hot'],['battery','Drone battery low'],['hms','DJI warning'],['','All clear']];
  const v=x.video||{},LN={wide:'Wide',zoom:'Zoom',ir:'Thermal',normal:'Main'};
  const vid=found||x.over_limit||!x.online?'':v.streaming
    ?`<button class="hud-btn danger" data-sn="${esc(x.sn)}" onclick="dockVideo(this.dataset.sn,'stop')">■ Stop video</button>`
      +((v.lenses||[]).length>1?`<select data-sn="${esc(x.sn)}" onchange="this.blur();dockVideo(this.dataset.sn,'lens',this.value)">${v.lenses.map(l=>`<option value="${l}" ${l===v.lens?'selected':''}>${LN[l]||l}</option>`).join('')}</select>`:'')
    :`<button class="hud-btn" data-sn="${esc(x.sn)}" onclick="dockVideo(this.dataset.sn,'start')" ${(v.sources||[]).includes('drone')?'':'disabled title="The drone isn\'t reporting a camera yet"'}>▶ Drone video</button>`
      +((v.sources||[]).includes('dock')?`<button class="hud-btn" data-sn="${esc(x.sn)}" onclick="dockVideo(this.dataset.sn,'start',null,'dock')">▶ Dock camera</button>`:'');
  if(v.streaming)tags.unshift('● LIVE · '+(v.device==='dock'?'dock camera':(LN[v.lens]||v.lens||'')));
  // Phase 3: missions
  const m=x.mission,ma=m&&m.active,MS={starting:'starting',sent:'starting',in_progress:'flying',paused:'paused',returning:'returning to dock'};
  if(ma)tags.unshift(`🛫 ${esc(m.name)} · ${MS[m.status]||esc(m.status)}${m.status==='in_progress'?' · '+m.percent+'%':''}`);
  else if(m&&m.ended)tags.push(`Last route ${esc(m.name)}: ${m.status==='ok'?'done':esc(m.status)}`);
  let fly='';
  if(!found&&!x.over_limit){
    if(ma)fly=`<button class="hud-btn danger" data-sn="${esc(x.sn)}" onclick="dockMission(this.dataset.sn,'stop')">⏹ Return to dock</button>`;
    else if(x.auto_flights&&x.online)fly=`<select id="dkRoute_${esc(x.sn)}" data-sn="${esc(x.sn)}" onchange="dkRouteSel[this.dataset.sn]=this.value;this.blur()" style="max-width:160px">`
      +(dkRoutes.length?dkRoutes.map(r=>`<option ${dkRouteSel[x.sn]===r?'selected':''}>${esc(r)}</option>`).join(''):'<option value="">No saved routes</option>')
      +`</select><button class="hud-btn" data-sn="${esc(x.sn)}" onclick="dockMission(this.dataset.sn,'fly')" ${dkRoutes.length?'':'disabled'}>🛫 Fly route</button>`;
    else if(!x.auto_flights)fly=`<span class="muted" style="font-size:12px">Automatic flights off</span>`;
  }
  const adm=DK_ADMIN&&!found?`<button class="hud-btn" data-sn="${esc(x.sn)}" data-on="${x.auto_flights?1:0}" onclick="dockAuto(this.dataset.sn,this.dataset.on==='1')" title="Lets this dock's drone take off by itself">Automatic flights: ${x.auto_flights?'ON':'OFF'}</button>`
    +`<button class="hud-btn" data-sn="${esc(x.sn)}" data-r="${x.range_m||500}" onclick="dockRange(this.dataset.sn,this.dataset.r)">Range ${x.range_m||500} m</button>`:'';
  const test=DK_ADMIN&&!found&&x.simulated?`<select data-sn="${esc(x.sn)}" onchange="dockFault(this)" style="max-width:150px">${faults.map(([v,t],i)=>`<option value="${v}" ${i===0?'selected disabled':''}>${t}</option>`).join('')}</select>`:'';
  const btns=!DK_ADMIN?'':found?`<input id="dkName_${esc(x.sn)}" placeholder="Name, e.g. Roof dock" style="flex:1;min-width:120px"><button class="hud-btn" onclick="dockRegister('${esc(x.sn)}')" ${dkFull&&!x.simulated?'disabled title="The licence\'s dock count is used up"':''}>Register</button>`
    :`<button class="hud-btn" data-sn="${esc(x.sn)}" data-name="${esc(x.name)}" onclick="dockRename(this.dataset.sn,this.dataset.name)">Rename</button><button class="hud-btn danger" data-sn="${esc(x.sn)}" data-name="${esc(x.name)}" onclick="dockRemove(this.dataset.sn,this.dataset.name)">Remove</button>`;
  return `<div class="dk-card${found?' found':''}${sev}" id="dkCard_${esc(x.sn)}"${x.over_limit?' style="opacity:.55" title="Over the licence\'s dock count: not watched. Remove a dock or ask your provider for more."':''}><h4><i class="dot ${dot}"></i>${found?'Found: ':''}${esc(found?(x.model||'Dock'):x.name)}</h4>
    <div class="dk-sub">${esc(found?'':(x.model||'Dock')+' · ')}SN ${esc(x.sn)}${found?'':' · '+esc(x.slot)} · ${x.online?'online':'offline'}</div>
    ${alerts}<div class="dk-tags">${tags.map(t=>'<span>'+t+'</span>').join('')}</div>${fly?`<div class="actions" style="gap:6px;margin-bottom:6px">${fly}</div>`:''}${vid?`<div class="actions" style="gap:6px;margin-bottom:6px">${vid}</div>`:''}${adm?`<div class="actions" style="gap:6px;margin-bottom:6px">${adm}</div>`:''}<div class="actions" style="gap:6px">${btns}${test}</div></div>`}
async function loadDocks(){try{const d=await fetch('/api/docks',{cache:'no-store'}).then(r=>r.json());if(!d.ok)return;
  dkFull=d.limit!=null&&d.used>=d.limit;
  $('dockState').textContent=(!d.allowed?'NOT LICENSED':d.broker.connected?'BROKER READY':d.broker.running?'BROKER STARTING':'BROKER OFF')+(d.allowed&&d.limit!=null?` · ${d.used} OF ${d.limit} DOCK${d.limit===1?'':'S'}`:'');
  $('dockState').style.color=d.allowed&&d.broker.connected?'':'#ffcf7a';
  const cards=d.docks.map(x=>dkCard(x,false)).concat(d.found.map(x=>dkCard(x,true)));
  const ae=document.activeElement,keep=ae&&((ae.id&&ae.id.startsWith('dkName_'))||(ae.tagName==='SELECT'&&ae.closest('#dockList')));
  const hl=d.health_log||[];$('dockHealth').innerHTML=hl.length?'<b style="color:#5bd9ff;font-size:11px;letter-spacing:1px">HEALTH</b>'+hl.map(a=>`<div class="${a.active?'on':''}"><small>${new Date(a.t*1000).toLocaleString()}</small>${a.active?(a.level==='warning'?'⚠ ':'● '):'✓ '}${esc(a.text)}</div>`).join(''):'';
  if(!keep)$('dockList').innerHTML=cards.length?cards.join(''):'<div class="muted">No dock yet.'+(DK_ADMIN?' Open “Set up a dock” below.':' An admin can set one up.')+'</div>';
  if($('dkSimBtn'))$('dkSimBtn').disabled=!d.can_simulate||!d.allowed;
  if($('dkNoAsk'))$('dkNoAsk').checked=!!d.launch_without_asking;
  $('dockLaunches').innerHTML=(d.launches||[]).map(l=>`<div class="dk-launch"><span>🚨 Launch <b>${esc(l.name)}</b> to <b>${esc(l.camera)}</b>?</span><span class="muted">${esc(l.by)} · expires ${new Date(l.expires*1000).toLocaleTimeString()}</span>
    <button class="hud-btn danger" data-id="${esc(l.id)}" onclick="dockLaunch(this.dataset.id,true)">🚁 Launch</button><button class="hud-btn" data-id="${esc(l.id)}" onclick="dockLaunch(this.dataset.id,false)">✋ Don't</button></div>`).join('');
  dockData=d.docks;drawDockFleet();drawDockMap();drawDockVideos();drawDockMissions()}catch(e){}}
let dkRoutes=[],dkRouteSel={},dkMissionLines={};
async function loadDockRoutes(){try{const d=await fetch('/api/routes',{cache:'no-store'}).then(r=>r.json());if(d.ok)dkRoutes=Object.keys(d.routes||{}).sort()}catch(e){}}
async function dockMission(sn,action){const name=action==='fly'?(dkRouteSel[sn]||($('dkRoute_'+sn)||{}).value||''):'';
  if(action==='fly'){const x=dockData.find(d=>d.sn===sn)||{};
    if(!confirm(`${x.name||'The dock'} will take off by itself and fly route “${name}”, then return to the dock.\n\nThe area must be clear and the flight permitted. Continue?`))return}
  dkMsg(action==='fly'?'Checking and sending the flight plan to the dock…':'Calling the drone back…');
  const d=await dkPost('/api/docks/'+encodeURIComponent(sn)+'/mission',{action,route:name});dkMsg(d.ok?d.message:d.error,d.ok);loadDocks()}
async function dockLaunch(id,yes){const d=await dkPost('/api/docks/launches/'+encodeURIComponent(id),{launch:yes});dkMsg(d.ok?d.message:d.error,d.ok);loadDocks()}
async function dockNoAsk(el){if(el.checked&&!confirm('Launch docks without asking?\n\nWhen an alarm needs a drone, a ready dock\'s drone will take off by itself with nobody confirming. Only for sites with permission for automated flights and a safe area.')){el.checked=false;return}
  const d=await dkPost('/api/docks/setup',{launch_without_asking:el.checked});dkMsg(d.ok?(el.checked?'Docks launch without asking.':'Docks ask before launching.'):d.error,d.ok)}
async function dockAuto(sn,on){const x=dockData.find(d=>d.sn===sn)||{};let body={auto_flights:!on};
  if(!on){if(!confirm(`Allow ${x.name||'this dock'}'s drone to take off by itself (routes now; patrols and alarm launches later)?\n\nOnly switch this on when the site has permission for automated flights (Lebanon: DGCA) and the area is safe. Your name and the time are recorded.`))return;body.confirm=true}
  const d=await dkPost('/api/docks/'+encodeURIComponent(sn)+'/settings',body);dkMsg(d.ok?`Automatic flights ${d.auto_flights?'on':'off'}.`:d.error,d.ok);loadDocks()}
async function dockRange(sn,r){const v=prompt('How far from the dock may its drone fly (metres, up to 2000)?',r);if(!v)return;
  const d=await dkPost('/api/docks/'+encodeURIComponent(sn)+'/settings',{range_m:v});dkMsg(d.ok?`Range ${d.range_m} m.`:d.error,d.ok);loadDocks()}
function drawDockMissions(){if(!map||!window.L)return;const seen=new Set();
  dockData.forEach(x=>{const m=x.mission;if(!m||!m.active||!(m.points||[]).length)return;seen.add(x.sn);
    const pts=[[x.lat,x.lon],...m.points.map(p=>[p.lat,p.lon]),[x.lat,x.lon]].filter(p=>p[0]);
    if(!dkMissionLines[x.sn])dkMissionLines[x.sn]=L.polyline(pts,{color:'#ffb23c',weight:2,dashArray:'6 6'}).addTo(map);else dkMissionLines[x.sn].setLatLngs(pts)});
  Object.keys(dkMissionLines).forEach(sn=>{if(!seen.has(sn)){dkMissionLines[sn].remove();delete dkMissionLines[sn]}})}
loadDockRoutes();setInterval(loadDockRoutes,30000);
// One player per streaming dock, kept across polls (the cards above are redrawn every 3 s).
function drawDockVideos(){const box=$('dockVideos');if(!box)return;
  const live=dockData.filter(x=>(x.video||{}).streaming&&!x.over_limit);const want=new Set(live.map(x=>x.sn));
  [...box.children].forEach(el=>{if(!want.has(el.dataset.sn)){const s=el.querySelector('.live-slot');if(s&&window.detachLiveCamera)window.detachLiveCamera(s);el.remove()}});
  live.forEach(x=>{let el=box.querySelector(`[data-sn="${CSS.escape(x.sn)}"]`);
    if(!el){el=document.createElement('div');el.className='dk-video';el.dataset.sn=x.sn;
      el.innerHTML=`<div class="dk-vhead"><i class="dot good"></i><span></span></div><div class="dk-vbody">`
        +(x.simulated?'<div class="dk-sim">SIMULATED DOCK · NO PICTURE<br>A real dock streams here, and Frigate runs the AI on it.</div>'
          :`<div class="live-slot" data-live-camera="${esc(x.slot)}"></div>`)+'</div>';
      box.appendChild(el);const s=el.querySelector('.live-slot');if(s&&window.attachLiveCamera)window.attachLiveCamera(s)}
    const v=x.video,LN={wide:'wide',zoom:'zoom',ir:'thermal',normal:'main'};
    el.querySelector('.dk-vhead span').textContent=`${x.name} · ${v.device==='dock'?'dock camera':(x.drone_model||'drone')+' · '+(LN[v.lens]||v.lens||'')}`})}
async function dockVideo(sn,action,lens,device){dkMsg(action==='start'?'Asking the dock to start the video…':action==='stop'?'Stopping the video…':'Changing lens…');
  const d=await dkPost('/api/docks/'+encodeURIComponent(sn)+'/video',{action,lens,device});
  dkMsg(d.ok?(action==='start'?'Video started. The picture appears below in a few seconds.':action==='stop'?'Video stopped.':'Lens changed.'):d.error,d.ok);loadDocks()}
// Registered docks in the fleet bar and on the map. Docks don't fly from here yet: a click shows the dock.
let dockData=[],dockMarks={};
function dockInfo(x){if(x.over_limit)return 'over licence';if(!x.online)return 'offline';
  if(x.mission&&x.mission.active)return 'flying '+x.mission.name+(x.battery!=null?' · '+x.battery+'%':'');
  const where=x.drone_in_dock===false?'drone out':x.drone_model?'drone in dock':'no drone';
  return where+(x.battery!=null?' · '+x.battery+'%':'')}
function dkAlertName(k){return k.startsWith('hms:')?'DJI warning':({offline:'offline',cover:'cover fault',rain:'heavy rain',wind:'strong wind',hot:'too hot',cold:'too cold',battery:'battery low'})[k]||k}
function drawDockFleet(){const box=$('fleetDocks');if(!box)return;
  box.innerHTML=dockData.map(x=>`<button class="dk-chip" data-sn="${esc(x.sn)}" onclick="focusDock(this.dataset.sn)" title="${esc((x.model||'Dock')+' · SN '+x.sn)}"><i class="${x.online?((x.alerts||[]).length?'half':'ok'):''}"></i>🛬 ${esc(x.name)} <small>${(x.alerts||[]).length?'⚠ '+esc(x.alerts.length===1?dkAlertName(x.alerts[0].key):x.alerts.length+' alerts')+' · ':''}${esc(dockInfo(x))}</small></button>`).join('')}
function drawDockMap(){let fit=false;
  if(!map&&dockData.some(x=>x.lat)){const f=dockData.find(x=>x.lat);initMap(f.lat,f.lon);fit=true}
  if(!map||!window.L)return;const seen=new Set();
  dockData.forEach(x=>{if(!x.lat||!x.lon)return;seen.add(x.sn);let m=dockMarks[x.sn];
    const icon=L.divIcon({className:'',iconSize:[22,22],iconAnchor:[11,11],html:`<div class="dk-mark${x.online?'':' off'}">D</div>`});
    if(!m){m=dockMarks[x.sn]={dock:L.marker([x.lat,x.lon],{icon,zIndexOffset:-100}).addTo(map).on('click',()=>focusDock(x.sn,true)),drone:null}}
    m.dock.setLatLng([x.lat,x.lon]).setIcon(icon);const tip=`${esc(x.name)} · ${esc(dockInfo(x))}`;
    if(m.dock.getTooltip())m.dock.setTooltipContent(tip);else m.dock.bindTooltip(tip,{direction:'right'});
    const out=x.drone_in_dock===false&&x.drone_lat&&x.drone_lon;
    if(out){if(!m.drone)m.drone=L.circleMarker([x.drone_lat,x.drone_lon],{radius:7,color:'#ffb23c',fillColor:'#ffb23c',fillOpacity:.8}).addTo(map);
      const dt=`${esc(x.drone_model||'Drone')} (${esc(x.name)})${x.drone_height!=null?' · '+fmt(x.drone_height)+' m':''}`;
      m.drone.setLatLng([x.drone_lat,x.drone_lon]);if(m.drone.getTooltip())m.drone.setTooltipContent(dt);else m.drone.bindTooltip(dt,{permanent:true,direction:'right'})}
    else if(m.drone){m.drone.remove();m.drone=null}});
  const pts=dockData.flatMap(x=>[x.lat?[x.lat,x.lon]:null,x.drone_in_dock===false&&x.drone_lat?[x.drone_lat,x.drone_lon]:null]).filter(Boolean);
  if(fit&&pts.length>1)map.fitBounds(pts,{padding:[40,40],maxZoom:18});
  Object.keys(dockMarks).forEach(sn=>{if(!seen.has(sn)){dockMarks[sn].dock.remove();dockMarks[sn].drone&&dockMarks[sn].drone.remove();delete dockMarks[sn]}})}
function focusDock(sn,fromMap){const x=dockData.find(d=>d.sn===sn);if(!x)return;
  if(map&&x.lat&&!fromMap){map.setView([x.lat,x.lon],Math.max(map.getZoom(),17));dockMarks[sn]&&dockMarks[sn].dock.openTooltip()}
  const c=$('dkCard_'+sn);if(c){if(fromMap)c.scrollIntoView({behavior:'smooth',block:'center'});c.classList.add('flash');setTimeout(()=>c.classList.remove('flash'),1600)}
  if(!x.lat)dkMsg(`${x.name} hasn't sent its position yet.`)}
async function loadDockSetup(){if(!DK_ADMIN)return;$('dockSetup').style.display='';
  const d=await fetch('/api/docks/setup',{cache:'no-store'}).then(r=>r.json()).catch(()=>({}));if(!d.ok)return;
  $('dkAppId').value=d.app_id||'';$('dkKeysState').textContent=d.cloud_ready?'✓ Keys saved':'Keys missing'+(d.app_key_set?'':' · App Key')+(d.app_license_set?'':' · App License');
  $('dkQr').innerHTML=d.qr||'';$('dkLink').textContent=d.pilot_link;$('dkBroker').textContent=d.broker;
  if(d.pilot_page&&d.pilot_page!=='ok')dkMsg('Pilot 2 setup page: '+d.pilot_page,false)}
async function dockSaveKeys(){const b={app_id:$('dkAppId').value.trim()};if($('dkAppKey').value.trim())b.app_key=$('dkAppKey').value.trim();
  if($('dkAppLic').value.trim())b.app_license=$('dkAppLic').value.trim();const d=await dkPost('/api/docks/setup',b);
  dkMsg(d.ok?'Cloud API keys saved.':d.error,d.ok);if(d.ok){$('dkAppKey').value='';$('dkAppLic').value='';loadDockSetup()}}
async function dockNewLink(){if(!confirm('Make a new Pilot 2 link? The old link stops working.'))return;await dkPost('/api/docks/setup',{new_link:true});loadDockSetup()}
async function dockRegister(sn){const n=$('dkName_'+sn);const d=await dkPost('/api/docks/register',{sn,name:n?n.value:''});
  if(n)n.blur();dkMsg(d.ok?`Registered as ${d.dock.name}.`:d.error,d.ok);loadDocks()}
async function dockRename(sn,old){const name=prompt('New name for this dock:',old);if(!name)return;const d=await dkPost('/api/docks/'+encodeURIComponent(sn),{name});dkMsg(d.ok?'Renamed.':d.error,d.ok);loadDocks()}
async function dockRemove(sn,name){if(!confirm(`Remove ${name}? It stops being part of this system${sn.startsWith('SIMDOCK')?' and the simulated dock is deleted':''}. A real dock can be registered again when it connects.`))return;
  const d=await dkPost('/api/docks/'+encodeURIComponent(sn),{},'DELETE');dkMsg(d.ok?'Removed.':d.error,d.ok);loadDocks()}
async function dockFault(sel){const d=await dkPost('/api/docks/'+encodeURIComponent(sel.dataset.sn)+'/fault',{fault:sel.value});sel.blur();
  dkMsg(d.ok?(d.fault?'Test problem set. The alert shows here and on Telegram within a few seconds'+(d.fault==='offline'?' (offline: after 1 minute).':'.'):'All clear set.'):d.error,d.ok);setTimeout(loadDocks,800)}
async function dockSimulate(){const c=map&&map.getCenter?map.getCenter():null;const d=await dkPost('/api/docks/simulate',c?{lat:c.lat,lon:c.lng}:{});
  dkMsg(d.ok?`Simulated dock ${d.sn} added: it shows under Found in a moment. Register it to try the steps.`:d.error,d.ok);setTimeout(loadDocks,1500)}
loadDocks();setInterval(loadDocks,3000);loadDockSetup();
$('speedVal').textContent='30%';loadFleet();setInterval(loadFleet,3000);loadPair();poll();loadResp();loadRoutes().then(loadScheds);setInterval(poll,500);
</script>"""
