"""Ubicaciones de SIGED, calculadas al iniciar el proceso."""

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
DATA_DIR = Path(os.environ.get("GESTOR_DATA_DIR", str(BASE_DIR))).expanduser().resolve()
DB_PATH = DATA_DIR / "gestor.db"
STORAGE_DIR = DATA_DIR / "storage"
AVISOS_DIR = STORAGE_DIR / "avisos"
FOTOS_PERFIL_DIR = STORAGE_DIR / "perfiles"
SECRET_PATH = DATA_DIR / ".secret_key"
BACKUP_DIR = DATA_DIR / "respaldos"
CACHE_LOCAL = Path(os.environ.get("LOCALAPPDATA", str(DATA_DIR / "cache")))
DIRECTORIO_CACHE = CACHE_LOCAL / "SIGED" / "previsualizaciones"
