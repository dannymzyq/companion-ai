"""Pruebas unitarias de la integración con Gemini Live API (sin red ni GPU).

Cubren:
  - Cliente WebSocket (setup, audio 16 kHz, imagen JPEG, texto, eventos de respuesta e interrupción).
  - Sesión en modo Gemini Live (retransmisión de audio 24 kHz, subtítulos en vivo, guardado en memoria y barge-in).
  - Interruptor de ajustes (_gemini_live_changes y profile.apply).
"""
import asyncio
import base64
import json
import unittest

from tests import ROOT  # noqa: F401  (fija DATA_DIR temporal)

from companion import gemini_live, profile, server, state, store
from companion.config import settings
from companion.session import Session


class FakeRemoteWS:
    """Simula el WebSocket de Google BidiGenerateContent."""

    def __init__(self, incoming: list[dict]):
        self.sent: list[dict] = []
        self._incoming = [json.dumps(m) for m in incoming]
        self.closed = False

    async def send(self, text: str):
        self.sent.append(json.loads(text))

    async def recv(self) -> str:
        if not self._incoming:
            raise EOFError("Sin mensajes")
        return self._incoming.pop(0)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)

    async def close(self):
        self.closed = True


class FakeBrowserWS:
    """Simula el WebSocket /ws de la interfaz del companion."""

    def __init__(self):
        self.json_msgs: list[dict] = []
        self.audio_chunks: list[bytes] = []

    async def send_text(self, text: str):
        self.json_msgs.append(json.loads(text))

    async def send_bytes(self, data: bytes):
        self.audio_chunks.append(data)


class FakeTranscriber:
    ready = False
    device = "cpu"
    engine = "nube"


class GeminiLiveClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_y_recepcion_eventos(self):
        pcm_out = b"\x01\x02\x03\x04" * 20
        remote = FakeRemoteWS([
            {"setupComplete": {}},
            {"serverContent": {"inputTranscription": {"text": "Hola Mika"}}},
            {"serverContent": {"modelTurn": {"parts": [{"inlineData": {
                "mimeType": "audio/pcm;rate=24000",
                "data": base64.b64encode(pcm_out).decode("ascii"),
            }}]}}},
            {"serverContent": {"outputTranscription": {"text": "[emo:feliz] ¡Hola!"}}},
            {"serverContent": {"interrupted": True}},
            {"serverContent": {"turnComplete": True}},
        ])

        async def connect(url, **kw):
            self.assertIn("key=clave-demo", url)
            return remote

        client = gemini_live.GeminiLiveClient(
            "clave-demo", "Eres Mika.", model="gemini-2.5-flash-native-audio-latest",
            voice_name="Aoede", ws_connect=connect,
        )
        await client.connect()
        self.assertTrue(client.connected)
        setup = remote.sent[0]["setup"]
        self.assertEqual(setup["model"], "models/gemini-2.5-flash-native-audio-latest")
        self.assertEqual(setup["generationConfig"]["responseModalities"], ["AUDIO"])
        self.assertEqual(setup["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"], "Aoede")
        self.assertIn("inputAudioTranscription", setup)
        self.assertIn("outputAudioTranscription", setup)

        await client.send_audio(b"\x00\x01" * 160)
        await client.send_image("/9j/fakejpeg")
        await client.send_text("¿Cómo estás?")
        self.assertEqual(remote.sent[1]["realtimeInput"]["audio"]["mimeType"], "audio/pcm;rate=16000")
        self.assertEqual(remote.sent[2]["realtimeInput"]["video"]["mimeType"], "image/jpeg")
        self.assertTrue(remote.sent[3]["clientContent"]["turnComplete"])

        events = [ev async for ev in client.receive()]
        self.assertEqual(events[0], ("in_text", "Hola Mika"))
        self.assertEqual(events[1], ("audio", pcm_out))
        self.assertEqual(events[2], ("out_text", "[emo:feliz] ¡Hola!"))
        self.assertEqual(events[3], ("interrupted", None))
        self.assertEqual(events[4], ("turn_complete", None))
        await client.close()
        self.assertTrue(remote.closed)

    async def test_sin_clave_falla(self):
        client = gemini_live.GeminiLiveClient("", "Eres Mika.")
        with self.assertRaises(gemini_live.GeminiLiveError):
            await client.connect()

    def test_helpers(self):
        self.assertEqual(gemini_live.voice_for("mika", "f"), "Aoede")
        self.assertEqual(gemini_live.voice_for("kenji", "m"), "Puck")
        self.assertEqual(gemini_live.voice_for("desconocida", "m"), "Puck")
        self.assertEqual(gemini_live.clean_spoken_text("[emo:feliz] Hola [gesto:saludar]"), "Hola")
        self.assertEqual(gemini_live.model_uri("gemini-2.5-flash-native-audio-latest"),
                         "models/gemini-2.5-flash-native-audio-latest")


class GeminiLiveSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        store.forget_all()
        self.prev_key = settings.gemini_api_key
        self.prev_preset = settings.cloud_preset
        settings.gemini_api_key = "clave-prueba"
        settings.cloud_preset = "gemini"
        state.save(gemini_live=True, provider="gemini", cloud={"preset": "gemini", "key": "clave-prueba", "base": settings.gemini_base, "model": ""})

    def tearDown(self):
        state.save(gemini_live=False)
        settings.gemini_api_key = self.prev_key
        settings.cloud_preset = self.prev_preset

    async def test_turno_texto_audio_imagen_y_memoria(self):
        pcm_reply = b"\x10\x20" * 120
        remote = FakeRemoteWS([
            {"setupComplete": {}},
            {"serverContent": {"modelTurn": {"parts": [{"inlineData": {
                "mimeType": "audio/pcm;rate=24000",
                "data": base64.b64encode(pcm_reply).decode("ascii"),
            }}]}}},
            {"serverContent": {"outputTranscription": {"text": "¡Hola! Todo listo en vivo."}}},
            {"serverContent": {"turnComplete": True}},
        ])
        browser = FakeBrowserWS()
        persona = {"name": "Mika", "age": 22, "speaks": "f", "role": "asistente", "personality": "cercana"}
        sess = Session(browser, persona, FakeTranscriber())

        async def connect(url, **kw):
            return remote

        sess._live_factory = lambda key, sys_p, **kw: gemini_live.GeminiLiveClient(
            key, sys_p, ws_connect=connect, **kw
        )

        await sess.on_message({"type": "text", "text": "Hola desde pruebas"})
        # Esperar a que termine el bucle receptor del turno simulado
        if sess.live_task:
            await asyncio.wait_for(sess.live_task, 5)

        types = [m["type"] for m in browser.json_msgs]
        self.assertIn("user_text", types)
        self.assertIn("sentence", types)
        self.assertIn("caption_delta", types)
        self.assertIn("sentence_end", types)
        self.assertIn("reply_end", types)
        self.assertEqual(b"".join(browser.audio_chunks), pcm_reply)

        # Verifica que guardó el turno en el historial (memoria)
        hist = store.recent(10)
        self.assertTrue(any(m["role"] == "user" and "Hola desde pruebas" in m["content"] for m in hist))
        self.assertTrue(any(m["role"] == "assistant" and "Todo listo en vivo." in m["content"] for m in hist))
        await sess.close()

    async def test_audio_e_imagen_se_reenvian_en_vivo(self):
        gate = asyncio.Event()

        class BlockingWS(FakeRemoteWS):
            async def __anext__(self):
                await gate.wait()
                raise StopAsyncIteration

        remote = BlockingWS([{"setupComplete": {}}])
        browser = FakeBrowserWS()
        persona = {"name": "Mika", "age": 22, "speaks": "f", "role": "asistente", "personality": "cercana"}
        sess = Session(browser, persona, FakeTranscriber())
        sess._live_factory = lambda key, sys_p, **kw: gemini_live.GeminiLiveClient(
            key, sys_p, ws_connect=lambda url, **c_kw: asyncio.sleep(0, result=remote), **kw
        )

        await sess.on_audio(b"\x01\x02" * 1600)       # 3200 bytes (>= 3072 umbral de lote)
        await sess.on_message({"type": "frame", "source": "screen", "jpeg": "/9j/camframe"})
        await sess.on_message({"type": "screen_audio", "pcm": base64.b64encode(b"\x03\x04" * 1600).decode("ascii")})
        await asyncio.sleep(0.05)

        audio_msgs = [m for m in remote.sent if "realtimeInput" in m and "audio" in m["realtimeInput"]]
        self.assertGreaterEqual(len(audio_msgs), 2)   # micrófono + sonido de pantalla compartida
        self.assertTrue(any("realtimeInput" in m and "video" in m["realtimeInput"] for m in remote.sent))
        # No debe emitir aviso de «hace falta tarjeta NVIDIA» en modo Gemini Live
        self.assertFalse(any(m.get("type") == "notice" for m in browser.json_msgs))
        gate.set()
        await sess.close()

    async def test_tool_call_ejecuta_accion_y_responde(self):
        remote = FakeRemoteWS([
            {"setupComplete": {}},
            {"toolCall": {"functionCalls": [{
                "id": "call-1",
                "name": "ejecutar_accion",
                "args": {"accion": "controlar", "arg1": "Apple Music", "arg2": "pon La Barca"},
            }]}},
            {"serverContent": {"outputTranscription": {"text": "¡Listo! Pongo La Barca en Apple Music."}}},
            {"serverContent": {"turnComplete": True}},
        ])
        browser = FakeBrowserWS()
        persona = {"name": "Mika", "age": 22, "speaks": "f", "role": "asistente", "personality": "cercana"}
        sess = Session(browser, persona, FakeTranscriber())
        asked = []

        async def fake_exec(wanted, trusted, card=False):
            asked.append((wanted, trusted))

        sess._live_exec_actions = fake_exec
        sess._live_factory = lambda key, sys_p, **kw: gemini_live.GeminiLiveClient(
            key, sys_p, ws_connect=lambda url, **c_kw: asyncio.sleep(0, result=remote), **kw
        )

        await sess.on_message({"type": "text", "text": "Abre Apple Music y pon La Barca"})
        if sess.live_task:
            await asyncio.wait_for(sess.live_task, 5)
        if sess.side:
            await asyncio.gather(*list(sess.side))

        setup = remote.sent[0]["setup"]
        self.assertIn("tools", setup)
        self.assertIn("temperature", setup["generationConfig"])
        self.assertEqual(len(asked), 1)
        self.assertEqual(asked[0][0], [("controlar", ["Apple Music", "pon La Barca"])])
        self.assertTrue(any("toolResponse" in m for m in remote.sent))
        await sess.close()

    def _sess(self, remote):
        browser = FakeBrowserWS()
        persona = {"name": "Mika", "age": 22, "speaks": "f", "role": "asistente", "personality": "cercana"}
        sess = Session(browser, persona, FakeTranscriber())
        sess._live_factory = lambda key, sys_p, **kw: gemini_live.GeminiLiveClient(
            key, sys_p, ws_connect=lambda url, **c_kw: asyncio.sleep(0, result=remote), **kw
        )
        return sess, browser

    async def _drain(self, sess):
        if sess.live_task:
            await asyncio.wait_for(sess.live_task, 5)
        if sess.side:
            await asyncio.gather(*list(sess.side))

    async def test_saludo_no_puede_ejecutar_acciones(self):
        """Saludo, mirada, toques y temporizadores no son turnos del usuario: la herramienta se rechaza."""
        remote = FakeRemoteWS([
            {"setupComplete": {}},
            {"toolCall": {"functionCalls": [{"id": "c1", "name": "ejecutar_accion",
                                             "args": {"accion": "abrir_web", "arg1": "https://example.com"}}]}},
            {"serverContent": {"turnComplete": True}},
        ])
        sess, _ = self._sess(remote)
        asked = []

        async def fake_exec(wanted, trusted, card=False):
            asked.append(wanted)
        sess._live_exec_actions = fake_exec
        await sess.on_message({"type": "start"})
        await self._drain(sess)
        self.assertEqual(asked, [])
        resp = [m for m in remote.sent if "toolResponse" in m][0]["toolResponse"]["functionResponses"][0]
        self.assertFalse(resp["response"]["ok"])
        await sess.close()

    async def test_sonido_de_pantalla_no_aprueba_ni_ordena(self):
        """Con la pantalla sonando, un «sí» oído no aprueba tarjetas y las acciones piden tarjeta."""
        remote = FakeRemoteWS([
            {"setupComplete": {}},
            {"serverContent": {"inputTranscription": {"text": "sí"}}},
            {"toolCall": {"functionCalls": [{"id": "c1", "name": "ejecutar_accion",
                                             "args": {"accion": "abrir_web", "arg1": "https://example.com"}}]}},
            {"serverContent": {"turnComplete": True}},
        ])
        sess, _ = self._sess(remote)
        got = []

        async def fake_exec(wanted, trusted, card=False):
            got.append(card)
        sess._live_exec_actions = fake_exec
        answered = []

        async def fake_answer(req, verdict):
            answered.append(verdict)
        sess._answer = fake_answer

        class Req:
            id = "r1"
        sess.pending["r1"] = Req()
        sess._live_screen_at = __import__("time").monotonic()
        await sess._ensure_live()
        await self._drain(sess)
        self.assertEqual(answered, [])
        self.assertIn("r1", sess.pending)
        self.assertEqual(got, [True])
        sess.pending.clear()
        await sess.close()


class GeminiLiveSettingsTests(unittest.TestCase):
    def setUp(self):
        self.prev_key = settings.gemini_api_key
        self.prev_preset = settings.cloud_preset
        state.save(gemini_live=False, cloud_only=False, provider="local",
                   ear={"engine": "local"}, voice_engine="ligera",
                   cloud={"preset": "gemini", "key": "clave-live", "base": settings.gemini_base, "model": ""})

    def tearDown(self):
        state.save(gemini_live=False, cloud_only=False)
        settings.gemini_api_key = self.prev_key
        settings.cloud_preset = self.prev_preset
        profile.apply()

    def test_encender_y_apagar_restaura_ajustes(self):
        on = server._gemini_live_changes(True, {})
        self.assertTrue(on["gemini_live"])
        self.assertEqual(on["provider"], "gemini")
        self.assertEqual(on["ear"]["engine"], "nube")
        self.assertEqual(on["voice_engine"], "nube")
        state.save(**on)

        off = server._gemini_live_changes(False, {})
        self.assertFalse(off["gemini_live"])
        self.assertEqual(off["provider"], "local")
        self.assertEqual(off["ear"]["engine"], "local")
        self.assertEqual(off["voice_engine"], "ligera")

    def test_sin_clave_gemini_rechaza(self):
        state.save(cloud={"preset": "openai", "key": "sk-otra", "base": "https://api.openai.com/v1", "model": "gpt-4o"})
        with self.assertRaises(ValueError):
            server._gemini_live_changes(True, {})


if __name__ == "__main__":
    unittest.main()
