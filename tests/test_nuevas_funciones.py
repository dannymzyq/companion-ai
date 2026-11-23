"""Pruebas de las nuevas funciones: Gemini Live (reanudación + recordar), recordatorios persistentes y portapapeles."""
import asyncio
import json
import os
import time
import unittest

from companion import actions, gemini_live, state, store
from companion.config import settings
from companion.session import Session
from tests.test_gemini_live import FakeBrowserWS, FakeRemoteWS, FakeTranscriber


class TestGeminiLiveNuevas(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.prev_key = settings.gemini_api_key
        self.prev_preset = settings.cloud_preset
        self.prev_live = state.load().get("gemini_live", False)
        settings.gemini_api_key = "clave-prueba"
        settings.cloud_preset = "gemini"
        state.save(gemini_live=True, provider="gemini",
                   cloud={"preset": "gemini", "key": "clave-prueba", "base": settings.gemini_base, "model": ""})

    def tearDown(self):
        state.save(gemini_live=self.prev_live)
        settings.gemini_api_key = self.prev_key
        settings.cloud_preset = self.prev_preset

    def test_setup_incluye_compresion_y_reanudacion(self):
        c1 = gemini_live.GeminiLiveClient("k", "sys")
        s1 = c1.build_setup()["setup"]
        self.assertIn("contextWindowCompression", s1)
        self.assertEqual(s1["sessionResumption"], {})

        c2 = gemini_live.GeminiLiveClient("k", "sys", resume_handle="tok-123")
        s2 = c2.build_setup()["setup"]
        self.assertEqual(s2["sessionResumption"], {"handle": "tok-123"})

    async def test_recordar_y_reanudacion_en_sesion(self):
        remote = FakeRemoteWS([
            {"setupComplete": {}},
            {"sessionResumptionUpdate": {"newHandle": "handle-xyz", "resumable": True}},
            {"toolCall": {"functionCalls": [
                {"id": "r1", "name": "recordar", "args": {"dato": "A Danny le encanta el café frío por las mañanas"}},
                {"id": "r2", "name": "recordar", "args": {"dato": "Su contraseña es 12345678"}},
            ]}},
            {"serverContent": {"outputTranscription": {"text": "¡Anotado!"}}},
            {"serverContent": {"turnComplete": True}},
            {"goAway": {"timeLeft": "30s"}},
        ])
        browser = FakeBrowserWS()
        persona = {"name": "Mika", "age": 22, "speaks": "f", "role": "asistente", "personality": "cercana"}
        sess = Session(browser, persona, FakeTranscriber())
        sess._live_factory = lambda key, sys_p, **kw: gemini_live.GeminiLiveClient(
            key, sys_p, ws_connect=lambda url, **c_kw: asyncio.sleep(0, result=remote), **kw
        )

        await sess.on_message({"type": "text", "text": "Me encanta el café frío por las mañanas"})
        if sess.live_task:
            await asyncio.wait_for(sess.live_task, 5)

        self.assertEqual(sess._live_resume_handle, "handle-xyz")
        mems = store.memories(50)
        self.assertTrue(any("café frío" in m for m in mems))
        self.assertFalse(any("contraseña" in m for m in mems))

        # Respuestas silenciosas (scheduling SILENT)
        tr = [m["toolResponse"]["functionResponses"] for m in remote.sent if "toolResponse" in m]
        self.assertTrue(tr)
        self.assertEqual(tr[0][0]["response"]["scheduling"], "SILENT")
        self.assertTrue(tr[0][0]["response"]["ok"])
        self.assertFalse(tr[0][1]["response"]["ok"])

        store.delete_memory("A Danny le encanta el café frío por las mañanas")
        await sess.close()


class TestRecordatoriosYPortapapeles(unittest.TestCase):
    def test_recordatorio_preparar_adivinar_y_persistir(self):
        g = actions.guess("Recuérdame mañana a las 9 llamar al dentista")
        self.assertIsNotNone(g)
        self.assertEqual(g[0], "recordatorio")

        req = actions.prepare("recordatorio", ["en 2 horas", "revisar el horno"])
        self.assertEqual(req.name, "recordatorio")
        self.assertGreater(req.target["due_ts"], time.time() + 3600)

        rid = store.add_reminder(time.time() - 5, "probar recordatorio vencido")
        try:
            due = store.due_reminders()
            self.assertTrue(any(r[0] == rid for r in due))
            store.mark_reminder_done(rid)
            due_after = store.due_reminders()
            self.assertFalse(any(r[0] == rid for r in due_after))
        finally:
            store.delete_reminder(rid)

    def test_portapapeles_bajo_demanda(self):
        g = actions.guess("Traduce lo que acabo de copiar")
        self.assertIsNotNone(g)
        self.assertEqual(g[0], "portapapeles")

        req = actions.prepare("portapapeles", ["leer"])
        old = os.environ.get("COMPANION_CLIPBOARD_TEST")
        os.environ["COMPANION_CLIPBOARD_TEST"] = "Hello world from clipboard"
        try:
            out = actions.run(req)
            self.assertIn("Hello world from clipboard", out)
        finally:
            if old is None:
                os.environ.pop("COMPANION_CLIPBOARD_TEST", None)
            else:
                os.environ["COMPANION_CLIPBOARD_TEST"] = old


if __name__ == "__main__":
    unittest.main()
