"""Acciones en la PC que el personaje puede PEDIR, nunca hacer por su cuenta.

El modelo escribe al final de su respuesta una etiqueta como  [accion: abrir_app | Spotify].  El companion
la comprueba (acción del catálogo, datos válidos), la muestra en una tarjeta de permiso y solo la ejecuta si
el usuario la aprueba: en la tarjeta, diciendo «sí», o porque la marcó antes como «permitir siempre».

Es un catálogo cerrado de acciones de poco riesgo: abrir cosas, buscar por nombre, temporizadores, música y
volumen. Nada borra, envía, compra ni cambia ajustes, y no hay comandos libres. Todo queda en
data/acciones.jsonl y se ve en Ajustes.
"""
import asyncio
import difflib
import json
import logging
import os
import re
import subprocess
import sys
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from . import state
from .config import settings

log = logging.getLogger("companion.actions")
LOG_FILE = settings.data_dir / "acciones.jsonl"
DRY = os.getenv("COMPANION_ACTIONS_DRY") == "1"          # las pruebas: se comprueba todo, no se ejecuta nada
MAX_PER_REPLY = 3
TIMER_MAX_S = 12 * 3600
SEARCH_BUDGET_S, SEARCH_MAX = 4.0, 8

# nombre → título para la tarjeta y si su resultado vuelve al modelo (que entonces te lo cuenta)
CATALOG = {
    "abrir_app": {"title": "Abrir una aplicación", "report": False},
    "abrir_web": {"title": "Abrir una página web", "report": False},
    "abrir_carpeta": {"title": "Abrir una carpeta", "report": False},
    "buscar_archivo": {"title": "Buscar archivos por nombre", "report": True},
    "temporizador": {"title": "Poner un temporizador", "report": False},
    "multimedia": {"title": "Controlar la música o el vídeo", "report": False},
    "volumen": {"title": "Cambiar el volumen", "report": False},
    # Ratón y teclado sobre una ventana (companion/control.py). Desde el 16 nov 2026 también admite «permitir
    # siempre» (petición del usuario); los pasos delicados que la orden no pedía se siguen confirmando.
    "controlar": {"title": "Usar una aplicación por ti", "report": True},
}


class ActionError(ValueError):
    pass


@dataclass
class Request:
    name: str
    args: list[str]
    title: str
    detail: str                           # lo que se va a hacer, tal cual, para la tarjeta
    target: dict = field(default_factory=dict)     # lo ya resuelto (AppID, ruta, URL, segundos…)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: float = field(default_factory=time.monotonic)

    def public(self, *, is_cloud: bool, provider: str) -> dict:
        note = (f"Con el cerebro en la nube, los nombres de los archivos que encuentre se envían a {provider}."
                if self.name == "buscar_archivo" and is_cloud else "")
        if self.name == "controlar":
            note = ("Lo hace en segundo plano, sin quitarte el foco: tu teclado y tu ratón solo los usa si no estás usando "
                    "la PC. Te preguntará antes de enviar, comprar o borrar algo que no pediste, y nunca escribe contraseñas. "
                    "Lo paras con Esc."
                    + (f" Con el cerebro en la nube, lo que muestra esa ventana se envía a {provider} en cada paso." if is_cloud else ""))
        return {"id": self.id, "action": self.name, "title": self.title, "detail": self.detail, "note": note,
                "always": self.name in always(), "no_always": bool(CATALOG[self.name].get("no_always"))}


# ---------------------------------------------------------------- ajustes
def config() -> dict:
    c = state.load().get("actions") or {}
    # «ask»: pedir permiso en una tarjeta antes de cada acción. Apagado por defecto desde el 13 nov 2026: la orden
    # del usuario ya es la autorización (lo pidió él). Se puede volver a encender en Ajustes.
    # «full» (acceso total, 16 nov 2026, petición del usuario): ninguna acción del catálogo pide tarjeta, tampoco las
    # que elige el modelo con la pantalla o la cámara compartidas. Siguen: el catálogo cerrado, que solo cuenten las
    # de turnos con mensaje suyo y la confirmación de pasos delicados que la orden no pedía (control.task_allows).
    return {"enabled": c.get("enabled", True) is not False, "ask": bool(c.get("ask", False)) and not c.get("full"),
            "full": bool(c.get("full", False)),
            "always": [a for a in c.get("always") or [] if a in CATALOG and not CATALOG[a].get("no_always")]}


def always() -> list[str]:
    return config()["always"]


def save(enabled: bool | None = None, add_always: str | None = None, forget_always: str | None = None,
         ask: bool | None = None, full: bool | None = None) -> dict:
    c = config()
    if full is not None:
        c["full"] = bool(full)
    if enabled is not None:
        c["enabled"] = bool(enabled)
    if ask is not None:
        c["ask"] = bool(ask)
    if add_always in CATALOG and add_always not in c["always"] and not CATALOG[add_always].get("no_always"):
        c["always"].append(add_always)
    if forget_always:
        c["always"] = [a for a in c["always"] if a != forget_always]
    state.save(actions=c)
    return c


def record(req: Request, decision: str, result: str):
    log_entry(req.name, req.detail, decision, result)


def log_entry(action: str, detail: str, decision: str, result: str):
    entry = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action, "detail": detail[:300],
             "decision": decision, "result": result[:300]}
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
    log.info("Acción %s (%s): %s → %s", action, decision, detail, result[:120])


def history(n: int = 30) -> list[dict]:
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- utilidades
def _plain(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s).strip().lower())
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn"))


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def _folders() -> dict[str, Path]:
    h = _home()
    one = Path(os.environ.get("OneDrive", "")) if os.environ.get("OneDrive") else None

    def pick(*names):
        for base in ([one] if one else []) + [h]:
            for n in names:
                if (base / n).is_dir():
                    return base / n
        return h / names[0]
    return {"descargas": h / "Downloads", "documentos": pick("Documents", "Documentos"),
            "escritorio": pick("Desktop", "Escritorio"), "imagenes": pick("Pictures", "Imágenes"),
            "musica": pick("Music", "Música"), "videos": pick("Videos", "Vídeos"), "inicio": h}


_NETWORK = re.compile(r"^(\\\\|//|[a-z][a-z0-9+.-]*://)", re.I)


def _network_path(text: str) -> bool:
    """¿Ruta de red o dirección? (\\\\servidor, //servidor, \\\\?\\UNC\\…, smb://, file://…)"""
    t = text.strip().replace("/", "\\") if sys.platform == "win32" else text.strip()
    return bool(_NETWORK.match(text.strip()) or t.startswith("\\\\"))


def _remote_drive(path: Path) -> bool:
    """Windows: una letra de unidad conectada a una carpeta de red (Z: → \\\\servidor)."""
    if sys.platform != "win32" or not path.drive or not path.drive.endswith(":"):
        return False
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(path.drive + "\\") == 4      # DRIVE_REMOTE
    except Exception:  # noqa: BLE001
        return True


_ALIASES = {"descarga": "descargas", "downloads": "descargas", "documento": "documentos", "documents": "documentos",
            "mis documentos": "documentos", "desktop": "escritorio", "imagen": "imagenes", "fotos": "imagenes",
            "pictures": "imagenes", "music": "musica", "video": "videos", "carpeta personal": "inicio",
            "usuario": "inicio"}


# ---------------------------------------------------------------- aplicaciones (menú Inicio)
_apps: tuple[float, list[dict]] = (0.0, [])


def _start_apps() -> list[dict]:
    """Las aplicaciones del menú Inicio (Get-StartApps: también las de la Microsoft Store). Se guardan 10 min."""
    global _apps
    if time.monotonic() - _apps[0] < 600 and _apps[1]:
        return _apps[1]
    if os.getenv("COMPANION_ACTIONS_APPS"):                  # pruebas: lista fija
        apps = json.loads(os.environ["COMPANION_ACTIONS_APPS"])
    elif sys.platform == "darwin":                           # las apps de /Applications (y las del sistema)
        roots = [Path("/Applications"), Path("/Applications/Utilities"), Path("/System/Applications"),
                 Path("/System/Applications/Utilities"), _home() / "Applications"]
        apps = [{"name": p.stem, "id": str(p)} for r in roots if r.is_dir() for p in sorted(r.glob("*.app"))]
    elif sys.platform == "win32":
        cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
               "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(r.stdout.decode("utf-8", "replace") or "[]")
        apps = [data] if isinstance(data, dict) else data
    else:
        apps = []
    apps = [{"name": str(a.get("Name") or a.get("name")), "id": str(a.get("AppID") or a.get("id"))}
            for a in apps if (a.get("Name") or a.get("name")) and (a.get("AppID") or a.get("id"))]
    _apps = (time.monotonic(), apps)
    return apps


def find_app(query: str) -> dict:
    q = _plain(query)
    q = re.sub(r"^(la |el |app |aplicacion |programa )+", "", q).strip()
    if not q:
        raise ActionError("No me dijo qué aplicación abrir.")
    apps = _start_apps()
    names = {a["id"]: _plain(a["name"]) for a in apps}
    junk = re.compile(r"desinstal|uninstall|readme|ayuda|help|manual|licen|release notes")
    ok = [a for a in apps if not junk.search(names[a["id"]])]
    for test in (lambda n: n == q, lambda n: n.startswith(q), lambda n: q in n.split(), lambda n: q in n):
        hits = [a for a in ok if test(names[a["id"]])]
        if hits:
            return min(hits, key=lambda a: len(a["name"]))
    close = difflib.get_close_matches(q, [names[a["id"]] for a in ok], n=1, cutoff=0.72)
    if close:
        return next(a for a in ok if names[a["id"]] == close[0])
    raise ActionError(f"No encontré «{query}» entre las aplicaciones del menú Inicio.")


# ---------------------------------------------------------------- preparar (antes de pedir permiso)
def _duration(text: str) -> int:
    t = _plain(text).replace(",", ".")
    words = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "diez": 10, "quince": 15,
             "veinte": 20, "treinta": 30, "media": 0.5, "medio": 0.5, "cuarto": 0.25}
    total = 0.0
    for num, unit in re.findall(r"(\d+(?:\.\d+)?|[a-z]+)\s*(h|hora|horas|m|min|mins|minuto|minutos|s|seg|segundo|segundos)\b", t):
        n = float(num) if num[0].isdigit() else words.get(num)
        if n is None:
            continue
        total += n * (3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1)
    if "y media" in t and total:
        total += 1800 if "hora" in t else 30
    if not total and re.fullmatch(r"\d+", t):
        total = int(t) * 60                                   # un número suelto: minutos
    if not 1 <= total <= TIMER_MAX_S:
        raise ActionError("Ese temporizador no es válido (de 1 segundo a 12 horas).")
    return int(total)


def _say_duration(s: int) -> str:
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    parts = [f"{h} h" if h else "", f"{m} min" if m else "", f"{sec} s" if sec else ""]
    return " ".join(p for p in parts if p)


def prepare(name: str, args: list[str]) -> Request:
    """Comprueba la acción y resuelve a qué se refiere. Lanza ActionError si no se puede hacer."""
    name = _plain(name).replace(" ", "_")
    if name not in CATALOG:
        raise ActionError(f"«{name}» no es una de las acciones que puedo hacer.")
    args = [re.sub(r"[\r\n\t]+", " ", a).strip()[:200] for a in args if a and a.strip()]
    first = args[0] if args else ""
    title = CATALOG[name]["title"]

    if name == "abrir_app":
        app = find_app(first)
        return Request(name, args, title, f"Abrir {app['name']}", {"app": app})

    if name == "abrir_web":
        if not first:
            raise ActionError("No me dijo qué página abrir.")
        text = first.strip()
        if re.fullmatch(r"(https?://)?[\w-]+(\.[\w-]+)+(:\d+)?(/\S*)?", text, re.I):
            url = text if re.match(r"https?://", text, re.I) else f"https://{text}"
            detail = f"Abrir {urlparse(url).netloc}{urlparse(url).path if len(urlparse(url).path) > 1 else ''}"
        else:
            url = f"https://www.google.com/search?q={quote_plus(text)}"
            detail = f"Buscar en Google: «{text}»"
        if urlparse(url).scheme not in ("http", "https"):
            raise ActionError("Solo puedo abrir direcciones web normales (http o https).")
        return Request(name, args, title, detail, {"url": url})

    if name == "abrir_carpeta":
        key = _ALIASES.get(_plain(first), _plain(first))
        folders = _folders()
        if key in folders:
            path = folders[key]
        else:
            raw = os.path.expandvars(first).strip()
            # Una ruta de red (\\servidor\carpeta, //servidor, smb://…) no se toca: solo comprobar si existe hace que
            # Windows se conecte a ese servidor y le entregue una huella de la contraseña, antes de cualquier permiso.
            if _network_path(raw):
                raise ActionError("Solo abro carpetas de este equipo, no de la red.")
            path = Path(raw).expanduser()
            if not path.is_absolute():
                raise ActionError("Dime una carpeta conocida (descargas, documentos, escritorio, imágenes, música, vídeos) o una ruta completa.")
            if _network_path(str(path)) or _remote_drive(path):
                raise ActionError("Solo abro carpetas de este equipo, no de la red.")
        if not path.is_dir():
            raise ActionError(f"La carpeta {path} no existe.")
        return Request(name, args, title, f"Abrir la carpeta {path}", {"path": str(path)})

    if name == "buscar_archivo":
        words = [w for w in re.split(r"[\s*?]+", _plain(first)) if len(w) >= 2][:5]
        if not words:
            raise ActionError("No me dijo qué archivo buscar.")
        return Request(name, args, title, f"Buscar archivos cuyo nombre contenga «{' '.join(words)}» en tus carpetas personales",
                       {"words": words})

    if name == "temporizador":
        seconds = _duration(first)
        label = args[1][:60] if len(args) > 1 else ""
        return Request(name, args, title, f"Temporizador de {_say_duration(seconds)}" + (f" ({label})" if label else ""),
                       {"seconds": seconds, "label": label})

    if name == "multimedia":
        if sys.platform != "win32":
            raise ActionError("Controlar la música solo funciona en Windows, de momento.")
        k = _plain(first)
        op = ("pausa" if re.search(r"paus|para|deten|stop|reanud|segu|play|reproduc|continu", k) else
              "siguiente" if re.search(r"sig|next|adelant|salt", k) else
              "anterior" if re.search(r"ant|prev|atras|volver", k) else None)
        if not op:
            raise ActionError("Solo puedo pausar o reanudar, y pasar a la siguiente o a la anterior.")
        text = {"pausa": "Pausar o reanudar lo que suena", "siguiente": "Pasar a la siguiente", "anterior": "Volver a la anterior"}[op]
        return Request(name, args, title, text, {"op": op})

    if name == "controlar":
        if sys.platform != "win32":
            raise ActionError("Manejar aplicaciones solo funciona en Windows.")
        from . import control
        if len(args) < 2:
            raise ActionError("Para usar una aplicación necesito cuál y qué hacer en ella.")
        try:
            win = control.find_window(args[0])
        except control.ControlError as e:
            raise ActionError(str(e)) from None
        task = args[1][:200]
        return Request(name, args, title, f"Usar «{win.title[:60]}» para: {task}", {"window": win, "task": task})

    if name == "volumen":
        k = _plain(" ".join(args))
        op = ("silenciar" if re.search(r"silen|mute|quit", k) else
              "subir" if re.search(r"sub|mas|aument|alto", k) else
              "bajar" if re.search(r"baj|menos|reduc|bajo", k) else None)
        if not op:
            raise ActionError("Solo puedo subir, bajar o silenciar el volumen.")
        m = re.search(r"\d+", k)
        steps = max(1, min(25, int(m.group()) // 2)) if m and op != "silenciar" else 5
        text = {"silenciar": "Silenciar o quitar el silencio", "subir": f"Subir el volumen (~{steps * 2} %)",
                "bajar": f"Bajar el volumen (~{steps * 2} %)"}[op]
        return Request(name, args, title, text, {"op": op, "steps": steps})

    raise ActionError("Acción no reconocida.")


# ---------------------------------------------------------------- órdenes claras del usuario
# Los modelos locales pequeños a veces dicen «te lo busco» y olvidan la etiqueta. Cuando el mensaje del usuario
# es una orden clara de la lista, se reconoce aquí: se le indica al modelo y, si aun así no la pide, se pide
# igual. Sale de las palabras del propio usuario (nunca de una imagen o un resultado) y sigue necesitando su
# permiso en la tarjeta.
_POLITE = re.compile(r"\b(por favor|porfa|porfis|ahora|ya|rapido|enseguida)\b")
_DO = (r"(?:pon|ponme|busca|buscame|reproduce|escribe|pulsa|haz|activa|desactiva|cambia|cierra|selecciona|marca|elige|"
       r"dale|sube|baja|pasa|crea|anade|agrega|quita|elimina|borra|envia|manda|guarda|abre)")
_GUESS = [
    ("controlar", re.compile(r"^(?:en|usa|usando|con)\s+(?:la app\s+|el programa\s+|la ventana de\s+)?(?P<a>[\w .-]{2,30}?)\s+(?:para\s+)?(?P<b>" + _DO + r"\b.+)$")),
    # «reproduce La Barca de Luis Miguel en Apple Music»: la tarea primero y la aplicación al final
    ("controlar", re.compile(r"^(?P<b>" + _DO + r"\b.+?)\s+en\s+(?:la app\s+|el programa\s+|la ventana de\s+)?(?P<a>[\w .-]{2,30})$")),
    ("temporizador", re.compile(r"\b(?:pon|ponme|programa|activa|crea)\s+(?:un|otro)?\s*(?:temporizador|cronometro|alarma)\s+(?:de\s+)?(?P<a>[\w ,.]+?)(?:\s+para\s+(?P<b>.+))?$")),
    ("buscar_archivo", re.compile(r"^(?:busca(?:me)?|encuentra(?:me)?|localiza)\s+(?:mi|mis|el|la|los|las|un|una)?\s*(?:archivo|archivos|documento|documentos|fichero|ficheros|foto|fotos|pdf)\s+(?:de\s+(?:la|el|los|las)?\s*|del\s+|que se llama\s+|llamado\s+)?(?P<a>.+)$")),
    ("volumen", re.compile(r"^(?P<a>sube|subeme|baja|bajame|silencia|quita|pon)\s+(?:el\s+)?(?:volumen|sonido|audio)(?P<b>.*)$")),
    ("multimedia", re.compile(r"^(?P<a>pausa|pon pausa|para la (?:musica|cancion)|reanuda|siguiente cancion|pasa (?:la|de) cancion|cancion anterior|la anterior)\b")),
    ("abrir_carpeta", re.compile(r"^(?:abre(?:me)?|abrir|muestrame)\s+(?:la\s+)?carpeta\s+(?:de\s+)?(?:mis\s+|las\s+|los\s+)?(?P<a>.+)$")),
    ("abrir_web", re.compile(r"^(?:abre(?:me)?|abrir|entra a|ve a)\s+(?:la\s+(?:pagina|web)\s+(?:de\s+)?)?(?P<a>[\w-]+(?:\.[\w-]+)+\S*)$")),
    ("abrir_app", re.compile(r"^(?:abre(?:me)?|abrir|inicia|lanza|arranca)\s+(?:la\s+app\s+|la\s+aplicacion\s+|el\s+programa\s+)?(?:el\s+|la\s+)?(?P<a>[\w .+-]{2,40})$")),
]


def guess(text: str) -> tuple[str, list[str]] | None:
    t = _plain(text)
    t = _POLITE.sub(" ", re.sub(r"[¡!¿?,;:]+|\.(?!\w)", " ", t))       # el punto de «youtube.com» se queda
    t = re.sub(r"^(oye|mika|hey|eh|bueno|vale|venga|puedes|podrias|me puedes|quiero que)\s+", "", re.sub(r"\s+", " ", t).strip())
    t = re.sub(r"^(?:me\s+)?(\w+?)(?:me|lo|la)?$", r"\1", t) if " " not in t else t
    for name, rx in _GUESS:
        m = rx.search(t)
        if m:
            args = [g.strip() for g in (m.groupdict().get("a"), m.groupdict().get("b")) if g and g.strip()]
            if name == "controlar" and m.group("b").startswith(("abre", "abreme")) and "carpeta" in m.group("b"):
                continue                                # «abre la carpeta… en el explorador»: es abrir_carpeta
            if name == "volumen":
                args = [" ".join(args)]
            if name == "controlar":                     # solo si hay una ventana abierta con ese nombre
                try:
                    from . import control
                    control.find_window(args[0])
                except Exception:  # noqa: BLE001
                    return None
            if name == "abrir_app":                     # «abre tu corazón…» no es una app: solo si existe
                if len(args[0].split()) > 4:
                    return None
                try:
                    find_app(args[0])
                except (ActionError, OSError, ValueError, subprocess.SubprocessError):
                    return None
            return name, args
    return None


async def guess_async(text: str) -> tuple[str, list[str]] | None:
    return await asyncio.to_thread(guess, text)


# ---------------------------------------------------------------- ejecutar (solo con permiso)
_VK = {"pausa": 0xB3, "siguiente": 0xB0, "anterior": 0xB1, "silenciar": 0xAD, "bajar": 0xAE, "subir": 0xAF}


def _open(target: str):
    """Abre una dirección o una carpeta con el programa predeterminado del sistema."""
    if sys.platform == "win32":
        os.startfile(target)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", target])


def _mac_volume(op: str, steps: int):
    script = ("set volume output muted not (output muted of (get volume settings))" if op == "silenciar" else
              f"set volume output volume ((output volume of (get volume settings)) {'+' if op == 'subir' else '-'} {steps * 2})")
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)


def _key(vk: int, times: int = 1):
    import ctypes
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.02)


def _search(words: list[str]) -> list[Path]:
    roots = ([Path(p) for p in os.environ["COMPANION_ACTIONS_ROOTS"].split(os.pathsep)]
             if os.getenv("COMPANION_ACTIONS_ROOTS") else
             list(dict.fromkeys(p for k, p in _folders().items() if k != "inicio" and p.is_dir())))
    # Tolerante: una palabra cuenta si está en el nombre o se parece mucho a una de sus partes (el modelo a veces
    # escribe «octubra» por «octubre»). Primero los que tienen todas las palabras; si no hay, los que tienen la
    # mayoría.
    skip = re.compile(r"^(\.|node_modules$|__pycache__$|appdata$|\$recycle)", re.I)

    def hits(name: str) -> int:
        plain = _plain(name)
        parts = re.split(r"[^a-z0-9ñ]+", plain)
        return sum(1 for w in words if w in plain or any(difflib.SequenceMatcher(None, w, p).ratio() >= 0.8 for p in parts if p))
    best: list[tuple[int, Path]] = []
    limit = time.monotonic() + SEARCH_BUDGET_S
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not skip.search(d)]
            for f in filenames:
                n = hits(f)
                if n and n * 2 >= len(words):
                    best.append((n, Path(dirpath) / f))
            if time.monotonic() > limit or sum(1 for n, _ in best if n == len(words)) >= SEARCH_MAX:
                break
    full = [p for n, p in best if n == len(words)]
    return (full or [p for n, p in sorted(best, key=lambda x: -x[0])])[:SEARCH_MAX]


def run(req: Request) -> str:
    """Hace la acción. Devuelve una frase con el resultado (para el registro y, si toca, para el modelo)."""
    t = req.target
    if req.name == "buscar_archivo":                       # solo lee nombres: también se hace en las pruebas
        hits = _search(t["words"])
        if not hits:
            return f"No encontré archivos con «{' '.join(t['words'])}» en el nombre."
        home = _home()
        rows = []
        for p in hits:
            try:
                where = str(p.parent.relative_to(home))
            except ValueError:
                where = str(p.parent)
            rows.append(f"{p.name} (en {where})")
        return f"Encontré {len(hits)}{' o más' if len(hits) >= SEARCH_MAX else ''}: " + "; ".join(rows)
    if DRY:
        return f"(simulado) {req.detail}"
    if req.name == "abrir_app":
        if sys.platform == "darwin":
            subprocess.Popen(["open", t["app"]["id"]])     # la ruta del .app
        else:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{t['app']['id']}"],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return f"Abrí {t['app']['name']}."
    if req.name == "abrir_web":
        _open(t["url"])                                     # el navegador predeterminado
        return f"Abrí {t['url']} en el navegador."
    if req.name == "abrir_carpeta":
        _open(t["path"])                                    # siempre una carpeta (comprobado), nunca un archivo
        return f"Abrí la carpeta {t['path']}."
    if req.name == "multimedia":
        _key(_VK[t["op"]])
        return req.detail + "."
    if req.name == "volumen":
        if sys.platform == "darwin":
            _mac_volume(t["op"], t["steps"])
            return req.detail + "."
        _key(_VK[t["op"]], 1 if t["op"] == "silenciar" else t["steps"])
        return req.detail + "."
    if req.name == "temporizador":
        return f"Temporizador de {_say_duration(t['seconds'])} en marcha."
    raise ActionError("Acción no reconocida.")


async def run_async(req: Request) -> str:
    return await asyncio.to_thread(run, req)


async def prepare_async(name: str, args: list[str]) -> Request:
    return await asyncio.to_thread(prepare, name, args)
