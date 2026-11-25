"""Voz. Dos motores: «completa» = servidor de voz propio (voz/servidor.py, F5-TTS con voces clonadas; POST
/v1/audio/speech, PCM en streaming) y «ligera» = Piper en el procesador (tts_light.py)."""
import logging
from typing import AsyncIterator

import httpx

from .config import settings

log = logging.getLogger("companion.tts")
SAMPLE_RATE = 24000
_client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5))


class TTSError(Exception):
    pass


class _NotReady(Exception):
    """El servidor de voz todavía carga o no responde: merece esperar y repetir."""


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.tts_token}"} if settings.tts_token else {}   # el servidor propio no pide token


async def node_available() -> bool:
    """¿Responde el servidor de la voz completa?"""
    try:
        r = await _client.get(f"{settings.tts_url}/health", headers=_headers(), timeout=3)
        data = r.json()                    # «loading»: recién arrancado, todavía cargando el modelo
        return r.status_code == 200 and (data.get("tts", "none") != "none" or bool(data.get("loading")))
    except (httpx.HTTPError, ValueError):
        return False


async def available() -> bool:
    """¿Hay voz con el motor elegido? (ligera: Piper · kokoro: Kokoro CPU · nube: edge-tts · completa: F5)"""
    if settings.voice_engine == "nube":
        from . import tts_cloud
        return tts_cloud.installed()
    if settings.voice_engine == "kokoro":
        from . import tts_kokoro, tts_light
        return tts_kokoro.installed() or tts_light.installed()
    if settings.voice_engine == "ligera":
        from . import tts_light
        return tts_light.installed()
    return await node_available()


async def stream_speech(text: str, voice: str, speed: float = 1.0, engine: str | None = None) -> AsyncIterator[bytes]:
    """Devuelve PCM de 16 bits mono a 24 kHz en trozos, siempre con un número par de bytes."""
    engine = engine or settings.voice_engine
    if engine == "nube":                  # las voces neuronales leen bien el español y el inglés tal cual
        async for chunk in _with_light_backup(_cloud(text, voice, speed), text, voice, speed, "en la nube"):
            yield chunk
        return
    if engine == "kokoro":
        from . import tts_kokoro
        from .pronounce import for_voice
        async for chunk in _with_light_backup(tts_kokoro.stream_speech(for_voice(text), voice, speed),
                                              for_voice(text), voice, speed, "Kokoro"):
            yield chunk
        return
    from .pronounce import for_voice
    text = for_voice(text)                 # «Apple Music» → como se pronuncia; «qué» → «ké» (solo para la voz)
    if engine == "ligera":
        from . import tts_light
        async for chunk in tts_light.stream_speech(text, voice, speed):
            yield chunk
        return
    body = {"model": "local", "input": text[:1500], "voice": voice, "response_format": "pcm",
            "stream": True, "speed": speed}
    async for chunk in _with_light_backup(_full_with_retry(body), text, voice, speed, "completa"):
        yield chunk


async def _cloud(text: str, voice: str, speed: float) -> AsyncIterator[bytes]:
    from . import tts_cloud
    async for chunk in tts_cloud.stream_speech(text, voice, speed):
        yield chunk


async def _with_light_backup(source: AsyncIterator[bytes], text: str, voice: str, speed: float,
                             which: str) -> AsyncIterator[bytes]:
    """Si la voz completa no pudo cargar (p. ej. PyTorch no ve la tarjeta) o la de la nube no responde (sin
    internet), la frase suena con la ligera en vez de quedarse muda. Si ya sonó algo, no se mezclan las dos voces."""
    sent = False
    try:
        async for chunk in source:
            sent = True
            yield chunk
    except TTSError as e:
        from . import tts_light
        if sent or not tts_light.installed():
            raise
        log.warning("La voz %s no está disponible (%s): esta frase va con la ligera", which, e)
        async for chunk in tts_light.stream_speech(text, voice, speed):
            yield chunk


async def _full_with_retry(body: dict) -> AsyncIterator[bytes]:
    for attempt in (1, 2):
        sent = False
        try:
            async for chunk in _full(body):
                sent = True
                yield chunk
            return
        except _NotReady as e:
            # Recién arrancado, el servidor de voz tarda unos segundos en cargar; si se cayó, se vuelve a levantar.
            # Antes la frase (a menudo el saludo) se quedaba sin voz.
            from . import voz_proc
            if sent or attempt == 2:
                raise TTSError(str(e)) from None
            log.info("La voz no está lista (%s): espero a que cargue", e)
            if not await voz_proc.recover():
                raise TTSError(str(e)) from None


async def _full(body: dict) -> AsyncIterator[bytes]:
    carry = b""
    try:
        async with _client.stream("POST", f"{settings.tts_url}/v1/audio/speech", json=body, headers=_headers()) as r:
            if r.status_code != 200:
                detail = (await r.aread()).decode("utf-8", "replace")[:200]
                if r.status_code == 503:
                    raise _NotReady(f"el servidor de voz respondió 503: {detail}")
                raise TTSError(f"El servidor de voz respondió {r.status_code}: {detail}")
            async for chunk in r.aiter_bytes():
                data = carry + chunk
                cut = len(data) - (len(data) % 2)
                carry = data[cut:]
                if cut:
                    yield data[:cut]
    except httpx.ConnectError as e:
        raise _NotReady(f"no hay conexión con el servidor de voz ({type(e).__name__})") from e
    except httpx.HTTPError as e:
        raise TTSError(f"Se cortó la conexión con el servidor de voz ({type(e).__name__})") from e
