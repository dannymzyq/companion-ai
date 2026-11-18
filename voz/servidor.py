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
import shutil
import sys
import re
import tempfile
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
# Muestra corta (VOZ_REF_CORTA=1, el companion lo pone en el Mac): con la de 8 s, F5 en la GPU del Mac tardaba
# 6–10 s por frase; con 4–5 s, la mitad (16 nov 2026). En la PC no gana nada (1,15 s por frase con las dos: en CUDA
# el coste es fijo), así que allí va la entera. (Dar más duración a las frases largas no evita que alguna vez se
# coma el final: lo empeoraba, medido con 10 tiradas por frase.)
CORTA_REF = os.getenv("VOZ_REF_CORTA") == "1"
# Frases largas: se parten a partir de LARGA letras, en las comas y, si no hay, antes de una conjunción (el primer
# trozo suena antes, y un trozo corto se genera antes de que acabe de sonar el anterior). En el Mac, donde cada
# frase tarda más, voz_proc lo baja a 90.
LARGA = int(os.getenv("VOZ_LARGA", "150"))
LENTA_S = float(os.getenv("VOZ_LENTA_S", "2.5"))   # una frase corta más lenta que esto: modo rápido (_medir_tarjeta)
_CONJ = re.compile(r"\s(?=(?:y|e|o|u|pero|porque|que|cuando|aunque|mientras|para|si)\s)", re.IGNORECASE)
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


def _muestra_corta(wav: Path, corta: dict) -> tuple[Path, str, float]:
    """El tramo corto de la muestra (`short` en su .json, de scripts/recortar_muestras.py): F5 genera la muestra junto
    con cada frase, así que con 4–5 s en vez de 8 cada frase tarda la mitad. Se recorta una vez y se guarda en la
    carpeta temporal. Devuelve (wav, su texto, ajuste de velocidad para que hable al mismo ritmo que con la entera)."""
    import soundfile as sf
    t0, t1 = float(corta["start"]), float(corta["end"])
    destino = Path(tempfile.gettempdir()) / "companion_voz" / f"{wav.stem}_{wav.stat().st_mtime_ns}_{t0:.2f}_{t1:.2f}.wav"
    if not destino.is_file():
        x, sr = sf.read(str(wav), dtype="float32", always_2d=False)
        y = x[int(t0 * sr):int(t1 * sr)].copy()
        n = min(len(y), int(sr * 0.03))
        if n:
            y[:n] *= np.linspace(0.0, 1.0, n, dtype=np.float32)
            y[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(".tmp.wav")
        sf.write(str(tmp), y, sr)
        tmp.replace(destino)
    return destino, str(corta["text"]), min(1.25, max(0.8, float(corta.get("speed", 1.0))))


def _decir(texto: str, nombre: str, velocidad: float) -> np.ndarray:
    """Una cláusula → audio float32 a 24 kHz, sin el silencio de los extremos."""
    import librosa
    import torch
    import soundfile as sf
    wav, cfg = _voz(nombre)
    velocidad *= RITMO
    ref_text = cfg["ref_text"]
    if CORTA_REF and isinstance(cfg.get("short"), dict):
        wav, ref_text, ajuste = _muestra_corta(wav, cfg["short"])
        velocidad *= ajuste
    fijo = None
    if len(texto) < CORTA:
        # F5 calcula la duración por la longitud del texto: a una frase corta le da tan poco tiempo que se la come
        # («¡Hola, Danny!» → «Dani»). Se le da un mínimo.
        ref = _ref_s.setdefault(f"{wav}:{wav.stat().st_mtime_ns}", sf.info(str(wav)).duration)
        est = ref / max(1, len(ref_text.encode("utf-8"))) * len(texto.encode("utf-8")) / velocidad
        if est < MIN_S:
            fijo = ref + MIN_S
    audio, sr, _ = estado["tts"].infer(ref_file=str(wav), ref_text=ref_text, gen_text=texto,
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
        elif torch.backends.mps.is_available():
            torch.mps.empty_cache()
    return audio


def _por_conjuncion(t: str) -> list[str]:
    """Un trozo que sigue siendo largo (sin comas) se corta antes de la conjunción más cercana a la mitad, si deja
    al menos 25 letras a cada lado; si no hay, se queda entero (cortar en cualquier palabra rompe la entonación)."""
    if len(t) <= LARGA:
        return [t]
    cortes = [m.start() for m in _CONJ.finditer(t) if 25 <= m.start() <= len(t) - 25]
    if not cortes:
        return [t]
    k = min(cortes, key=lambda c: abs(c - len(t) / 2))
    return _por_conjuncion(t[:k].strip()) + _por_conjuncion(t[k:].strip())


def partir(texto: str) -> list[str]:
    """Frases; las largas se parten en las comas y las muy cortas («Hola,») se unen a la siguiente, porque
    F5 dice mal los trozos de una o dos palabras."""
    frases = [f.strip() for f in re.split(r"(?<=[.!?…])\s+|\n+", texto.strip()) if f.strip()]
    trozos: list[str] = []
    for f in frases:
        if len(f) > LARGA:
            actual = ""
            for parte in re.split(r"(?<=[,;:])\s+", f):
                if actual and len(actual) + len(parte) > int(LARGA * 0.73):      # 110 con el umbral de 150
                    trozos.append(actual)
                    actual = parte
                else:
                    actual = f"{actual} {parte}".strip()
            if actual:
                trozos.append(actual)
        else:
            trozos.append(f)
    trozos = [p for t in trozos for p in _por_conjuncion(t)]
    unidos: list[str] = []
    for t in trozos:
        if unidos and len(unidos[-1]) < 22:
            unidos[-1] = f"{unidos[-1]} {t}"
        else:
            unidos.append(t)
    if len(unidos) > 1 and len(unidos[-1]) < 12:
        unidos[-2:] = [f"{unidos[-2]} {unidos[-1]}"]
    return unidos


def _medir_tarjeta():
    """Modo rápido en tarjetas lentas (18 nov 2026): en una RTX 3050 de laptop cada frase tardaba 5-6,5 s (la GPU al
    100 %; en la 5070 Ti, 1,1 s), más lenta que lo que dura. Se mide una frase corta tras el calentamiento y, si pasa
    de LENTA_S, se usa lo mismo que en el Mac: 16 pasos, la muestra corta y frases partidas antes. Se pierde algo de
    precisión (con 16 pasos se comía más palabras) a cambio de empezar a hablar varias veces antes. VOZ_NFE o
    VOZ_REF_CORTA en el entorno lo fijan a mano."""
    global NFE, CORTA_REF, LARGA
    t = time.perf_counter()
    _decir("Vale, ahora mismo te lo cuento.", POR_DEFECTO, 1.0)
    s = time.perf_counter() - t
    estado["frase_s"] = round(s, 2)
    if s <= LENTA_S or os.getenv("VOZ_NFE") or os.getenv("VOZ_REF_CORTA"):
        log.info("Tarjeta: una frase corta en %.2f s (modo normal)", s)
        return
    NFE, CORTA_REF, LARGA = 16, True, min(LARGA, 90)
    estado["rapida"] = True
    t = time.perf_counter()
    _decir("Vale, ahora mismo te lo cuento.", POR_DEFECTO, 1.0)
    log.info("Tarjeta lenta: una frase corta tardaba %.2f s; modo rápido (16 pasos, muestra corta): %.2f s",
             s, time.perf_counter() - t)


def cargar():
    try:
        import torch
        _parche_torchaudio()
        from f5_tts.api import F5TTS
        # VOZ_DISPOSITIVO=cpu|mps|cuda lo fija (la prueba en un Mac virtual de GitHub: su GPU se cuelga con Metal).
        dispositivo = os.getenv("VOZ_DISPOSITIVO") or (
            "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")   # mps: la GPU de un Mac
        if dispositivo == "cpu" and not os.getenv("VOZ_DISPOSITIVO") and sys.platform != "darwin" and shutil.which("nvidia-smi"):
            # Hay tarjeta NVIDIA pero PyTorch no la ve (casi siempre: un driver anterior al CUDA de esta versión de
            # PyTorch). En el procesador F5 tarda decenas de segundos por frase: mejor avisar y que suene la ligera.
            raise RuntimeError("PyTorch no puede usar la tarjeta NVIDIA (el driver es más antiguo que el CUDA de "
                               f"PyTorch {torch.__version__}). Vuelve a ejecutar el instalador o actualiza el driver.")
        ckpt = next(MODELO.glob("model_*.safetensors"))

        def preparar(disp: str):
            estado["tts"] = F5TTS(model="F5TTS_Base", ckpt_file=str(ckpt), vocab_file=str(MODELO / "vocab.txt"),
                                  vocoder_local_path=str(VOCOS) if (VOCOS / "config.yaml").is_file() else None,
                                  device=disp)
            if disp == "mps" and os.getenv("VOZ_F16", "1") == "1":
                # F5 solo usa float16 en CUDA; en la GPU del Mac cargaba en float32. Con float16, 1,4–1,7 veces más
                # rápido y sin perder palabras (M5 Pro, 16 nov 2026). El vocoder sigue en float32 (F5 le pasa la mel así).
                estado["tts"].ema_model.half()
            estado["dispositivo"] = disp
            t = time.perf_counter()
            _decir("Hola, ¿qué tal estás hoy?", POR_DEFECTO, 1.0)      # calentamiento: la primera frase tarda más
            log.info("F5-TTS listo en %s (%s, calentamiento %.1f s) · voces en %s", disp, ckpt.name,
                     time.perf_counter() - t, VOCES)
            if disp == "cuda":
                _medir_tarjeta()
        try:
            preparar(dispositivo)
        except Exception:  # noqa: BLE001
            if dispositivo != "mps":
                raise
            log.exception("La GPU del Mac falló con F5-TTS: sigo en el procesador")     # más lenta, pero suena
            estado["tts"] = None
            preparar("cpu")
    except Exception as e:  # noqa: BLE001
        estado["tts"] = None
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
            "error": estado["error"], "device": estado["dispositivo"],
            "fast": bool(estado.get("rapida")), "phrase_s": estado.get("frase_s")}


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
