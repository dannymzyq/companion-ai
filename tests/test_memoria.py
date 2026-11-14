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


if __name__ == "__main__":
    unittest.main()
