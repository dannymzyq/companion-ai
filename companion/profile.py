"""Perfil del usuario y elecciones de la bienvenida: cómo se llama, año de nacimiento, género, proveedor del
cerebro (nube con su clave, o modelo local), voz. Se guardan con state.py y se aplican sobre `settings`.
"""
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path

from . import state
from .config import ROOT, settings

GENDERS = {"mujer": "en femenino", "hombre": "en masculino",
           "no_binario": "con lenguaje neutro, sin masculino ni femenino",
           "": "sin asumir su género: usa formas neutras"}          # "" = prefiere no decirlo

# Proveedores con API compatible con la de OpenAI. Los modelos de cada uno se leen de su propia API al
# comprobar la clave (no se adivinan aquí); solo Gemini trae un relevo ya probado.
PRESETS = {
    "gemini": {"name": "Google Gemini", "base": "https://generativelanguage.googleapis.com/v1beta/openai",
               "keys": "https://aistudio.google.com/apikey", "note": "Tiene capa gratuita. Probado con este companion."},
    "openai": {"name": "OpenAI", "base": "https://api.openai.com/v1", "keys": "https://platform.openai.com/api-keys",
               "note": "De pago. Sin probar aquí."},
    "openrouter": {"name": "OpenRouter", "base": "https://openrouter.ai/api/v1", "keys": "https://openrouter.ai/keys",
                   "note": "Muchos modelos con una sola clave. Sin probar aquí."},
    "groq": {"name": "Groq", "base": "https://api.groq.com/openai/v1", "keys": "https://console.groq.com/keys",
             "note": "Muy rápido. Sin probar aquí."},
    "mistral": {"name": "Mistral", "base": "https://api.mistral.ai/v1", "keys": "https://console.mistral.ai/api-keys",
                "note": "Sin probar aquí."},
    "custom": {"name": "Otro (compatible con OpenAI)", "base": "", "keys": "", "note": "Escribe la dirección de su API."},
}

# Modelos locales ligeros que se ofrecen. vram = memoria de vídeo que ocupan (medida); min_gpu = tarjeta mínima
# para usarlos junto a la voz y el oído, que también viven en la GPU.
LOCAL_MODELS = [                          # de mayor a menor
    {"id": "gemma4:e4b-it-qat", "name": "Gemma 4 E4B", "size_gb": 6.1, "vram_gb": 4.8, "vision": True,
     "note": "El más capaz de los ligeros. Ve imágenes."},
    {"id": "gemma4:e2b-it-qat", "name": "Gemma 4 E2B", "size_gb": 4.3, "vram_gb": 3.3, "vision": True, "control": False,
     "note": "Más pequeño y rápido; se equivoca algo más. Ve imágenes."},
    {"id": "qwen3:1.7b", "name": "Qwen 3 1.7B", "size_gb": 1.4, "vram_gb": 2.4, "vision": False, "actions": False,
     "note": "Muy ligero, para tarjetas de 4 a 6 GB. No ve imágenes (ni cámara ni pantalla)."},
    {"id": "gemma3:1b-it-qat", "name": "Gemma 3 1B", "size_gb": 1.0, "vram_gb": 1.4, "vision": False, "actions": False,
     "note": "El más pequeño: funciona incluso sin tarjeta gráfica. Respuestas sencillas. No ve imágenes."},
]

# Memoria de vídeo (GB) de lo que convive con el modelo local, medida en esta PC (RTX 5070 Ti, nov 2026).
VOICE_ENGINES = {
    # 1,0 GB en reposo medido con voz/servidor.py (solo F5-TTS); 1,5 con margen para la síntesis. El nodo de
    # waifuv3 que se usaba antes ocupaba de 5 a 9 GB porque cargaba también Chatterbox.
    "completa": {"name": "Voz completa", "vram_gb": 1.5,
                 "note": "Voces clonadas, la de más calidad. Necesita tarjeta NVIDIA: usa alrededor de 1,5 GB de memoria de vídeo."},
    "ligera": {"name": "Voz ligera", "vram_gb": 0.0,
               "note": "Voces sintéticas (Piper). Corre en el procesador: no usa memoria de vídeo. Suena más artificial y no es la voz clonada."},
}
EAR_GB = 1.1                              # Whisper large-v3-turbo
DESKTOP_GB = 2.0                          # Windows, el navegador y la propia ventana


def voice_engine() -> str:
    e = state.load().get("voice_engine")
    return e if e in VOICE_ENGINES else (_ENV_ENGINE if _ENV_ENGINE in VOICE_ENGINES else "completa")


def model_vram(model_id: str, installed: dict | None = None) -> float:
    """GB de vídeo que pide un modelo local: medido si es del catálogo; si no, estimado por su tamaño en disco."""
    known = next((m["vram_gb"] for m in LOCAL_MODELS if m["id"] == model_id), None)
    # gemma4:12b ocupa 8,0 GB en disco y 10,6 GB cargado (medido): tamaño × 1,2 + 1
    return known if known else round((installed or {}).get(model_id, 6.0) * 1.2 + 1.0, 1)


def resources(gpu: dict | None, *, is_cloud: bool, local_model: str, node_ok: bool, installed: dict | None = None) -> dict:
    """Qué cabe en esta PC. La voz, el oído y el modelo local comparten la memoria de vídeo: de la tarjeta se
    descuenta el escritorio, el oído y la voz elegida, y lo que queda es para el modelo local."""
    total = round((gpu or {}).get("total", 0) / 1024, 1)
    base = EAR_GB + DESKTOP_GB
    room = {k: round(max(0.0, total - base - v["vram_gb"]), 1) for k, v in VOICE_ENGINES.items()}
    tier = "alto" if total >= 8 else "medio" if total >= 6 else "bajo"     # desde 8 GB cabe la voz completa con un modelo local
    # Voz recomendada: la completa solo si, además de ella, cabe el cerebro que se va a usar.
    need = 0.0 if is_cloud else model_vram(local_model, installed)
    full_fits = total >= base + VOICE_ENGINES["completa"]["vram_gb"] + need - 0.3
    engine = "completa" if node_ok and full_fits else "ligera"

    def best(key: str) -> str:
        # con 0,3 GB de holgura: un modelo que cabe justo se desborda en cuanto se abre otra cosa
        return next((m["id"] for m in LOCAL_MODELS if m["vram_gb"] + 0.3 <= room[key]), LOCAL_MODELS[-1]["id"])
    # Pareja recomendada si el cerebro es local: la voz completa solo si a su lado cabe un modelo que vea
    # imágenes; si no, mejor la ligera con un modelo más capaz.
    sees = {m["id"]: m["vision"] for m in LOCAL_MODELS}
    pair = "completa" if node_ok and total and sees[best("completa")] else "ligera"
    return {"total_gb": total, "tier": tier, "ear_gb": EAR_GB, "desktop_gb": DESKTOP_GB, "room": room,
            "engines": {k: {**v, "id": k} for k, v in VOICE_ENGINES.items()},
            "recommended_engine": engine, "recommended_model": best(pair), "recommended_pair": pair,
            "best": {k: best(k) for k in VOICE_ENGINES}}

_ENV_KEY = settings.gemini_api_key          # la clave que venía en .env, si la había
_ENV_NAME = settings.user_name
_ENV_VOICE = settings.tts_voice
_ENV_ENGINE = settings.voice_engine
_ENV_PROVIDER, _ENV_LOCAL, _ENV_FALLBACK = settings.llm_provider, settings.ollama_model, list(settings.ollama_fallback)


def get() -> dict:
    p = state.load().get("profile") or {}
    return {"name": str(p.get("name") or ""), "birth_year": p.get("birth_year"), "gender": str(p.get("gender") or "")}


def age() -> int | None:
    """Años cumplidos como mínimo (solo se sabe el año de nacimiento, así que se cuenta por lo bajo)."""
    year = get()["birth_year"]
    return date.today().year - year - 1 if isinstance(year, int) else None


def is_adult() -> bool:
    a = age()
    return a is not None and a >= 18


def clean_profile(raw: dict) -> dict:
    name = re.sub(r"[\r\n\t\[\]{}<>]+", " ", str(raw.get("name") or "")).strip()[:40]
    if not name:
        raise ValueError("Dime cómo quieres que te llame.")
    try:
        year = int(raw.get("birth_year"))
    except (TypeError, ValueError):
        raise ValueError("Escribe tu año de nacimiento con cuatro cifras.") from None
    if not 1900 <= year <= date.today().year:
        raise ValueError("Ese año de nacimiento no es válido.")
    gender = str(raw.get("gender") or "")
    if gender not in GENDERS:
        raise ValueError("Género no reconocido.")
    return {"name": name, "birth_year": year, "gender": gender}


def describe(user_name: str) -> str:
    """Línea del prompt sobre la persona con la que habla."""
    p, a = get(), age()
    years = f"Tiene {a} años (o está por cumplir {a + 1}). " if a is not None else ""
    return f"{years}Háblale {GENDERS.get(p['gender'], GENDERS[''])}."


# ---------------------------------------------------------------- cerebro
def cloud() -> dict:
    c = state.load().get("cloud") or {}
    preset = c.get("preset") if c.get("preset") in PRESETS else "gemini"
    return {"preset": preset, "base": (c.get("base") or PRESETS[preset]["base"]).rstrip("/"),
            "model": c.get("model") or "", "key": c.get("key") or (_ENV_KEY if preset == "gemini" else "")}


def public_cloud() -> dict:
    c = cloud()
    return {"preset": c["preset"], "name": PRESETS[c["preset"]]["name"], "base": c["base"], "model": c["model"],
            "has_key": bool(c["key"]), "key_hint": f"…{c['key'][-4:]}" if len(c["key"]) >= 8 else ""}


def apply():
    """Pasa lo guardado a `settings` (al arrancar y cada vez que se cambia algo)."""
    s = state.load()
    settings.user_name = get()["name"] or _ENV_NAME
    c = cloud()
    settings.cloud_preset, settings.cloud_base, settings.gemini_api_key = c["preset"], c["base"], c["key"]
    settings.cloud_model = c["model"]
    if c["preset"] == "gemini" and c["model"]:
        settings.gemini_model = c["model"]
    settings.llm_provider = s["provider"] if s.get("provider") in ("gemini", "local") else _ENV_PROVIDER
    settings.ollama_model, settings.ollama_fallback = _ENV_LOCAL, list(_ENV_FALLBACK)
    if s.get("local_model"):
        ids = [m["id"] for m in LOCAL_MODELS]
        settings.ollama_model = s["local_model"]
        # respaldo si va lento: los del catálogo más pequeños que el elegido (uno propio: todos los del catálogo)
        settings.ollama_fallback = ids[ids.index(s["local_model"]) + 1:] if s["local_model"] in ids else ids
    settings.voice_engine = voice_engine()
    v = voice()
    settings.tts_voice = v["tts_voice"] if v else _ENV_VOICE
    if v and settings.voice_engine == "completa":
        install_voice(v["tts_voice"])


# ---------------------------------------------------------------- voces
def _voices_dir() -> Path:
    return Path(os.getenv("VOICES_DIR") or ROOT / "voices")       # el servidor de voz propio las lee de aquí mismo


LOCAL_VOICES = ROOT / "voices"            # las muestras del companion; al nodo solo se copia la que se usa
PREVIEWS = LOCAL_VOICES / "previews"      # la muestra ▶ de cada voz, pregrabada (scripts/grabar_muestras.py)
# Sin comas: el nodo sintetiza por cláusulas y las muy cortas («Hola,») salen comidas o mal dichas.
PREVIEW_TEXT = "Hola soy {name} y así sueno cuando hablo contigo."


def install_voice(tts_voice: str):
    """Copia la muestra de la voz elegida a la carpeta del nodo de voz, si no está o cambió. Solo esa: el nodo
    guarda en la memoria de vídeo algo por cada voz que llega a usar y no lo suelta hasta reiniciarse, así que
    las demás se quedan aquí y sus muestras ▶ están pregrabadas."""
    folder = _voices_dir()
    if os.getenv("VOICE_INSTALL") == "0" or not folder.is_dir():
        return
    for ext in (".wav", ".json"):
        src, dst = LOCAL_VOICES / f"{tts_voice}{ext}", folder / f"{tts_voice}{ext}"
        try:
            if src.is_file() and (not dst.is_file() or dst.read_bytes() != src.read_bytes()):
                shutil.copy2(src, dst)
        except OSError:
            pass


def voices() -> list[dict]:
    """Catálogo de voices.json con si cada voz ya tiene su muestra en el nodo de voz."""
    try:
        catalog = json.loads((ROOT / "voices.json").read_text(encoding="utf-8"))["voices"]
    except (OSError, ValueError, KeyError):
        catalog = [{"id": "mika", "name": "Mika", "tts_voice": _ENV_VOICE, "default": True}]
    folder = _voices_dir()
    present = {p.stem for p in folder.iterdir() if p.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg")} if folder.is_dir() else None
    chosen = state.load().get("voice")
    out = []
    for v in catalog:
        if not re.fullmatch(r"[\w-]{1,40}", str(v.get("id", ""))) or not re.fullmatch(r"[\w-]{1,60}", str(v.get("tts_voice", ""))):
            continue
        out.append({"id": v["id"], "name": str(v.get("name") or v["id"])[:40], "speaks": "m" if v.get("speaks") == "m" else "f",
                    "tts_voice": v["tts_voice"], "default": bool(v.get("default")), "note": str(v.get("note") or "")[:60],
                    "available": present is None or v["tts_voice"] in present
                                 or (LOCAL_VOICES / f"{v['tts_voice']}.wav").is_file()})
    if not any(v["id"] == chosen and v["available"] for v in out):
        chosen = next((v["id"] for v in out if v["default"] and v["available"]), None)
    for v in out:
        v["selected"] = v["id"] == chosen
    return out


def voice() -> dict | None:
    return next((v for v in voices() if v["selected"]), None)


def character(persona: dict) -> dict:
    """La ficha del personaje con el nombre de la voz elegida (Mika, Kenji…) y cómo habla de sí."""
    v = voice()
    return {**persona, "name": v["name"], "speaks": v["speaks"]} if v else persona
