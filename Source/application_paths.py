"""Application locations independent of the current working directory."""
from pathlib import Path
import sys


def project_root() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_database() -> Path:
    return project_root() / 'Data' / 'btm495.db'


def backup_folder(database: Path) -> Path:
    database = Path(database).resolve()
    root = project_root()
    if database.parent == (root / 'Data').resolve():
        return root / 'Backups'
    return database.parent / 'backups'


def asset_path(name: str) -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / name
    return project_root() / 'Source' / 'Assets' / name
