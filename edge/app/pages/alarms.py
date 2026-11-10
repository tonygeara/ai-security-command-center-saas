"""Settings → Monitoring centre: drone-verified alarms (switch, destinations, test) and recent verifications."""
BODY = r"""
<main class="hud-main narrow">
<div class="page-head"><div><div class="page-kicker">Monitoring centre</div><h1 class="page-title">Drone-verified alarms</h1>
<div class="page-sub">When a drone is sent, it checks first. If its camera sees a person or vehicle (or an operator confirms on Telegram or here), a <b>verified alarm</b> goes to your monitoring centre with the pictures, and the evidence pack follows when the response ends. False alarms are never sent.</div></div></div>
<section class="panel"><div class="panel-head"><div class="panel-title">⏻ Verified alarms</div><div class="live" id="state">…</div></div><div class="panel-body">
<div class="hud-row"><div><b>Send drone-verified alarms</b><div class="muted">Off: drones respond as before and nothing is sent to a monitoring centre.</div></div><input class="toggle" type="checkbox" id="verified_alarms"></div>
<div class="hud-row"><div><b>Drone looks for</b><div class="muted">Seconds after the drone arrives for its camera to see someone before an operator is asked.</div></div><input id="verify_window_s" type="number" min="15" max="300" style="width:110px"></div>
<div class="hud-row"><div><b>Operator has</b><div class="muted">Seconds to confirm on Telegram or here.</div></div><input id="operator_window_s" type="number" min="60" max="3600" style="width:110px"></div>
<div class="hud-row"><div><b>Send unconfirmed alarms too</b><div class="muted">When nobody confirms in time, send it marked "unconfirmed" (Contact ID 380). Off: not sent.</div></div><input class="toggle" type="checkbox" id="send_unconfirmed"></div>
<div class="hud-row"><div><b>Site name</b><div class="muted">How the monitoring centre knows this site.</div></div><input id="site_name" style="width:240px"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">⇄ Webhook (HTTPS)</div></div><div class="panel-body">
<p class="muted" style="margin-top:0">JSON with the camera and drone pictures, then a second message with the evidence pack (zip). Signed in the <code>X-Signature-SHA256</code> header (HMAC-SHA256 of the body with the secret) so the centre can check it came from you.</p>
<label for="webhook_url">Address (https://…)</label><input id="webhook_url" placeholder="https://monitoring.example.com/alarms">
<label for="webhook_secret" style="margin-top:8px">Secret</label><input id="webhook_secret" type="password" autocomplete="new-password">
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">☎ Alarm receiver (SIA DC-09)</div></div><div class="panel-body">
<p class="muted" style="margin-top:0">The standard way alarm panels report over IP to an alarm-receiving centre. Contact ID: <b>130</b> burglary (verified), <b>380</b> unconfirmed, <b>602</b> test. Zone = the camera's number. Unencrypted: ask your centre for the address, account, receiver and line numbers.</p>
<div style="display:grid;grid-template-columns:2fr 1fr;gap:0 10px"><div><label for="sia_host">Receiver address</label><input id="sia_host" placeholder="arc.example.com"></div><div><label for="sia_port">Port</label><input id="sia_port" type="number" min="0" max="65535"></div></div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0 10px"><div><label for="sia_account">Account</label><input id="sia_account"></div><div><label for="sia_receiver">Receiver no.</label><input id="sia_receiver"></div><div><label for="sia_line">Line no.</label><input id="sia_line"></div></div>
</div></section>
<div class="actions" style="margin:12px 0"><button class="hud-btn primary" onclick="save()">Save</button><button class="hud-btn" onclick="test()">Send a test</button></div>
<div id="msg" class="hud-msg"></div>
<section class="panel"><div class="panel-head"><div class="panel-title">☰ Recent verifications</div></div><div class="panel-body"><div id="list" class="muted">None yet.</div></div></section>
</main>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const KEYS=['verified_alarms','verify_window_s','operator_window_s','send_unconfirmed','site_name','webhook_url','webhook_secret','sia_host','sia_port','sia_account','sia_receiver','sia_line'];
const STATUS={watching:'Drone checking…',asked:'Waiting for an operator',verified:'✅ Verified',false_alarm:'❎ False alarm',unconfirmed:'Unconfirmed'};
function msg(t,ok){const e=$('msg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t||''}
async function call(url,body){const r=await fetch(url,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body||{})});try{return await r.json()}catch(e){return {ok:false,error:'HTTP '+r.status}}}
async function load(fill){const d=await fetch('/api/alarms').then(r=>r.json());
  if(fill){for(const k of KEYS){const e=$(k);if(e.type==='checkbox')e.checked=!!d.settings[k];else e.value=d.settings[k]??''}}
  $('state').textContent=d.settings.verified_alarms?'ON':'OFF';
  $('list').innerHTML=d.verifications.length?d.verifications.map(v=>`<div class="hud-row"><div><b>${esc(v.camera)}</b> · ${esc(STATUS[v.status]||v.status)}
    <div class="muted">${new Date(v.started*1000).toLocaleString()} · ${esc(v.drone_label)}${v.verified_by?' · '+esc(v.verified_by):''}${Object.keys(v.sent||{}).length?' · sent: '+esc(Object.entries(v.sent).map(([k,r])=>k+' '+r).join(', ')):''}</div></div>
    ${['watching','asked'].includes(v.status)?`<div class="actions"><button class="hud-btn primary" onclick="decide('${v.id}','verify')">Real intrusion</button><button class="hud-btn" onclick="decide('${v.id}','false')">False alarm</button></div>`:''}</div>`).join(''):'None yet.'}
async function save(){const body={};for(const k of KEYS){const e=$(k);body[k]=e.type==='checkbox'?e.checked:e.type==='number'?Number(e.value||0):e.value}
  if(body.verified_alarms&&!body.webhook_url&&!(body.sia_host&&body.sia_port&&body.sia_account)){msg('Set a webhook address or an alarm receiver before turning this on.',false);return}
  const d=await call('/api/alarms/settings',body);msg(d.ok?'Saved.':d.error,d.ok);if(d.ok)load(true)}
async function test(){msg('Sending a test…');const d=await call('/api/alarms/test');msg(d.error||Object.entries(d.results).map(([k,r])=>k+': '+r).join(' · '),d.ok)}
async function decide(id,decision){const d=await call('/api/alarms/'+id,{decision});msg(d.ok?(decision==='verify'?'Verified: sending the alarm.':'Marked as a false alarm.'):d.error,d.ok);load(false)}
load(true);setInterval(()=>load(false),5000);
</script>"""
