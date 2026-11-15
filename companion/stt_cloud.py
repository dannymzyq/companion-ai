"""Oído en la nube (15 nov 2026): transcribe lo que dice el usuario sin cargar Whisper en esta PC (ni memoria de
vídeo ni ~1,5 GB de RAM). Proveedores, de más a menos uso gratuito:
  1. Groq (whisper-large-v3-turbo): unas 2.000 frases y 8 horas de audio al día gratis, con una clave propia y
     gratuita de console.groq.com. Es el mismo modelo que el oído local.
  2. Gemini (EAR_GEMINI_MODELS) con la clave del cerebro: sin clave nueva, pero con la cuota diaria de cada modelo
     (unas cientos en Flash-Lite), que comparte con el relevo de la conversación.
Si un proveedor responde que se acabó la cuota (429) se descansa de él un rato y se pasa al siguiente. Si no
queda ninguno, Transcriber vuelve al Whisper local en el procesador.
El audio va a internet: por eso es una opción aparte, nunca la de por defecto."""
import base64
import io
import logging
import os
import time
import wave

import httpx
import numpy as np

from . import state
from .config import settings

log = logging.getLogger("companion.stt")
GROQ_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = os.getenv("EAR_GROQ_MODEL", "whisper-large-v3-turbo").strip()
GEMINI_MODELS = [m.strip() for m in os.getenv("EAR_GEMINI_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite").split(",") if m.strip()]
GEMINI_PROMPT = ("Transcribe literalmente lo que dice la persona en este audio, en {lang}, con su puntuación. "
                 "Responde solo con la transcripción, sin comillas ni comentarios. Si no se oye a nadie hablar, "
                 "responde exactamente: (silencio)")
_client = httpx.Client(timeout=httpx.Timeout(20, connect=5))
_rest: dict[str, float] = {}              # proveedor → hasta cuándo no se usa (se acabó su cuota)
last: dict = {}                           # el último proveedor que respondió y cuánto tardó (para el estado)


class CloudEarError(Exception):
    pass


def groq_key() -> str:
    return str((state.load().get("ear") or {}).get("groq_key") or "").strip()


def gemini_key() -> str:
    """La clave del cerebro sirve si el proveedor es Gemini."""
    return settings.gemini_api_key if settings.cloud_preset == "gemini" else ""


def available() -> bool:
    return bool(groq_key() or gemini_key())


def wav16(audio: np.ndarray) -> bytes:
    """float32 mono a 16 kHz → WAV de 16 bits."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _resting(name: str) -> bool:
    return _rest.get(name, 0.0) > time.monotonic()


def _rest_after(name: str, r: httpx.Response):
    try:
        wait = float(r.headers.get("retry-after") or 0)
    except ValueError:
        wait = 0.0
    _rest[name] = time.monotonic() + max(60.0, min(wait, 6 * 3600.0) or 600.0)
    log.warning("El oído en la nube (%s) agotó su cuota: descanso %d min", name, round((_rest[name] - time.monotonic()) / 60))


def _groq(wav: bytes, language: str, hint: str) -> str:
    data = {"model": GROQ_MODEL, "response_format": "verbose_json", "temperature": "0"}
    if language:
        data["language"] = language
    if hint:
        data["prompt"] = hint[:400]
    r = _client.post(f"{GROQ_URL}/audio/transcriptions", headers={"Authorization": f"Bearer {groq_key()}"},
                     data=data, files={"file": ("voz.wav", wav, "audio/wav")})
    if r.status_code == 429:
        _rest_after("groq", r)
        raise CloudEarError("Groq: cuota agotada")
    if r.status_code != 200:
        raise CloudEarError(f"Groq respondió {r.status_code}")
    out = r.json()
    segs = out.get("segments")
    if isinstance(segs, list):            # se quitan los tramos que Whisper inventa sobre silencio, como en local
        return " ".join(str(s.get("text", "")).strip() for s in segs
                        if not (s.get("no_speech_prob", 0) > 0.6 and s.get("avg_logprob", 0) < -0.8)).strip()
    return str(out.get("text") or "").strip()


def _gemini(model: str, wav: bytes, language: str) -> str:
    lang = {"es": "español", "en": "inglés"}.get(language, "el idioma en que hable")
    body = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": [
        {"type": "text", "text": GEMINI_PROMPT.format(lang=lang)},
        {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}}]}]}
    r = _client.post(f"{settings.gemini_base}/chat/completions", json=body,
                     headers={"Authorization": f"Bearer {gemini_key()}"})
    if r.status_code == 429:
        _rest_after(model, r)
        raise CloudEarError(f"{model}: cuota agotada")
    if r.status_code != 200:
        raise CloudEarError(f"{model} respondió {r.status_code}")
    text = str(r.json()["choices"][0]["message"].get("content") or "").strip().strip('"«»')
    return "" if "(silencio)" in text.lower() else text


def transcribe(audio: np.ndarray, language: str = "es", hint: str = "") -> str:
    """Texto de lo que se oye ('' si no hay habla). CloudEarError si ningún proveedor pudo."""
    wav = wav16(audio)
    tries = []
    if groq_key() and not _resting("groq"):
        tries.append(("groq", lambda: _groq(wav, language, hint)))
    if gemini_key():
        tries += [(m, lambda m=m: _gemini(m, wav, language)) for m in GEMINI_MODELS if not _resting(m)]
    if not tries:
        raise CloudEarError("no hay ningún proveedor del oído en la nube disponible (falta la clave o se acabó la cuota)")
    errors = []
    for name, call in tries:
        t = time.perf_counter()
        try:
            text = call()
            last.update(provider=name, seconds=round(time.perf_counter() - t, 2))
            return text
        except CloudEarError as e:
            errors.append(str(e))
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
            errors.append(f"{name}: {type(e).__name__}")
    raise CloudEarError("; ".join(errors))


async def check_groq(key: str) -> bool:
    """¿La clave de Groq vale? (lista sus modelos; no gasta cuota del oído)"""
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.get(f"{GROQ_URL}/models", headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as e:
            raise CloudEarError(f"No pude conectar con Groq ({type(e).__name__}).") from e
    if r.status_code in (401, 403):
        return False
    if r.status_code != 200:
        raise CloudEarError(f"Groq respondió {r.status_code}.")
    return True
