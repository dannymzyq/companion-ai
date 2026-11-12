"""Lo que el usuario elige en la bienvenida y en Ajustes, guardado en data/settings.json para que la siguiente
sesión arranque igual: perfil, proveedor y clave del cerebro, modelo local, voz y modelo 3D.
El archivo queda solo en esta PC (data/ no se sube a ningún sitio). La clave nunca se devuelve a la interfaz."""
import json

from .config import settings

STATE_FILE = settings.data_dir / "settings.json"


def load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(**changes) -> dict:
    state = {**load(), **changes}
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return state


def clear():
    """Borra todo lo guardado: la siguiente carga vuelve a pedir la bienvenida."""
    STATE_FILE.unlink(missing_ok=True)
