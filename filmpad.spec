# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

tk_datas, tk_binaries, tk_hiddenimports = collect_all('tkinter')

a = Analysis(
    ['filmpad.py'],
    pathex=[],
    binaries=tk_binaries,
    datas=[('assets', 'assets')] + tk_datas,
    hiddenimports=tk_hiddenimports + ['tkinter', '_tkinter', 'tkinter.ttk',
                                      'tkinter.filedialog', 'tkinter.font',
                                      'tkinter.messagebox'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='filmpad',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
