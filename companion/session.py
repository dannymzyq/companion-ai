"""Una conversación en vivo: micrófono → VAD → Whisper → LLM → voz → avatar.

Protocolo del WebSocket (/ws):
  cliente → servidor   binario: PCM 16 bits mono 16 kHz del micrófono
                       {"type":"start"} · {"type":"text","text":"..."} · {"type":"interrupt"} · {"type":"playback_end"}
  servidor → cliente   {"type":"state","value":"idle|listening|thinking|speaking"}
                       {"type":"user_text","text":"..."}
                       {"type":"sentence","id":n,"text":"...","emotion":"feliz"|null,"gestures":[...]}
                       binario: PCM 16 bits mono 24 kHz de esa frase · {"type":"sentence_end","id":n}
                       {"type":"reply_end","text":"..."} · {"type":"interrupt"} · {"type":"error","message":"..."}
  acciones             servidor → {"type":"action_request","id","title","detail","note"} · {"type":"action_done","id","ok","text"}
                       cliente → {"type":"action_answer","id","answer":"allow|always|deny"}
"""
import asyncio
import json
import logging
import re
import time
from collections import deque

import numpy as np

from . import actions, llm, profile, store, tts, voicecheck
from .config import settings
from .prompt import (ACTION_FAILED, ACTION_RESULT, OBSERVE, OPERATOR, OPERATOR_COORDS, OPERATOR_STEP, SUMMARIZE, TIMER_DONE, adult_active,
                     build_system_prompt, local_time, sampling_for, turn_context)
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
VOICE_RETRIES = 2                         # veces que se repite una frase si la voz se comió una palabra
CONFIRM_TTL = 60.0                       # un paso delicado sin confirmar en 1 minuto no se hace

GREETING = ("(El usuario acaba de abrir la aplicación y todavía no ha dicho nada. Salúdale con naturalidad, "
            "en una sola frase corta, según la hora.)")


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

        self.anchor = store.anchor(HISTORY_KEEP)           # primer mensaje del historial que se envía al LLM
        self.watch = False                                 # mirada en vivo (la activa la interfaz)
        self.watcher: asyncio.Task | None = None
        self.clips: dict[str, deque] = {}                  # origen → últimas imágenes espaciadas (jpeg, cuándo, qué, título)
        self.motion: dict[str, float] = {}                 # origen → mayor cambio visto desde la última mirada
        self.comments: deque = deque(maxlen=3)             # lo último que comentó por su cuenta (para no repetirse)
        self.last_talk = time.monotonic()                  # última vez que alguien habló
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
                await self.interrupt()
                self.turn = asyncio.create_task(self._guard(self._run_turn(text)))
        elif kind == "start":
            if not self.busy:
                self.turn = asyncio.create_task(self._guard(self._run_turn(None, instruction=GREETING)))
        elif kind == "interrupt":
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
        elif kind == "frame_stop":
            for box in (self.frames, self.clips, self.motion):
                box.pop(data.get("source"), None)
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
        log.info("STT %.2fs de espera%s (%.1fs de audio): %r", time.perf_counter() - t0,
                 " (adelantado)" if early is not None else "", len(audio) / 16000, text)
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
        guessed = await actions.guess_async(text) if text is not None else None
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
                if not images:
                    trusted |= {actions._plain(n).replace(" ", "_") for n, _ in wanted}
                await self._ask(wanted[:actions.MAX_PER_REPLY], quiet=not parser.actions, trusted=trusted)
        self.phase, self.turn_text, self.turn_audio = "idle", None, None
        if not self.client_playing:
            await self.set_state("idle")

    # ------------------------------------------------------------ acciones en la PC (con permiso)
    def actions_on(self) -> bool:
        return actions.config()["enabled"] and llm.can_act()

    async def _ask(self, wanted: list[tuple[str, list[str]]], quiet: bool = False, trusted: set[str] | None = None):
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
            if not actions.config()["ask"] and req.name in (trusted or set()):
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
        await self.send_json({"type": "action_done", "id": req.id, "ok": True, "text": result})
        if req.name == "temporizador":
            self._spawn(self._timer(req))
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

    def _sharing_screen(self) -> bool:
        """¿El usuario está compartiendo la pantalla ahora? Entonces el control puede mirar la ventana que maneja."""
        f = self.frames.get("screen")
        return bool(f) and time.monotonic() - f[1] < 15

    async def _control(self, req: actions.Request):
        from . import control
        win, task = req.target["window"], req.target["task"]
        self.controlling, self.control_stop = {"title": win.title, "task": task}, False
        await self.send_json({"type": "control_start", "title": win.title[:60], "task": task, "max": control.MAX_STEPS})
        steps: list[str] = []
        result, ok, bad, last_typed = "", False, 0, None
        # ¿cambió algo? · pasos seguidos sin efecto · cuántas veces se probó cada paso (cada vez, de forma más directa)
        last_sig, still, attempts, last_texts, written = None, 0, {}, [], set()
        limit = time.monotonic() + control.MAX_SECONDS
        sees = self._sharing_screen() and llm.sees_images()
        system = OPERATOR.format(user=settings.user_name, task=task,
                                 sees=", una imagen de la ventana" if sees else "",
                                 coords=OPERATOR_COORDS if sees else "")
        try:
            # En segundo plano: la ventana NO se trae al frente. Solo un paso que necesite el teclado o el ratón de
            # verdad lo hace, y únicamente si no estás usando la PC (control.real_input).
            with control.EscWatch() as esc:
                for n in range(1, control.MAX_STEPS + 1):
                    if esc.pressed or self.control_stop or self.closed:
                        result = f"{settings.user_name} lo paró" + (" con Esc" if esc.pressed else "")
                        break
                    if time.monotonic() > limit:
                        result = "se acabó el tiempo máximo de la tarea"
                        break
                    if not control.user32.IsWindow(win.hwnd):
                        result = "la ventana se cerró"
                        break
                    if win.hwnd in control._fronted and control.user32.GetForegroundWindow() != win.hwnd:
                        result = f"{settings.user_name} cambió a otra ventana, así que me detuve"
                        break
                    items, texts = await asyncio.to_thread(control.snapshot, win.hwnd)
                    sig = control.signature(items, texts)
                    if last_sig is not None and sig == last_sig and steps and "no se pudo" not in steps[-1]:
                        steps[-1] += " — no cambió nada en la ventana"
                        still += 1
                        if still >= 4:
                            result = "varios pasos seguidos sin cambiar nada en la ventana"
                            break
                    elif last_sig is not None:
                        still = 0
                        # qué apareció de nuevo: así el modelo nota «sonando…» o «guardado» y sabe que ya está
                        new = [t for t in texts if t not in last_texts][:3]
                        if new and steps and "no se pudo" not in steps[-1]:
                            steps[-1] += " — ahora se ve: " + " | ".join(f"«{t[:70]}»" for t in new)
                    last_sig, last_texts = sig, texts
                    shot = None
                    if sees:
                        try:
                            shot = await asyncio.to_thread(control.capture, win.hwnd)
                        except Exception as e:  # noqa: BLE001
                            log.warning("No pude capturar la ventana: %s", e)
                    prompt = OPERATOR_STEP.format(window=control.describe(win.title, items, texts, shot),
                                                  steps="\n".join(steps) or "(ninguno todavía)")
                    images = [llm.Image("window", shot.jpeg, win.title[:60])] if shot else []
                    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
                    reply = "".join([p async for p in llm.stream_chat(messages, {"temperature": 0.2, "top_p": 0.9, "max_tokens": 450}, images)])
                    llm.pop_notices()
                    step = control.parse(reply)
                    log.info("Control %d%s: %r → %s", n, " (con imagen)" if shot else "", reply[:120], step and (step[0], [a[:60] for a in step[1]]))
                    if esc.pressed or self.control_stop:
                        result = f"{settings.user_name} lo paró" + (" con Esc" if esc.pressed else "")
                        break
                    if step is None:
                        bad += 1
                        if bad >= 3:
                            result = "no supe qué paso dar"
                            break
                        continue
                    verb, args = step
                    if verb == "listo":
                        ok, result = True, args[0] if args else "tarea hecha"
                        break
                    if verb == "no_puedo":
                        result = "no se pudo: " + (args[0] if args else "sin motivo")
                        break

                    # ---- a qué se refiere y cómo describirlo
                    item, xy, name, problem = None, None, "", ""
                    coords = re.findall(r"-?\d+", args[0]) if args else []
                    if verb in ("clic", "doble_clic") and len(coords) >= 2:
                        if not shot:
                            problem = "sin imagen de la ventana no hay clic por coordenadas: usa el número del control"
                        else:
                            xy = (int(coords[0]), int(coords[1]))
                            name = await asyncio.to_thread(control.name_at, shot, *xy)
                    elif verb in ("pulsar", "escribir", "doble_clic", "clic"):
                        item = control.pick(items, args[0], "escribir" if verb == "escribir" else "pulsar") if args else None
                        if item is None:
                            problem = f"no hay ningún control «{args[0] if args else ''}»"
                        elif verb == "escribir" and len(args) < 2:
                            problem = "falta el texto: escribir N | texto"
                        name = item.name if item else ""
                    if not problem and verb == "escribir" and item and (item.kind, item.name) in written and len(args[1]) > 60:
                        # un párrafo ya escrito no se repite (el modelo tendía a escribirlo otra vez)
                        problem = f"ya escribiste ese texto en «{item.name or item.kind}»: si está bien, responde listo"
                    elif verb == "tecla" and (not args or control._plain(args[0]) not in control.KEYS):
                        problem = f"no conozco la tecla «{args[0] if args else ''}»"
                    elif verb in ("atajo", "teclear", "rueda") and not args:
                        problem = "le falta el dato"
                    if problem:
                        bad += 1
                        steps.append(f"{n}. (paso no válido: {problem})")
                        if bad >= 4:
                            result = "se equivocó varias veces"
                            break
                        continue
                    key = control._plain(args[0]) if verb == "tecla" else ""
                    target = f"«{item.name or item.kind}»" if item else (f"({xy[0]},{xy[1]})" + (f" «{name[:40]}»" if name else "")) if xy else ""
                    desc = {"pulsar": f"Pulsar {target}", "clic": f"Clic en {target}", "doble_clic": f"Doble clic en {target}",
                            "escribir": f"Escribir «{args[1][:60]}» en {target}" if len(args) > 1 else "",
                            "teclear": f"Teclear «{args[0][:60]}»", "tecla": f"Tecla {key}", "atajo": f"Atajo {args[0][:20]}",
                            "rueda": f"Rueda {args[0][:10]}"}[verb]
                    # el mismo paso puede repetirse dos veces (cada una de forma más directa); a la cuarta, se para
                    if len(steps) >= 3 and all(s.split(" — ")[0].endswith(desc) for s in steps[-3:]):
                        result = "se quedó repitiendo el mismo paso"
                        break

                    # ---- lo delicado se confirma, salvo que la orden del usuario ya lo pidiera
                    kind = "enter" if key == "enter" or (verb == "atajo" and "enter" in control._plain(args[0])) else verb
                    if control.needs_confirm(kind, name, last_typed, win.title) and not control.task_allows(task, name):
                        if not await self._confirm(f"{desc} en «{win.title[:50]}»"):
                            steps.append(f"{n}. {desc} — {settings.user_name} NO lo aprobó")
                            result = f"{settings.user_name} no aprobó «{desc}»"
                            actions.log_entry("controlar", f"{desc} en «{win.title}»", "negada", "")
                            break
                    await self.send_json({"type": "control_step", "n": n, "max": control.MAX_STEPS, "text": desc})

                    # ---- hacerlo: si este mismo paso ya se probó sin efecto, se prueba de forma más directa
                    # (accesibilidad → mensajes a la ventana → teclado y ratón de verdad, solo si no usas la PC)
                    k = (verb, item.kind if item else "", item.name if item else "", xy, key, args[0][:40] if args else "")
                    attempt = attempts[k] = attempts.get(k, -1) + 1

                    def do():
                        if verb == "pulsar":
                            return control.press(item, win.hwnd, attempt)
                        if verb == "escribir":
                            return control.type_text(item, args[1][:3000], win.hwnd, attempt)
                        if verb in ("clic", "doble_clic") and xy:
                            return control.click_at(shot, *xy, win.hwnd, double=verb == "doble_clic", attempt=attempt)
                        if verb in ("clic", "doble_clic"):
                            return control.click_item(item, win.hwnd, double=verb == "doble_clic", attempt=attempt)
                        if verb == "teclear":
                            return control.type_here(args[0][:3000], win.hwnd, attempt)
                        if verb == "tecla":
                            return control.key(key, win.hwnd, attempt)
                        if verb == "atajo":
                            return control.hotkey(args[0], win.hwnd, attempt)
                        return control.scroll(win.hwnd, "arriba" not in control._plain(args[0]), attempt)
                    try:
                        esc.sending = verb in ("tecla", "atajo", "teclear", "escribir")
                        how = await asyncio.to_thread(do)
                    except control.ControlError as e:
                        steps.append(f"{n}. {desc} — no se pudo: {e}")
                        actions.log_entry("controlar", f"{desc} en «{win.title}»", "paso", f"no se pudo: {e}")
                        if "Cambiaste a otra ventana" in str(e):          # tomaste el control: se detiene
                            result = str(e)
                            break
                        bad += 1
                        if bad >= 4:
                            result = str(e)
                            break
                        continue
                    finally:
                        esc.sending = False
                    if verb == "escribir":
                        last_typed = item
                        if len(args[1]) > 60:
                            written.add((item.kind, item.name))
                    # Un texto ya escrito no se repite: sin esto, el modelo volvía a teclear el mismo párrafo.
                    done_note = " — HECHO: ese texto ya está escrito ahí; no lo vuelvas a escribir" if verb in ("escribir", "teclear") else ""
                    steps.append(f"{n}. {desc}{done_note}")
                    actions.log_entry("controlar", f"{desc} en «{win.title}»", "paso", how)
                    await asyncio.sleep(0.9)                 # que la ventana se actualice antes de mirarla otra vez
                else:
                    result = f"llegó al límite de {control.MAX_STEPS} pasos"
        except Exception as e:  # noqa: BLE001
            log.exception("El control de la ventana falló")
            result = f"falló ({type(e).__name__})"
        finally:
            self.controlling = None
            await asyncio.to_thread(control.release, win.hwnd)   # si la trajo al frente, te devuelve tu ventana
        actions.log_entry("controlar", req.detail, "terminada" if ok else "sin terminar", result)
        await self.send_json({"type": "control_end", "ok": ok, "text": result})
        done = "; ".join(s.split(". ", 1)[-1] for s in steps) or "ninguno"
        summary = (f"la tarea se completó: {result}. Pasos: {done}" if ok else
                   f"la tarea NO se completó ({result}). No digas que está hecha. Pasos que sí se dieron: {done}")
        self._later(ACTION_RESULT.format(user=settings.user_name, title=req.detail, result=summary))

    async def _timer(self, req: actions.Request):
        await asyncio.sleep(req.target["seconds"])
        label = req.target["label"]
        await self.send_json({"type": "notice", "message": "Se acabó el temporizador" + (f": {label}." if label else ".")})
        self._later(TIMER_DONE.format(user=settings.user_name, what=req.detail))

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
        """La ficha con el nombre de la voz elegida: si se cambia de voz en Ajustes, cambia en el siguiente turno."""
        return profile.character(self.base_persona)

    def _system(self) -> str:
        adult = adult_active(self.persona, is_cloud=settings.is_cloud, user_adult=profile.is_adult())
        past = [f"{time.strftime('%d/%m/%Y', time.localtime(ts))}: {text}" for text, ts in store.summaries(8)]
        return build_system_prompt(self.persona, user_name=settings.user_name, memories=store.memories(), adult=adult,
                                   about=profile.describe(settings.user_name), summaries=past, actions=self.actions_on(),
                                   control=llm.can_control())

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
        try:
            text = await llm.complete([{"role": "user", "content": SUMMARIZE.format(
                user=settings.user_name, name=name, dialog=dialog[:12000])}])
        except llm.LLMError as e:
            log.warning("No pude resumir la conversación: %s", e)
            self.summary_retry = time.monotonic() + 300
            return
        finally:
            self.phase = "idle"
            llm.pop_notices()
        text = re.sub(r"\[[^\]]*\]", "", text).strip()
        if len(text) > 20:
            store.add_summary(text[:900], rows[0][0], rows[-1][0], rows[-1][3])
            log.info("Recuerdo guardado (%d mensajes): %r", len(rows), text[:120])

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
            if self.outcomes and not instruction:          # cómo acabaron sus acciones, una sola vez
                done = f"\n(Tus acciones anteriores: {'; '.join(self.outcomes[-4:])}.)"
                self.outcomes = []
            if hint:                                        # orden clara: se le recuerda la etiqueta exacta
                done += (f"\n(Esto es una petición de tu lista. Empieza tu respuesta con "
                         f"[accion: {' | '.join([hint[0], *hint[1]])}] y di en una frase que lo haces.)")
            if refuse:
                done += (f"\n(Te pide algo en su PC, pero ahora no puedes hacerlo: {refuse}. Díselo con claridad en "
                         "una frase; no digas que lo vas a hacer.)")
            last["content"] = f"{turn_context(local_time(settings.timezone))}{done}\n{last['content']}"
        return messages

    # ------------------------------------------------------------ mirada en vivo
    async def _watch_loop(self):
        """Mientras se comparte la cámara o la pantalla, cada pocos segundos Mika mira por su cuenta. Solo lo
        hace si hubo movimiento, nadie está hablando y ha pasado un rato desde lo último que se dijo."""
        try:
            while not self.closed:
                await asyncio.sleep(settings.watch_interval)
                await self._expire_actions()
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
                moved = [src for src in FRAME_SOURCES if clips.get(src) and self.motion.get(src, 0) >= WATCH_MOTION]
                if not moved:
                    continue
                for src in moved:
                    self.motion[src] = 0.0
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
        log.info("Mirada en vivo (%s, %d imágenes, %.2fs): %r", "+".join(clips), len(images), time.perf_counter() - t0, reply[:120])
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

    async def _say_checked(self, text: str, voice: str, speed: float) -> bytes:
        """La frase en audio, comprobada: con la voz completa se escucha con Whisper y, si se comió una palabra, se
        genera otra vez (hasta VOICE_RETRIES) y se queda la mejor. La voz ligera (Piper) no lo necesita."""
        pcm = b"".join([c async for c in tts.stream_speech(text, voice, speed)])
        if settings.voice_engine != "completa" or not self.stt.ready or not pcm:
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
            log.info("Voz: faltó %s en %r (oído %r); repito", lost, text[:60], got[:60])
            if attempt < retries:
                pcm = b"".join([c async for c in tts.stream_speech(text, voice, speed)])
        if best_lost and voicecheck.bad(best_lost):
            log.info("Voz: tras %d intentos sigue faltando %s en %r", retries + 1, best_lost, text[:60])
        return best

    async def _speak(self, queue: asyncio.Queue, t0: float):
        voice = settings.tts_voice or self.persona["voice"].get("tts_voice")      # la elegida en la bienvenida
        speed = float(self.persona["voice"].get("speed", 1.0))
        tts_ok, idx, finish = True, 0, False
        while not finish:
            sentence = await queue.get()
            if sentence is None:
                return
            # Una frase muy corta («¡Hola, Danny!») el modelo de voz la dice mal casi siempre: si la siguiente llega
            # enseguida, van juntas (un solo subtítulo y un solo audio).
            if len(sentence.text) < SHORT_SENTENCE and settings.voice_engine == "completa":
                try:
                    nxt = await asyncio.wait_for(queue.get(), SHORT_WAIT)
                except asyncio.TimeoutError:
                    nxt = False                             # la siguiente tarda: esta va sola
                if nxt is None:
                    finish = True                           # era la última frase de la respuesta
                elif nxt:
                    sentence = Sentence(f"{sentence.text} {nxt.text}", sentence.emotion or nxt.emotion,
                                        [*sentence.gestures, *nxt.gestures])
            idx += 1
            if sentence.emotion:
                self.emotion = sentence.emotion
            await self.send_json({"type": "sentence", "id": idx, "text": sentence.text,
                                  "emotion": sentence.emotion, "gestures": sentence.gestures})
            if idx == 1:
                self.phase = "audio"
                log.info("Primera frase a los %.2fs", time.perf_counter() - t0)
            if tts_ok:
                try:
                    pcm = await self._say_checked(sentence.text, voice, speed)
                    for k in range(0, len(pcm), 9600):
                        chunk = pcm[k:k + 9600]
                        if not self.client_playing:
                            self.client_playing, self.play_started, self.audio_bytes = True, time.monotonic(), 0
                            log.info("Primer audio a los %.2fs", time.perf_counter() - t0)
                            await self.set_state("speaking")
                        self.audio_bytes += len(chunk)
                        await self.send_bytes(chunk)
                except tts.TTSError as e:
                    tts_ok = False
                    log.warning("Sin voz: %s", e)
                    await self.send_json({"type": "error", "message": "La voz no está disponible (nodo GPU apagado). "
                                                                      "Sigo respondiendo en texto."})
            self.sent_sentences.append(sentence.text)
            await self.send_json({"type": "sentence_end", "id": idx})

    def start(self):
        self.watcher = asyncio.create_task(self._watch_loop())

    async def close(self):
        self.closed = True
        self.control_stop = True              # una tarea con ratón y teclado se para al cerrar la ventana
        if self.watcher:
            self.watcher.cancel()
        for task in list(self.side):          # los temporizadores viven mientras la ventana está abierta
            task.cancel()
        for req in self.pending.values():
            actions.record(req, "sin respuesta (se cerró la ventana)", "")
        if self.turn_running:
            self.turn.cancel()
            await asyncio.gather(self.turn, return_exceptions=True)
