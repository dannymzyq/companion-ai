"""Etiquetas del modelo, pronunciación, comprobación de la voz y resúmenes de memoria."""
import unittest

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from companion import pronounce, voicecheck
from companion.session import split_summary
from companion.tags import TagStream


def run(chunks):
    p = TagStream()
    out = [s for c in chunks for s in p.feed(c)] + p.flush()
    return p, out


class Etiquetas(unittest.TestCase):
    def test_etiquetas_no_se_leen(self):
        p, out = run(["[emo:feliz] ¡Qué bien que hayas vuelto, Ana! [gesto:saludar]",
                      " Hoy podemos hablar de lo que quieras. [recordar: Ana vuelve de viaje]"])
        texto = " ".join(s.text for s in out)
        self.assertNotIn("[", texto)
        self.assertEqual(out[0].emotion, "feliz")
        self.assertIn("saludar", [g for s in out for g in s.gestures])
        self.assertEqual(p.memories, ["Ana vuelve de viaje"])

    def test_etiqueta_partida_entre_trozos(self):
        p, out = run(["Claro, te lo abro ahora mismo. [acc", "ion: abrir_app | Spotify]"])
        self.assertEqual(p.actions, [("abrir_app", ["Spotify"])])
        self.assertTrue(all("accion" not in s.text for s in out))

    def test_etiqueta_sin_cerrar_no_se_lee(self):
        _, out = run(["Vale, ahora lo miro con calma. [emo:fel"])
        self.assertEqual([s.text for s in out], ["Vale, ahora lo miro con calma."])

    def test_emocion_desconocida_se_ignora(self):
        _, out = run(["[emo:volcanica] Hola, ¿cómo te ha ido el día de hoy?"])
        self.assertIsNone(out[0].emotion)


class Pronunciacion(unittest.TestCase):
    def test_ingles_como_suena(self):
        self.assertIn("Apel Miúsik", pronounce.for_voice("Te lo pongo en Apple Music."))

    def test_qu_como_k(self):
        self.assertEqual(pronounce.for_voice("¿Qué quieres?"), "¿Ké kieres?")
        self.assertEqual(pronounce.for_voice("cuando"), "cuando")        # sin «qu»+e/i no cambia


class ComprobarVoz(unittest.TestCase):
    def test_tolera_ortografia_y_cifras(self):
        self.assertEqual(voicecheck.missing("Hola Danny, son las cinco y media", "Hola Dani, son las 5 y media"), [])

    def test_detecta_palabra_comida(self):
        lost = voicecheck.missing("Podemos retomarlo en media hora", "Podemos remedia hora")
        self.assertIn("retomarlo", lost)
        self.assertTrue(voicecheck.bad(lost))

    def test_interjecciones_no_cuentan(self):
        self.assertFalse(voicecheck.bad(voicecheck.missing("Ay, qué bonito", "Qué bonito")))


class Resumenes(unittest.TestCase):
    def test_separa_datos(self):
        summary, facts = split_summary("Hablaron del viaje de Ana a Cusco.\nDATO: A Ana le encanta la fotografía\n"
                                       "DATO: Ana trabaja como enfermera")
        self.assertEqual(summary, "Hablaron del viaje de Ana a Cusco.")
        self.assertEqual(facts, ["A Ana le encanta la fotografía", "Ana trabaja como enfermera"])

    def test_no_guarda_datos_privados(self):
        _, facts = split_summary("Resumen corto de la charla de hoy.\nDATO: Su tarjeta es 4111 1111 1111 1111\n"
                                 "DATO: Su contraseña del correo es gato123\nDATO: Su DNI es 12345678")
        self.assertEqual(facts, [])

    def test_como_mucho_tres(self):
        _, facts = split_summary("Charla.\n" + "\n".join(f"DATO: Ana tiene el dato número {n}" for n in "abcde"))
        self.assertEqual(len(facts), 3)


if __name__ == "__main__":
    unittest.main()
