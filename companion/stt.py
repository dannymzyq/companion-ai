"""Oído: transcripción local con faster-whisper (GPU si se puede, CPU si no) o en la nube (stt_cloud, `engine`
«nube»: no se carga Whisper; si la nube falla, se carga en el procesador como respaldo)."""
import logging
import os
import site
import sys
import threading
from pathlib import Path

import numpy as np

from .config import ROOT

log = logging.getLogger("companion.stt")

# Frases que Whisper inventa cuando solo oye ruido o silencio.
HALLUCINATIONS = ("amara.org", "subtítulos", "subtitulos", "suscríbete", "suscribete", "gracias por ver",
                  "gracias por ver el video", "¡gracias!", "gracias.")


def _add_cuda_dlls():
    """Hace visibles las DLL de cuBLAS/cuDNN instaladas por pip (paquetes nvidia-*-cu12)."""
    for base in site.getsitepackages():
        root = Path(base) / "nvidia"
        if not root.is_dir():
            continue
        for bin_dir in root.glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


on_gpu = False                            # ¿el oído ya está cargado en la tarjeta? (profile.measured_others)
loaded_name = ""                          # el Whisper cargado en la tarjeta (profile.ear_gb)


class Transcriber:
    def __init__(self, model: str, device: str, compute: str, language: str, hint: str = ""):
        self.model_name, self.want_device, self.compute = model, device, compute
        self.language, self.hint = language, hint
        self.model = None
        self.device = None
        self.error: str | None = None
        self.engine = "local"             # local | nube (Ajustes › Oído; profile.ear_engine)
        self.used_cuda = False            # cargó en la tarjeta alguna vez: CUDA no se suelta hasta reiniciar
        self._backup = None               # Whisper en el procesador, por si la nube falla (solo se carga entonces)
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self.engine == "nube" or self.model is not None

    def set_engine(self, engine: str):
        """Cambia entre el oído local y el de la nube. Al pasar a la nube se descarga Whisper (devuelve la memoria de
        vídeo y la RAM); al volver a local hay que llamar a load() (tarda unos segundos)."""
        global on_gpu
        engine = "nube" if engine == "nube" else "local"
        if engine == self.engine and (engine == "nube" or self.model is not None or self.error):
            return False
        self.engine = engine
        if engine == "nube":
            with self._lock:
                self.model, self._backup, self.error = None, None, None
                self.device = "nube"
                on_gpu = False
            import gc
            gc.collect()
            log.info("Oído en la nube: Whisper descargado de esta PC")
            return False
        self.device = None
        return True                       # quien llama carga el modelo local (load) en segundo plano

    def local_model(self):
        """Un Whisper local para lo que no se hace en la nube (crear una voz propia) o si la nube falla: el del oído
        si está cargado; si no, el modelo instalado en el procesador (sin memoria de vídeo)."""
        if self.model is not None:
            return self.model
        with self._load_lock:
            if self._backup is None:
                from faster_whisper import WhisperModel
                local = ROOT / "models" / "whisper" / self.model_name
                self._backup = WhisperModel(str(local) if (local / "model.bin").is_file() else self.model_name,
                                            device="cpu", compute_type="int8")
                log.info("Whisper %s cargado en CPU (respaldo del oído en la nube)", self.model_name)
            return self._backup

    def load(self):
        if self.engine == "nube":         # con el oído en la nube no se carga nada al arrancar
            self.device = "nube"
            return
        from faster_whisper import WhisperModel as _Whisper

        def WhisperModel(name, **kw):       # el modelo que trajo el instalador a models/whisper; si no, se descarga
            local = ROOT / "models" / "whisper" / name
            return _Whisper(str(local) if (local / "model.bin").is_file() else name, **kw)

        global on_gpu, loaded_name
        silence = np.zeros(8000, dtype=np.float32)
        if self.want_device in ("auto", "cuda") and sys.platform != "darwin":   # en el Mac no hay CUDA
            try:
                _add_cuda_dlls()
                model = WhisperModel(self.model_name, device="cuda", compute_type=self.compute)
                list(model.transcribe(silence, language=self.language, beam_size=1)[0])   # fuerza la carga de las DLL
                self.model, self.device, self.used_cuda = model, "cuda", True
                on_gpu = True
                loaded_name = self.model_name
                log.info("Whisper %s en GPU (%s)", self.model_name, self.compute)
                return
            except Exception as e:  # noqa: BLE001
                log.warning("Whisper no pudo usar la GPU (%s); paso a CPU", e)
                if self.want_device == "cuda":
                    self.error = str(e)
                    return
        if self.want_device in ("auto", "mps") and sys.platform == "darwin":
            # La GPU del Mac (backend MPS de CTranslate2, experimental): 4 s de habla en 0,7 s frente a 3,9 s en el
            # procesador (medido en una MacBook M5 Pro, 16 nov 2026). Si falla, sigue en el procesador.
            try:
                model = WhisperModel(self.model_name, device="mps", compute_type="float16")
                list(model.transcribe(silence, language=self.language, beam_size=1)[0])
                self.model, self.device = model, "mps"
                on_gpu = True
                log.info("Whisper %s en la GPU del Mac (MPS)", self.model_name)
                return
            except Exception as e:  # noqa: BLE001
                log.warning("Whisper no pudo usar la GPU del Mac (%s); paso al procesador", e)
        try:
            # large en CPU sería muy lento en un PC; el procesador de un Mac con Apple Silicon sí mueve el turbo
            name = self.model_name if self.want_device == "cpu" or sys.platform == "darwin" else "small"
            # Con los hilos por defecto CTranslate2 usa pocos núcleos: en el Mac, 10 hilos lo bajan de 3,9 a 2,1 s
            threads = min(os.cpu_count() or 4, 10) if sys.platform == "darwin" else 0
            self.model, self.device = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads), "cpu"
            self.model_name = name
            log.info("Whisper %s en CPU", name)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            log.error("No se pudo cargar Whisper: %s", e)

    def transcribe(self, audio: np.ndarray) -> str:
        """audio: float32 mono a 16 kHz. Devuelve el texto, o '' si no hubo habla reconocible."""
        if self.engine == "nube":
            from . import stt_cloud
            try:
                return _clean(stt_cloud.transcribe(audio, self.language, self.hint), len(audio))
            except stt_cloud.CloudEarError as e:
                log.warning("El oído en la nube falló (%s): transcribo en esta PC", e)
                model = self.local_model()
        else:
            model = self.model
        if model is None:
            return ""
        with self._lock:
            segments, _ = model.transcribe(
                audio, language=self.language, beam_size=1, temperature=0.0, vad_filter=False,
                condition_on_previous_text=False, initial_prompt=self.hint or None, without_timestamps=True)
            parts = [s.text.strip() for s in segments
                     if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)]
        return _clean(" ".join(p for p in parts if p).strip(), len(audio))

    def transcribe_media(self, audio: np.ndarray) -> str:
        """Sonido de la pantalla compartida (vídeos, juegos, llamadas): el idioma se detecta solo, el filtro de voz
        salta la música y el silencio, y sin la pista de nombres del usuario (no es él quien habla). Con el oído en
        la nube no se transcribe: serían 10 peticiones por minuto y agotarían la cuota del día en un rato."""
        if self.model is None or self.engine == "nube":
            return ""
        with self._lock:
            segments, _ = self.model.transcribe(
                audio, language=None, beam_size=1, temperature=0.0, vad_filter=True,
                condition_on_previous_text=False, without_timestamps=True)
            parts = [s.text.strip() for s in segments if not (s.no_speech_prob > 0.5 and s.avg_logprob < -0.7)]
        return _clean(" ".join(p for p in parts if p).strip(), len(audio))


def _clean(text: str, samples: int) -> str:
    """Quita lo que Whisper inventa sobre ruido o silencio (en tramos cortos)."""
    low = text.lower()
    if len(low) < 60 and any(h in low for h in HALLUCINATIONS) and samples < 16000 * 2.5:
        return ""
    return text
