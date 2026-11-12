"""Una conversación en vivo: micrófono → VAD → Whisper → LLM → voz → avatar.

Protocolo del WebSocket (/ws):
  cliente → servidor   binario: PCM 16 bits mono 16 kHz del micrófono
                       {"type":"start"} · {"type":"text","text":"..."} · {"type":"interrupt"} · {"type":"playback_end"}
  servidor → cliente   {"type":"state","value":"idle|listening|thinking|speaking"}
                       {"type":"user_text","text":"..."}
                       {"type":"sentence","id":n,"text":"...","emotion":"feliz"|null,"gestures":[...]}
                       binario: PCM 16 bits mono 24 kHz de esa frase · {"type":"sentence_end","id":n}
                       {"type":"reply_end","text":"..."} · {"type":"interrupt"} · {"type":"error","message":"..."}
"""
import asyncio
import json
import logging
import re
import time
from collections import deque

import numpy as np

from . import llm, profile, store, tts
from .config import settings
from .prompt import OBSERVE, SUMMARIZE, adult_active, build_system_prompt, local_time, sampling_for, turn_context
from .tags import TagStream
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
        messages = self._messages(instruction)
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
                store.add_message("assistant", full, self.emotion)
            for fact in parser.memories:
                store.add_memory(fact)
            await self.send_json({"type": "reply_end", "text": full})
        self.phase, self.turn_text, self.turn_audio = "idle", None, None
        if not self.client_playing:
            await self.set_state("idle")

    @property
    def persona(self) -> dict:
        """La ficha con el nombre de la voz elegida: si se cambia de voz en Ajustes, cambia en el siguiente turno."""
        return profile.character(self.base_persona)

    def _system(self) -> str:
        adult = adult_active(self.persona, is_cloud=settings.is_cloud, user_adult=profile.is_adult())
        past = [f"{time.strftime('%d/%m/%Y', time.localtime(ts))}: {text}" for text, ts in store.summaries(8)]
        return build_system_prompt(self.persona, user_name=settings.user_name, memories=store.memories(), adult=adult,
                                   about=profile.describe(settings.user_name), summaries=past)

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

    def _messages(self, instruction: str | None = None) -> list[dict]:
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
            last["content"] = f"{turn_context(local_time(settings.timezone))}\n{last['content']}"
        return messages

    # ------------------------------------------------------------ mirada en vivo
    async def _watch_loop(self):
        """Mientras se comparte la cámara o la pantalla, cada pocos segundos Mika mira por su cuenta. Solo lo
        hace si hubo movimiento, nadie está hablando y ha pasado un rato desde lo último que se dijo."""
        try:
            while not self.closed:
                await asyncio.sleep(settings.watch_interval)
                now = time.monotonic()
                # Memoria: en un rato de calma, resume lo que ya salió de la ventana de corto plazo.
                if (not self.busy and not self.in_speech and self.state == "idle" and now - self.last_talk > SUMMARY_QUIET
                        and now > self.summary_retry and len(store.unsummarized(self.anchor, SUMMARY_MIN)) >= SUMMARY_MIN):
                    self.turn = asyncio.create_task(self._guard(self._summarize()))
                    continue
                if (not self.watch or self.busy or self.in_speech or self.run or self.state != "idle"
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

    async def _speak(self, queue: asyncio.Queue, t0: float):
        voice = settings.tts_voice or self.persona["voice"].get("tts_voice")      # la elegida en la bienvenida
        speed = float(self.persona["voice"].get("speed", 1.0))
        tts_ok, idx = True, 0
        while True:
            sentence = await queue.get()
            if sentence is None:
                return
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
                    async for chunk in tts.stream_speech(sentence.text, voice, speed):
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
        if self.watcher:
            self.watcher.cancel()
        if self.turn_running:
            self.turn.cancel()
            await asyncio.gather(self.turn, return_exceptions=True)
