"""Sign-in and users: the first-run admin, the sign-in gate on every request, roles, login and logout.

Part of the dashboard (registered by dashboard.py with setup()); the role rules are in users.py.
"""
import ipaddress
import os
import time
import urllib.parse

from flask import Blueprint, Response, g, jsonify, redirect, request, session

import users as user_accounts

try:
    from edition import PRODUCT_NAME
except Exception:  # noqa: BLE001
    PRODUCT_NAME = "AI Security Command Center"

bp = Blueprint("access", __name__)
hud_page = None  # set by setup()
DATA_FOLDER = ""
USERS_FILE = ""  # set by setup()
# Before the first admin exists, everything asks for one (/welcome). Tests turn this off.
REQUIRE_FIRST_ADMIN = True
_login_fails = {}


def setup(app, data_folder, hud_page_fn):
    global hud_page, DATA_FOLDER, USERS_FILE
    hud_page, DATA_FOLDER = hud_page_fn, data_folder
    USERS_FILE = os.path.join(DATA_FOLDER, "users.json")
    app.register_blueprint(bp)


def current_user():
    """The signed-in user, or None (also None while sign-in is off)."""
    users = user_accounts.load(USERS_FILE)
    u = user_accounts.find(users, session.get("user")) if users else None
    return u if u and session.get("stamp") == u.get("stamp") else None


WELCOME_PAGE = r"""
<main class="hud-main" style="max-width:460px;margin:50px auto">
<div class="page-head"><div><div class="page-kicker">First start</div><h1 class="page-title">Create the admin account</h1>
<div class="page-sub">This account protects the cameras and the drones. You'll sign in with it, and can add viewers and operators later under Settings → Users.</div></div></div>
<section class="panel"><div class="panel-body">
<label for="u">User name</label><input id="u" autocomplete="username" autofocus>
<label for="p1" style="margin-top:10px">Password (8+ characters)</label><input id="p1" type="password" autocomplete="new-password">
<label for="p2" style="margin-top:10px">Password again</label><input id="p2" type="password" autocomplete="new-password">
<div class="actions" style="margin-top:14px"><button class="hud-btn primary" id="go">Create and sign in</button></div>
<div id="msg" class="hud-msg"></div>
</div></section></main>
<script>
const $=id=>document.getElementById(id);
async function go(){const m=$('msg');m.className='hud-msg';
  if($('p1').value!==$('p2').value){m.className='hud-msg bad';m.textContent='The two passwords are different.';return}
  const d=await fetch('/api/users',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({username:$('u').value,password:$('p1').value,role:'admin'})}).then(r=>r.json());
  if(!d.ok){m.className='hud-msg bad';m.textContent=d.error;return}location.href='/'}
$('go').onclick=go;$('p2').addEventListener('keydown',e=>{if(e.key==='Enter')go()});
</script>"""
FIRST_RUN_PATHS = ("/welcome", "/hud.css")


@bp.route("/welcome")
def welcome_page():
    if user_accounts.load(USERS_FILE):
        return redirect("/")
    return Response(hud_page("Create the admin account", WELCOME_PAGE, nav=False), mimetype="text/html")


@bp.before_app_request
def _require_sign_in():
    g.user = None
    path = request.path
    if not user_accounts.load(USERS_FILE):
        if not REQUIRE_FIRST_ADMIN:
            return None
        if path in user_accounts.OPEN_PATHS or path in FIRST_RUN_PATHS or \
                any(path.startswith(p) for p in user_accounts.OPEN_PATHS if p.endswith("/")) or \
                (path == "/api/users" and request.method == "POST"):
            return None
        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Create the admin account first (open the dashboard)."}), 401
        return redirect("/welcome")
    if path in user_accounts.OPEN_PATHS or any(path.startswith(p) for p in user_accounts.OPEN_PATHS if p.endswith("/")):
        return None
    g.user = current_user()
    if not g.user:
        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Sign in first."}), 401
        return redirect("/login?next=" + urllib.parse.quote(request.full_path.rstrip("?")))
    if not user_accounts.allowed(g.user["role"], request.method, path):
        msg = f"Your role ({g.user['role']}) can't do that. Ask an admin."
        return (jsonify({"ok": False, "error": msg}), 403) if path.startswith("/api/") or request.method != "GET" else \
            Response(hud_page("Not allowed", f'<main class="hud-main"><h1 class="page-title">Not allowed</h1><p class="muted">{msg}</p>'
                                              '<a class="hud-btn" href="/">Back to the dashboard</a></main>'), status=403, mimetype="text/html")
    return None


@bp.after_app_request
def _user_badge(resp):
    """Who is signed in, with Sign out, on every page."""
    u = getattr(g, "user", None)
    if u and resp.mimetype == "text/html" and not resp.direct_passthrough:
        try:
            html = resp.get_data(as_text=True)
            i = html.rfind("</body>")
            if i != -1:
                badge = ('<div id="userBadge" style="position:fixed;left:10px;bottom:10px;z-index:9999;background:rgba(3,16,26,.92);'
                         'border:1px solid #155879;border-radius:4px;padding:5px 9px;font:12px Arial;color:#9edfff">👤 '
                         f'{html_escape(u["username"])} · {u["role"]} · <a href="/logout" style="color:#5bd9ff">Sign out</a></div>')
                resp.set_data(html[:i] + badge + html[i:])
        except Exception:
            pass
    return resp


def html_escape(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


LOGIN_PAGE = r"""
<main class="hud-main" style="max-width:420px;margin:60px auto">
<div class="page-head"><div><div class="page-kicker">AI Security</div><h1 class="page-title">Sign in</h1></div></div>
<section class="panel"><div class="panel-body">
<form method="post">
<input type="hidden" name="next" value="__NEXT__">
<label for="u">User name</label><input id="u" name="username" autocomplete="username" autofocus required>
<label for="pw" style="margin-top:10px">Password</label><input id="pw" name="password" type="password" autocomplete="current-password" required>
<div class="actions" style="margin-top:14px"><button class="hud-btn primary" type="submit">Sign in</button></div>
<div class="hud-msg bad" style="__ERRSTYLE__">__ERR__</div>
</form>__RESET__</div></section></main>"""
FORGOT = ('<p class="muted" style="margin-top:14px;font-size:13px">Forgot the password? On this PC open '
          f'<b>Start → {PRODUCT_NAME} - Reset sign-in</b>. The dashboard uses its own user names, not your portal email.</p>')
RESET_READY = ('<div class="hud-msg" style="margin-top:14px">A sign-in reset was requested on this PC. '
               '<a class="hud-btn primary" href="/reset-signin">Choose a new password</a></div>')


@bp.route("/login", methods=["GET", "POST"])
def login_page():
    nxt = request.values.get("next") or "/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    if not user_accounts.load(USERS_FILE):
        return redirect("/welcome" if REQUIRE_FIRST_ADMIN else "/users")
    err = ""
    if request.method == "POST":
        ip = request.remote_addr or ""
        fails = [t for t in _login_fails.get(ip, []) if time.time() - t < 300]
        if len(fails) >= 5:
            err = "Too many wrong tries. Wait 5 minutes."
        else:
            u = user_accounts.authenticate(USERS_FILE, request.form.get("username"), request.form.get("password"))
            if u:
                session.clear()
                session.permanent = True
                session.update(user=u["username"], stamp=u.get("stamp"))
                _login_fails.pop(ip, None)
                return redirect(nxt)
            time.sleep(1)
            _login_fails[ip] = fails + [time.time()]
            err = "Wrong user name or password."
    body = (LOGIN_PAGE.replace("__NEXT__", html_escape(nxt)).replace("__ERR__", html_escape(err))
            .replace("__ERRSTYLE__", "" if err else "display:none")
            .replace("__RESET__", RESET_READY if reset_requested() else FORGOT))
    return Response(hud_page("Sign in", body, nav=False), mimetype="text/html")


# Forgotten password: Start menu → "<product> - Reset sign-in" (launcher.pyw --reset-signin) writes this file in
# the data folder; for 15 minutes the sign-in page then offers to choose a new password, only in a browser on
# this PC. Writing the file needs this Windows account, which can read every file of the app anyway.
RESET_FILE_NAME = "reset-signin.request"
RESET_VALID_S = 15 * 60


def _reset_file():
    return os.path.join(DATA_FOLDER, RESET_FILE_NAME)


def reset_requested():
    """A fresh reset request, made on this PC, for a browser on this PC."""
    try:
        if time.time() - os.path.getmtime(_reset_file()) > RESET_VALID_S:
            return False
        return ipaddress.ip_address((request.remote_addr or "").split("%")[0]).is_loopback
    except (OSError, ValueError):
        return False


RESET_PAGE = r"""
<main class="hud-main" style="max-width:460px;margin:60px auto">
<div class="page-head"><div><div class="page-kicker">AI Security</div><h1 class="page-title">Choose a new password</h1>
<div class="page-sub">Requested from this PC's Start menu. Pick the admin account and its new password; you are then signed in.</div></div></div>
<section class="panel"><div class="panel-body"><form method="post">
<label for="u">Account</label><select id="u" name="username">__USERS__</select>
<label for="p1" style="margin-top:10px">New password (8+ characters)</label><input id="p1" name="password" type="password" autocomplete="new-password" required minlength="8">
<label for="p2" style="margin-top:10px">New password again</label><input id="p2" name="password2" type="password" autocomplete="new-password" required minlength="8">
<div class="actions" style="margin-top:14px"><button class="hud-btn primary" type="submit">Save and sign in</button></div>
<div class="hud-msg bad" style="__ERRSTYLE__">__ERR__</div>
</form></div></section></main>"""


@bp.route("/reset-signin", methods=["GET", "POST"])
def reset_signin_page():
    if not reset_requested():
        return Response(hud_page("Reset sign-in", '<main class="hud-main" style="max-width:520px;margin:60px auto">'
                                 '<h1 class="page-title">Reset sign-in</h1><p class="muted">On the PC running the system, open '
                                 f'<b>Start → {PRODUCT_NAME} - Reset sign-in</b>, then use the browser window it opens '
                                 '(within 15 minutes).</p><a class="hud-btn" href="/login">Back to sign in</a></main>', nav=False),
                        status=403, mimetype="text/html")
    admins = [u for u in user_accounts.load(USERS_FILE) if u["role"] == "admin"]
    if not admins:
        return redirect("/welcome")
    err = ""
    if request.method == "POST":
        name, pw = request.form.get("username"), request.form.get("password") or ""
        try:
            if pw != (request.form.get("password2") or ""):
                raise ValueError("The two passwords are different.")
            u = user_accounts.find(admins, name)
            if not u:
                raise ValueError("Choose an admin account.")
            u = user_accounts.update(USERS_FILE, u["username"], password=pw)
            try:
                os.remove(_reset_file())
            except OSError:
                pass
            session.clear()
            session.permanent = True
            session.update(user=u["username"], stamp=u.get("stamp"))
            _login_fails.clear()
            try:
                import web_records
                web_records.audit_record("password reset from the Start menu", target=u["username"], user=u["username"])
            except Exception:
                pass
            return redirect("/")
        except ValueError as e:
            err = str(e)
    opts = "".join(f'<option value="{html_escape(u["username"])}">{html_escape(u["username"])}</option>' for u in admins)
    body = (RESET_PAGE.replace("__USERS__", opts).replace("__ERR__", html_escape(err))
            .replace("__ERRSTYLE__", "" if err else "display:none"))
    return Response(hud_page("Reset sign-in", body, nav=False), mimetype="text/html")


@bp.route("/logout")
def logout_page():
    session.clear()
    return redirect("/login" if user_accounts.load(USERS_FILE) or REQUIRE_FIRST_ADMIN else "/")


USERS_PAGE = r"""
<main class="hud-main">
<div class="page-head"><div><div class="page-kicker">Access</div><h1 class="page-title">Users &amp; roles</h1>
<div class="page-sub">Who can use this dashboard. <b>Viewer</b>: watches live video, events and maps. <b>Operator</b>: also flies drones, routes and drone responses. <b>Admin</b>: everything, including setup, licences, no-fly zones and users.</div></div></div>
<section class="panel"><div class="panel-body">
<div id="firstNote" class="hud-msg" style="display:none">Sign-in is <b>off</b>: anyone at this PC can use everything. Create the first user below (an admin) to turn it on; you will be signed in as that user.</div>
<div id="userList"></div>
<div style="margin-top:14px;border-top:1px solid #123447;padding-top:12px"><b style="color:#5bd9ff;font-size:11px;letter-spacing:1.5px">ADD A USER</b>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0 10px">
<div><label for="nu">User name</label><input id="nu" autocomplete="off"></div>
<div><label for="np">Password (8+ characters)</label><input id="np" type="password" autocomplete="new-password"></div>
<div><label for="nr">Role</label><select id="nr"><option value="viewer">Viewer: watch only</option><option value="operator">Operator: watch and fly</option><option value="admin">Admin: everything</option></select></div></div>
<div class="actions" style="margin-top:10px"><button class="hud-btn primary" onclick="addUser()">Add user</button></div>
<div id="umsg" class="hud-msg"></div></div>
</div></section></main>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const ROLES={viewer:'Viewer: watch only',operator:'Operator: watch and fly',admin:'Admin: everything'};
let me='',arm='';
function umsg(t,ok){const e=$('umsg');e.className='hud-msg '+(ok===true?'ok':ok===false?'bad':'');e.textContent=t}
async function call(url,method,body){const r=await fetch(url,{method,headers:{'content-type':'application/json'},body:body?JSON.stringify(body):undefined});return r.json()}
async function load(){const d=await call('/api/users','GET');if(!d.ok){umsg(d.error,false);return}me=d.me||'';
  $('firstNote').style.display=d.users.length?'none':'';if(!d.users.length){$('nr').value='admin'}
  $('userList').innerHTML=d.users.map(u=>`<div class="hud-row"><div><b>${esc(u.username)}</b>${u.username===me?' <span class="muted">(you)</span>':''}<div class="muted">${ROLES[u.role]}</div></div>
    <div class="actions"><select onchange="setRole('${esc(u.username)}',this.value)">${Object.keys(ROLES).map(r=>`<option value="${r}" ${r===u.role?'selected':''}>${r}</option>`).join('')}</select>
    <button class="hud-btn" onclick="resetPw('${esc(u.username)}')">New password</button>
    <button class="hud-btn danger" onclick="delUser('${esc(u.username)}',this)">${arm===u.username?'Click again to delete':'Delete'}</button></div></div>`).join('')||'<p class="muted">No users yet.</p>'}
async function addUser(){const first=!$('userList').querySelector('.hud-row');
  const d=await call('/api/users','POST',{username:$('nu').value,password:$('np').value,role:$('nr').value});
  if(!d.ok){umsg(d.error,false);return}$('nu').value=$('np').value='';umsg('User '+d.username+' added.'+(first?' Sign-in is now on.':''),true);if(first)location.reload();else load()}
async function setRole(n,r){const d=await call('/api/users/'+encodeURIComponent(n),'POST',{role:r});umsg(d.ok?n+' is now '+r+'.':d.error,d.ok);load()}
async function resetPw(n){const pw=prompt('New password for '+n+' (8+ characters):');if(!pw)return;const d=await call('/api/users/'+encodeURIComponent(n),'POST',{password:pw});
  umsg(d.ok?'Password changed. '+n+' is signed out on other devices.':d.error,d.ok);if(d.ok&&n===me)location.href='/login'}
async function delUser(n){if(arm!==n){arm=n;load();setTimeout(()=>{if(arm===n){arm='';load()}},4000);return}arm='';
  const d=await call('/api/users/'+encodeURIComponent(n),'DELETE');umsg(d.ok?n+' deleted.':d.error,d.ok);if(d.ok&&n===me)location.href='/login';else load()}
load();
</script>"""


@bp.route("/users")
def users_page():
    return Response(hud_page("Users", USERS_PAGE, active="users"), mimetype="text/html")


@bp.route("/api/users", methods=["GET", "POST"])
def api_users():
    all_users = user_accounts.load(USERS_FILE)
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        try:
            name = user_accounts.add(USERS_FILE, data.get("username"), data.get("password"), data.get("role"))
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        if not all_users:  # the first admin is signed in straight away
            u = user_accounts.find(user_accounts.load(USERS_FILE), name)
            session.clear()
            session.permanent = True
            session.update(user=u["username"], stamp=u.get("stamp"))
        return jsonify({"ok": True, "username": name})
    me = current_user()
    return jsonify({"ok": True, "users": [user_accounts.public(u) for u in all_users], "me": me["username"] if me else ""})


@bp.route("/api/users/<name>", methods=["POST", "DELETE"])
def api_user(name):
    try:
        if request.method == "DELETE":
            user_accounts.delete(USERS_FILE, name)
        else:
            data = request.get_json(silent=True) or {}
            user_accounts.update(USERS_FILE, name, role=data.get("role"), password=data.get("password"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})

