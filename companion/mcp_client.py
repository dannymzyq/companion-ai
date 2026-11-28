"""Puente opcional y seguro hacia servidores locales Model Context Protocol (MCP, N-10).

Reglas de seguridad estrictas (CLAUDE.md):
- Apagado por defecto (`enabled=False`).
- Solo acepta direcciones HTTP locales (`http://127.0.0.1:...` o `http://localhost:...`), nunca el puerto del propio
  companion ni el de su servidor de voz, y no sigue redirecciones.
- Las herramientas MCP NUNCA se invocan en saludos, miradas en vivo ni temporizadores: solo en turnos con mensaje del
  propio usuario.
- Un servidor nuevo NO es de solo lectura: sus herramientas van con tarjeta. Solo si el usuario lo marca `read_only=True`
  van sin ella (la anotación `readOnlyHint` del propio servidor no cuenta); cualquier otra exige SIEMPRE tarjeta de confirmación explícita (`card=True`), incluso con «Acceso total».

Protocolo (transporte «Streamable HTTP», especificación 2025-06-18; 27 nov 2026): antes se mandaba `tools/list` a
secas y los servidores hechos con los SDK oficiales lo rechazaban. Ahora:
- Cada servidor se saluda primero: `initialize` y después la notificación `notifications/initialized`.
- Todas las peticiones llevan `Accept: application/json, text/event-stream`; desde el saludo, también
  `MCP-Protocol-Version` y, si el servidor la dio, la sesión (`Mcp-Session-Id`).
- La respuesta puede llegar como JSON o como un flujo SSE: se lee hasta el mensaje con el mismo `id` (1 MB como mucho).
- Si el servidor olvidó la sesión (se reinició: 404), se saluda otra vez, una sola vez.
"""
import itertools
import json
import logging
import re
import uuid
from urllib.parse import urlparse

import httpx

from . import state
from .config import settings

log = logging.getLogger("companion.mcp")
MAX_SERVERS = 8
PROTOCOL = "2025-06-18"
KNOWN_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
MAX_BODY = 1 << 20                           # una respuesta de más de 1 MB no es de una herramienta para charlar
ACCEPT = "application/json, text/event-stream"
_SESSION_ID = re.compile(r"[\x21-\x7e]{1,200}")   # la especificación: solo caracteres ASCII visibles

_sessions: dict[str, dict] = {}              # dirección del servidor → {"sid": str | None, "version": str}
_ids = itertools.count(1)
_transport: httpx.AsyncBaseTransport | None = None   # pruebas: un servidor MCP falso (httpx.MockTransport)


class McpError(Exception):
    pass


class _Expired(Exception):
    """El servidor ya no conoce la sesión: hay que saludar otra vez."""


def config() -> dict:
    raw = state.load().get("mcp") or {}
    servers = []
    for s in (raw.get("servers") or [])[:MAX_SERVERS]:
        if isinstance(s, dict) and s.get("id") and s.get("url"):
            servers.append({
                "id": str(s["id"])[:24],
                "name": str(s.get("name") or s["id"])[:40],
                "url": str(s["url"])[:200],
                "read_only": bool(s.get("read_only", False)),
            })
    return {"enabled": bool(raw.get("enabled", False)), "servers": servers}


def _own_ports() -> set[int]:
    """El propio companion y su servidor de voz: una «herramienta» ahí podría borrar datos o tocar ajustes."""
    ports = {settings.port}
    try:
        tts_port = urlparse(settings.tts_url).port
    except ValueError:
        tts_port = None
    if tts_port:
        ports.add(tts_port)
    return ports


def _valid_local_url(url: str) -> str:
    u = (url or "").strip()
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("Por seguridad, los servidores MCP deben ser locales (http://127.0.0.1 o http://localhost).")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise ValueError("La dirección del servidor MCP no tiene un puerto válido.") from None
    if port in _own_ports():
        raise ValueError("Esa dirección es la del propio companion, no la de un servidor MCP.")
    return u


def save(*, enabled: bool | None = None, add: dict | None = None, remove_id: str | None = None) -> dict:
    cur = config()
    if enabled is not None:
        cur["enabled"] = bool(enabled)
    if remove_id:
        cur["servers"] = [s for s in cur["servers"] if s["id"] != remove_id]
    if isinstance(add, dict):
        name = re.sub(r"[^\w .+-]+", "", str(add.get("name") or "").strip())[:40]
        if not name:
            raise ValueError("Escribe un nombre para el servidor MCP.")
        url = _valid_local_url(str(add.get("url") or ""))
        if len(cur["servers"]) >= MAX_SERVERS:
            raise ValueError(f"Como máximo se permiten {MAX_SERVERS} servidores MCP.")
        sid = "mcp_" + uuid.uuid4().hex[:8]
        cur["servers"].append({"id": sid, "name": name, "url": url, "read_only": bool(add.get("read_only", False))})
    state.save(mcp=cur)
    keep = {s["url"] for s in cur["servers"]}
    for url in [u for u in _sessions if u not in keep]:      # servidores quitados: se olvida su sesión
        _sessions.pop(url, None)
    return cur


# ---------------------------------------------------------------- protocolo
def _client(timeout: float) -> httpx.AsyncClient:
    # Sin proxies del sistema (es tráfico local) y sin seguir redirecciones (podrían llevar fuera de esta PC).
    return httpx.AsyncClient(timeout=timeout, transport=_transport, trust_env=False, follow_redirects=False)


def _headers(st: dict) -> dict:
    h = {"Accept": ACCEPT, "Content-Type": "application/json"}
    if st.get("sid"):
        h["Mcp-Session-Id"] = st["sid"]
    if st.get("version"):
        h["MCP-Protocol-Version"] = st["version"]
    return h


async def _read_json(r: httpx.Response) -> dict:
    buf = bytearray()
    async for chunk in r.aiter_bytes():
        buf += chunk
        if len(buf) > MAX_BODY:
            raise McpError("La respuesta del servidor MCP es demasiado grande.")
    try:
        msg = json.loads(bytes(buf).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise McpError("El servidor MCP no respondió con JSON.") from None
    if not isinstance(msg, dict):
        raise McpError("El servidor MCP respondió algo que no es un mensaje JSON-RPC.")
    return msg


def _event(lines: list[str], rid: int) -> dict | None:
    """Un evento SSE ya completo: el mensaje JSON-RPC si es la respuesta a `rid`."""
    if not lines:
        return None
    try:
        msg = json.loads("\n".join(lines))
    except ValueError:
        return None
    if isinstance(msg, dict) and msg.get("id") == rid and ("result" in msg or "error" in msg):
        return msg
    return None                                  # una notificación o una petición del servidor: no se atienden


async def _read_sse(r: httpx.Response, rid: int) -> dict:
    data: list[str] = []
    size = 0
    async for line in r.aiter_lines():
        size += len(line) + 1
        if size > MAX_BODY:
            raise McpError("La respuesta del servidor MCP es demasiado grande.")
        if line == "":                           # fin de un evento
            msg = _event(data, rid)
            if msg:
                return msg
            data = []
            continue
        if line.startswith(":"):                 # comentario (latidos)
            continue
        field, _, value = line.partition(":")
        if field == "data":
            data.append(value[1:] if value.startswith(" ") else value)
    msg = _event(data, rid)
    if msg:
        return msg
    raise McpError("El servidor MCP cerró la respuesta sin contestar.")


async def _rpc(client: httpx.AsyncClient, url: str, st: dict, method: str, params: dict | None) -> dict:
    """Una petición JSON-RPC; devuelve el mensaje de respuesta (con `result` o `error`)."""
    rid = next(_ids)
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    async with client.stream("POST", url, json=body, headers=_headers(st)) as r:
        if st.get("sid") and r.status_code in (400, 404):
            raise _Expired()
        if r.status_code != 200:
            raise McpError(f"El servidor MCP respondió {r.status_code}.")
        if method == "initialize":
            sid = (r.headers.get("mcp-session-id") or "").strip()
            st["sid"] = sid if _SESSION_ID.fullmatch(sid) else None
        kind = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        return await (_read_sse(r, rid) if kind == "text/event-stream" else _read_json(r))


async def _notify(client: httpx.AsyncClient, url: str, st: dict, method: str) -> None:
    r = await client.post(url, json={"jsonrpc": "2.0", "method": method}, headers=_headers(st))
    if r.status_code not in (200, 202, 204):
        raise McpError(f"El servidor MCP rechazó «{method}» ({r.status_code}).")


async def _connect(client: httpx.AsyncClient, url: str) -> dict:
    st: dict = {"sid": None, "version": None}
    from .update import current
    msg = await _rpc(client, url, st, "initialize", {
        "protocolVersion": PROTOCOL, "capabilities": {},
        "clientInfo": {"name": "Companion", "version": current()},
    })
    if msg.get("error"):
        err = msg["error"].get("message") if isinstance(msg["error"], dict) else msg["error"]
        raise McpError(f"El servidor MCP no aceptó el saludo: {str(err)[:200]}")
    version = str((msg.get("result") or {}).get("protocolVersion") or "")
    if version not in KNOWN_PROTOCOLS:
        raise McpError(f"El servidor MCP usa una versión del protocolo que no conozco ({version[:20] or 'ninguna'}).")
    st["version"] = version
    await _notify(client, url, st, "notifications/initialized")
    return st


async def _call(srv: dict, method: str, params: dict | None, *, timeout: float) -> dict:
    url = _valid_local_url(srv["url"])
    async with _client(timeout) as client:
        for attempt in (1, 2):
            st = _sessions.get(url)
            if st is None:
                st = await _connect(client, url)
                _sessions[url] = st
            try:
                return await _rpc(client, url, st, method, params)
            except _Expired:
                _sessions.pop(url, None)
                if attempt == 2:
                    raise McpError("El servidor MCP cerró la sesión.") from None
    raise McpError("No pude hablar con el servidor MCP.")


def _why(e: Exception) -> str:
    if isinstance(e, (McpError, ValueError)):
        return str(e)
    if isinstance(e, httpx.ConnectError):
        return "No responde (¿está encendido?)."
    if isinstance(e, httpx.TimeoutException):
        return "Tardó demasiado en responder."
    return f"Falló ({type(e).__name__})."


async def list_tools(errors: dict | None = None) -> list[dict]:
    """`tools/list` en cada servidor activo. `errors` recoge, por servidor, por qué no respondió (para Ajustes)."""
    cfg = config()
    if not cfg["enabled"] or not cfg["servers"]:
        return []
    out: list[dict] = []
    for srv in cfg["servers"]:
        try:
            msg = await _call(srv, "tools/list", {}, timeout=5.0)
            if msg.get("error"):
                raise McpError("El servidor MCP no quiso dar sus herramientas.")
        except (McpError, httpx.HTTPError, ValueError) as e:
            if errors is not None:
                errors[srv["id"]] = _why(e)
            log.info("MCP: el servidor %s no dio sus herramientas (%s)", srv["id"], type(e).__name__)
            continue
        tools = (msg.get("result") or {}).get("tools") or []
        for t in tools[:15] if isinstance(tools, list) else []:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            schema = t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {}
            props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            out.append({
                "server_id": srv["id"],
                "server_name": srv["name"],
                "url": srv["url"],
                "name": str(t["name"])[:60],
                "description": str(t.get("description") or "")[:200],
                "args": [str(k)[:30] for k in list(props)[:8]],
                # Lo que el propio servidor diga de sí mismo (readOnlyHint) no cuenta: solo lo que marcó el usuario.
                "read_only": bool(srv["read_only"]),
            })
    return out


async def call_tool(server_id: str, tool_name: str, arguments: dict | None = None) -> tuple[bool, str, bool]:
    """Ejecuta `tools/call` en un servidor MCP registrado. Devuelve `(ok, texto, read_only)`."""
    cfg = config()
    if not cfg["enabled"]:
        raise ValueError("El conector MCP está desactivado en Ajustes.")
    srv = next((s for s in cfg["servers"] if s["id"] == server_id), None)
    if not srv:
        raise ValueError("Servidor MCP no encontrado.")
    try:
        msg = await _call(srv, "tools/call", {"name": tool_name, "arguments": arguments or {}}, timeout=30.0)
    except (McpError, httpx.HTTPError, ValueError) as e:
        return False, _why(e), srv["read_only"]
    if msg.get("error"):
        err = msg["error"].get("message") if isinstance(msg["error"], dict) else str(msg["error"])
        return False, str(err)[:300], srv["read_only"]
    res = msg.get("result") or {}
    parts = [str(c.get("text") or "") for c in (res.get("content") or ()) if isinstance(c, dict) and c.get("text")]
    text = "\n".join(parts).strip()[:2000] or str(res)[:500]
    return not bool(res.get("isError")), text, srv["read_only"]
