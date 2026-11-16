"""Voz más rápida (16 nov 2026): muestra corta para F5 y audio que sale según llega cuando no se comprueba."""
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace as W
from unittest import mock

import numpy as np

from companion import session as session_mod
from companion import voice_import


def _palabras():
    # «Hola a todos. Hoy hace sol y me apetece salir. Luego vemos.» con pausas tras cada punto
    out, t = [], 0.3
    for frase in (["Hola", "a", "todos."], ["Hoy", "hace", "sol", "y", "me", "apetece", "salir."], ["Luego", "vemos."]):
        for w in frase:
            out.append(W(word=f" {w}", start=t, end=t + 0.45, probability=0.9))
            t += 0.5
        t += 0.4
    return out


class TestMuestraCorta(unittest.TestCase):
    def test_tramo_en_final_de_frase(self):
        x = np.zeros(int(8 * voice_import.SR), dtype=np.float32)
        with mock.patch.object(voice_import, "decode", return_value=x), \
             mock.patch.object(voice_import, "transcribe_words", return_value=_palabras()):
            s = voice_import.short_window(None, Path("x.wav"), "Hola a todos. Hoy hace sol y me apetece salir. Luego vemos.")
        self.assertIsNotNone(s)
        self.assertGreaterEqual(s["end"] - s["start"], voice_import.SHORT_MIN_S)
        self.assertLessEqual(s["end"] - s["start"], 6.0)
        self.assertTrue(s["text"].endswith("."), s["text"])
        self.assertTrue(0.8 <= s["speed"] <= 1.25)

    def test_sin_tramo(self):
        x = np.zeros(int(2 * voice_import.SR), dtype=np.float32)
        with mock.patch.object(voice_import, "decode", return_value=x), \
             mock.patch.object(voice_import, "transcribe_words", return_value=_palabras()[:3]):
            self.assertIsNone(voice_import.short_window(None, Path("x.wav"), "Hola a todos."))


class TestAudioSegunLlega(unittest.TestCase):
    def _sesion(self, device):
        s = session_mod.Session.__new__(session_mod.Session)
        s.stt = W(ready=True, device=device)
        return s

    def _trozos(self, s):
        async def voz(*a, **k):
            for c in (b"\1\0" * 10, b"\2\0" * 10, b"\3\0" * 10):
                yield c

        async def comprobada(*a, **k):
            return b"todo"

        async def run():
            with mock.patch.object(session_mod.tts, "stream_speech", voz), \
                 mock.patch.object(session_mod.settings, "voice_engine", "completa"), \
                 mock.patch.object(s, "_say_checked", comprobada):
                return [c async for c in s._say("Hola, ¿qué tal?", "mika_es", 1.0)]
        return asyncio.run(run())

    def test_sin_comprobar_sale_por_trozos(self):
        self.assertEqual(len(self._trozos(self._sesion("mps"))), 3)        # Mac: cada trozo según llega
        self.assertEqual(len(self._trozos(self._sesion("cpu"))), 3)

    def test_con_comprobacion_sale_entera(self):
        self.assertEqual(self._trozos(self._sesion("cuda")), [b"todo"])     # PC: la frase comprobada


class TestPartir(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voz"))
        import servidor
        self.s = servidor

    def test_sin_comas_se_parte_en_una_conjuncion(self):
        f = ("Primero caliento la leche en un cazo pequeño y luego le pongo un poco de canela por encima "
             "porque me encanta como huele.")
        with mock.patch.object(self.s, "LARGA", 90):
            trozos = self.s.partir(f)
        self.assertGreater(len(trozos), 1)
        self.assertEqual(" ".join(trozos), f)
        self.assertTrue(all(len(t) >= 25 for t in trozos))

    def test_la_corta_no_se_toca(self):
        with mock.patch.object(self.s, "LARGA", 90):
            self.assertEqual(self.s.partir("Me gusta mucho el café de la mañana."), ["Me gusta mucho el café de la mañana."])


if __name__ == "__main__":
    unittest.main()
