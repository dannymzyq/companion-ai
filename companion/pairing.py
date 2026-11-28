"""Portabilidad «Mochila de Companion» (.companion.json) y Modo «En Casa» (emparejamiento LAN con móvil, N-04).

Seguridad estricta:
- La mochila exportada NUNCA incluye claves de API ni secretos cifrados.
- El emparejamiento LAN está APAGADO por defecto (`enabled=False`). Mientras está apagado, el servidor solo escucha
  en `127.0.0.1` y solo atiende a esta misma PC.
- Al encenderlo se abre una segunda escucha en las IP privadas de la PC (`start_lan`, mismo puerto); al apagarlo se
  cierra. Desde la red solo pasa quien llega desde una IP privada o de Tailscale, nombra a la PC por una de sus IP y
  presenta el token aleatorio de 256 bits (`Authorization: Bearer <token>`, `?pair=<token>` o cookie `companion_pair`).
- Si una petición es de esta PC lo decide la dirección de quien llama (`is_loopback`), nunca la cabecera Host, que la
  escribe el cliente (27 nov 2026: con `Host: localhost` un equipo de la red se saltaba el token).
"""
import asyncio
import contextlib
import hmac
import ipaddress
import logging
import secrets
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn

from . import personality, profile, state, store
from .config import settings
from .text_utils import is_private_fact

log = logging.getLogger("companion.pairing")
BACKPACK_FORMAT = "companion-backpack-v1"
COOKIE_NAME = "companion_pair"
CGNAT = ipaddress.ip_network("100.64.0.0/10")      # Tailscale y otras VPN de malla


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


def _addr(host: str | None):
    """La dirección IP de `host` (sin zona IPv6 y con las IPv4 metidas en IPv6 ya sacadas), o None."""
    if not host:
        return None
    try:
        addr = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return None
    return addr.ipv4_mapped if getattr(addr, "ipv4_mapped", None) else addr


def is_loopback(host: str | None) -> bool:
    """¿La petición sale de esta misma PC? (127.0.0.0/8 o ::1). Un nombre que no es una IP, nunca."""
    addr = _addr(host)
    return bool(addr and addr.is_loopback)


def local_ips() -> list[str]:
    """Las IP de esta PC en una red privada (Wi-Fi, cable) o en Tailscale."""
    ips: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            addr = ipaddress.ip_address(ip)
            if ((addr.is_private and not addr.is_link_local) or addr in CGNAT) and not addr.is_loopback and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def lan_hosts() -> set[str]:
    """Nombres con los que un teléfono puede llamar a esta PC (la cabecera Host): sus IP de la red."""
    return set(local_ips()) | set(_lan["ips"])


def status(port: int, *, include_secret: bool = False, wide: bool = False) -> dict:
    """`wide`: el servidor principal ya escucha en toda la red (HOST=0.0.0.0 en .env), sin escucha aparte."""
    c = _cfg()
    on = c["enabled"] and bool(c["token"])
    ips = local_ips() if wide else (list(_lan["ips"]) if listening() else [])
    secure = bool(ips) and not wide and _lan["secure"]
    urls = [f"{'https' if secure else 'http'}://{ip}:{port}" for ip in ips]
    out = {
        "enabled": on,
        "listening": bool(ips),
        "secure": secure,
        "fingerprint": _lan["fingerprint"] if secure else "",
        "error": _lan["error"] if on else "",
        "urls": urls,
        "has_token": bool(c["token"]),
    }
    if include_secret and on and urls:
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
    """RFC1918 privada, rango CGNAT 100.64.0.0/10 (Tailscale) o esta misma PC."""
    addr = _addr(host)
    return bool(addr and (addr.is_loopback or addr.is_private or (addr.version == 4 and addr in CGNAT)))


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


# ---------------------------------------------------------------- certificado propio (https en la red)
TLS_DAYS = 397                    # lo máximo que Safari acepta para un certificado de servidor


def _tls_paths() -> tuple[Path, Path]:
    folder = settings.data_dir / "en_casa"
    return folder / "cert.pem", folder / "key.pem"


def tls_cert(ips: list[str]) -> dict | None:
    """Certificado propio de la PC para sus IP de la red: el navegador del teléfono solo da el micrófono en una página
    segura (https). Se reutiliza mientras cubra esas IP y le queden más de 30 días; si no, se hace otro.
    None si falta el paquete `cryptography` (entonces En Casa va por http, sin micrófono en el teléfono)."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError:
        return None
    want = sorted({ip for ip in ips if _addr(ip)})
    if not want:
        return None
    cert_p, key_p = _tls_paths()
    now = datetime.now(timezone.utc)

    def done(cert) -> dict:
        return {"cert": cert_p, "key": key_p, "fingerprint": cert.fingerprint(hashes.SHA256()).hex(":").upper()}

    if cert_p.exists() and key_p.exists():
        try:
            cert = x509.load_pem_x509_certificate(cert_p.read_bytes())
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            have = {str(a) for a in san.get_values_for_type(x509.IPAddress)}
            if set(want) <= have and cert.not_valid_after_utc - now > timedelta(days=30):
                return done(cert)
        except (ValueError, OSError, x509.ExtensionNotFound):
            pass                                  # roto o de otra versión: se hace otro
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Companion - Modo En Casa")])
    usage = x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                          data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
                          encipher_only=False, decipher_only=False)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=TLS_DAYS))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip)) for ip in want]),
                           critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(usage, critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_p.parent.mkdir(parents=True, exist_ok=True)
    key_p.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    log.info("Modo En Casa: certificado nuevo para %d dirección/es de la red", len(want))
    return done(cert)


# ---------------------------------------------------------------- escucha en la red (solo con En Casa encendido)
# Un segundo servidor uvicorn en el mismo proceso y el mismo bucle, atado a las IP privadas de la PC. El principal sigue
# en 127.0.0.1: con En Casa apagado no hay nada escuchando en la red (ni aviso del cortafuegos de Windows).
_lan: dict = {"server": None, "task": None, "ips": [], "error": "", "secure": False, "fingerprint": ""}


class _LanServer(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self):
        """Las señales (Ctrl+C) son del servidor principal: este no las toca."""
        yield


def _socket(ip: str, port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):       # Windows: que ningún otro programa pueda escuchar en el mismo
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:                                            # Mac: poder volver a abrirla enseguida tras cerrarla
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((ip, port))
        s.setblocking(False)
    except OSError:
        s.close()
        raise
    return s


def listening() -> bool:
    task, server = _lan["task"], _lan["server"]
    return bool(task and not task.done() and server and server.started)


async def start_lan(app, port: int, ips: list[str] | None = None, *, tls: bool = True) -> None:
    """Abre la escucha en la red, por https si se puede. `ips` solo en las pruebas (127.0.0.1, que no despierta al
    cortafuegos)."""
    if _lan["task"] and not _lan["task"].done():
        return
    ips = local_ips() if ips is None else ips
    socks, bound, failed = [], [], []
    for ip in ips:
        try:
            socks.append(_socket(ip, port))
            bound.append(ip)
        except OSError as e:
            failed.append(f"{ip} ({e.strerror or type(e).__name__})")
    if not socks:
        _lan.update(server=None, task=None, ips=[], secure=False, fingerprint="",
                    error=("No encontré ninguna red Wi-Fi o por cable en esta PC." if not ips else
                           "No pude escuchar en la red: " + ", ".join(failed) + "."))
        log.warning("Modo En Casa: %s", _lan["error"])
        return
    cert = None
    if tls:
        try:
            cert = await asyncio.to_thread(tls_cert, bound)
        except Exception as e:  # noqa: BLE001  (sin certificado, por http: mejor que no abrir)
            log.warning("Modo En Casa: no pude preparar el certificado (%s); va por http", type(e).__name__)
    # Sin registro de accesos: las direcciones llevan el token (?pair=…). Sin cabeceras de proxy: la IP es la del socket.
    config = uvicorn.Config(app, lifespan="off", proxy_headers=False, log_config=None, access_log=False,
                            server_header=False, timeout_graceful_shutdown=3,
                            ssl_certfile=str(cert["cert"]) if cert else None, ssl_keyfile=str(cert["key"]) if cert else None)
    server = _LanServer(config)

    async def run():
        try:
            await server.serve(sockets=socks)
        except (Exception, SystemExit) as e:     # uvicorn sale con sys.exit si no puede arrancar: que no tumbe al principal
            _lan["error"] = f"La escucha en la red se cerró ({type(e).__name__})."
            log.warning("Modo En Casa: %s", _lan["error"])
        finally:
            for s in socks:
                with contextlib.suppress(OSError):
                    s.close()
            if _lan["server"] is server:
                _lan.update(server=None, task=None, ips=[], secure=False, fingerprint="")

    _lan.update(server=server, task=asyncio.create_task(run()), ips=bound, secure=bool(cert),
                fingerprint=cert["fingerprint"] if cert else "",
                error=("No pude escuchar en " + ", ".join(failed) + ".") if failed else "")
    for _ in range(100):                          # hasta 2 s a que acepte conexiones
        if server.started or _lan["task"] is None or _lan["task"].done():
            break
        await asyncio.sleep(0.02)
    if listening():
        log.info("Modo En Casa: escuchando en la red local (%d dirección/es, %s)", len(bound),
                 "https" if cert else "http")


async def stop_lan() -> None:
    """Cierra la escucha en la red y corta las conexiones que entraron por ella."""
    server, task = _lan["server"], _lan["task"]
    _lan.update(error="")
    if not server or not task:
        return
    server.should_exit = True
    try:
        await asyncio.wait_for(asyncio.shield(task), 6)
    except asyncio.TimeoutError:
        server.force_exit = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    _lan.update(server=None, task=None, ips=[], secure=False, fingerprint="")
