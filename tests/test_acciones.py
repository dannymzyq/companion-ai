"""Acciones en la PC y los frenos del control de ventanas (no se ejecuta nada: COMPANION_ACTIONS_DRY)."""
import unittest

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from companion import actions, control
from companion.control import Item


class Preparar(unittest.TestCase):
    def test_temporizador(self):
        r = actions.prepare("temporizador", ["5 minutos", "la pasta"])
        self.assertEqual(r.target["seconds"], 300)
        self.assertEqual(r.detail, "Temporizador de 5 min (la pasta)")
        self.assertEqual(actions.prepare("temporizador", ["una hora y media"]).target["seconds"], 5400)

    def test_temporizador_fuera_de_rango(self):
        for mal in ("0 segundos", "13 horas", "nada"):
            with self.assertRaises(actions.ActionError, msg=mal):
                actions.prepare("temporizador", [mal])

    def test_web_solo_http(self):
        self.assertEqual(actions.prepare("abrir_web", ["youtube.com"]).target["url"], "https://youtube.com")
        busca = actions.prepare("abrir_web", ["recetas de ají de gallina"])
        self.assertTrue(busca.target["url"].startswith("https://www.google.com/search?q="))
        for mal in ("javascript:alert(1)", "file:///C:/Windows"):
            self.assertTrue(actions.prepare("abrir_web", [mal]).target["url"].startswith("https://www.google.com/search?q="))

    def test_carpeta_de_red_nunca(self):
        # Ni siquiera se comprueba si existe: eso ya conecta con el servidor (y Windows le da una huella de la clave)
        from pathlib import Path
        from unittest import mock
        real = Path.is_dir

        def is_dir(p):
            if "servidor" in str(p):
                raise AssertionError(f"tocó la red: {p}")
            return real(p)
        with mock.patch("pathlib.Path.is_dir", is_dir):
            for mal in (r"\\servidor.ejemplo\carpeta", "//servidor.ejemplo/carpeta", r"\\?\UNC\servidor\x",
                        "smb://servidor/x", "file://servidor/x"):
                with self.assertRaises(actions.ActionError, msg=mal):
                    actions.prepare("abrir_carpeta", [mal])

    def test_catalogo_cerrado(self):
        for nombre in ("borrar_archivo", "ejecutar", "enviar_correo", "comprar"):
            with self.assertRaises(actions.ActionError):
                actions.prepare(nombre, ["x"])

    def test_controlar_se_puede_permitir_siempre(self):
        """Desde el 16 nov 2026 (petición del usuario); los pasos delicados se siguen confirmando aparte."""
        actions.save(add_always="controlar")
        self.assertIn("controlar", actions.always())
        actions.save(forget_always="controlar")

    def test_acceso_total(self):
        actions.save(full=True, ask=True)
        self.assertTrue(actions.config()["full"])
        self.assertFalse(actions.config()["ask"])          # con acceso total no hay tarjetas
        actions.save(full=False, ask=False)
        self.assertFalse(actions.config()["full"])


class OrdenesClaras(unittest.TestCase):
    def test_reconoce(self):
        self.assertEqual(actions.guess("Pon un temporizador de 5 minutos"), ("temporizador", ["5 minutos"]))
        self.assertEqual(actions.guess("sube el volumen"), ("volumen", ["sube"]))
        self.assertEqual(actions.guess("abre youtube.com"), ("abrir_web", ["youtube.com"]))
        self.assertEqual(actions.guess("pausa la música"), ("multimedia", ["pausa"]))

    def test_charla_no_es_orden(self):
        for frase in ("¿Qué tal tu día?", "Me encanta cuando me cuentas cosas", "Hoy estoy cansado"):
            self.assertIsNone(actions.guess(frase), frase)


class FrenosDelControl(unittest.TestCase):
    """Los dos frenos que no se quitan (CLAUDE.md): lo delicado se confirma salvo que la orden ya lo pidiera."""

    def test_delicado_pide_confirmar(self):
        for boton in ("Enviar", "Comprar ahora", "Eliminar lista", "Pagar"):
            self.assertTrue(control.needs_confirm("pulsar", boton, None, "App"), boton)
        self.assertFalse(control.needs_confirm("pulsar", "Reproducir", None, "Apple Music"))

    def test_enter_en_un_chat(self):
        chat = Item(n=1, kind="campo", name="Escribe un mensaje")
        self.assertTrue(control.needs_confirm("enter", "", chat, "WhatsApp"))
        self.assertFalse(control.needs_confirm("enter", "", Item(n=1, kind="campo", name="Buscar"), "Explorador"))

    def test_la_orden_lo_pedia(self):
        self.assertTrue(control.task_allows("envía el correo a Ana", "Enviar"))
        self.assertTrue(control.task_allows("elimina la lista de la compra", "Eliminar lista"))
        self.assertFalse(control.task_allows("escribe un correo a Ana", "Enviar"))
        self.assertFalse(control.task_allows("reproduce La Barca", "Comprar canción"))

    def test_leer_pasos(self):
        self.assertEqual(control.parse("pulsar 3"), ("pulsar", ["3"]))
        self.assertEqual(control.parse("Paso: escribir 2 | Hola, Ana"), ("escribir", ["2", "Hola, Ana"]))
        self.assertEqual(control.parse("listo | ya suena"), ("listo", ["ya suena"]))
        self.assertIsNone(control.parse("No sé qué hacer"))


if __name__ == "__main__":
    unittest.main()


class OrdenesSeguidas(unittest.TestCase):
    """24 nov 2026: «abre Apple Music» y luego «pon La Barca» va a esa aplicación; MCP siempre con tarjeta."""
    def test_seguir_en_la_app_abierta(self):
        from companion import actions
        for frase in ("Pon La Barca de Luis Miguel", "oye, reproduce lofi", "busca jazz"):
            self.assertTrue(actions.follow_up(frase), frase)
        for frase in ("pon el volumen al 20", "ponme un temporizador de 5 minutos", "¿qué tal estás?", "me gusta el jazz"):
            self.assertFalse(actions.follow_up(frase), frase)

    def test_mcp_nuevo_no_es_de_solo_lectura(self):
        from companion import mcp_client
        cfg = mcp_client.save(enabled=True, add={"name": "notas", "url": "http://127.0.0.1:8765/mcp"})
        self.assertFalse(cfg["servers"][-1]["read_only"])
        mcp_client.save(enabled=False, remove_id=cfg["servers"][-1]["id"])
