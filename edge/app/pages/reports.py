"""Settings → Reports: daily / weekly / monthly reports sent to Telegram as a PDF and kept on this PC."""

BODY = r"""
<main class="hud-main narrow">
<div class="page-head"><div><div class="page-kicker">Settings</div><h1 class="page-title">Reports</h1>
<div class="page-sub">A summary of what happened on the site: what the cameras saw, incidents and drone responses, drone flights, unknown drones, alarms, and cameras that went offline, compared with the period before. Sent to Telegram as a short message with a PDF (and by email on PCs paired with the portal), and kept on this PC.</div></div>
<div class="actions"><button class="hud-btn" onclick="location.href='/settings'">← Settings</button></div></div>
<style>
.rp-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.rp-card{border:1px solid #155879;border-radius:5px;padding:14px;background:#05131d}
.rp-card h3{margin:0 0 10px;font-size:13px;letter-spacing:1px;color:#9edfff;display:flex;justify-content:space-between;align-items:center}
.rp-card label{display:block;font-size:11px;color:#6d8b9d;margin:10px 0 4px;letter-spacing:.5px}
.rp-card input[type=time],.rp-card select,.rp-card input[type=number]{width:100%;box-sizing:border-box}
.rp-card input[type=time]{background:#020b12;color:#e9f8ff;border:1px solid #155879;border-radius:4px;padding:10px 12px;font:inherit;color-scheme:dark}
.rp-card .rp-btns{display:flex;gap:6px;margin-top:12px;flex-wrap:wrap}
.rp-secs{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:8px}
.rp-secs label{display:flex;gap:8px;align-items:center;padding:10px 12px;border:1px solid #123d55;border-radius:4px;cursor:pointer;text-transform:none;letter-spacing:0;font-size:13px;color:#e9f8ff;margin:0}
.rp-list td,.rp-list th{padding:7px 8px;border-bottom:1px solid #0f3347;text-align:left;font-size:12px}
.rp-list th{color:#5bd9ff;font-size:10px;letter-spacing:1px}
@media(max-width:900px){.rp-grid{grid-template-columns:1fr}}
</style>
<section class="panel"><div class="panel-head"><div class="panel-title">🗓 When</div><div class="live" id="rpWhen">LOADING</div></div><div class="panel-body">
<div class="rp-grid">
 <div class="rp-card"><h3>DAILY <input class="toggle" type="checkbox" id="dOn" onchange="save()"></h3>
  <div class="muted">The last 24 hours. Replaces the morning briefing.</div>
  <label for="dTime">SEND AT</label><input type="time" id="dTime" onchange="save()">
  <div class="rp-btns"><button class="hud-btn" onclick="preview('daily')">Preview</button><button class="hud-btn primary" onclick="sendNow('daily')">Send now</button></div></div>
 <div class="rp-card"><h3>WEEKLY <input class="toggle" type="checkbox" id="wOn" onchange="save()"></h3>
  <div class="muted">The last 7 days.</div>
  <label for="wDay">ON</label><select id="wDay" onchange="save()"></select>
  <label for="wTime">SEND AT</label><input type="time" id="wTime" onchange="save()">
  <div class="rp-btns"><button class="hud-btn" onclick="preview('weekly')">Preview</button><button class="hud-btn primary" onclick="sendNow('weekly')">Send now</button></div></div>
 <div class="rp-card"><h3>MONTHLY <input class="toggle" type="checkbox" id="mOn" onchange="save()"></h3>
  <div class="muted">The last month. Days 29–31 fall on the month's last day in shorter months.</div>
  <label for="mDay">ON DAY</label><input type="number" min="1" max="31" id="mDay" onchange="save()">
  <label for="mTime">SEND AT</label><input type="time" id="mTime" onchange="save()">
  <div class="rp-btns"><button class="hud-btn" onclick="preview('monthly')">Preview</button><button class="hud-btn primary" onclick="sendNow('monthly')">Send now</button></div></div>
</div>
<div class="hud-row" style="margin-top:12px"><div><b>Send to Telegram</b><div class="muted" id="rpTg">A short summary and the PDF. Reports are always sent, even with "Telegram: intruder warnings only" on.</div></div><input class="toggle" type="checkbox" id="tgOn" onchange="save()"></div>
<div id="rpEmail" style="display:none">
<div class="hud-row"><div><b>Email</b><div class="muted">The same summary with the PDF, sent through your portal to the people you tick: only your company's portal accounts can receive it.</div></div><input class="toggle" type="checkbox" id="emOn" onchange="save()"></div>
<div id="emPeople" class="rp-secs" style="margin-top:8px"></div>
</div>
<div id="rpMsg" class="hud-msg"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">☑ What goes in</div></div><div class="panel-body">
<div class="rp-secs" id="rpSecs"></div>
</div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">🗎 Saved reports</div><div class="live" id="rpCount"></div></div><div class="panel-body">
<p class="muted" style="margin-top:0">Every report sent is kept on this PC for 13 months.</p>
<table class="rp-list" style="width:100%;border-collapse:collapse"><thead><tr><th>REPORT</th><th>PERIOD ENDS</th><th>SIZE</th><th></th></tr></thead><tbody id="rpList"><tr><td colspan="4" class="muted">Loading…</td></tr></tbody></table>
</div></section>
</main>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const DAYS=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
$('wDay').innerHTML=DAYS.map((d,i)=>`<option value="${i}">${d}</option>`).join('');
let S=null,SEC=[],loading=true,people=null;
async function loadPeople(){const box=$('emPeople');
  try{const r=await fetch('/api/reports/people',{cache:'no-store'});const d=await r.json().catch(()=>({}));
    if(r.status===403){box.innerHTML='<div class="muted">Only admins can choose who receives the reports.</div>';return}
    if(!d.ok){box.innerHTML='<div class="muted" style="color:#ffcf7a">'+esc(d.error||'Could not get the list of people.')+'</div>';return}
    people=d.people;const chosen=new Set(S.email.to);
    const extra=S.email.to.filter(e=>!people.some(p=>p.email===e));
    box.innerHTML=people.map(p=>`<label><input type="checkbox" data-em="${esc(p.email)}" ${chosen.has(p.email)?'checked':''} onchange="save()"> ${esc(p.name||p.email)} <span class="muted">${p.name?esc(p.email)+' · ':''}${esc(p.role)}</span></label>`).join('')
      +extra.map(e=>`<label title="No longer one of your company's portal accounts: it will not receive reports"><input type="checkbox" data-em="${esc(e)}" checked onchange="save()"> <s>${esc(e)}</s> <span class="muted">not in the portal any more</span></label>`).join('')
      ||'<div class="muted">No portal accounts yet: add your people in the portal (Users).</div>'}
  catch(e){box.innerHTML='<div class="muted">The portal did not answer.</div>'}}
function msg(t,ok){const e=$('rpMsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t||''}
async function load(){
  const d=await fetch('/api/reports',{cache:'no-store'}).then(r=>r.json());S=d.settings;SEC=d.sections;loading=true;
  $('dOn').checked=S.daily.on;$('dTime').value=S.daily.time;
  $('wOn').checked=S.weekly.on;$('wDay').value=S.weekly.weekday;$('wTime').value=S.weekly.time;
  $('mOn').checked=S.monthly.on;$('mDay').value=S.monthly.day;$('mTime').value=S.monthly.time;$('tgOn').checked=S.telegram;$('emOn').checked=S.email.on;
  if(d.email_available){$('rpEmail').style.display='';if(people===null)loadPeople()}
  $('rpWhen').textContent=d.schedule.toUpperCase();
  if(!d.telegram_ready)$('rpTg').innerHTML='<span style="color:#ffcf7a">Telegram is not set up on this PC: reports are only kept here until it is.</span>';
  $('rpSecs').innerHTML=SEC.map(([k,t])=>`<label><input type="checkbox" data-sec="${k}" ${S.sections[k]?'checked':''} onchange="save()"> ${esc(t)}</label>`).join('');
  const L=d.reports||[];$('rpCount').textContent=L.length+' SAVED';
  $('rpList').innerHTML=L.length?L.map(x=>`<tr><td><b>${esc(x.kind[0].toUpperCase()+x.kind.slice(1))} report</b></td><td>${esc(x.ends)}</td><td class="muted">${Math.max(1,Math.round(x.size/1024))} KB</td>
    <td style="text-align:right;white-space:nowrap"><button class="hud-btn" onclick="window.open('/api/reports/file/${encodeURIComponent(x.name)}','_blank')">Open</button> <button class="hud-btn" onclick="location.href='/api/reports/file/${encodeURIComponent(x.name)}?download=1'">Download</button></td></tr>`).join('')
    :'<tr><td colspan="4" class="muted">No reports yet. The first one is made at its time, or press Send now.</td></tr>';
  loading=false}
async function save(){if(loading||!S)return;
  const body={daily:{on:$('dOn').checked,time:$('dTime').value},weekly:{on:$('wOn').checked,weekday:+$('wDay').value,time:$('wTime').value},
    monthly:{on:$('mOn').checked,day:+$('mDay').value||1,time:$('mTime').value},telegram:$('tgOn').checked,
    email:{on:$('emOn').checked,to:people===null?S.email.to:[...document.querySelectorAll('[data-em]')].filter(x=>x.checked).map(x=>x.dataset.em)},
    sections:Object.fromEntries([...document.querySelectorAll('[data-sec]')].map(x=>[x.dataset.sec,x.checked]))};
  const r=await fetch('/api/reports',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});const d=await r.json().catch(()=>({}));
  if(r.status===403){msg('Only admins can change the reports.',false);load();return}
  msg(d.ok?'Saved: '+d.schedule+'.':(d.error||'Not saved.'),!!d.ok);if(d.ok)$('rpWhen').textContent=d.schedule.toUpperCase()}
function preview(kind){window.open('/api/reports/preview?kind='+kind,'_blank')}
async function sendNow(kind){
  if(!await uiConfirm(`Make the ${kind} report now (the ${kind==='daily'?'last 24 hours':kind==='weekly'?'last 7 days':'last month'} up to now)${$('tgOn').checked?' and send it to Telegram':''}${$('emOn').checked&&$('rpEmail').style.display===''?' and by email':''}?`,{ok:'Send now'}))return;
  msg('Making the report…');
  const r=await fetch('/api/reports/send',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({kind})});const d=await r.json().catch(()=>({}));
  if(r.status===403){msg('Only operators and admins can send reports.',false);return}
  msg(d.ok?d.message:(d.error||'Not sent.'),!!d.ok);load()}
load();
</script>
"""
