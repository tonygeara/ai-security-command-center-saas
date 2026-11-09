"""4D live: the drones flying in 3D over the site, in real time (served as /live4d.js, an ES module).

Shown on the Drone page when its map's "4D LIVE" switch is on. Each drone has its own switch (show / hide)
and a Follow button. Coordinates: metres east (x), up (y) and south (z) of the site centre.
"""
IMPORTMAP = '<script type="importmap">{"imports":{"three":"/vendor/three/three.module.min.js","three/addons/":"/vendor/three/"}}</script>'

JS = r"""
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/OrbitControls.js';
import {MTLLoader} from 'three/addons/MTLLoader.js';
import {OBJLoader} from 'three/addons/OBJLoader.js';

const COLORS = [0x25c7ff, 0xffd23f, 0x26ee89, 0xff7bd5, 0xff9a3c, 0xa98bff, 0x7dffea, 0xff5d5d];
const ZONE = {airport: 0xff9a3c, airspace: 0xb36bff};
const M_LAT = 110540, M_LON = 111320;
const store = {get(k){try{return JSON.parse(localStorage.getItem(k))}catch(e){return null}}, set(k, v){try{localStorage.setItem(k, JSON.stringify(v))}catch(e){}}};
// The place every map on this PC looks at (search, Locate me, moving a map): see /mapsearch.js.
const focusGet = () => { const f = store.get('map-focus'); return f && isFinite(f.lat) && isFinite(f.lon) ? f : null; };
const focusSet = (lat, lon) => { const f = focusGet(); store.set('map-focus', {lat, lon, zoom: f && f.zoom || 17, at: Date.now()}); };
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);

let st = null;  // one running view

export function start(box, bar, drone, hooks){
  if (st) return;
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  box.innerHTML = '';
  box.appendChild(renderer.domElement);
  const info = document.createElement('div');
  info.style.cssText = 'position:absolute;left:8px;bottom:8px;z-index:2;background:rgba(3,16,26,.88);border:1px solid #155879;border-radius:4px;padding:5px 8px;color:#9edfff;font:11px Arial;pointer-events:none';
  info.textContent = 'Connecting…';
  box.appendChild(info);
  box.appendChild(searchBox());
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x020a10);
  scene.fog = new THREE.Fog(0x020a10, 1500, 6000);
  scene.add(new THREE.AmbientLight(0xffffff, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 0.8); sun.position.set(300, 600, 200); scene.add(sun);
  const camera = new THREE.PerspectiveCamera(50, 1, 1, 20000);
  camera.position.set(-120, 110, 160);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.maxPolarAngle = Math.PI * 0.49;
  // Turning or moving the view by hand saves the place looked at, for the flat map and 3D MAP.
  controls.addEventListener('end', () => { if (st && st.centre) { const ll = latlon(controls.target); focusSet(ll.lat, ll.lon); } });
  const groups = {zones: new THREE.Group(), aircraft: new THREE.Group(), site: new THREE.Group(), draft: new THREE.Group(), cams: new THREE.Group()};
  Object.values(groups).forEach(g => scene.add(g));
  st = {box, bar, drone, renderer, scene, camera, controls, groups, info, centre: null, drones: {}, follow: store.get('l4d-follow') || drone,
        hidden: new Set(store.get('l4d-hidden') || []), zonesKey: '', siteKey: '', timer: null, raf: 0, alive: true, last: null,
        hooks: hooks || {}, anim: null, draftKey: ''};
  // A click (not a drag): on a drone, go to it; on the ground, the same as clicking the flat map (route stop / zone corner).
  let down = null;
  renderer.domElement.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointerup', e => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5 || e.button !== 0) return;
    pick(e);
  });
  const size = () => { const w = box.clientWidth, h = box.clientHeight; renderer.setSize(w, h); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix(); };
  st.size = size; window.addEventListener('resize', size); size();
  const loop = () => { if (!st || !st.alive) return; st.raf = requestAnimationFrame(loop); animate(); controls.update(); renderer.render(scene, camera); };
  loop();
  poll();
  st.timer = setInterval(poll, 1000);
}

export function stop(){
  if (!st) return;
  st.alive = false; clearInterval(st.timer); cancelAnimationFrame(st.raf);
  window.removeEventListener('resize', st.size);
  st.renderer.dispose(); st.box.innerHTML = ''; st.bar.innerHTML = '';
  st = null;
}

// Move the whole scene to another place: new ground there, everything else is redrawn round it.
function recentre(lat, lon, label){
  (st.groundObjs || []).forEach(o => st.scene.remove(o));
  st.centre = {lat, lon}; st.zonesKey = ''; st.siteKey = ''; st.camsKey = ''; st.draftKey = ''; st.barKey = '';
  Object.values(st.drones).forEach(o => { o.routeKey = null; });
  if (st.follow) { st.follow = ''; store.set('l4d-follow', ''); }
  st.last = null; ground(); focusSet(lat, lon);
  st.anim = {t0: performance.now(), ms: 900, fromT: st.controls.target.clone(), toT: new THREE.Vector3(),
             fromC: st.camera.position.clone(), toC: new THREE.Vector3(-120, 110, 160)};
  const pin = new THREE.Mesh(new THREE.CylinderGeometry(1.2, 1.2, 40, 10), new THREE.MeshBasicMaterial({color: 0x25c7ff}));
  pin.position.set(0, 20, 0); st.scene.add(pin);
  const tag = label && label.length ? labelFor(label.length > 60 ? label.slice(0, 58) + '…' : label, 0x25c7ff) : null;
  if (tag) { tag.position.set(0, 42, 0); st.scene.add(tag); }
  setTimeout(() => { if (st) { st.scene.remove(pin); if (tag) st.scene.remove(tag); } }, 20000);
  poll();
}

function searchBox(){
  const w = document.createElement('div');
  w.style.cssText = 'position:absolute;left:8px;top:8px;z-index:3;font:12px Arial';
  w.innerHTML = '<div style="display:flex;gap:4px;background:rgba(3,16,26,.92);border:1px solid #155879;border-radius:5px;padding:4px">' +
    '<input type="search" placeholder="Search address or lat, lon" aria-label="Search" style="width:220px;max-width:46vw;background:#020a10;color:#d9efff;border:1px solid #155879;border-radius:3px;padding:6px 8px;font:12px Arial;outline:none">' +
    '<button type="button" title="Search" style="background:#05131d;color:#5bd9ff;border:1px solid #155879;border-radius:3px;min-width:30px;cursor:pointer;font:bold 14px Arial">⌕</button>' +
    '<button type="button" title="Locate me" style="background:#05131d;color:#5bd9ff;border:1px solid #155879;border-radius:3px;min-width:30px;cursor:pointer;font:bold 14px Arial">◎</button></div>' +
    '<div class="l4d-res" hidden style="margin-top:4px;background:rgba(3,16,26,.96);border:1px solid #155879;border-radius:5px;max-width:300px;overflow:hidden"></div>';
  ['pointerdown', 'pointerup', 'wheel', 'keydown'].forEach(ev => w.addEventListener(ev, e => e.stopPropagation()));
  const input = w.querySelector('input'), [go, me] = w.querySelectorAll('button'), list = w.querySelector('.l4d-res');
  const row = 'padding:7px 9px;color:#cfeeff;border-bottom:1px solid #123447;cursor:pointer';
  const note = t => { list.hidden = false; list.innerHTML = `<div style="${row};cursor:default;color:#8ba9b8">${esc(t)}</div>`; };
  const search = async () => {
    const q = input.value.trim();
    if (q.length < 3) { note('Type at least 3 letters, or coordinates like 33.89, 35.50'); return; }
    const m = q.match(/^\s*(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$/);
    if (m && Math.abs(+m[1]) <= 90 && Math.abs(+m[2]) <= 180) { list.hidden = true; recentre(+m[1], +m[2], q); return; }
    note('Searching…');
    let d;
    try { d = await fetch('/api/geocode?q=' + encodeURIComponent(q)).then(r => r.json()); } catch (e) { note('No answer from the dashboard.'); return; }
    if (!d.ok) { note(d.error || 'Search failed.'); return; }
    if (!d.results.length) { note('Nothing found. Try a street and town, or coordinates.'); return; }
    list.innerHTML = d.results.map((r, i) => `<div data-i="${i}" style="${row}">${esc(r.name)}</div>`).join('');
    list.querySelectorAll('[data-i]').forEach(el => el.onclick = () => {
      const r = d.results[+el.dataset.i]; list.hidden = true; input.value = r.name; recentre(r.lat, r.lon, r.name);
    });
    if (d.results.length === 1) list.querySelector('[data-i]').click();
  };
  go.onclick = search;
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); search(); } if (e.key === 'Escape') list.hidden = true; });
  me.onclick = () => {
    const site = async why => {
      try { const d = await fetch('/api/safety', {cache: 'no-store'}).then(r => r.json()); const p = d && d.site && d.site.pos;
        if (p) { recentre(p[0], p[1], 'Site'); note(why + ' Showing the site instead.'); setTimeout(() => list.hidden = true, 4000); return; } } catch (e) {}
      note(why);
    };
    if (!navigator.geolocation) { site('This browser can\'t give a location.'); return; }
    note('Finding where you are…');
    navigator.geolocation.getCurrentPosition(p => { list.hidden = true; recentre(p.coords.latitude, p.coords.longitude, `You are here (±${Math.round(p.coords.accuracy)} m)`); },
      err => site(err.code === 1 ? 'Location is blocked for this page (allow it in the browser\'s address bar).' : 'This computer could not find its location.'),
      {enableHighAccuracy: true, timeout: 10000, maximumAge: 60000});
  };
  return w;
}

function latlon(v){
  const c = st.centre;
  return {lat: c.lat - v.z / M_LAT, lon: c.lon + v.x / (M_LON * Math.cos(c.lat * Math.PI / 180))};
}

function pick(e){
  if (!st.centre) return;
  const r = st.renderer.domElement.getBoundingClientRect(), ray = new THREE.Raycaster();
  ray.setFromCamera(new THREE.Vector2((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1), st.camera);
  const bodies = Object.entries(st.drones).filter(([, o]) => o.root.visible && o.body.visible).map(([slot, o]) => ({slot, body: o.body}));
  const hit = ray.intersectObjects(bodies.map(b => b.body), true)[0];
  if (hit) {
    const b = bodies.find(x => { let n = hit.object; while (n) { if (n === x.body) return true; n = n.parent; } return false; });
    if (b) { focus(b.slot); return; }
  }
  const p = new THREE.Vector3();
  if (!ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), p)) return;
  if (st.hooks.click) { const ll = latlon(p); st.hooks.click(ll.lat, ll.lon); setTimeout(draft, 50); }
}

// Fly the camera to a drone (clicking its name below the view, or the drone itself).
function focus(slot){
  const o = st.drones[slot];
  if (!o || !o.body.visible) { st.info.textContent = (o && o.data ? o.data.label : 'That drone') + ' has no position yet.'; return; }
  st.hidden.delete(slot); store.set('l4d-hidden', [...st.hidden]); o.root.visible = true;
  if (st.follow && st.follow !== slot) { st.follow = ''; store.set('l4d-follow', ''); }
  st.last = null; st.barKey = '';
  const to = o.body.position.clone(), dir = st.camera.position.clone().sub(st.controls.target).setY(0);
  if (dir.length() < 1) dir.set(-1, 0, 1);
  dir.normalize().multiplyScalar(70);
  st.anim = {t0: performance.now(), ms: 900, fromT: st.controls.target.clone(), toT: to,
             fromC: st.camera.position.clone(), toC: to.clone().add(new THREE.Vector3(dir.x, 45, dir.z))};
}

function animate(){
  const a = st.anim;
  if (!a) return;
  const k = Math.min(1, (performance.now() - a.t0) / a.ms), e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
  st.controls.target.lerpVectors(a.fromT, a.toT, e); st.camera.position.lerpVectors(a.fromC, a.toC, e);
  if (k >= 1) { st.anim = null; if (st.follow) st.last = st.drones[st.follow] ? st.drones[st.follow].body.position.clone() : null; }
}

// What is being drawn on the page: the route (not yet flown) at its height, and a no-fly zone's corners.
function draft(){
  if (!st || !st.centre || !st.hooks.draft) return;
  const d = st.hooks.draft() || {}, key = JSON.stringify(d);
  if (key === st.draftKey) return;
  st.draftKey = key; st.groups.draft.clear();
  const route = d.route || [], alt = d.alt || 30, zone = d.zone || [];
  if (route.length) {
    const pts = route.map(p => enu(p.lat, p.lon, alt));
    if (pts.length > 1) st.groups.draft.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({color: 0xffd23f})));
    pts.forEach((v, i) => {
      const s = new THREE.Mesh(new THREE.SphereGeometry(2.2, 14, 10), new THREE.MeshBasicMaterial({color: 0xffd23f})); s.position.copy(v);
      const post = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(v.x, 0, v.z), v]), new THREE.LineBasicMaterial({color: 0xffd23f, transparent: true, opacity: 0.4}));
      const tag = label(`Stop ${i + 1} · ${Math.round(alt)} m`, 0xffd23f); tag.position.copy(v);
      st.groups.draft.add(s, post, tag);
    });
  }
  if (zone.length) {
    const pts = zone.map(p => enu(p[0], p[1], 0.5));
    st.groups.draft.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts.length > 2 ? [...pts, pts[0]] : pts), new THREE.LineBasicMaterial({color: 0xff4d6a})));
    pts.forEach(v => { const post = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.8, 30, 8), new THREE.MeshBasicMaterial({color: 0xff4d6a, transparent: true, opacity: 0.7}));
      post.position.set(v.x, 15, v.z); st.groups.draft.add(post); });
  }
}

function enu(lat, lon, alt){
  const c = st.centre;
  return new THREE.Vector3((lon - c.lon) * M_LON * Math.cos(c.lat * Math.PI / 180), alt || 0, -(lat - c.lat) * M_LAT);
}

async function poll(){
  let d;
  try { d = await fetch('/api/live4d?drone=' + encodeURIComponent(st.drone), {cache: 'no-store'}).then(r => r.json()); }
  catch (e) { if (st) st.info.textContent = 'Lost contact with the dashboard'; return; }
  if (!st || !d.ok) { if (st) st.info.textContent = d && d.error || 'No data'; return; }
  if (!st.centre) { const f = focusGet(); st.centre = f ? {lat: f.lat, lon: f.lon} : d.centre; ground(); }
  zones(d.zones || []);
  cams(d.cameras || []);
  site(d.maps || []);
  drones(d.drones || []);
  aircraft(d.aircraft || []);
  draft();
  barUi(d.drones || []);
  const flying = (d.drones || []).filter(x => x.flying).length;
  st.info.innerHTML = `<b>4D LIVE</b> · ${d.drones.length} drone${d.drones.length === 1 ? '' : 's'}, ${flying} flying` +
    (d.aircraft.length ? ` · ✈ ${d.aircraft.length} aircraft` : '') + ' · click the ground to add a route stop (or a zone corner while drawing a zone), click a drone to go to it';
}

// ----- ground: satellite tiles round the centre (from the dashboard's offline tile cache) -----
function ground(){
  const z = 17, n = 2 ** z, c = st.centre, R = 2;  // 5 × 5 tiles ≈ 1.2 km across
  const tx = Math.floor((c.lon + 180) / 360 * n), ty = Math.floor((1 - Math.log(Math.tan(c.lat * Math.PI / 180) + 1 / Math.cos(c.lat * Math.PI / 180)) / Math.PI) / 2 * n);
  const lon = x => x / n * 360 - 180, lat = y => Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI;
  const nw = enu(lat(ty - R), lon(tx - R), 0), se = enu(lat(ty + R + 1), lon(tx + R + 1), 0);
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 256 * (2 * R + 1);
  const g = canvas.getContext('2d'); g.fillStyle = '#0b1c26'; g.fillRect(0, 0, canvas.width, canvas.height);
  const tex = new THREE.CanvasTexture(canvas); tex.colorSpace = THREE.SRGBColorSpace;
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(se.x - nw.x, se.z - nw.z), new THREE.MeshBasicMaterial({map: tex}));
  plane.rotation.x = -Math.PI / 2; plane.position.set((nw.x + se.x) / 2, -0.2, (nw.z + se.z) / 2);
  st.scene.add(plane);
  const grid = new THREE.GridHelper(4000, 40, 0x155879, 0x0d2c3d); grid.position.y = -0.5; st.scene.add(grid);
  st.groundObjs = [plane, grid];
  for (let i = -R; i <= R; i++) for (let j = -R; j <= R; j++) {
    const img = new Image();
    img.onload = () => { g.drawImage(img, (i + R) * 256, (j + R) * 256); tex.needsUpdate = true; };
    img.src = `/tiles/sat/${z}/${tx + i}/${ty + j}`;
  }
}

// ----- no-fly zones and airspace as see-through volumes up to the drones' 120 m ceiling -----
function zones(list){
  const key = JSON.stringify(list.map(z => [z.id, z.points.length]));
  if (key === st.zonesKey) return;
  st.zonesKey = key; st.groups.zones.clear();
  for (const z of list) {
    const shape = new THREE.Shape(z.points.map(p => { const v = enu(p.lat, p.lon, 0); return new THREE.Vector2(v.x, -v.z); }));
    const geo = new THREE.ExtrudeGeometry(shape, {depth: 120, bevelEnabled: false});
    geo.rotateX(-Math.PI / 2);
    const color = ZONE[z.source] || 0xff4d6a;
    st.groups.zones.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({color, transparent: true, opacity: 0.13, depthWrite: false})));
    st.groups.zones.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({color, transparent: true, opacity: 0.6})));
  }
}

// ----- cameras: what each one sees on the ground (from the Coverage page) -----
function cams(list){
  const key = JSON.stringify(list);
  if (key === st.camsKey) return;
  st.camsKey = key; st.groups.cams.clear();
  for (const c of list) {
    const at = enu(c.lat, c.lon, 0), v = c.view, n = 18;
    const shape = new THREE.Shape(); shape.moveTo(at.x, -at.z);
    for (let i = 0; i <= n; i++) {
      const b = (v.heading - v.fov / 2 + v.fov * i / n) * Math.PI / 180;
      shape.lineTo(at.x + v.range * Math.sin(b), -at.z + v.range * Math.cos(b));
    }
    const geo = new THREE.ShapeGeometry(shape); geo.rotateX(-Math.PI / 2);
    const fan = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({color: 0x2bc0ff, transparent: true, opacity: 0.22, depthWrite: false, side: THREE.DoubleSide}));
    fan.position.y = 0.3; st.groups.cams.add(fan);
    const post = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 6), new THREE.MeshBasicMaterial({color: 0x5bd9ff}));
    post.position.set(at.x, 3, at.z); st.groups.cams.add(post);
    const tag = label('▣ ' + c.name, '#9edfff'); tag.position.set(at.x, 9, at.z); st.groups.cams.add(tag);
  }
}

// ----- the finished 3D site map (from 3D Maps), placed where it was flown -----
function site(maps){
  const m = maps[0], key = m ? m.id : '';
  if (key === st.siteKey) return;
  st.siteKey = key; st.groups.site.clear();
  if (!m) return;
  const base = `/maps/${m.id}/model/`, mtl = new MTLLoader();
  mtl.setPath(base); mtl.setResourcePath(base);
  const place = materials => { const obj = new OBJLoader(); if (materials) obj.setMaterials(materials); obj.setPath(base);
    obj.load(m.model, o => {
      o.traverse(c => { if (c.isMesh) { const ms = Array.isArray(c.material) ? c.material : [c.material];
        c.material = ms.map(x => new THREE.MeshBasicMaterial({map: x.map || null, color: x.map ? 0xffffff : 0x8fb7c9, side: THREE.DoubleSide}));
        if (c.material.length === 1) c.material = c.material[0]; } });
      o.rotation.x = -Math.PI / 2;  // the model is east/north/up in metres from its origin
      const g = new THREE.Group(); g.add(o); g.updateMatrixWorld(true);
      const low = new THREE.Box3().setFromObject(g).min.y, at = enu(m.origin.lat, m.origin.lon, 0);
      g.position.set(at.x, -low, at.z);
      if (st && st.siteKey === key) st.groups.site.add(g);
    });
  };
  mtl.load(m.model.replace(/\.obj$/i, '.mtl'), x => { x.preload(); place(x); }, undefined, () => place(null));
}

// ----- drones: body, heading, height stick, label, trail, the route it is flying -----
function labelFor(text, color){ return label(text, color); }
function label(text, color){
  const c = document.createElement('canvas'), g = c.getContext('2d');
  g.font = 'bold 40px Arial';
  const w = Math.ceil(g.measureText(text).width) + 40;  // as wide as the text
  c.width = w; c.height = 96;
  g.fillStyle = 'rgba(3,16,26,.85)'; g.fillRect(0, 0, w, 96);
  g.strokeStyle = '#' + color.toString(16).padStart(6, '0'); g.lineWidth = 6; g.strokeRect(3, 3, w - 6, 90);
  g.fillStyle = '#e9f8ff'; g.font = 'bold 40px Arial'; g.textBaseline = 'middle'; g.fillText(text, 20, 50);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), depthTest: false, sizeAttenuation: false}));
  s.scale.set(0.0375 * w / 96, 0.0375, 1); s.center.set(0.5, -0.4); s.renderOrder = 10; s.userData.text = text;
  return s;
}

function droneMesh(color){
  const g = new THREE.Group(), mat = new THREE.MeshLambertMaterial({color});
  g.scale.setScalar(1.6);
  g.add(new THREE.Mesh(new THREE.BoxGeometry(3.2, 1.2, 4.4), mat));
  for (const [x, z] of [[-3, -3], [3, -3], [-3, 3], [3, 3]]) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.4, 4.6), mat);
    arm.position.set(x / 2, 0, z / 2); arm.rotation.y = Math.atan2(x, z); g.add(arm);
    const rotor = new THREE.Mesh(new THREE.CylinderGeometry(1.7, 1.7, 0.2, 20), new THREE.MeshBasicMaterial({color: 0xe9f8ff, transparent: true, opacity: 0.55}));
    rotor.position.set(x, 0.5, z); g.add(rotor);
  }
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.9, 2.4, 12), new THREE.MeshBasicMaterial({color: 0xffffff}));
  nose.rotation.x = -Math.PI / 2; nose.position.z = -3.4; g.add(nose);  // points the way the drone faces
  return g;
}

function drones(list){
  const seen = new Set();
  list.forEach((d, i) => {
    seen.add(d.slot);
    let o = st.drones[d.slot];
    const color = COLORS[i % COLORS.length];
    if (!o) {
      o = st.drones[d.slot] = {color, root: new THREE.Group(), body: droneMesh(color), stick: null, tag: null,
        trail: new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({color})),
        route: new THREE.Group(), home: new THREE.Mesh(new THREE.RingGeometry(3, 4.5, 32), new THREE.MeshBasicMaterial({color, side: THREE.DoubleSide}))};
      o.stick = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), new THREE.LineDashedMaterial({color, dashSize: 3, gapSize: 2}));
      o.home.rotation.x = -Math.PI / 2;
      o.root.add(o.body, o.stick, o.trail, o.route, o.home);
      st.scene.add(o.root);
    }
    o.root.visible = !st.hidden.has(d.slot);
    o.data = d;
    if (d.home) o.home.position.copy(enu(d.home.lat, d.home.lon, 0.3));
    o.home.visible = !!d.home;
    const has = d.lat != null;
    o.body.visible = o.stick.visible = has;
    if (has) {
      const p = enu(d.lat, d.lon, Math.max(0, d.altitude || 0) + 1);
      o.body.position.copy(p);
      o.body.rotation.y = -((d.heading || 0) * Math.PI / 180);
      o.stick.geometry.setFromPoints([new THREE.Vector3(p.x, 0, p.z), p]); o.stick.computeLineDistances();
      const text = `${d.label} · ${Math.round(d.altitude || 0)} m${d.battery != null ? ' · ' + d.battery + '%' : ''}${d.mission ? ' · ' + d.mission : ''}`;
      if (!o.tag || o.tag.userData.text !== text) { if (o.tag) o.root.remove(o.tag); o.tag = label(text, color); o.root.add(o.tag); }
      o.tag.position.copy(p);
    } else if (o.tag) { o.root.remove(o.tag); o.tag = null; }
    const pts = (d.trail || []).map(t => enu(t[0], t[1], Math.max(0, t[2]) + 1));
    o.trail.geometry.setFromPoints(pts.length > 1 ? pts : [new THREE.Vector3(), new THREE.Vector3()]);
    o.trail.visible = pts.length > 1;
    const rk = JSON.stringify(d.route || null);
    if (rk !== o.routeKey) {
      o.routeKey = rk; o.route.clear();
      if (d.route && d.route.points.length) {
        const rp = d.route.points.map(p => enu(p.lat, p.lon, d.route.alt));
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(rp), new THREE.LineDashedMaterial({color, dashSize: 6, gapSize: 4, transparent: true, opacity: 0.8}));
        line.computeLineDistances(); o.route.add(line);
        rp.forEach((v, k) => { const s = new THREE.Mesh(new THREE.SphereGeometry(k + 1 === d.route.index ? 2.6 : 1.6, 14, 10), new THREE.MeshBasicMaterial({color}));
          s.position.copy(v); o.route.add(s); });
      }
    }
    if (st.follow === d.slot && has && o.root.visible && !st.anim) followTo(o.body.position);
  });
  for (const k of Object.keys(st.drones)) if (!seen.has(k)) { st.scene.remove(st.drones[k].root); delete st.drones[k]; }
}

function followTo(p){
  const c = st.controls;
  if (!st.last) {  // start following: look at the drone from behind and above it
    c.target.copy(p); st.camera.position.copy(p).add(new THREE.Vector3(-45, 35, 55)); st.last = p.clone(); return;
  }
  const delta = p.clone().sub(st.last);
  c.target.add(delta); st.camera.position.add(delta); st.last = p.clone();
}

// ----- crewed aircraft from the air-traffic watch (Flight safety) -----
function aircraft(list){
  st.groups.aircraft.clear();
  for (const a of list) {
    const h = a.height_ft == null ? 300 : Math.max(30, a.height_ft * 0.3048), p = enu(a.lat, a.lon, h);
    const color = a.threat ? 0xff4d6a : 0xffd23f;
    const cone = new THREE.Mesh(new THREE.ConeGeometry(6, 22, 12), new THREE.MeshBasicMaterial({color}));
    cone.rotation.x = -Math.PI / 2; const g = new THREE.Group(); g.add(cone);
    g.position.copy(p); g.rotation.y = -((a.track || 0) * Math.PI / 180);
    const stick = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(p.x, 0, p.z), p]), new THREE.LineBasicMaterial({color, transparent: true, opacity: 0.35}));
    const tag = label(`✈ ${a.call || a.hex} · ${a.height_ft == null ? '?' : Math.round(a.height_ft / 100) * 100} ft`, color);
    tag.position.copy(p);
    st.groups.aircraft.add(g, stick, tag);
  }
}

// ----- one switch per drone: show / hide, and follow -----
function barUi(list){
  const key = JSON.stringify(list.map(d => [d.slot, d.label, st.hidden.has(d.slot), st.follow === d.slot, !!d.flying]));
  if (key === st.barKey) return;
  st.barKey = key;
  st.bar.innerHTML = list.map((d, i) => {
    const col = '#' + COLORS[i % COLORS.length].toString(16).padStart(6, '0'), on = !st.hidden.has(d.slot);
    return `<span class="l4d-chip" style="border-color:${col}"><label title="Show or hide ${esc(d.label)}"><input type="checkbox" class="toggle" data-l4d-show="${esc(d.slot)}" ${on ? 'checked' : ''}></label>
      <button type="button" class="l4d-go" data-l4d-go="${esc(d.slot)}" title="Go to ${esc(d.label)}"><i style="background:${col}"></i>${esc(d.label)}${d.flying ? ' · flying' : ''}</button>
      <button type="button" class="${st.follow === d.slot ? 'on' : ''}" data-l4d-follow="${esc(d.slot)}">${st.follow === d.slot ? 'Following' : 'Follow'}</button></span>`;
  }).join('') + `<button type="button" class="l4d-reset" data-l4d-reset="1">Whole site</button>`;
  st.bar.querySelectorAll('[data-l4d-show]').forEach(el => el.onchange = () => {
    const s = el.dataset.l4dShow; el.checked ? st.hidden.delete(s) : st.hidden.add(s);
    store.set('l4d-hidden', [...st.hidden]); st.barKey = '';
  });
  st.bar.querySelectorAll('[data-l4d-go]').forEach(el => el.onclick = () => focus(el.dataset.l4dGo));
  st.bar.querySelectorAll('[data-l4d-follow]').forEach(el => el.onclick = () => {
    st.follow = st.follow === el.dataset.l4dFollow ? '' : el.dataset.l4dFollow; st.last = null;
    store.set('l4d-follow', st.follow); st.barKey = '';
  });
  st.bar.querySelector('[data-l4d-reset]').onclick = () => {
    st.follow = ''; st.last = null; store.set('l4d-follow', ''); st.barKey = '';
    st.anim = {t0: performance.now(), ms: 900, fromT: st.controls.target.clone(), toT: new THREE.Vector3(),
               fromC: st.camera.position.clone(), toC: new THREE.Vector3(-120, 110, 160)};
  };
}
"""
