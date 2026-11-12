"""Ajustes del companion: se leen de .env (ver .env.example)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "si", "sí", "yes", "on")


def _list(name: str, default: str) -> list:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def _tts_token() -> str:
    """El servidor de voz propio (voz/servidor.py) solo escucha en esta PC y no pide token. TTS_TOKEN queda por
    si se apunta TTS_URL a un servidor de voz externo que sí lo pida."""
    return os.getenv("TTS_TOKEN", "").strip()


@dataclass
class Settings:
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "gemini").strip().lower())
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip())
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip())
    gemini_reasoning: str = field(default_factory=lambda: os.getenv("GEMINI_REASONING", "minimal").strip())
    # La capa gratuita limita las peticiones diarias POR MODELO (20 al día en gemini-3.6-flash, medido el
    # 11 nov 2026). Cuando un modelo se agota se pasa al siguiente de esta lista y, al final, al modelo local.
    # gemma-4-26b-a4b-it va con la misma clave y tiene una cuota gratuita mucho mayor.
    gemini_fallback: list = field(default_factory=lambda: _list(
        "GEMINI_FALLBACK", "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemma-4-26b-a4b-it"))
    local_fallback: bool = field(default_factory=lambda: _bool("LOCAL_FALLBACK", True))
    gemini_base: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    # Proveedor de la nube elegido en la bienvenida (profile.py lo rellena): gemini u otro compatible con OpenAI.
    cloud_preset: str = "gemini"
    cloud_base: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    cloud_model: str = ""
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"))
    # El modelo local comparte los 16 GB de la GPU con la voz (~5 GB) y Whisper (~2 GB): tiene que ser pequeño.
    # gemma4:12b no cabe (medido el 11 nov 2026). Si el principal no cabe se pasa a los de OLLAMA_FALLBACK.
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "gemma4:e4b-it-qat").strip())
    ollama_fallback: list = field(default_factory=lambda: _list("OLLAMA_FALLBACK", "gemma4:e2b-it-qat"))
    ollama_num_ctx: int = field(default_factory=lambda: int(os.getenv("OLLAMA_NUM_CTX", "8192")))
    ollama_keep_alive: str = field(default_factory=lambda: os.getenv("OLLAMA_KEEP_ALIVE", "15m").strip())
    ollama_timeout: float = field(default_factory=lambda: float(os.getenv("OLLAMA_TIMEOUT", "45")))

    # Mirada en vivo: mientras se comparte la cámara o la pantalla, Mika mira por su cuenta y comenta.
    watch_interval: float = field(default_factory=lambda: float(os.getenv("WATCH_INTERVAL", "7")))    # s entre miradas
    watch_gap: float = field(default_factory=lambda: float(os.getenv("WATCH_GAP", "20")))             # s entre comentarios
    # Con el cerebro en la nube la mirada usa solo este modelo (cuota aparte de la conversación).
    watch_model: str = field(default_factory=lambda: os.getenv("WATCH_MODEL", "gemma-4-26b-a4b-it").strip())

    persona_path: Path = field(default_factory=lambda: _path(os.getenv("PERSONA", "personas/mika.json")))
    user_name: str = field(default_factory=lambda: os.getenv("USER_NAME", "").strip() or os.getenv("USERNAME", "amigo"))
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "America/Lima").strip())

    tts_url: str = field(default_factory=lambda: os.getenv("TTS_URL", "http://127.0.0.1:8210").rstrip("/"))
    tts_token: str = field(default_factory=_tts_token)
    tts_voice: str = field(default_factory=lambda: os.getenv("TTS_VOICE", "mika_es").strip())
    # completa = servidor de voz propio, voz/servidor.py (F5-TTS, voces clonadas) · ligera = Piper en el procesador
    voice_engine: str = field(default_factory=lambda: os.getenv("VOICE_ENGINE", "completa").strip().lower())

    # large-v3-turbo: en la RTX 5070 Ti ocupa 1,1 GB (large-v3: 2,2 GB), transcribe 3 veces más rápido y acierta
    # lo mismo en español (medido el 11 nov 2026). float16 no mejora la velocidad y duplica la memoria.
    stt_model: str = field(default_factory=lambda: os.getenv("STT_MODEL", "large-v3-turbo").strip())
    stt_device: str = field(default_factory=lambda: os.getenv("STT_DEVICE", "auto").strip().lower())
    stt_compute: str = field(default_factory=lambda: os.getenv("STT_COMPUTE", "int8_float16").strip())
    stt_language: str = field(default_factory=lambda: os.getenv("STT_LANGUAGE", "es").strip())

    end_silence_ms: int = field(default_factory=lambda: int(os.getenv("END_SILENCE_MS", "550")))
    barge_in: bool = field(default_factory=lambda: _bool("BARGE_IN", True))

    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1").strip())
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8200")))

    web_dir: Path = ROOT / "web"
    # MODELS_DIR y DATA_DIR solo se cambian en las pruebas, para no tocar los modelos ni la conversación reales.
    models_dir: Path = field(default_factory=lambda: _path(os.getenv("MODELS_DIR", "models")))
    data_dir: Path = field(default_factory=lambda: _path(os.getenv("DATA_DIR", "data")))

    # ---- reglas derivadas -------------------------------------------------
    @property
    def is_cloud(self) -> bool:
        return self.llm_provider != "local"

    @property
    def model_name(self) -> str:
        return self.gemini_model if self.is_cloud else self.ollama_model


settings = Settings()
settings.models_dir.mkdir(parents=True, exist_ok=True)
settings.data_dir.mkdir(parents=True, exist_ok=True)
