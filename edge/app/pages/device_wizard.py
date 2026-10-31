"""Adding cameras, recorders and drones."""
BODY = r"""
<style>
.wz-tabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.wz-tab{flex:1;min-width:200px;text-align:left;padding:14px 16px;cursor:pointer;background:#04111b;border:1px solid #0a5480;border-radius:6px;color:#a8c7d7;font-family:inherit}
.wz-tab b{display:block;color:#5bd9ff;font-size:14px;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:4px}
.wz-tab span{font-size:12px;color:#6d8b9d}
.wz-tab.on{border-color:#36cfff;box-shadow:0 0 16px rgba(54,207,255,.18);background:rgba(18,151,215,.08)}
.wz-steps{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap}
.wz-steps i{font-style:normal;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:#4d6b7c;padding:6px 10px;border:1px solid #123447;border-radius:12px}
.wz-steps i.on{color:#02131d;background:#25c7ff;border-color:#45d0ff}
.wz-steps i.done{color:#2aea88;border-color:#1f7a50}
.wz-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}
.wz-grid .full{grid-column:1/-1}
.wz-found{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px;margin-top:12px}
.wz-found button{text-align:left;padding:10px 12px;cursor:pointer;background:#05131d;border:1px solid #153c56;border-radius:5px;color:#d9efff;font-family:inherit}
.wz-found button:hover{border-color:#36cfff}
.wz-found small{display:block;color:#6d8b9d;font-size:11px;margin-top:3px}
.wz-shot{width:100%;max-width:520px;border:1px solid #155879;border-radius:5px;display:block;margin-top:12px;background:#000}
.wz-link{background:none;border:0;color:#5bd9ff;cursor:pointer;font-family:inherit;font-size:12px;padding:0;margin-top:12px;text-decoration:underline}
.wz-drone{display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:center;padding:14px;background:#05131d;border:1px solid #153c56;border-radius:5px;margin-bottom:10px}
.wz-drone .qr{width:132px;height:132px;background:#fff;border-radius:4px;display:flex;align-items:center;justify-content:center}
.wz-drone .qr svg{width:124px;height:124px}
.wz-hidden{display:none}
.rec-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.rec-cam{background:#05131d;border:1px solid #153c56;border-radius:6px;overflow:hidden}
.rec-cam.on{border-color:#2aea88}
.rec-cam img,.rec-cam .nopic{width:100%;aspect-ratio:16/9;object-fit:cover;display:block;background:#000}
.rec-cam .nopic{display:flex;align-items:center;justify-content:center;color:#6d8b9d;font-size:12px}
.rec-cam .rc-body{padding:8px 10px}
.rec-cam input[type=text]{padding:7px 9px;font-size:13px;margin-top:6px}
.rec-cam label{margin:0;display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;font-size:12px;color:#d9efff}
@media(max-width:640px){.wz-grid{grid-template-columns:1fr}.wz-drone{grid-template-columns:1fr}}
</style>
<main class="hud-main narrow">
<div class="page-head"><div><div class="page-kicker">Devices</div><h1 class="page-title">Add a camera or drone</h1>
<div class="page-sub">Pick the brand, enter the IP and login. The system finds the stream, shows a live snapshot, and adds it. Nothing is changed until you confirm.</div></div>
<div id="usage" class="muted"></div></div>

<div class="wz-tabs">
<button class="wz-tab on" id="tabCam" onclick="mode('cam')"><b>▣ Camera</b><span>IP / CCTV camera or NVR channel</span></button>
<button class="wz-tab" id="tabRec" onclick="mode('rec')"><b>📼 Recorder</b><span>Whole NVR / DVR in one step</span></button>
<button class="wz-tab" id="tabDrone" onclick="mode('drone')"><b>✈ Drone</b><span>DJI live stream over RTMP</span></button>
</div>

<section class="panel" id="camPanel"><div class="panel-head"><div class="panel-title">▣ New camera</div><div class="live">RTSP</div></div>
<div class="panel-body">
<div class="wz-steps"><i id="st1" class="on">1 · Find</i><i id="st2">2 · Connect</i><i id="st3">3 · Check</i><i id="st4">4 · Add</i></div>

<div id="step1">
<div class="actions"><button class="hud-btn primary" id="scanBtn" onclick="scan()">Scan network for cameras</button>
<button class="hud-btn" onclick="go(2)">I know the IP address</button></div>
<div id="scanMsg" class="muted" style="margin-top:12px"></div>
<div id="found" class="wz-found"></div>
</div>

<div id="step2" class="wz-hidden">
<div id="simple" class="wz-grid">
<div class="full"><label for="brand">Brand</label><select id="brand" onchange="brandChanged()"></select><div id="note" class="muted" style="margin-top:6px"></div></div>
<div><label for="ip">IP address</label><input id="ip" placeholder="192.168.1.64" autocomplete="off"></div>
<div><label for="channel">Channel <span class="muted" style="text-transform:none;letter-spacing:0">(1 for a single camera; NVR = camera number)</span></label><input id="channel" type="number" min="1" max="64" value="1"></div>
<div><label for="user">Username</label><input id="user" autocomplete="off"></div>
<div><label for="pass">Password</label><input id="pass" type="password" autocomplete="new-password"></div>
<div><label for="port">RTSP port</label><input id="port" type="number" value="554"></div>
</div>
<div id="manual" class="wz-hidden"><label for="rtsp">Full RTSP address</label><input id="rtsp" type="password" placeholder="rtsp://username:password@192.168.1.50:554/stream1" autocomplete="off"></div>
<button class="wz-link" id="manualLink" onclick="toggleManual()">Enter full RTSP address instead</button>
<div class="muted" style="margin-top:10px">The login stays on this PC; it is never sent to the cloud.</div>
<div class="actions" style="margin-top:16px"><button class="hud-btn" onclick="go(1)">Back</button><button class="hud-btn primary" id="testBtn" onclick="probe()">Connect &amp; test</button></div>
<div id="m2" class="hud-msg"></div>
</div>

<div id="step3" class="wz-hidden">
<img id="shot" class="wz-shot" alt="Camera snapshot">
<div id="m3" class="hud-msg ok"></div>
<label for="cname">Camera name</label><input id="cname" placeholder="Front Gate" maxlength="40">
<div class="actions" style="margin-top:16px"><button class="hud-btn" onclick="go(2)">Back</button><button class="hud-btn primary" id="addBtn" onclick="addCam()">Add camera</button></div>
<div id="m3b" class="hud-msg"></div>
</div>

<div id="step4" class="wz-hidden">
<div id="m4" class="hud-msg"></div>
<div class="actions" style="margin-top:16px"><button class="hud-btn primary" onclick="location.href='/'">Open dashboard</button><button class="hud-btn" onclick="reset()">Add another camera</button></div>
</div>
</div></section>

<section class="panel wz-hidden" id="recPanel"><div class="panel-head"><div class="panel-title">📼 Add a whole recorder</div><div class="live">NVR / DVR</div></div>
<div class="panel-body">
<div class="muted">Enter the recorder's address and login. The system recognises the brand, finds every camera channel with its name and a live picture, and you choose which to add.</div>
<div class="wz-grid" style="margin-top:6px">
<div class="full"><label for="recBrand">Brand</label><select id="recBrand"></select></div>
<div><label for="recIp">Recorder IP address</label><input id="recIp" placeholder="192.168.1.100" autocomplete="off"></div>
<div><label for="recPort">RTSP port</label><input id="recPort" type="number" value="554"></div>
<div><label for="recUser">Username</label><input id="recUser" value="admin" autocomplete="off"></div>
<div><label for="recPass">Password</label><input id="recPass" type="password" autocomplete="new-password"></div>
<div class="full"><label style="display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;font-size:13px"><input type="checkbox" id="recSub"> Use lighter sub-streams (recommended for 8+ cameras; faces and plates are read best without it)</label></div>
</div>
<div class="actions" style="margin-top:14px"><button class="hud-btn primary" id="recScanBtn" onclick="recScan()">Find cameras</button></div>
<div id="recMsg" class="hud-msg"></div>
<div id="recResult" class="wz-hidden" style="margin-top:14px">
<div class="muted" id="recInfo"></div>
<div class="actions" style="margin:10px 0"><button class="hud-btn" onclick="recSelect(true)">Select all with video</button><button class="hud-btn" onclick="recSelect(false)">Select none</button></div>
<div id="recList" class="rec-grid"></div>
<div class="actions" style="margin-top:14px"><button class="hud-btn primary" id="recAddBtn" onclick="recAdd()">Add selected</button></div>
<div id="recMsg2" class="hud-msg"></div>
</div>
</div></section>

<section class="panel wz-hidden" id="dronePanel"><div class="panel-head"><div class="panel-title">✈ Drones</div><div class="live" id="recv"></div></div>
<div class="panel-body">
<div class="muted">In DJI Fly: tap <b>•••</b> &gt; <b>Transmission</b> &gt; <b>Live Streaming Platforms</b> &gt; <b>RTMP</b>, then type the address below (or scan the QR code with the phone and copy it). The phone/controller must be on the same Wi-Fi as this PC.</div>
<div id="drones" style="margin-top:14px"></div>
<div class="actions" style="margin-top:6px"><button class="hud-btn primary" id="droneBtn" onclick="addDrone()">Add another drone</button></div>
<div id="md" class="hud-msg"></div>
</div></section>
</main>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const msg=(id,t,cls)=>{const e=$(id);e.className='hud-msg '+(cls||'');e.textContent=t};
let brands=[],manual=false,found=null,dronePoll=null;
function mode(m){$('tabCam').classList.toggle('on',m==='cam');$('tabDrone').classList.toggle('on',m==='drone');$('tabRec').classList.toggle('on',m==='rec');
  $('camPanel').classList.toggle('wz-hidden',m!=='cam');$('dronePanel').classList.toggle('wz-hidden',m!=='drone');$('recPanel').classList.toggle('wz-hidden',m!=='rec');
  clearInterval(dronePoll);if(m==='drone'){loadDrones();dronePoll=setInterval(loadDrones,5000)}history.replaceState(null,'',m==='drone'?'#drone':m==='rec'?'#recorder':'#camera')}
function go(n){for(let i=1;i<=4;i++){$('step'+i).classList.toggle('wz-hidden',i!==n);$('st'+i).className=i===n?'on':(i<n?'done':'')}}
function brandChanged(){const b=brands.find(x=>x.id===$('brand').value)||{};$('note').textContent=b.note||'';if(!$('user').dataset.touched)$('user').value=b.user||'';$('port').value=b.port||554}
function toggleManual(){manual=!manual;$('simple').classList.toggle('wz-hidden',manual);$('manual').classList.toggle('wz-hidden',!manual);$('manualLink').textContent=manual?'Use brand + IP instead':'Enter full RTSP address instead'}
async function usage(){try{const [c,d]=await Promise.all(['camera','drone'].map(k=>fetch('/api/cloud/can-add-source/'+k).then(r=>r.json())));
  const f=x=>x.limit==null?x.used+' used':x.used+' of '+x.limit;$('usage').innerHTML='Cameras: <b>'+esc(f(c))+'</b> · Drones: <b>'+esc(f(d))+'</b>';
  if(!c.allowed){$('scanBtn').disabled=true;$('testBtn').disabled=true;msg('m2',c.message,'bad');$('scanMsg').textContent=c.message}
  $('droneBtn').disabled=!d.allowed;if(!d.allowed)msg('md',d.message,'bad')}catch(e){}}
async function scan(){$('scanBtn').disabled=true;$('found').innerHTML='';$('scanMsg').textContent='Scanning the local network… (up to 30 seconds)';
  try{const d=await fetch('/api/setup/scan',{method:'POST'}).then(r=>r.json());const cams=d.cameras||[];
    $('scanMsg').textContent=cams.length?`Found ${cams.length} camera(s) on ${d.network}. Click one to use it.`:`No cameras found on ${d.network||'the network'}. Check the camera is powered and on the same network, or enter the IP yourself.`;
    $('found').innerHTML=cams.map((c,i)=>`<button onclick="pick(${i})"><b>${esc(c.ip)}</b><small>${esc(c.camera_name?'Already added: '+c.camera_name:(brands.find(b=>b.id===c.brand)||{}).label||'Unknown brand')}</small></button>`).join('');found=cams}
  catch(e){$('scanMsg').textContent='Scan failed. Enter the IP address yourself.'}finally{$('scanBtn').disabled=false}}
function pick(i){const c=found[i];$('ip').value=c.ip;$('brand').value=c.brand||'other';brandChanged();go(2);$('pass').focus()}
let probed=null;
async function probe(){const body=manual?{rtsp_url:$('rtsp').value.trim()}:{brand:$('brand').value,ip:$('ip').value.trim(),port:$('port').value,channel:$('channel').value,user:$('user').value,password:$('pass').value};
  $('testBtn').disabled=true;msg('m2','Connecting to the camera… (up to 20 seconds)');
  try{const d=await fetch('/api/setup/camera/probe',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
    if(!d.ok){msg('m2',d.error||'Could not connect.','bad');return}
    probed=d;$('shot').src=d.snapshot;$('m3').textContent=d.message;$('m3b').className='hud-msg';$('m3b').textContent='';
    if(!$('cname').value)$('cname').value='Camera '+(($('ip').value||'').split('.').pop()||'');go(3);$('cname').focus();$('cname').select()}
  catch(e){msg('m2','Could not reach the system: '+e.message,'bad')}finally{$('testBtn').disabled=false}}
async function addCam(){const name=$('cname').value.trim();if(!name){msg('m3b','Give the camera a name.','bad');return}
  $('addBtn').disabled=true;msg('m3b','Adding the camera and restarting video processing…');
  try{const r=await fetch('/api/setup/camera',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name,rtsp_url:probed.rtsp_url})});const d=await r.json();
    if(!r.ok||!d.ok){msg('m3b',d.error||'Could not add the camera.','bad');return}
    go(4);msg('m4','“'+name+'” added. Waiting for its live video… (about 20–40 seconds)');waitLive(d.camera_name,name)}
  catch(e){msg('m3b','Could not reach the system: '+e.message,'bad')}finally{$('addBtn').disabled=false}}
async function waitLive(slug,name){for(let i=0;i<45;i++){await new Promise(r=>setTimeout(r,2000));
  try{const d=await fetch('/api/cameras').then(r=>r.json());const c=(d.cameras||[]).find(x=>x.name===slug);
    if(c&&c.online){msg('m4','✓ “'+name+'” is live ('+c.fps+' fps) with face and plate recognition. It now appears on the dashboard.','ok');usage();return}}catch(e){}}
  msg('m4','“'+name+'” was added, but its video has not started yet. Give it a minute, then check the dashboard.','bad')}
function reset(){probed=null;['ip','pass','rtsp','cname'].forEach(k=>$(k).value='');$('channel').value=1;go(1);usage()}
async function loadDrones(){try{const d=await fetch('/api/setup/drones').then(r=>r.json());
  $('recv').innerHTML=d.receiver_ready?'<i class="dot good"></i>RECEIVER READY':'<i class="dot bad"></i>RECEIVER OFF';
  $('drones').innerHTML=(d.drones||[]).map(x=>`<div class="wz-drone"><div class="qr">${x.qr||''}</div><div><b style="color:#5bd9ff;letter-spacing:1px;text-transform:uppercase">${esc(x.name)}</b>
  <span class="state" style="margin-left:10px">${x.online?'<i class="dot good"></i>LIVE':'<i class="dot warn"></i>WAITING FOR STREAM'}</span>
  <label>RTMP address for DJI Fly</label><code>${esc(x.publish_url)}</code> <button class="hud-btn" style="min-height:28px;margin-left:6px" onclick="navigator.clipboard.writeText('${esc(x.publish_url)}')">Copy</button></div></div>`).join('')||'<p class="muted">No drone slot yet. Click “Add another drone”.</p>'}catch(e){}}
async function addDrone(){$('droneBtn').disabled=true;msg('md','Adding a drone slot…');
  try{const r=await fetch('/api/setup/drone',{method:'POST'});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Could not add the drone');
    msg('md',d.message,'ok');loadDrones()}catch(e){msg('md',e.message,'bad')}finally{usage()}}
let recFound=[],recCanAdd=null;
async function recScan(){const body={brand:$('recBrand').value,ip:$('recIp').value.trim(),port:$('recPort').value,user:$('recUser').value,password:$('recPass').value,sub_stream:$('recSub').checked};
  $('recScanBtn').disabled=true;$('recResult').classList.add('wz-hidden');msg('recMsg','Looking for the recorder and its cameras… (up to a minute)');
  try{const d=await fetch('/api/setup/recorder/scan',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
    if(!d.ok){msg('recMsg',d.error||'Scan failed.','bad');return}
    recFound=d.channels||[];recCanAdd=d.can_add;const live=recFound.filter(c=>c.online).length;
    msg('recMsg',`Found ${d.brand_label}${d.model?' ('+d.model+')':''}: ${recFound.length} channel(s), ${live} with video.`,'ok');
    $('recInfo').textContent=recCanAdd==null?'Your licence has no camera limit.':`Your licence allows ${recCanAdd} more camera${recCanAdd===1?'':'s'}.`;
    $('recList').innerHTML=recFound.map((c,i)=>`<div class="rec-cam${c.online?' on':''}">${c.snapshot?`<img src="${c.snapshot}" alt="">`:'<div class="nopic">No video on this channel</div>'}
      <div class="rc-body"><label><input type="checkbox" id="rc${i}" ${c.online?'checked':''} onchange="recCount()"> Channel ${c.ch}${c.width?` · ${c.width}×${c.height}`:''}</label>
      <input type="text" id="rn${i}" value="${esc(c.name)}" maxlength="40"></div></div>`).join('')||'<p class="muted">No channels found.</p>';
    $('recResult').classList.remove('wz-hidden');recCount()}
  catch(e){msg('recMsg','Could not reach the system: '+e.message,'bad')}finally{$('recScanBtn').disabled=false}}
function recSelect(on){recFound.forEach((c,i)=>{$('rc'+i).checked=on&&c.online});recCount()}
function recCount(){const n=recFound.filter((c,i)=>$('rc'+i).checked).length;$('recAddBtn').textContent=`Add selected (${n})`;
  if(recCanAdd!=null&&n>recCanAdd)msg('recMsg2',`You selected ${n}, but the licence allows ${recCanAdd} more. Only the first ${recCanAdd} will be added.`,'bad');else $('recMsg2').textContent=''}
async function recAdd(){const cams=recFound.map((c,i)=>({sel:$('rc'+i).checked,name:$('rn'+i).value.trim()||('Camera '+c.ch),rtsp_url:c.rtsp_url})).filter(c=>c.sel);
  if(!cams.length){msg('recMsg2','Select at least one camera.','bad');return}
  $('recAddBtn').disabled=true;msg('recMsg2',`Adding ${cams.length} camera(s) and restarting video processing once…`);
  try{const r=await fetch('/api/setup/recorder/add',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({cameras:cams})});const d=await r.json();
    msg('recMsg2',(d.message||d.error)+(d.ok?' They appear on the dashboard within about a minute.':''),d.ok?'ok':'bad');usage()}
  catch(e){msg('recMsg2','Could not reach the system: '+e.message,'bad')}finally{$('recAddBtn').disabled=false}}
fetch('/api/setup/brands').then(r=>r.json()).then(d=>{brands=d.brands||[];
  $('recBrand').innerHTML=brands.filter(b=>['other','hikvision','dahua','reolink','uniview','ezviz'].includes(b.id)).map(b=>`<option value="${b.id}">${b.id==='other'?'Not sure: detect automatically':esc(b.label)}</option>`).join('');$('brand').innerHTML=brands.map(b=>`<option value="${b.id}">${esc(b.label)}</option>`).join('');$('brand').value='other';brandChanged()});
$('user').addEventListener('input',()=>$('user').dataset.touched=1);
usage();mode(location.hash==='#drone'?'drone':location.hash==='#recorder'?'rec':'cam');
</script>"""
