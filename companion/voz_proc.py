"""Arranca y para el servidor de la voz completa (voz/servidor.py, en su propio entorno voz/.venv) desde el
companion: se levanta al usar la voz completa y se apaga al pasar a la ligera o al cerrar, para devolver su
memoria de vídeo. Si ya hay uno respondiendo en TTS_URL (otro companion, o lanzado a mano), se usa ese."""
import asyncio
import logging
import os
import subprocess
import sys
import time
from urllib.parse import urlparse

import httpx

from .config import ROOT, settings

log = logging.getLogger("companion.voz")
DIR = ROOT / "voz"
LOAD_WAIT = 60.0                          # lo que se espera a que cargue (F5-TTS tarda ~10-20 s en esta PC)
_proc: subprocess.Popen | None = None
_log = None


def _python():
    return DIR / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def installed() -> bool:
    return _python().is_file() and any((DIR / "modelos" / "f5-spanish").glob("model_*.safetensors"))


def _answers() -> bool:
    try:
        return httpx.get(f"{settings.tts_url}/health", timeout=1.5).status_code == 200
    except httpx.HTTPError:
        return False


def start():
    global _proc, _log
    url = urlparse(settings.tts_url)
    if not installed() or url.hostname not in ("127.0.0.1", "localhost") or (_proc and _proc.poll() is None) or _answers():
        return
    # El oído añade al PATH las librerías de NVIDIA del companion (cuDNN para CTranslate2). El servidor de voz
    # trae las suyas con PyTorch, de otra versión: si hereda ese PATH las mezcla y falla al cargar
    # (CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH, 12 nov 2026).
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                  if "site-packages" not in p.lower() or "nvidia" not in p.lower())
    env["VOICES_CUSTOM_DIR"] = str(settings.data_dir / "voces")     # las voces propias del usuario
    if _log:
        _log.close()
    path = settings.data_dir / "voz.log"
    try:                                  # el registro de la vez anterior se guarda (si se cayó, ahí está el porqué)
        if path.is_file() and path.stat().st_size:
            path.replace(path.with_name("voz.1.log"))
    except OSError:
        pass
    _log = open(path, "w", encoding="utf-8")
    _proc = subprocess.Popen([str(_python()), "-m", "uvicorn", "servidor:app", "--app-dir", str(DIR), "--host", "127.0.0.1",
                              "--port", str(url.port or 8210)], cwd=ROOT, env=env, stdout=_log, stderr=subprocess.STDOUT,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log.info("Servidor de voz arrancado (pid %s); tarda unos segundos en cargar", _proc.pid)


def stop():
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(5)
        except subprocess.TimeoutExpired:
            _proc.kill()
        log.info("Servidor de voz detenido")
    _proc = None
    if _log:
        _log.close()


def sync():
    """Deja el servidor de voz como pide el motor elegido."""
    start() if settings.voice_engine == "completa" else stop()


def ensure() -> bool:
    """Con la voz completa elegida, si el servidor de voz se cayó (o nunca arrancó) se vuelve a levantar.
    Devuelve True si lo arrancó ahora."""
    if settings.voice_engine != "completa" or not installed():
        return False
    if _proc is not None and _proc.poll() is None:
        return False
    if _proc is not None:
        log.warning("El servidor de voz se cerró (código %s): lo vuelvo a arrancar", _proc.returncode)
    before = _proc
    start()
    return _proc is not before and _proc is not None


def _health() -> dict:
    try:
        r = httpx.get(f"{settings.tts_url}/health", timeout=1.5)
        return r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {}


async def recover(timeout: float = LOAD_WAIT) -> bool:
    """La voz no respondió (cargando, o el proceso se cayó): se relanza si hace falta y se espera a que esté lista.
    True si al final hay voz."""
    await asyncio.to_thread(ensure)
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        h = await asyncio.to_thread(_health)
        if h.get("tts", "none") != "none":
            return True
        if h.get("error"):
            log.warning("El servidor de voz no pudo cargar: %s", str(h["error"])[:200])
            return False
        if not h and (_proc is None or _proc.poll() is not None):
            return False                  # no hay uno nuestro arrancando (o se volvió a cerrar): mejor seguir en texto
        await asyncio.sleep(0.5)
    return False
