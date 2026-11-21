"""Cliente WebSocket para la Gemini Live API (BidiGenerateContent).

Convierte al companion en una interfaz ligera conectada directamente a Gemini en tiempo real:
  entrada  → PCM 16 bits mono 16 kHz (micrófono), JPEG (cámara/pantalla) o texto
  salida   ← PCM 16 bits mono 24 kHz (voz nativa de Gemini), transcripciones de entrada/salida e interrupciones

Usa `websockets` (ya incluido con uvicorn[standard]) sin dependencias nuevas.
"""
import asyncio
import base64
import json
import logging
import re

import websockets

from .config import settings

log = logging.getLogger("companion.gemini_live")

WS_ENDPOINT = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
DEFAULT_MODEL = "gemini-3.1-flash-live-preview"
INPUT_RATE = 16000
OUTPUT_RATE = 24000

# Mapeo de las voces del catálogo del companion a voces predefinidas de Gemini Live API.
VOICE_MAP = {
    "mika": "Aoede",
    "natsumi": "Leda",
    "ayaka": "Kore",
    "chiaki": "Zephyr",
    "kenji": "Puck",
    "akira": "Orus",
    "goro": "Charon",
    "ryo": "Fenrir",
    "satoshi": "Charon",
}

LIVE_PROMPT_NOTE = (
    "\n\n[Modo Gemini Live activo: respondes directamente con tu propia voz en español, "
    "en frases naturales y breves como en una llamada. Mantén siempre al pie de la letra tu personalidad "
    "actual (tono, nivel de humor, muletillas, formalidad y estilo de las frases de ejemplo). "
    "No leas en voz alta ni escribas etiquetas entre corchetes como [emo:...], [gesto:...] ni [accion:...]. "
    "Cuando el usuario te pida abrir una aplicación, poner una canción en Apple Music/Spotify, abrir una web "
    "o carpeta, buscar un archivo, poner un temporizador o cambiar música/volumen, llama a la herramienta "
    "`ejecutar_accion` con la acción correspondiente.]"
)

# Herramienta nativa (Function Calling) para el catálogo cerrado de acciones en la PC.
ACTION_TOOLS = [{
    "name": "ejecutar_accion",
    "description": (
        "Ejecuta una acción segura en la PC del usuario. Úsala siempre que te pida abrir una aplicación, "
        "reproducir música o interactuar con una ventana (como Apple Music, Spotify o Word), abrir una web "
        "o carpeta, buscar archivos, poner un temporizador o controlar volumen/multimedia."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "accion": {
                "type": "STRING",
                "description": (
                    "Tipo de acción: 'abrir_app', 'controlar' (para manejar una app como reproducir una canción en "
                    "Apple Music o Spotify o escribir en Word), 'abrir_web', 'abrir_carpeta', 'buscar_archivo', "
                    "'temporizador', 'multimedia' o 'volumen'."
                ),
            },
            "arg1": {
                "type": "STRING",
                "description": (
                    "Argumento principal: nombre de la app (ej. 'Apple Music', 'Spotify'), URL o búsqueda, "
                    "carpeta, nombre de archivo, duración ('10m'), multimedia ('pausa'|'siguiente'|'anterior') "
                    "o volumen ('subir'|'bajar'|'silenciar'|'50%')."
                ),
            },
            "arg2": {
                "type": "STRING",
                "description": (
                    "Opcional. Para 'controlar': lo que debe hacer en esa app (ej. 'reproduce La Barca de Luis Miguel'). "
                    "Para 'temporizador': etiqueta opcional (ej. 'pasta')."
                ),
            },
        },
        "required": ["accion", "arg1"],
    },
}]

_TAG_RE = re.compile(r"\[[^\]]+\]")


class GeminiLiveError(RuntimeError):
    """Error de conexión o configuración con la Gemini Live API."""


def voice_for(voice_id: str | None, speaks: str = "f") -> str:
    """Devuelve la voz predefinida de Gemini Live más cercana al personaje elegido."""
    if settings.gemini_live_voice:
        return settings.gemini_live_voice
    if voice_id and voice_id in VOICE_MAP:
        return VOICE_MAP[voice_id]
    return "Puck" if speaks == "m" else "Aoede"


def model_uri(model: str | None = None) -> str:
    """Asegura el prefijo `models/` que exige BidiGenerateContent por WebSocket."""
    name = (model or settings.gemini_live_model or DEFAULT_MODEL).strip()
    return name if name.startswith("models/") else f"models/{name}"


def clean_spoken_text(text: str) -> str:
    """Limpia etiquetas tipo [emo:...] si el modelo llegara a incluirlas en la transcripción."""
    return _TAG_RE.sub("", text or "").strip()


class GeminiLiveClient:
    """Sesión bidireccional persistente con la Gemini Live API."""

    def __init__(
        self,
        api_key: str,
        system_instruction: str,
        *,
        model: str | None = None,
        voice_name: str = "Aoede",
        temperature: float | None = None,
        tools: list[dict] | None = None,
        ws_connect=None,
    ):
        self.api_key = (api_key or "").strip()
        self.system_instruction = system_instruction
        self.model = model_uri(model)
        self.voice_name = voice_name or "Aoede"
        self.temperature = temperature
        self.tools = tools or []
        self._ws_connect = ws_connect or websockets.connect
        self.ws = None
        self.connected = False
        self._send_lock = asyncio.Lock()

    def build_setup(self) -> dict:
        gen_cfg: dict = {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": self.voice_name}
                }
            },
        }
        if self.temperature is not None:
            gen_cfg["temperature"] = float(self.temperature)
        setup: dict = {
            "model": self.model,
            "generationConfig": gen_cfg,
            "systemInstruction": {
                "parts": [{"text": self.system_instruction + LIVE_PROMPT_NOTE}]
            },
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
        }
        if self.tools:
            setup["tools"] = [{"functionDeclarations": self.tools}]
        return {"setup": setup}

    async def connect(self, timeout: float = 15.0):
        if not self.api_key:
            raise GeminiLiveError("Falta la clave de API de Gemini para usar Gemini Live.")
        url = f"{WS_ENDPOINT}?key={self.api_key}"
        try:
            self.ws = await asyncio.wait_for(
                self._ws_connect(url, max_size=None, ping_interval=20, ping_timeout=20),
                timeout=timeout,
            )
            await self.ws.send(json.dumps(self.build_setup(), ensure_ascii=False))
            raw = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            msg = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            await self.close()
            raise GeminiLiveError(f"No se pudo conectar a Gemini Live ({type(e).__name__}: {e})") from e

        if "setupComplete" not in msg:
            await self.close()
            raise GeminiLiveError(f"Gemini Live rechazó la configuración inicial: {list(msg.keys())}")
        self.connected = True
        log.info("Gemini Live conectado (%s, voz %s)", self.model, self.voice_name)

    async def _send_json(self, payload: dict):
        if self.ws is None or not self.connected:
            raise GeminiLiveError("Gemini Live no está conectado.")
        try:
            async with self._send_lock:
                await self.ws.send(json.dumps(payload, ensure_ascii=False))
        except (websockets.exceptions.ConnectionClosed, OSError) as e:
            self.connected = False
            raise GeminiLiveError(f"Conexión con Gemini Live cerrada ({e})") from e

    async def send_audio(self, pcm_16k: bytes):
        """Envía audio PCM 16 bits mono 16 kHz en tiempo real."""
        if not self.connected or not pcm_16k:
            return
        await self._send_json({
            "realtimeInput": {
                "audio": {
                    "mimeType": f"audio/pcm;rate={INPUT_RATE}",
                    "data": base64.b64encode(pcm_16k).decode("ascii"),
                }
            }
        })

    async def send_image(self, jpeg_b64: str):
        """Envía una imagen JPEG (base64) de cámara o pantalla."""
        if not self.connected or not jpeg_b64:
            return
        await self._send_json({
            "realtimeInput": {
                "video": {
                    "mimeType": "image/jpeg",
                    "data": jpeg_b64,
                }
            }
        })

    async def send_text(self, text: str, end_of_turn: bool = True, images: list[str] | None = None):
        """Envía un mensaje de texto (y opcionalmente imágenes JPEG actuales) al turno."""
        if not self.connected or not text:
            return
        parts: list[dict] = [{"inlineData": {"mimeType": "image/jpeg", "data": img}} for img in (images or ()) if img]
        parts.append({"text": text})
        await self._send_json({
            "clientContent": {
                "turns": [{"role": "user", "parts": parts}],
                "turnComplete": bool(end_of_turn),
            }
        })

    async def send_tool_response(self, responses: list[dict]):
        """Devuelve a Gemini Live el resultado de una o más llamadas a herramientas (toolCall)."""
        if not self.connected or not responses:
            return
        await self._send_json({"toolResponse": {"functionResponses": responses}})

    async def receive(self):
        """Itera eventos normalizados del servidor:
        ('audio', bytes) | ('out_text', str) | ('in_text', str) | ('tool_call', list[dict])
        | ('interrupted', None) | ('turn_complete', None).
        """
        if self.ws is None:
            return
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                tc = msg.get("toolCall")
                if isinstance(tc, dict) and tc.get("functionCalls"):
                    yield ("tool_call", list(tc["functionCalls"]))
                sc = msg.get("serverContent")
                if not isinstance(sc, dict):
                    continue
                if sc.get("interrupted"):
                    yield ("interrupted", None)
                in_tr = sc.get("inputTranscription")
                if isinstance(in_tr, dict) and in_tr.get("text"):
                    yield ("in_text", str(in_tr["text"]))
                out_tr = sc.get("outputTranscription")
                if isinstance(out_tr, dict) and out_tr.get("text"):
                    yield ("out_text", str(out_tr["text"]))
                model_turn = sc.get("modelTurn")
                if isinstance(model_turn, dict):
                    for part in model_turn.get("parts") or ():
                        inline = part.get("inlineData") if isinstance(part, dict) else None
                        if isinstance(inline, dict) and inline.get("data"):
                            mime = str(inline.get("mimeType") or "")
                            if mime.startswith("audio/pcm") or not mime:
                                try:
                                    yield ("audio", base64.b64decode(inline["data"]))
                                except Exception:  # noqa: BLE001
                                    pass
                if sc.get("turnComplete"):
                    yield ("turn_complete", None)
        finally:
            self.connected = False

    async def close(self):
        self.connected = False
        ws, self.ws = self.ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
