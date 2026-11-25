"""Puente opcional y seguro hacia servidores locales Model Context Protocol (MCP, N-10).

Reglas de seguridad estrictas (CLAUDE.md):
- Apagado por defecto (`enabled=False`).
- Solo acepta direcciones HTTP locales (`http://127.0.0.1:...` o `http://localhost:...`).
- Las herramientas MCP NUNCA se invocan en saludos, miradas en vivo ni temporizadores: solo en turnos con mensaje del
  propio usuario.
- Un servidor nuevo NO es de solo lectura: sus herramientas van con tarjeta. Solo si el usuario lo marca `read_only=True`
  van sin ella (la anotación `readOnlyHint` del propio servidor no cuenta); cualquier otra exige SIEMPRE tarjeta de confirmación explícita (`card=True`), incluso con «Acceso total».
"""
import re
import uuid
from urllib.parse import urlparse

import httpx

from . import state

MAX_SERVERS = 8


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


def _valid_local_url(url: str) -> str:
    u = (url or "").strip()
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("Por seguridad, los servidores MCP deben ser locales (http://127.0.0.1 o http://localhost).")
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
    return cur


async def list_tools() -> list[dict]:
    """Consulta `tools/list` por JSON-RPC 2.0 en los servidores MCP activos."""
    cfg = config()
    if not cfg["enabled"] or not cfg["servers"]:
        return []
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=3.0) as client:
        for srv in cfg["servers"]:
            try:
                r = await client.post(
                    srv["url"],
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                )
                if r.status_code != 200:
                    continue
                tools = (r.json().get("result") or {}).get("tools") or []
                for t in tools[:15]:
                    if not isinstance(t, dict) or not t.get("name"):
                        continue
                    # Lo que el propio servidor diga de sí mismo (readOnlyHint) no cuenta: solo lo que marcó el usuario.
                    ro = bool(srv["read_only"])
                    out.append({
                        "server_id": srv["id"],
                        "server_name": srv["name"],
                        "url": srv["url"],
                        "name": str(t["name"])[:60],
                        "description": str(t.get("description") or "")[:200],
                        "read_only": ro,
                    })
            except (httpx.HTTPError, ValueError):
                continue
    return out


async def call_tool(server_id: str, tool_name: str, arguments: dict | None = None) -> tuple[bool, str, bool]:
    """Ejecuta `tools/call` en un servidor MCP registrado. Devuelve `(ok, texto, read_only)`."""
    cfg = config()
    if not cfg["enabled"]:
        raise ValueError("El conector MCP está desactivado en Ajustes.")
    srv = next((s for s in cfg["servers"] if s["id"] == server_id), None)
    if not srv:
        raise ValueError("Servidor MCP no encontrado.")
    url = _valid_local_url(srv["url"])
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            url,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                  "params": {"name": tool_name, "arguments": arguments or {}}},
        )
        r.raise_for_status()
        body = r.json()
    if body.get("error"):
        err = body["error"].get("message") if isinstance(body["error"], dict) else str(body["error"])
        return False, str(err)[:300], srv["read_only"]
    res = body.get("result") or {}
    parts = [str(c.get("text") or "") for c in (res.get("content") or ()) if isinstance(c, dict) and c.get("text")]
    text = "\n".join(parts).strip()[:2000] or str(res)[:500]
    return not bool(res.get("isError")), text, srv["read_only"]
