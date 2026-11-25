"""Memoria a largo plazo: recuerdos sin duplicados y resúmenes antiguos que vienen al caso."""
import time
import unittest

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from companion import store


class Memoria(unittest.TestCase):
    def setUp(self):
        store.forget_all()

    def test_recuerdo_sin_duplicados(self):
        store.add_memory("A Ana le gusta el café")
        store.add_memory("a ana le gusta el café.")
        self.assertEqual(store.memories(), ["A Ana le gusta el café"])

    def test_resumenes_antiguos_que_vienen_al_caso(self):
        viejo = "Ana contó que prepara un viaje a Cusco en diciembre con su hermana y le preocupa la altura."
        store.add_summary(viejo, 1, 2, time.time() - 90 * 86400)
        for n in range(8):                              # los 8 más recientes ya van siempre en el prompt
            store.add_summary(f"Charla número {n} sobre series de televisión y música.", 3 + n, 4 + n, time.time())
        hits = store.relevant_summaries("¿Te acuerdas de mi viaje a Cusco con mi hermana?")
        self.assertEqual([t for t, _ in hits], [viejo])
        self.assertEqual(store.relevant_summaries("¿Qué hora es?"), [])
        self.assertEqual(store.relevant_summaries("Cusco"), [])           # una sola palabra no basta
        # lo reciente no se repite (ya está en el prompt)
        self.assertEqual(store.relevant_summaries("series de televisión y música"), [])

    def test_los_nombres_no_cuentan(self):
        store.add_summary("Ana y Mika hablaron de recetas de cocina peruana.", 1, 2, time.time() - 86400)
        for n in range(8):
            store.add_summary(f"Ana le contó a Mika la noticia número {n}.", 3 + n, 4 + n, time.time())
        self.assertEqual(store.relevant_summaries("Ana, Mika, ¿qué tal?", ignore="Ana Mika"), [])
        self.assertEqual(len(store.relevant_summaries("Mika, ¿te acuerdas de las recetas de cocina?", ignore="Ana Mika")), 1)


class OrdenarRecuerdos(unittest.TestCase):
    """Orden de los recuerdos (23 nov 2026): se juntan los repetidos y se puede deshacer."""
    def setUp(self):
        store.forget_all()

    def test_lista_del_modelo(self):
        from companion.session import tidy_facts
        texto = "DATO: A Ana le gusta el café\nDATO: a ana le gusta el café.\nDATO: Ana vive en Lima\nDATO: Su clave es 1234 5678\nDATO: Ana estudia diseño"
        self.assertEqual(tidy_facts(texto, 5), ["A Ana le gusta el café", "Ana vive en Lima", "Ana estudia diseño"])
        self.assertIsNone(tidy_facts("No sé hacerlo.", 10))                   # sin lista: no se toca nada
        self.assertIsNone(tidy_facts(texto, 30))                             # perdería demasiados datos
        self.assertIsNone(tidy_facts(texto, 2))                              # más que antes: algo inventó

    def test_deshacer(self):
        for f in ("A Ana le gusta el café", "Ana toma café cada mañana", "Ana vive en Lima"):
            store.add_memory(f)
        store.replace_memories(["Ana toma café cada mañana", "Ana vive en Lima"])
        self.assertTrue(store.can_undo_tidy())
        self.assertEqual(store.last_tidy_count(), 2)
        store.add_memory("Ana tiene un gato llamado Miso")                  # lo de después se conserva sin esperar 1s
        self.assertTrue(store.undo_tidy())
        self.assertEqual(store.memories(), ["A Ana le gusta el café", "Ana toma café cada mañana", "Ana vive en Lima",
                                            "Ana tiene un gato llamado Miso"])
        self.assertFalse(store.can_undo_tidy())
        store.replace_memories(["Ana vive en Lima"])
        store.forget_all()                                                   # olvidar todo borra también la copia
        self.assertFalse(store.can_undo_tidy())


if __name__ == "__main__":
    unittest.main()
