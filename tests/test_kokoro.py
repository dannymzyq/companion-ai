"""Voz Kokoro (24 nov 2026): la descarga solo se usa si coincide con su suma SHA-256."""
import asyncio
import hashlib
import shutil
import unittest
from unittest import mock

import httpx

from tests import TMP  # noqa: F401  (fija el entorno de prueba)

from companion import tts_kokoro


class DescargaKokoro(unittest.TestCase):
    def setUp(self):
        self.dir = TMP / "kokoro"
        shutil.rmtree(self.dir, ignore_errors=True)
        tts_kokoro.progress.clear()

    def _bajar(self, cuerpo: bytes, files: dict):
        real = httpx.AsyncClient
        transporte = httpx.MockTransport(lambda req: httpx.Response(200, content=cuerpo))
        with mock.patch.object(tts_kokoro, "DIR", self.dir), mock.patch.object(tts_kokoro, "FILES", files), \
             mock.patch.object(tts_kokoro.httpx, "AsyncClient", lambda **kw: real(transport=transporte, **kw)):
            asyncio.run(tts_kokoro.install())

    def test_suma_buena(self):
        cuerpo = b"modelo de prueba"
        self._bajar(cuerpo, {"m.onnx": ("http://127.0.0.1:9/m.onnx", 1, hashlib.sha256(cuerpo).hexdigest())})
        self.assertEqual(tts_kokoro.progress["status"], "lista")
        self.assertEqual((self.dir / "m.onnx").read_bytes(), cuerpo)

    def test_suma_mala_no_se_usa(self):
        self._bajar(b"otra cosa", {"m.onnx": ("http://127.0.0.1:9/m.onnx", 1, "0" * 64)})
        self.assertNotEqual(tts_kokoro.progress["status"], "lista")
        self.assertTrue(tts_kokoro.progress["error"])
        self.assertFalse((self.dir / "m.onnx").exists())
        self.assertFalse((self.dir / "m.onnx.part").exists())
