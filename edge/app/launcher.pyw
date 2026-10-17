import os, sys, time, socket, subprocess, threading, queue, webbrowser, shutil, urllib.request
import tkinter as tk
from tkinter import ttk, messagebox

APP_VERSION = 'V11.0.2 • Startup repair'
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
APP_HOME = os.path.dirname(os.path.abspath(__file__))
FRIGATE_DIR = os.path.join(APP_HOME, 'frigate')
OVERLAY_DIR = os.path.join(APP_HOME, 'frigate-overlay')
LOG_DIR = os.path.join(APP_HOME, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
DASHBOARD = os.path.join(OVERLAY_DIR, 'dashboard.py')
PID_FILE = os.path.join(APP_HOME, 'dashboard.pid')
DASH_LOG = os.path.join(LOG_DIR, 'dashboard.log')


def run_hidden(args, timeout=60):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)


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


def pythonw_exe():
    exe = sys.executable
    folder = os.path.dirname(exe)
    cand = os.path.join(folder, 'pythonw.exe')
    return cand if os.path.exists(cand) else exe


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'AI Security Command Center {APP_VERSION}')
        self.geometry('820x610')
        self.minsize(760, 540)
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.q = queue.Queue()
        self.busy = False
        self._build()
        self.after(200, self._poll)
        self.after(800, self.start_system)

    def _build(self):
        top = ttk.Frame(self, padding=(18,16,18,10)); top.pack(fill='x')
        ttk.Label(top, text='AI Security Command Center', font=('Segoe UI', 20, 'bold')).pack(anchor='w')
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

    def emit(self, kind, *args): self.q.put((kind,args))

    def _poll(self):
        try:
            while True:
                kind,args = self.q.get_nowait()
                if kind == 'log':
                    self.log.configure(state='normal'); self.log.insert('end', args[0]+'\n'); self.log.see('end'); self.log.configure(state='disabled')
                elif kind == 'msg': self.message.set(args[0])
                elif kind == 'status': self.status_vars[args[0]].set(args[1])
                elif kind == 'busy':
                    self.busy = args[0]; self.start_btn.configure(state='disabled' if self.busy else 'normal')
                    self.progress.start(12) if self.busy else self.progress.stop()
                elif kind == 'error': messagebox.showerror('AI Security', args[0], parent=self)
                elif kind == 'info': messagebox.showinfo('AI Security', args[0], parent=self)
        except queue.Empty:
            pass
        self.after(200, self._poll)

    def start_system(self):
        if self.busy: return
        self.busy = True
        self.start_btn.configure(state='disabled')
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        self.emit('busy', True)
        try:
            self.emit('msg','Checking Docker Desktop...'); self.emit('log','Checking Docker engine...')
            if not self.ensure_docker():
                raise RuntimeError('Docker Desktop could not be started. Open Docker Desktop, wait until it says Engine running, then click Start System.')
            self.emit('status','Docker','Running')

            self.ensure_container('frigate-mqtt', ['docker','run','-d','--name','frigate-mqtt','--restart','unless-stopped','-p','1883:1883','eclipse-mosquitto:2','mosquitto','-c','/mosquitto-no-auth.conf'])
            self.emit('status','MQTT','Running' if docker_container_running('frigate-mqtt') else 'Error')

            self.ensure_container('drone-mediamtx', ['docker','run','-d','--name','drone-mediamtx','--restart','unless-stopped','-e','MTX_RTSPTRANSPORTS=tcp','-p','1935:1935','-p','8556:8554','bluenviron/mediamtx:1'])
            self.emit('status','MediaMTX','Running' if docker_container_running('drone-mediamtx') else 'Error')

            if docker_container_exists('frigate'):
                self.ensure_container('frigate', None)
            else:
                cfg = os.path.abspath(os.path.join(FRIGATE_DIR,'config'))
                storage = os.path.abspath(os.path.join(FRIGATE_DIR,'storage')); os.makedirs(storage, exist_ok=True)
                cmd=['docker','run','-d','--name','frigate','--restart','unless-stopped','--privileged','--shm-size=512m',
                     '-p','8971:8971','-p','8554:8554','-p','8555:8555/tcp','-p','8555:8555/udp','-p','1984:1984',
                     '-v',cfg+':/config','-v',storage+':/media/frigate','-e','FRIGATE_RTSP_PASSWORD=password',
                     'ghcr.io/blakeblackshear/frigate:stable']
                self.ensure_container('frigate', cmd)

            self.emit('status','Frigate','Starting...'); self.emit('msg','Waiting for Frigate...')
            for _ in range(90):
                if port_open(8971): break
                time.sleep(1)
            self.emit('status','Frigate','Running' if port_open(8971) else 'Container running')

            self.emit('msg',f'Starting dashboard {APP_VERSION}...')
            if port_open(8080) and not http_ok('http://127.0.0.1:8080/', 2):
                raise RuntimeError('Port 8080 is already being used by another application. Close it and click Start System again.')
            if not port_open(8080): self.start_dashboard()
            for _ in range(40):
                if http_ok('http://127.0.0.1:8080/', 2): break
                time.sleep(1)
            if not http_ok('http://127.0.0.1:8080/', 2):
                raise RuntimeError('Dashboard did not start on port 8080. Click Diagnostics to open the dashboard log.')
            self.emit('status','Dashboard','Running • 8080')
            self.emit('status','Drone stream','RTSP server reachable • 8556' if port_open(8556) else 'Waiting for RTSP server')
            self.emit('msg','System ready'); self.emit('log','System ready: http://127.0.0.1:8080')
            webbrowser.open('http://127.0.0.1:8080')
        except Exception as e:
            self.emit('log','ERROR: '+str(e)); self.emit('error', str(e)); self.emit('msg','Start failed — see Activity / Diagnostics')
        finally:
            self.emit('busy', False)

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

    def ensure_container(self, name, create_cmd):
        self.emit('msg',f'Starting {name}...'); self.emit('log',f'Checking container: {name}')
        if docker_container_exists(name):
            if not docker_container_running(name):
                r=run_hidden(['docker','start',name], timeout=60)
                if r.returncode: raise RuntimeError(f'Could not start {name}: {r.stdout.strip()}')
        else:
            if not create_cmd: raise RuntimeError(f'{name} is missing and no creation command is available.')
            r=run_hidden(create_cmd, timeout=240)
            if r.returncode: raise RuntimeError(f'Could not create {name}: {r.stdout.strip()}')
        self.emit('log',f'{name}: running')

    def start_dashboard(self):
        if not os.path.isfile(DASHBOARD):
            raise RuntimeError('Dashboard file missing: ' + DASHBOARD)
        env=os.environ.copy(); env['AI_SECURITY_HOME']=OVERLAY_DIR
        log=open(DASH_LOG,'a',encoding='utf-8',errors='ignore')
        p=subprocess.Popen([pythonw_exe(), DASHBOARD], cwd=OVERLAY_DIR, env=env,
                           stdout=log, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
        with open(PID_FILE,'w') as f: f.write(str(p.pid))
        self.emit('log',f'Dashboard process started (PID {p.pid})')

    def open_dashboard(self):
        if port_open(8080): webbrowser.open('http://127.0.0.1:8080')
        else: messagebox.showwarning('Dashboard not running','Click Start System first.',parent=self)

    def diagnostics(self):
        lines=[]
        for name in ['frigate','drone-mediamtx','frigate-mqtt']:
            lines.append(f'{name}: ' + ('running' if docker_container_running(name) else ('stopped' if docker_container_exists(name) else 'missing')))
        lines += [f'8080 dashboard: {port_open(8080)}', f'8556 drone RTSP: {port_open(8556)}', f'8971 Frigate: {port_open(8971)}']
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
            if os.path.exists(PID_FILE):
                try:
                    pid=open(PID_FILE).read().strip()
                    if pid: run_hidden(['taskkill','/PID',pid,'/F'], timeout=15)
                except Exception: pass
                try: os.remove(PID_FILE)
                except OSError: pass
            for name in ['frigate','drone-mediamtx','frigate-mqtt']:
                if docker_container_exists(name):
                    try: run_hidden(['docker','stop',name], timeout=40)
                    except Exception: pass
            for k in self.status_vars: self.emit('status',k,'Stopped')
            self.emit('msg','System stopped'); self.emit('log','System stopped.')
        finally: self.emit('busy',False)

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
                path=os.path.join(FRIGATE_DIR,'config','config.yaml')
                with open(path,'r',encoding='utf-8') as f: data=yaml.safe_load(f) or {}
                data.setdefault('go2rtc',{}).setdefault('streams',{})['tony']=[urlvar.get().strip()]
                data['go2rtc']['streams']['drone']=['rtsp://host.docker.internal:8556/drone']
                with open(path,'w',encoding='utf-8') as f: yaml.safe_dump(data,f,sort_keys=False)
                messagebox.showinfo('Saved','Camera URL saved. Restart Frigate (Stop System, then Start System) to apply it.',parent=win)
            except Exception as e: messagebox.showerror('Save failed',str(e),parent=win)
        b=ttk.Frame(frm); b.pack(fill='x',side='bottom',pady=(14,0))
        ttk.Button(b,text='Save Camera',command=save).pack(side='left')
        ttk.Button(b,text='Open Dashboard',command=self.open_dashboard).pack(side='left',padx=8)
        ttk.Button(b,text='Close',command=win.destroy).pack(side='right')

    def read_camera_url(self):
        try:
            import yaml
            path=os.path.join(FRIGATE_DIR,'config','config.yaml')
            with open(path,'r',encoding='utf-8') as f: data=yaml.safe_load(f) or {}
            s=data.get('go2rtc',{}).get('streams',{}).get('tony',[''])
            if isinstance(s,list) and s: return str(s[0])
            return str(s or '')
        except Exception: return ''

    def local_ip(self):
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('8.8.8.8',80)); ip=s.getsockname()[0]; s.close(); return ip
        except Exception:
            try: return socket.gethostbyname(socket.gethostname())
            except Exception: return 'YOUR_PC_IP'

    def on_close(self): self.destroy()

if __name__=='__main__': App().mainloop()
