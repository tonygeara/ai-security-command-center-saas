# -*- mode: python ; coding: utf-8 -*-
# One program: AI-Security-Command-Center.exe opens the launcher window, and
# "AI-Security-Command-Center.exe --dashboard" runs the dashboard web server.
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

EDGE = os.path.abspath(os.path.join(SPECPATH, '..'))
APP = os.path.join(EDGE, 'app')

a = Analysis(
    [os.path.join(APP, 'launcher.pyw')],
    pathex=[APP],
    # cv2/data holds the Haar face detector used by face enrollment.
    datas=collect_data_files('cv2', includes=['data/*.xml']),
    hiddenimports=['dashboard', 'paho.mqtt.client', 'yaml', 'requests', 'cv2']
                  + collect_submodules('pyttsx3.drivers') + ['comtypes', 'win32com.client'],
    excludes=['matplotlib', 'tkinter.test'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='AI-Security-Command-Center',
    icon=os.path.join(EDGE, 'assets', 'ai_security.ico'),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name='AI-Security-Command-Center', upx=False)
