"""Voz en la nube (15 nov 2026): las voces neuronales de Microsoft que usa la lectura en voz alta de Edge, con la
librería edge-tts. No pide clave ni tiene cupo diario conocido, no usa memoria de vídeo y casi nada de procesador
(solo decodifica el MP3 que llega). No es una API oficial: si Microsoft la cambia y deja de responder, la frase
suena con la voz ligera (tts.stream_speech). No clona: cada voz del catálogo tiene aquí una voz neuronal parecida
(`cloud` en voices.json; las propias del usuario, según cómo hablan). Necesita internet y el texto de cada frase
sale de la PC."""
import logging
from typing import AsyncIterator

from .config import ROOT

log = logging.getLogger("companion.tts")
SAMPLE_RATE = 24000
DEFAULT = {"f": "es-MX-DaliaNeural", "m": "es-MX-JorgeNeural"}
_specs: tuple = (0, {})


def specs() -> dict:
    """tts_voice → {"voice", "pitch", "rate"} según `cloud` en voices.json."""
    global _specs
    import json
    path = ROOT / "voices.json"
    try:
        stamp = path.stat().st_mtime_ns
        if stamp != _specs[0]:
            data = json.loads(path.read_text(encoding="utf-8"))["voices"]
            _specs = (stamp, {v["tts_voice"]: v["cloud"] for v in data if isinstance(v.get("cloud"), dict)})
    except (OSError, ValueError, KeyError):
        pass
    return _specs[1]


def spec_for(voice: str) -> dict:
    s = specs().get(voice)
    if s:
        return s
    from . import voice_import
    own = next((v for v in voice_import.custom() if v.get("tts_voice") == voice), None)
    return {"voice": DEFAULT["m" if own and own.get("speaks") == "m" else "f"]}


def installed() -> bool:
    try:
        import edge_tts  # noqa: F401
        import av  # noqa: F401
    except ImportError:
        return False
    return True


def _percent(x: float) -> str:
    return f"{'+' if x >= 0 else ''}{round(x * 100)}%"


async def stream_speech(text: str, voice: str, speed: float = 1.0) -> AsyncIterator[bytes]:
    """PCM de 16 bits mono a 24 kHz, en trozos según va llegando el MP3."""
    from .tts import TTSError
    if not installed():
        raise TTSError("La voz en la nube no está instalada (falta edge-tts).")
    import av
    import edge_tts
    spec = spec_for(voice)
    rate = float(spec.get("rate", 0.0)) + (min(1.3, max(0.7, speed)) - 1.0)
    comm = edge_tts.Communicate(text[:1500], spec["voice"], rate=_percent(rate),
                                pitch=f"{'+' if spec.get('pitch', 0) >= 0 else ''}{int(spec.get('pitch', 0))}Hz")
    codec = av.CodecContext.create("mp3", "r")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

    def decode(data: bytes | None) -> bytes:
        out = bytearray()
        for packet in codec.parse(data):
            for frame in codec.decode(packet):
                for f in resampler.resample(frame):
                    out += f.to_ndarray().tobytes()
        return bytes(out)
    sent = False
    try:
        async for chunk in comm.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                pcm = decode(chunk["data"])
                if pcm:
                    sent = True
                    yield pcm
        tail = decode(None) + b"".join(f.to_ndarray().tobytes() for f in resampler.resample(None))
        if tail:
            sent = True
            yield tail
    except TTSError:
        raise
    except Exception as e:  # noqa: BLE001  (edge-tts lanza las suyas, aiohttp las suyas)
        if sent:
            raise TTSError(f"Se cortó la voz en la nube ({type(e).__name__})") from e
        raise TTSError(f"La voz en la nube no respondió ({type(e).__name__})") from e
    if not sent:
        raise TTSError("La voz en la nube no devolvió audio")

