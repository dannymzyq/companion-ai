"""Motor de voz local equilibrado: Kokoro-82M (Apache 2.0, ~330 MB en CPU, 0 GB de memoria de vídeo).

Ofrece una alternativa intermedia muy natural entre la voz completa (F5-TTS en GPU, ~1.1 GB VRAM) y la voz ligera
de Piper (0 GB VRAM pero más sintética). Si `kokoro_onnx` está disponible o sus archivos viven en `models/kokoro`,
sintetiza directamente en CPU a 24 kHz; si todavía no se descargaron, permite descargarlos bajo demanda y, mientras
tanto, cae con elegancia a la voz ligera si esta está instalada.
"""
import asyncio
import hashlib
import importlib.util
import logging
import threading
from pathlib import Path
from typing import AsyncIterator

import httpx
import numpy as np

from .config import ROOT

log = logging.getLogger("companion.tts")
SAMPLE_RATE = 24000
DIR = ROOT / "models" / "kokoro"
MODEL_FILE = DIR / "kokoro-v1.0.onnx"
VOICES_FILE = DIR / "voices-v1.0.bin"
SIZE_MB = 345
RELEASE_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
# (dirección, MB aproximados, SHA-256). Sumas calculadas el 24 nov 2026 sobre la descarga de ese Release: si el
# archivo llega distinto (cortado o cambiado), no se usa.
FILES = {
    "kokoro-v1.0.onnx": (f"{RELEASE_BASE}kokoro-v1.0.onnx", 310,
                         "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"),
    "voices-v1.0.bin": (f"{RELEASE_BASE}voices-v1.0.bin", 27,
                        "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
}

# Mapeo de las voces del catálogo a voces en español de Kokoro v1.0 (ef_dora, em_alex, em_santa) + ajuste de velocidad/tono.
VOICE_MAP = {
    "mika_es": ("ef_dora", 1.02, 1.0),
    "natsumi_es": ("ef_dora", 1.06, 1.08),
    "ayaka_es": ("ef_dora", 1.03, 1.05),
    "chiaki_es": ("ef_dora", 0.98, 0.97),
    "kenji_es": ("em_alex", 1.0, 0.98),
    "akira_es": ("em_alex", 1.04, 1.02),
    "goro_es": ("em_santa", 0.95, 0.96),
    "ryo_es": ("em_alex", 0.96, 0.94),
    "satoshi_es": ("em_santa", 0.93, 0.90),
}

progress: dict = {}
_lock = threading.Lock()
_engine = None


def runtime_supported() -> bool:
    return importlib.util.find_spec("kokoro_onnx") is not None


def files_present() -> bool:
    return MODEL_FILE.is_file() and VOICES_FILE.is_file()


def installed() -> bool:
    """¿Está listo para sonar con Kokoro real (librería + archivos)?"""
    return runtime_supported() and files_present()


async def install():
    """Descarga los pesos oficiales Apache-2.0 de Kokoro v1.0 a models/kokoro (solo cuando el usuario lo pide)."""
    if progress.get("status") == "descargando":
        return
    progress.update(status="descargando", percent=0, error="")
    todo = [name for name in FILES if not (DIR / name).is_file()]
    if not todo:
        progress.update(status="lista", percent=100, error="")
        return
    total = sum(FILES[n][1] for n in todo) * 2**20 or 1
    done = 0
    DIR.mkdir(parents=True, exist_ok=True)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10), follow_redirects=True) as client:
            for name in todo:
                url, _, want = FILES[name]
                part = DIR / f"{name}.part"
                digest = hashlib.sha256()
                async with client.stream("GET", url) as r:
                    r.raise_for_status()
                    with open(part, "wb") as f:
                        async for chunk in r.aiter_bytes(1 << 16):
                            f.write(chunk)
                            digest.update(chunk)
                            done += len(chunk)
                            progress["percent"] = min(99, round(100 * done / total))
                if digest.hexdigest() != want:
                    part.unlink(missing_ok=True)
                    raise ValueError(f"{name} no coincide con su suma SHA-256")
                part.replace(DIR / name)
        progress.update(status="lista", percent=100, error="")
    except ValueError as e:
        log.warning("Descarga de Kokoro descartada: %s", e)
        progress.update(status="", error="El archivo descargado no es el esperado; no se usó. Vuelve a intentarlo.")
    except (httpx.HTTPError, OSError) as e:
        log.warning("No pude descargar Kokoro: %s", e)
        progress.update(status="", error=f"Se cortó la descarga ({type(e).__name__}). Vuelve a intentarlo.")


def _spec_for(voice: str) -> tuple[str, float, float]:
    if voice in VOICE_MAP:
        return VOICE_MAP[voice]
    from . import voice_import
    own = next((v for v in voice_import.custom() if v.get("tts_voice") == voice), None)
    if own and own.get("speaks") == "m":
        return ("em_alex", 1.0, 1.0)
    return ("ef_dora", 1.0, 1.0)


def _synth(text: str, voice: str, speed: float) -> bytes:
    global _engine
    from kokoro_onnx import Kokoro
    k_voice, base_speed, pitch = _spec_for(voice)
    with _lock:
        if _engine is None:
            _engine = Kokoro(str(MODEL_FILE), str(VOICES_FILE))
        samples, sr = _engine.create(text, voice=k_voice, speed=min(1.4, max(0.7, speed * base_speed / pitch)), lang="es")
    x = np.asarray(samples, dtype=np.float32)
    if x.size == 0:
        return b""
    if sr != SAMPLE_RATE or abs(pitch - 1.0) > 0.01:
        n = max(1, int(len(x) / pitch * SAMPLE_RATE / sr))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


async def stream_speech(text: str, voice: str, speed: float = 1.0) -> AsyncIterator[bytes]:
    from .tts import TTSError
    if not installed():
        raise TTSError("La voz Kokoro todavía no está instalada o falta kokoro-onnx.")
    try:
        pcm = await asyncio.to_thread(_synth, text[:1500], voice, speed)
    except Exception as e:  # noqa: BLE001
        raise TTSError(f"La voz Kokoro falló ({type(e).__name__})") from e
    step = SAMPLE_RATE // 2 * 2
    for i in range(0, len(pcm), step):
        yield pcm[i:i + step]
