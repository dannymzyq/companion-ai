"""Modo rápido de la voz completa (tarjetas lentas, 18 nov 2026): las frases cortas se juntan antes de pedir el audio,
porque cada petición cuesta ~2 s fijos en una RTX 3050 de laptop y entre frases quedaban silencios."""
import asyncio
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from companion import session as S
from companion.config import settings
from companion.tags import Sentence


class Juntar(unittest.IsolatedAsyncioTestCase):
    async def _run(self, texts, fast):
        s = object.__new__(S.Session)
        s.sent_sentences, s.emotion, s.phase, s.asked_gesture = [], "neutral", "llm", None
        said, events = [], []

        async def say(text, voice, speed, engine=None):
            said.append(text)
            yield b"\x00\x00"

        async def send_json(ev):
            events.append(ev)

        async def send_audio(pcm, t0):
            return True
        s._say, s.send_json, s._send_audio = say, send_json, send_audio
        q: asyncio.Queue = asyncio.Queue()
        for t in texts:
            q.put_nowait(Sentence(t, None, []))
        q.put_nowait(None)
        with mock.patch.object(settings, "voice_engine", "completa"), \
                mock.patch.object(S.voz_proc, "fast", return_value=fast), mock.patch.object(S, "SHORT_WAIT", 0.05), \
                mock.patch.object(S.Session, "persona", {"voice": {"speed": 1.0}, "personality": {}}), \
                mock.patch.object(S.mood, "feel", lambda *a: None):
            await s._speak(q, 0.0)
        return said, [e["text"] for e in events if e["type"] == "sentence"]

    async def test_en_modo_rapido_junta_las_cortas(self):
        texts = ["Uf, qué cansancio.", "¿Comiste algo ya?", "Yo me haría unos fideos.", "Rápido y rico."]
        said, subs = await self._run(texts, fast=True)
        self.assertEqual(said, [" ".join(texts[:3]), texts[3]])   # dos peticiones en vez de cuatro
        self.assertEqual(subs, said)                              # y un solo subtítulo con lo mismo

    async def test_no_pasa_del_maximo(self):
        larga = "Esta es una frase bastante larga que ocupa sola casi todo lo que cabe en una petición rápida."
        said, _ = await self._run(["Vale.", larga, "Y otra corta."], fast=True)
        self.assertEqual(said, ["Vale.", larga, "Y otra corta."])     # «Vale.» + la larga no caben en una

    async def test_sin_modo_rapido_solo_la_muy_corta(self):
        said, _ = await self._run(["Hola.", "¿Comiste algo ya?", "Yo me haría unos fideos."], fast=False)
        self.assertEqual(said, ["Hola. ¿Comiste algo ya?", "Yo me haría unos fideos."])


if __name__ == "__main__":
    unittest.main()
