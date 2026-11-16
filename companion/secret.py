"""Las claves de API guardadas en data/settings.json, cifradas con la protección del propio sistema.

Windows: DPAPI del usuario (CryptProtectData). Solo esta cuenta de Windows en esta PC puede descifrarla; copiar
settings.json a otra PC no se lleva la clave. Mac: el Llavero (servicio «Companion»). En otro sistema quedan
tal cual. Si una clave no se puede descifrar (otra PC, otro usuario), se trata como si no hubiera: se vuelve a pedir.
No importa nada del companion: los scripts de prueba lo usan para leer la clave sin imprimirla.
"""
import base64
import hashlib
import os
import subprocess
import sys

KEYS = (("cloud", "key"), ("ear", "groq_key"))     # dónde hay claves dentro de settings.json
_DPAPI, _KEYCHAIN = "dpapi:", "llavero:"
_SERVICE = "Companion"
_cache: dict[str, str] = {}                        # lo cifrado → la clave (el Llavero es un proceso por lectura)


def _blob(data: bytes):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    return Blob, Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    Blob, src, _keep = _blob(data)
    out = Blob()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    # CRYPTPROTECT_UI_FORBIDDEN (0x1): nunca una ventana de Windows
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(out)):
        raise OSError("DPAPI no pudo con la clave")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _security(*args: str) -> str:
    r = subprocess.run(["/usr/bin/security", *args], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise OSError(r.stderr.strip()[:200] or "el Llavero no respondió")
    return r.stdout.strip()


def protect(value: str, name: str, scope: str = "") -> str:
    """La clave lista para guardar. Si el sistema no puede protegerla, se guarda tal cual (como antes).
    `scope`: la carpeta de datos. En el Llavero cada carpeta tiene su entrada: el servidor de prueba (data\prueba)
    nunca pisa la clave de verdad."""
    if not value or value.startswith((_DPAPI, _KEYCHAIN)):
        return value
    try:
        if sys.platform == "win32":
            token = _DPAPI + base64.b64encode(_dpapi(value.encode("utf-8"), True)).decode("ascii")
        elif sys.platform == "darwin" and os.getenv("COMPANION_KEYCHAIN") != "0":     # las pruebas rápidas: 0
            account = f"{name}.{hashlib.sha256(scope.encode()).hexdigest()[:10]}"
            _security("add-generic-password", "-U", "-s", _SERVICE, "-a", account, "-w", value)
            token = _KEYCHAIN + account
        else:
            return value
    except Exception:  # noqa: BLE001
        return value
    _cache[token] = value
    return token


def unprotect(value: str) -> str:
    """La clave en claro ('' si no se puede descifrar aquí)."""
    if not isinstance(value, str) or not value.startswith((_DPAPI, _KEYCHAIN)):
        return value
    if value in _cache:
        return _cache[value]
    try:
        if value.startswith(_DPAPI):
            plain = _dpapi(base64.b64decode(value[len(_DPAPI):]), False).decode("utf-8") if sys.platform == "win32" else ""
        else:
            plain = _security("find-generic-password", "-s", _SERVICE, "-a", value[len(_KEYCHAIN):], "-w") \
                if sys.platform == "darwin" else ""
    except Exception:  # noqa: BLE001
        plain = ""
    _cache[value] = plain
    return plain


def _each(state: dict, fn) -> dict:  # fn(valor, nombre)
    out = dict(state)
    for section, field in KEYS:
        box = out.get(section)
        if isinstance(box, dict) and box.get(field):
            out[section] = {**box, field: fn(box[field], f"{section}.{field}")}
    return out


def hide(state: dict, scope: str = "") -> dict:
    """settings.json tal como se escribe: con las claves protegidas."""
    return _each(state, lambda v, name: protect(v, name, scope))


def reveal(state: dict) -> dict:
    """settings.json tal como lo usa el companion: con las claves en claro."""
    return _each(state, lambda v, _name: unprotect(v))


def has_plain(state: dict) -> bool:
    """¿Queda alguna clave sin proteger (guardada por una versión anterior)?"""
    return any(isinstance(state.get(s), dict) and isinstance(state[s].get(f), str) and state[s][f]
               and not state[s][f].startswith((_DPAPI, _KEYCHAIN)) for s, f in KEYS)
