# -*- mode: python ; coding: utf-8 -*-
# On-prem edition ("AI Command Centre Lebanon"). Built by build_onprem.ps1 from a staging
# folder that holds launcher.pyw plus dashboard / licensing / edition compiled to native
# .pyd modules by Nuitka; no readable source for those is shipped.
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

EDGE = os.path.abspath(os.path.join(SPECPATH, '..'))
STAGE = os.environ['AI_CC_STAGE']
SLUG = os.environ.get('AI_CC_SLUG', 'AI-Command-Centre-Lebanon')

# The compiled modules hide their imports from PyInstaller, so list what they use.
hidden = ['dashboard', 'licensing', 'edition',
          'flask', 'werkzeug', 'jinja2', 'markupsafe', 'itsdangerous', 'click', 'blinker',
          'cv2', 'numpy', 'requests', 'urllib3', 'certifi', 'idna', 'charset_normalizer',
          'paho.mqtt.client', 'paho.mqtt.publish', 'yaml', 'pyttsx3', 'comtypes', 'win32com.client',
          'cryptography.hazmat.primitives.asymmetric.ed25519', 'cryptography.hazmat.primitives.serialization',
          'segno', 'winreg', 'winsound', 'ipaddress', 'concurrent.futures', 'csv', 'hmac', 'ssl', 'uuid', 'logging']
hidden += collect_submodules('pyttsx3.drivers') + collect_submodules('flask') + collect_submodules('werkzeug')

a = Analysis(
    [os.path.join(STAGE, 'launcher.pyw')],
    pathex=[STAGE],
    datas=collect_data_files('cv2', includes=['data/*.xml']),
    hiddenimports=hidden,
    excludes=['matplotlib', 'tkinter.test'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=SLUG,
          icon=os.path.join(EDGE, 'assets', 'ai_security.ico'), console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name=SLUG, upx=False)
