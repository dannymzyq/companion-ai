"""Modo En Casa (27 nov 2026): desde la red solo entra un teléfono emparejado, y solo a conversar.

Antes, un equipo de la red que mandaba «Host: localhost» pasaba por esta misma PC: se llevaba los recuerdos, cambiaba
ajustes y, con En Casa encendido, leía el token. Ahora lo decide la dirección de quien llama.
"""
import asyncio
import socket
import ssl
import sys
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)
from companion import actions, llm, pairing, server, session, state, store

LOCAL = ("127.0.0.1", 50000)            # quien llama desde esta misma PC
PHONE = ("192.168.1.50", 50123)         # un teléfono en la Wi-Fi
PC_IP = "192.168.1.10"                  # la IP de la PC en esa red (simulada)
TOKEN = "t" * 43
MEMORY = "A Ana le gusta el cafe de Cusco"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EnCasa(unittest.TestCase):
    def setUp(self):
        store.forget_all()
        store.add_memory(MEMORY)
        state.save(pairing={"enabled": False, "token": ""})
        p = mock.patch.object(pairing, "local_ips", return_value=[PC_IP])
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        state.save(pairing={"enabled": False, "token": ""})

    def phone(self, host: str = PC_IP, **kw) -> TestClient:
        return TestClient(server.app, base_url=f"http://{host}:8299", client=PHONE, **kw)

    def turn_on(self):
        state.save(pairing={"enabled": True, "token": TOKEN})

    def test_host_falso_desde_la_red_no_entra(self):
        falso = self.phone("localhost")
        self.assertEqual(falso.get("/api/backpack").status_code, 400)
        self.assertEqual(falso.post("/api/memory/forget", json={"fact": MEMORY}).status_code, 400)
        self.assertEqual(falso.post("/api/setup/reset").status_code, 400)
        self.turn_on()
        r = falso.get("/api/pairing")
        self.assertEqual(r.status_code, 400)
        self.assertNotIn(TOKEN, r.text)
        self.assertEqual(store.memories(), [MEMORY])

    def test_sin_token_o_apagado_no_entra(self):
        self.assertEqual(self.phone().get("/api/config", params={"pair": TOKEN}).status_code, 400)   # apagado
        self.turn_on()
        self.assertEqual(self.phone().get("/api/config").status_code, 400)                              # sin token
        self.assertEqual(self.phone().get("/api/config", params={"pair": "x" * 43}).status_code, 400)    # otro token
        # Nombrando a la PC por un dominio (DNS rebinding dentro de la red), tampoco.
        self.assertEqual(self.phone("malicioso.example").get("/api/config", params={"pair": TOKEN}).status_code, 400)
        # Desde una dirección que no es de una red privada, tampoco.
        lejos = TestClient(server.app, base_url=f"http://{PC_IP}:8299", client=("8.8.8.8", 4000))
        self.assertEqual(lejos.get("/api/config", params={"pair": TOKEN}).status_code, 400)

    def test_emparejado_conversa_pero_no_cambia_nada(self):
        self.turn_on()
        tel = self.phone(headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(tel.get("/api/config").status_code, 200)
        self.assertEqual(tel.get("/api/memory").status_code, 200)
        for path in ("/api/backpack", "/api/pairing", "/api/mcp"):
            self.assertEqual(tel.get(path).status_code, 403, path)
        self.assertEqual(tel.post("/api/memory/forget", json={"fact": MEMORY}).status_code, 403)
        self.assertEqual(tel.post("/api/setup/reset").status_code, 403)
        self.assertEqual(tel.post("/api/pairing", json={"enabled": False}).status_code, 403)
        self.assertEqual(store.memories(), [MEMORY])

    def test_el_enlace_deja_cookie_y_quita_el_token_de_la_direccion(self):
        self.turn_on()
        tel = self.phone(follow_redirects=False)
        r = tel.get("/", params={"pair": TOKEN})
        self.assertEqual(r.status_code, 303)
        self.assertNotIn(TOKEN, r.headers["location"])
        self.assertIn(pairing.COOKIE_NAME, r.headers.get("set-cookie", ""))
        self.assertNotIn("secure", r.headers.get("set-cookie", "").lower())   # por http no puede ser «Secure»
        self.assertEqual(self.phone(cookies={pairing.COOKIE_NAME: TOKEN}).get("/").status_code, 200)
        cifrado = TestClient(server.app, base_url=f"https://{PC_IP}:8299", client=PHONE, follow_redirects=False)
        r = cifrado.get("/", params={"pair": TOKEN})
        self.assertIn("secure", r.headers.get("set-cookie", "").lower())       # por https, la cookie solo va cifrada

    def test_el_origen_https_del_telefono_vale(self):
        self.turn_on()
        self.assertTrue(server._origin_ok(f"https://{PC_IP}:8299", paired=True))
        self.assertFalse(server._origin_ok(f"https://{PC_IP}:8299"))                 # sin emparejar, no
        self.assertFalse(server._origin_ok("https://malicioso.example:8299", paired=True))

    def test_la_pc_sigue_entrando_y_ve_el_token(self):
        self.turn_on()
        pc = TestClient(server.app, base_url="http://127.0.0.1:8299", client=LOCAL)
        self.assertEqual(pc.get("/api/backpack").status_code, 200)
        self.assertEqual(pc.get("/api/pairing").json().get("enabled"), True)

    def test_websocket_del_telefono_sin_acciones(self):
        self.turn_on()
        made = []
        real = server.Session

        def make(*a, **kw):
            made.append(real(*a, **kw))
            return made[-1]

        fake_config = mock.AsyncMock(return_value={"name": "Mika"})
        with mock.patch.object(server, "Session", side_effect=make), mock.patch.object(server, "full_config", fake_config):
            with self.assertRaises(WebSocketDisconnect):                       # sin token, no
                with self.phone().websocket_connect(f"ws://{PC_IP}:8299/ws") as ws:
                    ws.receive_json()
            with self.phone().websocket_connect(f"ws://{PC_IP}:8299/ws?pair={TOKEN}") as ws:
                self.assertEqual(ws.receive_json()["type"], "hello")
            pc = TestClient(server.app, base_url="http://127.0.0.1:8299", client=LOCAL)
            with pc.websocket_connect("ws://127.0.0.1:8299/ws") as ws:
                self.assertEqual(ws.receive_json()["type"], "hello")
        self.assertEqual([s.remote for s in made], [True, False])
        with mock.patch.object(actions, "config", return_value={"enabled": True}), \
                mock.patch.object(llm, "can_act", return_value=True):
            self.assertFalse(made[0].actions_on())
            self.assertTrue(made[1].actions_on())

    def test_el_interruptor_abre_y_cierra_la_escucha(self):
        pc = TestClient(server.app, base_url="http://127.0.0.1:8299", client=LOCAL)
        origin = {"Origin": "http://127.0.0.1:8299"}
        with mock.patch.object(pairing, "start_lan", mock.AsyncMock()) as start, \
                mock.patch.object(pairing, "stop_lan", mock.AsyncMock()) as stop:
            asyncio.run(server._lan_sync())                       # al arrancar, con En Casa apagado: nada en la red
            start.assert_not_awaited()
            r = pc.post("/api/pairing", json={"enabled": True}, headers=origin)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["enabled"])
            start.assert_awaited_with(server.app, server.settings.port)
            stop.reset_mock()
            before = pairing._cfg()["token"]
            r = pc.post("/api/pairing", json={"enabled": True, "rotate": True}, headers=origin)
            self.assertNotEqual(pairing._cfg()["token"], before)
            stop.assert_awaited()                                  # renovar corta a quien ya estaba dentro
            r = pc.post("/api/pairing", json={"enabled": False}, headers=origin)
            self.assertFalse(r.json()["enabled"])

    def test_sesion_remota_no_carga_mcp(self):
        s = session.Session.__new__(session.Session)
        s.remote, s._mcp_tools = True, [{"name": "x"}]
        with mock.patch("companion.mcp_client.list_tools", side_effect=AssertionError("no debe preguntar")):
            asyncio.run(s.load_mcp())
        self.assertEqual(s._mcp_tools, [])


class Escucha(unittest.TestCase):
    """La segunda escucha (en la prueba, en 127.0.0.1: en una IP de la red despertaría al cortafuegos de Windows)."""

    def test_se_abre_y_se_cierra(self):
        port = free_port()

        async def run():
            await pairing.start_lan(server.app, port, ips=["127.0.0.1"], tls=False)
            self.assertTrue(pairing.listening())
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as c:
                self.assertEqual((await c.get("/api/models")).status_code, 200)
            await pairing.stop_lan()
            self.assertFalse(pairing.listening())
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as c:
                with self.assertRaises(httpx.ConnectError):
                    await c.get("/api/models")

        asyncio.run(run())

    def test_por_https_con_certificado_propio(self):
        """El navegador del teléfono solo da el micrófono en una página segura: la escucha en la red va por https."""
        port = free_port()

        async def run():
            await pairing.start_lan(server.app, port, ips=["127.0.0.1"])
            try:
                self.assertTrue(pairing.listening())
                self.assertTrue(pairing._lan["secure"])
                self.assertRegex(pairing._lan["fingerprint"], r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
                cert, _ = pairing._tls_paths()
                trust = ssl.create_default_context(cafile=str(cert))     # el certificado vale para esa IP
                async with httpx.AsyncClient(base_url=f"https://127.0.0.1:{port}", verify=trust, trust_env=False) as c:
                    self.assertEqual((await c.get("/api/models")).status_code, 200)
                async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as c:
                    with self.assertRaises(httpx.HTTPError):                # sin cifrar ya no entra
                        await c.get("/api/models")
            finally:
                await pairing.stop_lan()

        asyncio.run(run())

    def test_el_certificado_se_reutiliza_y_se_renueva(self):
        a = pairing.tls_cert(["127.0.0.1"])
        b = pairing.tls_cert(["127.0.0.1"])
        self.assertEqual(a["fingerprint"], b["fingerprint"])            # el teléfono no vuelve a avisar sin motivo
        c = pairing.tls_cert(["127.0.0.1", PC_IP])                       # IP nueva: certificado nuevo que la incluye
        self.assertNotEqual(a["fingerprint"], c["fingerprint"])
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(c["cert"].read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        self.assertEqual({str(ip) for ip in san.get_values_for_type(x509.IPAddress)}, {"127.0.0.1", PC_IP})
        self.assertLessEqual((cert.not_valid_after_utc - cert.not_valid_before_utc).days, pairing.TLS_DAYS)

    def test_sin_cryptography_va_por_http(self):
        port = free_port()

        async def run():
            with mock.patch.dict(sys.modules, {"cryptography": None}):
                self.assertIsNone(pairing.tls_cert(["127.0.0.1"]))
                await pairing.start_lan(server.app, port, ips=["127.0.0.1"])
            try:
                self.assertTrue(pairing.listening())
                self.assertFalse(pairing._lan["secure"])
                async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as c:
                    self.assertEqual((await c.get("/api/models")).status_code, 200)
            finally:
                await pairing.stop_lan()

        asyncio.run(run())

    def test_puerto_ocupado_lo_dice(self):
        port = free_port()
        busy = socket.socket()
        busy.bind(("127.0.0.1", port))
        busy.listen()
        self.addCleanup(busy.close)

        async def run():
            await pairing.start_lan(server.app, port, ips=["127.0.0.1"])
            self.assertFalse(pairing.listening())
            self.assertIn("127.0.0.1", pairing._lan["error"])
            await pairing.stop_lan()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
