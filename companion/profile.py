"""Perfil del usuario y elecciones de la bienvenida: cómo se llama, año de nacimiento, género, proveedor del
cerebro (nube con su clave, o modelo local), voz. Se guardan con state.py y se aplican sobre `settings`.
"""
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path

from . import state, voice_import
from .config import MAC, ROOT, for_this_pc, settings

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
PC_MODELS = [                             # de mayor a menor
    # 8,0 GB en disco y 10,6 GB cargado; con la voz propia (~1 GB) cabe en 16 GB y va a 58-93 tokens/s (medido el
    # 13 nov 2026). No se recomienda sola (recommend False): con un juego abierto ya no cabe y se desborda a la RAM.
    {"id": "gemma4:12b", "name": "Gemma 4 12B", "size_gb": 8.0, "vram_gb": 10.6, "vision": True, "recommend": False,
     "note": "El más listo, para tarjetas de 16 GB. Ocupa unos 10,6 GB: con un juego abierto puede ir lento. Ve imágenes."},
    {"id": "gemma4:e4b-it-qat", "name": "Gemma 4 E4B", "size_gb": 6.1, "vram_gb": 4.8, "vision": True,
     "note": "El más capaz de los ligeros. Ve imágenes."},
    {"id": "gemma4:e2b-it-qat", "name": "Gemma 4 E2B", "size_gb": 4.3, "vram_gb": 3.3, "vision": True, "control": False,
     "note": "Más pequeño y rápido; se equivoca algo más. Ve imágenes."},
    {"id": "qwen3:1.7b", "name": "Qwen 3 1.7B", "size_gb": 1.4, "vram_gb": 2.4, "vision": False, "actions": False,
     "note": "Muy ligero, para tarjetas de 4 a 6 GB. No ve imágenes (ni cámara ni pantalla)."},
    {"id": "gemma3:1b-it-qat", "name": "Gemma 3 1B", "size_gb": 1.0, "vram_gb": 1.4, "vision": False, "actions": False,
     "note": "El más pequeño: funciona incluso sin tarjeta gráfica. Respuestas sencillas. No ve imágenes."},
]

# Mac con Apple Silicon (15 nov 2026): los Gemma 4 en versión MLX de Ollama (el motor de Apple, RUNNER mlx en
# `ollama ps`). Medido en una MacBook M5 Pro de 24 GB con Ollama 0.40.13 (scripts/medir_modelos_locales.py): el doble
# de rápidos que los de PC en el mismo Mac (12B: 59 frente a 32 tokens/s; E4B: 124 frente a 64) y todos ven
# imágenes. vram_gb es la memoria unificada que ocupan cargados en una conversación del companion (`ollama ps`:
# 12B 9,4 GB, E4B 9,5 GB; el E2B, estimado). Van de más a menos capaz, no por memoria: en MLX el E4B ocupa lo que el 12B.
# Los dos más pequeños no tienen versión MLX: se quedan los de PC.
MAC_MODELS = [
    {"id": "gemma4:12b-mlx", "name": "Gemma 4 12B (MLX)", "size_gb": 7.7, "vram_gb": 9.5, "vision": True,
     "note": "El más listo, optimizado para Apple Silicon (unos 60 tokens/s en un M5 Pro). Ocupa unos 9,5 GB. Ve imágenes."},
    {"id": "gemma4:e4b-mlx", "name": "Gemma 4 E4B (MLX)", "size_gb": 9.5, "vram_gb": 9.6, "vision": True,
     "note": "Optimizado para Apple Silicon y el doble de rápido que el 12B, y ocupa lo mismo (unos 9,5 GB). Ve imágenes."},
    {"id": "gemma4:e2b-mlx", "name": "Gemma 4 E2B (MLX)", "size_gb": 7.5, "vram_gb": 8.0, "vision": True, "control": False,
     "note": "Optimizado para Apple Silicon, el más rápido (unos 170 tokens/s); se equivoca algo más. Ve imágenes."},
    *[m for m in PC_MODELS if m["id"] in ("qwen3:1.7b", "gemma3:1b-it-qat")],
]
LOCAL_MODELS = MAC_MODELS if MAC else PC_MODELS
TOP_RECOMMENDED = next(m["id"] for m in LOCAL_MODELS if m.get("recommend", True))   # el mayor que se llega a recomendar

# Memoria de vídeo (GB) de lo que convive con el modelo local, medida en esta PC (RTX 5070 Ti, nov 2026).
VOICE_ENGINES = {
    # Medido el 18 nov 2026 con voz/servidor.py (F5-TTS en float16): 1,03 GB en reposo y 1,12 GB de pico al hablar;
    # 1,2 con algo de margen. El nodo de waifuv3 que se usaba antes ocupaba de 5 a 9 GB porque cargaba Chatterbox.
    "completa": {"name": "Voz completa", "vram_gb": 1.2,
                 "note": "Voces clonadas, la de más calidad. Necesita tarjeta NVIDIA: usa alrededor de 1,1 GB de memoria de vídeo."},
    "ligera": {"name": "Voz ligera", "vram_gb": 0.0,
               "note": "Voces sintéticas (Piper). Corre en el procesador: no usa memoria de vídeo. Suena más artificial y no es la voz clonada."},
    # Voces neuronales de Edge (tts_cloud): sin clave ni cupo, casi sin procesador; necesita internet.
    "nube": {"name": "Voz en la nube", "vram_gb": 0.0,
             "note": "Voces neuronales de Microsoft, muy naturales. Gratis y sin clave, pero necesita internet: lo que dice sale de tu PC. No es la voz clonada."},
}
if MAC:
    VOICE_ENGINES["completa"] = {**VOICE_ENGINES["completa"], "note": (
        "Voces clonadas, la de más calidad. Usa la GPU del Mac: empieza a hablar unos 3 segundos después que la ligera.")}
EAR_ENGINES = ("local", "nube")
# Oído en la GPU (int8_float16), medido el 18 nov 2026 con frases en español de voz clara: memoria de vídeo y
# palabras perdidas. large-v3-turbo: 1,29 GB, 1,4 %, 0,13 s por frase · small: 0,53 GB, 3-5 %, 0,19 s ·
# base: 0,14 GB, 6-9 %. En el procesador, small tarda 1,8 s por frase (en esta PC; más en una laptop).
EAR_MODELS = {"large-v3-turbo": 1.3, "small": 0.55, "base": 0.15}
EAR_GB = EAR_MODELS["large-v3-turbo"]
SMALL_EAR_BELOW = 6.5                     # tarjetas de menos GB: el oído pequeño (deja sitio a la voz completa)
DESKTOP_GB = 2.0                          # Windows, el navegador y la propia ventana (si no se puede medir)


def ear_model(total: float | None = None) -> str:
    """El Whisper que se carga en la GPU. STT_MODEL en .env manda; si no, en tarjetas de menos de SMALL_EAR_BELOW
    GB el pequeño (si el instalador lo trajo): con el turbo (1,3 GB) y la voz completa (1,1 GB) una tarjeta de
    4 GB no tenía sitio para las dos."""
    if os.getenv("STT_MODEL"):
        return settings.stt_model
    if MAC:
        return "large-v3-turbo"
    total = gpu_total_gb() if total is None else total
    small = (ROOT / "models" / "whisper" / "small" / "model.bin").is_file()
    return "small" if 0 < total < SMALL_EAR_BELOW and small else "large-v3-turbo"


def ear_gb() -> float:
    """GB del oído que se usa ahora (o del que se cargaría)."""
    from . import stt
    name = stt.loaded_name or ear_model()
    return EAR_MODELS.get(name, EAR_GB)


def voice_engine() -> str:
    """El motor que eligió el usuario (el que se usa de verdad lo decide engine_now)."""
    e = state.load().get("voice_engine")
    return e if e in VOICE_ENGINES else (_ENV_ENGINE if _ENV_ENGINE in VOICE_ENGINES else "completa")


def ear_engine() -> str:
    """Dónde se transcribe lo que dices: local (Whisper en esta PC) o nube (stt_cloud)."""
    e = (state.load().get("ear") or {}).get("engine")
    return e if e in EAR_ENGINES else "local"


def cloud_only() -> bool:
    """Modo «solo nube»: cerebro, oído y voz en la nube; nada de modelos en esta PC (ni el respaldo local)."""
    return bool(state.load().get("cloud_only"))


def voice_auto() -> bool:
    """¿Pasar sola a la voz ligera cuando la completa no cabe en la tarjeta? (encendido por defecto)"""
    return state.load().get("voice_auto") is not False


_squeezed = False                         # el modelo local se quedó sin memoria de vídeo (lo marca llm._too_slow)
_gpu_total: float | None = None           # GB de la tarjeta (no cambia: se mide una vez)


def squeeze(on: bool = True):
    global _squeezed
    _squeezed = on


def gpu_total_gb() -> float:
    global _gpu_total
    if _gpu_total is None:
        from . import llm
        g = llm.gpu_memory()
        _gpu_total = round(g["total"] / 1024, 1) if g else 0.0
    return _gpu_total


_others: float | None = None              # lo último medido de los demás programas en la tarjeta (GB)


def _ollama_on_gpu() -> float:
    """GB que ocupa ahora en la tarjeta el modelo local (Ollama /api/ps)."""
    try:
        import httpx
        r = httpx.get(f"{settings.ollama_url}/api/ps", timeout=1.0)
        return sum(m.get("size_vram", 0) for m in r.json().get("models", [])) / 2**30
    except Exception:  # noqa: BLE001
        return 0.0


def measured_others() -> float | None:
    """GB que ocupan en la tarjeta los DEMÁS programas (escritorio, navegador, un juego), medidos: lo usado
    (nvidia-smi) menos lo nuestro (oído en la GPU y modelo local cargado). DESKTOP_GB era una estimación hecha en
    la PC de 16 GB: en una laptop de 4 GB, con el escritorio en la gráfica integrada, son unos cientos de MB, y con
    ella la voz completa nunca parecía caber (15 nov 2026). Con la voz completa en marcha no se mide (se queda con
    más memoria de la que dice VOICE_ENGINES y parecería de otros): vale la última medida. None si no se puede."""
    global _others
    from . import llm, stt, voz_proc
    running = voz_proc.running()
    if running and _others is not None:
        return _others
    g = llm.gpu_memory()
    if not g:
        return None
    ours = (ear_gb() if stt.on_gpu else 0.0) + _ollama_on_gpu() + (VOICE_ENGINES["completa"]["vram_gb"] if running else 0.0)
    _others = round(max(0.3, g["used"] / 1024 - ours), 1)
    return _others


def _need_full(others: float | None, model: float) -> float:
    """GB que hacen falta para la voz completa junto al oído, los demás programas y el modelo local. Con lo
    medido se deja 0,2 GB de holgura; con la estimación fija se toleraba 0,3 GB de más."""
    base = ear_gb() + VOICE_ENGINES["completa"]["vram_gb"] + model
    return base + (DESKTOP_GB - 0.3 if others is None else others + 0.2)


def full_voice_fits(is_cloud: bool, local_model: str, total: float | None = None, others: float | None = None) -> bool:
    """¿Caben la voz completa, el oído, los demás programas y (si el cerebro es local) el modelo en la tarjeta?
    Sin `total` se mira la tarjeta de verdad, con lo que los demás programas ocupan ahora."""
    if total is None:
        total = gpu_total_gb()
        others = measured_others() if others is None else others
    need = 0.0 if is_cloud else model_vram(local_model)
    return total >= _need_full(others, need)


def engine_now() -> tuple[str, str]:
    """(motor que se usa ahora, motivo si no es el elegido). Con la voz completa elegida y el cambio automático
    encendido, se pasa a la ligera cuando no cabe: con el cerebro en la nube casi siempre cabe (se descarga el
    modelo local); con el local, depende del tamaño del modelo y de la tarjeta. Si luego el modelo local se queda
    sin memoria (un juego abierto), llm._too_slow marca _squeezed y también se pasa a la ligera."""
    from . import tts_light, voz_proc
    pref = voice_engine()
    if pref == "nube":
        from . import tts_cloud
        return ("nube", "") if tts_cloud.installed() else ("ligera", "falta la librería de la voz en la nube")
    if pref != "completa" or not voice_auto() or not tts_light.installed():
        return pref, ""
    if not voz_proc.installed():
        return "ligera", "la voz completa no está instalada en esta PC"
    if not settings.is_cloud and _squeezed:
        return "ligera", "el modelo local se quedó sin memoria de vídeo"
    if not full_voice_fits(settings.is_cloud, settings.ollama_model):
        if settings.is_cloud:
            return "ligera", "la tarjeta gráfica no tiene memoria de vídeo suficiente para la voz completa"
        return "ligera", f"con el modelo local ({settings.ollama_model}) no cabe también la voz completa en la tarjeta"
    return "completa", ""


def model_vram(model_id: str, installed: dict | None = None) -> float:
    """GB de vídeo que pide un modelo local: medido si es del catálogo; si no, estimado por su tamaño en disco."""
    known = next((m["vram_gb"] for m in LOCAL_MODELS if m["id"] == model_id), None)
    # gemma4:12b ocupa 8,0 GB en disco y 10,6 GB cargado (medido): tamaño × 1,2 + 1
    return known if known else round((installed or {}).get(model_id, 6.0) * 1.2 + 1.0, 1)


def resources(gpu: dict | None, *, is_cloud: bool, local_model: str, node_ok: bool, installed: dict | None = None,
              others: float | None = None) -> dict:
    """Qué cabe en esta PC. La voz, el oído y el modelo local comparten la memoria de vídeo: de la tarjeta se
    descuenta lo que usan los demás programas (`others`, medido; si no, DESKTOP_GB), el oído y la voz elegida, y
    lo que queda es para el modelo local."""
    total = round((gpu or {}).get("total", 0) / 1024, 1)
    desktop = DESKTOP_GB if others is None else others
    ear = EAR_MODELS.get(ear_model(total), EAR_GB)
    base = ear + desktop
    room = {k: round(max(0.0, total - base - v["vram_gb"]), 1) for k, v in VOICE_ENGINES.items()}
    tier = "alto" if total >= 8 else "medio" if total >= 6 else "bajo"     # desde 8 GB cabe la voz completa con un modelo local
    # Voz recomendada: la completa solo si, además de ella, cabe el cerebro que se va a usar.
    need = 0.0 if is_cloud else model_vram(local_model, installed)
    full_fits = total >= _need_full(others, need)
    # En el Mac también: con float16 y la muestra corta (voz/servidor.py) va a tiempo real, primer audio ~3 s en una
    # M5 Pro (16 nov 2026; antes, 33 s de media).
    engine = "completa" if node_ok and full_fits else "ligera"

    def best(key: str) -> str:
        # con 0,3 GB de holgura: un modelo que cabe justo se desborda en cuanto se abre otra cosa
        return next((m["id"] for m in LOCAL_MODELS if m.get("recommend", True) and m["vram_gb"] + 0.3 <= room[key]),
                    LOCAL_MODELS[-1]["id"])
    # Pareja recomendada si el cerebro es local: la voz completa solo si a su lado cabe un modelo que vea
    # imágenes; si no, mejor la ligera con un modelo más capaz.
    sees = {m["id"]: m["vision"] for m in LOCAL_MODELS}
    pair = "completa" if node_ok and total and sees[best("completa")] else "ligera"
    return {"total_gb": total, "tier": tier, "ear_gb": ear, "ear_model": ear_model(total), "desktop_gb": desktop, "room": room,
            "engines": {k: {**v, "id": k} for k, v in VOICE_ENGINES.items()},
            "recommended_engine": engine, "recommended_model": best(pair), "recommended_pair": pair,
            "best": {k: best(k) for k in VOICE_ENGINES}}

_ENV_KEY = settings.gemini_api_key          # la clave que venía en .env, si la había
_ENV_NAME = settings.user_name
_ENV_VOICE = settings.tts_voice
_ENV_ENGINE = settings.voice_engine
_ENV_LOCAL_FALLBACK = settings.local_fallback
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
        if for_this_pc(s["local_model"]) != s["local_model"]:     # elegido antes de que el Mac usara los MLX
            s = state.save(local_model=for_this_pc(s["local_model"]))
        settings.ollama_model = s["local_model"]
        # respaldo si va lento: los del catálogo más pequeños que el elegido (uno propio: los que piden menos vídeo)
        settings.ollama_fallback = (ids[ids.index(s["local_model"]) + 1:] if s["local_model"] in ids else
                                    [m["id"] for m in LOCAL_MODELS if m["vram_gb"] < model_vram(s["local_model"])])
    # «Solo nube» se apaga solo si después se elige algo local (el cerebro, el oído o la voz) desde otro ajuste.
    if s.get("cloud_only") and (s.get("provider", "gemini") != "gemini" or ear_engine() != "nube"
                                or voice_engine() != "nube"):
        s = state.save(cloud_only=False)
    # En «solo nube» no se carga el modelo local ni como respaldo cuando se acaba la cuota (ocuparía RAM o vídeo).
    settings.local_fallback = _ENV_LOCAL_FALLBACK and not cloud_only()
    settings.voice_engine, settings.voice_reason = engine_now()
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
    if voice_import.is_custom(tts_voice):        # las propias: voz/servidor.py ya las lee de data/voces
        if folder.resolve() != LOCAL_VOICES.resolve():
            try:
                voice_import.copy_to(tts_voice, folder)
            except OSError:
                pass
        return
    for ext in (".wav", ".json"):
        src, dst = LOCAL_VOICES / f"{tts_voice}{ext}", folder / f"{tts_voice}{ext}"
        try:
            if src.is_file() and (not dst.is_file() or dst.read_bytes() != src.read_bytes()):
                shutil.copy2(src, dst)
        except OSError:
            pass


def voices() -> list[dict]:
    """Catálogo de voices.json más las voces propias (voice_import), con si cada una tiene su muestra."""
    try:
        catalog = json.loads((ROOT / "voices.json").read_text(encoding="utf-8"))["voices"]
    except (OSError, ValueError, KeyError):
        catalog = [{"id": "mika", "name": "Mika", "tts_voice": _ENV_VOICE, "default": True}]
    catalog = [*catalog, *voice_import.custom()]      # las propias del usuario (data/voces), al final
    folder = _voices_dir()
    present = {p.stem for p in folder.iterdir() if p.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg")} if folder.is_dir() else None
    chosen = state.load().get("voice")
    out = []
    for v in catalog:
        if not re.fullmatch(r"[\w-]{1,40}", str(v.get("id", ""))) or not re.fullmatch(r"[\w-]{1,60}", str(v.get("tts_voice", ""))):
            continue
        out.append({"id": v["id"], "name": str(v.get("name") or v["id"])[:40], "speaks": "m" if v.get("speaks") == "m" else "f",
                    "tts_voice": v["tts_voice"], "default": bool(v.get("default")), "note": str(v.get("note") or "")[:60],
                    "custom": bool(v.get("custom")),
                    "available": bool(v.get("custom")) or present is None or v["tts_voice"] in present
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
