"""Lo que el usuario elige en la bienvenida y en Ajustes, guardado en data/settings.json para que la siguiente
sesión arranque igual: perfil, proveedor y clave del cerebro, modelo local, voz y modelo 3D.
El archivo queda solo en esta PC (data/ no se sube a ningún sitio). La clave nunca se devuelve a la interfaz.
Las claves van cifradas con la protección del sistema (companion/secret.py)."""
import copy
import json
import os
import shutil
import threading
import time

from . import secret
from .config import settings

STATE_FILE = settings.data_dir / "settings.json"
BACKUP_FILE = STATE_FILE.with_suffix(".json.bak")
_lock = threading.RLock()
_cache: dict | None = None
_cache_key: tuple[str, int | None, int | None] | None = None


def _mtime_ns(path) -> int | None:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _read(path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def load() -> dict:
    global _cache, _cache_key
    with _lock:
        key = (str(STATE_FILE), _mtime_ns(STATE_FILE), _mtime_ns(BACKUP_FILE))
        if _cache is not None and _cache_key == key:
            return copy.deepcopy(_cache)
        data = _read(STATE_FILE)
        if data is None:
            data = _read(BACKUP_FILE)         # el archivo quedó roto (apagón a mitad de guardar): la copia anterior
        revealed = secret.reveal(data or {})
        _cache = revealed
        _cache_key = key
        return copy.deepcopy(revealed)


def save(**changes) -> dict:
    global _cache, _cache_key
    with _lock:
        state = {**load(), **changes}
        text = json.dumps(secret.hide(state, str(settings.data_dir)), ensure_ascii=False, indent=1)
        # Primero a un archivo aparte y luego se cambia por el bueno de una vez: si el programa se cierra a mitad,
        # queda el anterior entero (antes se podía quedar a medias y se perdían las claves y la bienvenida).
        tmp = STATE_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if _read(STATE_FILE) is not None:        # copia del anterior, solo si estaba entero
            try:
                shutil.copyfile(STATE_FILE, BACKUP_FILE)
            except OSError:
                pass
        for attempt in range(5):              # en Windows un antivirus puede tenerlo abierto un instante
            try:
                os.replace(tmp, STATE_FILE)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1)
        _cache = None
        _cache_key = None
        return state


def protect_keys():
    """Al arrancar: las claves que guardó una versión anterior en claro pasan a ir cifradas."""
    data = _read(STATE_FILE)
    if data and secret.has_plain(data):
        save()
        BACKUP_FILE.unlink(missing_ok=True)       # la copia anterior todavía las tenía en claro


def clear():
    """Borra todo lo guardado: la siguiente carga vuelve a pedir la bienvenida."""
    global _cache, _cache_key
    with _lock:
        for f in (STATE_FILE, BACKUP_FILE, STATE_FILE.with_suffix(".json.tmp")):
            f.unlink(missing_ok=True)
        _cache = None
        _cache_key = None
