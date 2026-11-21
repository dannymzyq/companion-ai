"""Lo que la mascota de escritorio necesita saber de las ventanas (modo flotante, desktop/pet.js): dónde está la
ventana activa, si está minimizada, maximizada o a pantalla completa. Solo la posición: nunca el título ni lo que
muestra, y no sale de esta PC. Coordenadas en píxeles reales de la pantalla (control.py activa el modo «DPI
aware»); la app de escritorio las pasa a las suyas.

Solo en Windows; en otro sistema no hay ventana activa (la mascota no se sienta en ventanas).
"""
import ctypes
import ctypes.wintypes
import os
import sys
import time
from pathlib import Path

from .config import ROOT

_own: dict[int, tuple[float, bool]] = {}         # hwnd → (cuándo se miró, ¿es del companion?)


def _frame(hwnd: int) -> tuple[int, int, int, int]:
    """El borde visible de la ventana (sin el borde invisible de 7 px que Windows 10/11 deja para agarrarla)."""
    from . import control
    r = ctypes.wintypes.RECT()
    try:
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:   # EXTENDED_FRAME_BOUNDS
            return r.left, r.top, r.right, r.bottom
    except OSError:
        pass
    return control.rect(hwnd)


def _is_own(hwnd: int) -> bool:
    """¿Es una ventana del propio companion (Electron de desktop\\, Python de la carpeta)? Se recuerda un rato."""
    from . import control
    seen = _own.get(hwnd)
    if seen and time.monotonic() - seen[0] < 30:
        return seen[1]
    pid = ctypes.wintypes.DWORD()
    control.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    _, path = control._process(hwnd)
    own = pid.value == os.getpid() or bool(path) and any(
        Path(path).resolve().is_relative_to(ROOT / d) for d in ("desktop", "runtime", ".venv", "voz"))
    if len(_own) > 200:
        _own.clear()
    _own[hwnd] = (time.monotonic(), own)
    return own


def foreground() -> dict | None:
    """La ventana activa: {id, rect: [izq, arriba, der, abajo], minimized, maximized, fullscreen, own}."""
    if sys.platform != "win32":
        return None
    from . import control
    u = control.user32
    hwnd = u.GetForegroundWindow()
    if not hwnd or hwnd in (u.GetShellWindow(), u.GetDesktopWindow()) or not u.IsWindowVisible(hwnd):
        return None
    return {"id": int(hwnd), "rect": list(_frame(hwnd)), "minimized": bool(u.IsIconic(hwnd)),
            "maximized": bool(u.IsZoomed(hwnd)), "fullscreen": control.fullscreen(hwnd), "own": _is_own(hwnd)}


def window(hwnd: int) -> dict | None:
    """Una ventana concreta (la de una tarea de control): {rect, minimized, maximized}."""
    if sys.platform != "win32" or not hwnd:
        return None
    from . import control
    u = control.user32
    if not u.IsWindow(hwnd):
        return None
    return {"rect": list(_frame(hwnd)), "minimized": bool(u.IsIconic(hwnd)), "maximized": bool(u.IsZoomed(hwnd)),
            "fullscreen": control.fullscreen(hwnd)}
