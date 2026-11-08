"""Browser mode: the app runs without its control window.

Starting the app opens a start page in the web browser (served here on port 8089) that shows
progress and then moves on to the dashboard. Closing the browser leaves the system guarding;
Settings → System → Shut down stops it (the dashboard asks the launcher here: POST /shutdown).
If "Stop the system when the browser closes" is switched on, every dashboard page tells the
dashboard it is open (see dashboard.py, /api/browser/*), and when none has been open for a short
while the launcher stops the system and exits.

The start page's port also makes the app single-instance: a second start finds the first one
here and asks it to open the browser (or show its window) instead of starting again.

No tkinter here, so the tests can run it anywhere.
"""
import html
import http.server
import json
import threading
import time
import urllib.request

SPLASH_PORT = 8089
SPLASH_URL = f'http://127.0.0.1:{SPLASH_PORT}/'
INSTANCE_TAG = 'ai-security-launcher'
BROWSER_GRACE = 15    # seconds with no open page before the system stops (covers moving between pages)
WAKE_GRACE = 90       # after the PC wakes from sleep, pages need a moment to check in again
SPLASH_ALIVE = 75     # a hidden start-page tab may only poll once a minute
NO_BROWSER_SHOW_WINDOW = 90  # the browser never opened the start page: show the window instead


class BrowserWatch:
    """Decides when the browser has been closed. step() is called every couple of seconds with
    whether a page is open (True / False, or None when it can't tell) and returns 'stop',
    'show-window' or None."""

    def __init__(self, now):
        self.started = now
        self.last_step = now
        self.seen = False
        self.closed_since = None
        self.grace = BROWSER_GRACE
        self.window_asked = False

    def step(self, now, page_open, busy=False, splash_ever_seen=True):
        if now - self.last_step > 30:  # the PC slept: start the count again, with more time
            self.closed_since = None
            self.grace = WAKE_GRACE
        self.last_step = now
        if not self.seen and not splash_ever_seen and not self.window_asked \
                and now - self.started > NO_BROWSER_SHOW_WINDOW:
            self.window_asked = True
            return 'show-window'
        if busy or page_open is None:  # starting up, or the dashboard isn't answering: wait
            self.closed_since = None
            return None
        if page_open:
            self.seen = True
            self.closed_since = None
            self.grace = BROWSER_GRACE
            return None
        if not self.seen:
            return None
        if self.closed_since is None:
            self.closed_since = now
        return 'stop' if now - self.closed_since >= self.grace else None


def dashboard_presence(port, timeout=2):
    """{'open_pages': n, 'stop_with_browser': bool}, or None if the dashboard doesn't answer."""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/browser/presence', timeout=timeout) as r:
            d = json.loads(r.read().decode('utf-8'))
        return {'open_pages': int(d.get('open_pages', 0)), 'stop_with_browser': bool(d.get('stop_with_browser'))}
    except Exception:
        return None


def notify_running_instance(action, timeout=2):
    """Ask an already running launcher to 'open' the browser or 'show' its window ('ping': just ask).
    True if one answered, so this start should just exit."""
    try:
        req = urllib.request.Request(SPLASH_URL + action, data=b'{}', method='POST',
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8')).get('app') == INSTANCE_TAG
    except Exception:
        return False


class _ExclusiveServer(http.server.ThreadingHTTPServer):
    # Windows lets two programs share a port with SO_REUSEADDR; the port is our single-instance lock.
    allow_reuse_address = False
    daemon_threads = True


class StartPage:
    """The start page server. `owner` provides status() -> dict and on_action(name)."""

    def __init__(self, owner, product_name, port=SPLASH_PORT):
        self.owner = owner
        self.product_name = product_name
        self.port = port
        self.last_seen = 0.0
        self.open = False
        self.server = None

    def start(self):
        """Start serving. False if the port is taken (another copy is running, or another program)."""
        page = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body, ctype='application/json'):
                data = body.encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = self.path.split('?', 1)[0]
                if path == '/':
                    page.seen()
                    self._send(200, START_PAGE.replace('__NAME__', html.escape(page.product_name)),
                               'text/html; charset=utf-8')
                elif path == '/status':
                    page.seen()
                    self._send(200, json.dumps(page.owner.status()))
                else:
                    self._send(404, '{"ok": false}')

            def do_POST(self):
                path = self.path.split('?', 1)[0].strip('/')
                origin = self.headers.get('Origin')
                if origin and origin not in (f'http://127.0.0.1:{page.port}', f'http://localhost:{page.port}'):
                    return self._send(403, '{"ok": false}')  # other web sites can't drive the launcher
                length = int(self.headers.get('Content-Length') or 0)
                if length:
                    self.rfile.read(min(length, 4096))
                if path == 'bye':
                    page.open = False
                elif path == 'ping':
                    pass
                elif path in ('show', 'open', 'retry', 'shutdown'):
                    page.owner.on_action(path)
                else:
                    return self._send(404, '{"ok": false}')
                self._send(200, json.dumps({'ok': True, 'app': INSTANCE_TAG}))

        try:
            self.server = _ExclusiveServer(('127.0.0.1', self.port), Handler)
        except OSError:
            return False
        threading.Thread(target=self.server.serve_forever, name='start-page', daemon=True).start()
        return True

    def seen(self):
        self.last_seen = time.time()
        self.open = True

    def is_open(self, now):
        return self.open and now - self.last_seen < SPLASH_ALIVE

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass


START_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__NAME__</title>
<style>
:root{color-scheme:dark}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#020b12;color:#cfefff;font:15px "Segoe UI",Arial,sans-serif}
.box{width:min(560px,calc(100% - 32px));border:1px solid #155879;border-radius:6px;background:#03101a;padding:28px}
h1{margin:0 0 4px;font-size:22px;color:#e8f8ff;letter-spacing:.5px}
.sub{color:#6fb6d6;font-size:13px;margin-bottom:22px}
.bar{height:6px;border-radius:3px;background:#0a2a3b;overflow:hidden}
.bar i{display:block;height:100%;width:35%;background:#2bc0ff;border-radius:3px;animation:run 1.4s ease-in-out infinite}
@keyframes run{0%{margin-left:-35%}100%{margin-left:100%}}
#msg{margin-top:14px;min-height:20px}
#err{display:none;margin-top:16px;padding:12px;border:1px solid #7a2a2a;background:#1c0909;color:#ffb4b4;border-radius:4px;white-space:pre-wrap}
.actions{display:none;margin-top:14px;gap:8px}
button{background:#0b3550;color:#e8f8ff;border:1px solid #2b7aa3;border-radius:4px;padding:8px 14px;font:inherit;cursor:pointer}
button:hover{background:#114a6e}
.note{margin-top:22px;color:#5d8ea6;font-size:12px}
</style></head><body>
<div class="box">
  <h1>__NAME__</h1>
  <div class="sub">Starting the system. This page opens the dashboard when it is ready.</div>
  <div class="bar" id="bar"><i></i></div>
  <div id="msg">Starting...</div>
  <div id="err"></div>
  <div class="actions" id="actions"><button id="retry">Try again</button><button id="show">Show control window</button></div>
  <div class="note">The system keeps guarding when you close the browser. To stop it: Settings → System → Shut down.</div>
</div>
<script>
(function(){
  var done=false;
  function post(p){return fetch('/'+p,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).catch(function(){});}
  function tick(){
    fetch('/status',{cache:'no-store'}).then(function(r){return r.json();}).then(function(s){
      if(done)return;
      if(s.ready&&s.url){done=true;document.getElementById('msg').textContent='Opening the dashboard...';location.replace(s.url);return;}
      document.getElementById('msg').textContent=s.message||'Starting...';
      var e=document.getElementById('err');
      if(s.error){e.style.display='block';e.textContent=s.error;document.getElementById('bar').style.display='none';document.getElementById('actions').style.display='flex';}
      else{e.style.display='none';document.getElementById('bar').style.display='';document.getElementById('actions').style.display='none';}
    }).catch(function(){
      document.getElementById('msg').textContent='The program has stopped. Start it again from the desktop icon.';
      document.getElementById('bar').style.display='none';
    });
  }
  document.getElementById('retry').onclick=function(){post('retry');};
  document.getElementById('show').onclick=function(){post('show');};
  addEventListener('pagehide',function(){if(!done){try{navigator.sendBeacon('/bye','{}');}catch(e){}}});
  tick();setInterval(tick,1000);
})();
</script>
</body></html>"""
