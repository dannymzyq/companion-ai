"""Recomendaciones según la tarjeta, relevo de modelos (nube y local) y nombres de los personajes incluidos."""
import asyncio
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from companion import llm, models, profile, state
from companion import config
from companion.config import settings

# Estas pruebas son del catálogo de PC (tarjeta NVIDIA). En un Mac con Apple Silicon el catálogo es el de MLX
# (tests/test_mac_mlx.py): aquí se fija el de PC para que pasen igual en las dos máquinas.
_parches = [mock.patch.object(config, "MAC", False), mock.patch.object(profile, "MAC", False),
            mock.patch.object(profile, "LOCAL_MODELS", profile.PC_MODELS),
            mock.patch.object(profile, "TOP_RECOMMENDED", next(m["id"] for m in profile.PC_MODELS if m.get("recommend", True)))]


def setUpModule():
    for p in _parches:
        p.start()


def tearDownModule():
    for p in _parches:
        p.stop()


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


class CambioDeVoz(unittest.TestCase):
    """Con las dos voces instaladas suena la completa y, si no cabe junto al modelo local, pasa sola a la ligera."""

    def setUp(self):
        from companion import tts_light, voz_proc
        self.antes = (settings.llm_provider, settings.ollama_model, settings.voice_engine, settings.voice_reason,
                      profile._gpu_total, profile._squeezed)
        self.parches = [mock.patch.object(tts_light, "installed", return_value=True),
                        mock.patch.object(voz_proc, "installed", return_value=True),
                        # sin medir la tarjeta de verdad (la de esta PC): lo de los demás programas lo pone cada prueba
                        mock.patch.object(profile, "measured_others", side_effect=lambda: self.otros)]
        self.otros = None                 # None: la estimación fija (DESKTOP_GB)
        for p in self.parches:
            p.start()
        state.save(voice_engine="completa", voice_auto=None)
        profile.squeeze(False)

    def tearDown(self):
        for p in self.parches:
            p.stop()
        state.save(voice_engine=None, voice_auto=None, provider=None, local_model=None)
        profile.apply()
        (settings.llm_provider, settings.ollama_model, settings.voice_engine, settings.voice_reason,
         profile._gpu_total, profile._squeezed) = self.antes

    def motor(self, gb, provider, model="gemma4:e4b-it-qat"):
        profile._gpu_total = float(gb)
        settings.llm_provider, settings.ollama_model = provider, model
        return profile.engine_now()

    def test_nube_en_6_gb_usa_la_completa(self):
        self.assertEqual(self.motor(6, "gemini"), ("completa", ""))

    def test_local_en_6_gb_pasa_a_la_ligera(self):
        motor, motivo = self.motor(6, "local")
        self.assertEqual(motor, "ligera")
        self.assertIn("gemma4:e4b-it-qat", motivo)

    def test_16_gb_con_12b_sigue_con_la_completa(self):
        self.assertEqual(self.motor(16, "local", "gemma4:12b")[0], "completa")

    def test_sin_cambio_automatico_se_respeta_la_eleccion(self):
        state.save(voice_auto=False)
        self.assertEqual(self.motor(6, "local"), ("completa", ""))

    def test_sin_voz_ligera_no_cambia(self):
        from companion import tts_light
        with mock.patch.object(tts_light, "installed", return_value=False):
            self.assertEqual(self.motor(6, "local")[0], "completa")

    def test_elegida_la_ligera_no_se_toca(self):
        state.save(voice_engine="ligera")
        self.assertEqual(self.motor(16, "gemini"), ("ligera", ""))

    def test_laptop_de_4_gb_con_la_nube_usa_la_completa(self):
        # RTX 3050 de 4 GB con el escritorio en la gráfica integrada: los demás programas ocupan poco (medido)
        self.otros = 0.4
        self.assertEqual(self.motor(4, "gemini"), ("completa", ""))

    def test_laptop_de_4_gb_con_un_juego_pasa_a_la_ligera(self):
        # Con el oído pequeño (0,55 GB, 18 nov 2026) caben la voz completa y 2 GB de otros: hace falta un juego mayor.
        self.otros = 2.5
        self.assertEqual(self.motor(4, "gemini")[0], "ligera")

    def test_lo_nuestro_no_cuenta_como_de_otros(self):
        from companion import stt, voz_proc
        self.parches[-1].stop()
        try:
            with mock.patch.object(llm, "gpu_memory", return_value={"used": 2048, "total": 4096}),                     mock.patch.object(stt, "on_gpu", True), mock.patch.object(stt, "loaded_name", "large-v3-turbo"), mock.patch.object(voz_proc, "running", return_value=False),                     mock.patch.object(profile, "_ollama_on_gpu", return_value=0.0):
                self.assertEqual(profile.measured_others(), round(2.0 - profile.EAR_GB, 1))
        finally:
            self.parches[-1].start()

    def test_sin_memoria_pasa_a_la_ligera_y_vuelve_con_la_nube(self):
        profile._gpu_total = 16.0
        state.save(provider="local", local_model="gemma4:12b")
        profile.apply()
        self.assertEqual(settings.voice_engine, "completa")
        from companion import voz_proc
        llm._notices.clear()
        with mock.patch.object(voz_proc, "stop") as parar, mock.patch.object(llm, "_swap", new=mock.AsyncMock()) as recargar:
            hecho = asyncio.run(llm._free_voice("gemma4:12b"))
            self.assertTrue(hecho)
            parar.assert_called_once()
            recargar.assert_awaited_once_with("gemma4:12b", "gemma4:12b")
        self.assertEqual(settings.voice_engine, "ligera")
        self.assertTrue(any("voz ligera" in n for n in llm.pop_notices()))
        self.assertFalse(asyncio.run(llm._free_voice("gemma4:12b")))     # la segunda vez, ya baja de modelo
        state.save(provider="gemini")
        profile.apply()
        self.assertEqual(settings.voice_engine, "completa")


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


class OidoSegunLaTarjeta(unittest.TestCase):
    """18 nov 2026: en tarjetas de 4-6 GB el turbo (1,3 GB) y la voz completa (1,1 GB) no cabían juntos."""

    def _model(self, total, small=True, env=None):
        import os
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            if small:
                (Path(d) / "models" / "whisper" / "small").mkdir(parents=True)
                (Path(d) / "models" / "whisper" / "small" / "model.bin").write_bytes(b"x")
            with mock.patch.object(profile, "ROOT", Path(d)), mock.patch.dict(os.environ, {"STT_MODEL": env} if env else {}, clear=False):
                if not env:
                    os.environ.pop("STT_MODEL", None)
                return profile.ear_model(total)

    def test_tarjeta_pequena_usa_el_pequeno(self):
        self.assertEqual(self._model(4.0), "small")
        self.assertEqual(self._model(6.0), "small")

    def test_tarjeta_grande_o_sin_tarjeta_usa_el_turbo(self):
        self.assertEqual(self._model(8.0), "large-v3-turbo")
        self.assertEqual(self._model(0.0), "large-v3-turbo")      # sin NVIDIA: el procesador elige por su cuenta

    def test_sin_el_pequeno_instalado_sigue_el_turbo(self):
        self.assertEqual(self._model(4.0, small=False), "large-v3-turbo")

    def test_stt_model_manda(self):
        with mock.patch.object(settings, "stt_model", "base"):
            self.assertEqual(self._model(4.0, env="base"), "base")

    def test_en_4_gb_caben_oido_y_voz_completa(self):
        with mock.patch.object(profile, "ear_model", lambda total=None: "small"):
            r = profile.resources(gpu(4), is_cloud=True, local_model=profile.TOP_RECOMMENDED, node_ok=True, others=1.5)
        self.assertEqual(r["ear_model"], "small")
        self.assertEqual(r["recommended_engine"], "completa")


class OidoConElEnvDeAntes(unittest.TestCase):
    def test_el_turbo_del_env_de_siempre_cuenta_como_automatico(self):
        """Hasta la 0.8.3 .env.example traía STT_MODEL=large-v3-turbo: en la laptop de 4 GB seguía cargando el turbo."""
        import os
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "models" / "whisper" / "small").mkdir(parents=True)
            (Path(d) / "models" / "whisper" / "small" / "model.bin").write_bytes(b"x")
            with mock.patch.object(profile, "ROOT", Path(d)):
                for value in ("large-v3-turbo", "auto", ""):
                    with mock.patch.dict(os.environ, {"STT_MODEL": value}):
                        self.assertEqual(profile.ear_model(4.0), "small", value)


class VozRapida(unittest.TestCase):
    """18 nov 2026: en una tarjeta lenta la voz va en modo rápido y no se comprueba con Whisper (cada repetición
    costaba otros 3-5 s en una RTX 3050 de laptop)."""

    def setUp(self):
        from companion import voz_proc
        self.vp = voz_proc
        voz_proc._fast, voz_proc._fast_asked = None, 0.0

    def tearDown(self):
        self.vp._fast, self.vp._fast_asked = None, 0.0

    def _health(self, h):
        import httpx
        return mock.patch.object(self.vp.httpx, "get", return_value=httpx.Response(200, json=h, request=httpx.Request("GET", "http://x")))

    def test_lee_el_modo_cuando_ya_midio(self):
        with self._health({"tts": "f5", "fast": True, "phrase_s": 5.4}):
            self.assertTrue(self.vp.fast())

    def test_mientras_carga_no_decide_y_no_pregunta_en_cada_frase(self):
        with self._health({"tts": "none", "loading": True}) as get:
            self.assertFalse(self.vp.fast())
            self.assertFalse(self.vp.fast())
        self.assertEqual(get.call_count, 1)
        self.assertIsNone(self.vp._fast)


if __name__ == "__main__":
    unittest.main()
