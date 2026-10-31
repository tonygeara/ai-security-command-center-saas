"""Every drone live at once."""
BODY = r"""
<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">
<style>
.dg-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.dg-bar select{width:auto}
.dg-grid{display:grid;gap:10px;grid-template-columns:repeat(var(--cols,2),minmax(0,1fr))}
.dg-tile{position:relative;background:#000;border:1px solid #155879;border-radius:5px;overflow:hidden;aspect-ratio:16/9;cursor:pointer}
.dg-tile.sel{box-shadow:0 0 0 2px #5bd9ff}
.dg-tile .live-slot,.dg-tile .dg-vcam{position:absolute;inset:0;width:100%;height:100%}
.dg-tile .live-slot video{width:100%;height:100%;object-fit:contain}
.dg-head{position:absolute;left:0;right:0;top:0;z-index:600;display:flex;justify-content:space-between;align-items:center;gap:6px;padding:7px 9px;background:linear-gradient(rgba(2,10,16,.85),rgba(2,10,16,0))}
.dg-name{color:#e9f8ff;font:bold 12px Arial;letter-spacing:1px}
.dg-name i{display:inline-block;width:8px;height:8px;border-radius:50%;background:#53636d;margin-right:6px}
.dg-name i.ok{background:#26ee89}.dg-name i.half{background:#ffb23c}
.dg-tag{font-size:9px;color:#ffcf7a;border:1px solid #7a5a12;border-radius:3px;padding:1px 4px;margin-left:6px}
.dg-btns{display:flex;gap:5px}
.dg-btns a,.dg-btns button{background:rgba(3,16,26,.85);border:1px solid #155879;color:#9edfff;border-radius:3px;padding:4px 8px;font:bold 10px Arial;letter-spacing:.5px;text-decoration:none;cursor:pointer}
.dg-hud{position:absolute;left:8px;right:8px;bottom:8px;z-index:600;display:flex;gap:5px;flex-wrap:wrap}
.dg-hud span{background:rgba(3,16,26,.85);border:1px solid #155879;color:#9edfff;padding:3px 7px;border-radius:3px;font:bold 10px Arial}
.dg-hud b{color:#fff}
.dg-off{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#6d8b9d;font:bold 12px Arial;letter-spacing:1px;text-align:center;padding:20px}
.dg-tile .live-mode{top:auto!important;bottom:38px!important;right:10px!important}
.dg-x{position:absolute;left:50%;top:50%;width:40px;height:40px;margin:-20px 0 0 -20px;border:2px solid rgba(91,217,255,.8);border-radius:50%;z-index:500;pointer-events:none}
.dg-grid:fullscreen{background:#000;padding:8px;align-content:center;overflow:auto}
.dg-grid:fullscreen .dg-tile{aspect-ratio:auto;height:calc((100vh - 16px - (var(--rows,1) - 1) * 10px) / var(--rows,1))}
.dg-tile:fullscreen{aspect-ratio:auto;border:0;border-radius:0}
.dg-grid.solo .dg-tile:not(.sel){display:none}
.dg-grid.solo{grid-template-columns:1fr}
@media(max-width:760px){.dg-grid{grid-template-columns:1fr}}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Drone</div><h1 class="page-title">Drone Grid</h1>
<div class="page-sub">Every drone live at once. Click a drone to select it, double-click (or ⛶) for its own full screen, or put the whole grid full screen.</div></div>
<div class="actions"><span class="state" id="dgState"><i class="dot warn"></i>LOADING</span></div></div>
<div class="dg-bar">
<button class="hud-btn primary" onclick="fullAll()">⛶ Full screen: all drones</button>
<button class="hud-btn" id="soloBtn" onclick="toggleSolo()">Show selected only</button>
<label style="margin:0;display:flex;gap:6px;align-items:center;text-transform:none;letter-spacing:0">Layout
<select id="dgCols" onchange="layout()"><option value="0">Auto</option><option value="1">1 per row</option><option value="2">2 per row</option><option value="3">3 per row</option><option value="4">4 per row</option></select></label>
<a class="hud-btn" href="/drone-control" style="text-decoration:none">← Drone controls</a>
</div>
<div class="dg-grid" id="dgGrid"></div>
<p class="muted" id="dgEmpty" style="display:none">No drones yet. Add one on the Drone page, or add a virtual drone on the Virtual drones tab.</p>
</main>
<script src="/vendor/leaflet/leaflet.js"></script>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const fmt=(v,d=1)=>v==null||isNaN(v)?'–':Number(v).toFixed(d);
const tiles={};let selected=null,solo=false;
const whenPlayer=fn=>window.attachLiveCamera?fn():window.addEventListener('live-player-ready',fn,{once:true});
function tileFor(x){const t=document.createElement('div');t.className='dg-tile';t.dataset.drone=x.drone;
  t.innerHTML=(x.virtual?'<div class="dg-vcam"></div><div class="dg-x"></div>':'<div class="live-slot" data-live-camera="'+esc(x.drone)+'"></div>')
    +'<div class="dg-off" style="display:none"></div>'
    +'<div class="dg-head"><span class="dg-name"><i></i>'+esc(x.label).toUpperCase()+(x.virtual?'<span class="dg-tag">VIRTUAL</span>':'')+'</span>'
    +'<span class="dg-btns"><a href="/drone-control?drone='+encodeURIComponent(x.drone)+'" onclick="event.stopPropagation()">CONTROLS</a>'
    +'<button type="button" title="Full screen this drone">⛶</button></span></div><div class="dg-hud"></div>';
  t.querySelector('button').addEventListener('click',e=>{e.stopPropagation();full(t)});
  t.addEventListener('click',()=>select(x.drone));
  t.addEventListener('dblclick',()=>full(t));
  if(!x.virtual)whenPlayer(()=>window.attachLiveCamera(t.querySelector('.live-slot')));
  return t}
function full(el){if(document.fullscreenElement)document.exitFullscreen();else el.requestFullscreen?.()}
function fullAll(){const g=$('dgGrid');if(document.fullscreenElement){document.exitFullscreen();return}g.requestFullscreen?.()}
function select(d){selected=d;Object.values(tiles).forEach(t=>t.classList.toggle('sel',t.dataset.drone===d))}
function toggleSolo(){if(!selected&&!solo){const f=Object.keys(tiles)[0];if(f)select(f)}solo=!solo;$('dgGrid').classList.toggle('solo',solo);
  $('soloBtn').textContent=solo?'Show all drones':'Show selected only';layout()}
function layout(){const n=solo?1:Object.keys(tiles).length||1,pick=+$('dgCols').value;
  const cols=solo?1:pick||(n<=1?1:n<=4?2:3),rows=Math.ceil(n/cols);
  $('dgGrid').style.setProperty('--cols',cols);$('dgGrid').style.setProperty('--rows',rows);
  Object.values(tiles).forEach(t=>t._map&&t._map.invalidateSize())}
function vcam(t,x){if(typeof L==='undefined'||!x.lat)return;const z=x.altitude>90?16:x.altitude>45?17:x.altitude>15?18:19;
  if(!t._map){t._map=L.map(t.querySelector('.dg-vcam'),{zoomControl:false,attributionControl:false,dragging:false,scrollWheelZoom:false,doubleClickZoom:false,boxZoom:false,keyboard:false,touchZoom:false});
    L.tileLayer('/tiles/sat/{z}/{x}/{y}',{maxZoom:19}).addTo(t._map);t._map.setView([x.lat,x.lon],z)}
  else t._map.setView([x.lat,x.lon],z,{animate:false})}
function paint(t,x){const dot=x.drone_connected?'ok':x.phone_connected?'half':'';t.querySelector('.dg-name i').className=dot;
  const off=t.querySelector('.dg-off'),down=!x.phone_connected||!x.drone_connected;
  off.style.display=down?'flex':'none';off.textContent=x.over_limit?'OVER LICENCE LIMIT':!x.phone_connected?'PHONE NOT CONNECTED':!x.drone_connected?'DRONE OFF':'';
  const state=x.mission?(x.mission==='route'?'ROUTE':x.mission==='backup'?'BACKUP (RESERVED)':'RESPONSE'):x.flying?'FLYING':'ON GROUND';
  t.querySelector('.dg-hud').innerHTML=down?'':`<span>${state}</span><span>ALT <b>${fmt(x.altitude)}</b> m</span><span>SPD <b>${fmt(x.speed)}</b> m/s</span>`
    +`<span>BAT <b>${x.battery??'–'}</b>%</span><span>GPS <b>${x.gps??'–'}</b></span><span>HOME <b>${fmt(x.distance_home,0)}</b> m</span>`;
  if(x.virtual)vcam(t,x)}
async function load(){let d;try{d=await fetch('/api/drone/links',{cache:'no-store'}).then(r=>r.json())}catch(e){return}if(!d.ok)return;
  const g=$('dgGrid'),seen=new Set();
  d.drones.forEach(x=>{seen.add(x.drone);if(!tiles[x.drone]){tiles[x.drone]=tileFor(x);g.appendChild(tiles[x.drone]);layout()}paint(tiles[x.drone],x)});
  Object.keys(tiles).filter(k=>!seen.has(k)).forEach(k=>{const s=tiles[k].querySelector('.live-slot');if(s)window.detachLiveCamera?.(s);tiles[k].remove();delete tiles[k];layout()});
  const live=d.drones.filter(x=>x.drone_connected).length;
  $('dgState').innerHTML='<i class="dot '+(live?'good':'warn')+'"></i>'+live+' / '+d.drones.length+' DRONES LINKED';
  $('dgEmpty').style.display=d.drones.length?'none':''}
document.addEventListener('fullscreenchange',()=>setTimeout(layout,100));
window.addEventListener('resize',layout);
load();setInterval(load,1000);
</script>"""
