"""Conversación en vivo con proveedores que siguen el protocolo de OpenAI Realtime (WebSocket).

Misma interfaz que `gemini_live.GeminiLiveClient` (connect, send_audio, send_image, send_text, send_tool_response,
receive, close), para que `Session` use cualquiera de los dos:
  entrada  → PCM 16 bits mono 16 kHz del micrófono (se remuestrea al ritmo que pida el proveedor), JPEG o texto
  salida   ← PCM 16 bits mono 24 kHz, transcripciones, llamadas a herramientas e interrupciones

Proveedores (`LIVE_PROVIDERS`, 21 nov 2026): OpenAI (protocolo GA), xAI Grok Voice y Qwen Omni Realtime (protocolo
«beta», el de antes del GA, que es el que clonan) y uno propio. Solo Gemini Live está probado con una clave de verdad;
los demás, con mensajes simulados (tests/test_realtime.py).
"""
import asyncio
import base64
import json
import logging

import numpy as np
import websockets

from .gemini_live import GeminiLiveError, LIVE_PROMPT_NOTE, SILENT_TOOLS

log = logging.getLogger("companion.realtime")

OUTPUT_RATE = 24000

# flavor: «ga» = OpenAI actual (session.type realtime, audio.input/output) · «beta» = campos planos (xAI, Qwen).
# rate: a qué ritmo quiere el audio de entrada. free: si tiene capa o cuota gratuita, cuál (texto para la interfaz).
LIVE_PROVIDERS = {
    "gemini": {"name": "Google Gemini Live", "free": "gratis con límite diario", "keys": "https://aistudio.google.com/apikey",
               "models": ["gemini-3.1-flash-live-preview"],
               "voices": ["Aoede", "Kore", "Leda", "Zephyr", "Puck", "Charon", "Fenrir", "Orus"],
               "voice": {"f": "Aoede", "m": "Puck"},
               "note": "Tiene capa gratuita (con límite diario). Usa la clave de Gemini del cerebro si no pones otra. Probado."},
    "openai": {"name": "OpenAI Realtime", "free": "", "keys": "https://platform.openai.com/api-keys",
               "url": "wss://api.openai.com/v1/realtime", "flavor": "ga", "rate": 24000,
               "models": ["gpt-realtime", "gpt-realtime-mini"],
               "voices": ["marin", "cedar", "coral", "shimmer", "sage", "alloy", "ash", "ballad", "echo", "verse"],
               "voice": {"f": "marin", "m": "cedar"},
               "note": "De pago (por minuto de audio, de los más caros). Sin probar aquí con una clave real."},
    "xai": {"name": "xAI Grok Voice", "free": "", "keys": "https://console.x.ai",
            "url": "wss://api.x.ai/v1/realtime", "flavor": "beta", "rate": 24000,
            "models": ["grok-voice-latest"],
            "voices": ["Ara", "Eve", "Rex", "Sal", "Leo"], "voice": {"f": "Ara", "m": "Rex"},
            "note": "De pago (unos 0,08 USD por minuto). Sin probar aquí con una clave real."},
    "qwen": {"name": "Qwen Omni Realtime (Alibaba)", "free": "cuota gratis al empezar", "keys": "https://modelstudio.console.alibabacloud.com",
             "url": "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime", "flavor": "beta", "rate": 16000,
             "out_format": "pcm24", "models": ["qwen3-omni-flash-realtime"],
             "voices": ["Cherry", "Serena", "Chelsie", "Ethan"], "voice": {"f": "Cherry", "m": "Ethan"},
             "note": "Cuota gratuita al abrir la cuenta y luego muy barato. Clave de la región internacional (Singapur). Sin probar aquí."},
    "custom": {"name": "Otro (compatible con OpenAI Realtime)", "free": "", "keys": "",
               "url": "", "flavor": "ga", "rate": 24000, "models": [], "voices": [], "voice": {"f": "", "m": ""},
               "note": "Escribe la dirección wss:// de su API (por ejemplo Azure OpenAI)."},
}


def voice_for(provider: str, speaks: str = "f") -> str:
    return LIVE_PROVIDERS.get(provider, LIVE_PROVIDERS["gemini"])["voice"].get("m" if speaks == "m" else "f", "")


def json_schema(tools: list[dict]) -> list[dict]:
    """Herramientas al formato de OpenAI: tipos de Gemini (OBJECT, STRING) en minúsculas."""
    def low(x):
        if isinstance(x, dict):
            return {k: (v.lower() if k == "type" and isinstance(v, str) else low(v)) for k, v in x.items()}
        if isinstance(x, list):
            return [low(v) for v in x]
        return x
    return [{"type": "function", "name": t["name"], "description": t.get("description", ""),
             "parameters": low(t.get("parameters") or {})} for t in tools]


def resample(pcm: bytes, src: int, dst: int) -> bytes:
    if src == dst or not pcm:
        return pcm
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n = int(len(x) * dst / src)
    if n <= 0:
        return b""
    y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return np.clip(y, -32768, 32767).astype(np.int16).tobytes()


class RealtimeClient:
    """Sesión con un proveedor compatible con OpenAI Realtime."""

    def __init__(self, api_key: str, system_instruction: str, *, provider: str = "openai", model: str | None = None,
                 voice_name: str = "", temperature: float | None = None, tools: list[dict] | None = None,
                 url: str | None = None, ws_connect=None):
        self.provider = provider if provider in LIVE_PROVIDERS else "custom"
        cfg = LIVE_PROVIDERS[self.provider]
        self.api_key = (api_key or "").strip()
        self.system_instruction = system_instruction
        self.model = (model or (cfg["models"][0] if cfg["models"] else "")).strip()
        self.voice_name = voice_name or cfg["voice"]["f"]
        self.temperature = temperature
        self.tools = tools or []
        self.url = (url or cfg.get("url") or "").strip()
        self.flavor = cfg.get("flavor", "ga")
        self.rate = int(cfg.get("rate", 24000))
        self.out_format = cfg.get("out_format", "pcm16")
        self._ws_connect = ws_connect or websockets.connect
        self.ws = None
        self.connected = False
        self._send_lock = asyncio.Lock()
        self._calls: dict[str, dict] = {}          # call_id → {name, args} hasta que llegan enteros
        self._responding = False

    # ---------------------------------------------------------------- configuración
    def build_session(self) -> dict:
        instructions = self.system_instruction + LIVE_PROMPT_NOTE
        tools = json_schema(self.tools)
        if self.flavor == "ga":
            session = {
                "type": "realtime", "model": self.model, "instructions": instructions,
                "output_modalities": ["audio"],
                "audio": {
                    "input": {"format": {"type": "audio/pcm", "rate": self.rate},
                              "transcription": {"model": "gpt-4o-mini-transcribe", "language": "es"},
                              "turn_detection": {"type": "server_vad", "interrupt_response": True}},
                    "output": {"format": {"type": "audio/pcm", "rate": OUTPUT_RATE}, "voice": self.voice_name},
                },
            }
        else:
            session = {
                "modalities": ["text", "audio"], "instructions": instructions, "voice": self.voice_name,
                "input_audio_format": "pcm16", "output_audio_format": self.out_format,
                "input_audio_transcription": {"model": "gummy-realtime-v1" if self.provider == "qwen" else "whisper-1"},
                "turn_detection": {"type": "server_vad"},
            }
            if self.temperature is not None and self.provider != "qwen":
                session["temperature"] = max(0.6, min(1.2, float(self.temperature)))
        if tools:
            session["tools"] = tools
            session["tool_choice"] = "auto"
        return {"type": "session.update", "session": session}

    def ws_url(self) -> str:
        if not self.url.startswith("wss://"):
            raise GeminiLiveError("Falta la dirección wss:// del proveedor en vivo.")
        if "model=" in self.url or not self.model:
            return self.url
        return f"{self.url}{'&' if '?' in self.url else '?'}model={self.model}"

    async def connect(self, timeout: float = 15.0):
        if not self.api_key:
            raise GeminiLiveError(f"Falta la clave de {LIVE_PROVIDERS[self.provider]['name']}.")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            url = self.ws_url()
            try:
                self.ws = await asyncio.wait_for(
                    self._ws_connect(url, additional_headers=headers, max_size=None, ping_interval=20, ping_timeout=20),
                    timeout=timeout)
            except TypeError:                                        # websockets antiguo
                self.ws = await asyncio.wait_for(
                    self._ws_connect(url, extra_headers=headers, max_size=None, ping_interval=20, ping_timeout=20),
                    timeout=timeout)
            await self.ws.send(json.dumps(self.build_session(), ensure_ascii=False))
            limit = asyncio.get_running_loop().time() + timeout
            while True:                                              # session.created y luego session.updated
                left = limit - asyncio.get_running_loop().time()
                msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=max(0.1, left)))
                if msg.get("type") == "error":
                    raise GeminiLiveError(_err(msg))
                if msg.get("type") == "session.updated":
                    break
        except GeminiLiveError:
            await self.close()
            raise
        except Exception as e:  # noqa: BLE001
            await self.close()
            raise GeminiLiveError(f"No se pudo conectar a {LIVE_PROVIDERS[self.provider]['name']} ({type(e).__name__})") from e
        self.connected = True
        log.info("En vivo conectado (%s, %s, voz %s)", self.provider, self.model, self.voice_name)

    async def _send(self, payload: dict):
        if self.ws is None or not self.connected:
            raise GeminiLiveError("La conversación en vivo no está conectada.")
        try:
            async with self._send_lock:
                await self.ws.send(json.dumps(payload, ensure_ascii=False))
        except (websockets.exceptions.ConnectionClosed, OSError) as e:
            self.connected = False
            raise GeminiLiveError(f"Se cerró la conexión en vivo ({type(e).__name__})") from e

    # ---------------------------------------------------------------- entrada
    async def send_audio(self, pcm_16k: bytes):
        if not self.connected or not pcm_16k:
            return
        pcm = resample(pcm_16k, 16000, self.rate)
        await self._send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode("ascii")})

    async def send_image(self, jpeg_b64: str):
        if not self.connected or not jpeg_b64:
            return
        if self.provider == "qwen":
            await self._send({"type": "input_image_buffer.append", "image": jpeg_b64})
            return
        await self._send({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user",
            "content": [{"type": "input_image", "image_url": f"data:image/jpeg;base64,{jpeg_b64}"}]}})

    async def send_text(self, text: str, end_of_turn: bool = True, images: list[str] | None = None):
        if not self.connected or not text:
            return
        content = [{"type": "input_image", "image_url": f"data:image/jpeg;base64,{img}"}
                   for img in (images or ()) if img and self.provider != "qwen"]
        content.append({"type": "input_text", "text": text})
        await self._send({"type": "conversation.item.create",
                          "item": {"type": "message", "role": "user", "content": content}})
        if end_of_turn:
            await self._create_response()

    async def _create_response(self):
        if self._responding:
            await self._send({"type": "response.cancel"})
        await self._send({"type": "response.create"})

    async def send_tool_response(self, responses: list[dict]):
        """Resultado de las herramientas. Tras una que no sea silenciosa se pide seguir hablando."""
        if not self.connected or not responses:
            return
        for r in responses:
            await self._send({"type": "conversation.item.create", "item": {
                "type": "function_call_output", "call_id": r.get("id", ""),
                "output": json.dumps(r.get("response") or {}, ensure_ascii=False)}})
        if any(r.get("name") not in SILENT_TOOLS for r in responses) and not self._responding:
            await self._send({"type": "response.create"})

    # ---------------------------------------------------------------- salida
    async def receive(self):
        """Los mismos eventos que GeminiLiveClient.receive."""
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
                for ev in self._events(msg):
                    yield ev
        finally:
            self.connected = False

    def _events(self, msg: dict):
        t = str(msg.get("type") or "")
        if t in ("response.output_audio.delta", "response.audio.delta"):
            try:
                yield ("audio", base64.b64decode(msg.get("delta") or ""))
            except Exception:  # noqa: BLE001
                pass
        elif t in ("response.output_audio_transcript.delta", "response.audio_transcript.delta",
                   "response.output_text.delta", "response.text.delta"):
            if msg.get("delta"):
                yield ("out_text", str(msg["delta"]))
        elif t == "conversation.item.input_audio_transcription.completed":
            if msg.get("transcript"):
                yield ("in_text", str(msg["transcript"]))
        elif t == "input_audio_buffer.speech_started":
            if self._responding:
                yield ("interrupted", None)
        elif t == "response.created":
            self._responding = True
        elif t == "response.function_call_arguments.done":
            try:
                args = json.loads(msg.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            yield ("tool_call", [{"id": msg.get("call_id", ""), "name": msg.get("name", ""), "args": args}])
        elif t == "response.done":
            self._responding = False
            resp = msg.get("response") or {}
            if resp.get("status") == "cancelled":
                return
            outputs = resp.get("output") or []
            if outputs and all(o.get("type") == "function_call" for o in outputs):
                return                                  # sigue tras send_tool_response (response.create)
            yield ("turn_complete", None)
        elif t == "error":
            err = msg.get("error") or {}
            if err.get("code") in ("response_cancel_not_active", "conversation_already_has_active_response"):
                return
            log.warning("En vivo (%s): %s", self.provider, _err(msg))

    async def close(self):
        self.connected = False
        ws, self.ws = self.ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass


def _err(msg: dict) -> str:
    err = msg.get("error") or {}
    return str(err.get("message") or err.get("code") or "error del proveedor en vivo")[:200]
