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

from .prompt import EMOTIONS, GESTURES  # noqa: E402

# Nota final del prompt en vivo. Los modelos en vivo atienden sobre todo a lo último del systemInstruction: por eso
# la personalidad se repite aquí en corto (live_recap) aunque ya esté entera más arriba (21 nov 2026: «en el modo
# Live la personalidad y las emociones se ignoran»).
LIVE_PROMPT_NOTE = (
    "\n\n# Modo en vivo (llamada de voz)\n"
    "Respondes con tu propia voz en español, en frases naturales y breves como en una llamada, y con TU forma de "
    "ser: el tono, el humor, las muletillas y el estilo de tus ejemplos se tienen que notar en cada respuesta. Nada "
    "de tono de asistente neutra.\n"
    "Tu cara y tu cuerpo se mueven con la herramienta `expresar`: llámala al EMPEZAR cada respuesta con la emoción "
    "que de verdad sientes ante lo que te dicen (y un gesto si viene a cuento), y otra vez si cambias de emoción. "
    "No cambia lo que dices ni hay que esperar su respuesta: sigue hablando.\n"
    "Nunca digas en voz alta etiquetas entre corchetes ([emo:…], [gesto:…], [accion:…]) ni el nombre de una herramienta.\n"
    "Cuando el usuario te pida abrir una aplicación, poner una canción en Apple Music/Spotify, abrir una web "
    "o carpeta, buscar un archivo, poner un temporizador o cambiar música/volumen, llama a la herramienta "
    "`ejecutar_accion` con la acción correspondiente."
)

EXPRESS_TOOL = {
    "name": "expresar",
    "description": ("Muestra en tu cara y tu cuerpo la emoción que sientes y, si viene a cuento, un gesto. "
                    "Llámala al empezar cada respuesta. No hace falta esperar su resultado."),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "emocion": {"type": "STRING", "enum": list(EMOTIONS)},
            "gesto": {"type": "STRING", "enum": ["ninguno", *GESTURES]},
        },
        "required": ["emocion"],
    },
}


def live_recap(p: dict, user_name: str) -> str:
    """Resumen corto de quién es el personaje ahora, para el final del prompt en vivo."""
    q = p.get("personality") or {}
    s = p.get("speech_style") or {}
    lines = [f"Recuerda quién eres: {p.get('name', 'tú')}"
             + (f", con la personalidad «{q['name']}»" if q.get("name") else "") + "."]
    if p.get("personality_text"):
        lines.append(str(p["personality_text"]))
    if q.get("emotions"):
        lines.append(f"Se te notan sobre todo: {', '.join(q['emotions'])}; tu ánimo de siempre es {q.get('base_mood', 'neutral')}.")
    if s.get("catchphrases"):
        lines.append(f"Tus muletillas (de vez en cuando): {', '.join(s['catchphrases'])}.")
    if q.get("examples"):
        lines.append("Suenas así: " + " · ".join(f"«{x}»" for x in q["examples"][:4]))
    lines.append(f"Hablas con {user_name}: reacciona a lo que siente y a cómo te habla, como lo harías tú.")
    return "\n".join(lines)


# Emoción deducida del texto mientras llega (la de `expresar` llega a los 3-4 s, ya hablando: medido el 21 nov 2026).
_EMO_WORDS = [
    ("triste", r"lo siento|qu[eé] pena|qu[eé] triste|qu[eé] mal|\bpobre|lamento|\bánimo"),
    ("molesta", r"\boye\b|qu[eé] pesad|no me gusta|me molesta|ya basta|qu[eé] rabia"),
    ("sorprendida", r"\bwow\b|en serio\?|de verdad\?|no me digas|no puede ser"),
    ("emocionada", r"qu[eé] emoci[oó]n|incre[ií]ble|felicidades|enhorabuena|me encanta|\bgenial\b"),
    ("sonrojada", r"me sonroj|qu[eé] cosas dices|ay,? (calla|para)"),
    ("carinosa", r"cari[nñ]o|aqu[ií] estoy|te quiero|mi vida|\babrazo"),
    ("feliz", r"\bjaj|\bjej|qu[eé] bien|me alegra|\bbonito|claro que s[ií]"),
    ("pensativa", r"\bhmm|d[eé]jame pensar|\ba ver\b|buena pregunta"),
    ("confundida", r"no entiendo|\bc[oó]mo\?|\bqu[eé] dices"),
    ("nerviosa", r"\beh+\.\.\.|\bum+\b|\bbueno\.\.\."),
]
_EMO_RES = [(e, re.compile(rx, re.IGNORECASE)) for e, rx in _EMO_WORDS]


def guess_emotion(text: str) -> str | None:
    """Emoción probable del principio de una respuesta (para que la cara reaccione ya, antes de `expresar`)."""
    for emo, rx in _EMO_RES:
        if rx.search(text or ""):
            return emo
    return None


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
                    "'temporizador', 'recordatorio' (con fecha/hora persistente), 'portapapeles' (leer lo copiado), "
                    "'multimedia' o 'volumen'."
                ),
            },
            "arg1": {
                "type": "STRING",
                "description": (
                    "Argumento principal: nombre de la app (ej. 'Apple Music', 'Spotify'), URL o búsqueda, "
                    "carpeta, nombre de archivo, duración ('10m'), fecha/hora del recordatorio ('mañana a las 9', "
                    "'hoy a las 18:30', 'en 2 horas'), 'leer' para portapapeles, multimedia ('pausa'|'siguiente'|'anterior') "
                    "o volumen ('subir'|'bajar'|'silenciar'|'50%')."
                ),
            },
            "arg2": {
                "type": "STRING",
                "description": (
                    "Opcional. Para 'controlar': lo que debe hacer en esa app (ej. 'reproduce La Barca de Luis Miguel'). "
                    "Para 'temporizador' o 'recordatorio': texto o etiqueta (ej. 'llamar al banco')."
                ),
            },
        },
        "required": ["accion", "arg1"],
    },
}]

# Herramienta silenciosa para guardar recuerdos duraderos durante una llamada en vivo.
REMEMBER_TOOL = {
    "name": "recordar",
    "description": (
        "Guarda un dato duradero e importante sobre el usuario (gustos, nombres de personas o mascotas, "
        "proyectos, planes con fecha) para recordarlo en futuras conversaciones. Nunca guardes contraseñas, "
        "documentos ni datos bancarios."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "dato": {
                "type": "STRING",
                "description": "El dato concreto en tercera persona (ej. 'A Danny le encanta el café sin azúcar').",
            }
        },
        "required": ["dato"],
    },
}

# `expresar` y `recordar` no frenan la voz: NON_BLOCKING en Gemini y respuesta SILENT (sin turno nuevo).
SILENT_TOOLS = {"expresar", "recordar"}


def gemini_tools(tools: list[dict]) -> list[dict]:
    return [{**t, "behavior": "NON_BLOCKING"} if t["name"] in SILENT_TOOLS else t for t in tools]

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
        resume_handle: str | None = None,
        ws_connect=None,
    ):
        self.api_key = (api_key or "").strip()
        self.system_instruction = system_instruction
        self.model = model_uri(model)
        self.voice_name = voice_name or "Aoede"
        self.temperature = temperature
        self.tools = tools or []
        self.resume_handle = (resume_handle or "").strip() or None
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
            # Permite sesiones largas sin corte de contexto y reanudación transparente tras ~10 min.
            "contextWindowCompression": {"slidingWindow": {}},
            "sessionResumption": {"handle": self.resume_handle} if self.resume_handle else {},
        }
        if self.tools:
            setup["tools"] = [{"functionDeclarations": gemini_tools(self.tools)}]
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
        out = []
        for r in responses:
            if r.get("name") in SILENT_TOOLS:
                r = {**r, "response": {**(r.get("response") or {}), "scheduling": "SILENT"}}
            out.append(r)
        await self._send_json({"toolResponse": {"functionResponses": out}})

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
                res_upd = msg.get("sessionResumptionUpdate")
                if isinstance(res_upd, dict) and res_upd.get("resumable") and res_upd.get("newHandle"):
                    self.resume_handle = str(res_upd["newHandle"])
                    yield ("resume_handle", self.resume_handle)
                if "goAway" in msg:
                    yield ("go_away", msg.get("goAway"))
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
