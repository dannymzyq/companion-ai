"""Modelos 3D: los incluidos (models/avatar1.vrm, avatar2.vrm y la esfera, que no tiene archivo) y los VRM propios
que sube el usuario (models/custom/).

Los incluidos nunca se sobrescriben: los propios se guardan aparte y se puede volver a ellos cuando se quiera.
La elección se recuerda en data/settings.json. El modelo de Mika se retiró el 13 nov 2026 (decisión del usuario);
los nombres son genéricos y sin género, como las voces.
"""
import re
from pathlib import Path

from . import vrm
from .config import settings

CUSTOM_DIR = settings.models_dir / "custom"
ID_RE = re.compile(r"^[a-z0-9_-]{1,60}$")
MAX_MB = 200


class ModelError(ValueError):
    pass


from .state import load as _state, save as _save  # noqa: E402


# Personajes incluidos. La esfera no tiene archivo: la dibuja la interfaz (web/js/orb.js). Cualquier voz se puede
# usar con cualquiera de ellos.
BUILTIN = [
    {"id": "avatar1", "name": "Avatar 1", "file": "avatar1.vrm", "note": "Personaje incluido"},
    {"id": "avatar2", "name": "Avatar 2", "file": "avatar2.vrm", "note": "Personaje incluido"},
    {"id": "avatar3", "name": "Avatar 3", "file": None, "note": "Una esfera que cambia de color con lo que siente"},
]
BUILTIN_IDS = {b["id"] for b in BUILTIN}
DEFAULT_ID = BUILTIN[0]["id"]
# Lo que se guardaba antes: el modelo de Mika («default») y los nombres viejos pasan a los nuevos.
LEGACY = {"default": DEFAULT_ID, "chica": "avatar1", "chico": "avatar2", "esfera": "avatar3"}


def _builtin(model_id: str) -> dict | None:
    return next((b for b in BUILTIN if b["id"] == model_id), None)


def _available(b: dict) -> bool:
    return not b["file"] or (settings.models_dir / b["file"]).is_file()


def kind(persona_name: str = "") -> str:
    """'orb' si el personaje activo es la esfera; 'vrm' en los demás casos."""
    b = _builtin(active_id())
    return "orb" if b and not b["file"] else "vrm"


def _custom_path(model_id: str) -> Path:
    if not ID_RE.match(model_id):
        raise ModelError("Identificador de modelo no válido")
    return CUSTOM_DIR / f"{model_id}.vrm"


def custom_list() -> list[dict]:
    out = []
    for path in sorted(CUSTOM_DIR.glob("*.vrm")) if CUSTOM_DIR.is_dir() else []:
        if path.stem in BUILTIN_IDS:
            continue
        try:
            meta = vrm.extract_meta(vrm.read_gltf_json_file(path))
        except (vrm.VRMError, ValueError, OSError):
            continue
        out.append({"id": path.stem, "name": meta.get("name") or path.stem, "spec": meta["spec"],
                    "size_mb": round(path.stat().st_size / 1e6, 1)})
    return out


def active_id(persona_name: str = "") -> str:
    wanted = str(_state().get("model") or DEFAULT_ID)
    wanted = LEGACY.get(wanted, wanted)
    b = _builtin(wanted)
    if b and _available(b):
        return wanted
    if not b and ID_RE.match(wanted) and _custom_path(wanted).is_file():
        return wanted
    return next((x["id"] for x in BUILTIN if _available(x)), DEFAULT_ID)


def active_path(persona_name: str = "") -> Path | None:
    current = active_id()
    b = _builtin(current)
    if b:
        return settings.models_dir / b["file"] if b["file"] else None
    return _custom_path(current)


def listing(persona_name: str = "") -> dict:
    return {"active": active_id(),
            "builtin": [{"id": b["id"], "name": b["name"], "note": b["note"], "available": _available(b)} for b in BUILTIN],
            "custom": custom_list()}


def select(model_id: str):
    model_id = LEGACY.get(model_id, model_id)
    b = _builtin(model_id)
    if b:
        if not _available(b):
            raise ModelError("Ese personaje no está instalado")
    elif not _custom_path(model_id).is_file():
        raise ModelError("Ese modelo no existe")
    _save(model=model_id)


def add(filename: str, data: bytes) -> dict:
    """Valida y guarda un VRM propio, y lo deja como modelo activo."""
    try:
        meta = vrm.extract_meta(vrm.read_gltf_json(data))
    except (vrm.VRMError, ValueError, UnicodeDecodeError) as e:
        raise ModelError(f"VRM inválido: {e}") from e
    stem = re.sub(r"[^a-z0-9_-]+", "-", Path(filename or "modelo").stem.lower()).strip("-")[:48] or "modelo"
    if stem in BUILTIN_IDS or stem in LEGACY:
        stem = f"{stem}-propio"
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    model_id, n = stem, 2
    while _custom_path(model_id).exists():
        model_id, n = f"{stem}-{n}", n + 1
    _custom_path(model_id).write_bytes(data)
    _save(model=model_id)
    return {"id": model_id, "meta": meta, "license_warnings": vrm.license_warnings(meta)}


def remove(model_id: str):
    if model_id in BUILTIN_IDS or model_id in LEGACY:      # los incluidos no se borran
        raise ModelError("Solo se pueden quitar los modelos propios")
    path = _custom_path(model_id)
    if not path.is_file():
        raise ModelError("Solo se pueden quitar los modelos propios")
    path.unlink()
    if _state().get("model") == model_id:
        _save(model=DEFAULT_ID)
