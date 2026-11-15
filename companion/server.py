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

from . import actions, llm, models, profile, state, store, tts, voice_import, voz_proc
from .config import settings
from .prompt import adult_active, load_persona
from .session import Session
from .stt import Transcriber

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("companion")
STARTED = int(time.time())

persona = load_persona(settings.persona_path)
profile.apply()                           # lo elegido en la bienvenida manda sobre .env


def character_name() -> str:
    """El personaje se llama como la voz elegida (Mika, Kenji…); `persona` es la ficha común a todas."""
    return profile.character(persona)["name"]


def _hint() -> str:
    return f"Conversación entre {settings.user_name} y {character_name()}, su asistente personal."


transcriber = Transcriber(settings.stt_model, settings.stt_device, settings.stt_compute, settings.stt_language, hint=_hint())


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_quiet_resets)
    loop.run_in_executor(None, transcriber.load)   # el modelo carga sin frenar el arranque
    log.info("Companion en http://%s:%s · cerebro: %s", settings.host, settings.port, llm.status())
    if not settings.is_cloud:
        _background(llm.warm_local())
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
        "watch": {"interval": settings.watch_interval, "model": settings.watch_model if settings.is_cloud else llm.local_model()},
        "stt": {"ready": transcriber.ready, "device": transcriber.device, "model": transcriber.model_name,
                "error": transcriber.error},
        "model": model_path() is not None or models.kind(persona["name"]) == "orb",
        "model_id": models.active_id(persona["name"]), "model_kind": models.kind(persona["name"]),
        "barge_in": settings.barge_in, "actions": _actions_state(),
        "started": STARTED,               # iniciar.ps1 lo compara con la fecha del código para saber si reiniciar
    }


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


@app.post("/api/actions", dependencies=[Depends(same_origin)])
async def set_actions(body: ActionsIn):
    actions.save(enabled=body.enabled, forget_always=body.forget_always, ask=body.ask)
    return {**_actions_state(), "history": actions.history(30)}


@app.delete("/api/memory", dependencies=[Depends(same_origin)])
async def forget():
    store.forget_all()
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


# ---------------------------------------------------------------- bienvenida y ajustes guardados
@app.get("/api/setup")
async def get_setup():
    from . import tts_light
    gpu = await asyncio.to_thread(llm.gpu_memory)
    installed = await llm.installed_local()
    node_ok = voz_proc.installed() or await tts.node_available()
    res =profile.resources(gpu, is_cloud=settings.is_cloud, local_model=settings.ollama_model, node_ok=node_ok, installed=installed)

    def fits(vram: float) -> dict:        # ¿cabe junto a cada voz? (sin tarjeta NVIDIA corre en el procesador)
        return {k: gpu is not None and vram <= room + 0.2 for k, room in res["room"].items()}
    catalog = [{**m, "installed": installed is not None and m["id"] in installed, "pull": llm.pulls.get(m["id"]),
                "fits": fits(m["vram_gb"])} for m in profile.LOCAL_MODELS]
    ids = {m["id"] for m in profile.LOCAL_MODELS}
    others = [{"id": n, "vram_gb": profile.model_vram(n, installed), "fits": fits(profile.model_vram(n, installed))}
              for n in sorted(installed or {}) if n not in ids]
    return {
        "resources": res,
        "voice_engine": {"selected": settings.voice_engine, "recommended": res["recommended_engine"], "node": node_ok,
                         "light_installed": tts_light.installed(), "light_size_mb": tts_light.SIZE_MB,
                         "light_progress": tts_light.progress or None},
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
    voice_engine: str | None = None       # completa | ligera
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
            changes["voice_engine"] = body.voice_engine
        if body.provider is not None:
            if body.provider not in ("gemini", "local"):
                raise ValueError("provider debe ser gemini o local")
            changes["provider"] = body.provider
        if body.onboarded is not None:
            changes["onboarded"] = bool(body.onboarded)
    except ValueError as e:
        raise HTTPException(422, str(e))
    state.save(**changes)
    profile.apply()
    transcriber.hint = _hint()
    if "voice_engine" in changes:         # la voz completa se arranca o se apaga (devuelve su memoria de vídeo)
        await asyncio.to_thread(voz_proc.sync)
    if "cloud" in changes:
        llm.reset_cloud()
    if settings.llm_provider != before or "local_model" in changes:
        _background(llm.warm_local() if not settings.is_cloud else llm.unload_local())
    return await full_config()


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
        with transcriber._lock:
            return voice_import.create(bytes(data), name, speaks, transcriber.model, taken)
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
