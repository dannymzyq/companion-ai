"""Mascota de escritorio (16 nov 2026): lo que el servidor da para las animaciones del modo flotante. Las
animaciones y el movimiento de la ventana se prueban en scripts/pruebas/prueba_mascota.py (Electron, fuera de pantalla)."""
import logging
import unittest
from types import SimpleNamespace as W
from unittest import mock

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from companion import control, control_task, desktop_scene


class PasosAnimados(unittest.TestCase):
    def test_cada_paso_tiene_su_animacion(self):
        self.assertEqual(control_task._anim("pulsar"), "click")
        self.assertEqual(control_task._anim("doble_clic"), "click")
        self.assertEqual(control_task._anim("escribir"), "type")
        self.assertEqual(control_task._anim("atajo"), "type")
        self.assertEqual(control_task._anim("rueda"), "scroll")
        self.assertEqual(control_task._anim("otra cosa"), "read")

    def test_punto_del_paso(self):
        item = control.Item(n=1, kind="botón", name="Reproducir", box=(100, 200, 140, 220))
        self.assertEqual(control_task._point(item, None, None), [120, 210])
        shot = W(to_screen=lambda x, y: (x + 1000, y + 500))
        self.assertEqual(control_task._point(None, (10, 20), shot), [1010, 520])
        self.assertIsNone(control_task._point(None, None, None))

    def test_sin_saber_donde_esta_la_ventana_la_tarea_sigue(self):
        import asyncio
        with mock.patch.object(desktop_scene, "window", side_effect=RuntimeError("sin ventana")):
            self.assertIsNone(asyncio.run(control_task._where(123)))


class Escena(unittest.TestCase):
    def test_fuera_de_windows_no_hay_ventana_activa(self):
        with mock.patch.object(desktop_scene.sys, "platform", "darwin"):
            self.assertIsNone(desktop_scene.foreground())
            self.assertIsNone(desktop_scene.window(5))

    def test_la_consulta_frecuente_no_llena_el_registro(self):
        from companion import server
        f = server._QuietPolls()
        rec = lambda msg: logging.LogRecord("uvicorn.access", logging.INFO, "", 0, msg, None, None)   # noqa: E731
        self.assertFalse(f.filter(rec('127.0.0.1 - "GET /api/desktop/scene?sit=5 HTTP/1.1" 200')))
        self.assertTrue(f.filter(rec('127.0.0.1 - "GET /api/config HTTP/1.1" 200')))


if __name__ == "__main__":
    unittest.main()
