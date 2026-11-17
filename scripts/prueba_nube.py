"""Prueba y medición del modo «solo nube» (cerebro, oído y voz en la nube) contra el servidor de prueba (8201).

Arranca el servidor aislado con «solo nube», habla con él por voz como si fuera el micrófono (la pregunta la dice
una voz neuronal distinta de la del personaje) y mide lo que gasta: RAM, procesador y memoria de vídeo del servidor
y de sus procesos hijos, en reposo y en el pico de cada turno. Después abre la ventana del companion fuera de la
pantalla (sin sonido, micrófono simulado) y la mide también. Para comparar, repite el reposo y un turno con el oído
local (Whisper en la tarjeta) y la voz ligera. La voz completa no se mide aquí: su servidor usa el puerto 8210,
que es el del usuario.

    .venv\\Scripts\\python.exe scripts\\prueba_nube.py [--turnos 3] [--sin-ventana] [--sin-comparar]

La clave del cerebro se lee de data\\settings.json (nunca se imprime). GROQ_API_KEY, si está en el entorno, se usa
para el oído; sin ella el oído en la nube usa Gemini. Gasta peticiones de la cuota gratuita de Gemini: una por
turno de conversación y otra por transcripción si no hay clave de Groq.
"""
import argparse
import asyncio
import ctypes
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prueba  # noqa: E402  (antes que companion.*: servidor, datos y modelos de prueba, no los reales)

from websockets.asyncio.client import connect  # noqa: E402

ROOT = _prueba.ROOT
API = _prueba.URL
FRAME = 512
ELECTRON = _prueba.ELECTRON
VOZ_USUARIO = "es-MX-JorgeNeural"         # quien pregunta suena distinto del personaje
PREGUNTAS = ["Hola, ¿cómo estás hoy?",
             "¿Me recomiendas una película tranquila para esta noche?",
             "Gracias. ¿Y qué podría cenar algo ligero?"]


# ---------------------------------------------------------------- medir procesos (Windows, sin librerías)
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                       "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                                       "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wintypes.HANDLE
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
NCPU = os.cpu_count() or 1


def arbol(raiz: int) -> dict[int, str]:
    """El proceso y todos sus descendientes: pid → ejecutable."""
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    hijos, nombres = {}, {}
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        hijos.setdefault(e.th32ParentProcessID, []).append(e.th32ProcessID)
        nombres[e.th32ProcessID] = e.szExeFile
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    out, cola = {}, [raiz]
    while cola:
        p = cola.pop()
        if p in nombres and p not in out:
            out[p] = nombres[p]
            cola += hijos.get(p, [])
    return out


def leer(pid: int) -> tuple[float, int] | None:
    """(segundos de procesador usados, bytes del conjunto de trabajo privado aproximado = WorkingSet)."""
    h = k32.OpenProcess(0x1000 | 0x0010, False, pid)
    if not h:
        return None
    try:
        c, x, k, u = (wintypes.FILETIME() for _ in range(4))
        k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(x), ctypes.byref(k), ctypes.byref(u))
        cpu = ((k.dwHighDateTime << 32 | k.dwLowDateTime) + (u.dwHighDateTime << 32 | u.dwLowDateTime)) / 1e7
        m = PROCESS_MEMORY_COUNTERS_EX()
        m.cb = ctypes.sizeof(m)
        k32.K32GetProcessMemoryInfo(h, ctypes.byref(m), m.cb)
        return cpu, m.WorkingSetSize
    finally:
        k32.CloseHandle(h)


def vram_por_proceso() -> dict[int, float]:
    """MB de memoria de vídeo dedicada por proceso (contador de Windows «GPU Process Memory»)."""
    ps = ("(Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage' -ErrorAction Stop).CounterSamples | "
          "ForEach-Object { if ($_.InstanceName -match '^pid_(\\d+)_') { \"$($Matches[1]) $($_.CookedValue)\" } }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out: dict[int, float] = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            out[int(parts[0])] = out.get(int(parts[0]), 0.0) + float(parts[1].replace(",", ".")) / 2**20
    return out


class Medidor:
    """Muestrea un árbol de procesos cada `paso` s en segundo plano: RAM total y % de procesador (de toda la PC)."""

    def __init__(self, raiz: int, paso: float = 0.25):
        self.raiz, self.paso = raiz, paso
        self.muestras: list[tuple[float, float]] = []      # (RAM en MB, % de procesador)
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._bucle, daemon=True)

    def _total(self) -> tuple[float, int, int]:
        cpu, ram, n = 0.0, 0, 0
        for pid in arbol(self.raiz):
            v = leer(pid)
            if v:
                cpu, ram, n = cpu + v[0], ram + v[1], n + 1
        return cpu, ram, n

    def _bucle(self):
        t0, (c0, _, _) = time.perf_counter(), self._total()
        while not self._parar.wait(self.paso):
            t1, (c1, ram, _) = time.perf_counter(), self._total()
            self.muestras.append((ram / 2**20, 100 * (c1 - c0) / ((t1 - t0) * NCPU)))
            t0, c0 = t1, c1

    def __enter__(self):
        self._hilo.start()
        return self

    def __exit__(self, *_):
        self._parar.set()
        self._hilo.join()

    def resumen(self) -> dict:
        if not self.muestras:
            return {}
        ram = [m[0] for m in self.muestras]
        cpu = [m[1] for m in self.muestras]
        return {"ram_mb": round(statistics.median(ram)), "ram_pico_mb": round(max(ram)),
                "cpu": round(statistics.mean(cpu), 1), "cpu_pico": round(max(cpu), 1)}


def ram_privada() -> dict[int, float]:
    """MB de memoria privada en uso por proceso: lo que enseña el Administrador de tareas en «Memoria». El conjunto
    de trabajo cuenta también lo compartido entre procesos (las DLL de Chromium), y sumado exagera."""
    ps = ("Get-CimInstance Win32_PerfFormattedData_PerfProc_Process | "
          "ForEach-Object { \"$($_.IDProcess) $($_.WorkingSetPrivate)\" }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            out[int(parts[0])] = int(parts[1]) / 2**20
    return out


def medir_reposo(pid: int, segundos: float = 8.0) -> dict:
    with Medidor(pid, 0.5) as m:
        time.sleep(segundos)
    procs = arbol(pid)
    vram, priv = vram_por_proceso(), ram_privada()
    return {**m.resumen(), "ram_privada_mb": round(sum(priv.get(p, 0.0) for p in procs)),
            "vram_mb": round(sum(vram.get(p, 0.0) for p in procs)), "procesos": sorted(set(procs.values())),
            "n_procesos": len(procs),
            "detalle": sorted(([n, round(priv.get(p, 0.0)), round(vram.get(p, 0.0)), _tipo(p)] for p, n in procs.items()),
                              key=lambda x: -x[1])}


def _tipo(pid: int) -> str:
    """El papel de un proceso de Chromium (--type=renderer, gpu-process…), para el desglose."""
    ps = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"
    try:
        cmd = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    import re
    m = re.search(r"--type=([\w-]+)", cmd)
    return m.group(1) if m else "principal"


# ---------------------------------------------------------------- hablarle como si fuera el micrófono
async def voz_16k(frase: str) -> np.ndarray:
    from companion import tts_cloud
    with_voice = {"voice": VOZ_USUARIO}
    orig = tts_cloud.spec_for
    tts_cloud.spec_for = lambda _v: with_voice
    try:
        pcm = b"".join([c async for c in tts_cloud.stream_speech(frase, "usuario")])
    finally:
        tts_cloud.spec_for = orig
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n = int(len(x) * 16000 / 24000)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16)


async def turno(ws, habla: np.ndarray) -> dict:
    silencio = np.zeros(FRAME, dtype=np.int16)
    r = {"oido_s": None, "primer_audio_s": None, "fin_s": None, "oyo": "", "dijo": "", "audio_s": 0.0, "error": ""}
    marca = {"t": None}
    fin = asyncio.Event()

    async def microfono():
        for i in range(0, len(habla) - FRAME, FRAME):
            await ws.send(habla[i:i + FRAME].tobytes())
            await asyncio.sleep(FRAME / 16000)
        marca["t"] = time.perf_counter()
        while not fin.is_set():
            await ws.send(silencio.tobytes())
            await asyncio.sleep(FRAME / 16000)

    async def escucha():
        audio = 0
        async for msg in ws:
            t = time.perf_counter() - (marca["t"] or time.perf_counter())
            if isinstance(msg, bytes):
                audio += len(msg)
                if r["primer_audio_s"] is None:
                    r["primer_audio_s"] = round(t, 2)
                continue
            ev = json.loads(msg)
            if ev["type"] == "user_text":
                r["oido_s"], r["oyo"] = round(t, 2), ev.get("text", "")
            elif ev["type"] == "sentence":
                r["dijo"] += (" " if r["dijo"] else "") + str(ev.get("text", ""))
            elif ev["type"] in ("reply_end", "error"):
                r["fin_s"] = round(t, 2)
                if ev["type"] == "error":
                    r["error"] = str(ev.get("message") or ev)[:200]
                await ws.send(json.dumps({"type": "playback_end"}))
                r["audio_s"] = round(audio / 48000, 1)
                fin.set()
                return
    await asyncio.wait_for(asyncio.gather(microfono(), escucha()), timeout=120)
    return r


async def conversar(pid: int, frases: list[str]) -> list[dict]:
    voces = [await voz_16k(f) for f in frases]
    out = []
    async with connect(f"ws://127.0.0.1:{_prueba.PORT}/ws", max_size=None) as ws:
        hello = json.loads(await ws.recv())
        print(f"  conectado: oído {hello['stt'].get('engine')}, voz {hello.get('voice_engine')}, cerebro {hello['llm'].get('model')}")
        await asyncio.sleep(4)            # el saludo inicial, si lo hay, se deja pasar
        while True:                       # vacía lo que quedara del saludo
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                if not isinstance(msg, bytes) and json.loads(msg).get("type") == "reply_end":
                    await ws.send(json.dumps({"type": "playback_end"}))
            except asyncio.TimeoutError:
                break
        for frase, voz in zip(frases, voces):
            with Medidor(pid) as m:
                r = await turno(ws, voz)
            r.update(pregunta=frase, **{f"pico_{k}": v for k, v in m.resumen().items()})
            print(f"  «{r['oyo']}» → oído {r['oido_s']} s · primer audio {r['primer_audio_s']} s · "
                  f"fin {r['fin_s']} s · RAM pico {r.get('pico_ram_pico_mb')} MB · CPU pico {r.get('pico_cpu_pico')} %"
                  + (f" · ERROR {r['error']}" if r["error"] else ""))
            out.append(r)
            await asyncio.sleep(2)
    return out


# ---------------------------------------------------------------- la ventana (Electron), fuera de la pantalla
def medir_ventana(segundos_carga: float = 25.0) -> dict:
    if not ELECTRON.exists():
        return {"error": "no está desktop\\electron"}
    env = {**os.environ, "COMPANION_TEST": "1", "COMPANION_TEST_PORT": "9335", "COMPANION_URL": API}
    proc = subprocess.Popen([str(ELECTRON), str(ROOT / "desktop")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(segundos_carga)        # carga la interfaz y el avatar 3D
        return medir_reposo(proc.pid, 10.0)
    finally:
        _prueba.cerrar(proc)


def clave() -> str:
    try:
        sys.path.insert(0, str(ROOT))
        from companion import secret     # desde la 0.7.0 la clave va cifrada (DPAPI / Llavero)
        guardado = secret.reveal(json.loads((ROOT / "data" / "settings.json").read_text(encoding="utf-8")))
        return (guardado.get("cloud") or {}).get("key", "")
    except (OSError, ValueError):
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turnos", type=int, default=3, help="0: solo mide en reposo (no gasta cuota)")
    ap.add_argument("--sin-ventana", action="store_true")
    ap.add_argument("--sin-comparar", action="store_true")
    args = ap.parse_args()
    key = clave()
    if not key:
        raise SystemExit("No hay clave del cerebro en data\\settings.json.")
    cloud = {"preset": "gemini", "base": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "", "key": key}
    ear = {"engine": "nube"}
    if os.getenv("GROQ_API_KEY"):
        ear["groq_key"] = os.environ["GROQ_API_KEY"].strip()
    informe: dict = {"fecha": time.strftime("%Y-%m-%d %H:%M"), "groq": "groq_key" in ear}

    print("== Solo nube: cerebro Gemini, oído", "Groq" if informe["groq"] else "Gemini", "y voz de Edge")
    ajustes = {"provider": "gemini", "cloud": cloud, "cloud_only": True, "voice_engine": "nube", "ear": ear,
               "before_cloud_only": {"provider": "gemini", "ear": "local", "voice_engine": "ligera"}}
    with _prueba.Servidor(ajustes=ajustes) as srv:
        cfg = httpx.get(f"{API}/api/config", timeout=10).json()
        assert cfg["cloud_only"] and cfg["stt"]["engine"] == "nube" and cfg["voice_engine"] == "nube", cfg
        time.sleep(5)
        informe["nube_reposo"] = medir_reposo(srv.proc.pid)
        print("  reposo:", informe["nube_reposo"])
        if args.turnos:
            informe["nube_turnos"] = asyncio.run(conversar(srv.proc.pid, PREGUNTAS[:args.turnos]))
            informe["nube_tras_turnos"] = medir_reposo(srv.proc.pid, 5)
            print("  tras hablar:", informe["nube_tras_turnos"])
        if not args.sin_ventana:
            informe["ventana"] = medir_ventana()
            print("  ventana (Electron):", informe["ventana"])
        cfg = httpx.get(f"{API}/api/config", timeout=10).json()
        informe["oido_ultimo"] = cfg["stt"]["cloud"]["last"]

    if not args.sin_comparar:
        print("== Para comparar: oído local (Whisper en la tarjeta) y voz ligera, cerebro en la nube")
        ajustes = {"provider": "gemini", "cloud": cloud, "voice_engine": "ligera", "ear": {"engine": "local"}}
        with _prueba.Servidor(ajustes=ajustes) as srv:
            time.sleep(5)
            informe["local_reposo"] = medir_reposo(srv.proc.pid)
            print("  reposo:", informe["local_reposo"])
            if args.turnos:
                informe["local_turnos"] = asyncio.run(conversar(srv.proc.pid, PREGUNTAS[:1]))

    salida = _prueba.TEST_DIR / ("medicion_nube.json" if args.turnos else "medicion_nube_reposo.json")
    salida.write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Informe: {salida}")
    errores = [t for t in informe.get("nube_turnos", []) if t["error"] or not t["oyo"] or not t["audio_s"]]
    if errores:
        raise SystemExit(f"{len(errores)} turno(s) sin transcripción, sin voz o con error")


if __name__ == "__main__":
    main()
