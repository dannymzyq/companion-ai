"""Mac con Apple Silicon: catálogo de modelos MLX y traducción de los nombres de PC (15 nov 2026)."""
import unittest
from unittest import mock

from companion import config, profile


class TestMacMLX(unittest.TestCase):
    def test_traduce_solo_en_el_mac(self):
        with mock.patch.object(config, "MAC", True):
            self.assertEqual(config.for_this_pc("gemma4:e4b-it-qat"), "gemma4:e4b-mlx")
            self.assertEqual(config.for_this_pc("gemma4:12b"), "gemma4:12b-mlx")
            self.assertEqual(config.for_this_pc("qwen3:1.7b"), "qwen3:1.7b")        # sin versión MLX
            self.assertEqual(config.for_this_pc("mio:latest"), "mio:latest")
        with mock.patch.object(config, "MAC", False):
            self.assertEqual(config.for_this_pc("gemma4:e4b-it-qat"), "gemma4:e4b-it-qat")

    def test_catalogo_del_mac(self):
        ids = [m["id"] for m in profile.MAC_MODELS]
        for mlx in set(config.MLX_EQUIV.values()):
            self.assertIn(mlx, ids)
        # de más a menos capaz (el respaldo si va lento sigue ese orden): primero el 12B, al final los de PC
        self.assertEqual(ids[:3], ["gemma4:12b-mlx", "gemma4:e4b-mlx", "gemma4:e2b-mlx"])
        # los recomendados en el Mac son los MLX (los pequeños de PC solo si no cabe ninguno)
        recomendados = [m["id"] for m in profile.MAC_MODELS if m.get("recommend", True)]
        self.assertTrue(recomendados[0].endswith("-mlx"))
        self.assertEqual(len({m["id"] for m in profile.MAC_MODELS}), len(ids))

    def test_recomienda_mlx_con_24_gb(self):
        with mock.patch.object(profile, "LOCAL_MODELS", profile.MAC_MODELS):
            gpu = {"total": int(24 * 1024 * 0.67), "used": 4000}
            r = profile.resources(gpu, is_cloud=False, local_model=profile.MAC_MODELS[0]["id"], node_ok=True, others=3.0)
            self.assertTrue(r["recommended_model"].endswith("-mlx"), r["recommended_model"])

    def test_guardado_de_pc_pasa_a_mlx(self):
        guardado = {"local_model": "gemma4:e4b-it-qat", "provider": "local"}
        guardados = []
        with mock.patch.object(config, "MAC", True), \
             mock.patch.object(profile, "for_this_pc", config.for_this_pc), \
             mock.patch.object(profile, "LOCAL_MODELS", profile.MAC_MODELS), \
             mock.patch.object(profile.state, "load", return_value=guardado), \
             mock.patch.object(profile.state, "save", side_effect=lambda **c: guardados.append(c) or {**guardado, **c}):
            antes = dict(vars(config.settings))      # apply() toca más ajustes: se dejan como estaban
            try:
                profile.apply()
                self.assertEqual(config.settings.ollama_model, "gemma4:e4b-mlx")
                self.assertIn({"local_model": "gemma4:e4b-mlx"}, guardados)
                self.assertIn("gemma4:e2b-mlx", config.settings.ollama_fallback)
            finally:
                vars(config.settings).update(antes)


if __name__ == "__main__":
    unittest.main()
