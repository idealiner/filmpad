# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

tk_datas, tk_binaries, tk_hiddenimports = collect_all('tkinter')

# PyInstaller's tcltk_info auto-discovery fails on this system; add the
# Tcl/Tk data directories explicitly so pyi_rth__tkinter.py can find them.
import os
_tcl_src = '/usr/share/tcltk/tcl8.6'
_tk_src  = '/usr/share/tcltk/tk8.6'
extra_datas = []
if os.path.isdir(_tcl_src):
    extra_datas.append((_tcl_src, '_tcl_data'))
if os.path.isdir(_tk_src):
    extra_datas.append((_tk_src, '_tk_data'))

a = Analysis(
    ['filmpad.py'],
    pathex=[],
    binaries=tk_binaries,
    datas=[('assets', 'assets')] + tk_datas + extra_datas,
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
