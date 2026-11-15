"""Oído: transcripción local con faster-whisper (GPU si se puede, CPU si no)."""
import logging
import os
import site
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


class Transcriber:
    def __init__(self, model: str, device: str, compute: str, language: str, hint: str = ""):
        self.model_name, self.want_device, self.compute = model, device, compute
        self.language, self.hint = language, hint
        self.model = None
        self.device = None
        self.error: str | None = None
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self.model is not None

    def load(self):
        from faster_whisper import WhisperModel as _Whisper

        def WhisperModel(name, **kw):       # el modelo que trajo el instalador a models/whisper; si no, se descarga
            local = ROOT / "models" / "whisper" / name
            return _Whisper(str(local) if (local / "model.bin").is_file() else name, **kw)

        silence = np.zeros(8000, dtype=np.float32)
        if self.want_device in ("auto", "cuda"):
            try:
                _add_cuda_dlls()
                model = WhisperModel(self.model_name, device="cuda", compute_type=self.compute)
                list(model.transcribe(silence, language=self.language, beam_size=1)[0])   # fuerza la carga de las DLL
                self.model, self.device = model, "cuda"
                log.info("Whisper %s en GPU (%s)", self.model_name, self.compute)
                return
            except Exception as e:  # noqa: BLE001
                log.warning("Whisper no pudo usar la GPU (%s); paso a CPU", e)
                if self.want_device == "cuda":
                    self.error = str(e)
                    return
        try:
            name = self.model_name if self.want_device == "cpu" else "small"   # large en CPU sería muy lento
            self.model, self.device = WhisperModel(name, device="cpu", compute_type="int8"), "cpu"
            self.model_name = name
            log.info("Whisper %s en CPU", name)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            log.error("No se pudo cargar Whisper: %s", e)

    def transcribe(self, audio: np.ndarray) -> str:
        """audio: float32 mono a 16 kHz. Devuelve el texto, o '' si no hubo habla reconocible."""
        if self.model is None:
            return ""
        with self._lock:
            segments, _ = self.model.transcribe(
                audio, language=self.language, beam_size=1, temperature=0.0, vad_filter=False,
                condition_on_previous_text=False, initial_prompt=self.hint or None, without_timestamps=True)
            parts = [s.text.strip() for s in segments
                     if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)]
        return _clean(" ".join(p for p in parts if p).strip(), len(audio))

    def transcribe_media(self, audio: np.ndarray) -> str:
        """Sonido de la pantalla compartida (vídeos, juegos, llamadas): el idioma se detecta solo, el filtro de voz
        salta la música y el silencio, y sin la pista de nombres del usuario (no es él quien habla)."""
        if self.model is None:
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
