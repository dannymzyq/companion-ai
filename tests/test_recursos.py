"""Recomendaciones según la tarjeta, relevo de modelos (nube y local) y nombres de los personajes incluidos."""
import asyncio
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from companion import llm, models, profile, state
from companion.config import settings


def gpu(gb):
    return {"total": gb * 1024, "used": 0} if gb else None


class Recomendacion(unittest.TestCase):
    def test_por_tarjeta(self):
        casos = {0: "gemma3:1b-it-qat", 4: "gemma3:1b-it-qat", 8: "gemma4:e2b-it-qat",
                 12: "gemma4:e4b-it-qat", 16: "gemma4:e4b-it-qat", 24: "gemma4:e4b-it-qat"}
        for gb, esperado in casos.items():
            r = profile.resources(gpu(gb), is_cloud=False, local_model=profile.TOP_RECOMMENDED, node_ok=True)
            self.assertEqual(r["recommended_model"], esperado, f"{gb} GB")

    def test_12b_se_ofrece_pero_no_se_recomienda(self):
        ids = [m["id"] for m in profile.LOCAL_MODELS]
        self.assertIn("gemma4:12b", ids)
        self.assertEqual(profile.TOP_RECOMMENDED, "gemma4:e4b-it-qat")
        r = profile.resources(gpu(16), is_cloud=False, local_model="gemma4:12b", node_ok=True)
        self.assertGreaterEqual(r["room"]["completa"], 10.6 + 0.3)     # en 16 GB cabe junto a la voz completa
        self.assertEqual(r["recommended_engine"], "completa")

    def test_voz_completa_en_12_gb(self):
        r = profile.resources(gpu(12), is_cloud=False, local_model=profile.TOP_RECOMMENDED, node_ok=True)
        self.assertEqual(r["recommended_pair"], "completa")


class Relevo(unittest.TestCase):
    def setUp(self):
        self.antes = (settings.cloud_preset, settings.gemini_model, settings.ollama_model, list(settings.ollama_fallback))
        settings.cloud_preset, settings.gemini_model = "gemini", "gemini-3.6-flash"

    def tearDown(self):
        settings.cloud_preset, settings.gemini_model, settings.ollama_model, settings.ollama_fallback = self.antes

    def test_fondo_usa_primero_el_de_mas_cuota(self):
        normal, fondo = llm.gemini_models(), llm.gemini_models(background=True)
        self.assertEqual(normal[0], "gemini-3.6-flash")
        self.assertEqual(fondo[0], settings.background_model)
        self.assertEqual(sorted(normal), sorted(fondo))                # los mismos, en otro orden

    def test_local_baja_a_los_que_ven(self):
        settings.ollama_model = "gemma4:12b"
        self.assertEqual(llm.local_models(), ["gemma4:12b", "gemma4:e4b-it-qat", "gemma4:e2b-it-qat"])
        settings.ollama_model = "qwen3:1.7b"
        self.assertEqual(llm.local_models(), ["qwen3:1.7b", "gemma3:1b-it-qat"])

    def test_modelo_propio_baja_a_los_pequenos(self):
        state.save(local_model="mi-modelo:7b")
        try:
            profile.apply()
            self.assertEqual(settings.ollama_model, "mi-modelo:7b")
            self.assertNotIn("gemma4:12b", settings.ollama_fallback)
            self.assertIn("gemma4:e4b-it-qat", settings.ollama_fallback)
        finally:
            state.save(local_model=None)
            profile.apply()


class RespaldoDeLaNube(unittest.TestCase):
    """Con la nube elegida y la cuota agotada, el modelo local no debe quitarle la tarjeta a la voz completa."""

    def setUp(self):
        self.antes = (settings.llm_provider, settings.cloud_preset, settings.gemini_model, settings.gemini_api_key,
                      settings.ollama_model, dict(llm._blocked_until), llm._local_announced)
        settings.llm_provider, settings.cloud_preset, settings.gemini_model = "gemini", "gemini", "gemini-3.6-flash"
        settings.gemini_api_key, settings.ollama_model = "clave-de-prueba", "gemma4:e4b-it-qat"
        llm._local_announced = False
        self.llamadas = []

        async def sin_cuota(model, payload, sampling):
            raise llm.QuotaExceeded(3600, True)
            yield ""                                   # noqa: B901  (generador)

        async def local(messages, sampling, model=None, cpu=False):
            self.llamadas.append((model, cpu))
            yield "hola"

        async def ollama_json(path):
            return {"models": []}
        self.parches = [mock.patch.object(llm, "_gemini", sin_cuota), mock.patch.object(llm, "_ollama", local),
                        mock.patch.object(llm, "_ollama_json", ollama_json)]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()
        (settings.llm_provider, settings.cloud_preset, settings.gemini_model, settings.gemini_api_key,
         settings.ollama_model, blocked, llm._local_announced) = self.antes
        llm._blocked_until.clear()
        llm._blocked_until.update(blocked)
        llm.pop_notices()

    def charla(self, gpu_mb, background=False):
        async def run():
            return "".join([p async for p in llm.stream_chat([{"role": "user", "content": "hola"}],
                                                             {"temperature": 0.5, "top_p": 0.9, "max_tokens": 20},
                                                             background=background)])
        with mock.patch.object(llm, "gpu_memory", lambda: gpu_mb):
            return asyncio.run(run())

    def test_fondo_no_carga_el_modelo_local(self):
        with self.assertRaises(llm.LLMError):
            self.charla({"total": 6144, "used": 4600}, background=True)
        self.assertEqual(self.llamadas, [])

    def test_tarjeta_pequena_va_al_procesador(self):
        self.assertEqual(self.charla({"total": 6144, "used": 4600}), "hola")      # voz completa + oído cargados
        self.assertEqual(self.llamadas, [("gemma4:e4b-it-qat", True)])
        self.assertTrue(any("procesador" in n for n in llm.pop_notices()))

    def test_si_cabe_va_a_la_tarjeta(self):
        self.charla({"total": 16384, "used": 4600})
        self.assertEqual(self.llamadas, [("gemma4:e4b-it-qat", False)])


class Personajes(unittest.TestCase):
    def test_nombres_genericos(self):
        nombres = [b["name"] for b in models.BUILTIN]
        self.assertEqual(nombres, ["Avatar 1", "Avatar 2", "Avatar 3"])
        self.assertFalse(any(n.lower().startswith(("chic", "mika", "esfera")) for n in nombres))

    def test_lo_guardado_antes_se_traduce(self):
        settings.models_dir.mkdir(parents=True, exist_ok=True)
        for b in models.BUILTIN:                       # basta con que el archivo exista (no se lee)
            if b["file"]:
                (settings.models_dir / b["file"]).write_bytes(b"x")
        for viejo, nuevo in {"chica": "avatar1", "chico": "avatar2", "esfera": "avatar3", "default": "avatar1"}.items():
            with mock.patch.object(models, "_state", return_value={"model": viejo}):
                self.assertEqual(models.active_id(), nuevo, viejo)
        with mock.patch.object(models, "_state", return_value={"model": "mika"}):
            self.assertEqual(models.active_id(), "avatar1")        # el de Mika ya no existe: el de por defecto


if __name__ == "__main__":
    unittest.main()
