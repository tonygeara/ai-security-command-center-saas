"""The Flight Safety tab: weather limits, crewed aircraft (ADS-B), official airspace, radio coverage."""
BODY = r"""
<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">
<style>
.fs-grid{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(360px,1fr);gap:16px;align-items:start}
#fsMap{height:640px;border:1px solid #155879;border-radius:5px;background:#020a10}
.fs-verdict{padding:12px 14px;border-radius:5px;border:1px solid #1f7a50;background:rgba(18,120,70,.12);color:#7dffc1;font-weight:bold;font-size:13px}
.fs-verdict.bad{border-color:#7a2935;background:rgba(125,12,28,.16);color:#ff9ea8}
.fs-verdict.warn{border-color:#7a5a12;background:rgba(125,90,12,.14);color:#ffcf7a}
.fs-verdict small{display:block;font-weight:normal;margin-top:4px;color:#9edfff}
.fs-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}
.fs-stats div{background:#020a10;border:1px solid #153c56;border-radius:4px;padding:6px 8px}
.fs-stats small{display:block;color:#6d8b9d;font-size:9px;letter-spacing:1.5px;text-transform:uppercase}
.fs-stats b{color:#e9f8ff;font-size:14px}
.fs-row{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}
.fs-row label,.fs-row3 label{margin-top:10px}
.fs-row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:0 10px}
.fs-check{display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;font-size:12px;margin-top:10px}
.fs-list{margin-top:8px;display:flex;flex-direction:column;gap:5px;max-height:220px;overflow:auto}
.fs-item{display:flex;justify-content:space-between;gap:8px;align-items:center;background:#05131d;border:1px solid #153c56;border-radius:4px;padding:6px 9px;font-size:12px;color:#cfeeff}
.fs-item.alert{border-color:#7a2935;color:#ffb3bb}
.fs-item small{color:#6d8b9d}
.fs-item .hud-btn{min-height:26px;font-size:9px;padding:0 8px}
.fs-legend{display:flex;gap:10px;flex-wrap:wrap;font-size:11px;color:#9edfff;margin-top:8px}
.fs-legend i{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:4px;vertical-align:-2px}
.panel+.panel{margin-top:16px}
@media(max-width:1000px){.fs-grid{grid-template-columns:1fr}#fsMap{height:420px}}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Drone</div><h1 class="page-title">Flight Safety</h1>
<div class="page-sub">Checks made before every automatic flight (routes, patrols, alert responses, 3D maps) and before take-off from this PC: weather limits, crewed aircraft nearby, official airspace, and where the controller's radio reaches. The pilot stays responsible: these checks help, they don't replace looking up.</div></div>
<div class="actions"><span class="state" id="fsState"><i class="dot warn"></i>CHECKING</span></div></div>
<div class="fs-grid">
<section class="panel"><div class="panel-head"><div class="panel-title">⌖ Site</div><div class="live" id="fsHint"></div></div>
<div class="panel-body"><div id="fsMap"></div>
<div class="actions" style="margin-top:10px;flex-wrap:wrap;align-items:center">
<button class="hud-btn" onclick="pick('site')">Set site position</button><button class="hud-btn" onclick="pick('controller')">Set controller position</button>
<button class="hud-btn" onclick="clearController()">Controller = drone home</button>
<label class="fs-check" style="margin:0"><input type="checkbox" id="fsShowAc" checked onchange="drawAircraft()">Aircraft</label>
<label class="fs-check" style="margin:0"><input type="checkbox" id="fsShowRf" onchange="toggleRf()">Radio coverage</label></div>
<div class="fs-legend"><span><i style="background:#ff4d6a"></i>Your no-fly zones</span><span><i style="background:#ff9a3c"></i>Airports</span>
<span><i style="background:#b36bff"></i>Airspace</span><span><i style="border:1px dashed #8aa;background:none"></i>Authorised (off)</span>
<span><i style="background:#26ee89"></i>Good signal</span><span><i style="background:#ffd23f"></i>Weak</span><span><i style="background:#ff4d6a;opacity:.6"></i>Poor</span></div>
<div id="fsMapMsg" class="hud-msg"></div></div></section>
<div>
<section class="panel"><div class="panel-head"><div class="panel-title">✔ Can the drones fly now?</div><div class="live" id="fsSite"></div></div>
<div class="panel-body"><div id="fsVerdict" class="fs-verdict">Checking…</div></div></section>

<section class="panel"><div class="panel-head"><div class="panel-title">☁ Weather</div><div class="live" id="wxWhen"></div></div>
<div class="panel-body"><div id="wxNow" class="muted">Loading…</div>
<label class="fs-check"><input type="checkbox" class="toggle" id="wxOn"> Check the weather before flights (Open-Meteo, needs internet)</label>
<div class="fs-row3">
<div><label for="wxWind">Max wind m/s</label><input id="wxWind" type="number" min="3" max="20" step="0.5"></div>
<div><label for="wxGust">Max gusts m/s</label><input id="wxGust" type="number" min="3" max="25" step="0.5"></div>
<div><label for="wxVis">Min visibility m</label><input id="wxVis" type="number" min="0" max="10000" step="100"></div>
<div><label for="wxTmin">Min °C</label><input id="wxTmin" type="number" min="-30" max="20"></div>
<div><label for="wxTmax">Max °C</label><input id="wxTmax" type="number" min="20" max="55"></div>
<div><label for="wxMode">When outside limits</label><select id="wxMode"><option value="block">Don't fly</option><option value="warn">Fly, warn</option></select></div></div>
<label class="fs-check"><input type="checkbox" id="wxRain"> Don't fly in rain, snow or thunderstorms (most drones aren't waterproof)</label>
<label class="fs-check"><input type="checkbox" id="wxUnknown"> Don't fly when the weather is unknown (offline)</label>
<div class="muted" style="margin-top:6px">A DJI Mini-class drone handles about 10 m/s; larger drones about 12 m/s. Wind is usually stronger at flying height than on the ground.</div>
<div class="actions" style="margin-top:10px"><button class="hud-btn primary" onclick="saveWx()">Save weather limits</button></div>
<div id="wxMsg" class="hud-msg"></div></div></section>

<section class="panel"><div class="panel-head"><div class="panel-title">✈ Crewed aircraft (ADS-B)</div><div class="live" id="acWhen"></div></div>
<div class="panel-body"><div id="acNow" class="muted">Loading…</div><div class="fs-list" id="acList"></div>
<label class="fs-check"><input type="checkbox" class="toggle" id="acOn"> Watch for planes and helicopters near the site</label>
<div class="fs-row">
<div><label for="acSource">Source</label><select id="acSource" onchange="$('acUrlBox').style.display=this.value==='local'?'':'none'"><option value="online">Online (airplanes.live)</option><option value="local">My ADS-B receiver</option></select></div>
<div><label for="acAction">If one comes close while flying</label><select id="acAction"><option value="descend">Descend to 15 m and hover</option><option value="land">Land</option><option value="home">Return home</option><option value="warn">Warn only</option></select></div></div>
<div id="acUrlBox" style="display:none"><label for="acUrl">Receiver's aircraft.json address</label><input id="acUrl" placeholder="http://192.168.1.50/tar1090/data/aircraft.json"></div>
<div class="fs-row3">
<div><label for="acWatch">Show within km</label><input id="acWatch" type="number" min="1" max="50"></div>
<div><label for="acAlert">Alert within km</label><input id="acAlert" type="number" min="0.5" max="50" step="0.5"></div>
<div><label for="acAlt">Alert below ft</label><input id="acAlt" type="number" min="500" max="10000" step="100"></div></div>
<label class="fs-check"><input type="checkbox" id="acBlock"> Don't take off while an aircraft is close</label>
<label class="fs-check"><input type="checkbox" id="acUnknown"> Don't fly when there is no traffic data</label>
<div class="muted" style="margin-top:6px">Helicopters and light aircraft fly low and not all send ADS-B, so keep watching and listening. A USB ADS-B receiver (about $30, with readsb or dump1090) works without internet and sees aircraft the online service misses.</div>
<div class="actions" style="margin-top:10px"><button class="hud-btn primary" onclick="saveAc()">Save air traffic settings</button></div>
<div id="acMsg" class="hud-msg"></div></div></section>

<section class="panel"><div class="panel-head"><div class="panel-title">🛇 Official airspace</div><div class="live" id="asCount"></div></div>
<div class="panel-body"><div class="muted">Airports and heliports round the site become no-fly circles (large 8 km, medium 5 km, small 3 km, heliport 1 km: cautious defaults, check your national rules). Add controlled airspace from a GeoJSON file (openAIP or your aviation authority). Mark a zone <b>authorised</b> only if the site has permission to fly there.</div>
<div class="actions" style="margin-top:10px;align-items:center;flex-wrap:wrap"><span class="muted">Within</span><input id="asKm" type="number" min="5" max="100" style="width:70px"><span class="muted">km</span>
<button class="hud-btn primary" onclick="importAirports()">Import airports</button>
<button class="hud-btn" onclick="pickFile()">Import a file</button></div>
<div class="fs-list" id="asList"></div>
<div class="actions" style="margin-top:8px"><button class="hud-btn danger" onclick="removeSource('airport')">Remove airports</button><button class="hud-btn danger" onclick="removeSource('airspace')">Remove airspace</button></div>
<div id="asMsg" class="hud-msg"></div></div></section>

<section class="panel"><div class="panel-head"><div class="panel-title">📡 Radio coverage</div><div class="live" id="rfWhen"></div></div>
<div class="panel-body"><div class="muted">Expected controller signal round the site from the controller position, using the ground's shape (hills, not buildings or trees). Use it to choose where the pilot stands and to spot route stops behind a hill.</div>
<div class="fs-row3">
<div><label for="rfBand">Band</label><select id="rfBand"><option value="2.4">2.4 GHz</option><option value="5.8">5.8 GHz</option></select></div>
<div><label for="rfEirp">Power dBm EIRP</label><input id="rfEirp" type="number" min="0" max="36"></div>
<div><label for="rfSens">Sensitivity dBm</label><input id="rfSens" type="number" min="-120" max="-60"></div>
<div><label for="rfAlt">Drone height m</label><input id="rfAlt" type="number" min="5" max="120" value="40"></div>
<div><label for="rfH">Controller height m</label><input id="rfH" type="number" min="0.5" max="30" step="0.5"></div></div>
<div class="muted" style="margin-top:6px">20 dBm is the 2.4 GHz limit in Europe and the Middle East (CE); 5.8 GHz is often not allowed there. In the USA (FCC) DJI controllers use up to about 30 dBm.</div>
<div class="actions" style="margin-top:10px"><button class="hud-btn" onclick="saveRf()">Save</button><button class="hud-btn primary" onclick="showRf()">Show coverage</button></div>
<div id="rfMsg" class="hud-msg"></div></div></section>
</div></div>
</main>
<script src="/vendor/leaflet/leaflet.js"></script><script src="/mapsearch.js"></script>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const post=(url,body,method)=>fetch(url,{method:method||'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body||{})}).then(async r=>{try{return await r.json()}catch(e){return {ok:false,error:'HTTP '+r.status}}});
function msg(id,t,ok){const e=$(id);e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t||''}
const COLORS={airport:'#ff9a3c',airspace:'#b36bff'};
let map=null,data=null,zoneLayer=null,acLayer=null,siteLayer=null,rfLayer=null,picking='',formsFilled=false,fitted=false;
function initMap(){map=L.map('fsMap',{maxZoom:20}).setView([20,0],2);
  const sat=L.tileLayer('/tiles/sat/{z}/{x}/{y}',{maxZoom:20,maxNativeZoom:19,attribution:'Imagery © Esri'});
  const osm=L.tileLayer('/tiles/osm/{z}/{x}/{y}',{maxZoom:20,maxNativeZoom:19,attribution:'© OpenStreetMap'}).addTo(map);
  L.control.layers({'Street map':osm,'Satellite':sat}).addTo(map);window.addMapSearch&&addMapSearch(map);
  rfLayer=L.layerGroup();zoneLayer=L.layerGroup().addTo(map);acLayer=L.layerGroup().addTo(map);siteLayer=L.layerGroup().addTo(map);
  map.on('click',e=>{if(picking)setPos(picking,e.latlng.lat,e.latlng.lng)})}
function pick(what){picking=what;$('fsHint').textContent=what==='site'?'CLICK WHERE THE DRONES FLY FROM':'CLICK WHERE THE PILOT STANDS'}
async function setPos(what,lat,lon){picking='';$('fsHint').textContent='';
  const d=await post('/api/safety/settings',what==='site'?{site:{lat,lon}}:{rf:{controller:{lat,lon}}});
  msg('fsMapMsg',d.ok?(what==='site'?'Site position saved.':'Controller position saved.'):d.error,d.ok);load(true)}
async function clearController(){const d=await post('/api/safety/settings',{rf:{controller:null}});msg('fsMapMsg',d.ok?'The controller is taken to be at the drone\'s home point.':d.error,d.ok);load(true)}
function drawZones(){zoneLayer.clearLayers();(data.zones||[]).forEach(z=>{const on=z.enabled!==false,c=COLORS[z.source]||'#ff4d6a';
  L.polygon(z.points.map(p=>[p.lat,p.lon]),{color:on?c:'#8aa',weight:on?2:1,dashArray:on?null:'5 5',fillColor:c,fillOpacity:on?.18:0})
   .bindTooltip(esc(z.name)+(z.note?'<br>'+esc(z.note):'')+(on?'':'<br><b>Authorised: drones may fly here</b>')).addTo(zoneLayer)})}
function planeIcon(a,alert){return L.divIcon({className:'',iconSize:[26,26],iconAnchor:[13,13],
  html:`<div style="transform:rotate(${(a.track||0)-45}deg);font-size:20px;line-height:26px;text-align:center;color:${alert?'#ff4d6a':'#ffd23f'};text-shadow:0 0 4px #000">✈</div>`})}
function drawAircraft(){acLayer.clearLayers();if(!$('fsShowAc').checked)return;const t=data.traffic||{},th=new Set((t.threats||[]).map(a=>a.hex));
  (t.aircraft||[]).forEach(a=>L.marker([a.lat,a.lon],{icon:planeIcon(a,th.has(a.hex))}).bindTooltip(acText(a)).addTo(acLayer));
  const s=data.settings.traffic,p=(data.site||{}).pos;
  if(p&&s.enabled)L.circle(p,{radius:s.alert_km*1000,color:'#ff4d6a',weight:1,fill:false,dashArray:'3 6'}).bindTooltip('Aircraft alert radius').addTo(acLayer)}
function acText(a){const h=a.height_ft==null?'height ?':Math.round(a.height_ft/100)*100+' ft';
  return `${esc(a.call||a.hex.toUpperCase())}${a.type?' · '+esc(a.type):''} · ${(a.dist_m/1000).toFixed(1)} km · ${h}${a.speed_kt?' · '+Math.round(a.speed_kt)+' kt':''}`}
function drawSite(){siteLayer.clearLayers();const p=(data.site||{}).pos;
  if(p)L.circleMarker(p,{radius:7,color:'#fff',fillColor:'#25c7ff',fillOpacity:1,weight:2}).bindTooltip('Site ('+esc(data.site.from)+')').addTo(siteLayer);
  const c=data.settings.rf.controller;
  if(c)L.circleMarker([c.lat,c.lon],{radius:6,color:'#111',fillColor:'#26ee89',fillOpacity:1,weight:2}).bindTooltip('Controller (pilot)').addTo(siteLayer);
  if(p)L.circle(p,{radius:data.max_distance_m,color:'#25c7ff',weight:1,fill:false,dashArray:'6 6'}).bindTooltip('Drone range from home').addTo(siteLayer);
  if(p&&!fitted){fitted=true;map.setView(p,15)}}
function fmt(v,u,d){return v==null?'–':(+v).toFixed(d||0)+u}
function render(){const c=data.conditions,v=$('fsVerdict');
  if(c.problem){v.className='fs-verdict bad';v.innerHTML='⛔ Automatic flights are on hold<small>'+esc(c.problem)+'</small>'}
  else if(c.warnings.length){v.className='fs-verdict warn';v.innerHTML='⚠ Flights allowed, with warnings<small>'+c.warnings.map(esc).join('<br>')+'</small>'}
  else{v.className='fs-verdict';v.innerHTML='✔ Clear to fly<small>No weather or air traffic problem found. Check the sky yourself before take-off.</small>'}
  $('fsState').innerHTML=c.problem?'<i class="dot bad"></i>ON HOLD':c.warnings.length?'<i class="dot warn"></i>WARNINGS':'<i class="dot good"></i>CLEAR';
  $('fsSite').textContent=data.site.pos?('FROM '+data.site.from.toUpperCase()):'NO SITE POSITION';
  const w=data.weather,r=w.reading;
  if(!w.enabled)$('wxNow').textContent='Weather check is off.';
  else if(!r)$('wxNow').textContent=w.error||'No reading.';
  else{$('wxNow').innerHTML=`<div class="fs-stats"><div><small>Wind</small><b>${fmt(r.wind_ms,' m/s',1)}</b></div><div><small>Gusts</small><b>${fmt(r.gust_ms,' m/s',1)}</b></div>
    <div><small>Wind at 80 m</small><b>${fmt(r.wind_80m_ms,' m/s',1)}</b></div><div><small>Sky</small><b>${esc(r.text)}</b></div>
    <div><small>Temperature</small><b>${fmt(r.temp_c,' °C')}</b></div><div><small>Visibility</small><b>${r.visibility_m==null?'–':(r.visibility_m/1000).toFixed(1)+' km'}</b></div></div>`
    +(w.issues.length?`<div class="hud-msg bad" style="margin-top:8px">Outside limits: ${w.issues.map(esc).join('; ')}</div>`:'')+(w.error?`<div class="muted" style="margin-top:6px">${esc(w.error)} Showing the last reading.</div>`:'')}
  $('wxWhen').textContent=r&&w.at?('UPDATED '+new Date(w.at*1000).toLocaleTimeString()):'';
  const t=data.traffic,ts=data.settings.traffic;
  $('acNow').innerHTML=!ts.enabled?'Air traffic watch is off.':!t.fresh?esc(t.error||'No data.'):
    (t.threats.length?`<div class="hud-msg bad" style="margin-top:0">✈ ${t.threats.length} aircraft close and low</div>`:`${t.aircraft.length} aircraft within ${ts.watch_km} km, none close and low.`);
  const th=new Set((t.threats||[]).map(a=>a.hex));
  $('acList').innerHTML=(t.aircraft||[]).slice(0,8).map(a=>`<div class="fs-item ${th.has(a.hex)?'alert':''}"><span>✈ ${acText(a)}</span></div>`).join('')
    +((t.actions||[]).slice(-3).reverse().map(x=>`<div class="fs-item alert"><span>${new Date(x.at*1000).toLocaleTimeString()} · ${esc(x.text)}</span><small>${esc(x.action)}</small></div>`).join(''));
  $('acWhen').textContent=t.fresh?('UPDATED '+new Date(t.at*1000).toLocaleTimeString()):'';
  const imp=(data.zones||[]).filter(z=>z.source);$('asCount').textContent=imp.length+' IMPORTED';
  $('asList').innerHTML=imp.length?imp.map(z=>`<div class="fs-item"><span>${esc(z.name)}<br><small>${esc(z.note||'')}</small></span>
    <label class="fs-check" style="margin:0;white-space:nowrap"><input type="checkbox" ${z.enabled===false?'checked':''} onchange="authorise('${esc(z.id)}',this.checked)">authorised</label></div>`).join(''):'<span class="muted">Nothing imported yet.</span>';
  if(!formsFilled)fillForms();drawZones();drawAircraft();drawSite()}
function fillForms(){formsFilled=true;const s=data.settings,w=s.weather,t=s.traffic,r=s.rf;
  $('wxOn').checked=w.enabled;$('wxWind').value=w.max_wind_ms;$('wxGust').value=w.max_gust_ms;$('wxVis').value=w.min_visibility_m;$('wxTmin').value=w.min_temp_c;
  $('wxTmax').value=w.max_temp_c;$('wxMode').value=w.mode;$('wxRain').checked=w.block_precip;$('wxUnknown').checked=w.unknown==='block';
  $('acOn').checked=t.enabled;$('acSource').value=t.source;$('acUrl').value=t.url;$('acUrlBox').style.display=t.source==='local'?'':'none';$('acAction').value=t.action;
  $('acWatch').value=t.watch_km;$('acAlert').value=t.alert_km;$('acAlt').value=t.alert_alt_ft;$('acBlock').checked=t.block_takeoff;$('acUnknown').checked=t.unknown==='block';
  $('rfBand').value=r.band;$('rfEirp').value=r.eirp_dbm;$('rfSens').value=r.sensitivity_dbm;$('rfH').value=r.controller_height_m;$('asKm').value=s.airports.within_km}
async function load(refill){try{const d=await fetch('/api/safety',{cache:'no-store'}).then(r=>r.json());if(!d.ok)return;data=d;if(refill)formsFilled=false;render()}catch(e){}}
async function saveWx(){const d=await post('/api/safety/settings',{weather:{enabled:$('wxOn').checked,max_wind_ms:+$('wxWind').value,max_gust_ms:+$('wxGust').value,
  min_visibility_m:+$('wxVis').value,min_temp_c:+$('wxTmin').value,max_temp_c:+$('wxTmax').value,mode:$('wxMode').value,block_precip:$('wxRain').checked,unknown:$('wxUnknown').checked?'block':'allow'}});
  msg('wxMsg',d.ok?'Weather limits saved.':d.error,d.ok);load(true)}
async function saveAc(){const d=await post('/api/safety/settings',{traffic:{enabled:$('acOn').checked,source:$('acSource').value,url:$('acUrl').value.trim(),action:$('acAction').value,
  watch_km:+$('acWatch').value,alert_km:+$('acAlert').value,alert_alt_ft:+$('acAlt').value,block_takeoff:$('acBlock').checked,unknown:$('acUnknown').checked?'block':'allow'}});
  msg('acMsg',d.ok?'Air traffic settings saved.':d.error,d.ok);load(true)}
async function saveRf(){const d=await post('/api/safety/settings',{rf:{band:$('rfBand').value,eirp_dbm:+$('rfEirp').value,sensitivity_dbm:+$('rfSens').value,controller_height_m:+$('rfH').value}});
  msg('rfMsg',d.ok?'Radio settings saved.':d.error,d.ok);if(d.ok&&$('fsShowRf').checked)showRf()}
async function importAirports(){msg('asMsg','Importing airports… (the first time downloads the world list, about 12 MB)');
  const d=await post('/api/airspace/airports',{within_km:+$('asKm').value});msg('asMsg',d.ok?d.message:d.error,d.ok);load()}
function pickFile(){const f=document.createElement('input');f.type='file';f.accept='.geojson,.json,.csv';f.onchange=async()=>{const fd=new FormData();fd.append('file',f.files[0]);
  msg('asMsg','Importing '+f.files[0].name+'…');const d=await fetch('/api/airspace/upload',{method:'POST',body:fd}).then(r=>r.json()).catch(()=>({ok:false,error:'Upload failed.'}));
  msg('asMsg',d.ok?d.message:d.error,d.ok);load()};f.click()}
async function authorise(id,on){if(on&&!confirm('Mark this zone authorised? Drones will fly in it. Only do this if the site has permission from the aviation authority.')){load();return}
  const d=await post('/api/airspace/zone',{id,enabled:!on});msg('asMsg',d.ok?(on?'Marked authorised: drones may fly there.':'Zone active again.'):d.error,d.ok);load()}
async function removeSource(src){if(!confirm('Remove all imported '+(src==='airport'?'airport':'airspace')+' zones?'))return;
  const d=await post('/api/airspace/zone',{source:src},'DELETE');msg('asMsg',d.ok?'Removed.':d.error,d.ok);load()}
function toggleRf(){if($('fsShowRf').checked)showRf();else map.removeLayer(rfLayer)}
async function showRf(){msg('rfMsg','Working out the coverage…');$('fsShowRf').checked=true;
  const d=await fetch('/api/rf/coverage?alt='+(+$('rfAlt').value||40)).then(r=>r.json()).catch(()=>({ok:false,error:'Failed.'}));
  if(!d.ok){msg('rfMsg',d.error,false);return}
  rfLayer.clearLayers();const half=d.cell_m/2,col={good:'#26ee89',weak:'#ffd23f',poor:'#ff4d6a'};
  d.results.forEach(r=>{const dl=half/110540,dn=half/(111320*Math.cos(r.lat*Math.PI/180));
    L.rectangle([[r.lat-dl,r.lon-dn],[r.lat+dl,r.lon+dn]],{stroke:false,fillColor:col[r.quality],fillOpacity:.32})
     .bindTooltip(`${r.quality} · ${r.margin_db>0?'+':''}${r.margin_db} dB margin · ${r.dist_m} m${r.line_of_sight?'':' · terrain in the way'}`).addTo(rfLayer)});
  rfLayer.addTo(map);const poor=d.results.filter(r=>r.quality!=='good').length;
  msg('rfMsg',`${d.results.length} points at ${d.alt} m: ${poor?poor+' weak or poor':'all good'}.`+(d.terrain?'':' Terrain unknown (offline): open ground assumed, so hills are not taken into account.'),poor?false:true)}
if(typeof L!=='undefined')initMap();load();setInterval(load,10000);
</script>
"""
