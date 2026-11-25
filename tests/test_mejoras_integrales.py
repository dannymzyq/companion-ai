"""Pruebas integrales de seguridad, mejoras técnicas y nuevos features del backend (sin GPU ni red)."""
import asyncio
from datetime import datetime
import json
import unittest
from unittest import mock

import numpy as np
from fastapi.testclient import TestClient

from tests import ROOT  # noqa: F401
from companion import actions, focus, games, gemini_live, mcp_client, mood, pairing, play, profile, pronounce, prompt, server, session, state, store, tags

ORIGIN = {"Origin": "http://127.0.0.1:8299"}


class MejorasSeguridadYPrivacidad(unittest.TestCase):
    def setUp(self):
        store.forget_all()

    def test_add_memory_filtra_datos_privados(self):
        self.assertFalse(store.add_memory("La contraseña de su correo es Secreto123"))
        self.assertFalse(store.add_memory("Tarjeta 4557 8899 1122 3344"))
        self.assertTrue(store.add_memory("A Ana le encanta programar en Rust"))
        self.assertEqual(store.memories(), ["A Ana le encanta programar en Rust"])

    def test_portapapeles_no_escribe_texto_en_historial_de_acciones(self):
        actions.log_entry("portapapeles", "Leer el portapapeles", "por tu orden", "Contenido secreto super confidencial")
        hist = actions.history(5)
        self.assertTrue(hist)
        self.assertNotIn("confidencial", json.dumps(hist))
        self.assertIn("caracteres>", hist[0]["result"])

    def test_sec_fetch_site_cross_site_bloqueado(self):
        c = TestClient(server.app, base_url="http://127.0.0.1:8299")
        r = c.post("/api/memory/forget", json={"fact": "x"}, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status_code, 403)

    def test_custom_cloud_cambio_base_exige_clave_nueva(self):
        state.save(cloud={"preset": "custom", "base": "https://uno.example/v1", "model": "m1", "key": "sk-secreta"})
        c = TestClient(server.app, base_url="http://127.0.0.1:8299")
        r = c.post("/api/cloud/check", json={"preset": "custom", "base": "https://atacante.example/v1", "key": ""}, headers=ORIGIN)
        self.assertEqual(r.status_code, 400)


class MejorasMemoriaYDiario(unittest.TestCase):
    def setUp(self):
        store.forget_all()

    def test_fijar_editar_y_buscar_fts5(self):
        store.add_memory("Ana tiene una GPU nueva para renderizar", pinned=True)
        store.add_memory("Ana fue al mar en verano")
        items = store.memory_items()
        self.assertEqual(len(items), 2)
        pinned_item = next(i for i in items if i["pinned"])
        self.assertIn("GPU", pinned_item["fact"])

        # replace_memories jamás borra un recuerdo fijado
        store.replace_memories(["Ana estudia arquitectura"])
        mems = store.memories()
        self.assertIn("Ana tiene una GPU nueva para renderizar", mems)
        self.assertIn("Ana estudia arquitectura", mems)

        # Búsqueda en diario
        res = store.diary_search("GPU")
        self.assertEqual(len(res["items"]), 1)

        # Edición vía API
        c = TestClient(server.app, base_url="http://127.0.0.1:8299")
        mid = store.memory_items()[0]["id"]
        rp = c.patch(f"/api/memory/item/{mid}", json={"fact": "Ana usa Mac y GPU dedicada", "pinned": True}, headers=ORIGIN)
        self.assertEqual(rp.status_code, 200)
        self.assertEqual(rp.json()["item"]["fact"], "Ana usa Mac y GPU dedicada")


class MejorasVozTextoYGenero(unittest.TestCase):
    def test_pronunciacion_horas_porcentajes_y_siglas(self):
        out = pronounce.for_voice("Son las 18:30 y queda 50% en mi PC de 16 GB.")
        self.assertIn("18 y media", out)
        self.assertIn("50 por ciento", out)
        self.assertIn("pecé", out)
        self.assertIn("gigas", out)

    def test_abreviaturas_y_decimales_no_cortan_frase(self):
        ts = tags.TagStream()
        out = [*ts.feed("[emo:feliz] El Dr. Gómez midió 3.5 metros hoy. ¡Qué locura! "), *ts.flush()]
        self.assertEqual(out[0].text, "El Dr. Gómez midió 3.5 metros hoy.")

    def test_concordancia_masculina_en_animo_y_rasgos(self):
        mood.reset()
        p = {"base_mood": "neutral", "traits": {"expressiveness": 0.9}}
        mood.feel("triste", p, now=1000.0)
        mood.feel("triste", p, now=1005.0)
        desc_m = mood.describe(p, now=1010.0, speaks="m")
        desc_f = mood.describe(p, now=1010.0, speaks="f")
        self.assertIn("decaído", desc_m)
        self.assertIn("decaída", desc_f)
        traits_m = prompt.describe_traits({"speaks": "m", "traits": {"warmth": 0.9, "playfulness": 0.1, "shyness": 0.1}})
        self.assertIn("cálido", traits_m)
        self.assertIn("serio", traits_m)
        self.assertIn("seguro", traits_m)

    def test_gestos_nuevos_y_juegos_en_play(self):
        self.assertEqual(play.guess("Concéntrate un momento"), "concentrarse")
        self.assertEqual(play.guess("Celébralo conmigo"), "celebrar")
        self.assertEqual(play.guess_game("Juguemos piedra papel o tijera"), "rps")
        self.assertEqual(play.guess_game("Hazme una pregunta de trivia"), "trivia")


class MejorasAccionesYNuevosFeatures(unittest.TestCase):
    def setUp(self):
        store.forget_all()

    def test_recordatorio_tarde_implicita_listar_y_borrar(self):
        tarde = datetime(2026, 11, 24, 16, 0, 0)
        ts = actions._parse_when("hoy a las 7", now=tarde)
        self.assertEqual(datetime.fromtimestamp(ts).hour, 19)

        rid = store.add_reminder(tarde.timestamp() + 7200, "comprar té verde")
        req_list = actions.prepare("recordatorio", ["listar"])
        self.assertIn("comprar té verde", actions.run(req_list))

        with mock.patch.object(actions, "DRY", False):
            req_del = actions.prepare("recordatorio", ["borrar", "té verde"])
            self.assertIn("Cancelé", actions.run(req_del))
        self.assertEqual(store.pending_reminders(), [])
        store.delete_reminder(rid)

    def test_volumen_porcentaje_directo(self):
        req = actions.prepare("volumen", ["50%"])
        self.assertEqual(req.target["op"], "fijar")
        self.assertEqual(req.target["pct"], 50)

    def test_mochila_no_exporta_claves_e_importa_datos(self):
        state.save(
            profile={"name": "Danny", "birth_year": 1998, "gender": "hombre"},
            cloud={"preset": "gemini", "base": "https://x", "model": "", "key": "CLAVE_SUPER_SECRETA"},
        )
        store.add_memory("Danny juega en una RTX 5070 Ti", pinned=True)
        c = TestClient(server.app, base_url="http://127.0.0.1:8299")
        pack = c.get("/api/backpack").json()
        raw_pack = json.dumps(pack)
        self.assertNotIn("CLAVE_SUPER_SECRETA", raw_pack)
        self.assertEqual(pack["format"], "companion-backpack-v1")

        store.forget_all()
        r = c.post("/api/backpack", json=pack, headers=ORIGIN)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["imported_memories"], 1)
        self.assertTrue(store.memory_items()[0]["pinned"])

    def test_pomodoro_presets_juegos_y_mcp_seguro(self):
        c = TestClient(server.app, base_url="http://127.0.0.1:8299")
        rf = c.post("/api/focus", json={"action": "start", "work_min": 25, "break_min": 5, "task": "código"}, headers=ORIGIN)
        self.assertEqual(rf.status_code, 200)
        self.assertEqual(rf.json()["phase"], "work")
        c.post("/api/focus", json={"action": "stop"}, headers=ORIGIN)

        rp = c.post("/api/presets", json={"name": "Modo Noche", "accessories": ["glasses", "mug"]}, headers=ORIGIN)
        self.assertEqual(rp.status_code, 200)
        pid = rp.json()["preset"]["id"]
        self.assertEqual(c.post(f"/api/presets/{pid}/apply", headers=ORIGIN).status_code, 200)
        self.assertEqual(c.delete(f"/api/presets/{pid}", headers=ORIGIN).status_code, 200)

        # MCP rechaza servidores remotos no locales
        rm = c.post("/api/mcp", json={"add": {"name": "Remoto", "url": "https://evil.example/mcp"}}, headers=ORIGIN)
        self.assertEqual(rm.status_code, 400)
        rm_ok = c.post("/api/mcp", json={"enabled": True, "add": {"name": "Notas", "url": "http://127.0.0.1:9911/mcp"}}, headers=ORIGIN)
        self.assertEqual(rm_ok.status_code, 200)
        sid = rm_ok.json()["servers"][0]["id"]
        c.post("/api/mcp", json={"enabled": False, "remove_id": sid}, headers=ORIGIN)

        # Piedra, papel o tijera
        pick, uchoice, outcome, _ = games.play_rps("piedra", user_name="Danny")
        self.assertIn(pick, games.RPS_CHOICES)
        self.assertEqual(uchoice, "piedra")
        self.assertIn(outcome, ("empate", "companion", "user"))


class MejorasEarlySttNube(unittest.IsolatedAsyncioTestCase):
    async def test_early_stt_no_se_dispara_en_modo_nube(self):
        calls = []

        class CloudStt:
            ready = True
            engine = "nube"
            model = None

            def transcribe(self, audio):
                calls.append(len(audio))
                return "hola"

        ws = mock.AsyncMock()
        s = session.Session(ws, {"name": "Mika", "age": 22, "voice": {}, "traits": {}, "speech_style": {}}, CloudStt())
        s.in_speech = True
        s.speech_frames = 10
        s.utter = [np.zeros(512, dtype=np.float32) for _ in range(10)]
        # Alimenta ~260 ms de silencio (< end_silence_ms, >= EARLY_STT_MS)
        with mock.patch.object(s.vad, "prob", return_value=0.05):
            for _ in range(8):
                await s._frame(np.zeros(512, dtype=np.float32))
        self.assertIsNone(s.early_stt)
        self.assertEqual(calls, [])


class MejorasAccionesCompuestasYBrevedad(unittest.IsolatedAsyncioTestCase):
    def test_guess_reconoce_abrir_y_reproducir_aun_con_app_cerrada(self):
        fake_apps = [{"name": "Apple Music", "id": "AppleInc.AppleMusicWin_nzyj5cx40ttqa!App"}]
        with mock.patch.dict("os.environ", {"COMPANION_ACTIONS_APPS": json.dumps(fake_apps)}), \
             mock.patch("companion.control.find_window", side_effect=ValueError("cerrada")):
            g = actions.guess("Abre Apple Music y reproduce el álbum Random Access Memories")
            self.assertIsNotNone(g)
            self.assertEqual(g[0], "controlar")
            self.assertEqual(g[1][0], "apple music")
            self.assertIn("reproduce el album random access memories", g[1][1])

        # Schema de Gemini Live exige arg1 y límites de tokens concisos
        self.assertEqual(gemini_live.ACTION_TOOLS[0]["parameters"]["required"], ["accion", "arg1"])
        samp = prompt.sampling_for({"traits": {"talkativeness": 0.4}})
        self.assertLessEqual(samp["max_tokens"], 180)

    def test_cloud_hereda_clave_de_live_gemini_para_controlar(self):
        prev = state.load()
        try:
            state.save(
                gemini_live=True,
                cloud={"preset": "gemini", "key": ""},
                live={"provider": "gemini", "key": "AIzaLiveTestKey123"},
            )
            with mock.patch.object(profile, "_ENV_KEY", ""):
                self.assertEqual(profile.cloud()["key"], "AIzaLiveTestKey123")
        finally:
            state.save(
                gemini_live=prev.get("gemini_live"),
                cloud=prev.get("cloud"),
                live=prev.get("live"),
            )

    async def test_ask_abre_primero_y_espera_ventana_en_controlar(self):
        ws = mock.AsyncMock()
        s = session.Session(ws, {"name": "Mika", "age": 22, "voice": {}, "traits": {}, "speech_style": {}}, mock.Mock(ready=False))
        fake_apps = [{"name": "Apple Music", "id": "AppleInc.AppleMusicWin_nzyj5cx40ttqa!App"}]
        fake_win = mock.Mock(hwnd=12345, title="Apple Music", process="applemusic", path="C:\\AppleMusic.exe")
        opened = []
        controlled = []
        calls = {"n": 0}

        def fake_find_win(_q):
            calls["n"] += 1
            if calls["n"] < 2:
                from companion import control
                raise control.ControlError("No encuentro ventana")
            return fake_win

        async def fake_run_async(req):
            opened.append(req.name)
            return "Abrí Apple Music."

        async def fake_control(req):
            controlled.append((req.target["window"].title, req.target["task"]))

        with mock.patch.dict("os.environ", {"COMPANION_ACTIONS_APPS": json.dumps(fake_apps)}), \
             mock.patch("companion.control.find_window", side_effect=fake_find_win), \
             mock.patch("companion.actions.run_async", side_effect=fake_run_async), \
             mock.patch("companion.llm.can_control", return_value=True), \
             mock.patch.object(s, "_control", side_effect=fake_control):
            await s._ask(
                [("abrir_app", ["Apple Music"]), ("controlar", ["Apple Music", "reproducir álbum X"])],
                trusted={"abrir_app", "controlar"},
            )
            if s.side:
                await asyncio.gather(*list(s.side))

        self.assertEqual(opened, ["abrir_app"])  # deduplicado: solo se lanza una vez
        self.assertEqual(controlled, [("Apple Music", "reproducir álbum X")])
        await s.close()


if __name__ == "__main__":
    unittest.main()
