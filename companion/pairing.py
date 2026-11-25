"""Portabilidad «Mochila de Companion» (.companion.json) y Modo «En Casa» (emparejamiento LAN con móvil, N-04).

Seguridad estricta:
- La mochila exportada NUNCA incluye claves de API ni secretos cifrados.
- El emparejamiento LAN está APAGADO por defecto (`enabled=False`). Mientras está apagado, el servidor mantiene el
  bloqueo 100 % exclusivo a `127.0.0.1` / `localhost` contra DNS Rebinding.
- Cuando el usuario lo enciende explícitamente, solo se aceptan conexiones fuera de localhost si provienen de una IP
  privada/Tailscale Y presentan el token aleatorio de 256 bits válido (`Authorization: Bearer <token>`, `?pair=<token>`
  o cookie `companion_pair`).
"""
import hmac
import ipaddress
import secrets
import socket
import time

from . import personality, profile, state, store
from .text_utils import is_private_fact

BACKPACK_FORMAT = "companion-backpack-v1"
COOKIE_NAME = "companion_pair"


def export_backpack() -> dict:
    """Exporta perfil público, personalidades propias, recuerdos (con fijados), resúmenes y presets. Cero claves."""
    items = store.memory_items(limit=500)
    sums = store.summaries(limit=200)
    pers = state.load().get("personality") or {}
    return {
        "format": BACKPACK_FORMAT,
        "exported_at": time.time(),
        "profile": profile.get(),
        "morning_briefing": profile.morning_briefing(),
        "personality": {
            "selected": pers.get("selected") or personality.active_id(),
            "custom": list((pers.get("custom") or {}).values()) if isinstance(pers.get("custom"), dict) else list(pers.get("custom") or []),
        },
        "memories": [{"fact": it["fact"], "ts": it["ts"], "pinned": it["pinned"]} for it in items],
        "summaries": [{"text": text, "ts": ts} for text, ts in sums],
        "presets": profile.list_presets(),
    }


def import_backpack(data: dict) -> dict:
    """Importa y fusiona una mochila sin tocar claves ni borrar lo que el usuario ya tenía."""
    if not isinstance(data, dict) or data.get("format") != BACKPACK_FORMAT:
        raise ValueError("El archivo no es una mochila válida de Companion.")
    added_mem = 0
    added_sum = 0
    prof = data.get("profile")
    if isinstance(prof, dict) and prof.get("name") and prof.get("birth_year"):
        try:
            state.save(profile=profile.clean_profile(prof))
        except ValueError:
            pass
    if isinstance(data.get("morning_briefing"), bool):
        state.save(morning_briefing=bool(data["morning_briefing"]))
    pers = data.get("personality")
    if isinstance(pers, dict):
        for custom in pers.get("custom") or ():
            if isinstance(custom, dict) and custom.get("name"):
                try:
                    personality.save_custom(custom)
                except ValueError:
                    continue
        sel = pers.get("selected")
        if isinstance(sel, str) and sel:
            try:
                personality.select(sel)
            except ValueError:
                pass
    for m in (data.get("memories") or ())[:500]:
        fact = str(m.get("fact") if isinstance(m, dict) else m or "").strip()
        pinned = bool(m.get("pinned")) if isinstance(m, dict) else False
        if 8 <= len(fact) <= 200 and not is_private_fact(fact):
            if store.add_memory(fact, pinned=pinned):
                added_mem += 1
    existing_sums = {t.strip() for t, _ in store.summaries(limit=500)}
    for s in (data.get("summaries") or ())[:200]:
        if isinstance(s, dict):
            txt = str(s.get("text") or "").strip()[:900]
            ts = float(s.get("ts") or time.time())
            if len(txt) > 20 and txt not in existing_sums and not is_private_fact(txt):
                store.add_summary(txt, 0, 0, ts)
                existing_sums.add(txt)
                added_sum += 1
    for p in (data.get("presets") or ())[:30]:
        if isinstance(p, dict) and p.get("name"):
            try:
                profile.save_preset(p)
            except ValueError:
                continue
    profile.apply()
    return {"ok": True, "imported_memories": added_mem, "imported_summaries": added_sum}


# ---------------------------------------------------------------- Modo «En Casa» (LAN Pairing)
def _cfg() -> dict:
    raw = state.load().get("pairing") or {}
    return {"enabled": bool(raw.get("enabled", False)), "token": str(raw.get("token") or "")}


def enabled() -> bool:
    c = _cfg()
    return c["enabled"] and len(c["token"]) >= 32


def local_ips() -> list[str]:
    ips: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            addr = ipaddress.ip_address(ip)
            if (addr.is_private or ip.startswith("100.")) and not addr.is_loopback and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def status(port: int, *, include_secret: bool = False) -> dict:
    c = _cfg()
    urls = [f"http://{ip}:{port}" for ip in local_ips()]
    out = {
        "enabled": c["enabled"] and bool(c["token"]),
        "urls": urls,
        "has_token": bool(c["token"]),
    }
    if include_secret and c["enabled"] and c["token"]:
        out["token"] = c["token"]
        out["pair_urls"] = [f"{u}/?pair={c['token']}" for u in urls]
    return out


def configure(*, on: bool, rotate: bool = False, port: int = 8200) -> dict:
    c = _cfg()
    tok = c["token"]
    if on and (rotate or len(tok) < 32):
        tok = secrets.token_urlsafe(32)
    if not on:
        state.save(pairing={"enabled": False, "token": tok})
    else:
        state.save(pairing={"enabled": True, "token": tok})
    return status(port, include_secret=True)


def is_private_client(host: str | None) -> bool:
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host.split("%")[0])
        # RFC1918 privada o rango CGNAT 100.64.0.0/10 (Tailscale)
        return addr.is_loopback or addr.is_private or (addr in ipaddress.ip_network("100.64.0.0/10"))
    except ValueError:
        return False


def valid_token(candidate: str | None) -> bool:
    c = _cfg()
    if not c["enabled"] or len(c["token"]) < 32 or not candidate:
        return False
    return hmac.compare_digest(c["token"], candidate.strip())


def extract_token(headers, query_params=None, cookies=None) -> str:
    auth = (headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if cookies and cookies.get(COOKIE_NAME):
        return str(cookies.get(COOKIE_NAME))
    if query_params and query_params.get("pair"):
        return str(query_params.get("pair"))
    return ""
