"""The Detector drones tab: drone detectors pinned on the map, each with how far it detects, the drones each one sees
(camera AI with YOLO, by position, Remote ID, acoustic and passive RF sensors), and the detections log."""
BODY = r"""
<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">
<style>
.dt-grid{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(340px,1fr);gap:16px;align-items:start}
#dtMap{height:calc(100vh - 220px);min-height:460px;border:1px solid #155879;border-radius:5px;background:#020a10}
#dtMap.adding{cursor:crosshair}
.dt-det{border:1px solid #153c56;border-radius:4px;background:#05131d;padding:9px 10px;margin-bottom:8px}
.dt-det.alarm{border-color:#a3303f;box-shadow:0 0 0 1px #a3303f inset}
.dt-det.off{opacity:.6}
.dt-ic{border:1px solid #a3303f;border-radius:4px;background:#05131d;padding:9px 10px;margin-bottom:6px}
.dt-det h4,.dt-ic h4{margin:0;display:flex;align-items:center;gap:8px;font:bold 13px Arial;color:#e9f8ff}
.dt-det h4 span,.dt-ic h4 span{flex:1;cursor:pointer}
.dt-det h4 button,.dt-ic h4 button{background:none;border:1px solid #155879;color:#9edfff;border-radius:3px;padding:2px 7px;cursor:pointer;font:11px Arial}
.dt-row{display:flex;gap:8px;align-items:center;margin-top:7px;flex-wrap:wrap;font-size:12px;color:#9edfff}
.dt-row input[type=range]{flex:1;min-width:120px}
.dt-row b{color:#fff;min-width:64px;text-align:right;font-variant-numeric:tabular-nums}
.dt-row select{flex:1;min-width:120px}
.dt-seen{margin-top:6px;font-size:12px}
.dt-seen div{padding:3px 0;border-top:1px solid #0f2a3b;color:#ffb3bb}
.dt-seen div.friend{color:#7dffc1}
.dt-ev{display:flex;gap:8px;padding:6px 0;border-bottom:1px solid #0f2a3b;font-size:12px;color:#cfeeff}
.dt-ev small{color:#6d8b9d;white-space:nowrap}
.dt-ev a{white-space:nowrap}
.dt-pin{width:26px;height:26px;border-radius:50%;background:#031a0e;border:2px solid #29ff7a;color:#29ff7a;font:bold 13px/22px Arial;text-align:center;box-shadow:0 0 10px rgba(41,255,122,.55)}
.dt-pin.acoustic{border-color:#ffb547;color:#ffb547;box-shadow:0 0 10px rgba(255,181,71,.5)}
.dt-pin.rf{border-color:#c18bff;color:#c18bff;box-shadow:0 0 10px rgba(193,139,255,.5)}
.dt-pin.alarm{border-color:#ff5d6c;color:#ff5d6c;box-shadow:0 0 14px #ff5d6c;animation:dtBlink 1s infinite}
@keyframes dtBlink{50%{box-shadow:0 0 2px #ff5d6c}}
.dt-drone{width:18px;height:18px;border-radius:50%;border:2px solid #fff;font:bold 10px/14px Arial;text-align:center;color:#fff}
.dt-drone.intruder{background:#e0283e}.dt-drone.friend{background:#1f9c63}
.dt-drone.estimated{background:#e0283e;border-style:dashed;animation:dtBlink 1s infinite}
.dt-hear{margin-top:6px;font-size:12px;color:#ffd08a}
.dt-label{background:rgba(3,16,26,.9);border:1px solid #155879;color:#e9f8ff;font:bold 11px Arial;padding:2px 6px;border-radius:3px;white-space:nowrap}
.dt-dist{background:rgba(3,16,26,.88);border:1px solid #2d6a8a;color:#cfeeff;font:bold 11px Arial;padding:1px 5px;border-radius:3px;box-shadow:none}
.dt-dist.bad{border-color:#a3303f;color:#ffb3bb}.dt-dist.ours{border-color:#1d7fae;color:#7fdcff}
.dt-dist::before{display:none}
.dt-pilot{width:18px;height:18px;border-radius:50%;background:#7a3cff;border:2px solid #fff;color:#fff;font:bold 10px/14px Arial;text-align:center}
.dt-rid{font:11px monospace;color:#cfeeff;background:#020a10;border:1px solid #155879;border-radius:3px;padding:6px 8px;word-break:break-all;margin-top:6px}
@media(max-width:1000px){.dt-grid{grid-template-columns:1fr}#dtMap{height:60vh}}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Drones</div><h1 class="page-title">Detector drones</h1>
<div class="page-sub">Pin drone detectors on the map and set how far each one detects. Your drones are known; any other drone that comes into a detector's range raises the alarm on every screen, with a siren, a spoken warning on this PC and Telegram. A detector with a camera also checks its picture with YOLO. A detector can also be an acoustic sensor (hears drone motors) or a passive RF sensor (hears drone radio links): where two sensors' directions cross, the drone is located on the map.</div></div>
<div class="actions"><span class="state" id="dtState"><i class="dot warn"></i>LOADING</span></div></div>
<div class="dt-grid">
<section class="panel"><div class="panel-body"><div id="dtMap"></div>
<div class="muted" style="margin-top:8px;font-size:12px">Radar circles: each detector's range, sweeping green, red while it sees an unknown drone (⌖ detector · 🎙 acoustic sensor · 📶 RF sensor). Orange / purple lines: the direction a sensor hears a drone from; a blinking dashed dot: a drone located where directions cross. Red dot: unknown drone · green dot: one of your drones. Drag a detector to move it; drag a drone to send it there (a virtual drone can also be put there at once).</div></div></section>
<div>
<section class="panel"><div class="panel-head"><div class="panel-title">⌖ Detectors</div><div class="live" id="dtCount"></div></div><div class="panel-body">
<div class="actions" style="margin-bottom:10px"><button class="hud-btn primary" id="dtAdd" onclick="startAdd()">＋ Add detector</button><span class="muted" id="dtHint" style="display:none">Click the map where the detector is (Esc cancels).</span></div>
<div id="dtList"></div><div id="dtMsg" class="hud-msg"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">✈ My drones</div><div class="live" id="mineCount"></div></div><div class="panel-body">
<div class="muted" style="font-size:12px;margin-bottom:6px">Your drones never raise the alarm. A drone added later (real or virtual) is unknown until you mark it as yours; a removed drone leaves this list.</div>
<div id="mineList"></div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">🛫 Send drones to an unknown drone</div><div class="live" id="icState">–</div></div><div class="panel-body">
<div class="muted" style="font-size:12px">When a detector sees an unknown drone, your drones fly to it, hold a set distance from it at a set height with their cameras on it, and follow it while it moves. They come home when it hasn't been seen for a minute, after 15 minutes, or when you press Recall. Flights use the usual checks (no-fly zones, weather, battery).</div>
<div class="hud-row"><div><b>Send automatically</b><div class="muted">Off: use "Send drones now" when the alarm goes off.</div></div><input class="toggle" type="checkbox" id="icAuto" onchange="saveSettings()"></div>
<div style="font-size:12px;color:#9edfff;margin-top:6px">Drones to send <span class="muted">(none ticked: the nearest ready drone)</span></div>
<div id="icDrones" class="dt-row" style="gap:12px"></div>
<div class="dt-row"><span>Height</span><input id="icAlt" type="number" min="20" max="120" step="5" style="width:70px" onchange="saveSettings()"><span>m</span><span style="margin-left:10px">Hold</span><input id="icStand" type="number" min="10" max="300" step="5" style="width:70px" onchange="saveSettings()"><span>m from it</span></div>
<div id="icActive" style="margin-top:8px"></div>
<div class="actions" style="margin-top:8px"><button class="hud-btn primary" onclick="sendNow()">Send drones now</button><button class="hud-btn danger" onclick="recall('all')">Recall all</button></div>
<div id="icMsg" class="hud-msg"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">🛸 Detections</div><div class="live" id="dtEvCount"></div></div><div class="panel-body">
<div id="dtEvents" style="max-height:300px;overflow:auto"></div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">🎙 Acoustic and RF sensors</div><div class="live" id="snState">–</div></div><div class="panel-body">
<div class="muted" style="font-size:12px">Make a detector an <b>acoustic sensor</b> (microphones that hear drone motors, also drones with no radio) or an <b>RF sensor</b> (a receiver that hears drone control and video links, often before the drone is seen). They only listen: nothing is transmitted or jammed. Each sensor sends what it hears to this PC, the same way as Remote ID receivers (same UDP port, or HTTP with the token below), naming its detector:</div>
<div class="dt-rid">{"sensor":"North mast","detected":true,"confidence":0.82,"bearing":210,"type":"quadcopter","protocol":"OcuSync","freq_mhz":2440,"rssi_dbm":-61}</div>
<div class="muted" style="font-size:12px;margin-top:6px">Only <code>sensor</code> is needed. With <code>bearing</code> (degrees from north) the map shows the direction; two sensors' directions crossing locate the drone; <code>distance_m</code> locates it from one sensor.</div>
<div id="snSources" class="muted" style="font-size:12px;margin-top:6px"></div>
<div class="dt-row"><span>Alarm from confidence</span><input id="snConf" type="number" min="0.1" max="0.99" step="0.05" style="width:80px" onchange="saveSettings()"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">📡 Remote ID receivers</div><div class="live" id="ridState">–</div></div><div class="panel-body">
<div class="muted" style="font-size:12px">Most drones over 250 g broadcast their ID, position, height and their pilot's position (Remote ID). A Remote ID receiver on this site's network (for example an ESP32 OpenDroneID receiver) sends what it hears to this PC; those drones then count like any other: yours, or an intruder that sounds the alarm, with where the pilot is.</div>
<div id="ridSources" class="muted" style="font-size:12px;margin-top:6px"></div>
<div class="hud-row"><div><b>Listen for receivers on UDP</b><div class="muted">JSON messages from receivers on the site network.</div></div><input class="toggle" type="checkbox" id="ridUdp" onchange="saveSettings()"></div>
<div class="dt-row"><span>UDP port</span><input id="ridPort" type="number" min="1024" max="65535" style="width:110px" onchange="saveSettings()"><span class="muted" id="ridUdpState"></span></div>
<details style="margin-top:8px"><summary style="cursor:pointer;color:#5bd9ff;font:bold 12px Arial">Receiver and sensor address and token (admins)</summary>
<div class="muted" style="font-size:12px;margin-top:6px">Receivers can also send by HTTP: POST the JSON to the address below with the header <code>X-RemoteID-Token</code>. Example message: <code>{"id":"1581F5FJ…","lat":33.89,"lon":35.50,"alt":60,"operator_lat":33.88,"operator_lon":35.49}</code> (OpenDroneID-style messages work too).</div>
<div class="actions" style="margin-top:6px"><button class="hud-btn" onclick="showRid()">Show address and token</button><button class="hud-btn danger" onclick="newRidToken()">New token</button></div>
<div id="ridConf"></div></details>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">⚙ Detection</div></div><div class="panel-body">
<div class="hud-row"><div><b>Telegram alerts</b><div class="muted">Each detection also goes to Telegram (camera detections with the picture).</div></div><input class="toggle" type="checkbox" id="setTg" onchange="saveSettings()"></div>
<div class="hud-row"><div><b>Camera AI (YOLO) model</b><div class="muted" id="modelState">–</div></div></div>
<div class="muted" style="font-size:12px">Admins: upload a YOLO model trained on drones, exported as ONNX (YOLOv5, YOLOv8 or YOLO11, 640×640). Then pick a camera on a detector. Check the model's licence allows your use.</div>
<div class="actions" style="margin-top:8px"><input type="file" id="modelFile" accept=".onnx" style="flex:1;min-width:160px"><button class="hud-btn" onclick="uploadModel()">Upload model</button><button class="hud-btn danger" onclick="removeModel()">Remove</button></div>
<div class="dt-row"><span>Class names</span><input id="setClasses" placeholder="drone" style="flex:1" onchange="saveSettings()"><span>Min. score</span><input id="setScore" type="number" min="0.1" max="0.95" step="0.05" style="width:70px" onchange="saveSettings()"></div>
<div id="setMsg" class="hud-msg"></div>
</div></section>
</div></div>
</main>
<script src="/vendor/leaflet/leaflet.js"></script><script src="/mapsearch.js"></script>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const fmtM=m=>m>=1000?(m/1000).toFixed(m%1000?1:0)+' km':m+' m';
let data={detectors:[],seen:{},drones:[],events:[],cameras:[]},dets=[],adding=false,saveT=null,fitted=false,editing=0,dragDrone=null,dragMoved=false;
const map=L.map('dtMap',{maxZoom:20}).setView([33.9,35.5],15);
L.tileLayer('/tiles/sat/{z}/{x}/{y}',{maxZoom:20,maxNativeZoom:19}).addTo(map);
const radarLayer=L.layerGroup().addTo(map),detLayer=L.layerGroup().addTo(map),droneLayer=L.layerGroup().addTo(map),hearLayer=L.layerGroup().addTo(map);
// Radar look: green range rings and cross-lines, and a sweep turning once every 4 s (red while the detector sees an intruder).
const RADAR_GREEN='#29ff7a',RADAR_RED='#ff3b4e',SWEEP_MS=4000,SWEEP_DEG=40,SWEEP_STEPS=8;
let radars=[];  // [{d, al, wedges: [polygon...], line}]
// Our drones sent to an unknown drone: a line from each to it, with how far it still has to go.
const chaseLayer=L.layerGroup().addTo(map);
function drawChase(){chaseLayer.clearLayers();
  let n=0;(data.intercept||[]).forEach(t=>t.drones.forEach(o=>{if(o.lat==null)return;
    L.polyline([[o.lat,o.lon],[t.lat,t.lon]],{color:'#25c7ff',weight:2.5,opacity:.9,dashArray:'10 6'}).addTo(chaseLayer);
    // The label sits beside our drone (two drones' lines run side by side, so mid-line labels would overlap).
    const left=n++%2===0;
    L.circleMarker([o.lat,o.lon],{radius:5,color:'#25c7ff',fillColor:'#25c7ff',fillOpacity:1,weight:1}).addTo(chaseLayer)
      .bindTooltip(`${esc(o.label)} · ${fmtM(o.distance_m)}`,{permanent:true,direction:left?'left':'right',offset:[left?-8:8,0],className:'dt-dist ours'})}))}
function geoAt(lat,lon,deg,m){const b=deg*Math.PI/180;return [lat+m*Math.cos(b)/111320,lon+m*Math.sin(b)/(111320*Math.cos(lat*Math.PI/180))]}
function wedge(d,a0,a1){const pts=[[d.lat,d.lon]];for(let a=a0;a<=a1+0.01;a+=Math.max(1,(a1-a0)/6))pts.push(geoAt(d.lat,d.lon,a,d.range_m));return pts}
function drawRadar(d,al){const col=al?RADAR_RED:RADAR_GREEN,on=d.enabled;
  L.circle([d.lat,d.lon],{radius:d.range_m,color:col,weight:2,opacity:on?.95:.4,fillColor:col,fillOpacity:on?.06:.02,dashArray:on?null:'6 6',interactive:false}).addTo(radarLayer);
  if(!on)return;
  [1/3,2/3].forEach(f=>L.circle([d.lat,d.lon],{radius:d.range_m*f,color:col,weight:1,opacity:.45,fill:false,interactive:false}).addTo(radarLayer));
  [0,90].forEach(a=>L.polyline([geoAt(d.lat,d.lon,a,d.range_m),geoAt(d.lat,d.lon,a+180,d.range_m)],{color:col,weight:1,opacity:.3,interactive:false}).addTo(radarLayer));
  const r={d,al,wedges:[],line:L.polyline([[d.lat,d.lon],[d.lat,d.lon]],{color:col,weight:2,opacity:.9,interactive:false}).addTo(radarLayer)};
  for(let i=0;i<SWEEP_STEPS;i++)r.wedges.push(L.polygon([[d.lat,d.lon]],{stroke:false,fillColor:col,fillOpacity:.32*(1-i/SWEEP_STEPS),interactive:false}).addTo(radarLayer));
  radars.push(r)}
let sweepT=0;
function sweep(t){requestAnimationFrame(sweep);if(t-sweepT<50||document.hidden)return;sweepT=t;  // about 20 frames a second
  const a=(t%SWEEP_MS)/SWEEP_MS*360,step=SWEEP_DEG/SWEEP_STEPS;
  radars.forEach(r=>{r.line.setLatLngs([[r.d.lat,r.d.lon],geoAt(r.d.lat,r.d.lon,a,r.d.range_m)]);
    r.wedges.forEach((w,i)=>w.setLatLngs(wedge(r.d,a-(i+1)*step,a-i*step)))})}
requestAnimationFrame(sweep);
const SENSOR_ICON={'':'⌖',acoustic:'🎙',rf:'📶'},SENSOR_NAME={'':'Detector (camera / position)',acoustic:'Acoustic sensor',rf:'RF sensor (passive)'};
function hits(){return (data.sensors&&data.sensors.hits)||[]}
function hitOf(id){return hits().find(h=>h.detector===id)}

function msg(id,t,ok){const e=$(id);e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t||''}
function alarmOf(id){const h=hitOf(id);return (data.seen[id]||[]).some(x=>x.intruder)||!!(h&&h.confidence>=((data.settings||{}).sensor_min_conf||0.6))}
function drawHearing(){hearLayer.clearLayers();
  hits().forEach(h=>{const d=dets.find(x=>x.id===h.detector);if(!d||!d.enabled||h.bearing==null)return;
    const len=h.distance_m||d.range_m,b=h.bearing*Math.PI/180,lat=d.lat+len*Math.cos(b)/111320,lon=d.lon+len*Math.sin(b)/(111320*Math.cos(d.lat*Math.PI/180));
    const col=d.sensor==='rf'?'#c18bff':'#ffb547';
    L.polyline([[d.lat,d.lon],[lat,lon]],{color:col,weight:3,opacity:.9}).bindTooltip(`${esc(d.name)} hears a drone from ${Math.round(h.bearing)}° (${Math.round(h.confidence*100)}%)`).addTo(hearLayer);
    L.polygon([[d.lat,d.lon],...[-6,6].map(w=>{const bb=(h.bearing+w)*Math.PI/180;return [d.lat+len*Math.cos(bb)/111320,d.lon+len*Math.sin(bb)/(111320*Math.cos(d.lat*Math.PI/180))]})],{color:col,weight:0,fillOpacity:.12}).addTo(hearLayer)})}
function drawMap(keepDets){if(!keepDets){detLayer.clearLayers();radarLayer.clearLayers();radars=[];
  dets.forEach(d=>{const al=alarmOf(d.id);
    drawRadar(d,al);
    L.marker([d.lat,d.lon],{draggable:true,icon:L.divIcon({className:'',iconSize:[26,26],iconAnchor:[13,13],html:`<div class="dt-pin ${d.sensor||''}${al?' alarm':''}">${SENSOR_ICON[d.sensor||'']}</div>`})})
      .bindTooltip(esc(d.name)+' · '+fmtM(d.range_m),{permanent:true,direction:'top',offset:[0,-14],className:'dt-label'})
      .on('dragstart',()=>{editing=Date.now()+600000})
      .on('dragend',e=>{const ll=e.target.getLatLng(),o=dets.find(x=>x.id===d.id)||d;o.lat=+ll.lat.toFixed(6);o.lon=+ll.lng.toFixed(6);save('Moved.')}).addTo(detLayer)})}
  drawHearing();
  if(dragDrone)return;  // don't redraw the drones while one is being dragged
  drawChase();
  droneLayer.clearLayers();
  (data.drones||[]).forEach(x=>{const lines=dets.filter(d=>(data.seen[d.id]||[]).some(s=>s.slot===x.slot));
    lines.forEach(d=>{const ln=L.polyline([[d.lat,d.lon],[x.lat,x.lon]],{color:x.intruder?'#ff5d6c':'#26ee89',weight:1.5,dashArray:'4 4'}).addTo(droneLayer);
      // How far the drone is from the detector, on the line.
      const s=(data.seen[d.id]||[]).find(y=>y.slot===x.slot);if(s)ln.bindTooltip(fmtM(s.distance_m),{permanent:true,direction:'center',className:'dt-dist'+(x.intruder?' bad':'')})});
    if(x.operator){L.polyline([[x.lat,x.lon],[x.operator.lat,x.operator.lon]],{color:'#a98bff',weight:1.5,dashArray:'2 6'}).addTo(droneLayer);
      L.marker([x.operator.lat,x.operator.lon],{icon:L.divIcon({className:'',iconSize:[18,18],iconAnchor:[9,9],html:'<div class="dt-pilot">👤</div>'})})
        .bindTooltip('Pilot of '+esc(x.label)).addTo(droneLayer)}
    if(x.estimated){L.circle([x.lat,x.lon],{radius:60,color:'#ff5d6c',weight:1,dashArray:'4 4',fillOpacity:.08}).addTo(droneLayer);
      L.marker([x.lat,x.lon],{icon:L.divIcon({className:'',iconSize:[18,18],iconAnchor:[9,9],html:'<div class="dt-drone estimated">?</div>'})})
        .bindTooltip(`${esc(x.label)} · estimated from ${esc((x.sensors||[]).join(' and '))} (${Math.round((x.confidence||0)*100)}%)`).addTo(droneLayer);return}
    L.marker([x.lat,x.lon],{draggable:!x.remote_id||x.slot.indexOf('rid:')!==0,icon:L.divIcon({className:'',iconSize:[18,18],iconAnchor:[9,9],html:`<div class="dt-drone ${x.intruder?'intruder':'friend'}">✈</div>`})})
      .bindTooltip(`${esc(x.label)}${x.virtual?' (virtual)':''} · ${x.alt} m ${x.intruder?'· UNKNOWN DRONE':'· yours'}${String(x.slot).startsWith('rid:')?' · heard by Remote ID'+(x.operator?' (pilot shown)':''):' · drag to send it somewhere'}`)
      .on('mousedown touchstart',()=>{dragDrone=x.slot})  // hold the redraw from the press, before the drag starts
      .on('dragstart',()=>{dragDrone=x.slot;dragMoved=true}).on('dragend',e=>{dragMoved=false;dropDrone(x,e.target.getLatLng())})
      .on('mouseup click',()=>setTimeout(()=>{if(!dragMoved&&dragDrone===x.slot)dragDrone=null},50)).addTo(droneLayer)})}
// Drag a drone and drop it: a virtual drone can fly there or be put there at once (testing); a real one flies there.
async function dropDrone(x,ll){const lat=+ll.lat.toFixed(6),lon=+ll.lng.toFixed(6),far=Math.round(map.distance([x.lat,x.lon],ll));
  try{
    let how;
    if(x.virtual)how=await uiChoose(`Send ${x.label} (virtual) ${far} m to ${lat.toFixed(5)}, ${lon.toFixed(5)}?`,['Fly there','Move there now'],{title:'Virtual drone'});
    else how=await uiConfirm(`REAL FLIGHT: ${x.label} takes off if it is on the ground and flies ${far} m to ${lat.toFixed(5)}, ${lon.toFixed(5)} at 30 m, then hovers there.\n\nThe usual checks apply (range from home, no-fly zones, weather, battery). Keep it in sight.`,{title:'Fly the drone there',ok:'Fly there',danger:true})?0:null;
    if(how===null)return;
    let r,d;
    if(how===1){r=await fetch('/api/virtual-drones/'+encodeURIComponent(x.slot),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action:'move',lat,lon})});d=await r.json().catch(()=>({}))
      ;msg('dtMsg',r.ok&&d.ok!==false?x.label+' moved.':(r.status===403?'Only operators and admins can move drones.':d.error||'Not moved.'),r.ok&&d.ok!==false)}
    else{({r,d}=await uiFly('/api/routes/fly?drone='+encodeURIComponent(x.slot),{name:'Sent from Detector drones',points:[{lat,lon}],alt:30,speed:6,pause:0,end:'hover'}));
      msg('dtMsg',d.ok?x.label+' is flying there.':(r.status===403?'Only operators and admins can fly drones.':d.error||'Not sent.'),!!d.ok)}
  }finally{dragDrone=null;await load()}}
function renderList(){
  $('dtCount').textContent=dets.length+' DETECTOR'+(dets.length===1?'':'S');
  const cams=data.cameras||[];
  $('dtList').innerHTML=dets.length?dets.map((d,i)=>{const seen=data.seen[d.id]||[],al=seen.some(x=>x.intruder),cc=(data.camera_checks||{})[d.id];
    return `<div class="dt-det${al?' alarm':''}${d.enabled?'':' off'}" data-i="${i}" data-id="${esc(d.id||'')}">
      <h4><span data-act="go">${al?'🚨 ':''}${SENSOR_ICON[d.sensor||'']} ${esc(d.name)}</span><input type="checkbox" class="toggle" data-act="on" ${d.enabled?'checked':''} title="On / off"><button data-act="ren">✎</button><button data-act="del">✕</button></h4>
      <div class="dt-row"><span>Range</span><input type="range" min="20" max="10000" step="10" value="${d.range_m}" data-act="range" title="How far this detector sees drones: about 50–150 m for a normal camera, up to ~1 km for a zoom camera"><b>${fmtM(d.range_m)}</b></div>
      <div class="dt-row"><span>Type</span><select data-act="kind">${Object.keys(SENSOR_NAME).map(k=>`<option value="${k}" ${k===(d.sensor||'')?'selected':''}>${SENSOR_NAME[k]}</option>`).join('')}</select></div>
      ${(()=>{const h=hitOf(d.id);if(d.sensor&&h)return `<div class="dt-hear">${d.sensor==='rf'?'📶':'🎙'} Hearing a drone now · ${Math.round(h.confidence*100)}%${h.bearing!=null?' · from '+Math.round(h.bearing)+'°':''}${h.distance_m?' · ~'+fmtM(h.distance_m):''}${h.drone_type?' · '+esc(h.drone_type):''}${h.protocol?' · '+esc(h.protocol):''}${h.freq_mhz?' · '+(h.freq_mhz>=1000?(h.freq_mhz/1000).toFixed(2)+' GHz':h.freq_mhz+' MHz'):''}${h.rssi_dbm!=null?' · '+h.rssi_dbm+' dBm':''}</div>`;
        return d.sensor?'<div class="muted" style="font-size:11px;margin-top:4px">'+(SENSOR_NAME[d.sensor])+': nothing heard now. The sensor reports with "sensor": "'+esc(d.name)+'".</div>':''})()}
      <div class="dt-row"><span>Camera</span><select data-act="cam"><option value="">None (position only)</option>${cams.map(c=>`<option ${c===d.camera?'selected':''}>${esc(c)}</option>`).join('')}</select></div>
      ${d.camera&&cc?`<div class="muted" style="font-size:11px;margin-top:4px">YOLO checked ${new Date(cc.at*1000).toLocaleTimeString()}: ${cc.count?cc.count+' drone(s), '+Math.round(cc.best*100)+'%':'no drone'}</div>`:''}
      <div class="dt-seen">${seen.length?seen.map(x=>`<div class="${x.intruder?'':'friend'}">${x.estimated?'🛸 '+esc(x.label)+' · '+x.distance_m+' m · '+x.bearing+'° · height unknown':(x.intruder?'🛸 Unknown drone':'✈ Yours')+': '+esc(x.label)+(x.virtual?' (virtual)':'')+' · '+x.distance_m+' m · '+x.bearing+'° · '+x.alt+' m high'+(x.operator?' · pilot shown on the map':'')}</div>`).join(''):'<span class="muted">No drone in range.</span>'}</div></div>`}).join('')
    :'<div class="muted">No detectors yet. Press <b>＋ Add detector</b> and click the map.</div>';
  // Each control finds its detector when used (the list is refreshed every 2 s, so never keep an old copy).
  document.querySelectorAll('.dt-det').forEach(el=>{const id=el.dataset.id,i0=+el.dataset.i,cur=()=>dets.find(x=>id&&x.id===id)||dets[i0];
    const d=new Proxy({},{get:(_,k)=>cur()?.[k],set:(_,k,v)=>{const o=cur();if(o)o[k]=v;return true}});
    el.querySelector('[data-act=go]').onclick=()=>map.setView([d.lat,d.lon],Math.max(map.getZoom(),15));
    el.querySelector('[data-act=on]').onchange=e=>{d.enabled=e.target.checked;save(d.enabled?'Detector on.':'Detector off.')};
    el.querySelector('[data-act=ren]').onclick=async()=>{const n=await uiPrompt('New name for this detector:',d.name);if(n&&n.trim()){d.name=n.trim();save('Renamed.')}};
    el.querySelector('[data-act=del]').onclick=async()=>{if(await uiConfirm('Delete detector “'+d.name+'”?')){const o=cur();dets=dets.filter(x=>x!==o);save('Deleted.')}};
    const r=el.querySelector('[data-act=range]');r.oninput=()=>{editing=Date.now();d.range_m=+r.value;r.nextElementSibling.textContent=fmtM(d.range_m);drawMap()};r.onchange=()=>{editing=Date.now();d.range_m=+r.value;save('Range: '+fmtM(d.range_m)+'.')};
    el.querySelector('[data-act=kind]').onchange=e=>{d.sensor=e.target.value;save(SENSOR_NAME[d.sensor]+'.')};
    el.querySelector('[data-act=cam]').onchange=e=>{d.camera=e.target.value;save(d.camera?'Camera '+d.camera+' checked by YOLO.':'Camera removed.')}})}
function renderEvents(){const ev=data.events||[];$('dtEvCount').textContent=ev.length?ev.length+' RECENT':'NONE';
  $('dtEvents').innerHTML=ev.length?ev.map(e=>`<div class="dt-ev"><small>${new Date(e.at*1000).toLocaleTimeString()}</small><span style="flex:1">${e.kind==='camera'?'📷':e.kind==='remote_id'?'🛰':e.kind==='acoustic'?'🎙':e.kind==='rf'?'📶':e.kind==='intercept'?'🛫':'📡'} ${esc(e.text)}</span>${e.photo?`<a href="/api/detector/photo/${e.id}" target="_blank" rel="noopener">Picture</a>`:''}</div>`).join(''):'<div class="muted">No detections yet.</div>'}
function save(okText){editing=Date.now();clearTimeout(saveT);saveT=setTimeout(async()=>{
  const d=await fetch('/api/detector/sites',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({detectors:dets})}).then(r=>r.json()).catch(()=>({ok:false,error:'No answer from the PC.'}));
  if(d.ok){dets=d.detectors;msg('dtMsg',okText,true)}else msg('dtMsg',d.error||'Not saved.',false);editing=0;await load()},250)}
function startAdd(){adding=!adding;$('dtMap').classList.toggle('adding',adding);$('dtHint').style.display=adding?'':'none';$('dtAdd').textContent=adding?'Cancel':'＋ Add detector'}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&adding)startAdd()});
map.on('click',async e=>{if(!adding)return;startAdd();
  const name=await uiPrompt('Name for this detector:','Detector '+(dets.length+1));if(!name||!name.trim())return;
  const r=await uiPrompt('How far does it detect drones (metres, 20–10000)?','500');if(r===null)return;
  dets.push({name:name.trim(),lat:+e.latlng.lat.toFixed(6),lon:+e.latlng.lng.toFixed(6),range_m:Math.max(20,Math.min(10000,parseInt(r)||500)),camera:'',enabled:true});
  save('Detector added.')});
async function saveSettings(){const d=await fetch('/api/detector/settings',{method:'POST',headers:{'content-type':'application/json'},
  body:JSON.stringify({remoteid_udp:$('ridUdp').checked,remoteid_port:+$('ridPort').value||47911,telegram:$('setTg').checked,classes:$('setClasses').value||'drone',min_score:+$('setScore').value||0.45,sensor_min_conf:+$('snConf').value||0.6,intercept_auto:$('icAuto').checked,
  intercept_drones:[...document.querySelectorAll('#icDrones input:checked')].map(x=>x.value),intercept_alt_m:+$('icAlt').value||50,intercept_standoff_m:+$('icStand').value||40})}).then(r=>r.json()).catch(()=>({ok:false}));
  msg('setMsg',d.ok?'Saved.':(d.error||'Only operators and admins can change this.'),d.ok);load()}
async function uploadModel(){const f=$('modelFile').files[0];if(!f){msg('setMsg','Choose the .onnx file first.',false);return}
  msg('setMsg','Uploading and checking the model…');const fd=new FormData();fd.append('model',f);
  const r=await fetch('/api/detector/model',{method:'POST',body:fd});const d=await r.json().catch(()=>({ok:false}));
  msg('setMsg',d.ok?'Model installed: cameras on detectors are now checked by YOLO.':(r.status===403?'Only an admin can upload a model.':d.error||'Not installed.'),d.ok);load()}
async function removeModel(){if(!await uiConfirm('Remove the YOLO model? Cameras stop being checked for drones.'))return;
  const r=await fetch('/api/detector/model',{method:'DELETE'});msg('setMsg',r.ok?'Model removed.':'Only an admin can remove the model.',r.ok);load()}
async function load(){let d;try{d=await fetch('/api/detector',{cache:'no-store'}).then(r=>r.json())}catch(e){$('dtState').innerHTML='<i class="dot bad"></i>PC NOT ANSWERING';return}
  data=d;if(Date.now()-editing>1500)dets=d.detectors;
  const alarms=dets.filter(x=>alarmOf(x.id)).length;
  $('dtState').innerHTML=alarms?`<i class="dot bad"></i>${alarms} DETECTOR${alarms>1?'S':''} SEE AN INTRUDER`:`<i class="dot good"></i>${dets.filter(x=>x.enabled).length} WATCHING · NO INTRUDER`;
  if(document.activeElement?.tagName!=='INPUT'){$('ridUdp').checked=d.settings.remoteid_udp;$('ridPort').value=d.settings.remoteid_port;$('setTg').checked=d.settings.telegram;$('setClasses').value=d.settings.classes.join(', ');$('setScore').value=d.settings.min_score;$('snConf').value=d.settings.sensor_min_conf;
    $('icAuto').checked=d.settings.intercept_auto;$('icAlt').value=d.settings.intercept_alt_m;$('icStand').value=d.settings.intercept_standoff_m;renderIcDrones()}
  $('modelState').textContent=d.model.installed?(d.model.error?'⚠ '+d.model.error:`Installed (${d.model.size_mb} MB): detectors with a camera are checked every 3 s.`):'No model: detectors see drones by position only.';
  $('modelState').style.color=d.model.installed&&!d.model.error?'#7dffc1':d.model.error?'#ff9ea8':'';
  // First look: frame every detector's circle and every drone.
  if(!fitted){fitted=true;if(dets.length||(d.drones||[]).length){const bb=L.latLngBounds([]);
      dets.forEach(x=>{const c=L.circle([x.lat,x.lon],{radius:x.range_m}).addTo(map);bb.extend(c.getBounds());map.removeLayer(c)});
      (d.drones||[]).forEach(x=>bb.extend([x.lat,x.lon]));map.fitBounds(bb.pad(0.15),{maxZoom:18})}
    else{const f=window.mapFocus&&mapFocus.get();if(f)map.setView([f.lat,f.lon],16);else if(d.centre)map.setView(d.centre,16)}
    if(window.addMapSearch)addMapSearch(map)}
  // Redraw the list unless a range is being dragged or a camera list is open.
  const busy=Date.now()-editing<1500||document.activeElement?.matches?.('.dt-det select');
  const rid=d.remote_id||{};$('ridState').textContent=rid.heard?rid.heard+' HEARD NOW':(rid.sources||[]).length?'LISTENING':'NO RECEIVER YET';
  $('ridSources').innerHTML=(rid.sources||[]).length?'Receivers: '+rid.sources.map(x=>`${esc(x.source)} (${x.ago_s<60?x.ago_s+' s':Math.round(x.ago_s/60)+' min'} ago)`).join(' · '):'No receiver has reported yet.';
  const sn=d.sensors||{};$('snState').textContent=sn.hearing?sn.hearing+' HEARING NOW':dets.some(x=>x.sensor)?'LISTENING':'NO SENSOR YET';
  $('snSources').innerHTML=(sn.unknown_sensors||[]).length?'⚠ Reports for sensors that aren\'t on the map: '+sn.unknown_sensors.map(esc).join(', ')+' (name a detector the same, or send its id).':'';
  $('ridUdpState').textContent=rid.udp_error?'⚠ '+rid.udp_error:rid.udp?'Listening on '+rid.udp:'';
  renderIntercept();drawMap(busy);if(!busy)renderList();renderEvents();renderMine()}
function renderIcDrones(){const ours=(data.fleet||[]).filter(x=>x.mine&&!String(x.slot).includes(':')),pick=data.settings.intercept_drones||[];
  $('icDrones').innerHTML=ours.length?ours.map(x=>`<label style="display:flex;gap:5px;align-items:center;text-transform:none;letter-spacing:0;margin:0"><input type="checkbox" value="${esc(x.slot)}" ${pick.includes(x.slot)?'checked':''} onchange="saveSettings()">${esc(x.label)}${x.virtual?' <span class="muted">(virtual)</span>':''}</label>`).join(''):'<span class="muted">No drones of yours yet.</span>'}
function renderIntercept(){const ic=data.intercept||[],intr=(data.drones||[]).some(x=>x.intruder);
  $('icState').textContent=ic.length?ic.reduce((n,t)=>n+t.drones.length,0)+' DRONE(S) OUT':data.settings.intercept_auto?'AUTOMATIC':'BY HAND';
  $('icActive').innerHTML=ic.map(t=>`<div class="dt-ic"><h4><span>🛫 ${t.drones.map(x=>esc(x.label)).join(', ')} → ${esc(t.label)}</span><button onclick="recall('${esc(t.target)}')">Recall</button></h4>
    <div style="font-size:12px;margin-top:4px;color:#7fdcff">${t.drones.map(x=>esc(x.label)+': '+(x.distance_m==null?'no position':fmtM(x.distance_m)+' to go'+(x.alt!=null?' · '+Math.round(x.alt)+' m high':''))).join(' · ')}</div>
    <div class="muted" style="font-size:11px;margin-top:4px">For ${Math.round(t.for_s/60)} min · ${t.seen_s<5?'seen now':'last seen '+t.seen_s+' s ago'} · sent ${esc(t.by)}</div></div>`).join('')}
async function sendNow(){const r=await fetch('/api/detector/intercept',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({target:'all'})});
  const d=await r.json().catch(()=>({}));msg('icMsg',d.ok?d.message:(r.status===403?'Only operators and admins can send drones.':d.error||'Not sent.'),!!d.ok);load()}
async function recall(t){if(t==='all'&&!(data.intercept||[]).length){msg('icMsg','No drone is out.',false);return}
  const r=await fetch('/api/detector/intercept',{method:'DELETE',headers:{'content-type':'application/json'},body:JSON.stringify({target:t})});
  const d=await r.json().catch(()=>({}));msg('icMsg',d.ok?'Returning home.':(r.status===403?'Only operators and admins can recall drones.':d.error||'Not recalled.'),!!d.ok);load()}
async function showRid(){const r=await fetch('/api/detector/remoteid-config',{cache:'no-store'});const d=await r.json().catch(()=>({}));
  $('ridConf').innerHTML=r.ok?`<div class="dt-rid">POST ${esc(location.origin)}${esc(d.http_path)} (Remote ID)<br>POST ${esc(location.origin)}${esc(d.sensor_path||'/api/sensors/report')} (acoustic / RF sensors)<br>X-RemoteID-Token: ${esc(d.token)}${d.udp?'<br>UDP: this PC, port '+d.port:''}</div>`:'<div class="hud-msg bad">Only an admin can see the receiver token.</div>'}
async function newRidToken(){if(!await uiConfirm('Make a new receiver token? Receivers using the old one stop being accepted until they get the new one.'))return;
  const r=await fetch('/api/detector/remoteid-config',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({new_token:true})});
  if(r.ok)showRid();else $('ridConf').innerHTML='<div class="hud-msg bad">Only an admin can change the receiver token.</div>'}
function renderMine(){const f=data.fleet||[];$('mineCount').textContent=f.filter(x=>x.mine).length+' OF '+f.length;
  $('mineList').innerHTML=f.length?f.map(x=>`<div class="hud-row"><div><b>${esc(x.label)}</b>${x.virtual?' <span class="muted">(virtual)</span>':''}${x.remote_id?' <span class="muted">(Remote ID)</span>':''}<div class="muted" style="color:${x.mine?'#7dffc1':'#ff9ea8'}">${x.mine?'✓ Mine: never raises the alarm':'⚠ Unknown: raises the alarm in a detector\'s range'}</div></div>`
    +`<button class="hud-btn${x.mine?'':' primary'}" data-slot="${esc(x.slot)}" data-mine="${x.mine?0:1}">${x.mine?'Not mine':'Mark as mine'}</button></div>`).join(''):'<div class="muted">No drones yet.</div>';
  document.querySelectorAll('#mineList button').forEach(b=>b.onclick=async()=>{const mine=b.dataset.mine==='1';
    if(!mine&&!await uiConfirm('Treat this drone as unknown? It will raise the alarm when it flies into a detector\'s range.'))return;
    const r=await fetch('/api/detector/mine',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({drone:b.dataset.slot,mine})});
    msg('setMsg',r.ok?(mine?'Marked as yours.':'Marked as unknown.'):'Only operators and admins can change this.',r.ok);load()})}
load();setInterval(load,2000);
</script>"""
