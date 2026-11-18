"""Prevent rebuilding a single-file executable while it is still in use."""
import json
import os
from pathlib import Path
import subprocess


def ensure_executable_not_running(executable):
    if os.name!='nt':return
    script="$ErrorActionPreference='Stop'; $paths=@(Get-Process | Where-Object {$_.ProcessName -eq 'TheOnigiriShop'} | Select-Object -ExpandProperty Path); ConvertTo-Json -InputObject $paths -Compress; exit 0"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
        capture_output=True,text=True,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    paths=json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(paths,str):paths=[paths]
    target=os.path.normcase(str(Path(executable).resolve()))
    if any(os.path.normcase(str(Path(path).resolve()))==target for path in paths if path):
        raise RuntimeError('Close all Onigiri Shop windows before replacing this executable. '
            'Moving or replacing a running build can break later imports, including graphs.')
