"""Seguridad local del servidor: solo atiende a su propio nombre y origen (sin arrancar Whisper ni la voz)."""
import unittest

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from fastapi.testclient import TestClient

from companion import server

LOCAL = ("127.0.0.1", 50000)        # quien llama desde esta misma PC


class SeguridadLocal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Sin «with»: no corre el arranque (no carga Whisper, ni la voz, ni el modelo local).
        cls.local = TestClient(server.app, base_url="http://127.0.0.1:8299", client=LOCAL)

    def test_nombre_de_esta_pc(self):
        self.assertEqual(self.local.get("/api/models").status_code, 200)
        self.assertEqual(TestClient(server.app, base_url="http://localhost:8299", client=LOCAL).get("/api/models").status_code, 200)

    def test_dns_rebinding(self):
        """Una página cuyo dominio pasa a apuntar a 127.0.0.1 no puede leer los recuerdos."""
        ajeno = TestClient(server.app, base_url="http://malicioso.example:8299", client=LOCAL)
        self.assertEqual(ajeno.get("/api/memory").status_code, 400)
        self.assertEqual(ajeno.get("/").status_code, 400)

    def test_otra_pagina_no_cambia_nada(self):
        r = self.local.post("/api/memory/forget", json={"fact": "x"}, headers={"Origin": "https://malicioso.example"})
        self.assertEqual(r.status_code, 403)
        r = self.local.post("/api/memory/forget", json={"fact": "x"}, headers={"Origin": "http://127.0.0.1:8299"})
        self.assertEqual(r.status_code, 200)

    def test_websocket_de_otra_pagina(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.local.websocket_connect("/ws", headers={"Origin": "https://malicioso.example"}) as ws:
                ws.receive_text()

    def test_la_clave_no_sale(self):
        cfg = self.local.get("/api/config").json()
        self.assertNotIn("key", cfg["cloud"])


if __name__ == "__main__":
    unittest.main()
