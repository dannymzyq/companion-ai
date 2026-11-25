"""Arranca y para el servidor de la voz completa (voz/servidor.py, en su propio entorno voz/.venv) desde el
companion: se levanta al usar la voz completa y se apaga al pasar a la ligera o al cerrar, para devolver su
memoria de vídeo. Si ya hay uno respondiendo en TTS_URL (otro companion, o lanzado a mano), se usa ese."""
import asyncio
import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

import httpx

from .config import ROOT, settings

log = logging.getLogger("companion.voz")
DIR = ROOT / "voz"
LOAD_WAIT = 60.0                          # lo que se espera a que cargue (F5-TTS tarda ~10-20 s en esta PC)
_proc: subprocess.Popen | None = None
_log = None
_job_handle = None
_fast: bool | None = None                 # la voz completa va en modo rápido (tarjeta lenta, voz/servidor.py)
_fast_asked = 0.0
_fast_busy = False


def _assign_job_object(proc: subprocess.Popen):
    """En Windows asocia el subproceso a un Job Object con KILL_ON_JOB_CLOSE para no dejar F5-TTS huérfano en VRAM."""
    global _job_handle
    if sys.platform != "win32":
        return
    try:
        k32 = ctypes.windll.kernel32
        if _job_handle is None:
            job = k32.CreateJobObjectW(None, None)
            if not job:
                return

            class BASIC_LIMIT(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", ctypes.c_uint32),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_uint32),
                    ("SchedulingClass", ctypes.c_uint32),
                ]

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("r_op", "w_op", "o_op", "r_tr", "w_tr", "o_tr")]

            class EXTENDED_LIMIT(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", BASIC_LIMIT),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            info = EXTENDED_LIMIT()
            info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
                _job_handle = job
            else:
                k32.CloseHandle(job)
                return
        k32.AssignProcessToJobObject(_job_handle, int(proc._handle))
    except Exception:  # noqa: BLE001
        pass


def _python():
    return DIR / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def installed() -> bool:
    return _python().is_file() and any((DIR / "modelos" / "f5-spanish").glob("model_*.safetensors"))


def _answers() -> bool:
    return bool(_health())


def start():
    global _proc, _log
    url = urlparse(settings.tts_url)
    if not installed() or url.hostname not in ("127.0.0.1", "localhost") or (_proc and _proc.poll() is None) or _answers():
        return
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                  if "site-packages" not in p.lower() or "nvidia" not in p.lower())
    env["VOICES_CUSTOM_DIR"] = str(settings.data_dir / "voces")
    env["COMPANION_PARENT_PID"] = str(os.getpid())
    if sys.platform == "darwin":
        env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
        env.setdefault("VOZ_NFE", "16")
        env.setdefault("VOZ_REF_CORTA", "1")
        env.setdefault("VOZ_LARGA", "90")
    if _log:
        _log.close()
        _log = None
    path = settings.data_dir / "voz.log"
    try:
        if path.is_file() and path.stat().st_size:
            path.replace(path.with_name("voz.1.log"))
    except OSError:
        pass
    _log = open(path, "w", encoding="utf-8")
    _proc = subprocess.Popen(
        [str(_python()), "-m", "uvicorn", "servidor:app", "--app-dir", str(DIR), "--host", "127.0.0.1",
         "--port", str(url.port or 8210)],
        cwd=ROOT, env=env, stdout=_log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    _assign_job_object(_proc)
    log.info("Servidor de voz arrancado (pid %s); tarda unos segundos en cargar", _proc.pid)


def running() -> bool:
    return _proc is not None and _proc.poll() is None


def stop():
    global _proc, _log, _fast
    if _proc and _proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(_proc.pid)], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            _proc.terminate()
        try:
            _proc.wait(5)
        except subprocess.TimeoutExpired:
            _proc.kill()
        log.info("Servidor de voz detenido")
    _proc = None
    _fast = None
    if _log:
        try:
            _log.close()
        except OSError:
            pass
        _log = None


def sync():
    start() if settings.voice_engine == "completa" else stop()


def ensure() -> bool:
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
    global _fast
    try:
        r = httpx.get(f"{settings.tts_url}/health", timeout=1.5)
        h = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {}
    if h.get("tts", "none") != "none" and h.get("phrase_s") is not None:
        _fast = bool(h.get("fast"))
    return h


def _probe_fast_bg():
    global _fast_busy
    try:
        _health()
    finally:
        _fast_busy = False


def fast() -> bool:
    """¿La voz completa está en modo rápido? Nunca bloquea el event loop: si aún no se sabe, lanza la consulta en un
    hilo de fondo salvo que no haya event loop activo (pruebas unitarias síncronas)."""
    global _fast_asked, _fast_busy
    if _fast is None and not _fast_busy and time.monotonic() - _fast_asked > 20:
        _fast_asked = time.monotonic()
        try:
            asyncio.get_running_loop()
            _fast_busy = True
            threading.Thread(target=_probe_fast_bg, daemon=True).start()
        except RuntimeError:
            _health()
    return bool(_fast)


async def recover(timeout: float = LOAD_WAIT) -> bool:
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
            return False
        await asyncio.sleep(0.5)
    return False
