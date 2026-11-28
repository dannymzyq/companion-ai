"""Cliente MCP (27 nov 2026): saludo, sesión y respuestas SSE como pide la especificación 2025-06-18.

Antes se mandaba `tools/list` a secas: un servidor hecho con los SDK oficiales lo rechazaba (sin `initialize`, sin la
cabecera Accept doble, sin la sesión). `ServidorFalso` exige lo mismo que ellos.
"""
import asyncio
import json
import unittest
from unittest import mock

import httpx

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)
from companion import mcp_client, prompt, session, state
from companion.config import settings

URL = "http://127.0.0.1:8765/mcp"


class ServidorFalso:
    def __init__(self, version: str = "2025-06-18"):
        self.version = version
        self.sid = "sesion-1"
        self.ready = False
        self.inits = 0
        self.calls: list[str] = []
        self.restarted = False                 # se reinició: ya no conoce la sesión anterior

    def __call__(self, request: httpx.Request) -> httpx.Response:
        accept = request.headers.get("accept", "")
        if "application/json" not in accept or "text/event-stream" not in accept:
            return httpx.Response(406, text="Not Acceptable")
        msg = json.loads(request.content)
        method = msg.get("method")
        self.calls.append(method)
        if method == "initialize":
            self.inits += 1
            if self.restarted:
                self.sid, self.restarted = f"sesion-{self.inits}", False
            self.ready = False
            return httpx.Response(200, headers={"Mcp-Session-Id": self.sid}, json={
                "jsonrpc": "2.0", "id": msg["id"],
                "result": {"protocolVersion": self.version, "capabilities": {"tools": {}},
                           "serverInfo": {"name": "falso", "version": "1"}}})
        sid = request.headers.get("mcp-session-id")
        if not sid:
            return httpx.Response(400, text="Bad Request: Missing session ID")
        if sid != self.sid or self.restarted:
            return httpx.Response(404, text="Session not found")
        if request.headers.get("mcp-protocol-version") != self.version:
            return httpx.Response(400, text="Bad MCP-Protocol-Version")
        if method == "notifications/initialized":
            self.ready = True
            return httpx.Response(202)
        if not self.ready:
            return httpx.Response(400, text="Not initialized")
        if method == "tools/list":
            result = {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [{
                "name": "buscar_nota", "description": "Busca una nota\npor texto",
                "inputSchema": {"type": "object", "properties": {"texto": {"type": "string"}}}}]}}
            body = (": latido\n\n"
                    'data: {"jsonrpc":"2.0","method":"notifications/message","params":{"level":"info","data":"hola"}}\n\n'
                    f"event: message\ndata: {json.dumps(result)}\n\n")
            return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})
        if method == "tools/call":
            texto = msg["params"]["arguments"].get("texto")
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"],
                                             "result": {"content": [{"type": "text", "text": f"nota: {texto}"}]}})
        return httpx.Response(400)


class ClienteMcp(unittest.TestCase):
    def setUp(self):
        mcp_client._sessions.clear()
        self.server = ServidorFalso()
        p = mock.patch.object(mcp_client, "_transport", httpx.MockTransport(self.server))
        p.start()
        self.addCleanup(p.stop)
        state.save(mcp={})
        self.srv = mcp_client.save(enabled=True, add={"name": "notas", "url": URL})["servers"][0]

    def tearDown(self):
        state.save(mcp={})
        mcp_client._sessions.clear()

    def test_saludo_sesion_y_respuesta_sse(self):
        errors: dict = {}
        tools = asyncio.run(mcp_client.list_tools(errors))
        self.assertEqual(errors, {})
        self.assertEqual([t["name"] for t in tools], ["buscar_nota"])
        self.assertEqual(tools[0]["args"], ["texto"])
        self.assertFalse(tools[0]["read_only"])
        self.assertEqual(self.server.calls, ["initialize", "notifications/initialized", "tools/list"])

    def test_llamar_reutiliza_la_sesion(self):
        asyncio.run(mcp_client.list_tools())
        ok, text, ro = asyncio.run(mcp_client.call_tool(self.srv["id"], "buscar_nota", {"texto": "café"}))
        self.assertTrue(ok)
        self.assertEqual(text, "nota: café")
        self.assertFalse(ro)
        self.assertEqual(self.server.inits, 1)

    def test_servidor_reiniciado_saluda_otra_vez(self):
        asyncio.run(mcp_client.list_tools())
        self.server.restarted = True
        ok, text, _ = asyncio.run(mcp_client.call_tool(self.srv["id"], "buscar_nota", {"texto": "pan"}))
        self.assertTrue(ok, text)
        self.assertEqual(self.server.inits, 2)

    def test_version_desconocida_o_servidor_apagado(self):
        self.server.version = "1999-01-01"
        errors: dict = {}
        self.assertEqual(asyncio.run(mcp_client.list_tools(errors)), [])
        self.assertIn("versión", errors[self.srv["id"]])
        mcp_client._sessions.clear()

        def apagado(request):
            raise httpx.ConnectError("refused", request=request)

        with mock.patch.object(mcp_client, "_transport", httpx.MockTransport(apagado)):
            errors = {}
            asyncio.run(mcp_client.list_tools(errors))
            self.assertIn("No responde", errors[self.srv["id"]])
            ok, text, _ = asyncio.run(mcp_client.call_tool(self.srv["id"], "buscar_nota", {}))
            self.assertFalse(ok)

    def test_nunca_el_propio_companion(self):
        for url in ("http://127.0.0.1:8299/api/setup/reset", "http://localhost:9/mcp"):   # el servidor y la voz
            with self.assertRaises(ValueError):
                mcp_client.save(add={"name": "trampa", "url": url})

    def test_quitar_un_servidor_olvida_su_sesion(self):
        asyncio.run(mcp_client.list_tools())
        self.assertIn(URL, mcp_client._sessions)
        mcp_client.save(remove_id=self.srv["id"])
        self.assertNotIn(URL, mcp_client._sessions)


class HerramientasEnElPrompt(unittest.TestCase):
    TOOLS = [{"server_id": "mcp_1", "name": "buscar_nota", "description": "Busca\nuna nota", "args": ["texto"]}]

    def test_en_vivo_tambien_las_ve(self):
        p = prompt.load_persona(settings.persona_path)
        txt = prompt.build_system_prompt(p, user_name="Ana", memories=[], adult=False, actions=True, live=True,
                                         mcp_tools=self.TOOLS)
        self.assertIn("mcp_1:buscar_nota(texto)", txt)
        self.assertIn("accion='mcp'", txt)
        sin = prompt.build_system_prompt(p, user_name="Ana", memories=[], adult=False, actions=False, live=True,
                                         mcp_tools=self.TOOLS)
        self.assertNotIn("buscar_nota", sin)

    def test_descripcion_en_una_linea(self):
        blk = prompt.mcp_block("Ana", self.TOOLS)
        self.assertIn("mcp_1:buscar_nota(texto) — Busca una nota", blk)

    def test_la_sesion_las_carga_fuera_de_en_vivo(self):
        s = session.Session.__new__(session.Session)
        s._mcp_tools = []
        with mock.patch.object(mcp_client, "config", return_value={"enabled": True, "servers": [{}]}), \
                mock.patch.object(mcp_client, "list_tools", mock.AsyncMock(return_value=self.TOOLS)):
            asyncio.run(s.load_mcp())
        self.assertEqual(s._mcp_tools, self.TOOLS)


if __name__ == "__main__":
    unittest.main()
