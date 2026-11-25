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
import shutil
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s voz: %(message)s")
log = logging.getLogger("voz")
RAIZ = Path(__file__).resolve().parent
MODELO = RAIZ / "modelos" / "f5-spanish"
VOCOS = RAIZ / "modelos" / "vocos"
VOCES = Path(os.getenv("VOICES_DIR") or RAIZ.parent / "voices")
PROPIAS = Path(os.getenv("VOICES_CUSTOM_DIR") or RAIZ.parent / "data" / "voces")
POR_DEFECTO = os.getenv("TTS_VOICE", "mika_es")
SR = 24000
PAUSA_S = 0.12
NFE = int(os.getenv("VOZ_NFE", "32"))
RITMO = float(os.getenv("VOZ_RITMO", "0.9"))
CORTA_REF = os.getenv("VOZ_REF_CORTA") == "1"
LARGA = int(os.getenv("VOZ_LARGA", "150"))
LENTA_S = float(os.getenv("VOZ_LENTA_S", "2.5"))
_CONJ = re.compile(r"\s(?=(?:y|e|o|u|pero|porque|que|cuando|aunque|mientras|para|si)\s)", re.IGNORECASE)
_SENT_SPLIT = re.compile(r"(?<!\bSr)(?<!\bSra)(?<!\bDr)(?<!\bDra)(?<!\bAv)(?<!\betc)(?<!\bp\. ej)(?<=[.!?…])(?!\d)\s+|\n+")
CORTA, MIN_S = 25, 1.7
_ref_s: dict[str, float] = {}
estado = {"tts": None, "error": "", "voz": None, "dispositivo": "", "listo": False}


def _parent_alive(pid: int) -> bool:
    if pid <= 0:
        return True
    if sys.platform == "win32":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok and code.value == 259)  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _watch_parent():
    raw = os.getenv("COMPANION_PARENT_PID", "").strip()
    if not raw.isdigit():
        return
    pid = int(raw)

    def loop():
        while True:
            time.sleep(5.0)
            if not _parent_alive(pid):
                log.info("El proceso padre (%d) terminó: cierro el servidor de voz", pid)
                os._exit(0)

    threading.Thread(target=loop, daemon=True).start()


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
    """Una cláusula → audio float32 a 24 kHz, sin el silencio de los extremos y con fundido suave."""
    import librosa
    import soundfile as sf
    import torch
    wav, cfg = _voz(nombre)
    velocidad *= RITMO
    ref_text = cfg["ref_text"]
    if CORTA_REF and isinstance(cfg.get("short"), dict):
        wav, ref_text, ajuste = _muestra_corta(wav, cfg["short"])
        velocidad *= ajuste
    fijo = None
    if len(texto) < CORTA:
        ref = _ref_s.setdefault(f"{wav}:{wav.stat().st_mtime_ns}", sf.info(str(wav)).duration)
        est = ref / max(1, len(ref_text.encode("utf-8"))) * len(texto.encode("utf-8")) / velocidad
        if est < MIN_S:
            fijo = ref + MIN_S
    with torch.inference_mode():
        audio, sr, _ = estado["tts"].infer(
            ref_file=str(wav), ref_text=ref_text, gen_text=texto,
            nfe_step=max(NFE, int(cfg.get("stream_nfe_step", 16))), speed=velocidad,
            fix_duration=fijo, show_info=lambda *a, **k: None, progress=_SinBarra,
            remove_silence=False,
        )
    audio = np.asarray(audio, dtype=np.float32)
    if sr != SR:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=SR)
    audio, _ = librosa.effects.trim(audio, top_db=40, frame_length=1024, hop_length=256)
    audio = audio.copy()
    fin = min(len(audio), int(SR * 0.010))
    if fin:
        audio[:fin] *= np.linspace(0.0, 1.0, fin, dtype=np.float32)
    fout = min(len(audio), int(SR * 0.025))
    if fout:
        audio[-fout:] *= np.linspace(1.0, 0.0, fout, dtype=np.float32)
    changed_voice = estado["voz"] != nombre
    if changed_voice:
        estado["voz"] = nombre
    if torch.cuda.is_available():
        if changed_voice or (torch.cuda.memory_reserved() - torch.cuda.memory_allocated() > 400 * 1024 * 1024):
            torch.cuda.empty_cache()
    elif changed_voice and torch.backends.mps.is_available():
        torch.mps.empty_cache()
    return audio


def _por_conjuncion(t: str) -> list[str]:
    if len(t) <= LARGA:
        return [t]
    cortes = [m.start() for m in _CONJ.finditer(t) if 25 <= m.start() <= len(t) - 25]
    if not cortes:
        return [t]
    k = min(cortes, key=lambda c: abs(c - len(t) / 2))
    return _por_conjuncion(t[:k].strip()) + _por_conjuncion(t[k:].strip())


def partir(texto: str) -> list[str]:
    """Frases; respeta abreviaturas y decimales, parte las largas en comas y une las muy cortas."""
    frases = [f.strip() for f in _SENT_SPLIT.split(texto.strip()) if f.strip()]
    trozos: list[str] = []
    for f in frases:
        if len(f) > LARGA:
            actual = ""
            for parte in re.split(r"(?<=[,;:])\s+", f):
                if actual and len(actual) + len(parte) > int(LARGA * 0.73):
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
    log.info("Tarjeta lenta: una frase corta tardó %.2f s; modo rápido (16 pasos, muestra corta)", s)


def cargar():
    try:
        import torch
        _parche_torchaudio()
        from f5_tts.api import F5TTS
        dispositivo = os.getenv("VOZ_DISPOSITIVO") or (
            "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        )
        if dispositivo == "cpu" and not os.getenv("VOZ_DISPOSITIVO") and sys.platform != "darwin" and shutil.which("nvidia-smi"):
            raise RuntimeError("PyTorch no puede usar la tarjeta NVIDIA (el driver es más antiguo que el CUDA de "
                               f"PyTorch {torch.__version__}). Vuelve a ejecutar el instalador o actualiza el driver.")
        ckpt = next(MODELO.glob("model_*.safetensors"))

        def preparar(disp: str):
            estado["tts"] = F5TTS(model="F5TTS_Base", ckpt_file=str(ckpt), vocab_file=str(MODELO / "vocab.txt"),
                                  vocoder_local_path=str(VOCOS) if (VOCOS / "config.yaml").is_file() else None,
                                  device=disp)
            if disp == "mps" and os.getenv("VOZ_F16", "1") == "1":
                estado["tts"].ema_model.half()
            estado["dispositivo"] = disp
            t = time.perf_counter()
            _decir("Hola, ¿qué tal estás hoy?", POR_DEFECTO, 1.0)
            log.info("F5-TTS listo en %s (%s, calentamiento %.1f s) · voces en %s", disp, ckpt.name,
                     time.perf_counter() - t, VOCES)
            if disp == "cuda":
                _medir_tarjeta()
            estado["listo"] = True
        try:
            preparar(dispositivo)
        except Exception:  # noqa: BLE001
            if dispositivo != "mps":
                raise
            log.exception("La GPU del Mac falló con F5-TTS: sigo en el procesador")
            estado["tts"] = None
            preparar("cpu")
    except Exception as e:  # noqa: BLE001
        estado["tts"], estado["listo"] = None, False
        estado["error"] = f"{type(e).__name__}: {e}"
        log.exception("No se pudo cargar F5-TTS")


@asynccontextmanager
async def vida(_: FastAPI):
    _watch_parent()
    asyncio.get_running_loop().run_in_executor(None, cargar)
    yield


app = FastAPI(title="Voz del companion", lifespan=vida)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
candado = asyncio.Lock()

_LOCAL_ORIGIN = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$", re.I)


def _check_origin(origin: str | None):
    if origin and not _LOCAL_ORIGIN.match(origin.strip()):
        raise HTTPException(403, "Origen no permitido")


@app.get("/health")
async def health():
    listo = bool(estado["tts"]) and estado["listo"]
    return {"ok": True, "tts": "f5" if listo else "none", "loading": not listo and not estado["error"],
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
async def speech(p: Peticion, origin: str | None = Header(default=None)):
    _check_origin(origin)
    if not estado["tts"] or not estado["listo"]:
        raise HTTPException(503, estado["error"] or "La voz todavía está cargando")
    nombre = p.voice or POR_DEFECTO
    _voz(nombre)
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
