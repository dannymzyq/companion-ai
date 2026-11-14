"""Voz. Dos motores: «completa» = cliente del nodo GPU de waifuv3 (POST /v1/audio/speech, contrato 1.6, PCM en
streaming; voces clonadas, ~5 GB de vídeo) y «ligera» = Piper en el procesador (tts_light.py)."""
import logging
from typing import AsyncIterator

import httpx

from .config import settings

log = logging.getLogger("companion.tts")
SAMPLE_RATE = 24000
_client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5))


class TTSError(Exception):
    pass


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.tts_token}"} if settings.tts_token else {}   # el servidor propio no pide token


async def node_available() -> bool:
    """¿Responde el nodo de voz de waifuv3 (la voz completa)?"""
    try:
        r = await _client.get(f"{settings.tts_url}/health", headers=_headers(), timeout=3)
        data = r.json()                    # «loading»: recién arrancado, todavía cargando el modelo
        return r.status_code == 200 and (data.get("tts", "none") != "none" or bool(data.get("loading")))
    except (httpx.HTTPError, ValueError):
        return False


async def available() -> bool:
    """¿Hay voz con el motor elegido? (ligera: Piper aquí mismo · completa: el nodo de waifuv3)"""
    if settings.voice_engine == "ligera":
        from . import tts_light
        return tts_light.installed()
    return await node_available()


async def stream_speech(text: str, voice: str, speed: float = 1.0, engine: str | None = None) -> AsyncIterator[bytes]:
    """Devuelve PCM de 16 bits mono a 24 kHz en trozos, siempre con un número par de bytes."""
    from .pronounce import for_voice
    text = for_voice(text)                 # «Apple Music» → como se pronuncia; «qué» → «ké» (solo para la voz)
    if (engine or settings.voice_engine) == "ligera":
        from . import tts_light
        async for chunk in tts_light.stream_speech(text, voice, speed):
            yield chunk
        return
    body = {"model": "local", "input": text[:1500], "voice": voice, "response_format": "pcm",
            "stream": True, "speed": speed}
    carry = b""
    try:
        async with _client.stream("POST", f"{settings.tts_url}/v1/audio/speech", json=body, headers=_headers()) as r:
            if r.status_code != 200:
                detail = (await r.aread()).decode("utf-8", "replace")[:200]
                raise TTSError(f"El nodo de voz respondió {r.status_code}: {detail}")
            async for chunk in r.aiter_bytes():
                data = carry + chunk
                cut = len(data) - (len(data) % 2)
                carry = data[cut:]
                if cut:
                    yield data[:cut]
    except httpx.HTTPError as e:
        raise TTSError(f"No hay conexión con el nodo de voz ({type(e).__name__})") from e
