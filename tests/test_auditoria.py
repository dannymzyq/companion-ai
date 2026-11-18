"""Correcciones de la auditoría del 16 nov 2026: claves cifradas, ajustes que no se pierden, hora del sistema,
relevo de la nube cuando un modelo va lento, aviso de versión nueva, registros sin texto y lentitud en el Mac."""
import asyncio
import json
import sys
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from companion import config, llm, secret, state, update
from companion.prompt import local_time


class Claves(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "DPAPI solo existe en Windows")
    def test_settings_json_no_guarda_la_clave_en_claro(self):
        state.save(cloud={"preset": "gemini", "base": "x", "model": "", "key": "AIza-prueba-123"},
                   ear={"engine": "nube", "groq_key": "gsk_prueba_456"})
        raw = state.STATE_FILE.read_text(encoding="utf-8")
        self.assertNotIn("AIza-prueba-123", raw)
        self.assertNotIn("gsk_prueba_456", raw)
        self.assertIn("dpapi:", raw)
        secret._cache.clear()                       # que de verdad descifre, no que lo recuerde
        self.assertEqual(state.load()["cloud"]["key"], "AIza-prueba-123")
        self.assertEqual(state.load()["ear"]["groq_key"], "gsk_prueba_456")

    def test_clave_de_otra_pc_cuenta_como_vacia(self):
        self.assertEqual(secret.unprotect("dpapi:" + "QUFBQQ=="), "")

    def test_las_claves_de_antes_se_cifran_al_arrancar(self):
        state.STATE_FILE.write_text(json.dumps({"cloud": {"key": "AIza-vieja"}, "onboarded": True}), encoding="utf-8")
        state.protect_keys()
        if sys.platform == "win32":
            self.assertNotIn("AIza-vieja", state.STATE_FILE.read_text(encoding="utf-8"))
            self.assertFalse(state.BACKUP_FILE.exists())
        self.assertEqual(state.load()["cloud"]["key"], "AIza-vieja")


class AjustesSeguros(unittest.TestCase):
    def test_un_archivo_roto_no_borra_lo_guardado(self):
        state.save(onboarded=True, provider="local")
        state.save(provider="gemini")               # deja la copia del anterior
        state.STATE_FILE.write_text('{"onboarded": tr', encoding="utf-8")   # cortado a mitad (apagón)
        got = state.load()
        self.assertTrue(got.get("onboarded"))
        state.save(onboarded=True)                  # al guardar de nuevo queda entero
        json.loads(state.STATE_FILE.read_text(encoding="utf-8"))

    def test_no_queda_el_temporal(self):
        state.save(x=1)
        self.assertFalse(state.STATE_FILE.with_suffix(".json.tmp").exists())


class Hora(unittest.TestCase):
    def test_sin_zona_usa_la_del_sistema(self):
        self.assertTrue(local_time(""))
        with mock.patch.dict("os.environ", {"TIMEZONE": "America/Lima"}):
            self.assertEqual(config.Settings().timezone, "")          # la que copiaba el instalador de antes
        with mock.patch.dict("os.environ", {"TIMEZONE": "Europe/Madrid"}):
            self.assertEqual(config.Settings().timezone, "Europe/Madrid")


class NubeLenta(unittest.TestCase):
    def setUp(self):
        llm._slow_cloud.clear()
        llm._slow_until.clear()
        llm._notices.clear()

    def test_dos_turnos_lentos_empiezan_por_el_siguiente(self):
        chain = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
        llm._note_wait(chain[0], 20.0, chain)
        self.assertEqual(llm._by_speed(chain)[0], chain[0])          # uno suelto no basta
        llm._note_wait(chain[0], 25.0, chain)
        self.assertEqual(llm._by_speed(chain), [chain[1], chain[0]])  # el lento sigue al final, por si acaso
        self.assertTrue(any("media hora" in n for n in llm.pop_notices()))

    def test_uno_rapido_reinicia_la_cuenta(self):
        chain = ["a", "b"]
        llm._note_wait("a", 20.0, chain)
        llm._note_wait("a", 2.0, chain)
        llm._note_wait("a", 20.0, chain)
        self.assertEqual(llm._by_speed(chain)[0], "a")

    def test_sin_otro_modelo_no_cambia(self):
        llm._note_wait("a", 20.0, ["a"])
        llm._note_wait("a", 20.0, ["a"])
        self.assertEqual(llm._slow_until, {})


class NubeSaturada(unittest.IsolatedAsyncioTestCase):
    """18 nov 2026: gemini-3.6-flash tardaba 8-49 s en devolver su 503 mientras Flash-Lite contestaba en 1 s."""

    def setUp(self):
        llm.reset_cloud()
        llm._notices.clear()
        self.p = [mock.patch.object(llm.settings, "llm_provider", "gemini"),
                  mock.patch.object(llm.settings, "cloud_preset", "gemini"),
                  mock.patch.object(llm.settings, "gemini_api_key", "x"),
                  mock.patch.object(llm.settings, "gemini_model", "a"),
                  mock.patch.object(llm.settings, "gemini_fallback", ["b"]),
                  mock.patch.object(llm.settings, "local_fallback", False),
                  mock.patch.object(llm, "CLOUD_FIRST_S", 0.2)]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()
        llm.reset_cloud()

    async def _talk(self, behaviour):
        calls = []

        async def fake(model, payload, sampling):
            calls.append(model)
            async for piece in behaviour(model):
                yield piece
        with mock.patch.object(llm, "_gemini", fake):
            out = "".join([p async for p in llm._cloud([{"role": "user", "content": "hola"}], {}, None)])
        return out, calls

    async def test_503_pasa_al_siguiente_y_lo_deja_al_final(self):
        async def b(model):
            if model == "a":
                raise llm.Overloaded("HTTP 503")
            yield "hola desde b"
        out, calls = await self._talk(b)
        self.assertEqual((out, calls), ("hola desde b", ["a", "b"]))
        self.assertEqual(llm._by_speed(["a", "b"]), ["b", "a"])      # el saturado, al final unos minutos

    async def test_sin_primer_texto_a_tiempo_salta(self):
        async def b(model):
            if model == "a":
                await asyncio.sleep(5)
            yield f"de {model}"
        out, calls = await self._talk(b)
        self.assertEqual((out, calls), ("de b", ["a", "b"]))

    async def test_el_ultimo_no_tiene_limite(self):
        async def b(model):
            if model == "a":
                raise llm.Overloaded("HTTP 503")
            await asyncio.sleep(0.4)                                  # más que CLOUD_FIRST_S, pero es el último
            yield "tarde pero llega"
        out, _ = await self._talk(b)
        self.assertEqual(out, "tarde pero llega")

    async def test_todos_saturados_da_un_error_claro(self):
        async def b(model):
            raise llm.Overloaded("HTTP 503")
            yield ""
        with self.assertRaises(llm.LLMError) as e:
            await self._talk(b)
        self.assertIn("saturados", str(e.exception))

    async def test_la_mirada_calla_si_esta_saturado(self):
        async def fake(model, payload, sampling):
            raise llm.Overloaded("HTTP 503")
            yield ""
        with mock.patch.object(llm, "_gemini", fake), mock.patch.object(llm.settings, "watch_model", "a"):
            self.assertEqual(await llm.observe([{"role": "user", "content": "x"}], {}, []), "[silencio]")


class LentoEnElMac(unittest.TestCase):
    def test_pc_umbral_fijo(self):
        with mock.patch.object(llm.sys, "platform", "win32"):
            self.assertEqual(llm.slow_limit("m", 20), llm.SLOW_TPS)

    def test_mac_relativo_a_lo_mejor_visto(self):
        llm._best_tps.clear()
        with mock.patch.object(llm.sys, "platform", "darwin"):
            self.assertFalse(20 < llm.slow_limit("12b", 20))          # un M1 a 20 tokens/s: normal
            self.assertFalse(18 < llm.slow_limit("12b", 18))
            self.assertTrue(6 < llm.slow_limit("12b", 6))             # cae a menos de la mitad: lento


class VersionNueva(unittest.TestCase):
    def _rel(self, tag, assets, pre=False):
        return {"tag_name": tag, "prerelease": pre, "draft": False, "assets": [{"name": a} for a in assets],
                "html_url": f"https://github.com/{update.REPO}/releases/tag/{tag}"}

    def test_elige_la_mas_alta_de_este_sistema(self):
        rels = [self._rel("v0.6.2", ["Companion-Setup-0.6.2.exe", "Companion-0.6.2-mac.dmg"]),
                self._rel("v0.10.0", ["Companion-Setup-0.10.0.exe"]),                 # solo Windows
                self._rel("ios-v0.1.0", []), self._rel("v0.11.0", ["Companion-Setup-0.11.0.exe"], pre=True)]
        with mock.patch.object(update, "MAC", False), mock.patch.object(update.sys, "platform", "win32"):
            self.assertEqual(update.pick(rels)["version"], "0.10.0")
        with mock.patch.object(update, "MAC", True):
            self.assertEqual(update.pick(rels)["version"], "0.6.2")

    def test_apagado_no_sale_a_internet(self):
        with mock.patch.object(update.httpx, "AsyncClient", side_effect=AssertionError("salió a internet")):
            out = asyncio.run(update.check())
        self.assertFalse(out["newer"])


class Registros(unittest.TestCase):
    def test_sin_log_text_no_se_escribe_lo_que_dices(self):
        with mock.patch.object(config.settings, "log_text", False):
            self.assertEqual(config.shown("me llamo Ana y vivo en Lima"), "<27 caracteres>")
        with mock.patch.object(config.settings, "log_text", True):
            self.assertIn("Lima", config.shown("me llamo Ana y vivo en Lima"))


class Memoria(unittest.TestCase):
    def test_borrar_todo_compacta_la_base(self):
        from companion import store
        store.add_message("user", "un secreto muy largo " * 200)
        store.forget_all()
        raw = (config.settings.data_dir / "companion.db").read_bytes()
        self.assertNotIn(b"un secreto muy largo", raw)


if __name__ == "__main__":
    unittest.main()
