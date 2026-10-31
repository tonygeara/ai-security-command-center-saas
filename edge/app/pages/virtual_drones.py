"""The Virtual drones tab."""
BODY = r"""
<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">
<style>
.vd-grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(340px,1fr);gap:16px;align-items:start}
#vdMap{height:460px;border:1px solid #155879;border-radius:5px;background:#020a10}
.vd-card{border:1px solid #155879;border-radius:5px;background:#05131d;padding:12px;margin-bottom:10px}
.vd-card h3{margin:0 0 6px;font-size:14px;color:#e9f8ff;letter-spacing:1px;display:flex;justify-content:space-between;align-items:center}
.vd-tag{font-size:10px;color:#ffcf7a;border:1px solid #7a5a12;border-radius:3px;padding:2px 6px;letter-spacing:1px}
.vd-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:8px 0}
.vd-stats div{background:#020a10;border:1px solid #153c56;border-radius:4px;padding:6px 8px}
.vd-stats small{display:block;color:#6d8b9d;font-size:9px;letter-spacing:1.5px;text-transform:uppercase}
.vd-stats b{color:#e9f8ff;font-size:14px}
.vd-card .actions{flex-wrap:wrap;gap:6px}
.vd-card .hud-btn{min-height:32px;font-size:11px}
@media(max-width:1000px){.vd-grid{grid-template-columns:1fr}}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Testing &amp; demos</div><h1 class="page-title">Virtual Drones</h1>
<div class="page-sub">Simulated drones that connect like a real Drone Link phone. Use them to test routes, patrols and alert responses, train operators, or demo the system with no drone on site. They never control a real aircraft.</div></div>
<div class="actions"><span class="state" id="vdState"><i class="dot warn"></i>LOADING</span></div></div>
<div class="vd-grid">
<section class="panel"><div class="panel-head"><div class="panel-title">⌖ Map</div><div class="live" id="vdHint">CLICK THE MAP TO CHOOSE A START POINT</div></div>
<div class="panel-body"><div id="vdMap"></div>
<div class="actions" style="margin-top:10px;align-items:center"><button class="hud-btn primary" id="vdAdd" onclick="addVd()">+ Add virtual drone here</button>
<span class="muted" id="vdPick">No start point chosen yet.</span></div>
<label style="margin-top:12px;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0"><input type="checkbox" id="vdAuto" onchange="setAuto(this.checked)">
Demo mode: let automatic missions (alert response, patrols set to "any drone", Telegram) use virtual drones when no real drone is ready</label>
<div id="vdMsg" class="hud-msg"></div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">◇ Virtual fleet</div><div class="live" id="vdCount"></div></div>
<div class="panel-body"><div id="vdList"><p class="muted">Loading…</p></div>
<div class="muted" style="margin-top:8px">Fly them from <b>Open controls</b> exactly like a real drone (take off, keyboard, click-to-fly, routes, patrols). Battery lasts about 24 minutes of flight; at 15% they return home and at 5% they land, like a real DJI drone.</div></div></section>
</div>
</main>
<script src="/vendor/leaflet/leaflet.js"></script>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
let map=null,pick=null,pickMark=null,marks={},trails={},homes={},data={drones:[]};
function msg(t,ok){const e=$('vdMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
function initMap(lat,lon){if(map||typeof L==='undefined')return;map=L.map('vdMap').setView([lat,lon],17);
  L.tileLayer('/tiles/sat/{z}/{x}/{y}',{maxZoom:19,attribution:'Esri'}).addTo(map);
  fetch('/api/nofly').then(r=>r.json()).then(d=>(d.zones||[]).forEach(z=>L.polygon(z.points.map(p=>[p.lat,p.lon]),{color:'#ff4d6a',weight:2,fillOpacity:.25,interactive:false}).addTo(map))).catch(()=>{});
  map.on('click',e=>{pick=[e.latlng.lat,e.latlng.lng];pickMark=pickMark||L.circleMarker(pick,{radius:8,color:'#ffd23f'}).addTo(map);pickMark.setLatLng(pick);
    $('vdPick').textContent='Start point: '+pick[0].toFixed(5)+', '+pick[1].toFixed(5)})}
const icon=h=>L.divIcon({className:'',iconSize:[26,26],iconAnchor:[13,13],html:`<div style="transform:rotate(${h||0}deg);font-size:22px;line-height:26px;text-align:center;color:#ffcf7a;text-shadow:0 0 4px #000">➤</div>`});
function draw(){if(!map)return;const seen=new Set();
  data.drones.forEach(d=>{seen.add(d.drone);const p=[d.lat,d.lon];
    marks[d.drone]=marks[d.drone]||L.marker(p).bindTooltip('',{permanent:true,direction:'right'}).addTo(map);
    marks[d.drone].setLatLng(p).setIcon(icon(d.heading-90)).setTooltipContent(esc(d.label)+(d.flying?' · '+d.altitude+' m':''));
    trails[d.drone]=trails[d.drone]||L.polyline([],{color:'#ffcf7a',weight:2,opacity:.7}).addTo(map);if(d.flying)trails[d.drone].addLatLng(p);
    homes[d.drone]=homes[d.drone]||L.circleMarker([d.home_lat,d.home_lon],{radius:5,color:'#2aea88'}).addTo(map);homes[d.drone].setLatLng([d.home_lat,d.home_lon])});
  Object.keys(marks).filter(k=>!seen.has(k)).forEach(k=>{[marks,trails,homes].forEach(o=>{o[k].remove();delete o[k]})})}
function card(d){const st=!d.powered?'Switched off':d.link_down?'Link lost (reconnecting)':!d.linked?'Connecting…':d.mission?'Auto-fly: '+d.mission:d.flying?d.mode.replace(/_/g,' ').toLowerCase():'On the ground';
  return `<div class="vd-card"><h3>${esc(d.label)} <span class="vd-tag">VIRTUAL</span></h3><div class="muted">${esc(st)}</div>
  <div class="vd-stats"><div><small>Battery</small><b>${d.battery}%</b></div><div><small>Height</small><b>${d.altitude} m</b></div><div><small>GPS</small><b>${d.gps_satellites}</b></div></div>
  <div class="actions"><a class="hud-btn primary" href="/drone-control?drone=${encodeURIComponent(d.drone)}" style="text-decoration:none">Open controls</a>
  <button class="hud-btn" onclick="act('${d.drone}','power')">${d.powered?'Switch off':'Switch on'}</button>
  <button class="hud-btn" onclick="act('${d.drone}','recharge')">Recharge</button>
  <button class="hud-btn" onclick="moveHome('${d.drone}')">Move home here</button>
  <button class="hud-btn warn" onclick="act('${d.drone}','low_battery')" title="Battery to 20%">Low battery</button>
  <button class="hud-btn warn" onclick="act('${d.drone}','weak_gps')">${d.gps_satellites<8?'Restore GPS':'Weak GPS'}</button>
  <button class="hud-btn warn" onclick="act('${d.drone}','drop_link')" title="Phone link drops for 10 seconds">Drop link 10 s</button>
  <button class="hud-btn danger" onclick="removeVd('${d.drone}')">Remove</button></div></div>`}
async function load(){try{data=await fetch('/api/virtual-drones',{cache:'no-store'}).then(r=>r.json())}catch(e){return}
  $('vdState').innerHTML=data.allowed?'<i class="dot good"></i>SIMULATOR READY':'<i class="dot bad"></i>DRONE CONTROL NOT IN LICENCE';
  $('vdCount').textContent=data.drones.length+' / '+data.max;$('vdAdd').disabled=data.drones.length>=data.max;$('vdAuto').checked=!!data.demo_auto;
  $('vdList').innerHTML=data.drones.map(card).join('')||'<p class="muted">No virtual drones yet. Click the map, then <b>+ Add virtual drone here</b>.</p>';
  if(!map){const d=data.drones[0];if(d)initMap(d.home_lat,d.home_lon);else navigator.geolocation?navigator.geolocation.getCurrentPosition(p=>initMap(p.coords.latitude,p.coords.longitude),()=>initMap(33.8938,35.5018),{timeout:4000}):initMap(33.8938,35.5018)}
  draw()}
async function addVd(){if(!pick){msg('Click the map first to choose where it starts.',false);return}
  const d=await fetch('/api/virtual-drones',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({lat:pick[0],lon:pick[1]})}).then(r=>r.json());
  msg(d.ok?d.label+' added. Open controls to fly it.':d.error,d.ok);load()}
async function act(slot,action,extra){const d=await fetch('/api/virtual-drones/'+encodeURIComponent(slot),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action,...(extra||{})})}).then(r=>r.json());
  if(!d.ok)msg(d.error,false);load()}
function moveHome(slot){if(!pick){msg('Click the map first to choose the new home point.',false);return}act(slot,'home',{lat:pick[0],lon:pick[1]})}
async function removeVd(slot){if(!confirm('Remove this virtual drone?'))return;await fetch('/api/virtual-drones/'+encodeURIComponent(slot),{method:'DELETE'});load()}
async function setAuto(on){await fetch('/api/virtual-drones',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({demo_auto:on})});
  msg(on?'Demo mode on: automatic missions may use virtual drones.':'Demo mode off: automatic missions use real drones only.',true)}
load();setInterval(load,1000);
</script>"""
