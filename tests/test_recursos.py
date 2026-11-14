"""Recomendaciones según la tarjeta, relevo de modelos (nube y local) y nombres de los personajes incluidos."""
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
