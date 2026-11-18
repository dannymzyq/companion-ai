"""Cerebro intercambiable: Gemini (nube, API compatible con OpenAI) u Ollama (local).

Nube: relevo de modelos cuando uno agota su cuota gratuita y, al final, el modelo local.
Local: el modelo tiene que caber en la memoria de vídeo junto a la voz y Whisper. Si no cabe, Windows lo
desborda a la RAM y responde diez veces más lento (o el motor se cae): eso se detecta por la velocidad real
y se pasa al modelo pequeño de OLLAMA_FALLBACK.
"""
import asyncio
import json
import logging
import re
import subprocess
import sys
import time
from typing import AsyncIterator, NamedTuple

import httpx

from .config import settings

log = logging.getLogger("companion.llm")
_client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10))
# Local: conectar es inmediato o no hay Ollama; la primera respuesta puede tardar lo que tarde en cargar el modelo.
_local = httpx.AsyncClient(timeout=httpx.Timeout(connect=4, read=settings.ollama_timeout, write=30, pool=10))


class LLMError(Exception):
    """Error con un mensaje pensado para mostrarse en la interfaz."""


class QuotaExceeded(Exception):
    def __init__(self, wait: float, daily: bool):
        self.wait, self.daily = wait, daily


class Overloaded(Exception):
    """El modelo de la nube está saturado (503 «high demand», 5xx o sin respuesta a tiempo): se pasa al siguiente."""


class Image(NamedTuple):
    """Lo que el usuario comparte en un turno. No se guarda en el historial."""
    kind: str               # camera | screen (pantalla entera) | window (una sola ventana)
    jpeg: str               # JPEG en base64
    name: str = ""          # título de la ventana compartida, ya saneado


def image_label(img: Image) -> str:
    if img.kind == "camera":
        return "Imagen actual de la cámara del usuario (así se le ve a él ahora):"
    if img.kind == "window":
        title = f" «{img.name}»" if img.name else ""
        return f"Imagen actual de la ventana{title} que el usuario comparte (solo ves esa ventana, no el resto de su pantalla):"
    return "Imagen actual de la pantalla del usuario (lo mismo que él está viendo):"


_notices: list[str] = []


def pop_notices() -> list[str]:
    """Avisos para mostrar en la interfaz (cambios de modelo por cuota o por memoria). Se entregan una sola vez."""
    out = _notices[:]
    _notices.clear()
    return out


# ------------------------------------------------------------------ relevo en la nube
_QUOTA_FILE = settings.data_dir / "cuota.json"
_blocked_until: dict[str, float] = {}     # modelo de Gemini → hasta cuándo no se puede usar (cuota agotada)
_no_reasoning: set[str] = set()           # modelos que no admiten reasoning_effort
_local_announced = False

try:                                      # la cuota agotada se recuerda entre reinicios: no se gasta un intento en balde
    _blocked_until = {m: float(t) for m, t in json.loads(_QUOTA_FILE.read_text(encoding="utf-8")).items() if float(t) > time.time()}
except (OSError, ValueError):
    pass


def _block(model: str, wait: float):
    _blocked_until[model] = time.time() + wait
    try:
        _QUOTA_FILE.write_text(json.dumps({m: t for m, t in _blocked_until.items() if t > time.time()}), encoding="utf-8")
    except OSError:
        pass


def reset_cloud():
    """Al cambiar de proveedor o de clave: lo que se sabía de cuotas agotadas ya no vale."""
    _blocked_until.clear()
    _no_reasoning.clear()
    _slow_cloud.clear()
    _slow_until.clear()
    try:
        _QUOTA_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _is_gemini() -> bool:
    return settings.cloud_preset == "gemini"


def gemini_models(background: bool = False) -> list[str]:
    """Modelos de la nube en orden de uso. Solo Gemini tiene relevo; con otro proveedor es el modelo elegido.
    `background`: trabajo de fondo (resúmenes, pasos al usar una ventana): primero BACKGROUND_MODEL."""
    if not _is_gemini():
        return [settings.cloud_model] if settings.cloud_model else []
    chain = [settings.gemini_model, *[m for m in settings.gemini_fallback if m != settings.gemini_model]]
    if background and settings.background_model:
        chain = [settings.background_model, *[m for m in chain if m != settings.background_model]]
    return chain


async def complete(messages: list[dict], max_tokens: int = 220, background: bool = True) -> str:
    """Respuesta completa, sin voz ni etiquetas (resúmenes para la memoria a largo plazo)."""
    sampling = {"temperature": 0.3, "top_p": 0.9, "max_tokens": max_tokens}
    return "".join([p async for p in stream_chat(messages, sampling, background=background)])


def _usable(model: str) -> bool:
    return time.time() >= _blocked_until.get(model, 0)


def status() -> dict:
    if settings.is_cloud:
        models = gemini_models()
        ready = bool(settings.gemini_api_key) and bool(models)
        current = next((m for m in models if _usable(m)), None)
        detail = "" if ready else "Falta la clave del cerebro en la nube: ponla en Ajustes › Cerebro"
        if ready and current != models[0]:
            detail = f"Cuota de {models[0]} agotada por ahora"
        return {"provider": "gemini", "model": current or f"{local_model()} (respaldo local)", "ready": ready,
                "detail": detail}
    model = local_model()
    detail = "" if model == settings.ollama_model else f"{settings.ollama_model} iba lento: no cabe ahora en la memoria de vídeo"
    return {"provider": "local", "model": model, "ready": True, "detail": detail, "vision": _vision.get(model, True)}


async def observe(messages: list[dict], sampling: dict, images: list[Image]) -> str:
    """Respuesta corta y completa para la mirada en vivo (Mika mira por su cuenta lo que se comparte).
    En la nube usa solo WATCH_MODEL, para no gastar la cuota de la conversación."""
    if settings.is_cloud:
        model = settings.watch_model if _is_gemini() else settings.cloud_model
        if not settings.gemini_api_key or not model:
            raise LLMError("La mirada en vivo necesita la clave del cerebro en la nube (Ajustes › Cerebro).")
        if not _usable(model):
            raise LLMError(f"La mirada en vivo no está disponible ahora: {model} agotó su cuota gratuita de hoy.")
        try:
            return "".join([p async for p in _gemini(model, _images_openai(messages, images), sampling)])
        except Overloaded:
            return "[silencio]"                # saturado: esta vez no mira; la mirada sigue encendida
        except QuotaExceeded as q:
            _block(model, q.wait)
            raise LLMError(f"La mirada en vivo se detiene: {model} agotó su cuota gratuita. La conversación sigue igual.")
    if not sees_images():
        return "[silencio]"
    return "".join([p async for p in _ollama(_images_ollama(messages, images), sampling)])


async def stream_chat(messages: list[dict], sampling: dict, images: list[Image] | None = None,
                      background: bool = False) -> AsyncIterator[str]:
    """`images`: lo que el usuario comparte en este turno (cámara, pantalla o ventana). Se adjuntan a su último
    mensaje; no se guardan en el historial. `background`: trabajo de fondo (ver gemini_models)."""
    stream = (_cloud(messages, sampling, images, background) if settings.is_cloud
              else _ollama(_images_ollama(messages, images), sampling))
    async for piece in stream:
        yield piece


async def _cloud(messages: list[dict], sampling: dict, images, background: bool = False) -> AsyncIterator[str]:
    """Gemini con relevo: si un modelo agotó su cuota gratuita se pasa al siguiente y, al final, al local."""
    global _local_announced
    chain = gemini_models(background)
    if not settings.gemini_api_key or not chain:
        raise LLMError("Falta la clave del cerebro en la nube. Ponla en Ajustes › Cerebro, o usa el cerebro local.")
    payload = _images_openai(messages, images)
    order = _by_speed(chain)
    for n, model in enumerate(order):
        if not _usable(model):
            continue
        sent = False
        t0 = time.monotonic()
        # Si quedan otros modelos, no se espera más de CLOUD_FIRST_S al primer texto: un modelo saturado tardaba
        # 8-49 s en devolver su 503 (medido el 18 nov 2026) mientras Flash-Lite contestaba en 1 s.
        rest = any(_usable(m) for m in order[n + 1:])
        deadline = (CLOUD_FIRST_BG_S if background else CLOUD_FIRST_S) if rest else None
        stream = _gemini(model, payload, sampling).__aiter__()
        try:
            try:
                first = await asyncio.wait_for(stream.__anext__(), deadline)
            except asyncio.TimeoutError:
                raise Overloaded(f"sin respuesta en {deadline:g} s") from None
            except StopAsyncIteration:
                first = None
            if first is not None:
                if not background:
                    _note_wait(model, time.monotonic() - t0, chain)
                sent = True
                yield first
                async for piece in stream:
                    yield piece
            if not background:
                _local_announced = False
                if _fallback_loaded:          # la nube volvió: el respaldo local deja libre la tarjeta
                    _keep(asyncio.create_task(_drop_fallback()))
            return
        except Overloaded as e:
            await stream.aclose()
            if sent:                           # ya habló: cortar a media frase sería peor que esperar
                raise LLMError("El cerebro en la nube se cortó a media respuesta. Vuelve a intentarlo.") from None
            _busy(model)
            log.warning("Nube: %s saturado (%s); paso al siguiente y lo dejo al final %d min", model, e, CLOUD_BUSY_S // 60)
            continue
        except LLMError as e:
            # El modelo de fondo puede no estar disponible para esa clave (o no admitir imágenes): sigue el relevo.
            if background and model == settings.background_model and model != settings.gemini_model and not sent:
                log.warning("El modelo de fondo %s falló (%s); sigo con el relevo normal durante una hora", model, e)
                _block(model, 3600)
                continue
            raise
        except QuotaExceeded as q:
            _block(model, q.wait)
            nxt = next((m for m in chain if _usable(m)), None)
            if background:
                log.warning("Cuota de %s agotada en trabajo de fondo; sigue: %s", model, nxt or "local")
                continue
            if q.daily:
                log.warning("Cuota diaria gratuita de %s agotada (%.1f h); sigue: %s", model, q.wait / 3600, nxt or "local")
                _notices.append(f"Se agotó la cuota gratuita de hoy de {model}. "
                                + (f"Sigo con {nxt}." if nxt else "No quedan modelos de Gemini por hoy."))
    if background:
        # Con la nube elegida, el trabajo de fondo (resúmenes, pasos al usar una ventana) nunca carga el modelo
        # local: en una tarjeta pequeña le quitaba la memoria de vídeo a la voz completa sin que el usuario lo
        # pidiera (15 nov 2026). Se reintenta cuando vuelva la cuota.
        raise LLMError("El cerebro en la nube no está disponible ahora (cuota o saturación); el trabajo de fondo "
                       "espera a que vuelva.")
    if not settings.local_fallback:
        raise LLMError("El cerebro en la nube no está disponible ahora (cuota agotada o servidores saturados). "
                       "Prueba en un momento, usa el cerebro local desde Ajustes o revisa el plan de tu proveedor.")
    model, cpu = await _fallback_place()
    if not _local_announced:
        _local_announced = True
        _notices.append(f"El cerebro en la nube no está disponible ahora (cuota o saturación). Sigo con el modelo local {model}"
                        + (" en el procesador, para no quitarle memoria de vídeo a la voz ni al oído: irá más lento."
                           if cpu else ": todo queda en esta PC."))
    async for piece in _ollama(_images_ollama(messages, images), sampling, model=model, cpu=cpu):
        yield piece


# Lento: hay días en que un modelo de Gemini tarda 20-30 s en empezar a responder (gemini-3.6-flash, 16 nov 2026)
# mientras Flash-Lite contesta en 3. Si tarda más de CLOUD_SLOW_S en dar el primer texto dos turnos seguidos, se
# empieza por el siguiente de la lista durante CLOUD_REST_S (lo mismo que hace la app de iOS).
CLOUD_SLOW_S, CLOUD_SLOW_TURNS, CLOUD_REST_S = 8.0, 2, 1800
# Saturado (503 o sin primer texto en CLOUD_FIRST_S con otros modelos disponibles): se pasa al siguiente en el acto
# y ese modelo va al final de la lista CLOUD_BUSY_S. El trabajo de fondo espera algo más (no hay nadie esperando).
CLOUD_FIRST_S, CLOUD_FIRST_BG_S, CLOUD_BUSY_S = 4.5, 15.0, 600
_slow_cloud: dict[str, int] = {}          # modelo → turnos lentos seguidos
_slow_until: dict[str, float] = {}        # modelo → hasta cuándo se empieza por otro


def _busy(model: str):
    _slow_cloud[model] = 0
    _slow_until[model] = max(_slow_until.get(model, 0), time.time() + CLOUD_BUSY_S)


def _by_speed(chain: list[str]) -> list[str]:
    """La lista de relevo con los modelos que van lentos ahora al final (siguen ahí por si los demás fallan)."""
    now = time.time()
    return [m for m in chain if _slow_until.get(m, 0) <= now] + [m for m in chain if _slow_until.get(m, 0) > now]


def _note_wait(model: str, waited: float, chain: list[str]):
    if waited <= CLOUD_SLOW_S:
        _slow_cloud[model] = 0
        return
    _slow_cloud[model] = _slow_cloud.get(model, 0) + 1
    log.info("Nube: %s tardó %.1f s en empezar a responder (%d seguidos)", model, waited, _slow_cloud[model])
    others = [m for m in chain if m != model and _usable(m) and _slow_until.get(m, 0) <= time.time()]
    if _slow_cloud[model] >= CLOUD_SLOW_TURNS and others:
        _slow_cloud[model] = 0
        _slow_until[model] = time.time() + CLOUD_REST_S
        log.warning("Nube: %s va lento; durante %d min empiezo por %s", model, CLOUD_REST_S // 60, others[0])
        _notices.append(f"{model} está tardando mucho en responder hoy: durante media hora uso {others[0]}, "
                        "que responde antes.")


_fallback_loaded = False                  # el respaldo local de la nube está cargado en Ollama


async def _fallback_place() -> tuple[str, bool]:
    """Respaldo de la nube: el modelo local elegido, en la tarjeta solo si cabe en la memoria de vídeo que queda
    libre AHORA (la voz completa y el oído ya están cargados); si no, en el procesador (num_gpu 0). El usuario
    eligió la nube: el respaldo no debe desplazar a la voz ni frenar el juego."""
    model = local_models()[0]
    _ours.add(model)
    if not _local_sizes:
        _local_sizes.update({m.get("name"): int(m.get("size", 0) / 2**20) for m in (await _ollama_json("/api/tags")).get("models", [])})
    gpu = await asyncio.to_thread(gpu_memory)
    if gpu is None:
        return model, False               # sin tarjeta NVIDIA, Ollama ya corre en el procesador
    loaded = {m.get("name"): m for m in (await _ollama_json("/api/ps")).get("models", [])}
    on_gpu = loaded.get(model, {}).get("size_vram", 0) / 2**20
    free = gpu["total"] - gpu["used"] + on_gpu
    cpu = free < need_mb(model) + FALLBACK_MARGIN_MB
    log.info("Respaldo local %s %s (libres %d MB, pide ~%d MB)", model, "en el procesador" if cpu else "en la tarjeta",
             free, need_mb(model))
    return model, cpu


FALLBACK_MARGIN_MB = 700                  # holgura: la voz crece un poco al hablar y el juego también pide


async def _drop_fallback():
    global _fallback_loaded
    _fallback_loaded = False
    await unload_local()


def _last_user(messages: list[dict]) -> tuple[list[dict], dict | None]:
    out = [dict(m) for m in messages]
    return out, next((m for m in reversed(out) if m["role"] == "user"), None)


def _images_openai(messages: list[dict], images) -> list[dict]:
    if not images:
        return messages
    out, last = _last_user(messages)
    if last is None:
        return messages
    parts = []
    for img in images:
        parts.append({"type": "text", "text": image_label(img)})
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img.jpeg}"}})
    parts.append({"type": "text", "text": last["content"]})
    last["content"] = parts
    return out


def _images_ollama(messages: list[dict], images) -> list[dict]:
    global _blind_told
    if not images:
        return messages
    out, last = _last_user(messages)
    if last is None:
        return messages
    if not _vision.get(local_model(), True):          # modelo de solo texto: mandarle imágenes da error
        if not _blind_told:
            _blind_told = True
            _notices.append(f"{local_model()} no ve imágenes: no puede mirar tu cámara ni tu pantalla. "
                            "Para eso elige Gemma 4 E2B o E4B, o el cerebro en la nube.")
        last["content"] = f"(No puedes ver lo que comparte: el modelo que usas ahora no ve imágenes. Si te pide mirar algo, díselo.)\n{last['content']}"
        return out
    notes = "\n".join(f"(Imagen adjunta {n}. {image_label(img)})" for n, img in enumerate(images, 1))
    last["content"] = f"{notes}\n{last['content']}"
    last["images"] = [img.jpeg for img in images]
    return out


# ------------------------------------------------------------------ Gemini
async def _gemini(model: str, messages: list[dict], sampling: dict) -> AsyncIterator[str]:
    body = {"model": model, "messages": messages, "stream": True,
            "temperature": sampling["temperature"], "top_p": sampling["top_p"],
            "max_tokens": sampling["max_tokens"] + 256}       # el razonamiento mínimo también gasta tokens
    if _is_gemini() and settings.gemini_reasoning and model not in _no_reasoning:
        body["reasoning_effort"] = settings.gemini_reasoning
    headers = {"Authorization": f"Bearer {settings.gemini_api_key}"}
    url = f"{settings.cloud_base}/chat/completions"

    for attempt in (1, 2):
        try:
            async with _client.stream("POST", url, json=body, headers=headers) as r:
                if r.status_code != 200:
                    detail = (await r.aread()).decode("utf-8", "replace")[:2500]
                    if attempt == 1 and r.status_code == 400 and any(w in detail.lower() for w in ("reasoning", "thinking")):
                        log.info("%s no admite reasoning_effort: se envía sin él", model)
                        _no_reasoning.add(model)
                        body.pop("reasoning_effort", None)
                        continue
                    if r.status_code == 429:
                        log.warning("Gemini 429 (%s): %s", model, detail[:700])
                        wait = re.search(r'"retryDelay":\s*"(\d+)', detail)
                        daily = "perday" in detail.lower()
                        raise QuotaExceeded(float(wait.group(1)) if wait else (12 * 3600 if daily else 60), daily)
                    if r.status_code in (500, 502, 503, 504) or "overloaded" in detail.lower() or "high demand" in detail.lower():
                        log.info("Nube %s (%s): saturado", r.status_code, model)
                        raise Overloaded(f"HTTP {r.status_code}")
                    raise LLMError(_gemini_error(r.status_code, detail, model))
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        choices = json.loads(data).get("choices") or []
                    except json.JSONDecodeError:
                        continue
                    piece = (choices[0].get("delta") or {}).get("content") if choices else None
                    if piece:
                        yield piece
                return
        except httpx.TimeoutException as e:
            raise Overloaded(type(e).__name__) from e        # ese modelo no contesta: el siguiente quizá sí
        except httpx.HTTPError as e:
            raise LLMError(f"No pude conectar con el cerebro en la nube ({type(e).__name__}). Revisa tu conexión a internet.") from e


def _gemini_error(code: int, detail: str, model: str) -> str:
    log.warning("Nube %s (%s): %s", code, model, detail[:700])
    if code in (401, 403) or "api key" in detail.lower():
        return "El proveedor rechazó la clave de API. Revísala en Ajustes › Cerebro."
    if code == 404:
        return f"El modelo «{model}» no existe o no está disponible para tu clave. Elige otro en Ajustes › Cerebro."
    return f"El cerebro en la nube devolvió un error ({code})."


async def check_cloud(base: str, key: str) -> list[str]:
    """Comprueba una clave contra la API del proveedor y devuelve los modelos que ofrece."""
    try:
        r = await _client.get(f"{base.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"}, timeout=15)
    except httpx.HTTPError as e:
        raise LLMError(f"No pude conectar con esa dirección ({type(e).__name__}).") from e
    if r.status_code in (400, 401, 403):
        raise LLMError("El proveedor rechazó la clave. Cópiala de nuevo, completa.")
    if r.status_code != 200:
        raise LLMError(f"El proveedor respondió {r.status_code} al comprobar la clave.")
    try:
        ids = [str(m.get("id", "")).removeprefix("models/") for m in r.json().get("data", [])]
    except (ValueError, AttributeError):
        ids = []
    return sorted(i for i in ids if i)[:400]


# ------------------------------------------------------------------ descarga de modelos locales
pulls: dict[str, dict] = {}               # modelo → {"status", "percent", "error"} mientras se descarga


async def pull_local(model: str):
    """Descarga un modelo con Ollama (lo pide el usuario desde la bienvenida) y va anotando el progreso."""
    pulls[model] = {"status": "Empezando…", "percent": 0, "error": ""}
    try:
        async with _local.stream("POST", f"{settings.ollama_url}/api/pull", json={"model": model, "stream": True},
                                 timeout=httpx.Timeout(None, connect=5)) as r:
            async for line in r.aiter_lines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("error"):
                    pulls[model]["error"] = str(d["error"])[:200]
                    return
                total, done = d.get("total") or 0, d.get("completed") or 0
                pulls[model].update(status=str(d.get("status", ""))[:60], percent=round(100 * done / total) if total else pulls[model]["percent"])
        pulls[model].update(status="success", percent=100)
        _local_sizes.clear()
    except httpx.HTTPError as e:
        pulls[model]["error"] = "Ollama no está abierto en esta PC." if isinstance(e, httpx.ConnectError) else f"Se cortó la descarga ({type(e).__name__})."


async def installed_local() -> dict | None:
    """Modelos que Ollama ya tiene: {nombre: tamaño en GB}. None si Ollama no responde."""
    data = await _ollama_json("/api/tags")
    if not data:
        return None
    return {m.get("name"): round(m.get("size", 0) / 1e9, 1) for m in data.get("models", [])}


# ------------------------------------------------------------------ Ollama
SLOW_TPS = 30          # por debajo de esto el modelo no está entero en la GPU (en ella va a más de 100 tokens/s;
                       # compartiéndola con la voz baja a 40-80, y desbordado a la RAM cae a 9-19)
SLOW_FOR = 600         # cada cuánto se repite el aviso de «GPU llena» si ya no queda un modelo más pequeño
_local_choice: str | None = None          # modelo local elegido; se decide al cargar y no cambia a mitad de la charla
_local_sizes: dict[str, int] = {}         # modelo → tamaño en disco (MB), para estimar cuánta memoria de vídeo pide
_slow_told = 0.0
_slow_turns = 0                           # turnos lentos seguidos


def local_models() -> list[str]:
    """El modelo elegido y, detrás, a cuáles pasar si va lento. Si es del catálogo, los más pequeños que ven lo
    mismo (12B → E4B → E2B); si no, los de OLLAMA_FALLBACK."""
    from .profile import LOCAL_MODELS
    chosen = settings.ollama_model
    ids = [m["id"] for m in LOCAL_MODELS]
    if chosen in ids:
        i = ids.index(chosen)
        vision = LOCAL_MODELS[i]["vision"]
        return [chosen, *[m["id"] for m in LOCAL_MODELS[i + 1:] if m["vision"] or not vision]]
    return [chosen, *[m for m in settings.ollama_fallback if m != chosen]]


def local_model() -> str:
    """El modelo local en uso (o el principal, si todavía no se ha elegido)."""
    return _local_choice or settings.ollama_model


async def _ollama_json(path: str) -> dict:
    try:
        r = await _local.get(f"{settings.ollama_url}{path}", timeout=5)
        return r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {}


async def choose_local() -> str:
    """Elige el modelo local más capaz que cabe AHORA en la memoria de vídeo y deja cargado solo ese.
    Tener dos a la vez, o volver a probar el grande a mitad de la conversación, provoca pausas de varios segundos."""
    global _local_choice
    models = local_models()
    loaded = {m.get("name"): m for m in (await _ollama_json("/api/ps")).get("models", [])}
    if not _local_sizes:
        _local_sizes.update({m.get("name"): int(m.get("size", 0) / 2**20) for m in (await _ollama_json("/api/tags")).get("models", [])})
    gpu = await asyncio.to_thread(gpu_memory)
    # Manda el modelo que eligió el usuario. Antes, si «no cabía» según la memoria libre, se cargaba otro más
    # pequeño sin decir nada y la elección parecía no tener efecto (12 nov 2026). Ahora se carga el elegido y se
    # avisa; si luego responde lento de verdad, _too_slow pasa al siguiente y también lo dice.
    choice = models[0]
    _ours.update(models)
    if gpu is not None:
        ours = sum(int(m.get("size_vram", 0) / 2**20) for name, m in loaded.items() if name in _ours)   # se libera al cambiar
        free = gpu["total"] - gpu["used"] + ours
        need = need_mb(choice)
        log.info("Memoria de vídeo libre para el modelo local: %d MB · %s pide ~%d MB", free, choice, need)
        if free < need and choice not in loaded:
            gb = lambda mb: f"{max(0, mb) / 1024:.1f}".replace(".", ",")  # noqa: E731
            _notices.append(f"{choice} pide unos {gb(need)} GB de memoria de vídeo y ahora hay {gb(free)} GB libres: "
                            "puede responder lento. Si pasa, cambiaré a un modelo más pequeño.")
    await unload_local([m for m in loaded if m in _ours and m != choice])
    _local_choice = choice
    await _learn_vision(choice)
    return choice


_ours: set[str] = set()                   # modelos que este companion ha cargado (solo esos se descargan de la GPU)
_vision: dict[str, bool] = {}             # modelo → ¿ve imágenes?
_blind_told = False


def need_mb(model: str) -> int:
    """Memoria de vídeo que pide un modelo local: la medida si es del catálogo; si no, se estima por su tamaño."""
    from .profile import LOCAL_MODELS
    known = next((m["vram_gb"] for m in LOCAL_MODELS if m["id"] == model), None)
    return int(known * 1024) if known else int(_local_sizes.get(model, 6000) * 1.2) + 1000


async def _learn_vision(model: str):
    if model not in _vision:
        try:
            r = await _local.post(f"{settings.ollama_url}/api/show", json={"model": model}, timeout=5)
            _vision[model] = "vision" in (r.json().get("capabilities") or [])
        except (httpx.HTTPError, ValueError):
            pass


def can_act() -> bool:
    """¿El cerebro en uso pide acciones con fiabilidad? Los modelos locales más pequeños se equivocan demasiado
    (inventan acciones o datos), así que con ellos las acciones en la PC quedan apagadas."""
    if settings.is_cloud:
        return True
    from .profile import LOCAL_MODELS
    return next((m.get("actions", True) for m in LOCAL_MODELS if m["id"] == local_model()), True)


def can_control() -> bool:
    """¿Puede manejar una ventana paso a paso? Gemma 4 E2B se atasca repitiendo pasos (probado el 13 nov 2026):
    hace falta E4B, un modelo local más grande o la nube. Solo en Windows (companion/control.py)."""
    if sys.platform != "win32" or not can_act():
        return False
    if settings.is_cloud:
        return True
    from .profile import LOCAL_MODELS
    return next((m.get("control", True) for m in LOCAL_MODELS if m["id"] == local_model()), True)


def sees_images() -> bool:
    """¿El cerebro en uso ve imágenes? (los modelos locales más pequeños solo leen texto)"""
    return settings.is_cloud or _vision.get(local_model(), True)


def _mac_memory() -> dict | None:
    """Mac con Apple Silicon: la GPU comparte la memoria con todo lo demás. macOS deja a la GPU unos dos tercios
    (tres cuartos desde 36 GB): ese es el «total»; lo «libre» es lo que la memoria del sistema tiene disponible."""
    try:
        ram = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=4).stdout)
        vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=4).stdout
        page = int(re.search(r"page size of (\d+)", vm).group(1))
        pages = {k.strip().lower(): int(v) for k, v in re.findall(r"^([^:\n]+):\s+(\d+)\.?$", vm, re.M)}
        free = sum(pages.get(k, 0) for k in ("pages free", "pages inactive", "pages speculative", "pages purgeable")) * page
        total = ram * (0.75 if ram >= 36 * 2**30 else 0.67)
        return {"used": int(max(0.0, total - free) / 2**20), "total": int(total / 2**20)}
    except Exception:  # noqa: BLE001
        return None


def gpu_memory() -> dict | None:
    """Memoria de vídeo en uso y total, en MB (None sin tarjeta NVIDIA ni Mac con Apple Silicon)."""
    if sys.platform == "darwin":
        return _mac_memory()
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=4, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        used, total = (int(x) for x in out.stdout.strip().splitlines()[0].split(","))
        return {"used": used, "total": total}
    except Exception:  # noqa: BLE001
        return None


def _gpu_text() -> str:
    g = gpu_memory()
    return f" ({g['used'] / 1024:.1f} de {g['total'] / 1024:.1f} GB en uso)".replace(".", ",") if g else ""


def _options(sampling: dict | None = None) -> dict:
    opts = {"num_ctx": settings.ollama_num_ctx}          # siempre el mismo: si cambia, Ollama recarga el modelo
    if sampling:
        opts.update(temperature=sampling["temperature"], top_p=sampling["top_p"], top_k=64,     # top_k: el que recomienda Gemma
                    num_predict=sampling["max_tokens"], repeat_penalty=1.1)
    return opts


async def _too_slow(model: str, why: str):
    """El modelo no cabe en la memoria de vídeo: se pasa al siguiente, más pequeño, y ahí se queda hasta que
    se reinicie el companion o se vuelva a elegir «Local» en Ajustes (eso repite la elección)."""
    global _slow_told, _local_choice
    if await _free_voice(model):
        return
    models = local_models()
    smaller = [m for m in models[models.index(model) + 1:] if not _local_sizes or m in _local_sizes] if model in models else []
    last = not smaller                    # solo cuentan los que están descargados
    nxt = model if last else smaller[0]
    gpu = await asyncio.to_thread(_gpu_text)
    log.warning("Modelo local %s lento (%s)%s; sigue: %s", model, why, gpu, nxt)
    if not last:
        _local_choice = nxt
        _notices.append(f"La memoria de vídeo está llena{gpu}: {model} no cabe y responde muy lento. "
                        f"Sigo con {nxt}, que es más pequeño.")
        _keep(asyncio.create_task(_swap(model, nxt)))
    elif time.time() - _slow_told > SLOW_FOR:
        _slow_told = time.time()
        _notices.append(f"La memoria está llena{gpu} y el modelo local responde lento. Cierra otras aplicaciones "
                        "que usen mucha memoria, o usa el cerebro en la nube desde Ajustes." if sys.platform == "darwin" else
                        f"La memoria de vídeo está llena{gpu} y el modelo local responde lento. Cierra el juego u otro "
                        "programa que use la tarjeta gráfica, o usa el cerebro en la nube desde Ajustes.")


async def _free_voice(model: str) -> bool:
    """Antes de bajar a un modelo más pequeño: si suena la voz completa y el usuario dejó el cambio automático,
    se pasa a la ligera (no usa la tarjeta) y el modelo se vuelve a cargar con esa memoria libre."""
    from . import profile, voz_proc
    if settings.voice_engine != "completa" or profile._squeezed:
        return False
    profile.squeeze()
    profile.apply()
    if settings.voice_engine != "ligera":
        return False                      # cambio automático apagado o voz ligera sin descargar
    await asyncio.to_thread(voz_proc.stop)
    log.warning("Modelo local %s sin memoria de vídeo: paso a la voz ligera", model)
    _notices.append("La memoria de vídeo se llenó: paso a la voz ligera (no usa la tarjeta) para que el modelo local "
                    "quepa. Al volver a la nube, o al elegir otra vez el modelo en Ajustes, vuelve la voz completa.")
    _keep(asyncio.create_task(_swap(model, model)))
    return True


_bg: set = set()


def _keep(task):
    _bg.add(task)
    task.add_done_callback(_bg.discard)


async def _swap(old: str, new: str):
    await unload_local([old])
    await warm_local(new)


warming: dict = {}                        # {"model", "state": cargando|listo|error} (pantalla de carga)


async def warm_local(model: str | None = None):
    """Carga el modelo local en la GPU antes del primer turno, para que no se note la espera.
    Sin `model`, primero elige el que cabe ahora."""
    warming.update(model=model or settings.ollama_model, state="cargando")
    try:
        model = model or await choose_local()
        warming["model"] = model
        _ours.add(model)
        await _learn_vision(model)
        r = await _local.post(f"{settings.ollama_url}/api/generate",
                              json={"model": model, "keep_alive": settings.ollama_keep_alive, "options": _options()})
        log.info("Modelo local %s %s", model, "cargado" if r.status_code == 200 else f"no cargó ({r.status_code}: {r.text[:200]})")
        warming["state"] = "listo" if r.status_code == 200 else "error"
    except httpx.HTTPError as e:
        log.warning("No pude precargar %s: %s", model, type(e).__name__)
        warming["state"] = "error"
    except Exception:  # noqa: BLE001
        warming["state"] = "error"
        raise


async def prime_local(messages: list[dict]) -> bool:
    """Hace que el modelo local lea ya un prompt nuevo (p. ej. tras cambiar de personalidad): Ollama guarda lo leído
    y el siguiente turno, que empieza igual, solo lee lo nuevo. Sin esto, la primera respuesta tras el cambio tenía que
    leer otra vez todo el prompt (con el 12B y un juego abierto, varios segundos). Solo con el cerebro local y el modelo
    ya cargado; genera un único token."""
    if settings.is_cloud or not _local_choice:
        return False
    body = {"model": _local_choice, "messages": messages, "stream": False, "think": False,
            "keep_alive": settings.ollama_keep_alive, "options": {**_options(), "num_predict": 1}}
    try:
        r = await _local.post(f"{settings.ollama_url}/api/chat", json=body, timeout=60)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


async def unload_local(models: list[str] | None = None):
    """Saca de la GPU los modelos locales del companion (al volver a la nube o al cerrar)."""
    global _local_choice
    if models is None:
        models, _local_choice = list(_ours | set(local_models())), None
    for model in models:
        try:
            await _local.post(f"{settings.ollama_url}/api/generate", json={"model": model, "keep_alive": 0}, timeout=10)
        except httpx.HTTPError:
            pass


async def _ollama(messages: list[dict], sampling: dict, model: str | None = None, cpu: bool = False) -> AsyncIterator[str]:
    """`model` y `cpu` solo los pasa el respaldo de la nube (ver _fallback_place)."""
    global _fallback_loaded
    fallback = model is not None
    model = model or _local_choice or await choose_local()
    opts = _options(sampling)
    if cpu:
        opts["num_gpu"] = 0                # ninguna capa en la tarjeta
    body = {"model": model, "messages": messages, "stream": True, "think": False,
            "keep_alive": "5m" if fallback else settings.ollama_keep_alive, "options": opts}
    if fallback:
        _fallback_loaded = True
    for attempt in (1, 2):
        spoke = False
        try:
            async with _local.stream("POST", f"{settings.ollama_url}/api/chat", json=body) as r:
                if r.status_code != 200:
                    detail = (await r.aread()).decode("utf-8", "replace")[:300]
                    log.warning("Ollama %s (%s): %s", r.status_code, model, detail)
                    if r.status_code == 404 or "not found" in detail.lower():
                        raise LLMError(f"El modelo local «{model}» no está descargado. Descárgalo con: ollama pull {model}")
                    if attempt == 1 and r.status_code >= 500:
                        await asyncio.sleep(1.5)          # el motor se cayó (casi siempre por memoria): Ollama lo relanza
                        continue
                    if not cpu:
                        await _too_slow(model, f"error {r.status_code}")
                    raise LLMError("El modelo local se detuvo, casi seguro por falta de memoria de vídeo. Vuelve a intentarlo.")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("error"):
                        log.warning("Ollama (%s) cortó la respuesta: %s", model, str(data["error"])[:300])
                        raise LLMError("El modelo local se detuvo a mitad de la respuesta. Vuelve a intentarlo.")
                    piece = (data.get("message") or {}).get("content")
                    if piece:
                        spoke = True
                        yield piece
                    if data.get("done"):
                        if not cpu:               # en el procesador ya se sabe que va lento
                            await _measure(model, data)
                        return
                return
        except httpx.ConnectError as e:
            raise LLMError("Ollama no está abierto en esta PC. Ábrelo desde el menú Inicio y vuelve a intentarlo.") from e
        except httpx.TimeoutException as e:
            if not cpu:
                await _too_slow(model, f"sin respuesta en {settings.ollama_timeout:.0f} s")
            raise LLMError("El modelo local tardó demasiado en responder: la memoria de vídeo está llena. "
                           "Vuelve a intentarlo o usa el cerebro en la nube.") from e
        except httpx.HTTPError as e:
            if attempt == 1 and not spoke:
                await asyncio.sleep(1.0)
                continue
            raise LLMError(f"Se cortó la conexión con Ollama ({type(e).__name__}). Vuelve a intentarlo.") from e


_best_tps: dict[str, float] = {}          # Mac: la mejor velocidad vista de cada modelo en esta sesión


def slow_limit(model: str, tps: float) -> float:
    """Por debajo de cuántos tokens/s el turno cuenta como lento. PC: SLOW_TPS fijo (en la tarjeta va a más de
    100; desbordado a la RAM cae a 9-19). Mac: no hay desborde (la memoria es una sola) y la velocidad normal depende
    del chip: un 12B va a 59 en un M5 Pro y a ~20 en un M1. Ahí es lento si cae a menos de la mitad de lo mejor que
    ha ido ese modelo (la memoria se llenó y macOS tira del disco); el primer turno nunca lo es."""
    if sys.platform != "darwin":
        return SLOW_TPS
    best = max(_best_tps.get(model, 0.0), tps)
    _best_tps[model] = best
    return best * 0.45


async def _measure(model: str, done: dict):
    """Velocidad real del turno. Si es muy baja, el modelo no está entero en la GPU."""
    n, ns = done.get("eval_count") or 0, done.get("eval_duration") or 0
    tps = n / (ns / 1e9) if ns else 0.0
    log.info("Local %s: carga %.1fs · prompt %s tokens en %.2fs · %s tokens a %.0f por segundo", model,
             (done.get("load_duration") or 0) / 1e9, done.get("prompt_eval_count"), (done.get("prompt_eval_duration") or 0) / 1e9, n, tps)
    # Un turno lento suelto puede ser otra cosa usando la GPU un momento; dos seguidos (o uno muy lento) es
    # que el modelo ya no cabe en la memoria de vídeo.
    global _slow_turns
    if n >= 12:
        limit = slow_limit(model, tps)
        _slow_turns = _slow_turns + 1 if tps < limit else 0
        if _slow_turns >= 2 or tps < limit / 2:
            _slow_turns = 0
            await _too_slow(model, f"{tps:.0f} tokens por segundo")
