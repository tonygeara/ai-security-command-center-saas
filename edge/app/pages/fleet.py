"""The Fleet tab: every drone on one map, where each is going and how far, with the controls of each drone, its patrol
route (drawn on the map), drag-to-move, and Stop all / Return all home."""
BODY = r"""
<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">
<style>
.fl-grid{display:grid;grid-template-columns:minmax(0,1fr) 420px;gap:14px;align-items:start}
#flMap{height:calc(100vh - 250px);min-height:520px;border:1px solid #155879;border-radius:5px;background:#020a10}
#flMap.picking{cursor:crosshair}
.fl-bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.fl-chip{border:1px solid #155879;border-radius:12px;padding:4px 10px;font-size:11px;color:#9edfff;background:none;cursor:pointer}
.fl-chip.on{background:#0b3550;color:#fff}
.fl-list{max-height:calc(100vh - 250px);min-height:520px;overflow:auto;padding-right:2px}
.fl-card{border:1px solid #153c56;border-radius:4px;padding:9px 10px;margin-bottom:8px;background:#05131d}
.fl-card.sel{border-color:#25c7ff;box-shadow:0 0 0 1px #25c7ff inset}
.fl-card h4{margin:0 0 4px;font:bold 13px Arial;color:#e9f8ff;display:flex;align-items:center;gap:7px}
.fl-card h4 i{width:9px;height:9px;border-radius:50%;display:inline-block;flex:none}
.fl-card h4 span.nm{cursor:pointer}
.fl-tag{margin-left:auto;font-size:9px;letter-spacing:1px;padding:2px 6px;border-radius:3px;border:1px solid}
.fl-st{font-size:11px;color:#8fb3c7;line-height:1.5}.fl-st b{color:#e9f8ff}
.fl-acts{display:flex;gap:5px;margin-top:7px;flex-wrap:wrap}
.fl-acts button{background:#05131d;border:1px solid #1d6a91;color:#9edfff;border-radius:3px;padding:4px 8px;font:bold 10px Arial;letter-spacing:.5px;cursor:pointer}
.fl-acts button:hover{background:#0b2c40}.fl-acts button.r{border-color:#7a3340;color:#ff9ea8}.fl-acts button.on{background:#25c7ff;color:#022}
.fl-acts button:disabled{opacity:.4;cursor:default}
.fl-ed{margin-top:8px;border-top:1px solid #0f2a3b;padding-top:8px;font-size:11px;color:#9edfff}
.fl-ed input[type=number]{width:62px}
.fl-lbl{background:rgba(3,16,26,.9);border:1px solid #1d6a91;color:#e9f8ff;font:bold 11px Arial;padding:2px 6px;border-radius:3px;box-shadow:none;white-space:nowrap}
.fl-lbl::before{display:none}
.fl-num{background:#03111b;border:1px solid #25c7ff;color:#e9f8ff;font:bold 10px Arial;padding:0 4px;border-radius:3px;box-shadow:none}.fl-num::before{display:none}
.fl-legend{font-size:11px;color:#8fb3c7;margin-top:6px}
@media(max-width:1100px){.fl-grid{grid-template-columns:1fr}#flMap{height:60vh}.fl-list{max-height:none}}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Drones</div><h1 class="page-title">Fleet</h1>
<div class="page-sub">Every drone on one map: where each one is, which way it flies, where it is going and how far it still has to go. Fly each one from its card, draw its patrol route on the map, drag a drone to move it, or stop or recall them all at once.</div></div>
<div class="actions"><span class="state" id="flState"><i class="dot warn"></i>LOADING</span></div></div>
<div class="fl-bar" id="flFilters"></div>
<div class="fl-bar">
<label class="l4d-switch" title="Every drone flies its own patrol route again and again"><input type="checkbox" class="toggle" id="flPatrol" onchange="setPatrol(this.checked)"> RUN PATROL</label>
<button class="hud-btn" id="flSendSel" onclick="pickSendSelected()" title="Tick drones in the list, then click the map">➤ Send ticked drones to a spot</button>
<span style="flex:1"></span>
<button class="hud-btn danger" onclick="stopAll()">■ Stop all</button>
<button class="hud-btn danger" onclick="homeAll()">⌂ Return all home</button>
</div>
<div id="flMsg" class="hud-msg"></div>
<div class="fl-grid">
<section class="panel"><div class="panel-body"><div id="flMap"></div>
<div class="fl-legend">▲ drone (points the way it flies) · dashed line: where it is going, with the distance · dotted: its route ahead · faded: its patrol route · thin line: where it has been ·
<span style="color:#25c7ff">■</span> patrol <span style="color:#ff9f43">■</span> response <span style="color:#c18bff">■</span> watching an intruder <span style="color:#ffcf7a">■</span> backup <span style="color:#e9f8ff">■</span> flying <span style="color:#26ee89">■</span> ready <span style="color:#6d8b9d">■</span> offline</div></div></section>
<div class="fl-list" id="flList"><div class="muted">Loading…</div></div>
</div>
</main>
<script src="/vendor/leaflet/leaflet.js"></script><script src="/mapsearch.js"></script>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const fmtM=m=>m==null?'–':m>=1000?(m/1000).toFixed(1)+' km':Math.round(m)+' m';
const COL={patrol:'#25c7ff',response:'#ff9f43',watching:'#c18bff',backup:'#ffcf7a',standby:'#ffcf7a',flying:'#e9f8ff',ready:'#26ee89',offline:'#6d8b9d'};
const TAG={patrol:'PATROL',response:'RESPONSE',watching:'WATCHING',backup:'BACKUP',standby:'BACKUP',flying:'FLYING',ready:'READY',offline:'OFFLINE'};
let data={drones:[],docks:[]},filter='all',sel=new Set(),picking=null,edit=null,dragging=null,fitted=false,trails={};
const map=L.map('flMap',{maxZoom:20}).setView([20,0],2);
L.tileLayer('/tiles/sat/{z}/{x}/{y}',{maxZoom:20,maxNativeZoom:19}).addTo(map);
const zoneL=L.layerGroup().addTo(map),routeL=L.layerGroup().addTo(map),droneL=L.layerGroup().addTo(map),editL=L.layerGroup().addTo(map);
if(window.addMapSearch)addMapSearch(map);
function msg(t,ok){const e=$('flMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t||''}
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body||{})});
  let d={};try{d=await r.json()}catch(e){}if(r.status===403&&d.ok===undefined)d={ok:false,error:'Only operators and admins can fly drones.'};
  if(!r.ok&&d.ok===undefined)d={ok:false,error:'Error '+r.status};if(r.status===403&&!d.error)d.error='Only operators and admins can fly drones.';return {status:r.status,...d}}
const D=slot=>data.drones.find(x=>x.slot===slot);
function pos(x){return x.lat!=null?[x.lat,x.lon]:(x.pin?[x.pin.lat,x.pin.lon]:null)}
function low(x){return x.battery!=null&&x.battery<30}
function shown(x){return filter==='all'||(filter==='flying'&&x.flying)||(filter==='ready'&&x.job==='ready')||(filter==='offline'&&x.job==='offline')||(filter==='low'&&low(x))}
function icon(x){const c=COL[x.job]||'#e9f8ff',me=sel.has(x.slot);
  if(x.lat==null)return L.divIcon({className:'',iconSize:[26,26],iconAnchor:[13,13],html:`<div style="width:22px;height:22px;border-radius:50%;border:2px dashed #8fb3c7;background:rgba(5,19,29,.85);color:#8fb3c7;font:bold 12px/18px Arial;text-align:center">✈</div>`});
  return L.divIcon({className:'',iconSize:[34,34],iconAnchor:[17,17],html:`<div style="transform:rotate(${x.heading||0}deg);color:${c};font-size:${me?30:26}px;line-height:34px;text-align:center;text-shadow:0 0 6px #000,0 0 2px #000${me?',0 0 10px '+c:''}">▲</div>`})}
function drawMap(){zoneL.clearLayers();routeL.clearLayers();
  (data.nofly||[]).forEach(z=>L.polygon(z.points.map(p=>[p.lat,p.lon]),{color:'#ff4d6a',weight:1.5,fillOpacity:.15,interactive:false}).addTo(zoneL));
  (data.docks||[]).forEach(k=>{if(k.lat==null)return;L.marker([k.lat,k.lon],{icon:L.divIcon({className:'',iconSize:[24,24],iconAnchor:[12,12],
    html:`<div style="width:20px;height:20px;border-radius:4px;background:#031a0e;border:2px solid ${k.online?'#26ee89':'#6d8b9d'};color:${k.online?'#26ee89':'#6d8b9d'};font:bold 12px/16px Arial;text-align:center">⌂</div>`})})
    .bindTooltip(`${esc(k.name)} · ${k.online?(k.drone_in_dock===false?'drone out':k.ready?'ready':'not ready'):'offline'}${k.battery!=null?' · '+k.battery+'%':''}`,{permanent:true,direction:'right',offset:[10,0],className:'fl-lbl'}).addTo(zoneL);
    if(k.drone_in_dock===false&&k.drone_lat)L.circleMarker([k.drone_lat,k.drone_lon],{radius:6,color:'#26ee89',fillOpacity:.8}).bindTooltip(esc(k.name)+' drone').addTo(zoneL)});
  (data.intruders||[]).forEach(t=>L.circleMarker([t.lat,t.lon],{radius:7,color:'#fff',weight:2,fillColor:'#e0283e',fillOpacity:1}).bindTooltip('⚠ '+esc(t.label),{permanent:true,direction:'top',offset:[0,-8],className:'fl-lbl'}).addTo(zoneL));
  data.drones.filter(shown).forEach(x=>{const c=COL[x.job]||'#e9f8ff',p=pos(x);
    if(x.patrol_route&&x.patrol_route.points.length&&(!edit||edit.slot!==x.slot)){const pp=x.patrol_route.points.map(q=>[q.lat,q.lon]);
      L.polyline(x.patrol_route.loop?pp.concat([pp[0]]):pp,{color:c,weight:1.5,opacity:.3,dashArray:'2 6',interactive:false}).addTo(routeL)}
    if(x.route){const pts=x.route.points.map(q=>[q.lat,q.lon]);
      L.polyline(pts.slice(x.route.index),{color:c,weight:2,opacity:.6,dashArray:'2 6',interactive:false}).addTo(routeL);
      pts.forEach((q,i)=>L.circleMarker(q,{radius:5,color:c,weight:1.5,fillColor:i<x.route.index?c:'#03111b',fillOpacity:1}).bindTooltip(String(i+1),{permanent:true,direction:'center',className:'fl-num'}).addTo(routeL))}
    const tr=trails[x.slot];if(tr&&tr.length>1)L.polyline(tr,{color:c,weight:2,opacity:.45,interactive:false}).addTo(routeL);
    if(x.target&&x.lat!=null){L.polyline([[x.lat,x.lon],[x.target.lat,x.target.lon]],{color:x.target.intruder?'#c18bff':c,weight:3,dashArray:'10 6'})
      .bindTooltip(fmtM(x.target.distance_m)+(x.target.label?' to '+esc(x.target.label):''),{permanent:true,direction:'center',className:'fl-lbl'}).addTo(routeL)}});
  if(dragging)return;droneL.clearLayers();
  data.drones.filter(shown).forEach(x=>{const p=pos(x);if(!p)return;
    const m=L.marker(p,{icon:icon(x),draggable:!!(data.allowed&&(x.lat!=null||x.pin)),zIndexOffset:sel.has(x.slot)?1000:500})
      .bindTooltip(`${esc(x.label)} · ${TAG[x.job].toLowerCase()}${x.battery!=null?' · '+x.battery+'%':''}${x.alt!=null&&x.flying?' · '+Math.round(x.alt)+' m':''}`,{permanent:true,direction:'right',offset:[14,0],className:'fl-lbl'})
      .on('click',()=>focusCard(x.slot)).on('dragstart',()=>{dragging=x.slot}).on('dragend',e=>dropDrone(x,e.target.getLatLng())).addTo(droneL)})}
function fitAll(){const pts=[];data.drones.forEach(x=>{const p=pos(x);if(p)pts.push(p);
    [...((x.route||{}).points||[]),...((x.patrol_route||{}).points||[])].forEach(q=>pts.push([q.lat,q.lon]));if(x.target)pts.push([x.target.lat,x.target.lon])});(data.docks||[]).forEach(k=>{if(k.lat!=null)pts.push([k.lat,k.lon])});
  if(pts.length)map.fitBounds(L.latLngBounds(pts).pad(0.25),{maxZoom:18});else if(data.centre)map.setView(data.centre,17);else{const f=window.mapFocus&&mapFocus.get();if(f)map.setView([f.lat,f.lon],16)}}
function renderFilters(){const n=k=>data.drones.filter(x=>k==='all'||(k==='flying'&&x.flying)||(k==='ready'&&x.job==='ready')||(k==='offline'&&x.job==='offline')||(k==='low'&&low(x))).length;
  $('flFilters').innerHTML=[['all','All'],['flying','Flying'],['ready','Ready'],['offline','Offline'],['low','Low battery']].map(([k,t])=>`<button class="fl-chip ${filter===k?'on':''}" onclick="setFilter('${k}')">${t} ${n(k)}</button>`).join('')
    +'<span class="muted" style="font-size:11px;margin-left:6px">Click a drone on the map or its name to select it; tick drones to send several at once.</span>'}
function setFilter(k){filter=k;render()}
function card(x){const c=COL[x.job]||'#e9f8ff',dis=!data.allowed||x.over_limit,live=x.lat!=null,ed=edit&&edit.slot===x.slot;
  const st=[];st.push(esc(x.job_text));if(x.target&&x.target.distance_m!=null)st.push(`<b>${fmtM(x.target.distance_m)}</b> to ${esc(x.target.label||'target')}`);
  const st2=[];if(x.battery!=null)st2.push(`Battery <b>${x.battery}%</b>`);if(live&&x.flying&&x.alt!=null)st2.push(`<b>${Math.round(x.alt)} m</b> high`);if(live&&x.speed!=null&&x.flying)st2.push(`<b>${(+x.speed).toFixed(1)} m/s</b>`);
  if(live&&x.heading!=null&&x.flying)st2.push(`heading ${Math.round((x.heading+360)%360)}°`);if(x.over_limit)st2.push('<b style="color:#ff9ea8">over the licence\'s drone limit</b>');
  const pr=x.patrol_route?`Patrol route: <b>${esc(x.patrol_route.name)}</b> (${x.patrol_route.points.length} stops${x.patrol_route.loop?', repeats':''})`:'No patrol route yet';
  return `<div class="fl-card ${sel.has(x.slot)?'sel':''}" id="card-${esc(x.slot)}" data-slot="${esc(x.slot)}">
  <h4><input type="checkbox" title="Tick to send with other drones" ${sel.has(x.slot)?'checked':''} onchange="tick('${esc(x.slot)}',this.checked)"><i style="background:${c}"></i><span class="nm" onclick="findDrone('${esc(x.slot)}')">${esc(x.label)}</span>${x.virtual?'<small class="muted">virtual</small>':''}<span class="fl-tag" style="color:${c};border-color:${c}55">${TAG[x.job]}</span></h4>
  <div class="fl-st">${st.join(' · ')}<br>${st2.join(' · ')||'&nbsp;'}<br><span style="color:#6d8b9d">${pr}</span></div>
  <div class="fl-acts">
   <button ${dis||!live||x.flying?'disabled':''} onclick="cmd('${esc(x.slot)}','takeoff')">⬆ Take off</button>
   <button ${dis||!x.flying?'disabled':''} onclick="hover('${esc(x.slot)}')">■ Hover</button>
   <button ${dis||!x.flying?'disabled':''} class="r" onclick="cmd('${esc(x.slot)}','go_home','Return home?')">⌂ Home</button>
   <button ${dis||!x.flying?'disabled':''} onclick="cmd('${esc(x.slot)}','land','Land where it is now?')">⬇ Land</button>
   <button ${dis||!live?'disabled':''} class="${picking&&picking.slot===x.slot?'on':''}" onclick="pickSend('${esc(x.slot)}')">➤ Send to…</button>
   <button ${dis?'disabled':''} class="${ed?'on':''}" onclick="editRoute('${esc(x.slot)}')">✎ Patrol route</button>
   <button ${dis||!live||!x.patrol_route?'disabled':''} onclick="flyPatrol('${esc(x.slot)}')">▶ Fly patrol</button>
   <button ${dis||!x.route?'disabled':''} onclick="stopRoute('${esc(x.slot)}')">⏹ Stop route</button>
   <button onclick="findDrone('${esc(x.slot)}')">⌖ Find</button>
   <a class="hud-btn" style="min-height:0;padding:4px 8px;font-size:10px" href="/drone-control?drone=${encodeURIComponent(x.slot)}">Open</a>
  </div>${ed?editor(x):''}</div>`}
function editor(x){return `<div class="fl-ed">Click the map to add stops (drag a stop to move it). <b>${edit.pts.length}</b> stop${edit.pts.length===1?'':'s'} · about <b>${fmtM(routeLen())}</b><br>
  <span style="display:inline-flex;gap:8px;align-items:center;margin-top:6px;flex-wrap:wrap">Height <input type="number" id="edAlt" min="10" max="120" value="${edit.alt}" onchange="edit.alt=+this.value">m
  Speed <input type="number" id="edSpd" min="1" max="8" value="${edit.speed}" onchange="edit.speed=+this.value">m/s
  <label style="display:inline-flex;gap:4px;align-items:center;text-transform:none;letter-spacing:0;margin:0"><input type="checkbox" ${edit.loop?'checked':''} onchange="edit.loop=this.checked"> Repeat until stopped</label></span>
  <div class="fl-acts"><button onclick="edUndo()">↶ Undo</button><button onclick="edClear()">Clear</button><button class="on" onclick="edSave(false)">💾 Save as its patrol route</button><button onclick="edSave(true)">▶ Save and fly now</button><button class="r" onclick="edCancel()">Cancel</button></div></div>`}
function renderList(){const a=document.activeElement;if(a&&$('flList').contains(a)&&a.tagName==='INPUT'&&a.type==='number')return;
  const ds=data.drones.filter(shown);$('flList').innerHTML=ds.length?ds.map(card).join(''):'<div class="muted">No drone here. Add drones on the Drone page (+ Add drone).</div>'}
function render(){renderFilters();drawMap();renderList();drawEdit();
  const fly=data.drones.filter(x=>x.flying).length,rdy=data.drones.filter(x=>x.job==='ready').length,off=data.drones.filter(x=>x.job==='offline').length;
  $('flState').innerHTML=`<i class="dot ${fly?'good':'warn'}"></i>${fly} FLYING · ${rdy} READY · ${off} OFFLINE`}
async function load(){try{data=await fetch('/api/fleet',{cache:'no-store'}).then(r=>r.json())}catch(e){$('flState').innerHTML='<i class="dot bad"></i>PC NOT ANSWERING';return}
  data.drones.forEach(x=>{if(x.lat==null)return;const t=trails[x.slot]=trails[x.slot]||[],l=t[t.length-1];if(!l||l[0]!==x.lat||l[1]!==x.lon){t.push([x.lat,x.lon]);if(t.length>90)t.shift()}});
  if(document.activeElement!==$('flPatrol'))$('flPatrol').checked=!!data.patrol_on;
  if(!fitted){fitted=true;fitAll()}render()}
function tick(slot,on){on?sel.add(slot):sel.delete(slot);drawMap();document.querySelectorAll('.fl-card').forEach(c=>c.classList.toggle('sel',sel.has(c.dataset.slot)))}
function focusCard(slot){sel.add(slot);render();const c=$('card-'+slot);if(c)c.scrollIntoView({behavior:'smooth',block:'nearest'})}
function findDrone(slot){const x=D(slot),p=x&&pos(x);if(p){map.setView(p,Math.max(map.getZoom(),17));focusCard(slot);msg(x.lat==null?x.label+' is not connected: shown at its pin.':'')}
  else msg((x?x.label:'This drone')+' has no position yet: pin it on its Drone page (📍 Pin drone).',false)}
async function cmd(slot,c,ask){const x=D(slot);if(ask&&!await uiConfirm(x.label+': '+ask))return;
  let d=await post('/api/drone/command?drone='+encodeURIComponent(slot),{cmd:c});
  if(!d.ok&&d.can_force&&await uiConfirm('⚠ '+d.error+'\n\nTake off anyway? You are responsible for the flight.'))d=await post('/api/drone/command?drone='+encodeURIComponent(slot),{cmd:c,args:{force:true}});
  msg(d.ok?x.label+': '+({takeoff:'taking off',go_home:'returning home',land:'landing',hover:'hovering'}[c]||c)+'.':(d.error||'Not done.'),!!d.ok);load()}
async function hover(slot){const x=D(slot);if(x.route)await post('/api/routes/stop?drone='+encodeURIComponent(slot));cmd(slot,'hover')}
async function stopRoute(slot){const d=await post('/api/routes/stop?drone='+encodeURIComponent(slot));msg(d.ok?D(slot).label+': route stopped, hovering.':(d.error||'Not stopped.'),!!d.ok);load()}
async function flyPatrol(slot){const x=D(slot),r=x.patrol_route;if(!r)return;
  if(!await uiConfirm(`${x.label}: fly its patrol route “${r.name}” (${r.points.length} stops${r.loop?', repeating until stopped':''})? It takes off if it is on the ground. Keep it in sight.`))return;
  const d=await post('/api/routes/fly?drone='+encodeURIComponent(slot),{name:r.name});msg(d.ok?d.message:(d.error||'Not started.'),!!d.ok);load()}
function pickSend(slot){picking=picking&&picking.slot===slot?null:{slot};edit=null;$('flMap').classList.toggle('picking',!!picking);msg(picking?'Click the map where '+D(slot).label+' should fly.':'');render()}
function pickSendSelected(){if(!sel.size){msg('Tick one or more drones in the list first.',false);return}picking={many:[...sel]};edit=null;$('flMap').classList.add('picking');msg('Click the map where the ticked drones should fly (they spread out around the spot).')}
async function sendTo(slot,lat,lon,quiet){const x=D(slot);
  const d=await post('/api/routes/fly?drone='+encodeURIComponent(slot),{name:'Sent from Fleet',points:[{lat,lon}],alt:30,speed:6,pause:0,end:'hover'});
  if(!quiet)msg(d.ok?x.label+' is flying there.':(d.error||'Not sent.'),!!d.ok);return d}
// Drag a drone: a virtual one flies there or is put there; a real one flies there after a warning; a pinned one moves its pin.
async function dropDrone(x,ll){const lat=+ll.lat.toFixed(6),lon=+ll.lng.toFixed(6);
  try{if(x.lat==null){const d=await post('/api/drone/pin?drone='+encodeURIComponent(x.slot),{lat,lon});msg(d.ok?x.label+': pin moved.':(d.error||'Not moved.'),!!d.ok);return}
    const far=Math.round(map.distance([x.lat,x.lon],ll));let how;
    if(x.virtual)how=await uiChoose(`Send ${x.label} (virtual) ${far} m to ${lat.toFixed(5)}, ${lon.toFixed(5)}?`,['Fly there','Move there now'],{title:'Virtual drone'});
    else how=await uiConfirm(`REAL FLIGHT: ${x.label} takes off if it is on the ground and flies ${far} m to ${lat.toFixed(5)}, ${lon.toFixed(5)} at 30 m, then hovers there.\n\nThe usual checks apply (no-fly zones, weather, battery). Keep it in sight.`,{title:'Fly the drone there',ok:'Fly there',danger:true})?0:null;
    if(how===null)return;
    if(how===1){const d=await post('/api/virtual-drones/'+encodeURIComponent(x.slot),{action:'move',lat,lon});msg(d.ok!==false&&d.status<300?x.label+' moved.':(d.error||'Not moved.'),d.ok!==false&&d.status<300)}
    else await sendTo(x.slot,lat,lon)}finally{dragging=null;await load()}}
map.on('click',async e=>{const lat=+e.latlng.lat.toFixed(6),lon=+e.latlng.lng.toFixed(6);
  if(edit){if(edit.pts.length>=25){msg('25 stops maximum.',false);return}edit.pts.push({lat,lon});renderList();drawEdit();return}
  if(!picking)return;const p=picking;picking=null;$('flMap').classList.remove('picking');
  if(p.slot){const x=D(p.slot);if(await uiConfirm(`${x.label} flies to ${lat.toFixed(5)}, ${lon.toFixed(5)} at 30 m and hovers there. Keep it in sight.`,{title:'Send drone',ok:'Fly there',danger:!x.virtual}))await sendTo(p.slot,lat,lon);load();return}
  const ds=p.many.map(D).filter(x=>x&&x.lat!=null);
  if(!ds.length){msg('None of the ticked drones has a live position.',false);return}
  if(!await uiConfirm(`${ds.map(x=>x.label).join(', ')} fly to this spot at 30 m (spread ${ds.length>1?'20 m apart':''}) and hover there. Keep them in sight.`,{title:'Send drones',ok:'Fly there',danger:true}))return;
  const out=[];for(let i=0;i<ds.length;i++){const a=i*2*Math.PI/Math.max(1,ds.length),r=ds.length>1?20:0;
    const q=[lat+r*Math.cos(a)/111320,lon+r*Math.sin(a)/(111320*Math.cos(lat*Math.PI/180))];const d=await sendTo(ds[i].slot,q[0],q[1],true);out.push(ds[i].label+(d.ok?' ✓':' ✗ '+(d.error||'')))}
  msg(out.join(' · '),out.every(t=>t.includes('✓')));load()});
// Patrol route editor
function editRoute(slot){const x=D(slot);if(edit&&edit.slot===slot){edCancel();return}picking=null;$('flMap').classList.remove('picking');
  const r=x.patrol_route;edit={slot,pts:r?r.points.map(p=>({lat:p.lat,lon:p.lon})):[],alt:r?Math.round(r.alt):30,speed:5,loop:r?!!r.loop:true};
  msg('Click the map to add '+x.label+'\'s patrol stops.');const p=pos(x);if(p&&!edit.pts.length)map.setView(p,Math.max(map.getZoom(),17));render()}
function routeLen(){let s=0;for(let i=1;i<edit.pts.length;i++)s+=map.distance([edit.pts[i-1].lat,edit.pts[i-1].lon],[edit.pts[i].lat,edit.pts[i].lon]);return s}
function drawEdit(){editL.clearLayers();if(!edit)return;const pp=edit.pts.map(p=>[p.lat,p.lon]);
  if(pp.length>1)L.polyline(edit.loop?pp.concat([pp[0]]):pp,{color:'#ffcf7a',weight:2.5,dashArray:'6 5'}).addTo(editL);
  edit.pts.forEach((p,i)=>L.marker([p.lat,p.lon],{draggable:true,icon:L.divIcon({className:'',iconSize:[22,22],iconAnchor:[11,11],
    html:`<div style="width:20px;height:20px;border-radius:50%;background:#2a1d02;border:2px solid #ffcf7a;color:#ffcf7a;font:bold 11px/16px Arial;text-align:center">${i+1}</div>`})})
    .on('dragend',e=>{const ll=e.target.getLatLng();edit.pts[i]={lat:+ll.lat.toFixed(6),lon:+ll.lng.toFixed(6)};drawEdit();renderList()}).addTo(editL))}
function edUndo(){edit.pts.pop();drawEdit();renderList()}
function edClear(){edit.pts=[];drawEdit();renderList()}
function edCancel(){edit=null;msg('');render()}
async function edSave(fly){const x=D(edit.slot);if(!edit.pts.length){msg('Click the map to add at least one stop.',false);return}
  const alt=+($('edAlt')||{}).value||edit.alt,speed=+($('edSpd')||{}).value||edit.speed;
  const route={name:(x.label+' patrol').replace(/[^\w \-]/g,'').slice(0,40),points:edit.pts,alt,speed,pause:0,loop:edit.loop,end:'home'};
  let d=await post('/api/routes?drone='+encodeURIComponent(edit.slot),route);
  if(!d.ok){msg(d.error||'Not saved.',false);return}
  if(fly){if(!await uiConfirm(`${x.label}: fly “${d.name}” now (${route.points.length} stops${route.loop?', repeating until stopped':''})? It takes off if it is on the ground. Keep it in sight.`)){edit=null;msg('Patrol route saved.',true);load();return}
    const f=await post('/api/routes/fly?drone='+encodeURIComponent(edit.slot),{name:d.name});msg(f.ok?'Saved and flying: '+f.message:'Saved, but not started: '+(f.error||''),!!f.ok)}
  else msg(`Saved as ${x.label}'s patrol route. Run patrol (top) flies it again and again.`,true);
  edit=null;load()}
async function setPatrol(on){const d=await post('/api/routes/patrol',{on});if(d.status>=300){msg(d.error||'Only operators and admins can change this.',false);$('flPatrol').checked=!on;return}
  msg(on?'Run patrol on: every drone with a patrol route flies it again and again.':'Run patrol off: patrolling drones return home.',true);load()}
async function stopAll(){if(!await uiConfirm('Stop every flying drone? They stop what they are doing and hover where they are.',{title:'Stop all',ok:'Stop all',danger:true}))return;
  const d=await post('/api/fleet/stop-all');msg(d.ok?d.message:(d.error||'Not done.'),!!d.ok);load()}
async function homeAll(){if(!await uiConfirm('Bring every flying drone home? Patrols, responses and watches end; they fly home round the no-fly zones.',{title:'Return all home',ok:'Return all home',danger:true}))return;
  const d=await post('/api/fleet/home-all');msg(d.ok?d.message:(d.error||'Not done.'),!!d.ok);load()}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(edit)edCancel();if(picking){picking=null;$('flMap').classList.remove('picking');msg('')}}});
load();setInterval(()=>{if(!dragging)load()},2000);
</script>
"""

# The Fleet card on the Dashboard: a small map with every drone and where it is going, a tile per drone, and the two
# buttons that act on all of them.
CARD = r"""
<style>
.flc-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:7px;padding:8px 10px}
.flc-t{border:1px solid #153c56;border-radius:4px;padding:6px 8px;background:#05131d;font-size:11px;color:#8fb3c7;cursor:pointer}
.flc-t b{display:block;color:#e9f8ff;font-size:12px}
.flc-lbl{background:rgba(3,16,26,.9);border:1px solid #1d6a91;color:#e9f8ff;font:bold 10px Arial;padding:1px 5px;border-radius:3px;box-shadow:none}.flc-lbl::before{display:none}
</style>
<div class="panel" style="margin-top:9px;" id="fleetCard">
<div class="panel-head"><div class="panel-title">◈ FLEET</div><div class="live" id="flcState">—</div></div>
<div id="flcMap" style="height:300px;background:#020a10"></div>
<div class="flc-tiles" id="flcTiles"></div>
<div class="grid-actions"><button type="button" class="history-action-button" onclick="location.href='/fleet'">OPEN FLEET PAGE →</button><span style="flex:1"></span>
<button type="button" class="history-action-button" style="border-color:#a3303f;color:#ff9ea8" onclick="flcAll('stop-all','Stop every flying drone? They hover where they are.')">■ STOP ALL</button>
<button type="button" class="history-action-button" style="border-color:#a3303f;color:#ff9ea8" onclick="flcAll('home-all','Bring every flying drone home? Patrols, responses and watches end.')">⌂ RETURN ALL HOME</button>
<span id="flcMsg" style="font-size:10px;color:#9edfff"></span></div>
</div>
<script>
(function(){
const COL={patrol:'#25c7ff',response:'#ff9f43',watching:'#c18bff',backup:'#ffcf7a',standby:'#ffcf7a',flying:'#e9f8ff',ready:'#26ee89',offline:'#6d8b9d'};
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const fmtM=m=>m==null?'':m>=1000?(m/1000).toFixed(1)+' km':Math.round(m)+' m';
let map=null,layer=null,fitted=false;
function leaflet(){return new Promise(ok=>{if(window.L)return ok();const css=document.createElement('link');css.rel='stylesheet';css.href='/vendor/leaflet/leaflet.css';document.head.appendChild(css);
  const js=document.createElement('script');js.src='/vendor/leaflet/leaflet.js';js.onload=ok;document.head.appendChild(js)})}
async function load(){let d;try{d=await fetch('/api/fleet',{cache:'no-store'}).then(r=>r.json())}catch(e){return}
  const card=document.getElementById('fleetCard');if(!d.drones.length&&!(d.docks||[]).length){card.style.display='none';return}card.style.display='';
  await leaflet();
  if(!map){map=L.map('flcMap',{zoomControl:false,attributionControl:false}).setView(d.centre||[20,0],d.centre?16:2);
    L.tileLayer('/tiles/sat/{z}/{x}/{y}',{maxZoom:20,maxNativeZoom:19}).addTo(map);layer=L.layerGroup().addTo(map)}
  layer.clearLayers();const pts=[];
  d.drones.forEach(x=>{const p=x.lat!=null?[x.lat,x.lon]:(x.pin?[x.pin.lat,x.pin.lon]:null);if(!p)return;pts.push(p);const c=COL[x.job]||'#e9f8ff';
    if(x.target&&x.lat!=null)L.polyline([p,[x.target.lat,x.target.lon]],{color:x.target.intruder?'#c18bff':c,weight:2.5,dashArray:'8 5'}).bindTooltip(fmtM(x.target.distance_m),{permanent:true,direction:'center',className:'flc-lbl'}).addTo(layer);
    L.marker(p,{icon:L.divIcon({className:'',iconSize:[26,26],iconAnchor:[13,13],html:x.lat!=null?`<div style="transform:rotate(${x.heading||0}deg);color:${c};font-size:22px;line-height:26px;text-align:center;text-shadow:0 0 5px #000">▲</div>`
      :`<div style="width:18px;height:18px;border-radius:50%;border:2px dashed #8fb3c7;color:#8fb3c7;font:bold 10px/14px Arial;text-align:center">✈</div>`})})
      .bindTooltip(esc(x.label),{permanent:true,direction:'right',offset:[10,0],className:'flc-lbl'}).on('click',()=>location.href='/fleet').addTo(layer)});
  (d.intruders||[]).forEach(t=>L.circleMarker([t.lat,t.lon],{radius:6,color:'#fff',weight:2,fillColor:'#e0283e',fillOpacity:1}).bindTooltip(esc(t.label),{permanent:true,direction:'top',className:'flc-lbl'}).addTo(layer));
  (d.docks||[]).forEach(k=>{if(k.lat!=null){pts.push([k.lat,k.lon]);L.circleMarker([k.lat,k.lon],{radius:6,color:k.online?'#26ee89':'#6d8b9d',weight:2,fillOpacity:.3}).bindTooltip(esc(k.name),{permanent:true,direction:'right',className:'flc-lbl'}).addTo(layer)}});
  if(!fitted&&pts.length){fitted=true;map.fitBounds(L.latLngBounds(pts).pad(0.3),{maxZoom:17})}
  const fly=d.drones.filter(x=>x.flying).length,rdy=d.drones.filter(x=>x.job==='ready').length,off=d.drones.filter(x=>x.job==='offline').length;
  document.getElementById('flcState').textContent=`${fly} FLYING · ${rdy} READY · ${off} OFFLINE`;
  document.getElementById('flcTiles').innerHTML=d.drones.map(x=>`<div class="flc-t" onclick="location.href='/fleet'"><b>${esc(x.label)}</b><span style="color:${COL[x.job]}">${esc(x.job.charAt(0).toUpperCase()+x.job.slice(1))}</span>${x.battery!=null?' · '+x.battery+'%':''}${x.target&&x.target.distance_m!=null?' · '+fmtM(x.target.distance_m):''}</div>`).join('')}
window.flcAll=async function(what,ask){if(!await uiConfirm(ask,{danger:true}))return;
  const r=await fetch('/api/fleet/'+what,{method:'POST'});const d=await r.json().catch(()=>({}));
  document.getElementById('flcMsg').textContent=d.message||d.error||(r.status===403?'Only operators and admins can do this.':'Error '+r.status);load()};
load();setInterval(load,3000)})();
</script>
"""
