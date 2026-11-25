"""Voz ligera: Piper (https://github.com/OHF-Voice/piper1-gpl) dentro del propio companion. Corre en el
procesador, no usa memoria de vídeo y va mucho más rápido que en tiempo real, así que sirve en PC sin tarjeta
gráfica o con poca. No clona: cada voz del catálogo usa aquí un modelo de Piper con el tono cambiado
(`light` en voices.json), así que suena distinta de la voz completa y más sintética.

Los modelos (~380 MB entre los cinco) se descargan a models/piper desde huggingface.co/rhasspy/piper-voices
cuando el usuario elige la voz ligera.
"""
import asyncio
from collections import OrderedDict
import json
import logging
import threading
from typing import AsyncIterator

import httpx
import numpy as np

from .config import ROOT

log = logging.getLogger("companion.tts")
SAMPLE_RATE = 24000
DIR = ROOT / "models" / "piper"
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
PATHS = {                                 # modelo → carpeta en el repositorio · tamaño en MB
    "es_MX-claude-high": ("es/es_MX/claude/high", 63),
    "es_AR-daniela-high": ("es/es_AR/daniela/high", 114),
    "es_ES-sharvard-medium": ("es/es_ES/sharvard/medium", 77),
    "es_ES-davefx-medium": ("es/es_ES/davefx/medium", 63),
    "es_MX-ald-medium": ("es/es_MX/ald/medium", 63),
}
SIZE_MB = sum(mb for _, mb in PATHS.values())
progress: dict = {}                       # {"status", "percent", "error"} mientras se descargan
_voices: OrderedDict = OrderedDict()      # modelo → PiperVoice ya cargado (LRU máx 2 en RAM)
_synth_lock = threading.Lock()
_specs: tuple = (0, {})


def specs() -> dict:
    """tts_voice → {"model", "speaker", "pitch", "speed"} según voices.json y las voces propias."""
    global _specs
    path = ROOT / "voices.json"
    try:
        stamp = path.stat().st_mtime_ns
        if stamp != _specs[0]:
            data = json.loads(path.read_text(encoding="utf-8"))["voices"]
            _specs = (stamp, {v["tts_voice"]: v["light"] for v in data if isinstance(v.get("light"), dict)})
    except (OSError, ValueError, KeyError):
        pass
    from . import voice_import
    own = {v["tts_voice"]: v["light"] for v in voice_import.custom() if isinstance(v.get("light"), dict)}
    return {**_specs[1], **own} if own else _specs[1]


def missing() -> list[str]:
    return [m for m in PATHS if not ((DIR / f"{m}.onnx").is_file() and (DIR / f"{m}.onnx.json").is_file())]


def installed() -> bool:
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return not missing()


async def install():
    """Descarga los modelos que falten (lo pide el usuario al elegir la voz ligera)."""
    if progress.get("status") == "descargando":
        return
    progress.update(status="descargando", percent=0, error="")
    todo = missing()
    total, done = sum(PATHS[m][1] for m in todo) * 2**20 or 1, 0
    DIR.mkdir(parents=True, exist_ok=True)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10), follow_redirects=True) as client:
            for model in todo:
                for ext in (".onnx.json", ".onnx"):
                    part = DIR / f"{model}{ext}.part"
                    async with client.stream("GET", f"{HF}{PATHS[model][0]}/{model}{ext}") as r:
                        r.raise_for_status()
                        with open(part, "wb") as f:
                            async for chunk in r.aiter_bytes(1 << 16):
                                f.write(chunk)
                                done += len(chunk)
                                progress["percent"] = min(99, round(100 * done / total))
                    part.replace(DIR / f"{model}{ext}")
        progress.update(status="lista", percent=100)
    except (httpx.HTTPError, OSError) as e:
        log.warning("No pude descargar la voz ligera: %s", e)
        progress.update(status="", error=f"Se cortó la descarga ({type(e).__name__}). Vuelve a intentarlo.")


def _synth(text: str, spec: dict, speed: float) -> bytes:
    from piper import PiperVoice, SynthesisConfig
    model = spec["model"]
    with _synth_lock:
        if model in _voices:
            _voices.move_to_end(model)
        else:
            while len(_voices) >= 2:
                _voices.popitem(last=False)
            _voices[model] = PiperVoice.load(DIR / f"{model}.onnx")
        voice_obj = _voices[model]
        pitch = float(spec.get("pitch", 1.0))
        cfg = SynthesisConfig(speaker_id=spec.get("speaker"), length_scale=pitch / (float(spec.get("speed", 1.0)) * speed))
        parts, sr = [], SAMPLE_RATE
        for chunk in voice_obj.synthesize(text, syn_config=cfg):
            parts.append(chunk.audio_int16_array.astype(np.float32))
            sr = chunk.sample_rate
            parts.append(np.zeros(int(sr * 0.12 * pitch), dtype=np.float32))
    if not parts:
        return b""
    x = np.concatenate(parts[:-1])
    n = max(1, int(len(x) / pitch * SAMPLE_RATE / sr))
    y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return np.clip(y, -32768, 32767).astype(np.int16).tobytes()


async def stream_speech(text: str, voice: str, speed: float = 1.0) -> AsyncIterator[bytes]:
    """PCM de 16 bits mono a 24 kHz, igual que el nodo de voz."""
    from .tts import TTSError
    spec = specs().get(voice) or next(iter(specs().values()), None)
    if spec is None or not installed():
        raise TTSError("La voz ligera no está instalada. Descárgala en Ajustes › Voz.")
    try:
        pcm = await asyncio.to_thread(_synth, text[:1500], spec, min(1.3, max(0.7, speed)))
    except Exception as e:  # noqa: BLE001
        raise TTSError(f"La voz ligera falló ({type(e).__name__})") from e
    step = SAMPLE_RATE // 2 * 2
    for i in range(0, len(pcm), step):
        yield pcm[i:i + step]
