"""Docker Desktop on the client's PC: install it when it's missing, stop it on "Log out and turn off", and make sure
the program (which starts Docker) runs at the next Windows sign-in.

Installing: the launcher asks first (start page or control window). The installer comes from a copy next to the
program or the on-prem USB folder ("Docker Desktop Installer.exe"), or is downloaded from Docker. It must carry a
valid Docker Inc. code signature, then runs with Windows' own permission prompt (UAC):
`install --quiet --accept-license --backend=wsl-2`. Docker may need a restart to finish (WSL 2); the program then
starts by itself after the restart and sets up the AI services (docker compose).

No tkinter here, so the tests can run it anywhere.
"""
import ntpath
import os
import platform
import subprocess
import sys
import urllib.request

CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
DESKTOP_EXE = r'C:\Program Files\Docker\Docker\Docker Desktop.exe'
INSTALLER_NAME = 'Docker Desktop Installer.exe'
INSTALLER_URL = {
    'amd64': 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe',
    'arm64': 'https://desktop.docker.com/win/main/arm64/Docker%20Desktop%20Installer.exe',
}
INSTALL_ARGS = ['install', '--quiet', '--accept-license', '--backend=wsl-2']
SIGNER = 'Docker Inc'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def _run(args, timeout=60):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)


def installed(path=DESKTOP_EXE):
    return os.path.exists(path)


def arch():
    m = (os.environ.get('PROCESSOR_ARCHITECTURE') or platform.machine() or '').lower()
    return 'arm64' if 'arm' in m else 'amd64'


def local_installer(folders):
    """A Docker Desktop installer brought along (next to the program, or on the on-prem USB stick)."""
    for d in folders:
        p = os.path.join(d or '', INSTALLER_NAME)
        if d and os.path.isfile(p):
            return p
    return None


def download(url, dest, progress=lambda pct: None, opener=urllib.request.urlopen):
    """Download to dest (reporting whole percents). Returns dest."""
    tmp = dest + '.part'
    req = urllib.request.Request(url, headers={'User-Agent': 'AI-Security-Setup'})
    with opener(req, timeout=60) as r, open(tmp, 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0)
        got, last = 0, -1
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            pct = int(got * 100 / total) if total else -1
            if pct != last:
                last = pct
                progress(pct)
    os.replace(tmp, dest)
    return dest


def signature_ok(path, run=_run):
    """True when Windows says the file carries a valid code signature from Docker Inc."""
    ps = ("$s = Get-AuthenticodeSignature -LiteralPath $args[0]; "
          "Write-Output ($s.Status.ToString() + '|' + $s.SignerCertificate.Subject)")
    try:
        r = run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps, path], timeout=60)
    except Exception:  # noqa: BLE001
        return False
    out = (r.stdout or '').strip().splitlines()[-1:] or ['']
    status, _, subject = out[0].partition('|')
    return status == 'Valid' and SIGNER in subject


def run_installer(path, run=_run):
    """Run the installer with Windows' permission prompt and wait. Returns its exit code (None: refused or failed).
    0 = installed; others usually mean a restart is needed or the person said no."""
    ps = ("$p = Start-Process -FilePath $args[0] -ArgumentList $args[1..($args.Length-1)] -Verb RunAs -Wait -PassThru; "
          "Write-Output $p.ExitCode")
    try:
        r = run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps, path, *INSTALL_ARGS], timeout=3600)
    except Exception:  # noqa: BLE001
        return None
    try:
        return int((r.stdout or '').strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None  # the permission prompt was refused


def stop_docker(run=_run):
    """Quit Docker Desktop and its engine (and so every container). True when the engine no longer answers."""
    try:
        if run(['docker', 'desktop', 'stop'], timeout=180).returncode == 0:
            return True
    except Exception:  # noqa: BLE001 - older Docker Desktop has no "docker desktop stop"
        pass
    for args in (['taskkill', '/IM', 'Docker Desktop.exe', '/T', '/F'], ['taskkill', '/IM', 'com.docker.backend.exe', '/T', '/F'],
                 ['wsl', '--terminate', 'docker-desktop']):
        try:
            run(args, timeout=60)
        except Exception:  # noqa: BLE001
            pass
    try:
        return run(['docker', 'info'], timeout=15).returncode != 0
    except Exception:  # noqa: BLE001
        return True


def ensure_autostart(exe=None, winreg=None):
    """Start the program (and with it Docker) at the next Windows sign-in: the installer's "start with Windows"
    value, added again if it's missing. Returns True when it is set."""
    if os.name != 'nt' and winreg is None:
        return False
    if winreg is None:
        import winreg  # noqa: PLC0415 - Windows only
    exe = exe or sys.executable
    name = ntpath.splitext(ntpath.basename(exe))[0]  # Windows paths (also when tested elsewhere)
    value = f'"{exe}" --background'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
        try:
            if winreg.QueryValueEx(k, name)[0]:
                return True
        except OSError:
            pass
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    return True
