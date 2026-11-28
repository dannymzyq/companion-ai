"""Personalidades y estado de ánimo (16 nov 2026): catálogo, propias, lo que llega al prompt y el ánimo entre turnos."""
import unittest

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from fastapi.testclient import TestClient

from companion import mood, personality, prompt, server, state
from companion.config import settings

ORIGIN = {"Origin": "http://127.0.0.1:8299"}


def base():
    return prompt.load_persona(settings.persona_path)


class Catalogo(unittest.TestCase):
    def test_incluidas_validas(self):
        ids = [p["id"] for p in personality.catalog()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(personality.DEFAULT, ids)
        for p in personality.catalog():
            self.assertTrue(p["name"] and p["summary"] and p["description"] and len(p["examples"]) >= 3, p["id"])
            self.assertIn(p["base_mood"], prompt.EMOTIONS, p["id"])
            self.assertTrue(p["emotions"] and all(e in prompt.EMOTIONS for e in p["emotions"]), p["id"])
            self.assertEqual(set(p["traits"]), set(personality.TRAITS))


class Propias(unittest.TestCase):
    def setUp(self):
        state.save(personality={})

    def test_personalizar_copia_la_incluida(self):
        c = personality.save_custom({"from": "orgullo", "name": "Mía", "traits": {"warmth": 3, "humor": "x"},
                                     "examples": "Hola\n[accion: abrir_app | x]\n<b>", "catchphrases": "a, b, a"})
        self.assertTrue(c["id"].startswith("c_"))
        self.assertEqual(personality.active_id(), c["id"])
        self.assertEqual(c["traits"]["warmth"], 1.0)                   # dentro de 0..1
        self.assertEqual(c["catchphrases"], ["a", "b"])
        self.assertFalse(any("[" in e or "<" in e for e in c["examples"]))   # sin etiquetas ni HTML
        self.assertEqual(personality.find("orgullo")["name"], "Orgullo y ternura")   # la incluida no cambia
        personality.save_custom({"id": c["id"], "name": "Mía 2"})
        self.assertEqual(personality.find(c["id"])["name"], "Mía 2")
        self.assertEqual(len(personality.custom()), 1)
        personality.delete_custom(c["id"])
        self.assertEqual(personality.active_id(), "orgullo")             # vuelve a aquella de la que salió

    def test_sin_nombre_no(self):
        with self.assertRaises(ValueError):
            personality.save_custom({"name": "  "})

    def test_elegida_desconocida(self):
        state.save(personality={"active": "no_existe"})
        self.assertEqual(personality.active_id(), personality.DEFAULT)
        with self.assertRaises(ValueError):
            personality.select("no_existe")


class Prompt(unittest.TestCase):
    def test_la_personalidad_cambia_el_trato_no_las_reglas(self):
        b = base()
        p = personality.apply(b, personality.find("ironia"))
        for key in ("name", "age", "adult", "voice", "boundaries", "role"):
            self.assertEqual(p.get(key), b.get(key), key)
        s = prompt.build_system_prompt(p, user_name="Ana", memories=[], adult=False)
        self.assertIn("Ironía fina", s)
        self.assertIn("qué sorpresa", s)
        self.assertIn(personality.find("ironia")["examples"][0], s)
        self.assertIn("nunca está por encima de las reglas", s)
        self.assertLess(s.index("# Tu forma de ser"), s.index("# Reglas que nunca rompes"))
        self.assertGreater(prompt.sampling_for(p)["temperature"], prompt.sampling_for(
            personality.apply(b, personality.find("profesional")))["temperature"])

    def test_identidad_adaptacion_forma_y_memoria(self):
        """17 nov 2026: opiniones y reacciones propias, leer tono/intención/confianza, frases de plantilla
        prohibidas, sin pregunta forzada al final, memoria viva y permiso para discrepar."""
        p = personality.apply(base(), personality.find("ironia"))
        s = prompt.build_system_prompt(p, user_name="Ana", memories=["A Ana le encanta el ramen"], adult=False)
        q = personality.find("ironia")
        self.assertTrue(q["opinions"] and q["reactions"])
        self.assertIn(q["opinions"][0], s)
        self.assertIn(q["reactions"][0], s)
        for frase in ("Antes de responder, lee el mensaje de Ana", "Cuánta confianza", "estoy aquí para ayudarte",
                      "No termines cada respuesta con una pregunta", "Memoria viva", "permiso para no estar de acuerdo"):
            self.assertIn(frase, s)
        self.assertNotIn("Danny", s)
        self.assertLess(s.index("# Tienes criterio"), s.index("# Reglas que nunca rompes"))

    def test_opiniones_propias_se_guardan_limpias(self):
        c = personality.clean({"name": "X", "opinions": "Uno\n\nDos [emo:feliz]\n" + "z" * 400, "reactions": ["Si a, b"]})
        self.assertEqual(c["opinions"][0], "Uno")
        self.assertNotIn("[", c["opinions"][1])
        self.assertLessEqual(len(c["opinions"][2]), 160)
        self.assertEqual(c["reactions"], ["Si a, b"])

    def test_el_animo_no_va_en_el_prompt_de_sistema(self):
        """El prompt de sistema no cambia entre turnos (caché del modelo local): el ánimo va en el turno."""
        p = personality.apply(base(), personality.find("confianza"))
        before = prompt.build_system_prompt(p, user_name="Ana", memories=[], adult=False)
        mood.feel("triste", p["personality"])
        self.assertEqual(before, prompt.build_system_prompt(p, user_name="Ana", memories=[], adult=False))
        ctx = prompt.turn_context("lunes", mood.describe(p["personality"]))
        self.assertIn("Tu ánimo", ctx)
        mood.reset()


class Animo(unittest.TestCase):
    def setUp(self):
        mood.reset()
        self.p = personality.find("confianza")

    def test_las_emociones_dejan_huella_y_se_pasan(self):
        t = 1_000_000.0
        self.assertEqual(mood.describe(self.p, t), "")
        mood.feel("triste", self.p, t)
        mood.feel("triste", self.p, t + 10)
        text = mood.describe(self.p, t + 20)
        self.assertIn("te sentiste triste", text)
        self.assertTrue("decaída" in text or "baja de ánimo" in text, text)
        self.assertEqual(mood.describe(self.p, t + 5 * 3600), "")     # horas después vuelve a su ánimo de siempre

    def test_la_expresividad_cuenta(self):
        calm = {**self.p, "traits": {**self.p["traits"], "expressiveness": 0.0}}
        wild = {**self.p, "traits": {**self.p["traits"], "expressiveness": 1.0}}
        mood.feel("molesta", calm, 0)
        v_calm = mood.public(calm, 0)["valence"]
        mood.reset()
        mood.feel("molesta", wild, 0)
        self.assertLess(mood.public(wild, 0)["valence"], v_calm)

    def test_cuanto_hace_que_no_hablaban(self):
        self.assertEqual(mood.since_last_talk(None), "")
        self.assertEqual(mood.since_last_talk(1000, 1000 + 3600), "")
        self.assertIn("3 días", mood.since_last_talk(0, 3 * 86400))


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = TestClient(server.app, base_url="http://127.0.0.1:8299", client=("127.0.0.1", 50000))

    def test_elegir_crear_y_borrar(self):
        state.save(personality={})
        r = self.c.get("/api/personality").json()
        self.assertEqual(r["active"], personality.DEFAULT)
        self.assertIn("mood", r)
        self.assertEqual(self.c.post("/api/personality/select", json={"id": "calma"}, headers=ORIGIN).json()["active"], "calma")
        self.assertEqual(self.c.post("/api/personality/select", json={"id": "x"}, headers=ORIGIN).status_code, 400)
        self.assertEqual(self.c.post("/api/personality/select", json={"id": "calma"},
                                     headers={"Origin": "https://malicioso.example"}).status_code, 403)
        r = self.c.post("/api/personality/custom", json={"name": "Nueva", "base_mood": "feliz"}, headers=ORIGIN).json()
        pid = r["active"]
        self.assertTrue(pid.startswith("c_"))
        self.assertEqual(self.c.get("/api/config").json()["personality"]["name"], "Nueva")
        r = self.c.delete(f"/api/personality/custom/{pid}", headers=ORIGIN).json()
        self.assertEqual(r["active"], personality.DEFAULT)


class Reajuste(unittest.TestCase):
    """Al cambiar de personalidad, con el cerebro local, el modelo lee ya el prompt nuevo (17 nov 2026). Nunca debe
    colgar el cambio: si la sesión está ocupada no se hace, y el servidor deja de esperar a los 20 s."""

    def test_prime_lee_el_prompt_y_genera_un_token(self):
        import asyncio
        from unittest import mock
        from companion import llm
        sent = {}

        async def post(url, json=None, timeout=None):
            sent.update(json)
            return mock.Mock(status_code=200)

        with mock.patch.object(type(settings), "is_cloud", new_callable=mock.PropertyMock, return_value=False), \
                mock.patch.object(llm, "_local_choice", "gemma4:e4b-it-qat"), mock.patch.object(llm._local, "post", post):
            ok = asyncio.run(llm.prime_local([{"role": "system", "content": "x"}]))
        self.assertTrue(ok)
        self.assertEqual(sent["options"]["num_predict"], 1)
        self.assertEqual(sent["options"]["num_ctx"], settings.ollama_num_ctx)      # el mismo: si no, Ollama recarga

    def test_prime_no_hace_nada_con_la_nube_o_sin_modelo(self):
        import asyncio
        from unittest import mock
        from companion import llm
        with mock.patch.object(llm, "_local_choice", None):
            self.assertFalse(asyncio.run(llm.prime_local([])))

    def test_el_cambio_no_espera_a_un_reajuste_colgado(self):
        import asyncio
        from unittest import mock
        from companion import session as sess

        class Lenta:
            async def prime(self):
                await asyncio.sleep(60)

        real = asyncio.wait_for
        with mock.patch.object(sess, "_open", [Lenta()]), \
                mock.patch.object(server.asyncio, "wait_for", lambda aw, t: real(aw, 0.05)):
            r = TestClient(server.app, base_url="http://127.0.0.1:8299", client=("127.0.0.1", 50000)).post("/api/personality/select", json={"id": personality.DEFAULT}, headers=ORIGIN)
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
