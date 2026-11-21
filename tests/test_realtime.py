"""Conversación en vivo con varios proveedores (21 nov 2026), sin red ni GPU.

Cubren:
  - RealtimeClient (protocolo de OpenAI Realtime: OpenAI, xAI, Qwen): configuración, eventos y herramientas.
  - `expresar`: la emoción y el gesto llegan a la interfaz sin frenar la voz; la deducida del texto va antes.
  - Ajustes del proveedor en vivo (clave propia o la de Gemini) y que en vivo no se cargue Whisper ni la voz completa.
  - Modelos propios de Ollama: los de embeddings no se ofrecen; los «:cloud» no piden memoria de vídeo.
"""
import asyncio
import base64
import json
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (fija DATA_DIR temporal)

from companion import gemini_live, lifecycle, llm, profile, realtime, server, state, store
from companion.config import settings
from companion.session import Session


class FakeWS:
    def __init__(self, incoming):
        self.sent = []
        self._in = [json.dumps(m) for m in incoming]

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        return self._in.pop(0)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._in:
            raise StopAsyncIteration
        return self._in.pop(0)

    async def close(self):
        pass


class Browser:
    def __init__(self):
        self.json_msgs, self.audio = [], []

    async def send_text(self, t):
        self.json_msgs.append(json.loads(t))

    async def send_bytes(self, b):
        self.audio.append(b)


class Ear:
    ready, device, engine = False, "cpu", "nube"


PERSONA = {"name": "Mika", "age": 22, "speaks": "f", "role": "asistente", "personality": "cercana"}


class RealtimeClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_ga_conecta_y_traduce_eventos(self):
        pcm = b"\x05\x06" * 50
        ws = FakeWS([{"type": "session.created"}, {"type": "session.updated"},
                     {"type": "response.created"},
                     {"type": "response.output_audio.delta", "delta": base64.b64encode(pcm).decode()},
                     {"type": "response.output_audio_transcript.delta", "delta": "¡Hola!"},
                     {"type": "conversation.item.input_audio_transcription.completed", "transcript": "hola"},
                     {"type": "response.function_call_arguments.done", "call_id": "c1", "name": "expresar",
                      "arguments": "{\"emocion\": \"feliz\"}"},
                     {"type": "input_audio_buffer.speech_started"},
                     {"type": "response.done", "response": {"status": "completed", "output": [{"type": "message"}]}}])
        seen = {}

        async def connect(url, **kw):
            seen["url"], seen["headers"] = url, kw.get("additional_headers")
            return ws
        c = realtime.RealtimeClient("k-demo", "Eres Mika.", provider="openai", tools=[gemini_live.EXPRESS_TOOL],
                                    ws_connect=connect)
        await c.connect()
        self.assertTrue(c.connected)
        self.assertIn("model=gpt-realtime", seen["url"])
        self.assertEqual(seen["headers"]["Authorization"], "Bearer k-demo")
        sess = ws.sent[0]["session"]
        self.assertEqual(sess["type"], "realtime")
        self.assertEqual(sess["audio"]["input"]["format"]["rate"], 24000)
        self.assertEqual(sess["tools"][0]["parameters"]["type"], "object")       # tipos de Gemini en minúsculas
        self.assertIn("Modo en vivo", sess["instructions"])

        await c.send_audio(b"\x00\x01" * 1600)                                   # 100 ms a 16 kHz → 24 kHz
        audio = base64.b64decode(ws.sent[1]["audio"])
        self.assertEqual(len(audio), 2400 * 2)
        events = [e async for e in c.receive()]
        kinds = [e[0] for e in events]
        self.assertEqual(kinds, ["audio", "out_text", "in_text", "tool_call", "interrupted", "turn_complete"])
        self.assertEqual(events[0][1], pcm)
        self.assertEqual(events[3][1][0]["args"], {"emocion": "feliz"})

    async def test_herramientas_silenciosas_no_piden_otra_respuesta(self):
        ws = FakeWS([{"type": "session.updated"}])
        c = realtime.RealtimeClient("k", "x", provider="xai", ws_connect=lambda url, **kw: asyncio.sleep(0, result=ws))
        await c.connect()
        self.assertEqual(ws.sent[0]["session"]["voice"], "Ara")                  # protocolo «beta» (campos planos)
        await c.send_tool_response([{"id": "c1", "name": "expresar", "response": {"ok": True}}])
        self.assertFalse(any(m["type"] == "response.create" for m in ws.sent))
        await c.send_tool_response([{"id": "c2", "name": "ejecutar_accion", "response": {"ok": True}}])
        self.assertEqual(ws.sent[-1]["type"], "response.create")
        await c.send_text("contexto", end_of_turn=False)
        self.assertEqual(ws.sent[-1]["type"], "conversation.item.create")

    async def test_error_al_configurar_y_sin_clave(self):
        ws = FakeWS([{"type": "error", "error": {"message": "modelo desconocido"}}])
        c = realtime.RealtimeClient("k", "x", provider="qwen", ws_connect=lambda url, **kw: asyncio.sleep(0, result=ws))
        with self.assertRaises(gemini_live.GeminiLiveError):
            await c.connect()
        with self.assertRaises(gemini_live.GeminiLiveError):
            await realtime.RealtimeClient("", "x", provider="openai").connect()

    def test_gemini_marca_expresar_como_no_bloqueante(self):
        c = gemini_live.GeminiLiveClient("k", "x", tools=[gemini_live.EXPRESS_TOOL, *gemini_live.ACTION_TOOLS])
        decl = c.build_setup()["setup"]["tools"][0]["functionDeclarations"]
        self.assertEqual(decl[0]["behavior"], "NON_BLOCKING")
        self.assertNotIn("behavior", decl[1])

    def test_emocion_deducida(self):
        self.assertEqual(gemini_live.guess_emotion("Lo siento mucho, de verdad"), "triste")
        self.assertEqual(gemini_live.guess_emotion("¡Wow, en serio? Cuéntame"), "sorprendida")
        self.assertIsNone(gemini_live.guess_emotion("Son las cinco."))


class ExpresarSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        store.forget_all()
        state.save(gemini_live=True, provider="gemini", live={},
                   cloud={"preset": "gemini", "key": "clave-prueba", "base": settings.gemini_base, "model": ""})

    def tearDown(self):
        state.save(gemini_live=False, live={})

    async def test_expresar_mueve_cara_y_cuerpo_sin_frenar(self):
        remote = FakeWS([
            {"setupComplete": {}},
            {"serverContent": {"outputTranscription": {"text": "¡Qué emoción, felicidades!"}}},
            {"toolCall": {"functionCalls": [{"id": "e1", "name": "expresar",
                                             "args": {"emocion": "emocionada", "gesto": "celebrar"}}]}},
            {"serverContent": {"turnComplete": True}},
        ])
        browser = Browser()
        sess = Session(browser, {**PERSONA, "personality": {"name": "Alegre"}}, Ear())
        prompts = []

        def factory(key, sys_p, **kw):
            prompts.append(sys_p)
            self.assertEqual(kw["tools"][0]["name"], "expresar")
            return gemini_live.GeminiLiveClient(key, sys_p, ws_connect=lambda url, **c: asyncio.sleep(0, result=remote), **kw)
        sess._live_factory = factory
        await sess.on_message({"type": "text", "text": "¡Me ascendieron!"})
        await asyncio.wait_for(sess.live_task, 5)
        express = [m for m in browser.json_msgs if m["type"] == "express"]
        self.assertEqual(express[0]["emotion"], "emocionada")                    # deducida del texto, al momento
        self.assertEqual(express[-1], {"type": "express", "emotion": "emocionada", "gestures": ["celebrar"]})
        resp = [m for m in remote.sent if "toolResponse" in m][0]["toolResponse"]["functionResponses"][0]
        self.assertEqual(resp["response"]["scheduling"], "SILENT")
        self.assertFalse(sess._live_in_tool)
        self.assertIn("Recuerda quién eres", prompts[0])                         # resumen de personalidad al final
        self.assertIn("(Contexto: ahora es", prompts[0])                       # hora y ánimo, en el prompt
        self.assertFalse([m for m in remote.sent if "clientContent" in m and not m["clientContent"]["turnComplete"]])
        await sess.close()


class LiveSettingsTests(unittest.TestCase):
    def setUp(self):
        state.save(gemini_live=False, live={}, provider="gemini",
                   cloud={"preset": "gemini", "key": "clave-gemini", "base": settings.gemini_base, "model": ""})

    def tearDown(self):
        state.save(gemini_live=False, live={})
        profile.apply()

    def test_gemini_usa_la_clave_del_cerebro_y_otros_la_suya(self):
        self.assertEqual(profile.live()["key"], "clave-gemini")
        state.save(live=server._live_settings({"provider": "openai"}))
        self.assertEqual(profile.live()["key"], "")
        with self.assertRaises(ValueError):
            server._gemini_live_changes(True, {})
        state.save(live=server._live_settings({"provider": "openai", "key": "sk-x", "model": "gpt-realtime-mini"}))
        self.assertEqual(profile.live()["model"], "gpt-realtime-mini")
        self.assertTrue(server._gemini_live_changes(True, {})["gemini_live"])
        self.assertFalse(profile.public_live()["has_key"] and "key" in profile.public_live())   # la clave no sale

    def test_ni_un_trozo_de_la_clave_del_cerebro_sale(self):
        state.save(cloud={"preset": "gemini", "key": "zzqx-secreto-9876", "base": settings.gemini_base, "model": ""})
        out = json.dumps(profile.public_cloud())
        self.assertNotIn("9876", out)                                           # ni sus últimos caracteres
        self.assertTrue(profile.public_cloud()["has_key"])

    def test_cambiar_de_proveedor_olvida_la_clave_anterior(self):
        state.save(live=server._live_settings({"provider": "xai", "key": "xai-k"}))
        lv = server._live_settings({"provider": "qwen"})
        self.assertNotIn("key", lv)
        with self.assertRaises(ValueError):
            server._live_settings({"provider": "custom", "url": "http://inseguro"})

    def test_en_vivo_no_carga_whisper_ni_la_voz_completa(self):
        state.save(gemini_live=True, ear={"engine": "local"}, voice_engine="completa")
        profile.apply()
        self.assertEqual(profile.ear_engine(), "nube")
        self.assertNotEqual(profile.engine_now()[0], "completa")
        out = asyncio.run(lifecycle.loading(Ear()))
        self.assertEqual([i["id"] for i in out["items"]], ["vivo"])
        self.assertFalse(out["busy"])


class OllamaPropiosTests(unittest.IsolatedAsyncioTestCase):
    async def test_embeddings_fuera_y_nube_marcada(self):
        caps = {"nomic-embed-text": ["embedding"], "llava:7b": ["completion", "vision"],
                "gpt-oss:120b-cloud": ["completion", "tools"]}

        class R:
            def __init__(self, c):
                self.c = c

            def json(self):
                return {"capabilities": self.c}

        async def post(url, json=None, timeout=None):
            return R(caps[json["model"]])
        llm._caps.clear()
        with mock.patch.object(llm._local, "post", post):
            info = await llm.local_info(list(caps))
        self.assertFalse(info["nomic-embed-text"]["chat"])
        self.assertTrue(info["llava:7b"]["vision"])
        self.assertTrue(info["gpt-oss:120b-cloud"]["cloud"])


if __name__ == "__main__":
    unittest.main()
