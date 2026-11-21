"""Companion – servidor local (FastAPI). Sirve la interfaz 3D y la conversación en vivo.

Arranque:  .venv\\Scripts\\python.exe -m companion      (o iniciar.ps1)
"""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import actions, config, llm, models, mood, personality, profile, state, store, tts, voice_import, voz_proc
from .config import settings
from .prompt import adult_active, load_persona
from .session import Session
from . import lifecycle
from .stt import Transcriber

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("companion")
STARTED = int(time.time())


class _QuietPolls(logging.Filter):
    """La mascota de escritorio pregunta por la ventana activa cada 0,6 s: eso no va al registro."""
    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/desktop/scene" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_QuietPolls())

persona = load_persona(settings.persona_path)
try:
    state.protect_keys()                  # claves guardadas en claro por una versión anterior → cifradas
except Exception:  # noqa: BLE001
    log.exception("No se pudieron cifrar las claves guardadas")
profile.apply()                         # lo elegido en la bienvenida manda sobre .env


def character_name() -> str:
    """El personaje se llama como la voz elegida (Mika, Kenji…); `persona` es la ficha común a todas."""
    return profile.character(persona)["name"]


def _hint() -> str:
    return f"Conversación entre {settings.user_name} y {character_name()}, su asistente personal."


# El modelo del oído según la tarjeta (profile.ear_model: el pequeño en las de menos de 6,5 GB, si está instalado).
transcriber = Transcriber(profile.ear_model(), settings.stt_device, settings.stt_compute, settings.stt_language, hint=_hint())
transcriber.engine = profile.ear_engine()  # con el oído en la nube no se carga Whisper al arrancar


_tasks: set = set()


def _background(coro):
    """Tarea que no frena la respuesta (cargar o descargar el modelo local)."""
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _quiet_resets(loop, context):
    """Windows registra como error cada ventana que se cierra de golpe (WinError 10054): no es un fallo."""
    if not isinstance(context.get("exception"), ConnectionResetError):
        loop.default_exception_handler(context)


def _load_ear():
    transcriber.load()
    if config.MAC and transcriber.model is not None:
        # En el Mac la voz completa usa la muestra corta (voz_proc): las voces propias de antes no la tenían
        try:
            with transcriber._lock:
                n = voice_import.backfill_short(transcriber.model)
            if n:
                log.info("Muestra corta añadida a %d voces propias", n)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo preparar la muestra corta de las voces propias")


@asynccontextmanager
async def lifespan(_: FastAPI):
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_quiet_resets)
    loop.run_in_executor(None, _load_ear)          # el modelo carga sin frenar el arranque
    log.info("Companion en http://%s:%s · cerebro: %s", settings.host, settings.port, llm.status())
    # Local: se carga ya. Nube: se saca de la tarjeta el modelo local que hubiera dejado una sesión anterior
    # cerrada de golpe (con 6 GB no deja sitio a la voz completa).
    _background(llm.warm_local() if not settings.is_cloud else llm.unload_local())
    await asyncio.to_thread(voz_proc.sync)   # la voz completa corre en su propio proceso (voz/servidor.py)
    yield
    voz_proc.stop()
    await llm.unload_local()             # al cerrar con normalidad se libera la memoria de vídeo del modelo local


app = FastAPI(title="Companion", version="0.1.0", lifespan=lifespan)
# Solo se atiende a quien llama al servidor por su nombre de esta PC. Sin esto, una página web con un truco de DNS
# («DNS rebinding»: su dominio pasa a apuntar a 127.0.0.1) podría leer /api/memory como si fuera la interfaz.
LOCAL_HOSTS = ["127.0.0.1", "localhost", *([settings.host] if settings.host not in ("127.0.0.1", "localhost", "0.0.0.0") else [])]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)


@app.middleware("http")
async def no_stale_interface(request: Request, call_next):
    """La interfaz se revalida en cada carga. Sin esto, la ventana puede seguir usando durante horas el
    JavaScript de una versión anterior (el navegador lo guarda en caché) mezclado con el servidor nuevo."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------------------------------------------------------------- seguridad local
def _origin_ok(origin: str | None) -> bool:
    """Solo la propia interfaz puede hablar con el servidor; otras páginas web abiertas en el navegador, no."""
    if not origin:
        return True                       # clientes que no son navegador (scripts de prueba)
    allowed = {f"http://{h}:{settings.port}" for h in ("127.0.0.1", "localhost")}
    return origin in allowed


def same_origin(origin: str | None = Header(default=None)):
    if not _origin_ok(origin):
        raise HTTPException(403, "Origen no permitido")


# ---------------------------------------------------------------- estado y ajustes
def model_path() -> Path | None:
    return models.active_path(persona["name"])


def public_config() -> dict:
    return {
        "name": character_name(), "user": settings.user_name, "llm": llm.status(),
        # Temas +18: implícitos con el cerebro local, nunca con la nube (no hay interruptor).
        "adult": {"active": adult_active(persona, is_cloud=settings.is_cloud, user_adult=profile.is_adult())},
        "onboarded": bool(state.load().get("onboarded")), "profile": profile.get(), "cloud": profile.public_cloud(),
        "voice": (profile.voice() or {}).get("name", ""), "local_model": settings.ollama_model,
        "voice_engine": settings.voice_engine, "voice_engine_name": profile.VOICE_ENGINES[settings.voice_engine]["name"],
        "voice_engine_pref": profile.voice_engine(), "voice_auto": profile.voice_auto(), "voice_reason": settings.voice_reason,
        "watch": {"interval": settings.watch_interval, "model": settings.watch_model if settings.is_cloud else llm.local_model()},
        "stt": {"ready": transcriber.ready, "device": transcriber.device, "model": transcriber.model_name,
                "error": transcriber.error, "engine": transcriber.engine, "cloud": _ear_public(),
                # Whisper ya se descargó, pero las librerías de CUDA (~200 MB de vídeo, ~500 MB de RAM) siguen
                # cargadas en este proceso hasta reiniciar el companion.
                "restart_frees": transcriber.engine == "nube" and transcriber.used_cuda},
        "cloud_only": profile.cloud_only(),
        "gemini_live": profile.gemini_live(), "gemini_live_model": profile.live()["model"],
        "gemini_live_voice": _live_voice_name(), "live": profile.public_live(),
        "model": model_path() is not None or models.kind(persona["name"]) == "orb",
        "model_id": models.active_id(persona["name"]), "model_kind": models.kind(persona["name"]),
        "barge_in": settings.barge_in, "actions": _actions_state(),
        "personality": {"id": personality.active_id(), "name": personality.active()["name"],
                        "temper": personality.temper(personality.active())},
        "started": STARTED,               # iniciar.ps1 lo compara con la fecha del código para saber si reiniciar
    }


def _live_voice_name() -> str:
    from . import gemini_live, realtime
    lv = profile.live()
    if lv["voice"]:
        return lv["voice"]
    v = profile.voice()
    speaks = (v or {}).get("speaks", "f")
    if lv["provider"] == "gemini":
        return gemini_live.voice_for(v["id"] if v else None, speaks)
    return realtime.voice_for(lv["provider"], speaks)


def _ear_public() -> dict:
    """Estado del oído en la nube, sin claves: si hay clave de Groq y quién respondió la última vez."""
    from . import stt_cloud
    return {"groq": bool(stt_cloud.groq_key()), "gemini": bool(stt_cloud.gemini_key()),
            "last": dict(stt_cloud.last) or None}


async def full_config() -> dict:
    return {**public_config(), "tts": await tts.available(), "gpu": await asyncio.to_thread(llm.gpu_memory)}


@app.get("/api/config")
async def get_config():
    return await full_config()


class ConfigIn(BaseModel):
    provider: str | None = None           # gemini | local


@app.post("/api/config", dependencies=[Depends(same_origin)])
async def set_config(body: ConfigIn):
    """Cambios en caliente (hasta reiniciar). Para dejarlos fijos, edita .env."""
    if body.provider is not None:
        if body.provider not in ("gemini", "local"):
            raise HTTPException(422, "provider debe ser gemini o local")
        changed = body.provider != settings.llm_provider
        settings.llm_provider = body.provider
        if body.provider == "local" and profile.gemini_live():
            state.save(provider=body.provider, gemini_live=False)
            profile.apply()
            from .session import _open
            for s in list(_open):
                if hasattr(s, "reset_live"):
                    await s.reset_live()
        else:
            state.save(provider=body.provider)            # se recuerda para la próxima sesión
        if changed:                       # local: se carga ya, para no esperar en el primer turno · nube: se libera la GPU
            _background(llm.warm_local() if body.provider == "local" else llm.unload_local())
        elif body.provider == "local":    # volver a pulsar «Local» repite la elección del modelo que cabe
            _background(llm.warm_local())
    return await full_config()


# ---------------------------------------------------------------- acciones en la PC
def _actions_state() -> dict:
    c = actions.config()
    return {**c, "available": llm.can_act(), "catalog": {k: v["title"] for k, v in actions.CATALOG.items()}}


@app.get("/api/actions")
async def get_actions():
    """Ajustes › Acciones: si están encendidas, cuáles se permiten siempre y el registro de lo que se hizo."""
    return {**_actions_state(), "history": actions.history(30)}


class ActionsIn(BaseModel):
    enabled: bool | None = None
    forget_always: str | None = None      # deja de permitir siempre esa acción (vuelve a preguntar)
    ask: bool | None = None               # pedir permiso en una tarjeta antes de cada acción
    full: bool | None = None              # acceso total: ninguna acción pide tarjeta


@app.post("/api/actions", dependencies=[Depends(same_origin)])
async def set_actions(body: ActionsIn):
    actions.save(enabled=body.enabled, forget_always=body.forget_always, ask=body.ask, full=body.full)
    return {**_actions_state(), "history": actions.history(30)}


@app.delete("/api/memory", dependencies=[Depends(same_origin)])
async def forget():
    store.forget_all()
    mood.reset()                          # su ánimo también sale de lo que hablaron
    return {"ok": True}


@app.get("/api/memory")
async def memory():
    """Lo que recuerda a largo plazo: datos sobre el usuario y resúmenes de conversaciones pasadas."""
    return {"facts": store.memories(200),
            "summaries": [{"text": t, "date": time.strftime("%d/%m/%Y", time.localtime(ts))} for t, ts in store.summaries(50)]}


class FactIn(BaseModel):
    fact: str


@app.post("/api/memory/forget", dependencies=[Depends(same_origin)])
async def forget_fact(body: FactIn):
    store.delete_memory(body.fact)
    return await memory()


# ---------------------------------------------------------------- personalidad
def _personality_state() -> dict:
    return {**personality.public(), "mood": mood.public(personality.active())}


@app.get("/api/personality")
async def get_personality():
    """Las personalidades (incluidas y propias), la elegida y su ánimo de ahora."""
    return _personality_state()


class PersonalitySelectIn(BaseModel):
    id: str


@app.post("/api/personality/select", dependencies=[Depends(same_origin)])
async def select_personality(body: PersonalitySelectIn):
    try:
        personality.select(body.id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    await _personality_ready()
    return _personality_state()


async def _personality_ready():
    """La personalidad va en el prompt de sistema: con el cerebro local, el modelo lo lee ya (la interfaz enseña
    «Ajustando…» mientras tanto), para que la primera respuesta no tarde. Como mucho 20 s: si no, sigue igual."""
    from .session import _open
    for s in list(_open)[-1:]:
        if hasattr(s, "reset_live"):
            await s.reset_live()
        try:
            await asyncio.wait_for(s.prime(), 20)
        except Exception:  # noqa: BLE001 (incluye el tiempo agotado: solo era para adelantar trabajo)
            pass


@app.post("/api/personality/custom", dependencies=[Depends(same_origin)])
async def save_personality(body: dict):
    """Crea una personalidad propia (desde cero o copiando una incluida, con `from`) o cambia una propia (`id`)."""
    try:
        personality.save_custom(body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    await _personality_ready()
    return _personality_state()


@app.delete("/api/personality/custom/{pid}", dependencies=[Depends(same_origin)])
async def delete_personality(pid: str):
    personality.delete_custom(pid)
    await _personality_ready()
    return _personality_state()


# ---------------------------------------------------------------- bienvenida y ajustes guardados
@app.get("/api/setup")
async def get_setup():
    from . import tts_light
    gpu = await asyncio.to_thread(llm.gpu_memory)
    installed = await llm.installed_local()
    node_ok = voz_proc.installed() or await tts.node_available()
    others = await asyncio.to_thread(profile.measured_others)
    res = profile.resources(gpu, is_cloud=settings.is_cloud, local_model=settings.ollama_model, node_ok=node_ok,
                            installed=installed, others=others)

    def fits(vram: float) -> dict:        # ¿cabe junto a cada voz? (sin tarjeta NVIDIA corre en el procesador)
        return {k: gpu is not None and vram <= room + 0.2 for k, room in res["room"].items()}
    catalog = [{**m, "installed": installed is not None and m["id"] in installed, "pull": llm.pulls.get(m["id"]),
                "fits": fits(m["vram_gb"])} for m in profile.LOCAL_MODELS]
    ids = {m["id"] for m in profile.LOCAL_MODELS}
    # Con las dos voces y el cambio automático, se recomienda la completa si cabe al menos con la nube: cuando el
    # modelo local no deje sitio, se pasa sola a la ligera.
    recommended = res["recommended_engine"]
    if node_ok and tts_light.installed() and profile.voice_auto() and profile.full_voice_fits(True, "", res["total_gb"]):
        recommended = "completa"
    extra = [n for n in sorted(installed or {}) if n not in ids]
    info = await llm.local_info(extra)
    others = [{"id": n, "vram_gb": 0.0 if info[n]["cloud"] else profile.model_vram(n, installed),
               "fits": fits(0.0 if info[n]["cloud"] else profile.model_vram(n, installed)),
               "vision": info[n]["vision"], "cloud": info[n]["cloud"]}
              for n in extra if info[n]["chat"]]
    return {
        "resources": res,
        "voice_engine": {"selected": profile.voice_engine(), "in_use": settings.voice_engine, "reason": settings.voice_reason,
                         "auto": profile.voice_auto(), "recommended": recommended, "node": node_ok,
                         "fits_now": res["recommended_engine"] == "completa",
                         "light_installed": tts_light.installed(), "light_size_mb": tts_light.SIZE_MB,
                         "light_progress": tts_light.progress or None},
        "ear": {"engine": profile.ear_engine(), **_ear_public()}, "cloud_only": profile.cloud_only(),
        "gemini_live": profile.gemini_live(), "gemini_live_model": profile.live()["model"], "live": profile.public_live(),
        "onboarded": bool(state.load().get("onboarded")), "character": character_name(), "year": time.localtime().tm_year,
        "profile": profile.get(), "suggested_name": settings.user_name,
        "provider": settings.llm_provider, "cloud": profile.public_cloud(),
        "presets": [{"id": k, **{f: v[f] for f in ("name", "base", "keys", "note")}} for k, v in profile.PRESETS.items()],
        "local": {"gpu": gpu, "ollama": installed is not None, "recommended": res["recommended_model"],
                  "selected": settings.ollama_model, "in_use": llm.local_model(), "models": catalog, "others": others},
        "voices": profile.voices(), "tts": await tts.available(),
    }


class SetupIn(BaseModel):
    profile: dict | None = None
    cloud: dict | None = None             # {preset, base, model, key}; sin key se conserva la guardada
    provider: str | None = None           # gemini (= nube) | local
    local_model: str | None = None
    voice: str | None = None
    voice_engine: str | None = None       # completa | ligera | nube
    ear: dict | None = None               # {engine: local|nube, groq_key, remove_groq_key}; sin groq_key se conserva
    cloud_only: bool | None = None        # cerebro, oído y voz en la nube (al apagarlo vuelve lo de antes)
    gemini_live: bool | None = None       # modo en vivo: el proveedor oye, piensa, ve y habla (WebSocket directo)
    live: dict | None = None              # {provider, key, remove_key, model, voice, url}; sin key se conserva
    voice_auto: bool | None = None        # pasar sola a la ligera cuando la completa no cabe en la tarjeta
    onboarded: bool | None = None


@app.post("/api/setup", dependencies=[Depends(same_origin)])
async def set_setup(body: SetupIn):
    """Guarda un paso de la bienvenida (o un cambio hecho después en Ajustes). Todo queda en data/settings.json."""
    changes: dict = {}
    before = settings.llm_provider
    try:
        if body.profile is not None:
            changes["profile"] = profile.clean_profile(body.profile)
        if body.cloud is not None:
            preset = str(body.cloud.get("preset") or "gemini")
            if preset not in profile.PRESETS:
                raise ValueError("Proveedor no reconocido.")
            base = str(body.cloud.get("base") or profile.PRESETS[preset]["base"]).strip().rstrip("/")
            if not base.startswith(("https://", "http://127.0.0.1", "http://localhost")):
                raise ValueError("La dirección de la API tiene que empezar por https://")
            old = profile.cloud()
            key = str(body.cloud.get("key") or "").strip() or (old["key"] if old["preset"] == preset else "")
            if not key:
                raise ValueError("Falta la clave de API.")
            model = str(body.cloud.get("model") or "").strip()[:120]
            if preset != "gemini" and not model:
                raise ValueError("Elige el modelo que quieres usar.")
            changes["cloud"] = {"preset": preset, "base": base, "model": model, "key": key}
        if body.local_model is not None:
            installed = await llm.installed_local()
            if installed is None:
                raise ValueError("Ollama no está abierto en esta PC.")
            if body.local_model not in installed:
                raise ValueError("Ese modelo todavía no está descargado.")
            changes["local_model"] = body.local_model
        if body.voice is not None:
            if not any(v["id"] == body.voice and v["available"] for v in profile.voices()):
                raise ValueError("Esa voz todavía no está disponible.")
            changes["voice"] = body.voice
        if body.voice_engine is not None:
            from . import tts_light
            if body.voice_engine not in profile.VOICE_ENGINES:
                raise ValueError("Motor de voz no reconocido.")
            if body.voice_engine == "ligera" and not tts_light.installed():
                raise ValueError("La voz ligera todavía no está descargada.")
            if body.voice_engine == "nube":
                from . import tts_cloud
                if not tts_cloud.installed():
                    raise ValueError("Falta la librería de la voz en la nube: vuelve a ejecutar el instalador.")
            changes["voice_engine"] = body.voice_engine
        if body.ear is not None:
            from . import stt_cloud
            ear = dict(state.load().get("ear") or {})
            key = str(body.ear.get("groq_key") or "").strip()
            if key:
                try:
                    ok = await stt_cloud.check_groq(key)
                except stt_cloud.CloudEarError as e:
                    raise ValueError(str(e)) from None
                if not ok:
                    raise ValueError("Groq no acepta esa clave. Cópiala de nuevo desde console.groq.com/keys.")
                ear["groq_key"] = key
            if body.ear.get("remove_groq_key"):
                ear.pop("groq_key", None)
            if body.ear.get("engine") is not None:
                if body.ear["engine"] not in profile.EAR_ENGINES:
                    raise ValueError("Oído no reconocido.")
                ear["engine"] = body.ear["engine"]
            if ear.get("engine") == "nube" and not (ear.get("groq_key") or stt_cloud.gemini_key()):
                raise ValueError("Para el oído en la nube hace falta una clave de Groq o el cerebro con Gemini.")
            changes["ear"] = ear
        if body.live is not None:
            changes["live"] = _live_settings(body.live)
        if body.voice_auto is not None:
            changes["voice_auto"] = bool(body.voice_auto)
        if body.provider is not None:
            if body.provider not in ("gemini", "local"):
                raise ValueError("provider debe ser gemini o local")
            changes["provider"] = body.provider
        if body.onboarded is not None:
            changes["onboarded"] = bool(body.onboarded)
        if body.cloud_only is not None:
            changes.update(_cloud_only_changes(bool(body.cloud_only), changes))
        if body.gemini_live is not None:
            changes.update(_gemini_live_changes(bool(body.gemini_live), changes))
    except ValueError as e:
        raise HTTPException(422, str(e))
    state.save(**changes)
    engine = settings.voice_engine
    if body.provider is not None or "local_model" in changes or "voice_engine" in changes:
        profile.squeeze(False)            # se vuelve a decidir si cabe la voz completa
    profile.apply()
    transcriber.hint = _hint()
    if transcriber.set_engine(profile.ear_engine()):      # se volvió al oído local: Whisper se carga de nuevo
        asyncio.get_running_loop().run_in_executor(None, transcriber.load)
    if settings.voice_engine != engine or "voice_engine" in changes:   # se arranca o se apaga la voz completa
        await asyncio.to_thread(voz_proc.sync)
    if "cloud" in changes:
        llm.reset_cloud()
    if any(k in changes for k in ("gemini_live", "live", "cloud", "voice", "profile", "provider")):
        from .session import _open
        for s in list(_open):
            if hasattr(s, "reset_live"):
                await s.reset_live()
    if settings.llm_provider != before or "local_model" in changes:
        _background(llm.warm_local() if not settings.is_cloud else llm.unload_local())
    return await full_config()


def _cloud_only_changes(on: bool, changes: dict) -> dict:
    """«Solo nube»: guarda lo que había (cerebro, oído, voz) y lo pasa todo a la nube; al apagarlo lo devuelve."""
    from . import tts_cloud
    s = {**state.load(), **changes}
    if on == bool(s.get("cloud_only")):
        return {}
    ear = dict(s.get("ear") or {})
    if not on:
        before = s.get("before_cloud_only") or {}
        ear["engine"] = before.get("ear", "local")
        return {"cloud_only": False, "provider": before.get("provider", "gemini"), "ear": ear,
                "voice_engine": before.get("voice_engine", profile.voice_engine())}
    cloud = s.get("cloud") or {}
    key = cloud.get("key") or profile.cloud()["key"]
    if not key:
        raise ValueError("Para usar solo la nube primero pon la clave del cerebro (Cerebro › Proveedor y clave).")
    if not (ear.get("groq_key") or (cloud.get("preset", profile.cloud()["preset"]) == "gemini" and key)):
        raise ValueError("Para el oído en la nube hace falta una clave de Groq o el cerebro con Gemini.")
    if not tts_cloud.installed():
        raise ValueError("Falta la librería de la voz en la nube: vuelve a ejecutar el instalador.")
    before = {"provider": s.get("provider", settings.llm_provider), "ear": ear.get("engine", "local"),
              "voice_engine": s.get("voice_engine", profile.voice_engine())}
    ear["engine"] = "nube"
    return {"cloud_only": True, "gemini_live": False, "before_cloud_only": before, "provider": "gemini", "ear": ear, "voice_engine": "nube"}


def _live_settings(body: dict) -> dict:
    """Proveedor de la conversación en vivo. La clave nunca vuelve a la interfaz."""
    from .realtime import LIVE_PROVIDERS
    lv = dict(state.load().get("live") or {})
    provider = str(body.get("provider") or lv.get("provider") or "gemini")
    if provider not in LIVE_PROVIDERS:
        raise ValueError("Proveedor en vivo no reconocido.")
    if provider != lv.get("provider", "gemini"):
        lv = {}                                        # otra empresa: su clave, modelo y voz son otros
    lv["provider"] = provider
    key = str(body.get("key") or "").strip()
    if key:
        lv["key"] = key[:300]
    if body.get("remove_key"):
        lv.pop("key", None)
    for f, n in (("model", 120), ("voice", 60)):
        if body.get(f) is not None:
            lv[f] = str(body[f]).strip()[:n]
    if body.get("url") is not None:
        url = str(body["url"]).strip()
        if url and not url.startswith("wss://"):
            raise ValueError("La dirección del proveedor en vivo tiene que empezar por wss://")
        lv["url"] = url[:300]
    if provider == "custom" and not lv.get("url"):
        raise ValueError("Escribe la dirección wss:// del proveedor.")
    return lv


def _gemini_live_changes(on: bool, changes: dict) -> dict:
    """«Gemini Live»: conecta la interfaz directamente a la Gemini Live API (oído, cerebro, visión y voz en tiempo real).
    Guarda los ajustes previos para restaurarlos al apagarlo."""
    s = {**state.load(), **changes}
    if on == bool(s.get("gemini_live")):
        return {}
    ear = dict(s.get("ear") or {})
    if not on:
        before = s.get("before_gemini_live") or {}
        ear["engine"] = before.get("ear", "local")
        return {
            "gemini_live": False,
            "provider": before.get("provider", "gemini"),
            "ear": ear,
            "voice_engine": before.get("voice_engine", profile.voice_engine()),
            "cloud_only": bool(before.get("cloud_only", False)),
        }
    lv = s.get("live") or {}
    provider = lv.get("provider") or profile.live()["provider"]
    key = lv.get("key") or ""
    if not key and provider == "gemini":
        cloud = s.get("cloud") or {}
        if cloud.get("preset", profile.cloud()["preset"]) == "gemini":
            key = cloud.get("key") or profile.cloud()["key"]
    if not key:
        from .realtime import LIVE_PROVIDERS
        raise ValueError(f"Para la conversación en vivo con {LIVE_PROVIDERS[provider]['name']} hace falta su clave "
                         "(Cerebro y voz › En vivo).")
    before = {
        "provider": s.get("provider", settings.llm_provider),
        "ear": ear.get("engine", "local"),
        "voice_engine": s.get("voice_engine", profile.voice_engine()),
        "cloud_only": bool(s.get("cloud_only", False)),
    }
    ear["engine"] = "nube"
    return {
        "gemini_live": True,
        "before_gemini_live": before,
        "cloud_only": False,
        "provider": "gemini",
        "ear": ear,
        "voice_engine": "nube",
    }


@app.get("/api/desktop/scene")
async def desktop_scene(sit: int = 0):
    """Para la mascota de escritorio (modo flotante): dónde está la ventana activa y, con `sit`, la ventana sobre la
    que está sentada. Solo posición y estado, nunca el título ni el contenido (companion/desktop_scene.py)."""
    from . import desktop_scene as ds
    fg = await asyncio.to_thread(ds.foreground)
    return {"fg": fg, "sit": await asyncio.to_thread(ds.window, sit) if sit else None}


@app.get("/api/update")
async def get_update():
    """¿Hay una versión nueva publicada? (companion/update.py; como mucho una consulta a GitHub cada 12 horas)"""
    from . import update
    return await update.check()


# ---------------------------------------------------------------- carga y cierre (lifecycle.py)
@app.get("/api/loading")
async def get_loading():
    """Lo que todavía se está cargando, para la pantalla de carga de la interfaz."""
    return await lifecycle.loading(transcriber)


class OwnerIn(BaseModel):
    pid: int


@app.post("/api/owner", dependencies=[Depends(same_origin)])
async def set_owner(body: OwnerIn):
    """La ventana del companion se registra: si su proceso muere sin cerrar bien, el servidor se apaga."""
    lifecycle.watch_owner(body.pid)
    return {"ok": True}


@app.post("/api/shutdown", dependencies=[Depends(same_origin)])
async def do_shutdown():
    """Apagado ordenado (detener.ps1 / detener.sh): voz completa, modelo local de Ollama y este proceso."""
    _background(lifecycle.shutdown("pedido al cerrar"))
    return {"ok": True}


class ResetIn(BaseModel):
    data: bool = False                    # True = borra también los datos del usuario


@app.post("/api/setup/reset", dependencies=[Depends(same_origin)])
async def reset_setup(body: ResetIn):
    """Ajustes › Empezar de nuevo. Sin `data` solo vuelve a mostrar la bienvenida (lo guardado sigue ahí para
    cambiarlo). Con `data` borra perfil, clave, voz, personaje elegido, conversación y recuerdos: queda como
    recién instalado (los VRM propios que se subieron siguen en su carpeta)."""
    before = settings.llm_provider
    if body.data:
        state.clear()
        store.forget_all()
        mood.reset()
        profile.apply()
        transcriber.hint = _hint()
        llm.reset_cloud()
        if settings.llm_provider != before:
            _background(llm.warm_local() if not settings.is_cloud else llm.unload_local())
    else:
        state.save(onboarded=False)
    return await full_config()


class CloudCheckIn(BaseModel):
    preset: str = "gemini"
    base: str = ""
    key: str = ""


@app.post("/api/cloud/check", dependencies=[Depends(same_origin)])
async def cloud_check(body: CloudCheckIn):
    """Comprueba la clave con el proveedor antes de guardarla y devuelve sus modelos."""
    if body.preset not in profile.PRESETS:
        raise HTTPException(422, "Proveedor no reconocido.")
    base = (body.base or profile.PRESETS[body.preset]["base"]).strip().rstrip("/")
    old = profile.cloud()
    key = body.key.strip() or (old["key"] if old["preset"] == body.preset else "")
    if not key or not base.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise HTTPException(422, "Falta la clave o la dirección de la API.")
    try:
        return {"ok": True, "models": await llm.check_cloud(base, key)}
    except llm.LLMError as e:
        raise HTTPException(400, str(e))


class PullIn(BaseModel):
    id: str


@app.post("/api/local-models/pull", dependencies=[Depends(same_origin)])
async def pull_model(body: PullIn):
    """Descarga con Ollama uno de los modelos ligeros del catálogo (lo pide el usuario en la bienvenida)."""
    if body.id not in {m["id"] for m in profile.LOCAL_MODELS}:
        raise HTTPException(422, "Ese modelo no está en el catálogo.")
    current = llm.pulls.get(body.id)
    if not current or current.get("error") or current.get("status") == "success":
        _background(llm.pull_local(body.id))
    return {"ok": True}


@app.post("/api/voice-engine/install", dependencies=[Depends(same_origin)])
async def install_light_voice():
    """Descarga los modelos de la voz ligera (Piper, ~380 MB). Lo pide el usuario en la bienvenida o en Ajustes."""
    from . import tts_light
    if not tts_light.installed():
        _background(tts_light.install())
    return {"ok": True}


class VoiceIn(BaseModel):
    id: str
    engine: str | None = None             # con qué voz oír la muestra (por defecto, la que está en uso)


@app.post("/api/voices/preview", dependencies=[Depends(same_origin)])
async def voice_preview(body: VoiceIn):
    """Una frase de muestra con esa voz, como WAV. Sale de un archivo pregrabado (voices/previews): oír
    muestras no carga voces en el nodo. Solo si falta el archivo se le pide al nodo."""
    v = next((v for v in profile.voices() if v["id"] == body.id and v["available"]), None)
    if not v:
        raise HTTPException(404, "Esa voz todavía no está disponible.")
    engine = body.engine if body.engine in profile.VOICE_ENGINES else settings.voice_engine
    recorded = (voice_import.previews() if v["custom"] else profile.PREVIEWS) / f"{v['id']}.wav"
    if engine == "completa":
        if recorded.is_file():
            return FileResponse(recorded, media_type="audio/wav", headers={"Cache-Control": "no-cache"})
        profile.install_voice(v["tts_voice"])
    try:                                  # la ligera se genera al momento: va en el procesador y tarda décimas
        pcm = b"".join([c async for c in tts.stream_speech(profile.PREVIEW_TEXT.format(name=v["name"]), v["tts_voice"], engine=engine)])
    except tts.TTSError as e:
        raise HTTPException(503, str(e))
    n = len(pcm)
    header = (b"RIFF" + (36 + n).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little") + (1).to_bytes(2, "little")
              + (1).to_bytes(2, "little") + tts.SAMPLE_RATE.to_bytes(4, "little") + (tts.SAMPLE_RATE * 2).to_bytes(4, "little")
              + (2).to_bytes(2, "little") + (16).to_bytes(2, "little") + b"data" + n.to_bytes(4, "little"))
    if engine == "completa" and v["custom"] and n:      # la muestra ▶ de una voz propia se graba la primera vez
        try:
            recorded.parent.mkdir(parents=True, exist_ok=True)
            recorded.write_bytes(header + pcm)
        except OSError:
            pass
    return Response(header + pcm, media_type="audio/wav")


@app.post("/api/voices/custom", dependencies=[Depends(same_origin)])
async def add_custom_voice(request: Request, name: str = "", speaks: str = ""):
    """Añade una voz propia a partir de una grabación (Ajustes › Voz › Añadir una voz propia). El cuerpo es el
    archivo de audio tal cual. Se queda en data/voces y aparece en la lista; elegirla es aparte."""
    limit = voice_import.MAX_MB * 1024 * 1024
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, f"La grabación supera {voice_import.MAX_MB} MB: recórtala a unos minutos.")
    taken = {v["name"] for v in profile.voices()}

    def make():                           # con el candado del oído: Whisper no puede transcribir dos cosas a la vez
        model = transcriber.local_model()   # con el oído en la nube, un Whisper en el procesador solo para esto
        with transcriber._lock:
            return voice_import.create(bytes(data), name, speaks, model, taken)
    try:
        v = await asyncio.to_thread(make)
    except voice_import.VoiceError as e:
        raise HTTPException(400, str(e))
    log.info("Voz propia guardada: %s (muestra de %.1f s)", v["id"], v["seconds"])
    return {"voice": {k: v[k] for k in ("id", "name", "seconds")}, "voices": profile.voices()}


@app.delete("/api/voices/custom/{voice_id}", dependencies=[Depends(same_origin)])
async def delete_custom_voice(voice_id: str):
    """Quita una voz propia (solo las del usuario). Si era la elegida, se vuelve a la voz por defecto."""
    try:
        voice_import.remove(voice_id)
    except voice_import.VoiceError as e:
        raise HTTPException(404, str(e))
    if state.load().get("voice") == voice_id:
        state.save(voice=None)
    profile.apply()
    transcriber.hint = _hint()
    return {"voices": profile.voices()}


# ---------------------------------------------------------------- modelo 3D
@app.get("/api/model")
async def get_model():
    path = model_path()
    if not path:
        raise HTTPException(404, "Todavía no hay modelo 3D")
    return FileResponse(path, media_type="model/gltf-binary", headers={"Cache-Control": "no-cache"})


@app.get("/api/models")
async def list_models():
    return models.listing(persona["name"])


@app.post("/api/models", dependencies=[Depends(same_origin)])
async def upload_model(request: Request, filename: str = "modelo.vrm"):
    """Sube un VRM propio (botón de Ajustes o arrastrándolo a la ventana). Se valida el formato, se leen
    nombre y licencia, se guarda aparte del modelo de fábrica y queda como modelo activo."""
    limit = models.MAX_MB * 1024 * 1024
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, f"El VRM supera {models.MAX_MB} MB")
    try:
        saved = models.add(filename, bytes(data))
    except models.ModelError as e:
        raise HTTPException(400, str(e))
    log.info("Modelo propio guardado: %s (%s, VRM %s)", saved["id"], saved["meta"].get("name"), saved["meta"]["spec"])
    return {**saved, **models.listing(persona["name"])}


class ModelSelectIn(BaseModel):
    id: str


@app.post("/api/models/select", dependencies=[Depends(same_origin)])
async def select_model(body: ModelSelectIn):
    try:
        models.select(body.id)
    except models.ModelError as e:
        raise HTTPException(404, str(e))
    return models.listing(persona["name"])


@app.delete("/api/models/{model_id}", dependencies=[Depends(same_origin)])
async def delete_model(model_id: str):
    try:
        models.remove(model_id)
    except models.ModelError as e:
        raise HTTPException(400, str(e))
    return models.listing(persona["name"])


# ---------------------------------------------------------------- conversación en vivo
@app.websocket("/ws")
async def live(ws: WebSocket):
    if not _origin_ok(ws.headers.get("origin")):
        await ws.close(code=1008)
        return
    await ws.accept()
    session = Session(ws, persona, transcriber)
    session.start()
    await ws.send_text(json.dumps({"type": "hello", **await full_config()}, ensure_ascii=False))
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                await session.on_audio(msg["bytes"])
            elif msg.get("text"):
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    await session.on_message(data)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await session.close()


app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
