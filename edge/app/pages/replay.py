"""4D incident replay: an incident played back in 3D over the site (Incidents → open one → 4D replay).

Cameras stand where they are placed, with their views on the ground; a camera's view lights up when it
sees something, the drone flies its recorded GPS track with a trail, the spot it was sent to is marked,
and each picture appears at its moment. Play, pause, change the speed or drag the timeline.
Coordinates: metres east (x), up (y) and south (z) of the incident's camera.
"""
BODY = r"""
<style>
.rp-grid{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:14px;align-items:start}
@media(max-width:980px){.rp-grid{grid-template-columns:1fr}}
#rpView{position:relative;height:min(68vh,640px);border:1px solid #155879;border-radius:5px;background:#020a10;overflow:hidden}
#rpView canvas{display:block}
.rp-bar{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}
.rp-bar>*{width:auto!important;margin:0}.rp-bar input[type=range]{flex:1;min-width:160px;padding:0}
#rpClock{font:600 13px Consolas,monospace;color:#e9f8ff;min-width:150px}
.rp-list{max-height:min(68vh,640px);overflow:auto}
.rp-it{display:flex;gap:8px;padding:6px 4px;border-top:1px solid #0f2c3c;font-size:12px;cursor:pointer;opacity:.45}
.rp-it.done{opacity:1}.rp-it.now{background:#0b2a3c;opacity:1}
.rp-it time{color:#6d8b9d;min-width:62px;font-family:Consolas,monospace}
#rpPic{display:none;position:absolute;right:8px;top:8px;width:min(42%,320px);border:1px solid #36cfff;border-radius:4px;box-shadow:0 0 18px rgba(0,0,0,.6);z-index:3}
#rpPic img{width:100%;display:block}#rpPic div{background:rgba(3,16,26,.92);color:#9edfff;font:11px Arial;padding:4px 6px}
#rpMsg{position:absolute;left:8px;bottom:8px;z-index:2;background:rgba(3,16,26,.88);border:1px solid #155879;border-radius:4px;padding:5px 8px;color:#9edfff;font:11px Arial;pointer-events:none}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Incident replay</div><h1 class="page-title" id="rpTitle">4D replay</h1>
<div class="page-sub" id="rpSub">Loading…</div></div><div class="actions"><a class="hud-btn" href="/incidents">Back to incidents</a></div></div>
<div class="rp-grid">
<section class="panel"><div class="panel-body">
<div id="rpView"><div id="rpMsg">Loading…</div><div id="rpPic"><img alt=""><div></div></div></div>
<div class="rp-bar">
<button class="hud-btn primary" id="rpPlay">▶ Play</button>
<select id="rpSpeed"><option value="1">1×</option><option value="4" selected>4×</option><option value="16">16×</option><option value="60">60×</option></select>
<input type="range" id="rpSlider" min="0" max="1000" value="0">
<span id="rpClock">--:--:--</span></div>
<div class="muted" style="font-size:11px;margin-top:6px">Drag to turn the view, scroll to zoom. Camera views light up when they see something; the yellow pin is where the drone was sent.</div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">⚑ Timeline</div></div><div class="panel-body rp-list" id="rpList"></div></section>
</div></main>
<script type="module">
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/OrbitControls.js';
import {MTLLoader} from 'three/addons/MTLLoader.js';
import {OBJLoader} from 'three/addons/OBJLoader.js';

const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
const M_LAT = 110540, M_LON = 111320;
const LIT_S = 12;  // seconds a camera's view stays lit after it sees something
const id = Number(location.pathname.split('/')[2]);
let D, C, scene, camera, renderer, controls, drone, trail, trailGeo, t0 = 0, t1 = 1, now = 0, playing = false, last = 0;
const camObjs = {}, hits = {};  // camera name -> {fan, post}; camera name -> [times it saw something]

function enu(lat, lon, alt){ return new THREE.Vector3((lon - C.lon) * M_LON * Math.cos(C.lat * Math.PI / 180), alt || 0, -(lat - C.lat) * M_LAT); }
const fmt = t => new Date(t * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});

function label(text, color){
  const c = document.createElement('canvas'), g = c.getContext('2d');
  g.font = 'bold 40px Arial'; const w = Math.ceil(g.measureText(text).width) + 40;
  c.width = w; c.height = 100; g.fillStyle = 'rgba(3,16,26,.85)'; g.fillRect(0, 10, w, 80);
  g.strokeStyle = color; g.lineWidth = 4; g.strokeRect(2, 12, w - 4, 76);
  g.fillStyle = '#e9f8ff'; g.font = 'bold 40px Arial'; g.textBaseline = 'middle'; g.fillText(text, 20, 50);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), depthTest: false, sizeAttenuation: false}));
  s.scale.set(0.0375 * w / 96, 0.0375, 1); s.center.set(0.5, -0.4); s.renderOrder = 10; return s;
}

function ground(){
  const z = 18, n = 2 ** z, c = C, R = 2;
  const tx = Math.floor((c.lon + 180) / 360 * n), ty = Math.floor((1 - Math.log(Math.tan(c.lat * Math.PI / 180) + 1 / Math.cos(c.lat * Math.PI / 180)) / Math.PI) / 2 * n);
  const lon = x => x / n * 360 - 180, lat = y => Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI;
  const nw = enu(lat(ty - R), lon(tx - R), 0), se = enu(lat(ty + R + 1), lon(tx + R + 1), 0);
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 256 * (2 * R + 1);
  const g = canvas.getContext('2d'); g.fillStyle = '#0b1c26'; g.fillRect(0, 0, canvas.width, canvas.height);
  const tex = new THREE.CanvasTexture(canvas); tex.colorSpace = THREE.SRGBColorSpace;
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(se.x - nw.x, se.z - nw.z), new THREE.MeshBasicMaterial({map: tex}));
  plane.rotation.x = -Math.PI / 2; plane.position.set((nw.x + se.x) / 2, -0.2, (nw.z + se.z) / 2); scene.add(plane);
  const grid = new THREE.GridHelper(1200, 60, 0x155879, 0x0d2c3d); grid.position.y = -0.4; scene.add(grid);
  for (let i = -R; i <= R; i++) for (let j = -R; j <= R; j++) {
    const img = new Image();
    img.onload = () => { g.drawImage(img, (i + R) * 256, (j + R) * 256); tex.needsUpdate = true; };
    img.src = `/tiles/sat/${z}/${tx + i}/${ty + j}`;
  }
}

function siteModel(m){
  if (!m) return;
  const base = `/maps/${m.id}/model/`, mtl = new MTLLoader(); mtl.setPath(base); mtl.setResourcePath(base);
  const place = materials => { const obj = new OBJLoader(); if (materials) obj.setMaterials(materials); obj.setPath(base);
    obj.load(m.model, o => {
      o.traverse(c => { if (c.isMesh) { const ms = Array.isArray(c.material) ? c.material : [c.material];
        c.material = ms.map(x => new THREE.MeshBasicMaterial({map: x.map || null, color: x.map ? 0xffffff : 0x8fb7c9, side: THREE.DoubleSide}));
        if (c.material.length === 1) c.material = c.material[0]; } });
      o.rotation.x = -Math.PI / 2;
      const grp = new THREE.Group(); grp.add(o); grp.updateMatrixWorld(true);
      const low = new THREE.Box3().setFromObject(grp).min.y, at = enu(m.origin.lat, m.origin.lon, 0);
      grp.position.set(at.x, -low, at.z); scene.add(grp);
    });
  };
  mtl.load(m.model.replace(/\.obj$/i, '.mtl'), x => { x.preload(); place(x); }, undefined, () => place(null));
}

function zones(list){
  for (const z of list) {
    const shape = new THREE.Shape(z.points.map(p => { const v = enu(p.lat, p.lon, 0); return new THREE.Vector2(v.x, -v.z); }));
    const geo = new THREE.ExtrudeGeometry(shape, {depth: 120, bevelEnabled: false}); geo.rotateX(-Math.PI / 2);
    scene.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({color: 0xff4d6a, transparent: true, opacity: 0.08, depthWrite: false})));
  }
}

function cameras(list){
  for (const c of list) {
    const at = enu(c.lat, c.lon, 0), v = c.view, n = 18, shape = new THREE.Shape(); shape.moveTo(at.x, -at.z);
    for (let i = 0; i <= n; i++) { const b = (v.heading - v.fov / 2 + v.fov * i / n) * Math.PI / 180;
      shape.lineTo(at.x + v.range * Math.sin(b), -at.z + v.range * Math.cos(b)); }
    const geo = new THREE.ShapeGeometry(shape); geo.rotateX(-Math.PI / 2);
    const fan = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({color: 0x2bc0ff, transparent: true, opacity: 0.12, depthWrite: false, side: THREE.DoubleSide}));
    fan.position.y = 0.3; scene.add(fan);
    const post = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 6), new THREE.MeshBasicMaterial({color: 0x5bd9ff}));
    post.position.set(at.x, 3, at.z); scene.add(post);
    const tag = label('▣ ' + c.name, '#9edfff'); tag.position.set(at.x, 9, at.z); scene.add(tag);
    camObjs[c.name] = {fan, post};
  }
}

function build(){
  const box = $('rpView');
  renderer = new THREE.WebGLRenderer({antialias: true}); renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  box.prepend(renderer.domElement);
  scene = new THREE.Scene(); scene.background = new THREE.Color(0x020a10);
  scene.add(new THREE.AmbientLight(0xffffff, 0.9));
  camera = new THREE.PerspectiveCamera(50, 1, 1, 20000); camera.position.set(-70, 80, 110);
  controls = new OrbitControls(camera, renderer.domElement); controls.target.set(0, 0, 0); controls.maxPolarAngle = Math.PI / 2.05;
  const size = () => { const w = box.clientWidth, h = box.clientHeight; renderer.setSize(w, h); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix(); };
  size(); window.addEventListener('resize', size);
  ground(); siteModel((D.maps || [])[0]); zones(D.zones || []); cameras(D.cameras || []);
  // frame the cameras, the drone's path and the spot it was sent to
  const pts = [...D.cameras.map(c => enu(c.lat, c.lon, 0)), ...D.track.map(p => enu(p.lat, p.lon, p.alt || 0)),
               ...D.items.filter(i => i.kind === 'dispatch' && i.data && i.data.lat != null).map(i => enu(i.data.lat, i.data.lon, 0))];
  if (pts.length) {
    const box3 = new THREE.Box3().setFromPoints(pts), mid = box3.getCenter(new THREE.Vector3()), r = Math.max(30, box3.getSize(new THREE.Vector3()).length() / 2);
    controls.target.copy(mid); camera.position.set(mid.x - r * 1.1, mid.y + r * 1.3, mid.z + r * 1.6);
  }
  // where the drone was sent
  for (const it of D.items) if (it.kind === 'dispatch' && it.data && it.data.lat != null) {
    const at = enu(it.data.lat, it.data.lon, 0);
    const pin = new THREE.Mesh(new THREE.ConeGeometry(1.6, 5, 16), new THREE.MeshBasicMaterial({color: 0xffd23f}));
    pin.rotation.x = Math.PI; pin.position.set(at.x, 2.5, at.z); scene.add(pin);
    const tag = label('◎ drone sent here', '#ffd23f'); tag.position.set(at.x, 7, at.z); scene.add(tag);
  }
  // the drone and its trail
  drone = new THREE.Group();
  drone.add(new THREE.Mesh(new THREE.SphereGeometry(1.4, 16, 12), new THREE.MeshBasicMaterial({color: 0x26ee89})));
  const stick = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 1, 6), new THREE.MeshBasicMaterial({color: 0x26ee89, transparent: true, opacity: 0.5}));
  drone.add(stick); drone.userData.stick = stick; drone.visible = false; scene.add(drone);
  trailGeo = new THREE.BufferGeometry(); trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({color: 0x26ee89}));
  scene.add(trail);
  const loop = tms => { requestAnimationFrame(loop);
    if (playing) { const dt = Math.min(0.25, (tms - last) / 1000) * Number($('rpSpeed').value); now = Math.min(t1, now + dt); if (now >= t1) setPlaying(false); }
    last = tms; draw(); controls.update(); renderer.render(scene, camera); };
  requestAnimationFrame(loop);
}

function trackAt(t){
  const tr = D.track; if (!tr.length || t < tr[0].t) return null;
  let i = 0; while (i < tr.length - 1 && tr[i + 1].t <= t) i++;
  if (i >= tr.length - 1) return t - tr[tr.length - 1].t < 20 ? tr[tr.length - 1] : null;
  const a = tr[i], b = tr[i + 1], k = (t - a.t) / Math.max(0.001, b.t - a.t);
  return {lat: a.lat + (b.lat - a.lat) * k, lon: a.lon + (b.lon - a.lon) * k, alt: (a.alt || 0) + ((b.alt || 0) - (a.alt || 0)) * k};
}

let lastDrawn = -1, lastPic = '';
function draw(){
  if (Math.abs(now - lastDrawn) < 0.05) return; lastDrawn = now;
  $('rpSlider').value = Math.round((now - t0) / Math.max(1, t1 - t0) * 1000);
  $('rpClock').textContent = fmt(now) + `  (+${Math.round(now - t0)} s)`;
  for (const [name, o] of Object.entries(camObjs)) {
    const lit = (hits[name] || []).some(t => now >= t && now - t < LIT_S);
    o.fan.material.opacity = lit ? 0.45 : 0.12; o.fan.material.color.set(lit ? 0xff8f3f : 0x2bc0ff); o.post.material.color.set(lit ? 0xff8f3f : 0x5bd9ff);
  }
  const p = trackAt(now);
  drone.visible = !!p;
  if (p) { const v = enu(p.lat, p.lon, p.alt || 0); drone.position.copy(v);
    const st = drone.userData.stick; st.scale.y = Math.max(0.1, v.y); st.position.y = -v.y / 2; }
  const pts = D.track.filter(q => q.t <= now).map(q => enu(q.lat, q.lon, q.alt || 0));
  trailGeo.setFromPoints(pts.length > 1 ? pts : []);
  // timeline highlight and the latest picture
  let cur = null;
  document.querySelectorAll('.rp-it').forEach(el => { const t = Number(el.dataset.t); el.classList.toggle('done', t <= now); el.classList.remove('now'); if (t <= now) cur = el; });
  if (cur) cur.classList.add('now');
  const pic = [...D.events].reverse().find(e => e.image && e.t <= now);  // the latest picture so far
  const key = pic ? pic.image + pic.t : '';
  if (key !== lastPic) { lastPic = key; $('rpPic').style.display = pic ? 'block' : 'none';
    if (pic) { $('rpPic').querySelector('img').src = pic.image; $('rpPic').querySelector('div').textContent = `${fmt(pic.t)} · ${pic.type}${pic.identifier ? ' ' + pic.identifier : ''}`; } }
  $('rpMsg').textContent = p ? `Drone ${Math.round(p.alt || 0)} m up` : (D.track.length ? 'Drone not flying yet' : 'No drone flew in this incident');
}

function setPlaying(on){ playing = on; $('rpPlay').textContent = on ? '❚❚ Pause' : '▶ Play'; if (on && now >= t1) now = t0; }

async function init(){
  const r = await fetch(`/api/incidents/${id}/replay`); D = await r.json();
  if (!D.ok) { $('rpSub').textContent = D.error || 'Could not load this incident.'; $('rpMsg').textContent = D.error || ''; return; }
  C = D.centre;
  const inc = D.incident;
  $('rpTitle').textContent = inc.title;
  $('rpSub').textContent = `Incident ${inc.id} · camera ${inc.camera} · ${new Date(inc.started * 1000).toLocaleString()} · ${inc.level}`;
  const times = [inc.started, inc.updated, ...D.items.map(i => i.t), ...D.track.map(p => p.t), ...D.events.map(e => e.t)].filter(Number.isFinite);
  t0 = Math.min(...times) - 3; t1 = Math.max(...times) + 5; now = t0;
  for (const it of D.items) if (['detection', 'event', 'sighting', 'pattern'].includes(it.kind)) (hits[inc.camera] = hits[inc.camera] || []).push(it.t);
  for (const e of D.events) (hits[inc.camera] = hits[inc.camera] || []).push(e.t);
  $('rpList').innerHTML = D.items.map(i => `<div class="rp-it" data-t="${i.t}"><time>${fmt(i.t)}</time><span>${esc(i.text)}</span></div>`).join('') || '<p class="muted">Nothing recorded.</p>';
  document.querySelectorAll('.rp-it').forEach(el => el.onclick = () => { now = Number(el.dataset.t); lastDrawn = -1; });
  $('rpPlay').onclick = () => setPlaying(!playing);
  $('rpSlider').oninput = e => { now = t0 + (t1 - t0) * Number(e.target.value) / 1000; lastDrawn = -1; };
  build();
}
init();
</script>"""
