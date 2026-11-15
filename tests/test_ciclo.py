"""Arranque y cierre (lifecycle.py): qué marca la pantalla de carga, que se sepa si un proceso sigue vivo y que el
servidor se apague solo si la ventana muere. Sin servidores ni procesos reales del usuario."""
import asyncio
import os
import subprocess
import sys
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from companion import lifecycle, llm, stt, tts_light, voz_proc
from companion.config import settings


class Vivo(unittest.TestCase):
    def test_este_proceso_vive_y_uno_cerrado_no(self):
        self.assertTrue(lifecycle.pid_alive(os.getpid()))
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        self.assertFalse(lifecycle.pid_alive(p.pid))
        self.assertFalse(lifecycle.pid_alive(0))


class PantallaDeCarga(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.antes = (settings.voice_engine, settings.llm_provider)

    async def asyncTearDown(self):
        settings.voice_engine, settings.llm_provider = self.antes
        llm.warming.clear()

    async def test_oido_cargando_y_voz_completa_cargando(self):
        t = stt.Transcriber("large-v3-turbo", "auto", "int8", "es")
        settings.voice_engine, settings.llm_provider = "completa", "local"
        llm.warming.update(model="gemma4:e4b-it-qat", state="cargando")
        with mock.patch.object(voz_proc, "_health", return_value={}), mock.patch.object(voz_proc, "installed", return_value=True):
            r = await lifecycle.loading(t)
        estados = {i["id"]: i["state"] for i in r["items"]}
        self.assertEqual(estados, {"oido": "cargando", "voz": "cargando", "cerebro": "cargando"})
        self.assertTrue(r["busy"])

    async def test_todo_listo_y_fallos_no_bloquean(self):
        t = stt.Transcriber("large-v3-turbo", "auto", "int8", "es")
        t.set_engine("nube")
        settings.voice_engine, settings.llm_provider = "completa", "local"
        llm.warming.update(model="gemma4:e4b-it-qat", state="listo")
        with mock.patch.object(voz_proc, "_health", return_value={"tts": "none", "error": "RuntimeError: sin CUDA"}):
            r = await lifecycle.loading(t)
        estados = {i["id"]: i["state"] for i in r["items"]}
        self.assertEqual(estados, {"oido": "listo", "voz": "error", "cerebro": "listo"})
        self.assertFalse(r["busy"])

    async def test_voz_ligera_sin_descargar(self):
        t = stt.Transcriber("large-v3-turbo", "auto", "int8", "es")
        t.model, t.device = object(), "cuda"
        settings.voice_engine = "ligera"
        with mock.patch.object(tts_light, "installed", return_value=False):
            r = await lifecycle.loading(t)
        self.assertEqual(next(i for i in r["items"] if i["id"] == "voz")["state"], "error")


class DuenoDelServidor(unittest.IsolatedAsyncioTestCase):
    async def test_si_la_ventana_muere_se_apaga(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        apagado = asyncio.Event()

        async def shutdown(reason=""):
            apagado.set()
        with mock.patch.object(lifecycle, "shutdown", shutdown), mock.patch.object(lifecycle.asyncio, "sleep", _rapido):
            lifecycle.watch_owner(p.pid)
            await asyncio.sleep(0.05)
            self.assertFalse(apagado.is_set())
            p.kill()
            p.wait()
            await asyncio.wait_for(apagado.wait(), 5)

    async def test_otra_ventana_releva_a_la_anterior(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        apagado = asyncio.Event()

        async def shutdown(reason=""):
            apagado.set()
        try:
            with mock.patch.object(lifecycle, "shutdown", shutdown), mock.patch.object(lifecycle.asyncio, "sleep", _rapido):
                lifecycle.watch_owner(p.pid)
                lifecycle.watch_owner(os.getpid())          # la nueva dueña sigue viva
                p.kill()
                p.wait()
                await _real_sleep(0.3)
                self.assertFalse(apagado.is_set())
        finally:
            lifecycle._owner_task.cancel()


_real_sleep = asyncio.sleep


async def _rapido(s):
    await _real_sleep(min(s, 0.02))


if __name__ == "__main__":
    unittest.main()
