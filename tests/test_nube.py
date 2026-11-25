"""Oído y voz en la nube y el modo «solo nube»: relevo entre proveedores, vuelta a Whisper local si la nube falla,
el motor «nube» y que «solo nube» guarda y devuelve lo que había. Sin red: las peticiones están simuladas."""
import unittest
from unittest import mock

import httpx
import numpy as np

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from companion import profile, state, stt, stt_cloud, tts, tts_cloud, tts_light
from companion.config import settings


def respuesta(status: int, data: dict | None = None, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=data or {}, headers=headers or {}, request=httpx.Request("POST", "http://x"))


class OidoEnLaNube(unittest.TestCase):
    def setUp(self):
        stt_cloud._rest.clear()
        self.audio = np.zeros(16000, dtype=np.float32)
        state.save(ear={"engine": "nube", "groq_key": "gsk_prueba"})
        self.key, settings.gemini_api_key = settings.gemini_api_key, "clave-prueba"
        self.preset, settings.cloud_preset = settings.cloud_preset, "gemini"

    def tearDown(self):
        state.save(ear=None)
        settings.gemini_api_key, settings.cloud_preset = self.key, self.preset

    def test_groq_primero_y_filtra_silencio(self):
        segs = {"segments": [{"text": " Hola, Mika.", "no_speech_prob": 0.01, "avg_logprob": -0.2},
                             {"text": " Gracias por ver.", "no_speech_prob": 0.9, "avg_logprob": -1.5}]}
        with mock.patch.object(stt_cloud._client, "post", return_value=respuesta(200, segs)) as post:
            self.assertEqual(stt_cloud.transcribe(self.audio, "es", "pista"), "Hola, Mika.")
        self.assertIn("api.groq.com", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["data"]["prompt"], "pista")
        self.assertEqual(stt_cloud.last["provider"], "groq")

    def test_cuota_agotada_pasa_a_gemini_y_descansa(self):
        gemini = {"choices": [{"message": {"content": "¿Qué hora es?"}}]}
        calls = []

        def post(url, **kw):
            calls.append(url)
            return respuesta(429, headers={"retry-after": "120"}) if "groq" in url else respuesta(200, gemini)
        with mock.patch.object(stt_cloud._client, "post", side_effect=post):
            self.assertEqual(stt_cloud.transcribe(self.audio), "¿Qué hora es?")
            self.assertEqual(stt_cloud.transcribe(self.audio), "¿Qué hora es?")
        self.assertEqual(sum("groq" in u for u in calls), 1)          # la segunda vez ya no se intenta Groq
        self.assertTrue(stt_cloud._resting("groq"))

    def test_gemini_silencio_es_vacio(self):
        state.save(ear={"engine": "nube"})                           # sin clave de Groq
        with mock.patch.object(stt_cloud._client, "post",
                               return_value=respuesta(200, {"choices": [{"message": {"content": "(silencio)"}}]})):
            self.assertEqual(stt_cloud.transcribe(self.audio), "")

    def test_sin_proveedores_falla(self):
        state.save(ear={"engine": "nube"})
        settings.gemini_api_key = ""
        with self.assertRaises(stt_cloud.CloudEarError):
            stt_cloud.transcribe(self.audio)

    def test_si_la_nube_falla_transcribe_en_local(self):
        t = stt.Transcriber("large-v3-turbo", "auto", "int8", "es")
        t.set_engine("nube")
        self.assertTrue(t.ready)
        self.assertEqual(t.device, "nube")
        seg = mock.Mock(text=" Pon música.", no_speech_prob=0.0, avg_logprob=-0.1)
        local = mock.Mock()
        local.transcribe.return_value = ([seg], None)
        with mock.patch.object(stt_cloud, "transcribe", side_effect=stt_cloud.CloudEarError("sin red")), \
                mock.patch.object(t, "local_model", return_value=local):
            self.assertEqual(t.transcribe(np.zeros(16000 * 3, dtype=np.float32)), "Pon música.")
        self.assertEqual(t.transcribe_media(np.zeros(16000, dtype=np.float32)), "")   # la pantalla, no en la nube

    def test_volver_a_local_pide_cargar(self):
        t = stt.Transcriber("large-v3-turbo", "auto", "int8", "es")
        t.model = object()
        t.set_engine("nube")
        self.assertIsNone(t.model)
        self.assertFalse(stt.on_gpu)
        self.assertTrue(t.set_engine("local"))
        self.assertFalse(t.ready)


class VozEnLaNube(unittest.IsolatedAsyncioTestCase):
    async def test_motor_nube(self):
        state.save(voice_engine="nube")
        try:
            with mock.patch.object(tts_cloud, "installed", return_value=True):
                self.assertEqual(profile.engine_now(), ("nube", ""))
            with mock.patch.object(tts_cloud, "installed", return_value=False):
                self.assertEqual(profile.engine_now()[0], "ligera")
        finally:
            state.save(voice_engine=None)

    async def test_voz_de_cada_personaje(self):
        self.assertEqual(tts_cloud.spec_for("mika_es")["voice"], "es-MX-DaliaNeural")
        self.assertTrue(all(v.endswith("Neural") for v in (s["voice"] for s in tts_cloud.specs().values())))
        self.assertEqual(len(tts_cloud.specs()), 9)

    async def test_sin_internet_suena_la_ligera(self):
        async def falla(text, voice, speed=1.0):
            raise tts.TTSError("La voz en la nube no respondió (ClientConnectorError)")
            yield b""                                   # noqa: unreachable (es un generador)

        async def ligera(text, voice, speed=1.0):
            yield b"\x03\x00" * 3
        with mock.patch.object(tts_cloud, "stream_speech", falla), mock.patch.object(tts_light, "installed", return_value=True), \
                mock.patch.object(tts_light, "stream_speech", ligera):
            pcm = b"".join([c async for c in tts.stream_speech("Hola, ¿qué tal?", "mika_es", engine="nube")])
        self.assertEqual(pcm, b"\x03\x00" * 3)

    async def test_texto_sin_reescribir(self):
        seen = []

        async def nube(text, voice, speed=1.0):
            seen.append(text)
            yield b"\x00\x00"
        with mock.patch.object(tts_cloud, "stream_speech", nube):
            _ = [c async for c in tts.stream_speech("¿Qué tal con Apple Music?", "mika_es", engine="nube")]
        self.assertEqual(seen, ["¿Qué tal con Apple Music?"])      # sin «ké» ni pronunciación a la española


class SoloNube(unittest.TestCase):
    def setUp(self):
        from companion import server
        self.server = server
        state.save(provider="local", voice_engine="ligera", ear={"engine": "local"},
                   cloud={"preset": "gemini", "base": profile.PRESETS["gemini"]["base"], "model": "", "key": "clave-prueba"})

    def tearDown(self):
        state.save(provider=None, voice_engine=None, ear=None, cloud=None, cloud_only=None, before_cloud_only=None)
        profile.apply()

    def test_encender_y_apagar_devuelve_lo_de_antes(self):
        with mock.patch.object(tts_cloud, "installed", return_value=True):
            on = self.server._cloud_only_changes(True, {})
            self.assertEqual((on["provider"], on["ear"]["engine"], on["voice_engine"]), ("gemini", "nube", "nube"))
            state.save(**on)
            profile.apply()
            self.assertTrue(profile.cloud_only())
            self.assertFalse(settings.local_fallback)                  # tampoco el respaldo local del cerebro
            off = self.server._cloud_only_changes(False, {})
        self.assertEqual((off["provider"], off["ear"]["engine"], off["voice_engine"]), ("local", "local", "ligera"))

    def test_sin_clave_no_se_enciende(self):
        state.save(cloud=None)
        with mock.patch.object(profile, "_ENV_KEY", ""), self.assertRaises(ValueError):
            self.server._cloud_only_changes(True, {})

    def test_elegir_algo_local_lo_apaga(self):
        with mock.patch.object(tts_cloud, "installed", return_value=True):
            state.save(**self.server._cloud_only_changes(True, {}))
            state.save(provider="local")
            profile.apply()
        self.assertFalse(profile.cloud_only())


class OidoSaturado(unittest.TestCase):
    """18 nov 2026: un 503 o un proveedor que no contesta descansa 5 min y se prueba el siguiente."""

    def setUp(self):
        stt_cloud._rest.clear()

    def tearDown(self):
        stt_cloud._rest.clear()

    def test_503_pasa_al_siguiente_y_descansa(self):
        calls = []

        def post(url, **kw):
            calls.append(url)
            if "groq" in url:
                return httpx.Response(503, request=httpx.Request("POST", url))
            return httpx.Response(200, request=httpx.Request("POST", url),
                                  json={"choices": [{"message": {"content": "hola"}}]})
        with mock.patch.object(stt_cloud, "groq_key", lambda: "g"), mock.patch.object(stt_cloud, "gemini_key", lambda: "k"), \
                mock.patch.object(stt_cloud._client, "post", post):
            self.assertEqual(stt_cloud.transcribe(np.zeros(16000, dtype=np.float32)), "hola")
        self.assertTrue(stt_cloud._resting("groq"))

    def test_sin_respuesta_descansa(self):
        def post(url, **kw):
            if "groq" in url:
                raise httpx.ReadTimeout("lento")
            return httpx.Response(200, request=httpx.Request("POST", url),
                                  json={"choices": [{"message": {"content": "hola"}}]})
        with mock.patch.object(stt_cloud, "groq_key", lambda: "g"), mock.patch.object(stt_cloud, "gemini_key", lambda: "k"), \
                mock.patch.object(stt_cloud._client, "post", post):
            self.assertEqual(stt_cloud.transcribe(np.zeros(16000, dtype=np.float32)), "hola")
        self.assertTrue(stt_cloud._resting("groq"))


if __name__ == "__main__":
    unittest.main()
