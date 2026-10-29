# -*- mode: python ; coding: utf-8 -*-
"""Сборка одиночного EXE: python -m PyInstaller PulseMonitor.spec"""

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/pulse.ico", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PulseMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/pulse.ico",
    version="packaging/version_info.txt",
)
