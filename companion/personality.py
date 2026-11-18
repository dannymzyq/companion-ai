"""Personalidades del personaje (16 nov 2026): un catálogo incluido (personas/personalidades.json) y las propias del
usuario (Ajustes › Personalidad), que se crean desde cero o a partir de una incluida. La elegida cambia la forma de
ser y de hablar (rasgos, estilo, muletillas, gustos, ejemplos de frases, emociones habituales); el nombre, la edad,
la voz, los límites y las reglas siguen siendo los de la ficha común (personas/mika.json) y el prompt de sistema.

Se guarda en data/settings.json: {"personality": {"active": id, "custom": [ ... ]}}."""
import json
import re
import secrets
from functools import lru_cache

from . import state
from .config import ROOT
from .prompt import EMOTIONS

CATALOG_FILE = ROOT / "personas" / "personalidades.json"
DEFAULT = "confianza"
MAX_CUSTOM = 30

# Rasgos (0..1). `label`, `low`, `high`: lo que enseña la interfaz en cada control (sin palabras con género:
# decisión del usuario del 12 nov 2026).
TRAITS = {
    "warmth":         {"label": "Calidez", "low": "Poca", "high": "Mucha", "default": 0.7},
    "playfulness":    {"label": "Humor", "low": "Nada", "high": "Mucho", "default": 0.5},
    "sarcasm":        {"label": "Ironía", "low": "Nada", "high": "Mucha", "default": 0.2},
    "shyness":        {"label": "Timidez", "low": "Nada", "high": "Mucha", "default": 0.2},
    "curiosity":      {"label": "Curiosidad", "low": "Poca", "high": "Pregunta por todo", "default": 0.6},
    "energy":         {"label": "Energía", "low": "Calma", "high": "A tope", "default": 0.5},
    "expressiveness": {"label": "Expresividad", "low": "Lo guarda", "high": "Lo muestra todo", "default": 0.6},
    "assertiveness":  {"label": "Opiniones propias", "low": "Te da la razón", "high": "Discute y opina", "default": 0.5},
    "talkativeness":  {"label": "Cuánto habla", "low": "Lo justo", "high": "Se explaya", "default": 0.4},
}
FORMALITY = {"casual": "Casual", "neutral": "Neutro", "formal": "Formal"}
_LIMITS = {"name": 40, "summary": 120, "description": 700, "speech": 400, "item": 60, "example": 200, "opinion": 160}
_JUNK = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\[\]{}<>]+")


@lru_cache(maxsize=1)
def catalog() -> tuple[dict, ...]:
    data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    return tuple({**clean(p, partial=True), "id": p["id"], "builtin": True} for p in data)


def _text(value, limit: int, lines: bool = False) -> str:
    s = str(value or "")
    s = _JUNK.sub(" ", s.replace("\n", " ") if not lines else s.replace("\r", ""))
    return re.sub(r"[ \t]+", " ", s).strip()[:limit]


def _items(value, n: int, limit: int) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[,;\n]", value)
    out = []
    for v in value or []:
        t = _text(v, limit)
        if t and t.lower() not in (x.lower() for x in out):
            out.append(t)
    return out[:n]


def clean(raw: dict, partial: bool = False) -> dict:
    """Lo que llega de la interfaz (o del catálogo), con límites de tamaño y sin caracteres que confundan al
    prompt o a las etiquetas. Lanza ValueError si falta el nombre."""
    name = _text(raw.get("name"), _LIMITS["name"])
    if not name and not partial:
        raise ValueError("Ponle un nombre a la personalidad.")
    traits_in = raw.get("traits") if isinstance(raw.get("traits"), dict) else {}
    traits = {}
    for key, meta in TRAITS.items():
        try:
            traits[key] = round(min(max(float(traits_in.get(key, meta["default"])), 0.0), 1.0), 2)
        except (TypeError, ValueError):
            traits[key] = meta["default"]
    mood = raw.get("base_mood") if raw.get("base_mood") in EMOTIONS else "neutral"
    return {
        "name": name, "summary": _text(raw.get("summary"), _LIMITS["summary"]),
        "description": _text(raw.get("description"), _LIMITS["description"], lines=True),
        "traits": traits,
        "formality": raw.get("formality") if raw.get("formality") in FORMALITY else "casual",
        "speech": _text(raw.get("speech"), _LIMITS["speech"], lines=True),
        "catchphrases": _items(raw.get("catchphrases"), 4, 40),
        "likes": _items(raw.get("likes"), 8, _LIMITS["item"]),
        "dislikes": _items(raw.get("dislikes"), 6, _LIMITS["item"]),
        "base_mood": mood,
        "emotions": [e for e in _items(raw.get("emotions"), 4, 20) if e in EMOTIONS][:3],
        "examples": _items(raw.get("examples") if not isinstance(raw.get("examples"), str)
                           else raw["examples"].split("\n"), 5, _LIMITS["example"]),
        # Opiniones fuertes y reacciones a cosas concretas (17 nov 2026): una por línea.
        "opinions": _items(raw.get("opinions") if not isinstance(raw.get("opinions"), str)
                           else raw["opinions"].split("\n"), 5, _LIMITS["opinion"]),
        "reactions": _items(raw.get("reactions") if not isinstance(raw.get("reactions"), str)
                            else raw["reactions"].split("\n"), 4, _LIMITS["opinion"]),
    }


# ---------------------------------------------------------------- lo guardado
def _saved() -> dict:
    p = state.load().get("personality")
    return p if isinstance(p, dict) else {}


def custom() -> list[dict]:
    out = []
    for c in _saved().get("custom") or []:
        if isinstance(c, dict) and str(c.get("id", "")).startswith("c_"):
            out.append({**clean(c, partial=True), "id": c["id"], "builtin": False, "from": c.get("from") or ""})
    return out


def all_personalities() -> list[dict]:
    return [*catalog(), *custom()]


def find(pid: str) -> dict | None:
    return next((p for p in all_personalities() if p["id"] == pid), None)


def active_id() -> str:
    pid = _saved().get("active") or DEFAULT
    return pid if find(pid) else DEFAULT


def active() -> dict:
    return find(active_id()) or catalog()[0]


def select(pid: str):
    if not find(pid):
        raise ValueError("Esa personalidad no existe.")
    state.save(personality={**_saved(), "active": pid})


def save_custom(raw: dict) -> dict:
    """Crea (sin `id`) o cambia (con el `id` de una propia) una personalidad propia y la deja elegida.
    Personalizar una incluida crea una copia propia (`from`): la incluida no cambia."""
    data = clean(raw)
    saved = _saved()
    items = [c for c in saved.get("custom") or [] if isinstance(c, dict)]
    pid = str(raw.get("id") or "")
    if pid.startswith("c_") and any(c.get("id") == pid for c in items):
        items = [{**data, "id": pid, "from": c.get("from") or ""} if c.get("id") == pid else c for c in items]
    else:
        if len(items) >= MAX_CUSTOM:
            raise ValueError(f"Ya tienes {MAX_CUSTOM} personalidades propias: borra alguna antes.")
        base = str(raw.get("from") or (pid if find(pid) else ""))
        pid = "c_" + secrets.token_hex(4)
        items.append({**data, "id": pid, "from": base if find(base) else ""})
    state.save(personality={**saved, "custom": items, "active": pid})
    return find(pid)


def delete_custom(pid: str):
    saved = _saved()
    items = [c for c in saved.get("custom") or [] if isinstance(c, dict) and c.get("id") != pid]
    active_now = saved.get("active")
    if active_now == pid:                    # si era la elegida, vuelve a aquella de la que salió (o a la de siempre)
        gone = next((c for c in saved.get("custom") or [] if isinstance(c, dict) and c.get("id") == pid), {})
        active_now = gone.get("from") if any(p["id"] == gone.get("from") for p in catalog()) else DEFAULT
    state.save(personality={**saved, "custom": items, "active": active_now})


def temper(p: dict) -> dict:
    """Lo que usa el cuerpo para reaccionar a toques y miradas (web/js/avatar.js setTemper)."""
    t = p["traits"]
    return {"shy": t["shyness"], "warm": t["warmth"], "sharp": round(max(t["sarcasm"], t["assertiveness"] * 0.8), 2)}


def public() -> dict:
    return {"active": active_id(), "personalities": all_personalities(), "default": DEFAULT,
            "traits": TRAITS, "formality": FORMALITY, "emotions": EMOTIONS, "max_custom": MAX_CUSTOM}


# ---------------------------------------------------------------- la ficha con la personalidad
def apply(persona: dict, p: dict | None = None) -> dict:
    """La ficha común con la forma de ser de la personalidad elegida. Lo que no toca: nombre, edad, voz, rol,
    límites y +18 (que dependen de la ficha y de las reglas, nunca de la personalidad)."""
    p = p or active()
    speech = {**persona.get("speech_style", {}), "formality": p["formality"],
              "notes": p["speech"] or persona.get("speech_style", {}).get("notes", ""),
              "catchphrases": p["catchphrases"]}
    return {**persona, "traits": {**persona.get("traits", {}), **p["traits"]}, "speech_style": speech,
            "backstory": p["description"] or persona.get("backstory", ""), "interests": p["likes"] or persona.get("interests", []),
            "personality": p}
