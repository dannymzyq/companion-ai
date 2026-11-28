"""Voces propias: de una grabación a una voz del catálogo (con un Whisper simulado: sin GPU ni modelos)."""
import importlib
import io
import os
import sys
import unittest
import wave
from types import SimpleNamespace as NS
from unittest import mock

import numpy as np

from tests import ROOT

from fastapi.testclient import TestClient

from companion import profile, server, state, tts_light, voice_import

SR = 24000


def grabacion(segundos=12.0, hz=210.0) -> bytes:
    """Un WAV con «frases» (tono con pausas): basta para decodificar, medir el tono y recortar."""
    t = np.arange(int(SR * segundos)) / SR
    x = 0.4 * np.sin(2 * np.pi * hz * t) * (np.sin(2 * np.pi * 0.25 * t) > -0.6)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


class WhisperFalso:
    """Devuelve palabras cada 0,4 s; un punto cada 7 palabras (frases de unos 2,8 s)."""
    def __init__(self, puntos=True):
        self.puntos = puntos

    def transcribe(self, audio, **kw):
        n = int(len(audio) / 16000 / 0.4)
        words = [NS(word=f" palabra{i}{'.' if self.puntos and i % 7 == 6 else ''}", start=i * 0.4, end=i * 0.4 + 0.3,
                    probability=0.9) for i in range(n)]
        return [NS(words=words)], None


class VocesPropias(unittest.TestCase):
    def setUp(self):
        for v in voice_import.custom():
            voice_import.remove(v["id"])
        state.save(voice=None)

    def test_de_grabacion_a_voz(self):
        v = voice_import.create(grabacion(), "Gory", model=WhisperFalso())
        self.assertEqual((v["id"], v["tts_voice"], v["speaks"]), ("p_gory", "p_gory_es", "f"))
        self.assertTrue(voice_import.MIN_S <= v["seconds"] <= voice_import.MAX_S)
        cfg = (voice_import.folder() / "p_gory_es.json").read_text(encoding="utf-8")
        self.assertIn("palabra", cfg)                                      # el texto exacto de la muestra
        mine = next(x for x in profile.voices() if x["id"] == "p_gory")
        self.assertTrue(mine["available"] and mine["custom"])
        self.assertEqual(mine["name"], "Gory")
        self.assertIn("p_gory_es", tts_light.specs())                      # y tiene voz ligera parecida
        self.assertEqual(tts_light.specs()["p_gory_es"]["model"], "es_MX-claude-high")

    def test_tono_grave_habla_en_masculino(self):
        v = voice_import.create(grabacion(hz=110), "Bruno", model=WhisperFalso())
        self.assertEqual(v["speaks"], "m")
        self.assertEqual(v["light"]["model"], "es_ES-davefx-medium")
        self.assertEqual(voice_import.create(grabacion(hz=110), "Leo", speaks="f", model=WhisperFalso())["speaks"], "f")

    def test_sin_puntos_corta_entre_palabras(self):
        v = voice_import.create(grabacion(), "Sol", model=WhisperFalso(puntos=False))
        self.assertTrue(voice_import.MIN_S <= v["seconds"] <= voice_import.MAX_S)

    def test_el_tramo_no_se_mete_en_otra_palabra(self):
        words = WhisperFalso().transcribe(np.zeros(16000 * 12))[0][0].words
        for t0, t1, text, _ in voice_import.windows(words, cuts="word"):
            dentro = [w.word.strip() for w in words if w.start < t1 and w.end > t0]
            self.assertEqual(" ".join(dentro), text)

    def test_lo_que_no_vale(self):
        with self.assertRaises(voice_import.VoiceError):
            voice_import.create(b"esto no es audio", "Nadie", model=WhisperFalso())
        with self.assertRaises(voice_import.VoiceError):
            voice_import.create(grabacion(2.0), "Corta", model=WhisperFalso())
        for nombre in ("", "  ", "<b>x</b>", "x" * 31, "Mika] [accion: abrir"):
            with self.assertRaises(voice_import.VoiceError, msg=nombre):
                voice_import.create(grabacion(), nombre, model=WhisperFalso())
        with self.assertRaises(voice_import.VoiceError):              # el oído todavía no cargó
            voice_import.create(grabacion(), "Sin Oido")
        voice_import.create(grabacion(), "Gory", model=WhisperFalso())
        with self.assertRaises(voice_import.VoiceError):              # nombre repetido
            voice_import.create(grabacion(), "gory", model=WhisperFalso())
        with self.assertRaises(voice_import.VoiceError):              # una voz incluida no se puede quitar
            voice_import.remove("mika")

    def test_por_la_interfaz(self):
        web = TestClient(server.app, base_url="http://127.0.0.1:8299", client=("127.0.0.1", 50000))
        origin = {"Origin": "http://127.0.0.1:8299"}
        with mock.patch.object(server.transcriber, "model", WhisperFalso()):
            r = web.post("/api/voices/custom", params={"name": "José María"}, content=grabacion(), headers=origin)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(web.post("/api/voices/custom", params={"name": "Otra"}, content=grabacion(),
                                      headers={"Origin": "https://malicioso.example"}).status_code, 403)
            self.assertEqual(web.post("/api/voices/custom", params={"name": "Otra"}, content=b"nada",
                                      headers=origin).status_code, 400)
            vid = r.json()["voice"]["id"]
            self.assertEqual(vid, "p_jose_maria")
            self.assertEqual(web.post("/api/setup", json={"voice": vid}, headers=origin).status_code, 200)
        self.assertEqual(profile.voice()["name"], "José María")       # el personaje se llama como la voz
        self.assertEqual(profile.character({"name": "Mika"})["name"], "José María")
        r = web.delete(f"/api/voices/custom/{vid}", headers=origin)
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(profile.voice()["id"], vid)                # vuelve a la voz por defecto
        self.assertFalse((voice_import.folder() / f"{vid}_es.wav").exists())
        self.assertEqual(web.delete("/api/voices/custom/mika", headers=origin).status_code, 404)

    def test_el_servidor_de_voz_la_encuentra(self):
        v = voice_import.create(grabacion(), "Gory", model=WhisperFalso())
        with mock.patch.dict(os.environ, {"VOICES_CUSTOM_DIR": str(voice_import.folder())}):
            sys.path.insert(0, str(ROOT / "voz"))
            sys.modules.pop("servidor", None)            # se vuelve a leer con esta carpeta de voces propias
            try:
                servidor = importlib.import_module("servidor")
            except ImportError as e:                     # sin las librerías de la voz en este entorno
                self.skipTest(f"voz/servidor.py no se puede importar aquí: {e}")
            finally:
                sys.path.remove(str(ROOT / "voz"))
                sys.modules.pop("servidor", None)
            wav, cfg = servidor._voz(v["tts_voice"])
        self.assertEqual(wav, voice_import.folder() / "p_gory_es.wav")
        self.assertIn("palabra", cfg["ref_text"])


if __name__ == "__main__":
    unittest.main()
