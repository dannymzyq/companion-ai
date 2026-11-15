"""Servidor de voz del companion (la «voz completa»): F5-TTS en español (jpgallegoar/F5-Spanish, CC-BY-NC),
que clona la voz de una muestra corta. Vive entero en esta carpeta: su entorno (voz/.venv), su modelo
(voz/modelos) y las muestras del companion (../voices/<voz>.wav + .json con ref_text). Sustituye al nodo de
voz de waifuv3, del que solo se usaba F5: sin Chatterbox ocupa menos memoria de vídeo.

    voz\\.venv\\Scripts\\python.exe -m uvicorn servidor:app --app-dir voz --host 127.0.0.1 --port 8210

Mismo contrato que usaba el companion:  GET /health  ·  POST /v1/audio/speech {input, voice, speed}
→ PCM de 16 bits, mono, 24 kHz, en streaming (una cláusula tras otra).
"""
import asyncio
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s voz: %(message)s")
log = logging.getLogger("voz")
RAIZ = Path(__file__).resolve().parent
MODELO = RAIZ / "modelos" / "f5-spanish"
VOCOS = RAIZ / "modelos" / "vocos"
VOCES = Path(os.getenv("VOICES_DIR") or RAIZ.parent / "voices")
# Las voces propias que sube el usuario (companion/voice_import.py): llevan el prefijo p_ y viven con sus datos.
PROPIAS = Path(os.getenv("VOICES_CUSTOM_DIR") or RAIZ.parent / "data" / "voces")
POR_DEFECTO = os.getenv("TTS_VOICE", "mika_es")
SR = 24000
PAUSA_S = 0.12
# Calidad frente a rapidez (medido el 13 nov 2026 con Whisper sobre respuestas típicas): con 16 pasos se perdían
# ~9 % de las palabras; con 32 pasos y un ritmo de 0,9, ~4 %. Cuesta ~0,6 s más por frase.
NFE = int(os.getenv("VOZ_NFE", "32"))
RITMO = float(os.getenv("VOZ_RITMO", "0.9"))
CORTA, MIN_S = 25, 1.7                     # una frase de menos letras recibe al menos MIN_S segundos para decirse
_ref_s: dict[str, float] = {}
estado = {"tts": None, "error": "", "voz": None, "dispositivo": ""}


def _parche_torchaudio():
    """torchaudio reciente carga con torchcodec, que pide las DLL de FFmpeg; para WAV basta soundfile."""
    import soundfile as sf
    import torch
    import torchaudio

    def load(path, *args, **kwargs):
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(data.T.copy()), sr
    torchaudio.load = load
    import f5_tts.infer.utils_infer as utils
    utils.torchaudio.load = load


class _SinBarra:
    @staticmethod
    def tqdm(iterable, *args, **kwargs):
        return iterable


def _voz(nombre: str) -> tuple[Path, dict]:
    for n in (nombre, POR_DEFECTO):
        carpeta = PROPIAS if (n or "").startswith("p_") else VOCES
        wav, cfg = carpeta / f"{n}.wav", carpeta / f"{n}.json"
        if re.fullmatch(r"[\w-]{1,60}", n or "") and wav.is_file() and cfg.is_file():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if data.get("ref_text"):
                return wav, data
    raise HTTPException(404, f"No hay muestra para la voz «{nombre}»")


def _decir(texto: str, nombre: str, velocidad: float) -> np.ndarray:
    """Una cláusula → audio float32 a 24 kHz, sin el silencio de los extremos."""
    import librosa
    import torch
    import soundfile as sf
    wav, cfg = _voz(nombre)
    velocidad *= RITMO
    fijo = None
    if len(texto) < CORTA:
        # F5 calcula la duración por la longitud del texto: a una frase corta le da tan poco tiempo que se la come
        # («¡Hola, Danny!» → «Dani»). Se le da un mínimo.
        ref = _ref_s.setdefault(f"{wav}:{wav.stat().st_mtime_ns}", sf.info(str(wav)).duration)
        est = ref / max(1, len(cfg["ref_text"].encode("utf-8"))) * len(texto.encode("utf-8")) / velocidad
        if est < MIN_S:
            fijo = ref + MIN_S
    audio, sr, _ = estado["tts"].infer(ref_file=str(wav), ref_text=cfg["ref_text"], gen_text=texto,
                                       nfe_step=max(NFE, int(cfg.get("stream_nfe_step", 16))), speed=velocidad,
                                       fix_duration=fijo, show_info=lambda *a, **k: None, progress=_SinBarra,
                                       remove_silence=False)
    audio = np.asarray(audio, dtype=np.float32)
    if sr != SR:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=SR)
    audio, _ = librosa.effects.trim(audio, top_db=40, frame_length=1024, hop_length=256)
    audio = audio.copy()
    n = min(len(audio), int(SR * 0.025))
    if n:
        audio[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
    if estado["voz"] != nombre:                 # al cambiar de voz se devuelve la memoria de vídeo sobrante
        estado["voz"] = nombre
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    return audio


def partir(texto: str) -> list[str]:
    """Frases; las largas se parten en las comas y las muy cortas («Hola,») se unen a la siguiente, porque
    F5 dice mal los trozos de una o dos palabras."""
    frases = [f.strip() for f in re.split(r"(?<=[.!?…])\s+|\n+", texto.strip()) if f.strip()]
    trozos: list[str] = []
    for f in frases:
        if len(f) > 150:
            actual = ""
            for parte in re.split(r"(?<=[,;:])\s+", f):
                if actual and len(actual) + len(parte) > 110:
                    trozos.append(actual)
                    actual = parte
                else:
                    actual = f"{actual} {parte}".strip()
            if actual:
                trozos.append(actual)
        else:
            trozos.append(f)
    unidos: list[str] = []
    for t in trozos:
        if unidos and len(unidos[-1]) < 22:
            unidos[-1] = f"{unidos[-1]} {t}"
        else:
            unidos.append(t)
    if len(unidos) > 1 and len(unidos[-1]) < 12:
        unidos[-2:] = [f"{unidos[-2]} {unidos[-1]}"]
    return unidos


def cargar():
    try:
        import torch
        _parche_torchaudio()
        from f5_tts.api import F5TTS
        dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
        ckpt = next(MODELO.glob("model_*.safetensors"))
        estado["tts"] = F5TTS(model="F5TTS_Base", ckpt_file=str(ckpt), vocab_file=str(MODELO / "vocab.txt"),
                              vocoder_local_path=str(VOCOS) if (VOCOS / "config.yaml").is_file() else None,
                              device=dispositivo)
        estado["dispositivo"] = dispositivo
        t = time.perf_counter()
        _decir("Hola, ¿qué tal estás hoy?", POR_DEFECTO, 1.0)      # calentamiento: la primera frase tarda más
        log.info("F5-TTS listo en %s (%s, calentamiento %.1f s) · voces en %s", dispositivo, ckpt.name,
                 time.perf_counter() - t, VOCES)
    except Exception as e:  # noqa: BLE001
        estado["error"] = f"{type(e).__name__}: {e}"
        log.exception("No se pudo cargar F5-TTS")


@asynccontextmanager
async def vida(_: FastAPI):
    asyncio.get_running_loop().run_in_executor(None, cargar)       # carga sin frenar el arranque
    yield


app = FastAPI(title="Voz del companion", lifespan=vida)
candado = asyncio.Lock()                                           # una síntesis a la vez en la GPU


@app.get("/health")
async def health():
    return {"ok": True, "tts": "f5" if estado["tts"] else "none", "loading": not estado["tts"] and not estado["error"],
            "error": estado["error"], "device": estado["dispositivo"]}


class Peticion(BaseModel):
    input: str
    voice: str = ""
    speed: float = 1.0
    model: str = ""
    response_format: str = "pcm"
    stream: bool = True


@app.post("/v1/audio/speech")
async def speech(p: Peticion):
    if not estado["tts"]:
        raise HTTPException(503, estado["error"] or "La voz todavía está cargando")
    nombre = p.voice or POR_DEFECTO
    _voz(nombre)                                                   # 404 antes de empezar a responder
    trozos = partir(p.input[:1500])
    velocidad = min(1.3, max(0.7, p.speed))

    async def audio():
        t0, primero = time.perf_counter(), None
        async with candado:
            for i, trozo in enumerate(trozos):
                x = await asyncio.to_thread(_decir, trozo, nombre, velocidad)
                primero = primero or time.perf_counter() - t0
                pcm = (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                if i:
                    yield b"\0\0" * int(SR * PAUSA_S)
                for k in range(0, len(pcm), 4800):
                    yield pcm[k:k + 4800]
        log.info("%d c con %s: primer audio %.2f s, total %.2f s", len(p.input), nombre, primero or 0, time.perf_counter() - t0)

    return StreamingResponse(audio(), media_type="audio/pcm", headers={"X-Sample-Rate": str(SR)})
