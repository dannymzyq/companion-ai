"""Una conversación en vivo: micrófono → VAD → Whisper → LLM → voz → avatar.

Protocolo del WebSocket (/ws):
  cliente → servidor   binario: PCM 16 bits mono 16 kHz del micrófono
                       {"type":"start"} · {"type":"text","text":"..."} · {"type":"interrupt"} · {"type":"playback_end"}
                       {"type":"screen_audio","pcm":"<base64 PCM 16 bits 16 kHz, ~1 s>"} · {"type":"screen_audio_stop"}
  servidor → cliente   {"type":"state","value":"idle|listening|thinking|speaking"}
                       {"type":"user_text","text":"..."}
                       {"type":"sentence","id":n,"text":"...","emotion":"feliz"|null,"gestures":[...]}
                       binario: PCM 16 bits mono 24 kHz de esa frase · {"type":"sentence_end","id":n}
                       {"type":"reply_end","text":"..."} · {"type":"interrupt"} · {"type":"error","message":"..."}
  acciones             servidor → {"type":"action_request","id","title","detail","note"} · {"type":"action_done","id","ok","text"}
                       cliente → {"type":"action_answer","id","answer":"allow|always|deny"}
"""
import asyncio
import base64
import json
import logging
import os
import re
import time
from collections import deque

import numpy as np

from . import actions, gemini_live, llm, realtime, mood, personality, play, profile, screen_audio, store, tts, voicecheck, voz_proc
from .config import settings, shown
from .prompt import (ACTION_FAILED, ACTION_RESULT, OBSERVE, POKE, REMINDER_DONE, SUMMARIZE, TIMER_DONE, adult_active,
                     build_system_prompt, local_time, poke_text, sampling_for, turn_context)
from .tags import Sentence, TagStream
from .vad import FRAME, FRAME_MS, StreamingVAD

log = logging.getLogger("companion.session")

START_THR, START_FRAMES = 0.5, 3          # empezar a escuchar: ~100 ms de voz
BARGE_THR, BARGE_FRAMES = 0.6, 8          # interrumpirla mientras habla: ~250 ms de voz clara
END_THR = 0.35
PREROLL_FRAMES = 50                       # se recuerdan los últimos ~1,6 s de micrófono
PREROLL_GAP, PREROLL_PAD = 12, 8          # hueco máximo entre palabras y margen antes de la primera
MIN_SPEECH_FRAMES = 6                     # menos de ~200 ms de voz es ruido
MAX_UTTERANCE_MS = 30_000
EARLY_STT_MS = 220                        # silencio tras el cual se adelanta la transcripción
HISTORY_KEEP, HISTORY_MAX = 14, 28        # el historial crece hasta MAX mensajes y entonces se recorta a KEEP
FRAME_SOURCES = ("camera", "screen")
CLIP_STEP, CLIP_FRAMES = 1.8, 3           # mirada en vivo: una imagen cada ~2 s, las tres últimas
WATCH_QUIET = 5.0                         # silencio mínimo tras lo último que se dijo antes de mirar por su cuenta
WATCH_WINDOW = 9.0                        # solo cuentan imágenes de los últimos segundos
WATCH_MOTION = 0.018                      # cambio mínimo entre imágenes (0..1) para que valga la pena mirar
SUMMARY_MIN, SUMMARY_QUIET = 8, 12.0      # se resume cuando hay al menos 8 mensajes viejos y 12 s de calma
POKE_GAP, POKE_GAP_CLOUD = 25.0, 60.0    # entre comentarios de toques o miradas (con la nube, cuota)
SYSTEM_SUMMARIES = 8                      # resúmenes más recientes que van siempre en el prompt de sistema
_SILENCE_TAG =re.compile(r"\[\s*silencio", re.I)
_SILENCE_ONLY = re.compile(r"(\[[^\]]*\]|\W)*silencio(\[[^\]]*\]|\W)*", re.I)
FRAME_MAX_AGE = 6.0                       # una imagen más vieja que esto ya no cuenta como «lo que ve ahora»
FRAME_MAX_B64 = 4_000_000
_TITLE_JUNK = re.compile(r"[^\w .,:;()\-–—/&+'!?@#%]+")   # el título de una ventana va al LLM: sin saltos ni corchetes

ACTION_TTL = 120.0                        # una tarjeta de permiso sin responder caduca a los 2 minutos
# «Sí» o «no» dichos (o escritos) mientras hay una tarjeta de permiso abierta: responden a la tarjeta
_YES = re.compile(r"^(si|dale|hazlo|adelante|ok|okey|okay|vale|claro|de acuerdo|permitir|permitelo|permito|acepto|venga|va|por favor)\b")
_NO = re.compile(r"^(no|nop|cancela|cancelala|cancelalo|niegala|niego|mejor no|dejalo|deja)\b")
_STOP = re.compile(r"^(para|parar|paralo|detente|deten|stop|basta|alto|cancela|quieto|quieta|suelta)\b")
SHORT_SENTENCE, SHORT_WAIT = 22, 1.2      # una frase más corta se junta con la siguiente si llega en ese tiempo
# En modo rápido: se juntan las de menos de 60 letras, hasta 90 en total (la voz parte en sus comas lo que pase de
# 90 en ese modo, VOZ_LARGA: juntar más no ahorraría peticiones).
FAST_MERGE, FAST_MERGE_MAX = 60, 90
VOICE_RETRIES = 2                         # veces que se repite una frase si la voz se comió una palabra
CONFIRM_TTL = 60.0                       # un paso delicado sin confirmar en 1 minuto no se hace

GREETING = ("(El usuario acaba de abrir la aplicación y todavía no ha dicho nada. Salúdale con naturalidad, "
            "en una sola frase corta, según la hora.)")
_FACT = re.compile(r"^\W*dato\s*:\s*(.+)$", re.I)
_PRIVATE = re.compile(r"\d[\d \-.]{5,}\d|contraseñ|password|clave|pin\b|tarjeta|cuenta bancaria|dni|pasaporte", re.I)


# Temporizadores: viven en el servidor, no en la conexión. Si la ventana se recarga o se reconecta mientras
# corren, avisan en la conexión que esté abierta cuando acaben (o en la siguiente que se abra).
_open: list["Session"] = []
_timers: set[asyncio.Task] = set()
_missed: list[actions.Request] = []


def _start_timer(req: actions.Request):
    task = asyncio.create_task(_run_timer(req))
    _timers.add(task)
    task.add_done_callback(_timers.discard)


async def _run_timer(req: actions.Request):
    await asyncio.sleep(req.target["seconds"])
    s = next((x for x in reversed(_open) if not x.closed), None)
    if s is None:
        _missed.append(req)
    else:
        await s._timer_done(req)


def split_summary(text: str) -> tuple[str, list[str]]:
    """El resumen de un tramo de conversación y los datos duraderos (líneas «DATO: …») que el modelo sacó de él.
    Un dato que parece privado (números largos, claves, documentos) no se guarda."""
    summary, facts = [], []
    for line in re.sub(r"\[[^\]]*\]", "", text).splitlines():
        m = _FACT.match(line.strip())
        if m:
            fact = m.group(1).strip().strip("«»\"' ")
            if 8 <= len(fact) <= 200 and not _PRIVATE.search(fact) and len(facts) < 3:
                facts.append(fact)
        elif line.strip():
            summary.append(line.strip())
    return " ".join(summary).strip(), facts


class Session:
    def __init__(self, ws, persona: dict, transcriber):
        self.ws, self.base_persona, self.stt = ws, persona, transcriber
        self.vad = StreamingVAD()
        self.pcm = np.zeros(0, dtype=np.int16)
        self.preroll: deque = deque(maxlen=PREROLL_FRAMES)
        self.in_speech = False
        self.run = self.silence = self.speech_frames = 0
        self.utter: list[np.ndarray] = []
        self.early_stt: asyncio.Future | None = None

        self.turn: asyncio.Task | None = None
        self.phase = "idle"               # idle | stt | llm | audio
        self.turn_audio: np.ndarray | None = None
        self.turn_text: str | None = None
        self.carry_audio: np.ndarray | None = None   # lo que dijo antes de una pausa, aún sin transcribir
        self.carry_text = ""                         # ídem, ya transcrito
        self.sent_sentences: list[str] = []
        self.frames: dict[str, tuple[str, float, str, str]] = {}   # origen → (JPEG base64, cuándo llegó, qué es, título)
        self.ear = screen_audio.ScreenEar(transcriber)            # el sonido de la pantalla compartida, transcrito

        self.anchor = store.anchor(HISTORY_KEEP)           # primer mensaje del historial que se envía al LLM
        self.watch = False                                 # mirada en vivo (la activa la interfaz)
        self.watcher: asyncio.Task | None = None
        self.clips: dict[str, deque] = {}                  # origen → últimas imágenes espaciadas (jpeg, cuándo, qué, título)
        self.motion: dict[str, float] = {}                 # origen → mayor cambio visto desde la última mirada
        self.comments: deque = deque(maxlen=3)             # lo último que comentó por su cuenta (para no repetirse)
        self.last_talk = time.monotonic()                  # última vez que alguien habló
        self.last_poke = -1e9                               # último comentario de un toque o una mirada
        self.last_comment = 0.0
        self.summary_retry = 0.0

        self.client_playing = False
        self.play_started = 0.0
        self.audio_bytes = 0
        self.state = "idle"
        self.emotion = "neutral"
        self._send_lock = asyncio.Lock()
        self.closed = False
        self.pending: dict[str, actions.Request] = {}     # acciones esperando permiso (id → petición)
        self.side: set[asyncio.Task] = set()               # temporizadores y respuestas tras una acción
        self.outcomes: list[str] = []                      # cómo acabaron sus acciones; van con el siguiente mensaje
        self.confirms: dict[str, asyncio.Future] = {}      # pasos delicados del control esperando un «sí»
        self.controlling: dict | None = None               # la tarea de ratón y teclado en curso
        self.control_stop = False
        # Gemini Live API (sesión bidireccional directa: oído + cerebro + visión + voz)
        self.live: gemini_live.GeminiLiveClient | None = None
        self.live_task: asyncio.Task | None = None
        self._live_lock = asyncio.Lock()
        self._live_factory = None                          # inyectable en pruebas
        self._live_frame_at = 0.0
        self._live_sentence_id = 0
        self._live_turn_open = False
        self._live_in_tool = False
        self._live_gesture: str | None = None
        self._live_pcm_buf = bytearray()
        self._live_in_buf: list[str] = []
        self._live_out_buf: list[str] = []
        self._live_user = False                            # el turno lo empezó el usuario (texto o micrófono)
        self._live_screen_at = 0.0                         # último sonido de la pantalla enviado a Gemini
        self._live_mixed = False                           # en este turno pudo hablar la pantalla, no el usuario
        self._live_emo = ""                                # «tool»: la dio `expresar` · «guess»: deducida del texto
        self._live_ctx_at = 0.0                            # última vez que se le pasó la hora y el ánimo
        self._live_resume_handle: str | None = None        # token de reanudación de Gemini Live (rotación sin perder hilo)

    # ------------------------------------------------------------ envío
    async def send_json(self, data: dict):
        if self.closed:
            return
        try:
            async with self._send_lock:
                await self.ws.send_text(json.dumps(data, ensure_ascii=False))
        except Exception:  # noqa: BLE001  (la ventana se cerró)
            self.closed = True

    async def send_bytes(self, data: bytes):
        if self.closed:
            return
        try:
            async with self._send_lock:
                await self.ws.send_bytes(data)
        except Exception:  # noqa: BLE001
            self.closed = True

    async def set_state(self, value: str):
        if value != self.state:
            self.state = value
            await self.send_json({"type": "state", "value": value})

    # ------------------------------------------------------------ entrada
    async def on_message(self, data: dict):
        kind = data.get("type")
        if kind == "text":
            text = str(data.get("text", "")).strip()[:2000]
            if text:
                if self._is_live():
                    await self._live_send_text(text, show_user=True)
                    return
                await self.interrupt()
                self.turn = asyncio.create_task(self._guard(self._run_turn(text)))
        elif kind == "start":
            if self._is_live():
                await self._live_send_text(GREETING, show_user=False)
                return
            if not self.busy:
                self.turn = asyncio.create_task(self._guard(self._run_turn(None, instruction=GREETING)))
        elif kind in ("touch", "look"):
            await self._poke(kind, str(data.get("zone") or data.get("kind") or ""), int(data.get("level") or 0))
        elif kind == "interrupt":
            if self._is_live():
                self._live_turn_open = False
                self.client_playing = False
                self._live_out_buf.clear()
                await self.send_json({"type": "interrupt"})
                await self.set_state("idle")
                return
            await self.interrupt()
            await self.set_state("idle")
        elif kind == "frame":
            # Última imagen de la cámara o de la pantalla. Solo se guarda la más reciente, en memoria.
            source, jpeg = data.get("source"), data.get("jpeg")
            if source in FRAME_SOURCES and isinstance(jpeg, str) and jpeg.startswith("/9j/") and len(jpeg) <= FRAME_MAX_B64:
                # De la pantalla se sabe además si es entera o una sola ventana (y su título, que es texto ajeno).
                window = source == "screen" and data.get("surface") == "window"
                name = _TITLE_JUNK.sub(" ", str(data.get("name") or "")).strip()[:80] if window else ""
                now = time.monotonic()
                frame = (jpeg, now, "window" if window else source, name)
                first = source not in self.frames
                self.frames[source] = frame
                clip = self.clips.setdefault(source, deque(maxlen=CLIP_FRAMES))
                if not clip or now - clip[-1][1] >= CLIP_STEP:
                    # Para la mirada en vivo se guarda la copia pequeña, si vino: se lee mucho más rápido.
                    thumb = data.get("thumb")
                    small = isinstance(thumb, str) and thumb.startswith("/9j/") and len(thumb) <= FRAME_MAX_B64
                    clip.append((thumb, *frame[1:]) if small else frame)
                try:
                    delta = 1.0 if first else min(1.0, max(0.0, float(data.get("delta") or 0)))
                except (TypeError, ValueError):
                    delta = 0.0
                self.motion[source] = max(self.motion.get(source, 0.0), delta)
                if self._is_live() and self.live and self.live.connected and now - self._live_frame_at >= 1.0:
                    self._live_frame_at = now
                    self._spawn(self._live_send_image(jpeg))
        elif kind == "frame_stop":
            for box in (self.frames, self.clips, self.motion):
                box.pop(data.get("source"), None)
            if data.get("source") == "screen":
                self.ear.clear()
        elif kind == "screen_audio":
            # Solo mientras se comparte la pantalla, y nunca mientras suena Mika (el sonido de la PC trae su voz).
            if "screen" not in self.frames:
                return
            if self._is_live():
                if self.client_playing or self._live_in_tool:
                    return
                b64 = data.get("pcm")
                if not isinstance(b64, str) or not b64:
                    return
                try:
                    raw_pcm = base64.b64decode(b64, validate=True)
                except Exception:  # noqa: BLE001
                    return
                if len(raw_pcm) % 2:
                    raw_pcm = raw_pcm[:-1]
                if not raw_pcm:
                    return
                client = await self._ensure_live()
                if client:
                    self._live_screen_at = time.monotonic()
                    try:
                        # Trozos de 100 ms (3200 bytes a 16 kHz mono 16-bit) para no saturar el socket
                        for i in range(0, len(raw_pcm), 3200):
                            await client.send_audio(raw_pcm[i:i + 3200])
                    except gemini_live.GeminiLiveError as e:
                        log.warning("Gemini Live screen_audio error: %s", e)
                return
            audio = screen_audio.decode(data.get("pcm"))
            if audio is None:
                return
            if getattr(self.stt, "device", None) != "cuda":
                # En el procesador, Whisper tarda más que el propio sonido y frenaría lo que dice el usuario.
                if not self.ear.told:
                    self.ear.told = True
                    await self.send_json({"type": "notice", "message": "Para escuchar el sonido de la pantalla hace falta "
                                          "que el oído use la tarjeta NVIDIA; en esta PC solo ve la imagen."})
                return
            if self.client_playing:
                self.ear.drop_buffer()
                return
            self.ear.feed(audio)
            self.ear.maybe_transcribe(can_wait=self.in_speech or self.phase == "stt")
        elif kind == "screen_audio_stop":
            self.ear.clear()
        elif kind == "watch":
            self.watch = bool(data.get("on"))
        elif kind == "action_answer":
            # Solo la interfaz (o la voz del usuario, en _run_turn) aprueba una acción; el modelo no puede.
            answer = data.get("answer")
            fut = self.confirms.pop(str(data.get("id", "")), None)
            if fut is not None:                     # un paso delicado del control de una ventana
                if not fut.done():
                    fut.set_result(answer in ("allow", "always"))
                return
            req = self.pending.pop(str(data.get("id", "")), None)
            if req and answer in ("allow", "always", "deny"):
                await self._answer(req, answer)
        elif kind == "control_stop":
            self.control_stop = True
        elif kind == "playback_end":
            self.last_talk = time.monotonic()
            self.client_playing = False
            if not self.turn_running and not self.in_speech:
                await self.set_state("idle")

    async def on_audio(self, data: bytes):
        if len(data) % 2:
            data = data[:-1]
        if self._is_live():
            if self._live_in_tool or (self.client_playing and not settings.barge_in):
                self._live_pcm_buf.clear()
                return
            self._live_pcm_buf.extend(data)
            if len(self._live_pcm_buf) < 3072:       # ~96 ms a 16 kHz mono 16-bit (reduce 3x la carga de tramas WS)
                return
            chunk = bytes(self._live_pcm_buf)
            self._live_pcm_buf.clear()
            client = await self._ensure_live()
            if client:
                try:
                    await client.send_audio(chunk)
                except gemini_live.GeminiLiveError as e:
                    log.warning("Gemini Live audio error: %s", e)
            return
        self.pcm = np.concatenate([self.pcm, np.frombuffer(data, dtype=np.int16)])
        while len(self.pcm) >= FRAME:
            frame, self.pcm = self.pcm[:FRAME], self.pcm[FRAME:]
            await self._frame(frame.astype(np.float32) / 32768.0)

    async def _frame(self, frame: np.ndarray):
        p = self.vad.prob(frame)
        if self.client_playing and time.monotonic() > self.play_started + self.audio_bytes / 48000 + 1.5:
            self.client_playing = False       # red de seguridad si la interfaz no avisó del fin del audio

        if not self.in_speech:
            self.preroll.append((frame, p))
            if self.client_playing and not settings.barge_in:
                self.run = 0
                return
            if self.client_playing:           # mientras ella habla se exige voz clara y sostenida
                self.run = self.run + 1 if p >= BARGE_THR else max(0, self.run - 1)
                need = BARGE_FRAMES
            else:
                self.run = self.run + 1 if p >= START_THR else 0
                need = START_FRAMES
            if self.run >= need:
                self.in_speech = True
                self.utter = self._speech_start()
                self.preroll.clear()
                self.speech_frames, self.silence, self.run = self.run, 0, 0
                await self.interrupt()
                await self.set_state("listening")
            return

        self.utter.append(frame)
        if p >= END_THR:
            self.silence = 0
            self.speech_frames += 1
            self.early_stt = None             # siguió hablando: la transcripción adelantada ya no sirve
        else:
            self.silence += 1
            # Adelanto: en cuanto hay un silencio corto se empieza a transcribir, sin esperar a confirmar
            # el fin del turno. Si no vuelve a hablar, el texto ya está listo cuando el turno termina.
            if (self.early_stt is None and self.silence * FRAME_MS >= EARLY_STT_MS and self.carry_audio is None
                    and self.speech_frames >= MIN_SPEECH_FRAMES and self.stt.ready):
                self.early_stt = asyncio.get_running_loop().run_in_executor(
                    None, self.stt.transcribe, np.concatenate(self.utter))
        if self.silence * FRAME_MS >= settings.end_silence_ms or len(self.utter) * FRAME_MS > MAX_UTTERANCE_MS:
            self.in_speech = False
            self.last_talk = time.monotonic()
            audio, frames, self.utter = np.concatenate(self.utter), self.speech_frames, []
            early, self.early_stt = self.early_stt, None
            if frames < MIN_SPEECH_FRAMES and self.carry_audio is None and not self.carry_text:
                await self.set_state("idle")
                return
            self.turn = asyncio.create_task(self._guard(self._voice_turn(audio, early)))

    def _speech_start(self) -> list[np.ndarray]:
        """Tramas guardadas desde donde de verdad empezó a hablar (no solo desde que se confirmó la voz),
        para no perder las primeras palabras, sobre todo al interrumpir."""
        items = list(self.preroll)
        start, gap = len(items) - 1, 0
        for i in range(len(items) - 1, -1, -1):
            if items[i][1] >= END_THR:
                start, gap = i, 0
            else:
                gap += 1
                if gap > PREROLL_GAP:
                    break
        return [f for f, _ in items[max(0, start - PREROLL_PAD):]]

    # ------------------------------------------------------------ turnos
    @property
    def turn_running(self) -> bool:
        return self.turn is not None and not self.turn.done()

    @property
    def busy(self) -> bool:
        return self.turn_running or self.client_playing

    async def interrupt(self):
        """Corta lo que esté pensando o diciendo. Si aún no había empezado a hablar, lo que dijo el
        usuario no se pierde: se une a lo siguiente que diga (pausas a mitad de una idea)."""
        if not self.busy:
            return
        task, self.turn = self.turn, None
        if task and not task.done():
            early = self.phase in ("stt", "llm")
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if early:
                if self.turn_text:
                    self.carry_text = self.turn_text
                elif self.turn_audio is not None:
                    self.carry_audio = self.turn_audio
        self.phase, self.turn_text, self.turn_audio = "idle", None, None
        self.client_playing = False
        await self.send_json({"type": "interrupt"})

    async def _guard(self, coro):
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Error en el turno")
            self.phase = "idle"
            await self.send_json({"type": "error", "message": "Algo falló al responder. Mira la consola del companion."})
            await self.set_state("idle")

    async def _voice_turn(self, audio: np.ndarray, early: asyncio.Future | None = None):
        if self.carry_audio is not None:
            audio = np.concatenate([self.carry_audio, np.zeros(4800, dtype=np.float32), audio])
            self.carry_audio, early = None, None
        self.phase, self.turn_audio, self.turn_text = "stt", audio, None
        await self.set_state("thinking")
        t0 = time.perf_counter()
        if early is not None:
            text = await early
        else:
            text = await asyncio.get_running_loop().run_in_executor(None, self.stt.transcribe, audio)
        log.info("STT %.2fs de espera%s (%.1fs de audio): %s", time.perf_counter() - t0,
                 " (adelantado)" if early is not None else "", len(audio) / 16000, shown(text))
        if not text and not self.carry_text:
            self.phase, self.turn_audio = "idle", None
            await self.set_state("speaking" if self.client_playing else "idle")
            return
        await self._run_turn(text, t0=t0)

    async def _run_turn(self, text: str | None, instruction: str | None = None, t0: float | None = None):
        t0 = t0 or time.perf_counter()
        msg_id = None
        said = re.sub(r"[^\w\s]", " ", actions._plain(text)).strip() if text is not None else ""
        if self.controlling and said and _STOP.match(said) and len(said.split()) <= 4:
            self.control_stop = True                         # «para» detiene el control de la ventana
            await self.send_json({"type": "user_text", "text": text})
            self.phase, self.turn_text, self.turn_audio = "idle", None, None
            return
        if text is not None and (self.pending or self.confirms):
            verdict = "allow" if _YES.match(said) else "deny" if _NO.match(said) else None
            if verdict and len(said.split()) <= 4:          # «sí» o «no» responde a la tarjeta, no va al modelo
                await self.send_json({"type": "user_text", "text": text})
                for cid, fut in list(self.confirms.items()):
                    self.confirms.pop(cid, None)
                    if not fut.done():
                        fut.set_result(verdict == "allow")
                for req in list(self.pending.values()):
                    self.pending.pop(req.id, None)
                    await self._answer(req, verdict)
                self.phase, self.turn_text, self.turn_audio = "idle", None, None
                if not self.client_playing:
                    await self.set_state("idle")
                return
        if text is not None:
            if self.carry_text:
                text, self.carry_text = f"{self.carry_text} {text}".strip(), ""
            msg_id = store.add_message("user", text)
            await self.send_json({"type": "user_text", "text": text})
        self.turn_text, self.phase, self.sent_sentences = text, "llm", []
        await self.set_state("thinking")

        # Lo que el usuario comparte en este momento (cámara, pantalla): solo imágenes recientes.
        now = time.monotonic()
        images = [llm.Image(kind, jpeg, name) for jpeg, at, kind, name in
                  (self.frames[src] for src in FRAME_SOURCES if src in self.frames)
                  if now - at <= FRAME_MAX_AGE] if text is not None else []
        heard = self._heard() if text is not None else ""
        guessed = await actions.guess_async(text) if text is not None else None
        # «¿Puedes bailar?», «salta», «duérmete»: si el modelo no pone el gesto, lo pone la sesión (play.py).
        self.asked_gesture = play.guess(text) if text is not None else None
        if guessed and guessed[0] == "controlar":
            # La tarea va con tus palabras tal cual (con acentos y entera): el reconocedor la simplifica.
            guessed = ("controlar", [guessed[1][0], text.strip()[:200]])
        if guessed and not self.actions_on():                 # orden clara pero sin acciones: que no diga que lo hará
            off = ("las acciones en la PC están apagadas en Ajustes" if not actions.config()["enabled"]
                   else "el modelo local que usa ahora es demasiado pequeño para hacer acciones")
            messages, guessed = self._messages(instruction, refuse=off), None
        else:
            messages = self._messages(instruction, hint=guessed)
        self.last_talk = time.monotonic()

        parser = TagStream()
        queue: asyncio.Queue = asyncio.Queue()
        speaker = asyncio.create_task(self._speak(queue, t0))
        failure: str | None = None
        try:
            async for piece in llm.stream_chat(messages, sampling_for(self.persona), images):
                for sentence in parser.feed(piece):
                    await queue.put(sentence)
            for sentence in parser.flush():
                await queue.put(sentence)
            await queue.put(None)
            await speaker
        except asyncio.CancelledError:
            speaker.cancel()
            await asyncio.gather(speaker, return_exceptions=True)
            self._save_partial(msg_id)
            raise
        except llm.LLMError as e:
            speaker.cancel()
            await asyncio.gather(speaker, return_exceptions=True)
            failure = str(e)

        for notice in llm.pop_notices():              # p. ej. cambio de modelo por cuota agotada
            await self.send_json({"type": "notice", "message": notice})
        if failure:
            self._save_partial(msg_id)
            await self.send_json({"type": "error", "message": failure})
        else:
            full = " ".join(parser.spoken)
            if full:
                # Las acciones pedidas se guardan con la respuesta: si no, el historial le enseña al modelo
                # (sobre todo a uno pequeño) que nunca escribe esas etiquetas, y deja de pedirlas.
                said = [guessed, *[a for a in parser.actions if guessed is None or a[0] != guessed[0]]] if guessed else parser.actions
                asked = "".join(f"[accion: {' | '.join([n, *a])}] " for n, a in said[:actions.MAX_PER_REPLY])
                store.add_message("assistant", (asked if text is not None and self.actions_on() else "") + full, self.emotion)
            for fact in parser.memories:
                store.add_memory(fact)
            await self.send_json({"type": "reply_end", "text": full})
            # Acciones: solo las que pide en respuesta a un mensaje del usuario (no al saludar, ni al mirar la
            # pantalla por su cuenta, ni al contar el resultado de otra acción).
            # Una orden clara del usuario manda sobre lo que interprete el modelo (que a veces olvida la etiqueta o
            # pide otra cosa); el modelo solo añade acciones de otro tipo. Los fallos de una suposición no se avisan.
            wanted = parser.actions
            if guessed:
                wanted = [guessed, *[a for a in parser.actions if actions._plain(a[0]).replace(" ", "_") != guessed[0]]]
            if text is not None and wanted and self.actions_on():
                # Tu orden basta como autorización. Excepción: si compartías la pantalla o la cámara, una acción que
                # no sale claramente de tus palabras (la eligió el modelo) pregunta, porque podría venir de un texto
                # que se veía en la imagen.
                trusted = {guessed[0]} if guessed else set()
                if not images and not heard:          # lo oído en la pantalla tampoco es una orden suya
                    trusted |= {actions._plain(n).replace(" ", "_") for n, _ in wanted}
                await self._ask(wanted[:actions.MAX_PER_REPLY], quiet=not parser.actions, trusted=trusted)
        self.phase, self.turn_text, self.turn_audio = "idle", None, None
        if not self.client_playing:
            await self.set_state("idle")

    # ------------------------------------------------------------ acciones en la PC (con permiso)
    def actions_on(self) -> bool:
        return actions.config()["enabled"] and llm.can_act()

    async def _ask(self, wanted: list[tuple[str, list[str]]], quiet: bool = False, trusted: set[str] | None = None,
                   card: bool = False):
        """`card`: siempre con tarjeta (la orden pudo venir del sonido de la pantalla, no del usuario)."""
        failed = []
        for name, args in wanted:
            try:
                req = await actions.prepare_async(name, args)
            except actions.ActionError as e:
                failed.append((name, str(e)))
                log.info("Acción %s %s no se puede hacer: %s", name, args, e)
                continue
            except Exception as e:  # noqa: BLE001
                failed.append((name, "no pude prepararla"))
                log.warning("Acción %s %s falló al prepararla: %s", name, args, e)
                continue
            if req.name == "controlar" and not llm.can_control():
                failed.append((name, f"el modelo local {llm.local_model()} es demasiado pequeño para manejar ventanas; "
                                     "con Gemma 4 E4B o el cerebro en la nube sí puedo"))
                continue
            if req.name == "controlar" and self.controlling:
                failed.append((name, "ya estoy usando otra ventana; espera a que termine o dile «para»"))
                continue
            if card:
                self.pending[req.id] = req
                await self.send_json({"type": "action_request", **req.public(is_cloud=settings.is_cloud,
                                                                              provider=profile.public_cloud()["name"])})
            elif actions.config()["full"]:
                await self._execute(req, "acceso total")
            elif not actions.config()["ask"] and req.name in (trusted or set()):
                await self._execute(req, "por tu orden")
            elif req.name in actions.always():
                await self._execute(req, "siempre")
            else:
                self.pending[req.id] = req
                await self.send_json({"type": "action_request", **req.public(is_cloud=settings.is_cloud,
                                                                              provider=profile.public_cloud()["name"])})
        if failed and not quiet:
            why = "; ".join(f"{n}: {e}" for n, e in failed)
            self._later(ACTION_FAILED.format(user=settings.user_name, what=why))

    async def _answer(self, req: actions.Request, answer: str):
        if answer == "deny":
            actions.record(req, "negada", "")
            self.outcomes.append(f"{settings.user_name} no aprobó «{req.detail}»: no se hizo")
            await self.send_json({"type": "action_done", "id": req.id, "ok": False, "text": f"No se hizo: {req.detail}"})
            return
        if answer == "always":
            actions.save(add_always=req.name)
        await self._execute(req, "siempre" if answer == "always" else "permitida")

    async def _execute(self, req: actions.Request, decision: str):
        if req.name == "controlar":                        # tarea de varios pasos: va aparte, sin frenar la charla
            actions.record(req, decision, "empieza")
            await self.send_json({"type": "action_done", "id": req.id, "ok": True, "text": "Empieza: lo verás en el aviso de arriba."})
            self._spawn(self._control(req))
            return
        try:
            result = await actions.run_async(req)
        except Exception as e:  # noqa: BLE001
            result = f"falló ({type(e).__name__}: {str(e)[:120]})"
            actions.record(req, decision, result)
            self.outcomes.append(f"«{req.detail}» falló")
            await self.send_json({"type": "action_done", "id": req.id, "ok": False, "text": f"{req.detail}: {result}"})
            self._later(ACTION_FAILED.format(user=settings.user_name, what=f"{req.detail}: {result}"))
            return
        actions.record(req, decision, result)
        self.outcomes.append(f"se hizo «{req.detail}»")
        await self.send_json({"type": "action_done", "id": req.id, "ok": True, "text": result, "action": req.name})
        if req.name == "temporizador":
            _start_timer(req)
        if actions.CATALOG[req.name]["report"]:
            self._later(ACTION_RESULT.format(user=settings.user_name, title=req.detail, result=result))

    # ------------------------------------------------------------ usar una ventana con ratón y teclado
    async def _confirm(self, detail: str) -> bool:
        """Un paso delicado (Enviar, Comprar, Eliminar…, o Enter en un chat): se pregunta otra vez."""
        cid = actions.uuid.uuid4().hex[:12]
        fut = asyncio.get_running_loop().create_future()
        self.confirms[cid] = fut
        await self.send_json({"type": "action_request", "id": cid, "action": "confirmar", "confirm": True, "no_always": True,
                              "title": "Confirmar un paso", "detail": detail,
                              "note": "Este paso puede enviar, comprar, borrar o publicar algo. Solo se hace si dices que sí."})
        try:
            ok = await asyncio.wait_for(fut, CONFIRM_TTL)
        except asyncio.TimeoutError:
            ok = False
        finally:
            self.confirms.pop(cid, None)
        await self.send_json({"type": "action_done", "id": cid, "ok": ok, "text": "Confirmado." if ok else "No se hizo."})
        return ok

    def _heard(self) -> str:
        """Lo que se oyó hace poco en el sonido de la pantalla compartida ('' si no se comparte o no se oye nada)."""
        return self.ear.recent() if "screen" in self.frames else ""

    def _sharing_screen(self) -> bool:
        """¿El usuario está compartiendo la pantalla ahora? Entonces el control puede mirar la ventana que maneja."""
        f = self.frames.get("screen")
        return bool(f) and time.monotonic() - f[1] < 15

    async def _control(self, req: actions.Request):
        from . import control_task                  # el bucle de pasos vive en control_task.py
        await control_task.run(self, req)

    async def _timer_done(self, req: actions.Request, late: bool = False):
        if late:
            await asyncio.sleep(1.5)          # que la interfaz reciba antes su saludo («hello»)
        label = req.target["label"]
        await self.send_json({"type": "notice", "message": ("Mientras la ventana estaba cerrada se acabó el temporizador" if late
                                                            else "Se acabó el temporizador") + (f": {label}." if label else ".")})
        self._later(TIMER_DONE.format(user=settings.user_name, what=req.detail))

    async def _check_reminders(self, late: bool = False):
        due = store.due_reminders()
        if not due:
            return
        if late:
            await asyncio.sleep(1.8)
        for rid, _due_ts, text in due:
            store.mark_reminder_done(rid)
            prefix = "Tenías un recordatorio pendiente" if late else "Recordatorio"
            await self.send_json({"type": "notice", "message": f"{prefix}: {text}."})
            self._later(REMINDER_DONE.format(user=settings.user_name, what=text))

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self.side.add(task)
        task.add_done_callback(self.side.discard)

    def _later(self, instruction: str):
        """Un turno del personaje (contar un resultado, avisar del temporizador) en cuanto termine de hablar."""
        async def wait_and_say():
            limit = time.monotonic() + 90
            while (self.busy or self.in_speech) and time.monotonic() < limit:
                await asyncio.sleep(0.3)
            if not self.closed and not self.busy and not self.in_speech:
                if self._is_live():
                    await self._live_send_text(instruction, show_user=False)
                else:
                    self.turn = asyncio.create_task(self._guard(self._run_turn(None, instruction=instruction)))
        self._spawn(wait_and_say())

    async def _expire_actions(self):
        now = time.monotonic()
        for req in [r for r in self.pending.values() if now - r.created > ACTION_TTL]:
            self.pending.pop(req.id, None)
            actions.record(req, "caducada", "")
            self.outcomes.append(f"«{req.detail}» no se hizo: nadie la aprobó")
            await self.send_json({"type": "action_done", "id": req.id, "ok": False, "text": f"Caducó sin respuesta: {req.detail}"})

    @property
    def persona(self) -> dict:
        """La ficha con el nombre de la voz elegida y la personalidad elegida: si se cambian en Ajustes, cambian en
        el siguiente turno."""
        return personality.apply(profile.character(self.base_persona))

    async def prime(self) -> bool:
        """Tras cambiar de personalidad: el modelo local lee ya el prompt nuevo, si no hay nadie hablando (Ollama tiene
        una sola cola: no debe retrasar un turno)."""
        if self.closed or self.busy or self.in_speech or self.controlling:
            return False
        return await llm.prime_local(self._messages())

    def _system(self, *, live: bool = False) -> str:
        adult = adult_active(self.persona, is_cloud=settings.is_cloud, user_adult=profile.is_adult())
        past = [f"{time.strftime('%d/%m/%Y', time.localtime(ts))}: {text}" for text, ts in store.summaries(SYSTEM_SUMMARIES)]
        return build_system_prompt(self.persona, user_name=settings.user_name, memories=store.memories(), adult=adult,
                                   about=profile.describe(settings.user_name), summaries=past,
                                   actions=self.actions_on(), control=llm.can_control(), live=live)

    # ------------------------------------------------------------ toques y miradas
    async def _poke(self, kind: str, zone: str, level: int):
        """La tocan o la miran de cerca con la cámara: a veces lo comenta en una frase (con su personalidad). Como
        mucho una cada POKE_GAP (con la nube, más espaciadas: cada una es una petición), y solo si nadie habla."""
        what = poke_text(kind, zone, level)
        now = time.monotonic()
        gap = POKE_GAP_CLOUD if settings.is_cloud else POKE_GAP
        if (not what or self.busy or self.in_speech or self.controlling or now - self.last_poke < gap
                or now - self.last_talk < 3):
            return
        self.last_poke = now
        instruction = POKE.format(user=settings.user_name, what=what)
        if getattr(self, "_is_live", lambda: False)():
            await self._live_send_text(instruction, show_user=False)
            return
        self.turn = asyncio.create_task(self._guard(self._run_turn(None, instruction=instruction)))

    # ------------------------------------------------------------ memoria a largo plazo
    async def _summarize(self):
        """Resume el tramo de conversación que ya quedó fuera de la ventana de corto plazo y lo guarda como
        recuerdo. Se hace en un rato de calma; si el usuario habla, se cancela y se reintenta después."""
        rows = store.unsummarized(self.anchor)
        if len(rows) < SUMMARY_MIN:
            return
        self.phase, self.turn_text, self.turn_audio, self.sent_sentences = "llm", None, None, []
        name = self.persona["name"]
        dialog = "\n".join(f"{settings.user_name if role == 'user' else name}: {text}" for _, role, text, _ in rows)
        known = "; ".join(store.memories(40)) or "nada todavía"
        try:
            text = await llm.complete([{"role": "user", "content": SUMMARIZE.format(
                user=settings.user_name, name=name, dialog=dialog[:12000], known=known[:2000])}], max_tokens=320)
        except llm.LLMError as e:
            log.warning("No pude resumir la conversación: %s", e)
            self.summary_retry = time.monotonic() + 300
            return
        finally:
            self.phase = "idle"
            llm.pop_notices()
        summary, facts = split_summary(text)
        for fact in facts:
            store.add_memory(fact)
        if len(summary) > 20:
            store.add_summary(summary[:900], rows[0][0], rows[-1][0], rows[-1][3])
            log.info("Recuerdo guardado (%d mensajes, %d datos nuevos): %s", len(rows), len(facts), shown(summary[:120]))

    def _messages(self, instruction: str | None = None, hint: tuple[str, list[str]] | None = None,
                  refuse: str = "") -> list[dict]:
        """Prompt de sistema + historial + (instrucción). Todo lo que va delante del último mensaje se mantiene
        idéntico de un turno a otro —el sistema no lleva la hora y el historial no se desliza mensaje a mensaje,
        sino a saltos— para que el modelo reutilice lo que ya procesó y solo lea lo nuevo."""
        system = self._system()
        rows = store.since(self.anchor)
        if len(rows) > HISTORY_MAX:
            rows = rows[-HISTORY_KEEP:]
            while rows and rows[0][1] != "user":
                rows.pop(0)
            self.anchor = rows[0][0] if rows else store.anchor(1)
        messages = [{"role": "system", "content": system}, *({"role": r, "content": t} for _, r, t in rows)]
        if instruction:
            messages.append({"role": "user", "content": instruction})
        last = next((m for m in reversed(messages) if m["role"] == "user"), None)
        if last is not None:
            done = ""
            if not instruction:
                # Conversaciones antiguas (las 8 últimas ya van en el prompt de sistema) que tratan de lo mismo que lo
                # que acaba de decir. Van aquí, no en el sistema, para que el modelo local reutilice su caché.
                old = store.relevant_summaries(last["content"], skip_recent=SYSTEM_SUMMARIES,
                                               ignore=f"{settings.user_name} {self.persona['name']}")
                if old:
                    done += "".join(f"\n(Recuerdas de una conversación del {time.strftime('%d/%m/%Y', time.localtime(ts))}: {t})"
                                    for t, ts in old)
            if self.outcomes and not instruction:          # cómo acabaron sus acciones, una sola vez
                done += f"\n(Tus acciones anteriores: {'; '.join(self.outcomes[-4:])}.)"
                self.outcomes = []
            if hint:                                        # orden clara: se le recuerda la etiqueta exacta
                done += (f"\n(Esto es una petición de tu lista. Empieza tu respuesta con "
                         f"[accion: {' | '.join([hint[0], *hint[1]])}] y di en una frase que lo haces.)")
            if refuse:
                done += (f"\n(Te pide algo en su PC, pero ahora no puedes hacerlo: {refuse}. Díselo con claridad en "
                         "una frase; no digas que lo vas a hacer.)")
            heard = self._heard()
            if heard:                                       # lo que se oye en lo que comparte (vídeo, juego, llamada)
                done += screen_audio.note(heard, settings.user_name)
                self.ear.new_text = False
            # Tras unos días sin hablar, que lo note (al saludar, el último guardado; si no, el anterior a este mensaje).
            gap = (mood.since_last_talk(store.previous_ts(0 if instruction == GREETING else 1))
                   if not instruction or instruction == GREETING else "")
            ctx = turn_context(local_time(settings.timezone), mood.describe(self.persona["personality"]), gap)
            last["content"] = f"{ctx}{done}\n{last['content']}"
        return messages

    # ------------------------------------------------------------ mirada en vivo
    async def _watch_loop(self):
        """Mientras se comparte la cámara o la pantalla, cada pocos segundos Mika mira por su cuenta. Solo lo
        hace si hubo movimiento, nadie está hablando y ha pasado un rato desde lo último que se dijo."""
        try:
            while not self.closed:
                await asyncio.sleep(settings.watch_interval)
                await self._expire_actions()
                await self._check_reminders()
                now = time.monotonic()
                # Memoria: en un rato de calma, resume lo que ya salió de la ventana de corto plazo.
                if (not self.busy and not self.in_speech and self.state == "idle" and now - self.last_talk > SUMMARY_QUIET
                        and now > self.summary_retry and len(store.unsummarized(self.anchor, SUMMARY_MIN)) >= SUMMARY_MIN):
                    self.turn = asyncio.create_task(self._guard(self._summarize()))
                    continue
                if (not self.watch or self.busy or self.in_speech or self.run or self.state != "idle" or self.controlling
                        or now - self.last_talk < WATCH_QUIET or now - self.last_comment < settings.watch_gap):
                    continue
                clips = {src: [f for f in clip if now - f[1] <= WATCH_WINDOW] for src, clip in self.clips.items()}
                # Algo que se dijo en el sonido de la pantalla también cuenta como novedad, aunque la imagen no cambie.
                moved = [src for src in FRAME_SOURCES if clips.get(src) and (self.motion.get(src, 0) >= WATCH_MOTION
                                                                             or (src == "screen" and self.ear.new_text))]
                if not moved:
                    continue
                for src in moved:
                    self.motion[src] = 0.0
                if self._is_live():
                    self.last_comment = now
                    said = "".join(f" («{c}»)" for c in self.comments)
                    prompt = OBSERVE.format(user=settings.user_name, said=(":" + said) if said else "")
                    self._spawn(self._live_send_text(prompt, show_user=False))
                    continue
                self.turn = asyncio.create_task(self._guard(self._observe({src: clips[src] for src in moved})))
        except asyncio.CancelledError:
            pass

    async def _observe(self, clips: dict):
        images = []
        for src, clip in clips.items():
            # La más antigua y la más reciente bastan para notar un cambio; cada imagen de más alarga la mirada,
            # y mientras Ollama la lee no puede atender un turno del usuario (tiene una sola cola).
            for jpeg, _, kind, name in dict.fromkeys([clip[0], clip[-1]]):
                images.append(llm.Image(kind, jpeg, name))
        said = "".join(f" («{c}»)" for c in self.comments)
        messages = self._messages(OBSERVE.format(user=settings.user_name, said=(":" + said) if said else ""))
        self.phase, self.turn_text, self.turn_audio, self.sent_sentences = "llm", None, None, []
        t0 = time.perf_counter()
        try:
            reply = await llm.observe(messages, {**sampling_for(self.persona), "max_tokens": 70}, images)
        except llm.LLMError as e:
            self.watch = False                 # sin cuota o sin modelo: se apaga la mirada, no la conversación
            self.phase = "idle"
            await self.send_json({"type": "notice", "message": str(e)})
            await self.send_json({"type": "watch", "on": False})
            return
        for notice in llm.pop_notices():
            await self.send_json({"type": "notice", "message": notice})
        parser = TagStream()
        quiet = _SILENCE_TAG.search(reply) or _SILENCE_ONLY.fullmatch(reply)
        sentences = [] if quiet else [*parser.feed(reply), *parser.flush()][:2]
        log.info("Mirada en vivo (%s, %d imágenes, %.2fs): %s", "+".join(clips), len(images), time.perf_counter() - t0, shown(reply[:120]))
        if not sentences or self.in_speech:
            self.phase = "idle"
            return
        self.last_comment = time.monotonic()
        queue: asyncio.Queue = asyncio.Queue()
        for s in sentences:
            queue.put_nowait(s)
        queue.put_nowait(None)
        try:
            await self._speak(queue, t0)
        except asyncio.CancelledError:
            self._save_partial(None)
            raise
        full = " ".join(s.text for s in sentences)
        store.add_message("assistant", full, self.emotion)
        self.comments.append(full)
        await self.send_json({"type": "reply_end", "text": full})
        self.phase, self.last_talk = "idle", time.monotonic()
        if not self.client_playing:
            await self.set_state("idle")

    def _save_partial(self, msg_id: int | None):
        """Turno cortado: se guarda lo que alcanzó a decir; si no dijo nada, el mensaje del usuario se retira
        (vuelve unido a lo siguiente que diga, o se descarta si el LLM falló)."""
        if self.sent_sentences:
            store.add_message("assistant", " ".join(self.sent_sentences) + "…", self.emotion)
        elif msg_id is not None:
            store.delete_message(msg_id)

    def _checks_voice(self, engine: str | None) -> bool:
        """¿Se escucha la frase con Whisper antes de que suene? Solo con la voz completa y el oído en CUDA: en el
        procesador o en la GPU del Mac, escucharla otra vez tarda casi lo que la frase."""
        # En una tarjeta lenta (modo rápido de la voz, 18 nov 2026) cada repetición costaba otros 3-5 s y esperar a la
        # frase entera retrasaba el primer audio: allí suena según llega, como en el Mac.
        from . import voz_proc
        return ((engine or settings.voice_engine) == "completa" and self.stt.ready
                and getattr(self.stt, "device", None) == "cuda" and not voz_proc.fast())

    async def _say(self, text: str, voice: str, speed: float, engine: str | None = None):
        """El audio de la frase en trozos. Sin comprobación, cada trozo sale según lo manda la voz: voz/servidor.py
        va cláusula a cláusula, y esperar a la frase entera retrasaba el primer audio unos 6 s en el Mac (16 nov
        2026). Con comprobación, la frase entera ya comprobada."""
        if not self._checks_voice(engine):
            async for chunk in tts.stream_speech(text, voice, speed, engine):
                yield chunk
            return
        yield await self._say_checked(text, voice, speed, engine)

    async def _send_audio(self, pcm: bytes, t0: float) -> bool:
        for k in range(0, len(pcm), 9600):
            chunk = pcm[k:k + 9600]
            if not self.client_playing:
                self.client_playing, self.play_started, self.audio_bytes = True, time.monotonic(), 0
                log.info("Primer audio a los %.2fs", time.perf_counter() - t0)
                await self.set_state("speaking")
            self.audio_bytes += len(chunk)
            await self.send_bytes(chunk)
        return bool(pcm)

    async def _say_checked(self, text: str, voice: str, speed: float, engine: str | None = None) -> bytes:
        """La frase en audio, comprobada: con la voz completa se escucha con Whisper y, si se comió una palabra, se
        genera otra vez (hasta VOICE_RETRIES) y se queda la mejor. La voz ligera (Piper) no lo necesita."""
        pcm = b"".join([c async for c in tts.stream_speech(text, voice, speed, engine)])
        if (engine or settings.voice_engine) != "completa" or not self.stt.ready or not pcm:
            return pcm
        if getattr(self.stt, "device", None) != "cuda":
            return pcm                    # en el procesador, escucharla otra vez tarda casi lo que la frase
        from . import voz_proc
        if voz_proc.fast():               # la primera frase se pidió antes de que la voz midiera la tarjeta
            return pcm
        loop = asyncio.get_running_loop()
        best, best_lost = pcm, None
        # Si no está sonando nada (la primera frase), cada repetición se nota como espera: como mucho una.
        retries = VOICE_RETRIES if self.client_playing else 1
        for attempt in range(retries + 1):
            got = await loop.run_in_executor(None, voicecheck.heard, self.stt.model, pcm)
            lost = voicecheck.missing(text, got)
            if best_lost is None or len(lost) < len(best_lost):
                best, best_lost = pcm, lost
            if not voicecheck.bad(lost):
                break
            log.info("Voz: faltó %s en %s (oído %s); repito", shown(" ".join(lost)), shown(text[:60]), shown(got[:60]))
            if attempt < retries:
                pcm = b"".join([c async for c in tts.stream_speech(text, voice, speed)])
        if best_lost and voicecheck.bad(best_lost):
            log.info("Voz: tras %d intentos sigue faltando %s en %s", retries + 1, shown(" ".join(best_lost)), shown(text[:60]))
        return best

    async def _speak(self, queue: asyncio.Queue, t0: float):
        voice = settings.tts_voice or self.persona["voice"].get("tts_voice")      # la elegida en la bienvenida
        speed = float(self.persona["voice"].get("speed", 1.0))
        tts_ok, idx, finish = True, 0, False
        # El gesto que pidió el usuario en este turno (play.py), solo para esta respuesta.
        asked, self.asked_gesture = getattr(self, "asked_gesture", None), None
        engine = None                     # "ligera" si la completa falló a mitad de respuesta (ver más abajo)
        pending = None                    # una frase que ya se sacó de la cola pero no cupo con la anterior
        while not finish:
            sentence, pending = (pending, None) if pending else (await queue.get(), None)
            if sentence is None:
                return
            # Una frase muy corta («¡Hola, Danny!») el modelo de voz la dice mal casi siempre: si la siguiente llega
            # enseguida, van juntas (un solo subtítulo y un solo audio). En modo rápido (tarjeta lenta) se juntan
            # también las cortas: cada petición a la voz cuesta ~2 s fijos en una RTX 3050 y una frase corta dura
            # menos al sonar, así que entre frases quedaban silencios (18 nov 2026).
            fast = settings.voice_engine == "completa" and engine is None and voz_proc.fast()
            limit = FAST_MERGE if fast else SHORT_SENTENCE
            while len(sentence.text) < limit and settings.voice_engine == "completa":
                try:
                    nxt = await asyncio.wait_for(queue.get(), SHORT_WAIT)
                except asyncio.TimeoutError:
                    break                                   # la siguiente tarda: esta va sola
                if nxt is None:
                    finish = True                           # era la última frase de la respuesta
                    break
                if fast and len(sentence.text) + len(nxt.text) + 1 > FAST_MERGE_MAX:
                    pending = nxt                           # no cabe: va en la siguiente vuelta
                    break
                sentence = Sentence(f"{sentence.text} {nxt.text}", sentence.emotion or nxt.emotion,
                                    [*sentence.gestures, *nxt.gestures])
                if not fast:
                    break
            idx += 1
            if asked and idx == 1 and asked not in sentence.gestures:
                sentence.gestures.append(asked)
            if sentence.emotion:
                self.emotion = sentence.emotion
                mood.feel(sentence.emotion, self.persona["personality"])
            await self.send_json({"type": "sentence", "id": idx, "text": sentence.text,
                                  "emotion": sentence.emotion, "gestures": sentence.gestures})
            if idx == 1:
                self.phase = "audio"
                log.info("Primera frase a los %.2fs", time.perf_counter() - t0)
            if tts_ok:
                sent = False
                try:
                    try:
                        async for pcm in self._say(sentence.text, voice, speed, engine):
                            sent = await self._send_audio(pcm, t0) or sent
                    except tts.TTSError as e:
                        # La voz completa no responde (sin memoria de vídeo, o se cayó): con el cambio automático
                        # encendido, esta respuesta sigue con la ligera en vez de quedarse en texto. Si ya sonó
                        # parte de la frase, no se repite con la otra voz.
                        if sent or engine or settings.voice_engine != "completa" or not self._light_fallback():
                            raise
                        log.warning("Voz completa sin respuesta (%s): sigo con la ligera", e)
                        engine = "ligera"
                        await self.send_json({"type": "notice", "message": "La voz completa no responde ahora: "
                                              "sigo con la voz ligera en esta respuesta."})
                        async for pcm in self._say(sentence.text, voice, speed, engine):
                            await self._send_audio(pcm, t0)
                except tts.TTSError as e:
                    tts_ok = False
                    log.warning("Sin voz: %s", e)
                    await self.send_json({"type": "error", "message": f"La voz no está disponible ahora (mira data{os.sep}voz.log, "
                                                                      "o pasa a la voz ligera en Ajustes). Sigo en texto."})
            self.sent_sentences.append(sentence.text)
            await self.send_json({"type": "sentence_end", "id": idx})

    @staticmethod
    def _light_fallback() -> bool:
        from . import tts_light
        return profile.voice_auto() and tts_light.installed()

    # ------------------------------------------------------------ Gemini Live API
    def _is_live(self) -> bool:
        return profile.live_ready()

    async def _ensure_live(self):
        async with self._live_lock:
            if self.live and self.live.connected:
                return self.live
            lv = profile.live()
            v = profile.voice()
            speaks = self.persona.get("speaks", "f")
            voice_name = lv["voice"] or (gemini_live.voice_for(v["id"] if v else None, speaks) if lv["provider"] == "gemini"
                                         else realtime.voice_for(lv["provider"], speaks))
            samp = sampling_for(self.persona)
            tools = [gemini_live.EXPRESS_TOOL, gemini_live.REMEMBER_TOOL,
                     *(gemini_live.ACTION_TOOLS if self.actions_on() else [])]
            system = (self._system(live=True) + "\n\n" + gemini_live.live_recap(self.persona, settings.user_name)
                      + "\n\n" + self._live_context())
            kw = {"model": lv["model"], "voice_name": voice_name, "temperature": samp.get("temperature"), "tools": tools}
            if self._live_factory:
                client = self._live_factory(lv["key"], system, **kw)
            elif lv["provider"] == "gemini":
                client = gemini_live.GeminiLiveClient(lv["key"], system, resume_handle=self._live_resume_handle, **kw)
            else:
                client = realtime.RealtimeClient(lv["key"], system, provider=lv["provider"], url=lv["url"], **kw)
            try:
                await client.connect()
            except gemini_live.GeminiLiveError as e:
                log.warning("En vivo no disponible: %s", e)
                await self.send_json({"type": "error", "message": str(e)})
                await self.set_state("idle")
                return None
            self.live = client
            self.live_task = asyncio.create_task(self._live_loop(client))
            return client

    def _live_context(self) -> str:
        """La hora, su ánimo y cuánto hace que no hablaban (lo que en los otros modos va en turn_context). En vivo va
        al final del prompt al conectar: mandarlo como mensaje aparte (turnComplete false) hacía que Gemini
        respondiera una vez de más y las respuestas se desfasaban un turno (medido el 21 nov 2026). Una sesión en
        vivo dura poco (se reconecta al cambiar ajustes o tras cortarse), así que se renueva sola."""
        self._live_ctx_at = time.monotonic()
        gap = mood.since_last_talk(store.previous_ts(0))
        return turn_context(local_time(settings.timezone), mood.describe(self.persona["personality"]), gap)

    def _live_screen_heard(self) -> bool:
        """Gemini recibe el micrófono y el sonido de la pantalla por el mismo canal y no los distingue: si la
        pantalla sonó hace poco, lo «oído» puede ser de un vídeo o un juego y no cuenta como orden del usuario."""
        return time.monotonic() - self._live_screen_at < 4.0

    async def _live_express(self, emotion: str | None, gesture: str | None = None, how: str = "tool"):
        """Cara y cuerpo en vivo: la emoción de `expresar` (o la deducida del texto) llega a la interfaz al momento."""
        from .prompt import EMOTIONS, GESTURES
        emotion = emotion if emotion in EMOTIONS else None
        gesture = gesture if gesture in GESTURES else None
        if not emotion and not gesture:
            return
        if emotion:
            self.emotion = emotion
            self._live_emo = how
        await self.send_json({"type": "express", "emotion": emotion, "gestures": [gesture] if gesture else []})

    async def _live_send_text(self, text: str, *, show_user: bool):
        # Saludo, mirada en vivo, toques y temporizadores no son turnos del usuario: ahí no se hace ninguna acción.
        self._live_user = show_user
        self._live_mixed = False
        if show_user:
            self._live_in_buf = [text]
            self._live_gesture = play.guess(text)
            await self.send_json({"type": "user_text", "text": text})
            if await self._live_check_voice_cmd(text):
                return
        await self.set_state("thinking")
        client = await self._ensure_live()
        if not client:
            return
        now = time.monotonic()
        fresh_images = [jpeg for jpeg, ts, _, _ in self.frames.values() if now - ts <= FRAME_MAX_AGE]
        try:
            await client.send_text(text, images=fresh_images)
        except gemini_live.GeminiLiveError as e:
            log.warning("Gemini Live texto falló: %s", e)
            await self.send_json({"type": "error", "message": str(e)})
            await self.set_state("idle")

    async def _live_send_image(self, jpeg_b64: str):
        if not self.live or not self.live.connected:
            return
        try:
            await self.live.send_image(jpeg_b64)
        except gemini_live.GeminiLiveError:
            pass

    async def _live_open_sentence(self):
        if self._live_turn_open:
            return
        self._live_turn_open = True
        self._live_sentence_id += 1
        self._live_out_buf.clear()
        self.client_playing = True
        self.play_started = time.monotonic()
        self.audio_bytes = 0
        gestures = [self._live_gesture] if self._live_gesture else []
        self._live_gesture = None
        await self.set_state("speaking")
        await self.send_json({
            "type": "sentence",
            "id": self._live_sentence_id,
            "text": "",
            "emotion": self.emotion,
            "gestures": gestures,
        })

    async def _live_check_voice_cmd(self, text: str, *, heard: bool = False) -> bool:
        """Comandos cortos por voz/texto en modo Live: «para» detiene controlar; «sí»/«no» responde tarjetas.
        `heard` con la pantalla sonando: un «sí» de un vídeo no puede aprobar nada («para» sí vale)."""
        said = re.sub(r"[^\w\s]", " ", actions._plain(text)).strip()
        if not said:
            return False
        if self.controlling and _STOP.match(said) and len(said.split()) <= 4:
            self.control_stop = True
            return True
        if heard and self._live_mixed:
            return False
        if (self.pending or self.confirms) and len(said.split()) <= 4:
            verdict = "allow" if _YES.match(said) else "deny" if _NO.match(said) else None
            if verdict:
                for cid in list(self.confirms):
                    fut = self.confirms.pop(cid, None)
                    if fut and not fut.done():
                        fut.set_result(verdict == "allow")
                for req in list(self.pending.values()):
                    self.pending.pop(req.id, None)
                    await self._answer(req, verdict)
                return True
        return False

    async def _live_loop(self, client: gemini_live.GeminiLiveClient):
        called_this_turn = False
        try:
            async for ev, payload in client.receive():
                if self.closed:
                    break
                if ev == "in_text":
                    self._live_user = True                     # habló alguien: el turno ya es del usuario
                    if self._live_screen_heard():
                        self._live_mixed = True
                    self._live_in_buf.append(payload)
                    said = "".join(self._live_in_buf).strip()
                    if said:
                        await self.send_json({"type": "user_text", "text": said})
                        if not self._live_gesture:
                            self._live_gesture = play.guess(said)
                        if self.controlling and _STOP.match(re.sub(r"[^\w\s]", " ", actions._plain(said)).strip()):
                            self.control_stop = True
                    if not self._live_turn_open:
                        await self.set_state("listening")
                elif ev == "resume_handle":
                    if isinstance(payload, str) and payload:
                        self._live_resume_handle = payload
                elif ev == "go_away":
                    log.info("Gemini Live pidió rotación de conexión (%s); se reanudará con el handle guardado", payload)
                    await client.close()
                    break
                elif ev == "tool_call":
                    silent = [fc for fc in payload if fc.get("name") in ("expresar", "recordar")]
                    payload = [fc for fc in payload if fc.get("name") not in ("expresar", "recordar")]
                    if silent:                      # no frenan la voz ni el micrófono
                        sres = []
                        for fc in silent:
                            cid = str(fc.get("id") or "")
                            fname = str(fc.get("name") or "")
                            args = fc.get("args") if isinstance(fc.get("args"), dict) else {}
                            if fname == "expresar":
                                await self._live_express(str(args.get("emocion") or ""), str(args.get("gesto") or ""))
                                sres.append({"id": cid, "name": fname, "response": {"ok": True}})
                            elif fname == "recordar":
                                dato = str(args.get("dato") or "").strip().strip("«»\"' ")
                                ok = (self._live_user and not self._live_mixed and 8 <= len(dato) <= 200
                                      and not _PRIVATE.search(dato))
                                if ok:
                                    store.add_memory(dato)
                                    log.info("Gemini Live recordó: %s", dato)
                                sres.append({"id": cid, "name": fname, "response": {"ok": ok}})
                        try:
                            await client.send_tool_response(sres)
                        except gemini_live.GeminiLiveError:
                            pass
                    if not payload:
                        continue
                    called_this_turn = True
                    self._live_in_tool = True
                    responses = []
                    wanted = []
                    try:
                        for fc in payload:
                            cid = str(fc.get("id") or "")
                            fname = str(fc.get("name") or "")
                            args = fc.get("args") if isinstance(fc.get("args"), dict) else {}
                            if fname == "ejecutar_accion" and not self._live_user:
                                responses.append({"id": cid, "name": fname, "response": {
                                    "ok": False, "error": "solo cuando el usuario lo pide en este turno"}})
                            elif fname == "ejecutar_accion" and self.actions_on():
                                accion = str(args.get("accion") or "").strip()
                                arg_list = [str(args[k]).strip() for k in ("arg1", "arg2") if args.get(k)]
                                if accion and arg_list:
                                    wanted.append((accion, arg_list))
                                    responses.append({"id": cid, "name": fname, "response": {"ok": True, "status": "en_marcha"}})
                                else:
                                    responses.append({"id": cid, "name": fname, "response": {"ok": False, "error": "faltan argumentos"}})
                            else:
                                responses.append({"id": cid, "name": fname, "response": {"ok": False, "error": "acciones desactivadas"}})
                        if responses:
                            await client.send_tool_response(responses)
                    finally:
                        self._live_in_tool = False
                    if wanted:
                        log.info("Gemini Live toolCall: %s", wanted)
                        now = time.monotonic()
                        has_frames = any(now - ts <= FRAME_MAX_AGE for _, ts, _, _ in self.frames.values())
                        trusted = set() if has_frames else {actions._plain(n).replace(" ", "_") for n, _ in wanted}
                        self._spawn(self._live_exec_actions(wanted[:actions.MAX_PER_REPLY], trusted,
                                                            card=self._live_mixed))
                elif ev == "audio":
                    await self._live_open_sentence()
                    self.audio_bytes += len(payload)
                    await self.send_bytes(payload)
                elif ev == "out_text":
                    await self._live_open_sentence()
                    self._live_out_buf.append(payload)
                    clean = gemini_live.clean_spoken_text("".join(self._live_out_buf))
                    if not self._live_emo and len(clean) >= 12:
                        self._live_emo = "guess"           # se mira una vez por respuesta; `expresar` manda después
                        await self._live_express(gemini_live.guess_emotion(clean), None, "guess")
                    await self.send_json({"type": "caption_delta", "id": self._live_sentence_id, "text": clean})
                elif ev == "interrupted":
                    self._live_emo = ""
                    self._live_turn_open = False
                    self.client_playing = False
                    self._live_out_buf.clear()
                    await self.send_json({"type": "interrupt"})
                    await self.set_state("listening")
                elif ev == "turn_complete":
                    reply = gemini_live.clean_spoken_text("".join(self._live_out_buf))
                    user_said = "".join(self._live_in_buf).strip()
                    if user_said:
                        store.add_message("user", user_said)
                        handled_cmd = await self._live_check_voice_cmd(user_said, heard=True)
                        if not handled_cmd and not called_this_turn and self.actions_on() and self._live_user:
                            guessed = await actions.guess_async(user_said)
                            if guessed:
                                log.info("Gemini Live fallback acción: %s", guessed)
                                now = time.monotonic()
                                seen = any(now - ts <= FRAME_MAX_AGE for _, ts, _, _ in self.frames.values())
                                await self._ask([guessed], quiet=True, trusted=set() if seen else {guessed[0]},
                                                card=self._live_mixed)
                    if reply:
                        store.add_message("assistant", reply)
                        mood.feel(self.emotion, self.persona["personality"])
                    if self._live_turn_open:
                        await self.send_json({"type": "sentence_end", "id": self._live_sentence_id})
                        await self.send_json({"type": "reply_end", "text": reply})
                        self._live_turn_open = False
                    called_this_turn = False
                    self._live_user = self._live_mixed = False
                    self._live_emo = ""
                    self._live_in_buf.clear()
                    self._live_out_buf.clear()
                    self.last_talk = time.monotonic()
                    if not self.client_playing:
                        await self.set_state("idle")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Conexión Gemini Live interrumpida")
            if not self.closed:
                await self.send_json({"type": "notice", "message": "La conexión con Gemini Live se cerró; se reconectará en el siguiente turno."})
                await self.set_state("idle")
        finally:
            await client.close()
            if self.live is client:
                self.live = None
            self._live_turn_open = False

    async def _live_exec_actions(self, wanted: list[tuple[str, list[str]]], trusted: set[str], card: bool = False):
        """Ejecuta las acciones pedidas por Gemini Live. Si pide «controlar» una app que aún no está abierta
        (ej. Apple Music), primero la abre con `abrir_app`, espera a que aparezca su ventana y luego la controla."""
        for name, args in wanted:
            norm = actions._plain(name).replace(" ", "_")
            if norm == "controlar" and len(args) >= 2:
                try:
                    await actions.prepare_async("controlar", args)
                except actions.ActionError:
                    # La ventana aún no existe: intentamos abrir la app primero y esperar brevemente a que arranque.
                    log.info("Gemini Live: %s no está abierta aún; abro la app antes de controlar", args[0])
                    await self._ask([("abrir_app", [args[0]])], quiet=True,
                                    trusted=(trusted | {"abrir_app"}) if trusted else set(), card=card)
                    for _ in range(8):
                        await asyncio.sleep(0.5)
                        try:
                            await actions.prepare_async("controlar", args)
                            break
                        except actions.ActionError:
                            continue
            await self._ask([(name, args)], trusted=trusted, card=card)

    async def reset_live(self, *, keep_handle: bool = False):
        """Cierra la sesión actual de Gemini Live (al cambiar ajustes, personalidad o cerrar la ventana)."""
        task, self.live_task = self.live_task, None
        client, self.live = self.live, None
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if client is not None:
            await client.close()
        self._live_turn_open = False
        self._live_in_tool = False
        self._live_user = self._live_mixed = False
        if not keep_handle:
            self._live_resume_handle = None
        self._live_pcm_buf.clear()
        self._live_in_buf.clear()
        self._live_out_buf.clear()

    def start(self):
        self.watcher = asyncio.create_task(self._watch_loop())
        _open.append(self)
        while _missed:                        # temporizadores que acabaron sin ninguna ventana abierta
            self._spawn(self._timer_done(_missed.pop(0), late=True))
        self._spawn(self._check_reminders(late=True))

    async def close(self):
        self.closed = True
        if self in _open:
            _open.remove(self)
        self.control_stop = True              # una tarea con ratón y teclado se para al cerrar la ventana
        self.ear.clear()
        await self.reset_live()
        if self.watcher:
            self.watcher.cancel()
        for task in list(self.side):          # respuestas pendientes de esta conexión (los temporizadores siguen)
            task.cancel()
        for req in self.pending.values():
            actions.record(req, "sin respuesta (se cerró la ventana)", "")
        if self.turn_running:
            self.turn.cancel()
            await asyncio.gather(self.turn, return_exceptions=True)
