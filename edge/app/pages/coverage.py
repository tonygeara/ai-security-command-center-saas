"""The Coverage page (digital twin): each camera's view on the map, the site outline, the coverage
heat map, blind spots, a suggested next camera, and "who sees this spot / send a drone here"."""
BODY = r"""
<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">
<style>
.cv-grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(330px,1fr);gap:16px;align-items:start}
@media(max-width:900px){.cv-grid{grid-template-columns:1fr}}
#cvMap{height:min(72vh,680px);border:1px solid #155879;border-radius:5px;background:#06131c}
.cv-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}
.cv-stats div{border:1px solid #155879;border-radius:5px;padding:8px;text-align:center}.cv-stats b{display:block;font-size:20px;color:#e9f8ff}
.cv-stats small{color:#6d8b9d;font-size:11px}
.cv-cam{border-top:1px solid #123447;padding:8px 0}.cv-cam b{color:#9edfff}
.cv-cam .row3{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:6px}.cv-cam input{width:100%}
.cv-legend{display:flex;gap:10px;flex-wrap:wrap;font-size:11px;color:#8fb3c6;margin-top:8px}.cv-legend i{display:inline-block;width:12px;height:12px;border-radius:2px;vertical-align:-2px;margin-right:4px}
#cvHint{color:#ffd27a;font-size:12px;min-height:16px;margin-top:6px}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Digital twin</div><h1 class="page-title">Coverage</h1>
<div class="page-sub">What each camera sees on the ground, where nobody is watching, and where one more camera would help most. Click anywhere on the map to see which cameras cover that spot, or send a drone there.</div></div></div>
<div class="cv-grid">
<section class="panel"><div class="panel-body">
<div id="cvMap"></div>
<div class="cv-legend"><span><i style="background:#ff4d6a"></i>Blind spot</span><span><i style="background:#2bc0ff"></i>1 camera</span><span><i style="background:#3cff9a"></i>2+ cameras</span><span><i style="border:2px dashed #ffd27a"></i>Suggested camera</span></div>
<div id="cvHint"></div>
<div class="muted" style="font-size:11px;margin-top:4px">Views are drawn as open ground: walls, trees and hills in the way are not taken into account.</div>
</div></section>
<div>
<section class="panel"><div class="panel-head"><div class="panel-title">◎ Site</div></div><div class="panel-body">
<div class="cv-stats"><div><b id="stBlind">–</b><small>blind spots</small></div><div><b id="stArea">–</b><small>area</small></div><div><b id="stCams">–</b><small>cameras placed</small></div></div>
<div class="actions" style="gap:8px;flex-wrap:wrap">
<button class="hud-btn" id="drawBtn" onclick="drawOutline()">Draw site outline</button>
<button class="hud-btn" onclick="clearOutline()">Clear outline</button></div>
<div class="hud-row" style="margin-top:10px"><div><b>Camera-to-drone handoff</b><div class="muted">When someone leaves a camera's view, the nearest drone flies to where they went. Same hours and cooldown as auto-send on the Drone page.</div></div><input class="toggle" type="checkbox" id="handoff" onchange="setHandoff(this)"></div>
<div id="sugBox" class="hud-msg" style="margin-top:10px"></div>
<div id="cvMsg" class="hud-msg"></div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">🗺 Smart patrol</div><div class="live" id="spState">OFF</div></div><div class="panel-body">
<div class="hud-row"><div><b>Smart patrol</b><div class="muted">The system writes its own patrol route over the blind spots and the places incidents happen, flies it every day at the riskiest hour, and rebuilds it every week.</div></div><input class="toggle" type="checkbox" id="smart_patrol" onchange="spSave()"></div>
<div class="hud-row"><div><b>Stops</b></div><input id="smart_patrol_stops" type="number" min="2" max="25" style="width:90px" onchange="spSave()"></div>
<div class="hud-row"><div><b>Height (m)</b></div><input id="smart_patrol_alt" type="number" min="10" max="120" style="width:90px" onchange="spSave()"></div>
<div class="hud-row"><div><b>Start without asking</b><div class="muted">Off (recommended): Telegram asks Start / Skip at patrol time.</div></div><input class="toggle" type="checkbox" id="smart_patrol_auto_start" onchange="spSave()"></div>
<div class="actions" style="margin-top:8px"><button class="hud-btn" onclick="spRebuild()">Rebuild now</button></div>
<div id="spInfo" class="hud-msg"></div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">▣ Cameras</div></div><div class="panel-body">
<div class="muted" style="margin-bottom:6px">Set where each camera is on the Drone page. Here, set where it looks: <b>Point</b> then click the map in the direction it faces, or type the numbers.</div>
<div id="camList"></div></div></section>
</div></div></main>
<script src="/vendor/leaflet/leaflet.js"></script><script src="/mapsearch.js"></script>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const post=(url,body)=>fetch(url,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body||{})}).then(async r=>{try{return await r.json()}catch(e){return {ok:false,error:'HTTP '+r.status}}});
function msg(id,t,ok){const e=$(id);e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t||''}
let map,heat,cones,marks,outlineLayer,sugLayer,spLayer,data=null,settings=null,mode='',draft=[],fitted=false;
function initMap(){map=L.map('cvMap',{maxZoom:22}).setView([20,0],2);
  const sat=L.tileLayer('/tiles/sat/{z}/{x}/{y}',{maxZoom:22,maxNativeZoom:19,attribution:'Imagery © Esri'}).addTo(map);
  const osm=L.tileLayer('/tiles/osm/{z}/{x}/{y}',{maxZoom:22,maxNativeZoom:19,attribution:'© OpenStreetMap'});
  L.control.layers({'Satellite':sat,'Street map':osm}).addTo(map);if(window.addMapSearch&&addMapSearch(map))fitted=true;
  heat=L.layerGroup().addTo(map);cones=L.layerGroup().addTo(map);outlineLayer=L.layerGroup().addTo(map);sugLayer=L.layerGroup().addTo(map);spLayer=L.layerGroup().addTo(map);marks=L.layerGroup().addTo(map);
  map.on('click',onClick)}
async function load(){
  const r=await fetch('/api/response/settings').then(r=>r.json());settings=r.settings;
  data=await fetch('/api/coverage').then(r=>r.json());$('handoff').checked=!!settings.handoff;draw();cams(r.cameras||[])}
async function setHandoff(el){if(el.checked&&!confirm('Handoff flies a drone with no confirmation when someone leaves a camera\'s view. Only use it when the drones and controllers stay on, the area is safe to fly and a pilot can take over. Turn it on?')){el.checked=false;return}
  const d=await post('/api/response/settings',{handoff:el.checked});msg('cvMsg',d.ok?(el.checked?'Handoff is on.':'Handoff is off.'):d.error,d.ok);if(!d.ok)el.checked=!el.checked}
function draw(){heat.clearLayers();cones.clearLayers();outlineLayer.clearLayers();sugLayer.clearLayers();marks.clearLayers();
  const out=settings.site_outline||[];
  if(out.length>=3)L.polygon(out,{color:'#ffd27a',weight:2,fill:false,dashArray:'6 4'}).addTo(outlineLayer);
  if(!data.ok){msg('cvMsg',data.error,false);$('stBlind').textContent='–';return}
  const c=document.createElement('canvas');c.width=data.nx;c.height=data.ny;const g=c.getContext('2d');
  data.grid.forEach((row,j)=>row.forEach((n,i)=>{if(n<0)return;g.fillStyle=n===0?'rgba(255,77,106,.55)':n===1?'rgba(43,192,255,.32)':'rgba(60,255,154,.36)';g.fillRect(i,data.ny-1-j,1,1)}));
  L.imageOverlay(c.toDataURL(),data.bounds,{opacity:1,interactive:false,className:'cv-heat'}).addTo(heat);
  Object.entries(data.cones).forEach(([n,p])=>{L.polygon(p,{color:'#5bd9ff',weight:1.5,fillOpacity:.06}).bindTooltip(esc(n)).addTo(cones)});
  Object.entries(settings.camera_locations||{}).forEach(([n,p])=>L.circleMarker([p.lat,p.lon],{radius:6,color:'#fff',weight:2,fillColor:'#2bc0ff',fillOpacity:1}).bindTooltip(esc(n),{permanent:true,direction:'top',offset:[0,-6],className:'cv-tip'}).addTo(marks));
  $('stBlind').textContent=data.blind_pct+'%';$('stArea').textContent=data.area_m2>=10000?(data.area_m2/10000).toFixed(2)+' ha':data.area_m2+' m²';
  $('stCams').textContent=Object.keys(data.cones).length;
  const s=data.suggestion;
  if(s){L.polygon(s.cone,{color:'#ffd27a',weight:2,dashArray:'6 4',fillOpacity:.08}).addTo(sugLayer);
    L.circleMarker([s.lat,s.lon],{radius:6,color:'#ffd27a',weight:2,fillColor:'#ffd27a',fillOpacity:.8}).bindTooltip('Suggested camera').addTo(sugLayer);
    msg('sugBox',`Suggested next camera (yellow): facing ${Math.round(s.view.heading)}°, ${s.view.fov}° wide, ${s.view.range} m. Blind spots would go from ${data.blind_pct}% to ${s.blind_pct_after}%.`,true)}
  else msg('sugBox',data.blind?'':'No blind spots inside the site.',true);
  if(!fitted){fitted=true;map.fitBounds(data.bounds,{padding:[30,30]})}}
function cams(names){const locs=settings.camera_locations||{},views=settings.camera_views||{};
  const all=[...new Set([...names.filter(n=>!/^drone/.test(n)),...Object.keys(locs)])];
  $('camList').innerHTML=all.map(n=>{const v={heading:0,fov:90,range:30,...(views[n]||{})},placed=!!locs[n];
    return `<div class="cv-cam"><b>${esc(n)}</b> ${placed?'':'<span class="muted">· not placed on the map yet</span>'}
    <div class="row3"><div><label>Facing °</label><input type="number" min="0" max="359" value="${Math.round(v.heading)}" data-cam="${esc(n)}" data-k="heading"></div>
    <div><label>Width °</label><input type="number" min="10" max="180" value="${v.fov}" data-cam="${esc(n)}" data-k="fov"></div>
    <div><label>Range m</label><input type="number" min="3" max="300" value="${v.range}" data-cam="${esc(n)}" data-k="range"></div></div>
    <div class="actions" style="margin-top:6px"><button class="hud-btn" ${placed?'':'disabled'} onclick="pointCam('${esc(n)}')">Point</button></div></div>`}).join('')||'<p class="muted">No cameras yet.</p>';
  document.querySelectorAll('#camList input').forEach(i=>i.onchange=()=>saveView(i.dataset.cam,{[i.dataset.k]:Number(i.value)}))}
async function saveView(cam,patch){const views={...(settings.camera_views||{})};views[cam]={heading:0,fov:90,range:30,...(views[cam]||{}),...patch};
  const d=await post('/api/response/settings',{camera_views:views});msg('cvMsg',d.ok?'Saved.':d.error,d.ok);load()}
function pointCam(n){mode='point:'+n;$('cvHint').textContent='CLICK THE MAP IN THE DIRECTION '+n.toUpperCase()+' FACES'}
function drawOutline(){mode='outline';draft=[];$('cvHint').textContent='CLICK THE CORNERS OF THE SITE, THEN CLICK THE FIRST CORNER (OR PRESS FINISH) TO CLOSE';$('drawBtn').textContent='Finish outline';$('drawBtn').onclick=finishOutline}
async function finishOutline(){$('drawBtn').textContent='Draw site outline';$('drawBtn').onclick=drawOutline;$('cvHint').textContent='';mode='';
  if(draft.length<3){msg('cvMsg','An outline needs at least 3 corners.',false);draft=[];draw();return}
  const d=await post('/api/response/settings',{site_outline:draft});draft=[];msg('cvMsg',d.ok?'Site outline saved.':d.error,d.ok);load()}
async function clearOutline(){const d=await post('/api/response/settings',{site_outline:[]});msg('cvMsg',d.ok?'Outline cleared: the area round the cameras is used.':d.error,d.ok);load()}
async function onClick(e){const {lat,lng}=e.latlng;
  if(mode.startsWith('point:')){const n=mode.slice(6),p=settings.camera_locations[n];mode='';$('cvHint').textContent='';
    const y=(lat-p.lat)*111320,x=(lng-p.lon)*111320*Math.cos(p.lat*Math.PI/180);saveView(n,{heading:(Math.atan2(x,y)*180/Math.PI+360)%360});return}
  if(mode==='outline'){if(draft.length>=3&&map.latLngToContainerPoint(draft[0]).distanceTo(e.containerPoint)<12){finishOutline();return}
    draft.push([lat,lng]);outlineLayer.clearLayers();L.polyline(draft,{color:'#ffd27a',dashArray:'4 4'}).addTo(outlineLayer);
    draft.forEach(q=>L.circleMarker(q,{radius:4,color:'#ffd27a'}).addTo(outlineLayer));return}
  const d=await fetch(`/api/coverage/at?lat=${lat}&lon=${lng}`).then(r=>r.json());
  const who=d.cameras.length?'Seen by '+d.cameras.map(c=>`<b>${esc(c.camera)}</b> (${Math.round(c.distance_m)} m)`).join(', '):'<b style="color:#ff8f8f">Blind spot</b>: no camera sees here';
  L.popup().setLatLng(e.latlng).setContent(`${who}<br><button class="hud-btn" style="margin-top:6px" onclick="sendHere(${lat},${lng})">Send a drone here</button><div id="sendMsg" class="muted"></div>`).openOn(map)}
async function sendHere(lat,lon){const d=await post('/api/coverage/send',{lat,lon});const m=$('sendMsg');if(m)m.textContent=d.ok?d.message:d.error}
function spShow(d){const c=d.settings,i=d.info||{};$('spState').textContent=c.smart_patrol?'ON':'OFF';
  for(const k of ['smart_patrol','smart_patrol_auto_start'])$(k).checked=!!c[k];for(const k of ['smart_patrol_stops','smart_patrol_alt'])$(k).value=c[k];
  spLayer.clearLayers();const r=i.route||[];
  if(c.smart_patrol&&r.length){L.polyline(r.map(p=>[p.lat,p.lon]),{color:'#26ee89',weight:3,dashArray:'8 6'}).addTo(spLayer);
    r.forEach((p,k)=>L.marker([p.lat,p.lon],{icon:L.divIcon({className:'',iconSize:[22,22],iconAnchor:[11,11],html:`<div style="width:22px;height:22px;border-radius:50%;background:#26ee89;color:#04131c;font:bold 12px/22px Arial;text-align:center">${k+1}</div>`})}).bindTooltip(esc(p.why)).addTo(spLayer));
    msg('spInfo',`${i.stops} stops (${i.blind_stops} blind spots, ${i.hot_stops} incident spots), every day at ${i.time}. Built ${new Date(i.built*1000).toLocaleString()} from ${i.incidents_used} incident(s).`,true)}
  else msg('spInfo',c.smart_patrol&&i.error?i.error:'',c.smart_patrol&&i.error?false:null)}
async function spLoad(){spShow(await fetch('/api/smart-patrol').then(r=>r.json()))}
async function spSave(){const body={smart_patrol:$('smart_patrol').checked,smart_patrol_auto_start:$('smart_patrol_auto_start').checked,
  smart_patrol_stops:Number($('smart_patrol_stops').value||6),smart_patrol_alt:Number($('smart_patrol_alt').value||30)};
  if(body.smart_patrol_auto_start&&!confirm('Start the Smart patrol without asking flies the drone with no confirmation at patrol time. Only use it when the drones and controllers stay on, the area is safe to fly and a pilot can take over. Turn it on?')){$('smart_patrol_auto_start').checked=false;body.smart_patrol_auto_start=false}
  msg('spInfo','Planning…');const d=await post('/api/smart-patrol',body);if(!d.ok){msg('spInfo',d.error,false);return spLoad()}spShow(d)}
async function spRebuild(){msg('spInfo','Planning…');const d=await post('/api/smart-patrol/rebuild');if(!d.ok){msg('spInfo',d.error,false);return}spLoad()}
initMap();load();spLoad();
</script>"""
