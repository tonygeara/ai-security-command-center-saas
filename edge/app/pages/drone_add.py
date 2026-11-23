"""The Add a drone page: pick the kind of drone from a list (DJI, PX4 / ArduPilot, virtual, drone-in-a-box systems,
Autel, FlytBase, ROS 2), or "Others" to let the PC find a MAVLink aircraft on the network and say what it is."""
BODY = r"""
<style>
.da-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.da-card{border:1px solid #155879;border-radius:5px;background:#05131d;padding:12px;cursor:pointer;text-align:left;color:#cfe9f7;font:inherit}
.da-card:hover,.da-card.on{border-color:#38c6ff;background:#071d2b}
.da-card h3{margin:0 0 4px;font-size:14px;color:#e9f8ff;display:flex;justify-content:space-between;gap:8px;align-items:center}
.da-card p{margin:0;font-size:12px;color:#8fb3c7}
.da-tag{font-size:9px;letter-spacing:1px;border-radius:3px;padding:2px 6px;white-space:nowrap}
.da-tag.ready{color:#7dffb0;border:1px solid #1f7a4a}.da-tag.req{color:#ffcf7a;border:1px solid #7a5a12}.da-tag.auto{color:#9fdcff;border:1px solid #1d6a91}
#daForm{margin-top:16px}
#daForm label{display:block;margin:8px 0 4px}
#daForm input,#daForm textarea{width:100%;max-width:520px}
.da-found{border:1px solid #155879;border-radius:5px;padding:10px;margin:8px 0;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.da-mine{margin-top:16px}
@media(max-width:700px){.da-grid{grid-template-columns:1fr}}
</style>
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Drones</div><h1 class="page-title">Add a drone</h1>
<div class="page-sub">Choose the kind of drone. Every drone added here works with the whole system: live view, routes, patrols, alarm responses, the backup drone, no-fly zones and the Drone Grid. Not sure what it is? Choose <b>Others</b> at the end and the PC will find it and tell you its model.</div></div>
<div class="actions"><a class="hud-btn" href="/drone-control">← Drone page</a></div></div>
<section class="panel"><div class="panel-head"><div class="panel-title">✈ Kind of drone</div><div class="live" id="daUsed"></div></div>
<div class="panel-body"><div class="da-grid" id="daList"></div>
<div id="daForm"></div><div id="daMsg" class="hud-msg"></div>
<div class="da-mine" id="daMine"></div></div></section>
</main>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
function msg(t,ok){const e=$('daMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
const KINDS=[
 {k:'dji',t:'DJI (Drone Link app)',d:'DJI drones with a phone and controller running the Drone Link app (Mini, Air, Mavic, Matrice). Each gets a pairing QR code.',tag:'ready'},
 {k:'px4',t:'PX4',d:'Drones running PX4 (Holybro, ModalAI, Auterion-based and many custom builds), over a telemetry radio, a companion computer or the network (MAVLink).',tag:'ready'},
 {k:'ardupilot',t:'ArduPilot',d:'Drones running ArduPilot / ArduCopter (CubePilot, Matek, Pixhawk builds and many commercial drones), over a radio, companion computer or network (MAVLink).',tag:'ready'},
 {k:'mavsdk',t:'Other MAVLink / MAVSDK drone',d:'Any autopilot that speaks MAVLink (also MAVSDK-based systems and simulators such as SITL or Gazebo).',tag:'ready'},
 {k:'dock',t:'DJI Dock',d:'DJI Dock 2 / Dock 3 / Dock 4: set up from the Drone page by an admin (DJI Cloud API).',tag:'ready'},
 {k:'virtual',t:'Virtual drone',d:'A simulated drone for tests, training and demos. Never controls a real aircraft.',tag:'ready'},
 {k:'azur',t:'Azur Drones (Skeyetech)',d:'Drone-in-a-box security system. Connected through Azur Drones’ partner API.',tag:'req'},
 {k:'asylon',t:'Asylon (DroneSentry)',d:'Robotic security drone-in-a-box. Connected through Asylon’s partner API.',tag:'req'},
 {k:'nightingale',t:'Nightingale Security',d:'Autonomous security drone-in-a-box. Connected through Nightingale’s partner API.',tag:'req'},
 {k:'percepto',t:'Percepto',d:'Drone-in-a-box for industrial sites. Connected through Percepto’s partner API.',tag:'req'},
 {k:'sunflower',t:'Sunflower Labs',d:'Home and estate security drone with its own base station. Connected through Sunflower Labs’ partner API.',tag:'req'},
 {k:'autel',t:'Autel Robotics',d:'EVO II / EVO Max drones and the EVO Nest dock. Connected through Autel’s SDK.',tag:'req'},
 {k:'flytbase',t:'FlytBase',d:'Drones and docks already managed in FlytBase. Connected through FlytBase’s API.',tag:'req'},
 {k:'ros2',t:'ROS 2 robot or drone',d:'Robots and drones running ROS 2 (MAVROS / px4_ros_com bridges). PX4 and ArduPilot drones can also be added directly above.',tag:'req'},
 {k:'others',t:'Others (find it automatically)',d:'The PC listens on the network for MAVLink drones, tells you the make (PX4, ArduPilot…) and type, and adds the one you choose. Anything it can’t find: ask us to connect it.',tag:'auto'},
];
const TAG={ready:'READY',req:'ON REQUEST',auto:'AUTO-DETECT'};
let cur='',info={};
function draw(){$('daList').innerHTML=KINDS.map(x=>`<button class="da-card ${cur===x.k?'on':''}" onclick="pick('${x.k}')"><h3>${esc(x.t)}<span class="da-tag ${x.tag}">${TAG[x.tag]}</span></h3><p>${esc(x.d)}</p></button>`).join('')}
function mavForm(title,hint){return `<h3>${esc(title)}</h3>
 <div class="muted">${hint}</div>
 <label>Name</label><input id="mName" maxlength="40" placeholder="e.g. North patrol drone">
 <label>Connection</label><input id="mConn" value="udpin:0.0.0.0:14550" placeholder="udpin:0.0.0.0:14550 or tcp:192.168.1.50:5760">
 <div class="muted" style="margin-top:4px">Telemetry radio or companion computer sending to this PC: <code>udpin:0.0.0.0:14550</code>. A drone or companion computer listening on TCP: <code>tcp:&lt;its address&gt;:5760</code>. Simulator (SITL): <code>udpin:0.0.0.0:14540</code> (PX4) or <code>tcp:127.0.0.1:5760</code> (ArduPilot).</div>
 <div class="actions" style="margin-top:10px"><button class="hud-btn primary" onclick="addMav()">Add drone</button><button class="hud-btn" onclick="pick('others')">Find it on the network instead</button></div>`}
function pick(k){cur=k;draw();msg('');const f=$('daForm');const x=KINDS.find(y=>y.k===k);
 if(k==='dji'){f.innerHTML=`<h3>DJI drone</h3><div class="muted">Adds a drone slot with its own pairing QR code and video. Pair it from the Drone page with the Drone Link app on the controller’s phone. Frigate restarts (about 20 s).</div><div class="actions" style="margin-top:10px"><button class="hud-btn primary" onclick="addDji()">Add DJI drone</button></div>`}
 else if(k==='px4')f.innerHTML=mavForm('PX4 drone','In QGroundControl or the companion computer, send MAVLink to this PC’s address. The drone flies routes in Hold/Position modes; keyboard and gamepad flying is not available for PX4 yet.');
 else if(k==='ardupilot')f.innerHTML=mavForm('ArduPilot drone','In Mission Planner or on the companion computer (mavlink-router, MAVProxy), send MAVLink to this PC’s address. The PC flies it in GUIDED mode.');
 else if(k==='mavsdk')f.innerHTML=mavForm('MAVLink drone','Any autopilot that speaks MAVLink 2 with the common command set (take-off, reposition, return to launch, land).');
 else if(k==='dock'){f.innerHTML=`<h3>DJI Dock</h3><div class="muted">Docks are registered on the Drone page under <b>DJI Docks</b> (admins). They need the DJI Docks licence feature.</div><div class="actions" style="margin-top:10px"><a class="hud-btn primary" href="/drone-control#docks">Open DJI Docks</a></div>`}
 else if(k==='virtual'){f.innerHTML=`<h3>Virtual drone</h3><div class="muted">Choose its start point on the map in the Virtual drones tab.</div><div class="actions" style="margin-top:10px"><a class="hud-btn primary" href="/virtual-drones">Open Virtual drones</a></div>`}
 else if(k==='others'){f.innerHTML=`<h3>Find a drone on the network</h3><div class="muted">Switch the drone on and make sure its radio or companion computer sends MAVLink to this PC (UDP ports 14550, 14540, 14551 or 14560). The PC listens for about 6 seconds.</div>
  <div class="actions" style="margin-top:10px"><button class="hud-btn primary" id="scanBtn" onclick="scan()">Search now</button></div><div id="found"></div>
  <div class="muted" style="margin-top:10px">Nothing found, or a drone that doesn’t use MAVLink? <a href="#" onclick="pick('other');return false">Ask us to connect it</a>.</div>`}
 else{const name=k==='other'?'Another drone or dock':x.t;f.innerHTML=`<h3>${esc(name)}</h3><div class="muted">${k==='other'?'Tell us the make and model.':esc(x.d)} This one needs a partner agreement and set-up by your provider. Send a request and they will contact you.</div>
  <label>Your email</label><input id="rEmail" type="email" placeholder="you@company.com">
  <label>Company</label><input id="rCompany" maxlength="160">
  <label>Details (models, how many, site)</label><textarea id="rDetails" rows="3" maxlength="1500"></textarea>
  <div class="actions" style="margin-top:10px"><button class="hud-btn primary" onclick="askIntegration('${k}')">Send request</button></div>`}
 f.scrollIntoView({behavior:'smooth',block:'nearest'})}
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});let d={};try{d=await r.json()}catch(e){}if(!r.ok&&d.ok===undefined)d={ok:false,error:r.status===403?'Only admins can add drones.':'Error '+r.status};return d}
async function addDji(){if(info.allowed===false){msg(info.message||'The licence’s drone limit is reached.',false);return}
 const d=await post('/api/drone/add');if(d.ok)location.href='/drone-control?drone='+encodeURIComponent(d.name);else msg(d.error||'Could not add a drone.',false)}
async function addMav(conn,name){conn=conn||$('mConn').value.trim();name=name??($('mName')?$('mName').value.trim():'');
 msg('Adding…');const d=await post('/api/mavlink',{connection:conn,name});
 if(d.ok){msg(d.label+' added. Waiting for it to connect…',true);setTimeout(()=>location.href='/drone-control?drone='+encodeURIComponent(d.drone),1500)}else msg(d.error||'Could not add the drone.',false)}
async function scan(){const b=$('scanBtn');b.disabled=true;b.textContent='Searching…';$('found').innerHTML='';
 const d=await post('/api/mavlink/scan');b.disabled=false;b.textContent='Search again';
 if(!d.ok){msg(d.error||'Search failed.',false);return}
 if(!d.found.length){$('found').innerHTML=`<p class="muted">No MAVLink drone heard on ports ${esc(d.ports.join(', '))}.</p>`;return}
 window._found=d.found;$('found').innerHTML=d.found.map((x,i)=>`<div class="da-found"><div><b>${esc(x.model)}</b><div class="muted">System ${esc(x.sysid)} · from ${esc(x.address||'?')} · port ${esc(x.port)}</div></div>
  <div class="actions"><input id="fName${i}" maxlength="40" placeholder="Name" value="${esc(x.model)}" style="width:180px"><button class="hud-btn primary" onclick="addFound(${i})">Add this drone</button></div></div>`).join('')}
function addFound(i){const x=window._found[i];addMav(x.connection,$('fName'+i).value.trim())}
async function askIntegration(k){const d=await post('/api/drone/integration-request',{kind:k,email:$('rEmail').value.trim(),company:$('rCompany').value.trim(),details:$('rDetails').value});
 msg(d.ok?d.message:(d.error||'Could not send.'),!!d.ok)}
async function removeMav(slot,label){if(!await uiConfirm('Remove '+label+'? Its routes and history stay.'))return;
 const r=await fetch('/api/mavlink/'+encodeURIComponent(slot),{method:'DELETE'});const d=await r.json().catch(()=>({}));if(d.ok)load();else uiAlert(d.error||'Could not remove it.')}
async function load(){try{info=await fetch('/api/cloud/can-add-source/drone').then(r=>r.json())}catch(e){info={}}
 $('daUsed').textContent=info.limit!=null?`${info.used??'?'} OF ${info.limit} DRONES`:'';
 try{const m=await fetch('/api/mavlink').then(r=>r.json());
  $('daMine').innerHTML=m.drones.length?'<h3>MAVLink drones on this PC</h3>'+m.drones.map(x=>`<div class="da-found"><div><b>${esc(x.label)}</b> <span class="muted">${esc(x.model||'waiting for the drone')} · ${esc(x.connection)} · ${x.aircraft_connected?'connected':'not heard yet'}</span></div><div class="actions"><a class="hud-btn" href="/drone-control?drone=${encodeURIComponent(x.drone)}">Open</a><button class="hud-btn" onclick="removeMav('${esc(x.drone)}','${esc(x.label)}')">Remove</button></div></div>`).join(''):''}catch(e){}}
draw();load();const q=new URLSearchParams(location.search).get('kind');if(q&&KINDS.some(x=>x.k===q))pick(q);
</script>
"""
