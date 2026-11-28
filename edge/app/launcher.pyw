import os, sys, json, time, socket, subprocess, threading, queue, webbrowser, shutil, urllib.request
import tkinter as tk
from tkinter import ttk, messagebox

import edition
import browser_mode as browser_mode_lib
import docker_setup

APP_VERSION = 'V11.25.1'
PRODUCT_NAME = edition.PRODUCT_NAME
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
FROZEN = getattr(sys, 'frozen', False)

# Program files (read-only when installed) are kept apart from user data, so the
# installer can replace the program without touching cameras, faces or events.
APP_HOME = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
DATA_HOME = os.environ.get('AI_SECURITY_DATA') or os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), edition.DATA_DIR_NAME)
FRIGATE_DIR = os.path.join(DATA_HOME, 'frigate')
FRIGATE_CONFIG = os.path.join(FRIGATE_DIR, 'config', 'config.yaml')
OVERLAY_DIR = os.path.join(DATA_HOME, 'frigate-overlay')
LOG_DIR = os.path.join(DATA_HOME, 'logs')
PID_FILE = os.path.join(DATA_HOME, 'dashboard.pid')
DASH_LOG = os.path.join(LOG_DIR, 'dashboard.log')
LAUNCHER_LOG = os.path.join(LOG_DIR, 'launcher.log')
LOG_MAX_BYTES = 5 * 1024 * 1024
DASHBOARD_PORT = 8080
CONTAINERS = ['frigate', 'drone-mediamtx', 'frigate-mqtt']
COMPOSE_PROJECT = 'ai-security'


def _first_existing(*paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return paths[0]


# Installed: <app>\runtime. Source checkout: edge\app\..\runtime.
RUNTIME_DIR = _first_existing(os.path.join(APP_HOME, 'runtime'),
                              os.path.join(os.path.dirname(APP_HOME), 'runtime'))
COMPOSE_FILE = os.path.join(RUNTIME_DIR, 'docker-compose.yml')
FRIGATE_TEMPLATE = os.path.join(RUNTIME_DIR, 'frigate', 'config.example.yaml')
DASHBOARD_SCRIPT = os.path.join(APP_HOME, 'dashboard.py')
# Offline install package (docker save of the pinned images), from the installer or USB stick.
OFFLINE_IMAGE_BUNDLES = [os.path.join(d, 'ai-command-centre-images.tar')
                         for d in (os.path.join(APP_HOME, 'offline'), os.path.join(DATA_HOME, 'offline'))]

for d in (LOG_DIR, OVERLAY_DIR, os.path.join(FRIGATE_DIR, 'config'), os.path.join(FRIGATE_DIR, 'storage')):
    os.makedirs(d, exist_ok=True)


def run_hidden(args, timeout=60, env=None):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW, env=env)


def port_open(port, host='127.0.0.1', timeout=0.4):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_ok(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def docker_container_exists(name):
    try:
        return run_hidden(['docker','inspect',name], timeout=10).returncode == 0
    except Exception:
        return False


def docker_container_running(name):
    try:
        r = run_hidden(['docker','inspect','-f','{{.State.Running}}',name], timeout=10)
        return r.returncode == 0 and r.stdout.strip().lower() == 'true'
    except Exception:
        return False


def docker_container_project(name):
    try:
        r = run_hidden(['docker','inspect','-f','{{index .Config.Labels "com.docker.compose.project"}}',name], timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def compose(*args, timeout=600):
    env = os.environ.copy()
    env['AI_SECURITY_DATA'] = DATA_HOME.replace('\\', '/')
    return run_hidden(['docker','compose','-p',COMPOSE_PROJECT,'-f',COMPOSE_FILE,*args], timeout=timeout, env=env)


def pythonw_exe():
    exe = sys.executable
    folder = os.path.dirname(exe)
    cand = os.path.join(folder, 'pythonw.exe')
    return cand if os.path.exists(cand) else exe


def rotate_log(path, max_bytes=LOG_MAX_BYTES):
    try:
        if os.path.getsize(path) > max_bytes:
            os.replace(path, path + '.1')
    except OSError:
        pass


def run_dashboard_in_process():
    """Frozen build: `AI-Security-Command-Center.exe --dashboard` runs the dashboard."""
    log = open(DASH_LOG, 'a', encoding='utf-8', errors='ignore', buffering=1)
    sys.stdout = sys.stderr = log  # windowed builds have no console streams
    os.environ.setdefault('AI_SECURITY_HOME', OVERLAY_DIR)
    os.chdir(OVERLAY_DIR)
    import dashboard  # may be a compiled extension module in the on-prem build
    dashboard.main()


class App(tk.Tk):
    """browser_mode (the normal start): no window; the system opens in the web browser and stops when
    the browser is closed. `--window` shows this control window instead and nothing stops on its own."""

    def __init__(self, browser_mode=True, background=False):
        super().__init__()
        self.title(f'{PRODUCT_NAME} {APP_VERSION}')
        self.geometry('820x610')
        self.minsize(760, 540)
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.q = queue.Queue()
        self.busy = False
        self.stage = 'Starting...'
        self.ready_url = ''
        self.error = ''
        self.window_shown = not browser_mode
        self.quitting = False
        self.background = background  # started with Windows: run without opening the browser
        self.need_docker = False      # Docker Desktop isn't installed: the start page / window asks to install it
        self._build()
        self.start_page = browser_mode_lib.StartPage(self, PRODUCT_NAME)
        if not self.start_page.start():
            self.start_page = None  # port taken by another program: no start page, use the window
        self.browser_mode = browser_mode and self.start_page is not None
        if self.browser_mode:
            self.withdraw()
            if not background:
                webbrowser.open(browser_mode_lib.SPLASH_URL)
            threading.Thread(target=self._browser_watch, name='browser-watch', daemon=True).start()
        else:
            self.window_shown = True
        self.after(200, self._poll)
        self.after(800, self.start_system)

    # ---- start page (browser_mode.StartPage owner) ----
    def status(self):
        return {'message': self.stage, 'ready': bool(self.ready_url) and not self.busy,
                'url': self.ready_url, 'error': self.error, 'need_docker': self.need_docker and not self.busy}

    def on_action(self, name):
        if name == 'shutdown':  # Settings → System → Shut down (the dashboard asks, admins only)
            threading.Thread(target=self._shutdown, daemon=True).start()
        elif name == 'logout':  # Settings → System → Log out and turn off: also Docker
            threading.Thread(target=self._logout, daemon=True).start()
        elif name == 'install_docker':
            if not self.busy:
                self.need_docker = False
                threading.Thread(target=self._install_docker, daemon=True).start()
        elif name == 'skip_docker':
            self.need_docker = False
            self.error = ("The cameras' AI, recordings and drone video need Docker Desktop, so the system is not running. "
                          "Click Try again to install it, or install Docker Desktop yourself and then Try again.")
            self.emit('msg', 'Docker Desktop is not installed')
        else:
            self.emit(name)

    def _shutdown(self):
        self.emit('log', 'Shut down asked from the dashboard: stopping the system.')
        time.sleep(1)  # let the dashboard answer its page first
        self._stop_services()
        self.emit('quit')

    def _logout(self):
        """Stop everything, Docker Desktop included. The program (and with it Docker) starts at the next Windows sign-in."""
        self.emit('log', 'Log out asked from the dashboard: stopping the system and Docker Desktop.')
        time.sleep(1)  # let the dashboard answer its page first
        self._stop_services()
        try:
            stopped = docker_setup.stop_docker()
            self.emit('log', 'Docker Desktop stopped.' if stopped else 'Docker Desktop may still be running.')
        except Exception as e:
            self.emit('log', f'Could not stop Docker Desktop: {e}')
        if FROZEN:
            try:
                docker_setup.ensure_autostart(sys.executable)
            except Exception as e:
                self.emit('log', f'Could not set the start at Windows sign-in: {e}')
        self.emit('quit')

    def _install_docker(self):
        """Install Docker Desktop (the person said yes), then start the system, which sets up the AI services."""
        self.emit('busy', True); self.error = ''
        restart = False
        try:
            folders = [APP_HOME, os.path.dirname(APP_HOME)] + [os.path.dirname(b) for b in OFFLINE_IMAGE_BUNDLES]
            path = docker_setup.local_installer(folders)
            if not path:
                os.makedirs(os.path.join(DATA_HOME, 'updates'), exist_ok=True)
                path = os.path.join(DATA_HOME, 'updates', docker_setup.INSTALLER_NAME)
                self.emit('msg', 'Downloading Docker Desktop (about 600 MB)...'); self.emit('log', 'Downloading Docker Desktop...')
                docker_setup.download(docker_setup.INSTALLER_URL[docker_setup.arch()], path,
                                      progress=lambda pct: pct >= 0 and self.emit('msg', f'Downloading Docker Desktop... {pct}%'))
            self.emit('msg', 'Checking the Docker Desktop installer...')
            if not docker_setup.signature_ok(path):
                raise RuntimeError('The Docker Desktop installer is not signed by Docker Inc., so it was not run. '
                                   'Download it from https://www.docker.com/products/docker-desktop/ and install it yourself.')
            self.emit('msg', 'Installing Docker Desktop: allow it when Windows asks. This takes a few minutes...')
            self.emit('log', 'Running the Docker Desktop installer (Windows asks for permission).')
            code = docker_setup.run_installer(path)
            self.emit('log', f'Docker Desktop installer finished (exit code {code}).')
            if code is None and not docker_setup.installed():
                raise RuntimeError('Docker Desktop was not installed (the Windows permission prompt was declined). Click Try again.')
            try:
                docker_setup.ensure_autostart(sys.executable) if FROZEN else None
            except Exception:
                pass
            if code != 0 or not docker_setup.installed():
                restart = True
                raise RuntimeError('Restart the computer to finish installing Docker Desktop. '
                                   f'{PRODUCT_NAME} starts by itself after the restart and sets up the AI services.')
            self.emit('log', 'Docker Desktop installed.')
        except Exception as e:
            self.error = str(e)
            self.emit('log', ('RESTART NEEDED: ' if restart else 'ERROR: ') + str(e))
            self.emit('msg', 'Restart needed' if restart else 'Docker Desktop was not installed')
            if not self.browser_mode: self.emit('error', str(e))
            self.emit('busy', False)
            return
        self.emit('busy', False)
        self.emit('retry')  # start the system: Docker starts, then docker compose installs the AI services

    def show_window(self):
        """From now on the person drives the system from the window; closing the browser stops nothing."""
        self.window_shown = True
        self.deiconify(); self.lift()
        try: self.focus_force()
        except Exception: pass

    def _browser_watch(self):
        watch = browser_mode_lib.BrowserWatch(time.time())
        while not self.quitting:
            time.sleep(2)
            if self.window_shown:
                return
            now = time.time()
            presence = browser_mode_lib.dashboard_presence(DASHBOARD_PORT)
            page_open = True if self.start_page.is_open(now) else None
            if page_open is None and presence is not None:
                # Normally the system keeps guarding with the browser closed; it only stops with the
                # browser when Settings → System → "Stop the system when the browser closes" is on.
                page_open = presence['open_pages'] > 0 or not presence['stop_with_browser']
            decision = watch.step(now, page_open, busy=self.busy,
                                  splash_ever_seen=self.background or self.start_page.last_seen > 0)
            if decision == 'show-window':
                self.emit('log', 'The browser did not open the start page; showing the control window.')
                self.emit('show')
                return
            if decision == 'stop' and not self.window_shown:
                self.emit('log', 'Browser closed: stopping the system.')
                self._stop_services()
                self.emit('quit')
                return

    def _build(self):
        top = ttk.Frame(self, padding=(18,16,18,10)); top.pack(fill='x')
        ttk.Label(top, text=PRODUCT_NAME, font=('Segoe UI', 20, 'bold')).pack(anchor='w')
        ttk.Label(top, text=f'{APP_VERSION} • Camera + Drone • Frigate + MQTT + MediaMTX').pack(anchor='w', pady=(2,0))

        status = ttk.LabelFrame(self, text='System status', padding=12); status.pack(fill='x', padx=18, pady=(0,10))
        self.status_vars = {}
        keys = ['Docker','MQTT','MediaMTX','Frigate','Dashboard','Drone stream']
        for i, key in enumerate(keys):
            col = (i % 2) * 2; row = i // 2
            ttk.Label(status, text=key, width=16).grid(row=row, column=col, sticky='w', padx=(0,6), pady=3)
            v = tk.StringVar(value='Checking...'); self.status_vars[key] = v
            ttk.Label(status, textvariable=v, width=26).grid(row=row, column=col+1, sticky='w', pady=3)

        actions = ttk.Frame(self, padding=(18,0)); actions.pack(fill='x')
        self.start_btn = ttk.Button(actions, text='Start System', command=self.start_system); self.start_btn.pack(side='left', padx=(0,7))
        ttk.Button(actions, text='Open Dashboard', command=self.open_dashboard).pack(side='left', padx=7)
        ttk.Button(actions, text='Camera / Drone Setup', command=self.open_settings).pack(side='left', padx=7)
        ttk.Button(actions, text='Diagnostics', command=self.diagnostics).pack(side='left', padx=7)
        ttk.Button(actions, text='Stop System', command=self.stop_system).pack(side='right')

        self.progress = ttk.Progressbar(self, mode='indeterminate'); self.progress.pack(fill='x', padx=18, pady=(12,0))
        self.message = tk.StringVar(value='Ready')
        ttk.Label(self, textvariable=self.message).pack(anchor='w', padx=18, pady=(5,8))

        logf = ttk.LabelFrame(self, text='Activity', padding=8); logf.pack(fill='both', expand=True, padx=18, pady=(0,14))
        self.log = tk.Text(logf, height=12, wrap='word', state='disabled', font=('Consolas', 9))
        scr = ttk.Scrollbar(logf, orient='vertical', command=self.log.yview)
        self.log.configure(yscrollcommand=scr.set)
        self.log.pack(side='left', fill='both', expand=True); scr.pack(side='right', fill='y')

    def emit(self, kind, *args):
        if kind == 'msg': self.stage = args[0]
        self.q.put((kind,args))

    def _file_log(self, text):
        try:
            rotate_log(LAUNCHER_LOG)
            with open(LAUNCHER_LOG, 'a', encoding='utf-8', errors='ignore') as f:
                f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + text + '\n')
        except OSError:
            pass

    def _poll(self):
        try:
            while True:
                kind,args = self.q.get_nowait()
                if kind == 'log':
                    self._file_log(args[0])
                    self.log.configure(state='normal'); self.log.insert('end', args[0]+'\n'); self.log.see('end'); self.log.configure(state='disabled')
                elif kind == 'msg': self.message.set(args[0])
                elif kind == 'status': self.status_vars[args[0]].set(args[1])
                elif kind == 'busy':
                    self.busy = args[0]; self.start_btn.configure(state='disabled' if self.busy else 'normal')
                    self.progress.start(12) if self.busy else self.progress.stop()
                elif kind == 'error':
                    if self.browser_mode: self.show_window()
                    messagebox.showerror(PRODUCT_NAME, args[0], parent=self)
                elif kind == 'show': self.show_window()
                elif kind == 'open': webbrowser.open(self.ready_url or browser_mode_lib.SPLASH_URL)
                elif kind == 'retry': self.start_system()
                elif kind == 'quit': self.on_close()
                elif kind == 'info': messagebox.showinfo(PRODUCT_NAME, args[0], parent=self)
                elif kind == 'ask_docker':
                    yes = messagebox.askyesno(PRODUCT_NAME, 'Docker Desktop is not installed on this computer. It runs the '
                                              'cameras\' AI, recordings and drone video.\n\nInstall it now? It downloads '
                                              '(about 600 MB, unless the installer is next to this program), Windows asks for '
                                              'permission, and a restart may be needed.', parent=self)
                    self.on_action('install_docker' if yes else 'skip_docker')
        except queue.Empty:
            pass
        self.after(200, self._poll)

    def start_system(self):
        if self.busy: return
        self.busy = True
        self.error = ''
        self.start_btn.configure(state='disabled')
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        self.emit('busy', True)
        try:
            self.emit('msg','Checking Docker Desktop...'); self.emit('log','Checking Docker engine...')
            if os.name == 'nt' and not docker_setup.installed() and not self.docker_answers():
                # Docker Desktop isn't on this PC: ask before installing it (start page or control window).
                self.need_docker = True
                self.emit('msg', 'Docker Desktop is needed to run the AI services.')
                self.emit('log', 'Docker Desktop is not installed: asking to install it.')
                if not self.browser_mode: self.emit('ask_docker')
                return
            if not self.ensure_docker():
                raise RuntimeError('Docker Desktop could not be started. Open Docker Desktop, wait until it says Engine running, then click Start System.')
            self.emit('status','Docker','Running')

            if not os.path.isfile(COMPOSE_FILE):
                raise RuntimeError('Runtime file missing: ' + COMPOSE_FILE + '. Reinstall the application.')
            self.seed_frigate_config()
            self.seed_dock_broker()
            self.replace_legacy_containers()
            self.load_offline_images()

            self.emit('msg','Starting MQTT, MediaMTX and Frigate...'); self.emit('log','docker compose up -d (first start downloads images and can take several minutes)')
            r = compose('up','-d')
            if r.returncode:
                raise RuntimeError('Could not start the AI services:\n' + r.stdout.strip()[-800:])
            self.emit('status','MQTT','Running' if docker_container_running('frigate-mqtt') else 'Error')
            self.emit('status','MediaMTX','Running' if docker_container_running('drone-mediamtx') else 'Error')
            self.emit('log','Dock broker: ' + ('running' if docker_container_running('dock-mqtt') else 'not running'))

            self.emit('status','Frigate','Starting...'); self.emit('msg','Waiting for Frigate...')
            for _ in range(90):
                if port_open(8971): break
                time.sleep(1)
            self.emit('status','Frigate','Running' if port_open(8971) else 'Container running')

            self.emit('msg',f'Starting dashboard {APP_VERSION}...')
            url = f'http://127.0.0.1:{DASHBOARD_PORT}/'
            if port_open(DASHBOARD_PORT) and not http_ok(url, 2):
                raise RuntimeError(f'Port {DASHBOARD_PORT} is already being used by another application. Close it and click Start System again.')
            if not port_open(DASHBOARD_PORT): self.start_dashboard()
            for _ in range(40):
                if http_ok(url, 2): break
                time.sleep(1)
            if not http_ok(url, 2):
                raise RuntimeError(f'Dashboard did not start on port {DASHBOARD_PORT}. Click Diagnostics to open the dashboard log.')
            self.emit('status','Dashboard',f'Running • {DASHBOARD_PORT}')
            self.emit('status','Drone stream','RTSP server reachable • 8556' if port_open(8556) else 'Waiting for RTSP server')
            self.emit('msg','System ready'); self.emit('log',f'System ready: {url}')
            self.ready_url = url
            if not self.browser_mode: webbrowser.open(url)  # browser mode: the start page moves on to it
        except Exception as e:
            self.error = str(e)
            self.emit('log','ERROR: '+str(e)); self.emit('error', str(e)); self.emit('msg','Start failed — see Activity / Diagnostics')
        finally:
            self.emit('busy', False)

    def seed_frigate_config(self):
        """First start on a new PC: give Frigate a starter config."""
        if os.path.isfile(FRIGATE_CONFIG) or not os.path.isfile(FRIGATE_TEMPLATE):
            return
        shutil.copyfile(FRIGATE_TEMPLATE, FRIGATE_CONFIG)
        settings_file = os.path.join(OVERLAY_DIR, 'local_settings.json')
        if not os.path.exists(settings_file):
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump({'camera_name': 'camera'}, f, indent=2)
        self.emit('log', 'Created starter Frigate config. Use Camera / Drone Setup to add your camera.')

    def seed_dock_broker(self):
        """The DJI Dock broker's config and passwords (made once), before docker compose starts it."""
        try:
            import dock
            dock.ensure_broker_files(os.path.join(DATA_HOME, 'dock-mqtt'))
        except Exception as e:
            self.emit('log', 'Dock broker setup skipped: ' + str(e))

    def load_offline_images(self):
        """Offline install: load the AI service images from the USB package if missing,
        so the first start needs no internet."""
        r = compose('config', '--images', timeout=60)
        images = [i.strip() for i in r.stdout.splitlines() if i.strip()] if r.returncode == 0 else []
        missing = [i for i in images if run_hidden(['docker', 'image', 'inspect', i], timeout=20).returncode != 0]
        if not missing:
            return
        bundle = next((p for p in OFFLINE_IMAGE_BUNDLES if os.path.isfile(p)), None)
        if not bundle:
            self.emit('log', 'AI services will be downloaded from the internet (no offline package found).')
            return
        self.emit('msg', 'Loading AI services from the offline package (several minutes)...')
        self.emit('log', f'Loading {len(missing)} image(s) from {bundle}')
        r = run_hidden(['docker', 'load', '-i', bundle], timeout=3600)
        if r.returncode:
            raise RuntimeError('Could not load the offline AI services package:\n' + r.stdout.strip()[-600:])
        self.emit('log', 'AI services loaded from the offline package.')
        if bundle.startswith(APP_HOME):  # installer's copy: free ~2 GB now that Docker has it
            try: os.remove(bundle)
            except OSError: pass

    def replace_legacy_containers(self):
        """Containers created by older versions (C:\\frigate, V8-V11 scripts) use the same
        names but other config folders. Remove them so only this runtime is used.
        Only the containers are removed; config, recordings and events stay on disk."""
        for name in CONTAINERS:
            if docker_container_exists(name) and docker_container_project(name) != COMPOSE_PROJECT:
                self.emit('log', f'Replacing old {name} container with the {APP_VERSION} runtime')
                run_hidden(['docker','rm','-f',name], timeout=60)

    def docker_answers(self):
        try:
            return run_hidden(['docker','info'], timeout=12).returncode == 0
        except Exception:
            return False

    def ensure_docker(self):
        try:
            if run_hidden(['docker','info'], timeout=12).returncode == 0: return True
        except Exception: pass
        docker_desktop = r'C:\Program Files\Docker\Docker\Docker Desktop.exe'
        if os.path.exists(docker_desktop):
            self.emit('log','Starting Docker Desktop...')
            subprocess.Popen([docker_desktop], creationflags=CREATE_NO_WINDOW)
            for _ in range(90):
                time.sleep(1)
                try:
                    if run_hidden(['docker','info'], timeout=8).returncode == 0: return True
                except Exception: pass
        return False

    def start_dashboard(self):
        if FROZEN:
            cmd = [sys.executable, '--dashboard']
        else:
            if not os.path.isfile(DASHBOARD_SCRIPT):
                raise RuntimeError('Dashboard file missing: ' + DASHBOARD_SCRIPT)
            cmd = [pythonw_exe(), DASHBOARD_SCRIPT]
        rotate_log(DASH_LOG)
        env=os.environ.copy(); env['AI_SECURITY_HOME']=OVERLAY_DIR; env['AI_SECURITY_DATA']=DATA_HOME
        log=open(DASH_LOG,'a',encoding='utf-8',errors='ignore')
        p=subprocess.Popen(cmd, cwd=OVERLAY_DIR, env=env,
                           stdout=log, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
        with open(PID_FILE,'w') as f: f.write(str(p.pid))
        self.emit('log',f'Dashboard process started (PID {p.pid})')

    def open_dashboard(self):
        if port_open(DASHBOARD_PORT): webbrowser.open(f'http://127.0.0.1:{DASHBOARD_PORT}')
        else: messagebox.showwarning('Dashboard not running','Click Start System first.',parent=self)

    def diagnostics(self):
        lines=[f'Version: {APP_VERSION}', f'Program: {APP_HOME}', f'Data: {DATA_HOME}']
        for name in CONTAINERS:
            lines.append(f'{name}: ' + ('running' if docker_container_running(name) else ('stopped' if docker_container_exists(name) else 'missing')))
        lines += [f'{DASHBOARD_PORT} dashboard: {port_open(DASHBOARD_PORT)}', f'8556 drone RTSP: {port_open(8556)}', f'8971 Frigate: {port_open(8971)}']
        self.emit('log','DIAGNOSTICS\n'+'\n'.join(lines))
        if os.path.exists(DASH_LOG):
            try: os.startfile(DASH_LOG)
            except Exception: pass
        else:
            messagebox.showinfo('Diagnostics','\n'.join(lines),parent=self)

    def stop_system(self):
        if self.busy: return
        if not messagebox.askyesno('Stop AI Security','Stop dashboard, Frigate, MediaMTX and MQTT?',parent=self): return
        threading.Thread(target=self._stop_worker,daemon=True).start()

    def _stop_worker(self):
        self.emit('busy',True); self.emit('msg','Stopping system...')
        try:
            self._stop_services()
            for k in self.status_vars: self.emit('status',k,'Stopped')
            self.emit('msg','System stopped'); self.emit('log','System stopped.')
        finally: self.emit('busy',False)

    def _stop_services(self):
        """Stop the dashboard and the AI services (Docker Desktop itself keeps running)."""
        self.ready_url = ''
        if os.path.exists(PID_FILE):
            try:
                pid=open(PID_FILE).read().strip()
                if pid: run_hidden(['taskkill','/PID',pid,'/T','/F'], timeout=15)
            except Exception: pass
            try: os.remove(PID_FILE)
            except OSError: pass
        try: compose('--profile', 'mapping', 'stop', timeout=120)  # also the 3D mapping engine, if it was started
        except Exception: pass

    def open_settings(self):
        win=tk.Toplevel(self); win.title('Camera / Drone Setup'); win.geometry('700x470'); win.minsize(640,430); win.transient(self)
        frm=ttk.Frame(win,padding=16); frm.pack(fill='both',expand=True)
        ttk.Label(frm,text='Camera / Drone Setup',font=('Segoe UI',16,'bold')).pack(anchor='w')
        ttk.Label(frm,text='Main camera RTSP URL').pack(anchor='w',pady=(16,4))
        urlvar=tk.StringVar(value=self.read_camera_url()); ttk.Entry(frm,textvariable=urlvar).pack(fill='x')
        ttk.Label(frm,text='Example: rtsp://username:password@192.168.1.50:554/stream1').pack(anchor='w',pady=(3,12))
        ip=self.local_ip(); drone=f'rtmp://{ip}:1935/drone'
        ttk.Label(frm,text='DJI / Drone RTMP address').pack(anchor='w',pady=(8,4))
        e=ttk.Entry(frm); e.insert(0,drone); e.configure(state='readonly'); e.pack(fill='x')
        ttk.Label(frm,text='DJI Fly → Live Streaming Platforms → RTMP → paste the address above.').pack(anchor='w',pady=(4,8))
        state='Drone RTSP endpoint 8556 is reachable.' if port_open(8556) else 'MediaMTX is not reachable yet. Click Start System first.'
        ttk.Label(frm,text=state).pack(anchor='w',pady=(4,12))
        def save():
            try:
                import yaml
                with open(FRIGATE_CONFIG,'r',encoding='utf-8') as f: data=yaml.safe_load(f) or {}
                streams=data.setdefault('go2rtc',{}).setdefault('streams',{})
                streams[self.camera_name(data)]=[urlvar.get().strip()]
                streams['drone']=['rtsp://host.docker.internal:8556/drone']
                shutil.copyfile(FRIGATE_CONFIG, FRIGATE_CONFIG + '.bak')
                with open(FRIGATE_CONFIG,'w',encoding='utf-8') as f: yaml.safe_dump(data,f,sort_keys=False)
                messagebox.showinfo('Saved','Camera URL saved. Restart Frigate (Stop System, then Start System) to apply it.',parent=win)
            except Exception as e: messagebox.showerror('Save failed',str(e),parent=win)
        b=ttk.Frame(frm); b.pack(fill='x',side='bottom',pady=(14,0))
        ttk.Button(b,text='Save Camera',command=save).pack(side='left')
        ttk.Button(b,text='Open Dashboard',command=self.open_dashboard).pack(side='left',padx=8)
        ttk.Button(b,text='Close',command=win.destroy).pack(side='right')

    @staticmethod
    def camera_name(data):
        """The first non-drone camera in the Frigate config (e.g. 'tony' or 'camera')."""
        for name in (data.get('cameras') or {}):
            if name != 'drone':
                return name
        return 'camera'

    def read_camera_url(self):
        try:
            import yaml
            with open(FRIGATE_CONFIG,'r',encoding='utf-8') as f: data=yaml.safe_load(f) or {}
            s=data.get('go2rtc',{}).get('streams',{}).get(self.camera_name(data),[''])
            if isinstance(s,list) and s: return str(s[0])
            return str(s or '')
        except Exception: return ''

    def local_ip(self):
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('8.8.8.8',80)); ip=s.getsockname()[0]; s.close(); return ip
        except Exception:
            try: return socket.gethostbyname(socket.gethostname())
            except Exception: return 'YOUR_PC_IP'

    def on_close(self):
        """Closing the window leaves the system running, as before (Stop System stops it)."""
        self.quitting = True
        if self.start_page: self.start_page.stop()
        self.destroy()


if __name__=='__main__':
    if '--dashboard' in sys.argv:
        run_dashboard_in_process()
    elif '--reset-signin' in sys.argv:
        # Start menu → "Reset sign-in": for 15 minutes a browser on this PC may choose a new dashboard password
        # (web_access.reset_signin_page). Opens that page, starting the system first if it isn't running.
        os.makedirs(DATA_HOME, exist_ok=True)
        with open(os.path.join(DATA_HOME, 'reset-signin.request'), 'w') as f:
            f.write(str(int(time.time())))
        if port_open(DASHBOARD_PORT):
            webbrowser.open(f'http://127.0.0.1:{DASHBOARD_PORT}/reset-signin')
        elif not browser_mode_lib.notify_running_instance('open'):
            App(browser_mode=True, background=False).mainloop()  # the sign-in page then offers the reset
    else:
        window = '--window' in sys.argv
        background = '--background' in sys.argv  # Windows sign-in: start guarding, no browser
        if background and browser_mode_lib.notify_running_instance('ping'):
            sys.exit(0)
        # Already running: bring up the browser (or the control window) and leave it at that.
        if background or not browser_mode_lib.notify_running_instance('show' if window else 'open'):
            App(browser_mode=not window, background=background and not window).mainloop()
