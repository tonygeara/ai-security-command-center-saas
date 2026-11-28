"""The Add Robot page: robots that can be connected to the system (robot dogs, humanoids, security patrol robots, hospital
and service robots, open ground robots), each on request, and "Others", which finds robots on the network."""

BODY = r"""
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Robots</div><h1 class="page-title">Add a robot</h1>
<div class="page-sub">Choose the kind of robot. Robots are connected by your provider: choose yours and send a request, and they set it up with you (its position on the map, patrols, live video into the AI, alarm responses). Not sure what it is? Choose <b>Others</b> at the end and the PC will look for it on the network.</div></div>
<div class="actions"><button class="hud-btn" onclick="location.href='/drone-control'">← Drone page</button></div></div>
<style>
.ra-group{margin:6px 0 10px;color:#5bd9ff;font:bold 11px Arial;letter-spacing:2px;text-transform:uppercase}
.ra-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px;margin-bottom:16px}
.ra-card{display:flex;flex-direction:column;gap:6px;text-align:left;padding:12px;border:1px solid #155879;border-radius:5px;background:#05131d;color:#e9f8ff;cursor:pointer;font:inherit}
.ra-card:hover,.ra-card.on{border-color:#36cfff;box-shadow:0 0 12px rgba(53,203,255,.18)}
.ra-card h3{margin:0;font-size:14px;display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
.ra-card p{margin:0;color:#8ba9b8;font-size:12px;line-height:1.45}
.ra-tag{font-size:9px;letter-spacing:1.2px;padding:2px 6px;border:1px solid;border-radius:3px;white-space:nowrap}
.ra-tag.req{color:#ffcf7a;border-color:#7a5a1a}.ra-tag.auto{color:#5bd9ff;border-color:#155879}
.ra-found{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 12px;border:1px solid #123d55;border-radius:4px;margin-top:8px;flex-wrap:wrap}
#raForm label{display:block;margin-top:8px}#raForm input,#raForm textarea{width:100%;box-sizing:border-box}
</style>
<section class="panel"><div class="panel-head"><div class="panel-title">🤖 Kind of robot</div><div class="live" id="raCount"></div></div>
<div class="panel-body"><div id="raList"></div>
<div id="raForm" class="panel" style="padding:14px;margin-top:4px"><p class="muted" style="margin:0">Choose a robot above.</p></div>
<div id="raMsg" class="hud-msg"></div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">⌛ Requested robots</div></div>
<div class="panel-body"><div id="raRequests" class="muted">Loading…</div></div></section>
</main>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
function msg(t,ok){const e=$('raMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t||''}
let KINDS=[],GROUPS=[],cur='',found=[];
function draw(){$('raList').innerHTML=GROUPS.map(g=>`<div class="ra-group">${esc(g)}</div><div class="ra-list">`+KINDS.filter(x=>x.group===g).map(x=>
  `<button class="ra-card ${cur===x.k?'on':''}" onclick="pick('${x.k}')"><h3>${esc(x.t)}<span class="ra-tag ${x.k==='others'?'auto':'req'}">${x.k==='others'?'AUTO-DETECT':'ON REQUEST'}</span></h3><p>${esc(x.d)}</p></button>`).join('')+'</div>').join('');
  $('raCount').textContent=(KINDS.length-1)+' ROBOTS'}
function requestForm(k,title,note,device){return `<h3 style="margin-top:0">${esc(title)}</h3><div class="muted">${esc(note)}</div>
  <label>Your email</label><input id="rEmail" type="email" placeholder="you@company.com">
  <label>Company</label><input id="rCompany" maxlength="160">
  <label>Details (model, how many, where on the site, what it should do)</label><textarea id="rDetails" rows="3" maxlength="1500">${esc(device?device.details:'')}</textarea>
  <div class="actions" style="margin-top:10px"><button class="hud-btn primary" onclick="ask('${k}',${device?found.indexOf(device):-1})">Send request</button></div>`}
function pick(k){cur=k;draw();msg('');const f=$('raForm'),x=KINDS.find(y=>y.k===k);
  if(k==='others'){f.innerHTML=`<h3 style="margin-top:0">Find a robot on the network</h3><div class="muted">Switch the robot on and connect it to the same network as this PC (or connect this PC to the robot's own Wi-Fi). The PC listens for about 6 seconds for ROS 2 robots (Unitree and most research and service robots), ArduPilot / PX4 rovers and boats, and robots answering at their makers' usual addresses (such as Boston Dynamics Spot). Nothing is sent to the robot and nothing moves.</div>
    <div class="actions" style="margin-top:10px"><button class="hud-btn primary" id="scanBtn" onclick="scan()">Search now</button></div><div id="found"></div>
    <div class="muted" style="margin-top:10px">Not found? <a href="#" onclick="pick('other');return false" style="color:#5bd9ff">Tell us about it instead</a>.</div>`}
  else f.innerHTML=requestForm(k,k==='other'?'Another robot':x.t,k==='other'?'Tell us the make and model.':x.d+' Connecting it needs set-up by your provider: send a request and they will contact you.');
  f.scrollIntoView({behavior:'smooth',block:'nearest'})}
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});let d={};try{d=await r.json()}catch(e){}
  if(!r.ok&&d.ok===undefined)d={ok:false,error:r.status===403?'Only admins can add robots.':'No answer from the PC.'};if(r.status===403&&!d.error)d.error='Only admins can add robots.';return d}
async function scan(){const b=$('scanBtn');b.disabled=true;b.textContent='Searching…';$('found').innerHTML='';
  const d=await post('/api/robot/scan');b.disabled=false;b.textContent='Search again';
  if(!d.ok){msg(d.error||'Search failed.',false);return}found=d.found;
  $('found').innerHTML=found.length?found.map((x,i)=>`<div class="ra-found"><div><b>${esc(x.label)}</b><div class="muted">${esc(x.details)}</div></div>
    <button class="hud-btn primary" onclick="connectFound(${i})">Connect this robot</button></div>`).join('')
    :'<p class="muted">No robot found. Check it is switched on and on the same network as this PC, then search again.</p>'}
function connectFound(i){const x=found[i];$('raForm').innerHTML=requestForm('found','Connect: '+x.label,'Your provider receives what the PC found ('+x.details+') and sets the robot up with you.',x)}
async function ask(k,i){const d=await post('/api/robot/integration-request',{kind:k,device:i>=0?found[i]:null,email:$('rEmail').value.trim(),company:$('rCompany').value.trim(),details:$('rDetails').value});
  msg(d.ok?d.message:(d.error||'Could not send.'),!!d.ok);if(d.ok)loadRequests()}
async function loadRequests(){try{const d=await fetch('/api/robot/requests',{cache:'no-store'}).then(r=>r.json());
  $('raRequests').innerHTML=(d.requests||[]).length?d.requests.map(r=>`<div class="hud-row"><div><b>${esc(r.label)}</b><div class="muted">${esc(r.details||'')}</div></div><span class="state">${r.sent?'REQUEST SENT':'NOTED'} · ${esc(new Date(r.at*1000).toLocaleDateString())}</span></div>`).join('')
    :'No robot requested yet.'}catch(e){}}
fetch('/api/robot/kinds').then(r=>r.json()).then(d=>{KINDS=d.kinds;GROUPS=d.groups;draw();const q=new URLSearchParams(location.search).get('kind');if(q&&KINDS.some(x=>x.k===q))pick(q)});
loadRequests();
</script>
"""
