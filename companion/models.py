"""Modelos 3D: el de fábrica (models/<personaje>.vrm) y los VRM propios que sube el usuario (models/custom/).

El modelo de fábrica nunca se sobrescribe: los propios se guardan aparte y se puede volver a él cuando se quiera.
La elección se recuerda en data/settings.json.
"""
import json
import re
from pathlib import Path

from . import vrm
from .config import settings

DEFAULT_ID = "default"
CUSTOM_DIR = settings.models_dir / "custom"
STATE_FILE = settings.data_dir / "settings.json"
ID_RE = re.compile(r"^[a-z0-9_-]{1,60}$")
MAX_MB = 200


class ModelError(ValueError):
    pass


from .state import load as _state, save as _save  # noqa: E402


# Personajes incluidos. «default» es el del personaje (models/<nombre>.vrm); la esfera no tiene archivo: la
# dibuja la interfaz (web/js/orb.js). Cualquier voz se puede usar con cualquiera de ellos.
BUILTIN = [
    {"id": "chica", "name": "Chica", "file": "chica.vrm", "note": "Personaje incluido"},
    {"id": "chico", "name": "Chico", "file": "chico.vrm", "note": "Personaje incluido"},
    {"id": "esfera", "name": "Esfera", "file": None, "note": "Cambia de color con lo que siente"},
]
BUILTIN_IDS = {b["id"] for b in BUILTIN}


def _builtin(model_id: str) -> dict | None:
    return next((b for b in BUILTIN if b["id"] == model_id), None)


def default_path(persona_name: str) -> Path | None:
    path = settings.models_dir / f"{persona_name.lower()}.vrm"
    return path if path.is_file() else None


def kind(persona_name: str) -> str:
    """'orb' si el personaje activo es la esfera; 'vrm' en los demás casos."""
    b = _builtin(active_id(persona_name))
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


def active_id(persona_name: str) -> str:
    wanted = _state().get("model", DEFAULT_ID)
    b = _builtin(wanted)
    if b and (not b["file"] or (settings.models_dir / b["file"]).is_file()):
        return wanted
    if wanted != DEFAULT_ID and not b and ID_RE.match(wanted) and _custom_path(wanted).is_file():
        return wanted
    return DEFAULT_ID


def active_path(persona_name: str) -> Path | None:
    current = active_id(persona_name)
    b = _builtin(current)
    if b:
        return settings.models_dir / b["file"] if b["file"] else None
    return default_path(persona_name) if current == DEFAULT_ID else _custom_path(current)


def listing(persona_name: str) -> dict:
    return {"active": active_id(persona_name),
            "default": {"id": DEFAULT_ID, "name": persona_name, "available": default_path(persona_name) is not None},
            "builtin": [{"id": b["id"], "name": b["name"], "note": b["note"],
                         "available": not b["file"] or (settings.models_dir / b["file"]).is_file()} for b in BUILTIN],
            "custom": custom_list()}


def select(model_id: str):
    b = _builtin(model_id)
    if b:
        if b["file"] and not (settings.models_dir / b["file"]).is_file():
            raise ModelError("Ese personaje no está instalado")
    elif model_id != DEFAULT_ID and not _custom_path(model_id).is_file():
        raise ModelError("Ese modelo no existe")
    _save(model=model_id)


def add(filename: str, data: bytes) -> dict:
    """Valida y guarda un VRM propio, y lo deja como modelo activo."""
    try:
        meta = vrm.extract_meta(vrm.read_gltf_json(data))
    except (vrm.VRMError, ValueError, UnicodeDecodeError) as e:
        raise ModelError(f"VRM inválido: {e}") from e
    stem = re.sub(r"[^a-z0-9_-]+", "-", Path(filename or "modelo").stem.lower()).strip("-")[:48] or "modelo"
    if stem == DEFAULT_ID or stem in BUILTIN_IDS:
        stem = f"{stem}-propio"
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    model_id, n = stem, 2
    while _custom_path(model_id).exists():
        model_id, n = f"{stem}-{n}", n + 1
    _custom_path(model_id).write_bytes(data)
    _save(model=model_id)
    return {"id": model_id, "meta": meta, "license_warnings": vrm.license_warnings(meta)}


def remove(model_id: str):
    path = _custom_path(model_id)             # el de fábrica no pasa por aquí: su id no es un archivo de custom/
    if model_id == DEFAULT_ID or not path.is_file():
        raise ModelError("Solo se pueden quitar los modelos propios")
    path.unlink()
    if _state().get("model") == model_id:
        _save(model=DEFAULT_ID)
