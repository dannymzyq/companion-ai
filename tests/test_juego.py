"""Pedirle cosas al personaje (17 nov 2026): companion/play.py reconoce «¿puedes bailar?», «salta», «duérmete»…"""
import unittest

from companion import play
from companion.prompt import GESTURES


class Peticiones(unittest.TestCase):
    def test_reconoce(self):
        casos = {
            "¿Puedes bailarme algo?": "bailar", "¿quieres que bailemos?": "bailar", "salta!": "saltar",
            "¿sabes saltar?": "saltar", "¿podrías dar una vuelta?": "girar", "date una vuelta": "girar",
            "estírate un poco": "estirarse", "quiero que hagas un hechizo": "hechizo", "canta algo": "tararear",
            "hazme la V": "paz", "Duérmete ya": "dormir", "échate una siesta": "dormir", "¡A dormir!": "dormir",
            "quiero que te duermas": "dormir", "saluda a mi hermana": "saludar",
        }
        for texto, gesto in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(play.guess(texto), gesto)

    def test_no_se_dispara(self):
        for texto in ["ayer fui a un baile", "me voy a dormir", "no bailes por favor", "no puedo dormir", "que bonito",
                      "¿qué te gusta bailar?", "", None]:
            with self.subTest(texto=texto):
                self.assertIsNone(play.guess(texto))

    def test_todos_son_gestos_del_prompt(self):
        for nombre in play._MOVES:
            self.assertIn(nombre, GESTURES)


if __name__ == "__main__":
    unittest.main()
