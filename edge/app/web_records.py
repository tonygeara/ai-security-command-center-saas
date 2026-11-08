"""Records and oversight: the audit log, incidents, browser presence and shutting the system down.

Part of the dashboard (registered by dashboard.py with setup()). Storage is store.py, the audit chain
audit.py, incident grouping incidents.py.
"""
import json
import re
import threading
import time

import requests
from flask import Blueprint, Response, g, has_request_context, jsonify, request

import audit
import edition
import evidence

bp = Blueprint("records", __name__)
STORE = INCIDENTS = hud_page = load_settings = None  # set by setup()
DATA_FOLDER = EVENT_FOLDER = VERSION = ""
_evidence_key = None


def setup(app, store, incidents, hud_page_fn, load_settings_fn, data_folder="", event_folder="", version=""):
    global STORE, INCIDENTS, hud_page, load_settings, DATA_FOLDER, EVENT_FOLDER, VERSION
    STORE, INCIDENTS, hud_page, load_settings = store, incidents, hud_page_fn, load_settings_fn
    DATA_FOLDER, EVENT_FOLDER, VERSION = data_folder, event_folder, version
    app.register_blueprint(bp)


def evidence_key():
    """This PC's evidence signing key (made on first use)."""
    global _evidence_key
    if _evidence_key is None:
        _evidence_key = evidence.load_or_create_key(DATA_FOLDER)
    return _evidence_key


# ---------------- Audit log ----------------
# Every drone event (from a person, a Telegram command or the system itself) and every change made
# through the dashboard to drones, users, safety and system settings. See audit.py.
_audit_actor = threading.local()  # .source for work done outside a web request (e.g. "telegram")
AUDITED_WRITES = re.compile(r"^/api/(drone/|routes|response/|maps/[a-f0-9]{12}/(fly|stop)|maps/plan|virtual-drones|nofly"
                            r"|gps-dispatch/request|users|customer/settings|safety/settings|response/settings|airspace/"
                            r"|system/|license|cloud/pair|sources/|incidents/)")
STICK_AUDIT_GAP = 30  # stick input arrives many times a second: log when a stick session starts
_stick_audit_last = {}


def audit_record(action, target="", detail=None, result="ok", user=None, source=None):
    """Write one audit record; never lets a logging problem break the action itself."""
    try:
        if has_request_context():
            u = getattr(g, "user", None)
            user = user if user is not None else (u["username"] if u else "")
            source = source or "dashboard"
        else:
            source = source or getattr(_audit_actor, "source", None) or "system"
        audit.record(STORE, action, user=user or "", source=source, target=target, detail=detail, result=result)
    except Exception as e:
        print("Audit log error:", e)


@bp.after_app_request
def _audit_request(resp):
    path = request.path
    if request.method in ("GET", "HEAD", "OPTIONS") or not AUDITED_WRITES.match(path):
        return resp
    target = request.args.get("drone") or ""
    if path == "/api/drone/stick":
        u = getattr(g, "user", None)
        key = ((u or {}).get("username", ""), target)
        now = time.time()
        quiet = now - _stick_audit_last.get(key, 0) > STICK_AUDIT_GAP
        _stick_audit_last[key] = now
        if not quiet:
            return resp
        audit_record("manual stick control", target=target, result=str(resp.status_code))
        return resp
    body = request.get_json(silent=True)
    if body is None and request.form:
        body = request.form.to_dict()
    audit_record(f"{request.method} {path}", target=target, detail=body if isinstance(body, dict) else {},
                 result="ok" if resp.status_code < 400 else f"refused ({resp.status_code})")
    return resp


@bp.route("/audit")
def audit_page():
    return Response(hud_page("Audit log", AUDIT_PAGE, active="settings"), mimetype="text/html")


@bp.route("/api/audit")
def api_audit():
    days = min(max(float(request.args.get("days") or 7), 0.01), 3650)
    rows = audit.read(STORE, limit=int(request.args.get("limit") or 1000), since=time.time() - days * 86400)
    if request.args.get("format") == "csv":
        return Response(audit.to_csv(rows), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=audit-{time.strftime('%Y%m%d')}.csv"})
    ok, checked, broken = audit.verify(STORE)
    return jsonify({"ok": True, "rows": rows, "chain": {"ok": ok, "checked": checked, "broken_line": broken}})


AUDIT_PAGE = r"""
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Security</div><h1 class="page-title">Audit log</h1>
<div class="page-sub">Every drone action, who asked for it (a person, Telegram, or the system by itself), and every change to users, safety and system settings. Each line is chained to the one before, so an edited or deleted line shows up here.</div></div></div>
<section class="panel"><div class="panel-body">
<div class="actions" style="align-items:center;flex-wrap:wrap;gap:8px">
<select id="days"><option value="1">Last 24 hours</option><option value="7" selected>Last 7 days</option><option value="30">Last 30 days</option><option value="365">Last year</option></select>
<input id="q" placeholder="Filter: user, drone, action" style="flex:1;min-width:180px">
<button class="hud-btn" onclick="dl()">Download CSV</button>
<span id="chain" class="hud-msg" style="margin:0"></span></div>
<div style="overflow-x:auto;margin-top:12px"><table style="width:100%;border-collapse:collapse;font-size:12px">
<thead><tr style="text-align:left;color:#5bd9ff"><th>Time</th><th>Who</th><th>From</th><th>Action</th><th>Drone / target</th><th>Result</th></tr></thead>
<tbody id="rows"></tbody></table></div>
</div></section></main>
<style>#rows td{padding:6px 8px;border-top:1px solid #123447;vertical-align:top}#rows tr:hover td{background:#071c29}</style>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
let all=[];
function show(){const q=$('q').value.toLowerCase();
  $('rows').innerHTML=all.filter(r=>!q||JSON.stringify(r).toLowerCase().includes(q)).map(r=>`<tr title="${esc(JSON.stringify(r.detail||{}))}">
  <td>${new Date(r.t*1000).toLocaleString()}</td><td>${esc(r.user)||'<span class="muted">system</span>'}</td><td>${esc(r.source)}</td>
  <td>${esc(r.action)}</td><td>${esc(r.target)}</td><td>${esc(r.result)}</td></tr>`).join('')||'<tr><td colspan="6" class="muted">Nothing in this period.</td></tr>'}
async function load(){const d=await fetch('/api/audit?days='+$('days').value).then(r=>r.json());all=d.rows||[];
  const c=$('chain');c.className='hud-msg '+(d.chain.ok?'ok':'bad');
  c.textContent=d.chain.ok?`✔ Log intact (${d.chain.checked} records)`:`⚠ The log was changed at line ${d.chain.broken_line}`;show()}
function dl(){location.href='/api/audit?format=csv&days='+$('days').value}
$('days').onchange=load;$('q').oninput=show;load();setInterval(load,15000);
</script>"""


# ---------------- Incidents ----------------
@bp.route("/incidents")
def incidents_page():
    return Response(hud_page("Incidents", INCIDENTS_PAGE, active="settings"), mimetype="text/html")


@bp.route("/api/incidents")
def api_incidents():
    INCIDENTS.close_stale()
    days = min(max(float(request.args.get("days") or 7), 0.01), 3650)
    return jsonify({"ok": True, "incidents": INCIDENTS.list(time.time() - days * 86400,
                                                            min_severity=int(request.args.get("min") or 1))})


@bp.route("/api/incidents/<int:inc_id>", methods=["GET", "POST"])
def api_incident(inc_id):
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        u = getattr(g, "user", None)
        try:
            INCIDENTS.set_status(inc_id, str(data.get("status") or "reviewed"), str(data.get("note") or ""),
                                 user=u["username"] if u else "")
        except KeyError:
            return jsonify({"ok": False, "error": "No such incident."}), 404
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
    INCIDENTS.close_stale()
    inc = INCIDENTS.get(inc_id)
    return (jsonify({"ok": True, "incident": inc}) if inc else (jsonify({"ok": False, "error": "No such incident."}), 404))


@bp.route("/api/incidents/<int:inc_id>/evidence.zip")
def api_incident_evidence(inc_id):
    INCIDENTS.close_stale()
    inc = INCIDENTS.get(inc_id)
    if not inc:
        return jsonify({"ok": False, "error": "No such incident."}), 404
    u = getattr(g, "user", None)
    data, manifest, mhash = evidence.build(inc, INCIDENTS.track(inc_id), EVENT_FOLDER, evidence_key(),
                                           made_by=u["username"] if u else "", product=edition.PRODUCT_NAME, version=VERSION)
    audit_record("evidence pack made", target=f"incident {inc_id}",
                 detail={"manifest_sha256": mhash, "files": len(manifest["files"]), "fingerprint": manifest["key_fingerprint"]})
    name = f"evidence-incident-{inc_id}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    return Response(data, mimetype="application/zip", headers={"Content-Disposition": f"attachment; filename={name}"})


@bp.route("/api/evidence/key")
def api_evidence_key():
    pub = evidence.public_key_b64(evidence_key())
    return jsonify({"ok": True, "public_key": pub, "fingerprint": evidence.fingerprint(pub)})


@bp.route("/api/evidence/verify", methods=["POST"])
def api_evidence_verify():
    f = request.files.get("pack")
    data = f.read(512 * 1024 * 1024) if f else request.get_data(cache=False)[:512 * 1024 * 1024]
    if not data:
        return jsonify({"ok": False, "error": "Choose an evidence pack (.zip)."}), 400
    mine = evidence.fingerprint(evidence.public_key_b64(evidence_key()))
    ok, problems, manifest = evidence.verify(data)
    signer = (manifest or {}).get("key_fingerprint") or ""
    return jsonify({"ok": True, "valid": ok, "problems": problems, "signed_here": bool(manifest) and signer == mine,
                    "fingerprint": signer, "incident": (manifest or {}).get("incident"), "made": (manifest or {}).get("made")})


INCIDENTS_PAGE = r"""
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Security</div><h1 class="page-title">Incidents</h1>
<div class="page-sub">Everything that happened at a camera within 5 minutes, told as one story: who or what was seen, unknown faces and plates, and the drone that was sent.</div></div></div>
<style>.inc{border:1px solid #155879;border-radius:5px;margin-bottom:10px;background:#05131d}.inc-h{display:flex;gap:10px;align-items:center;padding:10px 12px;cursor:pointer}
.inc-h b{flex:1}.sev{font-size:10px;letter-spacing:1px;padding:2px 7px;border-radius:3px;border:1px solid}.sev1{color:#7fb6cf;border-color:#245a73}.sev2{color:#ffd27a;border-color:#7a5a1a}.sev3{color:#ff8f8f;border-color:#7a2a2a}
.inc-b{display:none;padding:0 12px 12px}.inc.open .inc-b{display:block}.it{display:flex;gap:10px;padding:4px 0;border-top:1px solid #0f2c3c;font-size:12px}.it time{color:#6d8b9d;min-width:70px}
.inc-b img{max-width:220px;border-radius:4px;margin:6px 6px 0 0;border:1px solid #155879}</style>
<section class="panel"><div class="panel-body">
<div class="actions" style="gap:8px;flex-wrap:wrap;margin-bottom:12px">
<select id="days"><option value="1">Last 24 hours</option><option value="7" selected>Last 7 days</option><option value="30">Last 30 days</option></select>
<select id="min"><option value="1">All activity</option><option value="2" selected>Unknown faces/plates and drone responses</option><option value="3">Drone responses only</option></select></div>
<div id="list"></div></div></section>
<section class="panel"><div class="panel-head"><div class="panel-title">✔ Evidence packs</div></div><div class="panel-body">
<p class="muted" style="margin-top:0">Open an incident and choose <b>Download evidence pack</b>: one signed file with the timeline, snapshots, the drone's photo, video and GPS track. Anyone can check it was not changed. This PC's signing key fingerprint (give it to whoever receives packs): <b id="fp" style="font-family:monospace;color:#9edfff">…</b></p>
<div class="actions" style="gap:8px;flex-wrap:wrap"><input type="file" id="pack" accept=".zip"><button class="hud-btn" onclick="check()">Check an evidence pack</button></div>
<div id="vmsg" class="hud-msg"></div></div></section></main>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const tm=t=>new Date(t*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
const opened=new Set();
async function load(){const d=await fetch(`/api/incidents?days=${$('days').value}&min=${$('min').value}`).then(r=>r.json());
  $('list').innerHTML=(d.incidents||[]).map(i=>`<div class="inc${opened.has(i.id)?' open':''}" id="i${i.id}">
   <div class="inc-h" onclick="tog(${i.id})"><span class="sev sev${i.severity}">${esc(i.level.toUpperCase())}</span><b>${esc(i.title)}</b>
   <span class="muted">${new Date(i.started*1000).toLocaleString()}</span><span class="muted">${esc(i.status)}</span></div><div class="inc-b" id="b${i.id}"></div></div>`).join('')
   ||'<p class="muted">No incidents in this period.</p>';
  for(const id of opened)fill(id)}
async function fill(id){const d=await fetch('/api/incidents/'+id).then(r=>r.json());if(!d.ok)return;const i=d.incident;
  const imgs=i.events.filter(e=>e.snapshot).map(e=>`<img src="/events/${esc(e.snapshot.split(/[\\/]/).pop())}" alt="">`).join('');
  $('b'+id).innerHTML=i.items.map(x=>`<div class="it"><time>${tm(x.t)}</time><span>${esc(x.text)}</span></div>`).join('')+imgs+
   `<div class="actions" style="margin-top:8px"><button class="hud-btn" onclick="mark(${id},'reviewed')">Mark reviewed</button>
    <a class="hud-btn primary" href="/api/incidents/${id}/evidence.zip">Download evidence pack</a></div>`}
async function check(){const f=$('pack').files[0],m=$('vmsg');if(!f){m.className='hud-msg bad';m.textContent='Choose a .zip first.';return}
  const fd=new FormData();fd.append('pack',f);m.className='hud-msg';m.textContent='Checking…';
  const d=await fetch('/api/evidence/verify',{method:'POST',body:fd}).then(r=>r.json());
  if(!d.ok){m.className='hud-msg bad';m.textContent=d.error;return}
  m.className='hud-msg '+(d.valid?'ok':'bad');
  m.textContent=d.valid?`✔ Valid: nothing changed since ${d.made}. Incident ${d.incident.id} at ${d.incident.camera}. `+(d.signed_here?'Signed by this PC.':`Signed by another PC (key ${d.fingerprint}).`)
   :'✖ Not valid: '+d.problems.join(' ')}
fetch('/api/evidence/key').then(r=>r.json()).then(d=>{$('fp').textContent=d.fingerprint});
function tog(id){const e=$('i'+id);e.classList.toggle('open');if(e.classList.contains('open')){opened.add(id);fill(id)}else opened.delete(id)}
async function mark(id,status){await fetch('/api/incidents/'+id,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({status})});load()}
$('days').onchange=load;$('min').onchange=load;load();setInterval(load,15000);
</script>"""


# ---------------- System: shut down ----------------
LAUNCHER_URL = "http://127.0.0.1:8089/"  # the launcher's start page server (browser_mode.py)


@bp.route("/api/system/shutdown", methods=["POST"])
def api_system_shutdown():
    """Stop the dashboard and the AI services. The launcher does it, since it started them."""
    try:
        r = requests.post(LAUNCHER_URL + "shutdown", json={}, timeout=5)
        if r.ok and r.json().get("app") == "ai-security-launcher":
            return jsonify({"ok": True})
    except Exception:
        pass
    return jsonify({"ok": False, "error": "The program's launcher isn't running, so it can't stop the system from here. "
                                          "Use Stop System in the control window."}), 503



# ---------------- Browser presence ----------------
# Every page in the browser checks in here (script added by _browser_presence_script). The
# launcher asks how many are open; when none are, the browser was closed and it stops the system.
BROWSER_PAGE_TIMEOUT = 150  # a page that stopped checking in (killed browser); hidden tabs check in once a minute
_browser_pages = {}  # page id -> {"seen": time, "asleep": bool}
_browser_lock = threading.Lock()


def _browser_page_id():
    raw = request.get_data(cache=False, as_text=True)[:200]
    try:
        raw = json.loads(raw).get("page", "")
    except Exception:
        pass
    raw = str(raw or "")
    return raw if re.fullmatch(r"[A-Za-z0-9_-]{6,64}", raw) else ""


@bp.route("/api/browser/<action>", methods=["POST"])
def api_browser_presence(action):
    page = _browser_page_id()
    if not page or action not in ("ping", "sleep", "bye"):
        return jsonify({"ok": False}), 400
    with _browser_lock:
        if action == "bye":
            _browser_pages.pop(page, None)
        else:
            # A browser that freezes a background tab to save power keeps it in its tab bar: still open.
            _browser_pages[page] = {"seen": time.time(), "asleep": action == "sleep"}
    return jsonify({"ok": True})


@bp.route("/api/browser/presence")
def api_browser_open_pages():
    now = time.time()
    with _browser_lock:
        for page, info in list(_browser_pages.items()):
            if not info["asleep"] and now - info["seen"] > BROWSER_PAGE_TIMEOUT:
                del _browser_pages[page]
        pages = len(_browser_pages)
    # The launcher only stops the system with the browser when this is switched on (Settings → System).
    return jsonify({"ok": True, "open_pages": pages,
                    "stop_with_browser": bool(load_settings().get("stop_with_browser"))})


_BROWSER_PRESENCE_SCRIPT = """<script>(function(){
if(window.top!==window||window.__aiPresence)return;window.__aiPresence=1;
var id=Date.now().toString(36)+Math.random().toString(36).slice(2,10);
function send(a,b){try{if(b&&navigator.sendBeacon){navigator.sendBeacon('/api/browser/'+a,JSON.stringify({page:id}));return;}
fetch('/api/browser/'+a,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({page:id}),keepalive:true}).catch(function(){});}catch(e){}}
try{var prev=sessionStorage.getItem('aiPresenceAsleep');sessionStorage.removeItem('aiPresenceAsleep');
if(prev&&document.wasDiscarded)fetch('/api/browser/bye',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({page:prev})}).catch(function(){});}catch(e){}
send('ping');setInterval(function(){send('ping');},20000);
document.addEventListener('visibilitychange',function(){if(!document.hidden)send('ping');});
document.addEventListener('freeze',function(){try{sessionStorage.setItem('aiPresenceAsleep',id);}catch(e){}send('sleep',1);});
document.addEventListener('resume',function(){send('ping');});
addEventListener('pageshow',function(e){if(e.persisted)send('ping');});
addEventListener('pagehide',function(){send('bye',1);});
})();</script>"""


@bp.after_app_request
def _browser_presence_script(resp):
    """Add the presence check-in to every page."""
    if resp.mimetype == "text/html" and not resp.direct_passthrough:
        try:
            html = resp.get_data(as_text=True)
            i = html.rfind("</body>")
            if i != -1 and "__aiPresence" not in html:
                resp.set_data(html[:i] + _BROWSER_PRESENCE_SCRIPT + html[i:])
        except Exception:
            pass
    return resp
# ---------------- END browser presence ----------------
