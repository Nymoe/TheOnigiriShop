# Build resources explicitly; never collect databases or backups.
from pathlib import Path
import runpy

root = Path(SPECPATH).parent
source = root / 'Source'
icon = source / 'Assets' / 'onigiri.ico'
check_build=runpy.run_path(str(source / 'build_safety.py'))['ensure_executable_not_running']
check_build(Path(DISTPATH) / 'TheOnigiriShop.exe')
a = Analysis([str(source / 'windows_launcher.py')], pathex=[str(source)],
    binaries=[], datas=[(str(icon), '.')],
    hiddenimports=['matplotlib.backends.backend_tkagg'],
    hookspath=[], hooksconfig={'matplotlib': {'backends': ['TkAgg']}},
    runtime_hooks=[], excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6'])
pyz = PYZ(a.pure)
check_build(Path(DISTPATH) / 'TheOnigiriShop.exe')
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='TheOnigiriShop',
    debug=False, strip=False, upx=False, console=False,
    icon=str(icon))
