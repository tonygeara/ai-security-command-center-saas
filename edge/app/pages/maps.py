"""The 3D Maps tab: draw an area, fly the drone over it, process the images into a 3D model and orthophoto."""
BODY = r"""
<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">
<style>
.mp-grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(340px,1fr);gap:16px;align-items:start}
#mpMap{height:560px;border:1px solid #155879;border-radius:5px;background:#020a10}
.mp-row{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}
.mp-row label{margin-top:10px}
.mp-plan{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:12px}
.mp-plan div{background:#020a10;border:1px solid #153c56;border-radius:4px;padding:6px 8px}
.mp-plan small{display:block;color:#6d8b9d;font-size:9px;letter-spacing:1.5px;text-transform:uppercase}
.mp-plan b{color:#e9f8ff;font-size:14px}
.mp-card{border:1px solid #155879;border-radius:5px;background:#05131d;padding:12px;margin-bottom:10px}
.mp-card.sel{border-color:#5bd9ff;box-shadow:0 0 0 1px #5bd9ff inset}
.mp-card h3{margin:0 0 4px;font-size:14px;color:#e9f8ff;letter-spacing:.5px;display:flex;justify-content:space-between;gap:8px;align-items:center;cursor:pointer}
.mp-chip{font-size:10px;border:1px solid #155879;border-radius:3px;padding:2px 6px;letter-spacing:1px;text-transform:uppercase;color:#9edfff;white-space:nowrap}
.mp-chip.ready{color:#7dffc1;border-color:#1f7a50}.mp-chip.failed,.mp-chip.canceled{color:#ff9ea8;border-color:#7a2935}
.mp-chip.flying,.mp-chip.processing,.mp-chip.uploading,.mp-chip.starting,.mp-chip.queued,.mp-chip.downloading{color:#ffcf7a;border-color:#7a5a12}
.mp-bar{height:5px;background:#020a10;border:1px solid #153c56;border-radius:3px;margin:8px 0;overflow:hidden}
.mp-bar i{display:block;height:100%;background:#25c7ff;width:0;transition:width .5s}
.mp-card .actions{flex-wrap:wrap;gap:6px;margin-top:8px}
.mp-card .hud-btn{min-height:30px;font-size:10px;padding:0 10px}
.mp-card select{width:auto;min-width:110px;padding:4px 6px;font-size:12px}
.mp-check{display:flex;gap:8px;align-items:flex-start;text-transform:none;letter-spacing:0;font-size:12px;margin-top:12px}
.mp-check input{margin-top:2px}
@media(max-width:1000px){.mp-grid{grid-template-columns:1fr}#mpMap{height:420px}}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Drone</div><h1 class="page-title">3D Site Maps</h1>
<div class="page-sub">Draw an area, and the drone flies a grid over it with the camera pointing down. The images are turned into a 3D model you can walk around and measure, and an up-to-date aerial map of the site.</div></div>
<div class="actions"><span class="state" id="mpEngineState"><i class="dot warn"></i>ENGINE: CHECKING</span></div></div>
<div class="mp-grid">
<section class="panel"><div class="panel-head"><div class="panel-title">⌖ Map</div><div class="live" id="mpHint">PRESS “DRAW AREA”, THEN CLICK THE CORNERS</div></div>
<div class="panel-body"><div id="mpMap"></div>
<div class="actions" style="margin-top:10px;align-items:center;flex-wrap:wrap">
<button class="hud-btn primary" id="mpDrawBtn" onclick="startDraw()">＋ Draw area</button>
<button class="hud-btn" onclick="undoCorner()">Undo corner</button><button class="hud-btn" onclick="clearDraw()">Clear</button>
<label class="mp-check" style="margin:0"><input type="checkbox" id="mpOrtho" checked onchange="showSelected()">Show the finished aerial map</label></div>
</div></section>
<div>
<section class="panel"><div class="panel-head"><div class="panel-title">＋ New map</div><div class="live" id="mpCorners">0 CORNERS</div></div>
<div class="panel-body">
<label for="mpName">Name</label><input id="mpName" placeholder="e.g. Warehouse perimeter">
<div class="mp-row">
<div><label for="mpAlt">Height (m)</label><input id="mpAlt" type="number" min="15" max="120" value="40" onchange="replan()"></div>
<div><label for="mpQuality">Quality</label><select id="mpQuality"><option value="fast">Fast (preview)</option><option value="balanced" selected>Balanced</option><option value="high">High (slow)</option></select></div>
<div><label for="mpOverlap">Forward overlap</label><select id="mpOverlap" onchange="replan()"><option value="0.7">70%</option><option value="0.75" selected>75%</option><option value="0.8">80%</option><option value="0.85">85% (buildings)</option></select></div>
<div><label for="mpSidelap">Side overlap</label><select id="mpSidelap" onchange="replan()"><option value="0.65">65%</option><option value="0.7" selected>70%</option><option value="0.75">75%</option><option value="0.8">80% (buildings)</option></select></div>
</div>
<label class="mp-check"><input type="checkbox" id="mpPhotos" onchange="replan()"><span>Also take full-resolution photos on the drone's SD card (much sharper 3D model: import them here after landing). Flies a little slower.</span></label>
<div class="mp-plan" id="mpPlan"></div>
<div id="mpPlanMsg" class="hud-msg"></div>
<div class="actions" style="margin-top:12px"><button class="hud-btn primary" id="mpSaveBtn" onclick="saveMap()" disabled>Save map</button></div>
</div></section>
<section class="panel" style="margin-top:16px"><div class="panel-head"><div class="panel-title">▦ Maps</div><div class="live" id="mpCount"></div></div>
<div class="panel-body"><div id="mpList"><p class="muted">Loading…</p></div><div id="mpMsg" class="hud-msg"></div></div></section>
<section class="panel" style="margin-top:16px"><div class="panel-head"><div class="panel-title">⚙ Mapping engine</div></div>
<div class="panel-body"><div class="muted" id="mpEngineText">Checking…</div>
<label for="mpEngineUrl">Engine address (leave empty for this PC)</label>
<div class="actions"><input id="mpEngineUrl" placeholder="http://127.0.0.1:3000" style="flex:1"><button class="hud-btn" onclick="saveEngine()">Save</button>
<button class="hud-btn primary" id="mpEngineStart" onclick="startEngine()">Start engine</button></div>
<div class="muted" style="margin-top:8px">The engine is OpenDroneMap, running in Docker on this PC. It starts by itself when you process a map. The first start downloads it (several GB), and a map takes 10–60 minutes using all CPU cores. For big sites, run it on a stronger computer and enter its address here.</div>
</div></section>
</div></div>
</main>
<script src="/vendor/leaflet/leaflet.js"></script><script src="/mapsearch.js"></script>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const post=(url,body)=>fetch(url,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body||{})}).then(async r=>{try{return await r.json()}catch(e){return {ok:false,error:'HTTP '+r.status}}});
const STATUS={planned:'Planned',flying:'Flying',captured:'Images ready',queued:'Queued',starting:'Starting engine',uploading:'Uploading',
  processing:'Processing',downloading:'Downloading',ready:'Ready',failed:'Failed',canceled:'Cancelled'};
const BUSY=['queued','starting','uploading','processing','downloading'];
let map=null,drawing=false,corners=[],drawLayer=null,planLayer=null,selLayer=null,orthoLayer=null,plan=null,data={maps:[],drones:[]},sel=null,planTimer=null,centred=false;
function msg(id,t,ok){const e=$(id);e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t||''}
function initMap(){map=L.map('mpMap',{maxZoom:22}).setView([20,0],2);
  const sat=L.tileLayer('/tiles/sat/{z}/{x}/{y}',{maxZoom:22,maxNativeZoom:19,attribution:'Imagery © Esri'}).addTo(map);
  const osm=L.tileLayer('/tiles/osm/{z}/{x}/{y}',{maxZoom:22,maxNativeZoom:19,attribution:'© OpenStreetMap'});
  L.control.layers({'Satellite':sat,'Street map':osm}).addTo(map);if(window.addMapSearch&&addMapSearch(map))centred=true;
  drawLayer=L.layerGroup().addTo(map);planLayer=L.layerGroup().addTo(map);selLayer=L.layerGroup().addTo(map);
  map.on('click',e=>{if(!drawing)return;corners.push([e.latlng.lat,e.latlng.lng]);drawArea();replan()});
  fetch('/api/drone/links').then(r=>r.json()).then(d=>{const t=(d.drones||[]).find(x=>x.lat);if(t&&!centred){centred=true;map.setView([t.lat,t.lon],17)}}).catch(()=>{})}
function startDraw(){drawing=true;corners=[];drawArea();replan();$('mpHint').textContent='CLICK THE CORNERS OF THE AREA TO MAP';$('mpDrawBtn').textContent='Drawing…'}
function undoCorner(){corners.pop();drawArea();replan()}
function clearDraw(){drawing=false;corners=[];plan=null;drawArea();planLayer.clearLayers();$('mpPlan').innerHTML='';msg('mpPlanMsg','');$('mpSaveBtn').disabled=true;
  $('mpDrawBtn').textContent='＋ Draw area';$('mpHint').textContent='PRESS “DRAW AREA”, THEN CLICK THE CORNERS'}
function drawArea(){drawLayer.clearLayers();$('mpCorners').textContent=corners.length+' CORNER'+(corners.length===1?'':'S');
  if(corners.length>=3)L.polygon(corners,{color:'#25c7ff',weight:2,fillOpacity:.12}).addTo(drawLayer);
  else if(corners.length)L.polyline(corners,{color:'#25c7ff',weight:2}).addTo(drawLayer);
  corners.forEach(c=>L.circleMarker(c,{radius:4,color:'#fff',fillColor:'#25c7ff',fillOpacity:1,weight:1}).addTo(drawLayer))}
function settings(){return {alt:+$('mpAlt').value||40,overlap:+$('mpOverlap').value,sidelap:+$('mpSidelap').value,photos:$('mpPhotos').checked}}
function replan(){clearTimeout(planTimer);planTimer=setTimeout(doPlan,250)}
async function doPlan(){planLayer.clearLayers();plan=null;$('mpSaveBtn').disabled=true;
  if(corners.length<3){$('mpPlan').innerHTML='';msg('mpPlanMsg',corners.length?'Click at least 3 corners.':'');return}
  const d=await post('/api/maps/plan',{area:corners.map(c=>({lat:c[0],lon:c[1]})),...settings()});
  if(!d.ok){$('mpPlan').innerHTML='';msg('mpPlanMsg',d.error,false);return}
  plan=d.plan;$('mpSaveBtn').disabled=false;
  L.polyline(plan.points.map(p=>[p.lat,p.lon]),{color:'#ffcf7a',weight:1.5,dashArray:'4 4'}).addTo(planLayer);
  const ha=plan.area_m2/10000;
  $('mpPlan').innerHTML=[['Area',ha>=1?ha.toFixed(2)+' ha':plan.area_m2+' m²'],['Flight lines',plan.lines],['Images',plan.images],
    ['Flight time','~'+plan.minutes+' min'],['Speed',plan.speed+' m/s'],['Detail','~'+plan.gsd_cm+' cm/px']]
    .map(([k,v])=>`<div><small>${k}</small><b>${esc(v)}</b></div>`).join('');
  msg('mpPlanMsg',d.warning||'',d.warning?false:undefined)}
async function saveMap(){if(!plan)return;const d=await post('/api/maps',{name:$('mpName').value,area:corners.map(c=>({lat:c[0],lon:c[1]})),quality:$('mpQuality').value,...settings()});
  if(!d.ok){msg('mpPlanMsg',d.error,false);return}
  clearDraw();$('mpName').value='';sel=d.map.id;msg('mpMsg','Map saved. Choose a drone and press Fly.',true);load()}
function droneOptions(){const ds=data.drones||[];return ds.map(d=>`<option value="${esc(d.slot)}">${esc(d.label)}</option>`).join('')}
function card(m){const busy=BUSY.includes(m.status),flying=m.status==='flying',ready=m.status==='ready',r=m.result||{};
  const images=(m.frames||0)+(m.photos||0);
  const bar=(busy||flying)?`<div class="mp-bar"><i style="width:${flying?Math.min(100,images/Math.max(1,m.plan.images)*100):(m.progress||0)}%"></i></div>`:'';
  const fly=!busy&&!flying&&data.allowed&&(data.drones||[]).length?`<select id="dr_${m.id}">${droneOptions()}</select><button class="hud-btn primary" onclick="fly('${m.id}')">${images?'Fly again':'Fly'}</button>`:'';
  return `<div class="mp-card${sel===m.id?' sel':''}"><h3 onclick="select('${m.id}')"><span>${esc(m.name)}</span><span class="mp-chip ${m.status}">${STATUS[m.status]||m.status}</span></h3>
  <div class="muted">${(m.plan.area_m2/10000).toFixed(2)} ha · ${m.settings.alt} m · ${m.frames||0} video frames · ${m.photos||0} photos</div>
  <div style="margin-top:6px;font-size:12px;color:#9edfff">${esc(m.message||'')}</div>${bar}
  <div class="actions">${fly}${flying?`<button class="hud-btn danger" onclick="stopFly('${m.id}')">Stop flight</button>`:''}
  ${!busy&&!flying?`<button class="hud-btn" onclick="pickPhotos('${m.id}')">Import photos</button>`:''}
  ${!busy&&!flying&&images>=5?`<button class="hud-btn primary" onclick="processMap('${m.id}')">${ready?'Process again':'Process'}</button>`:''}
  ${busy?`<button class="hud-btn danger" onclick="cancelMap('${m.id}')">Cancel</button>`:''}
  ${ready&&r.model?`<a class="hud-btn primary" style="display:inline-flex;align-items:center;text-decoration:none" href="/maps/${m.id}/3d">Open 3D</a>`:''}
  ${ready&&r.report?`<a class="hud-btn" style="display:inline-flex;align-items:center;text-decoration:none" href="/maps/${m.id}/report.pdf" target="_blank">Report</a>`:''}
  ${!flying?`<button class="hud-btn danger" onclick="delMap('${m.id}')">Delete</button>`:''}</div></div>`}
function render(){const ms=data.maps||[];$('mpCount').textContent=ms.length+' MAP'+(ms.length===1?'':'S');
  $('mpList').innerHTML=ms.length?ms.map(card).join(''):'<p class="muted">No maps yet. Draw an area on the map to plan the first one.</p>';
  const e=data.engine||{};const st=$('mpEngineState');
  st.innerHTML=`<i class="dot ${e.ok?'good':'warn'}"></i>ENGINE: ${e.ok?'READY':e.starting?'STARTING':'OFF'}`;
  $('mpEngineText').textContent=e.ok?`Running at ${e.url}${e.version?' (OpenDroneMap '+e.version+')':''}.`:e.starting?'Starting… the first start downloads the engine and can take a while.':(e.error||'Not running.')+(e.local?' It starts by itself when you process a map.':'');
  $('mpEngineStart').style.display=e.ok||!e.local?'none':'';
  if(document.activeElement!==$('mpEngineUrl'))$('mpEngineUrl').value=e.local?'':e.url}
function select(id){sel=id;render();showSelected(true)}
function showSelected(fit){selLayer.clearLayers();if(orthoLayer){map.removeLayer(orthoLayer);orthoLayer=null}
  const m=(data.maps||[]).find(x=>x.id===sel);if(!m)return;
  L.polygon(m.area.map(p=>[p.lat,p.lon]),{color:'#5bd9ff',weight:2,fillOpacity:.06}).addTo(selLayer);
  const r=m.result||{};
  if(m.status==='ready'&&r.tiles&&$('mpOrtho').checked){orthoLayer=L.tileLayer(`/maps/${m.id}/tiles/{z}/{x}/{y}.png`,{tms:true,maxZoom:22,
    minNativeZoom:r.min_zoom||5,maxNativeZoom:r.max_zoom||21,bounds:L.latLngBounds(m.bounds).pad(0.3),attribution:'Drone map'}).addTo(map)}
  else L.polyline(m.points.map(p=>[p.lat,p.lon]),{color:'#ffcf7a',weight:1.5,dashArray:'4 4'}).addTo(selLayer);
  if(fit)map.fitBounds(m.bounds,{padding:[30,30],maxZoom:19})}
async function load(){try{const d=await fetch('/api/maps',{cache:'no-store'}).then(r=>r.json());if(!d.ok)return;
  const before=JSON.stringify((data.maps||[]).map(m=>[m.id,m.status]));data=d;
  if(!sel&&d.maps.length)sel=d.maps[0].id;
  if(!centred&&d.maps.length){centred=true;showSelected(true)}
  else if(before!==JSON.stringify(d.maps.map(m=>[m.id,m.status])))showSelected(false);
  if(!document.querySelector('.mp-card select:focus'))render()}catch(e){}}
async function fly(id){const dr=$('dr_'+id)?.value;const m=data.maps.find(x=>x.id===id);
  const dl=(data.drones||[]).find(x=>x.slot===dr);
  if(!confirm(`Fly ${dl?dl.label:'the drone'} over “${m.name}” at ${m.settings.alt} m? It takes off by itself, flies the grid and returns home. Keep it in sight.`))return;
  const d=await post(`/api/maps/${id}/fly`,{drone:dr});msg('mpMsg',d.ok?d.message:d.error,d.ok);load()}
async function stopFly(id){const d=await post(`/api/maps/${id}/stop`);msg('mpMsg',d.ok?'Stopped: the drone is hovering.':d.error,d.ok);load()}
async function processMap(id){const d=await post(`/api/maps/${id}/process`);msg('mpMsg',d.ok?'Processing queued. This page updates by itself.':d.error,d.ok);load()}
async function cancelMap(id){if(!confirm('Cancel processing this map?'))return;const d=await post(`/api/maps/${id}/cancel`);msg('mpMsg',d.ok?'Cancelled.':d.error,d.ok);load()}
async function delMap(id){const m=data.maps.find(x=>x.id===id);if(!confirm(`Delete “${m.name}” and all its images and results?`))return;
  const d=await fetch('/api/maps/'+id,{method:'DELETE'}).then(r=>r.json());msg('mpMsg',d.ok?'Deleted.':d.error,d.ok);if(sel===id)sel=null;load()}
function pickPhotos(id){const f=document.createElement('input');f.type='file';f.multiple=true;f.accept='image/jpeg';f.onchange=()=>uploadPhotos(id,[...f.files]);f.click()}
async function uploadPhotos(id,files){let ok=0,bad=[];
  for(let i=0;i<files.length;i++){msg('mpMsg',`Importing photo ${i+1} of ${files.length}…`);
    const fd=new FormData();fd.append('photos',files[i]);
    try{const d=await fetch(`/api/maps/${id}/photos`,{method:'POST',body:fd}).then(r=>r.json());if(d.added)ok+=d.added;else bad.push(...(d.errors||[d.error]))}catch(e){bad.push(files[i].name)}}
  msg('mpMsg',`Imported ${ok} photo${ok===1?'':'s'}.`+(bad.length?' Skipped: '+bad.slice(0,3).join('; '):''),bad.length?false:true);load()}
async function saveEngine(){const d=await post('/api/maps/engine',{url:$('mpEngineUrl').value.trim()});msg('mpMsg',d.ok?'Engine address saved.':d.error,d.ok);load()}
async function startEngine(){const d=await post('/api/maps/engine',{start:true});msg('mpMsg',d.ok?'Starting the engine… the first start downloads it and can take a while.':d.error,d.ok);load()}
if(typeof L!=='undefined')initMap();load();setInterval(load,3000);
</script>
"""

VIEWER_HEAD = r"""
<script type="importmap">{"imports":{"three":"/vendor/three/three.module.min.js","three/addons/":"/vendor/three/"}}</script>
<style>
#mv{position:fixed;left:0;right:0;top:64px;bottom:0;background:#020a10}
#mv canvas{display:block}
.mv-bar{position:fixed;left:12px;top:76px;z-index:5;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.mv-bar .hud-btn{min-height:32px;font-size:10px;padding:0 10px;display:inline-flex;align-items:center;text-decoration:none;background:rgba(3,16,26,.88)}
.mv-bar .hud-btn.on{color:#02131d;background:#25c7ff}
.mv-title{background:rgba(3,16,26,.88);border:1px solid #155879;border-radius:4px;padding:7px 10px;color:#e9f8ff;font:bold 12px Arial;letter-spacing:.5px}
#mvInfo{position:fixed;left:12px;bottom:12px;z-index:5;background:rgba(3,16,26,.9);border:1px solid #155879;border-radius:4px;padding:8px 11px;color:#9edfff;font:12px Arial;max-width:min(520px,90vw)}
#mvInfo b{color:#fff}
</style>
"""

VIEWER = r"""
<div id="mv"></div>
<div class="mv-bar"><a class="hud-btn" href="/maps">← 3D Maps</a><span class="mv-title">__MAP_NAME__</span>
<button class="hud-btn" id="mvReset">Reset view</button><button class="hud-btn" id="mvTop">Top view</button>
<button class="hud-btn" id="mvMeasure">Measure</button><button class="hud-btn" id="mvWire">Wireframe</button></div>
<div id="mvInfo">Loading the 3D model…</div>
<script type="module">
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/OrbitControls.js';
import {MTLLoader} from 'three/addons/MTLLoader.js';
import {OBJLoader} from 'three/addons/OBJLoader.js';
const BASE='/maps/__MAP_ID__/model/', MODEL='__MODEL__';
const box=document.getElementById('mv'), info=document.getElementById('mvInfo');
const say=h=>{info.innerHTML=h};
const renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(2,window.devicePixelRatio||1));
box.appendChild(renderer.domElement);
const scene=new THREE.Scene();scene.background=new THREE.Color(0x020a10);
const camera=new THREE.PerspectiveCamera(50,1,0.1,20000);
const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.maxPolarAngle=Math.PI*0.495;
scene.add(new THREE.AmbientLight(0xffffff,1.0));
function size(){const w=box.clientWidth,h=box.clientHeight;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix()}
window.addEventListener('resize',size);size();
let model=null,radius=50,wire=false,measuring=false,pts=[],marks=new THREE.Group();scene.add(marks);
function view(top){if(!model)return;const d=radius*2.2;
  if(top)camera.position.set(0,d,0.001);else camera.position.set(d*0.6,d*0.55,d*0.6);
  controls.target.set(0,0,0);controls.update()}
const mtl=new MTLLoader();mtl.setPath(BASE);mtl.setResourcePath(BASE);
mtl.load(MODEL.replace(/\.obj$/i,'.mtl'),materials=>{materials.preload();load(materials)},undefined,()=>load(null));
function load(materials){const obj=new OBJLoader();if(materials)obj.setMaterials(materials);obj.setPath(BASE);
  obj.load(MODEL,o=>{
    // The textures already hold the light of the day the images were taken: show them as they are.
    o.traverse(c=>{if(c.isMesh){const ms=Array.isArray(c.material)?c.material:[c.material];
      c.material=ms.map(m=>new THREE.MeshBasicMaterial({map:m.map||null,color:m.map?0xffffff:0x8fb7c9,side:THREE.DoubleSide}));
      if(c.material.length===1)c.material=c.material[0]}});
    o.rotation.x=-Math.PI/2;  // the engine's model has Z up (height); three.js uses Y up
    const g=new THREE.Group();g.add(o);g.updateMatrixWorld(true);
    const b=new THREE.Box3().setFromObject(g),c=b.getCenter(new THREE.Vector3()),s=b.getSize(new THREE.Vector3());
    g.position.set(-c.x,-b.min.y,-c.z);  // centre of the site on the origin, lowest point on the ground plane
    model=g;scene.add(g);radius=Math.max(s.x,s.z)/2||50;
    camera.near=radius/500;camera.far=radius*50;camera.updateProjectionMatrix();view(false);
    say(`<b>${s.x.toFixed(0)} × ${s.z.toFixed(0)} m</b> site, ${s.y.toFixed(0)} m high. Drag to turn, right-drag to move, scroll to zoom. <b>Measure</b> gives the distance between two points.`)},
    e=>{if(e.lengthComputable)say(`Loading the 3D model… ${Math.round(e.loaded/e.total*100)}%`)},
    ()=>say('Could not load the 3D model.'))}
const ray=new THREE.Raycaster(),mouse=new THREE.Vector2();let down=null;
renderer.domElement.addEventListener('pointerdown',e=>{down=[e.clientX,e.clientY]});
renderer.domElement.addEventListener('pointerup',e=>{if(!measuring||!model||!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>4)return;
  const r=renderer.domElement.getBoundingClientRect();mouse.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);
  ray.setFromCamera(mouse,camera);const hit=ray.intersectObject(model,true)[0];if(!hit)return;
  if(pts.length===2){pts=[];marks.clear()}
  pts.push(hit.point.clone());const dot=new THREE.Mesh(new THREE.SphereGeometry(radius/150),new THREE.MeshBasicMaterial({color:0xffcf7a}));
  dot.position.copy(hit.point);marks.add(dot);
  if(pts.length===2){marks.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineBasicMaterial({color:0xffcf7a})));
    const d=pts[0].distanceTo(pts[1]),h=Math.abs(pts[1].y-pts[0].y),flat=Math.hypot(pts[1].x-pts[0].x,pts[1].z-pts[0].z);
    say(`Distance <b>${d.toFixed(1)} m</b> (along the ground ${flat.toFixed(1)} m, height difference ${h.toFixed(1)} m). Click again to measure another.`)}
  else say('Click the second point.')});
document.getElementById('mvReset').onclick=()=>view(false);
document.getElementById('mvTop').onclick=()=>view(true);
document.getElementById('mvWire').onclick=e=>{wire=!wire;e.target.classList.toggle('on',wire);
  model&&model.traverse(c=>{if(c.isMesh)(Array.isArray(c.material)?c.material:[c.material]).forEach(m=>{m.wireframe=wire})})};
document.getElementById('mvMeasure').onclick=e=>{measuring=!measuring;e.target.classList.toggle('on',measuring);pts=[];marks.clear();
  say(measuring?'Click the first point on the model.':'Measuring off.')};
(function loop(){requestAnimationFrame(loop);controls.update();renderer.render(scene,camera)})();
</script>
"""
