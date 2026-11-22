"""The Satellite tab: named pins over NASA satellite imagery (GIBS), with a date slider, a view per pin
(true colour, fires, clouds) and optional NASA FIRMS fire alerts near the pins."""
BODY = r"""
<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">
<style>
.sat-grid{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(320px,1fr);gap:16px;align-items:start}
#satMap{height:calc(100vh - 230px);min-height:440px;border:1px solid #155879;border-radius:5px;background:#020a10}
#satMap.adding{cursor:crosshair}
.sat-bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
.sat-seg{display:inline-flex;border:1px solid #155879;border-radius:4px;overflow:hidden}
.sat-seg button{background:#05131d;color:#9edfff;border:0;border-right:1px solid #155879;padding:8px 12px;font:bold 10px Arial;letter-spacing:1px;text-transform:uppercase;cursor:pointer}
.sat-seg button:last-child{border-right:0}
.sat-seg button.on{background:#25c7ff;color:#02131d}
.sat-date{display:flex;align-items:center;gap:10px;flex:1;min-width:260px}
.sat-date input[type=range]{flex:1}
.sat-date b{color:#fff;font-variant-numeric:tabular-nums;white-space:nowrap}
.sat-pin{display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid #153c56;border-radius:4px;background:#05131d;margin-bottom:6px;cursor:pointer}
.sat-pin.on{border-color:#5bd9ff;box-shadow:0 0 0 1px #5bd9ff inset}
.sat-pin div{flex:1;min-width:0}.sat-pin b{color:#e9f8ff}.sat-pin small{display:block;color:#6d8b9d;font-size:11px}
.sat-pin .fire{color:#ffb23c;font:bold 11px Arial;white-space:nowrap}
.sat-pin button{background:none;border:1px solid #155879;color:#9edfff;border-radius:3px;padding:3px 7px;cursor:pointer;font:11px Arial}
.sat-pin button:hover{border-color:#36cfff;color:#fff}
.sat-mark{width:24px;height:24px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);background:#25c7ff;border:2px solid #fff;box-shadow:0 0 8px rgba(0,0,0,.6)}
.sat-mark.on{background:#ffd23f}
.sat-label{background:rgba(3,16,26,.9);border:1px solid #155879;color:#e9f8ff;font:bold 11px Arial;padding:2px 6px;border-radius:3px;white-space:nowrap}
.sat-fire{width:10px;height:10px;border-radius:50%;background:#ff5a1f;border:1px solid #ffd23f;box-shadow:0 0 8px #ff5a1f}
.sat-note{font-size:12px;color:#8ba9b8;margin-top:8px;line-height:1.5}
@media(max-width:1000px){.sat-grid{grid-template-columns:1fr}#satMap{height:60vh}}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Satellite</div><h1 class="page-title">Satellite view</h1>
<div class="page-sub">NASA satellite pictures of your places, one a day (VIIRS or MODIS): close to real time, not live, usually 3–24 hours behind. Pick a pin, a day and a view.</div></div>
<div class="actions"><span class="state" id="satState"><i class="dot warn"></i>LOADING</span></div></div>
<div class="sat-grid">
<section class="panel"><div class="panel-body">
<div class="sat-bar">
<span class="sat-seg" id="satLayer"><button data-v="truecolor">True colour</button><button data-v="fires">Fires</button><button data-v="clouds">Clouds</button></span>
<span class="sat-seg" id="satSat"><button data-v="viirs" title="NOAA-20 VIIRS, afternoon pass">VIIRS</button><button data-v="modis" title="Terra MODIS, morning pass">MODIS</button></span>
<label class="sat-date"><span class="muted">Day</span><input type="range" id="satDays" min="0" max="30" step="1" value="1"><b id="satDate">–</b></label>
</div>
<div id="satMap"></div>
<div class="sat-note">Imagery: NASA GIBS / Worldview (free). Fires: VIIRS thermal anomalies seen that day. Clouds: cloud-top temperature (daytime, MODIS Terra). Zooming past the satellite's detail (about 250–500 m) only enlarges the picture.</div>
</div></section>
<div>
<section class="panel"><div class="panel-head"><div class="panel-title">📍 Pins</div><div class="live" id="pinCount"></div></div><div class="panel-body">
<div class="actions" style="margin-bottom:10px"><button class="hud-btn primary" id="addBtn" onclick="startAdd()">＋ Add pin</button><span class="muted" id="addHint" style="display:none">Click the map where the pin goes (Esc cancels).</span></div>
<div id="pinList"></div>
<div id="pinMsg" class="hud-msg"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">🔥 Fire alerts</div><div class="live" id="fireState"></div></div><div class="panel-body">
<div class="muted" id="fireInfo">Fires seen by the NOAA-20 satellite within 50 km of each pin, from NASA FIRMS.</div>
<label style="margin-top:10px;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0">Last <select id="fireDays" onchange="loadFires()"><option value="1">24 hours</option><option value="2">2 days</option><option value="3">3 days</option><option value="5">5 days</option></select></label>
<div id="fireList" style="margin-top:8px"></div>
<details id="keyBox" style="margin-top:12px"><summary style="cursor:pointer;color:#5bd9ff;font:bold 12px Arial">FIRMS key (admins)</summary>
<div class="muted" style="margin:8px 0">Fire alerts need a free NASA FIRMS <b>MAP_KEY</b>: request one at firms.modaps.eosdis.nasa.gov/api/map_key with an email address. It is kept on this PC only.</div>
<div class="actions"><input id="keyIn" placeholder="MAP_KEY" autocomplete="off" style="flex:1;min-width:160px"><button class="hud-btn" onclick="saveKey()">Save key</button><button class="hud-btn danger" onclick="clearKey()">Remove</button></div>
<div id="keyMsg" class="hud-msg"></div></details>
</div></section>
</div></div>
</main>
<script src="/vendor/leaflet/leaflet.js"></script><script src="/mapsearch.js"></script>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const GIBS='https://gibs.earthdata.nasa.gov';
const TRUE={viirs:['VIIRS_NOAA20_CorrectedReflectance_TrueColor','GoogleMapsCompatible_Level9','jpg',9],
            modis:['MODIS_Terra_CorrectedReflectance_TrueColor','GoogleMapsCompatible_Level9','jpg',9]};
const CLOUDS=['MODIS_Terra_Cloud_Top_Temp_Day','GoogleMapsCompatible_Level6','png',6];
let pins=[],sel=null,adding=false,marks={},fireMarks=[],fires={},keySet=false,saving=null;
const view={layer:'truecolor',sat:'viirs',days_ago:1};

function dayStr(daysAgo){const d=new Date(Date.now()-daysAgo*86400000);return d.toISOString().slice(0,10)}
function wmts(def,date,opts){return L.tileLayer(`${GIBS}/wmts/epsg3857/best/${def[0]}/default/${date}/${def[1]}/{z}/{y}/{x}.${def[2]}`,
  Object.assign({maxNativeZoom:def[3],maxZoom:14,bounds:[[-85,-180],[85,180]],attribution:'NASA GIBS'},opts||{}))}

const map=L.map('satMap',{worldCopyJump:true,minZoom:2,maxZoom:14}).setView([33.9,35.5],7);
let base=null,overlay=null;
function draw(){
  const date=dayStr(view.days_ago);
  $('satDate').textContent=date+(view.days_ago===0?' (today, may be incomplete)':view.days_ago===1?' (yesterday)':` (${view.days_ago} days ago)`);
  if(base)map.removeLayer(base);if(overlay)map.removeLayer(overlay);overlay=null;
  base=wmts(TRUE[view.sat],date).addTo(map);
  if(view.layer==='clouds')overlay=wmts(CLOUDS,date,{opacity:.65}).addTo(map);
  if(view.layer==='fires')overlay=L.tileLayer.wms(`${GIBS}/wms/epsg3857/best/wms.cgi`,{layers:'VIIRS_NOAA20_Thermal_Anomalies_375m_All',
    format:'image/png',transparent:true,version:'1.1.1',time:date,maxZoom:14,attribution:'NASA FIRMS'}).addTo(map);
  document.querySelectorAll('#satLayer button').forEach(b=>b.classList.toggle('on',b.dataset.v===view.layer));
  document.querySelectorAll('#satSat button').forEach(b=>b.classList.toggle('on',b.dataset.v===view.sat));
  $('satDays').value=view.days_ago;
}
// A pin keeps its own view (layer, satellite, day): changing them while a pin is picked saves them on that pin.
function setView(k,v){view[k]=v;draw();const p=pins.find(x=>x.id===sel);if(p&&p[k]!==v){p[k]=v;savePins()}}
document.querySelectorAll('#satLayer button').forEach(b=>b.onclick=()=>setView('layer',b.dataset.v));
document.querySelectorAll('#satSat button').forEach(b=>b.onclick=()=>setView('sat',b.dataset.v));
$('satDays').oninput=e=>{view.days_ago=+e.target.value;draw()};
$('satDays').onchange=e=>setView('days_ago',+e.target.value);

function msg(t,ok){const e=$('pinMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t||''}
function icon(on){return L.divIcon({className:'',iconSize:[24,24],iconAnchor:[12,24],html:`<div class="sat-mark${on?' on':''}"></div>`})}
function renderPins(){
  $('pinCount').textContent=pins.length+' PIN'+(pins.length===1?'':'S');
  $('pinList').innerHTML=pins.length?pins.map(p=>{const n=(fires[p.id]||[]).length;
    return `<div class="sat-pin${p.id===sel?' on':''}" data-id="${p.id}"><div><b>${esc(p.name)}</b><small>${p.lat.toFixed(4)}, ${p.lon.toFixed(4)} · ${({truecolor:'True colour',fires:'Fires',clouds:'Clouds'})[p.layer]} · ${p.sat.toUpperCase()} · ${p.days_ago?p.days_ago+' d ago':'today'}</small></div>`
      +(keySet?`<span class="fire" title="Fires within 50 km">${n?'🔥 '+n:''}</span>`:'')
      +`<button data-act="ren" title="Rename">✎</button><button data-act="del" title="Delete">✕</button></div>`}).join('')
    :'<div class="muted">No pins yet. Press <b>＋ Add pin</b> and click the map, or search a place first (top left of the map).</div>';
  document.querySelectorAll('.sat-pin').forEach(el=>el.onclick=e=>{const id=el.dataset.id,act=e.target.dataset.act;
    if(act==='del')return delPin(id);if(act==='ren')return renPin(id);pick(id)});
  Object.values(marks).forEach(m=>map.removeLayer(m));marks={};
  pins.forEach(p=>{marks[p.id]=L.marker([p.lat,p.lon],{icon:icon(p.id===sel),draggable:true,title:p.name}).addTo(map)
    .bindTooltip(esc(p.name),{permanent:true,direction:'top',offset:[0,-24],className:'sat-label'})
    .on('click',()=>pick(p.id)).on('dragend',e=>{const ll=e.target.getLatLng();p.lat=+ll.lat.toFixed(6);p.lon=+ll.lng.toFixed(6);savePins('Moved.');loadFires()})});
}
function pick(id){const p=pins.find(x=>x.id===id);if(!p)return;sel=id;Object.assign(view,{layer:p.layer,sat:p.sat,days_ago:p.days_ago});draw();
  map.setView([p.lat,p.lon],Math.max(map.getZoom(),8));renderPins();renderFires()}
async function savePins(okText){clearTimeout(saving);saving=setTimeout(async()=>{
  const d=await fetch('/api/satellite/pins',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({pins})}).then(r=>r.json()).catch(()=>({ok:false,error:'No answer from the PC.'}));
  if(d.ok){pins=d.pins;if(okText)msg(okText,true)}else msg(d.error||'Not saved.',false);renderPins()},300)}
function startAdd(){adding=!adding;$('satMap').classList.toggle('adding',adding);$('addHint').style.display=adding?'':'none';$('addBtn').textContent=adding?'Cancel':'＋ Add pin'}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&adding)startAdd()});
map.on('click',async e=>{if(!adding)return;startAdd();
  const name=await uiPrompt('Name for this pin:','Pin '+(pins.length+1));if(!name||!name.trim())return;
  const id=[...crypto.getRandomValues(new Uint8Array(6))].map(b=>b.toString(16).padStart(2,'0')).join('');
  pins.push({id,name:name.trim(),lat:+e.latlng.lat.toFixed(6),lon:+e.latlng.lng.toFixed(6),layer:view.layer,sat:view.sat,days_ago:view.days_ago});
  pick(id);savePins('Pin added.');setTimeout(loadFires,1500)});
async function renPin(id){const p=pins.find(x=>x.id===id);const n=await uiPrompt('New name for this pin:',p.name);if(!n||!n.trim())return;p.name=n.trim();savePins('Renamed.')}
async function delPin(id){const p=pins.find(x=>x.id===id);if(!await uiConfirm('Delete pin “'+p.name+'”?'))return;pins=pins.filter(x=>x.id!==id);if(sel===id)sel=null;savePins('Deleted.');renderFires()}

function renderFires(){fireMarks.forEach(m=>map.removeLayer(m));fireMarks=[];
  const list=pins.map(p=>({p,f:fires[p.id]||[]}));
  list.forEach(({f})=>f.forEach(x=>fireMarks.push(L.marker([x.lat,x.lon],{icon:L.divIcon({className:'',iconSize:[10,10],html:'<div class="sat-fire"></div>'})})
    .bindTooltip(`Fire ${x.date} ${String(x.time).padStart(4,'0').replace(/(..)(..)/,'$1:$2')} UTC · ${x.km} km · confidence ${esc(x.confidence)} · ${x.frp} MW`).addTo(map))));
  if(!keySet){$('fireList').innerHTML='<div class="muted">Add a FIRMS key below to see fire alerts near your pins.</div>';return}
  $('fireList').innerHTML=pins.length?list.map(({p,f})=>`<div class="hud-row"><div><b>${esc(p.name)}</b><div class="muted">${f.length?`${f.length} fire${f.length>1?'s':''}, closest ${f[0].km} km (${esc(f[0].date)})`:'No fires within 50 km'}</div></div>${f.length?'<span style="color:#ffb23c;font-weight:bold">🔥 '+f.length+'</span>':''}</div>`).join(''):'<div class="muted">No pins yet.</div>'}
async function loadFires(){let d;try{d=await fetch('/api/satellite/fires?days='+$('fireDays').value,{cache:'no-store'}).then(r=>r.json())}catch(e){return}
  keySet=!!d.key_set;fires=d.fires||{};const n=Object.values(fires).reduce((a,f)=>a+f.length,0);
  $('fireState').textContent=!keySet?'NO KEY':d.error?'ERROR':n?n+' NEAR PINS':'NONE NEAR PINS';
  $('fireInfo').textContent=d.error||'Fires seen by the NOAA-20 satellite within 50 km of each pin, from NASA FIRMS (checked every 10 minutes).';
  $('fireInfo').className=d.error?'hud-msg bad':'muted';renderFires();renderPins()}
async function keyPost(key){const r=await fetch('/api/satellite/firms-key',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({key})});
  const d=await r.json().catch(()=>({ok:false}));if(r.status===403)d.error='Only an admin can change the FIRMS key.';
  const e=$('keyMsg');e.className='hud-msg '+(d.ok?'ok':'bad');e.textContent=d.ok?(key?'Key saved.':'Key removed.'):(d.error||'Not saved.');if(d.ok){$('keyIn').value='';loadFires()}}
function saveKey(){const k=$('keyIn').value.trim();if(!k){$('keyMsg').className='hud-msg bad';$('keyMsg').textContent='Paste the MAP_KEY first.';return}keyPost(k)}
async function clearKey(){if(await uiConfirm('Remove the FIRMS key? Fire alerts stop until a key is added again.'))keyPost('')}

async function load(){let d;try{d=await fetch('/api/satellite/pins',{cache:'no-store'}).then(r=>r.json())}catch(e){d={ok:false}}
  pins=d.pins||[];$('satState').innerHTML='<i class="dot '+(d.ok?'good':'bad')+'"></i>'+(d.ok?'NASA GIBS':'PC NOT ANSWERING');
  draw();renderPins();
  if(pins.length){map.fitBounds(pins.map(p=>[p.lat,p.lon]),{padding:[60,60],maxZoom:8});pick(pins[0].id)}
  else{const f=window.mapFocus&&mapFocus.get();if(f)map.setView([f.lat,f.lon],8);else if(d.centre)map.setView(d.centre,8)}
  if(window.addMapSearch)addMapSearch(map);
  loadFires();setInterval(loadFires,10*60*1000)}
load();
</script>"""
