"""Pantallas de carga y cierre de procesos, contra el servidor de prueba (8201) y la app fuera de la pantalla.

  1. /api/loading marca «cargando» al pasar del oído en la nube al local y «listo» cuando Whisper termina.
  2. Si el proceso dueño (la ventana) muere, el servidor se apaga solo, con todos sus procesos.
  3. detener.ps1 -PuertoPrueba 8201 -SoloServidor apaga el servidor de prueba con su árbol (nunca el 8200 ni la voz 8210).
  4. La app (Electron) abre ya con cargando.html mientras el servidor no responde, pasa a la interfaz cuando
     responde y enseña la pantalla de carga hasta que el personaje 3D y el oído están listos.
  5. Si el servidor se cierra al arrancar (COMPANION_SERVER_PID muerto), la app lo dice en vez de esperar.

    .venv\\Scripts\\python.exe scripts\\prueba_carga.py

Usa la clave del cerebro de data\\settings.json solo para poder elegir el oído en la nube (no gasta cuota).
Guarda capturas en data\\prueba\\carga_*.png.
"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prueba  # noqa: E402
import prueba_nube  # noqa: E402  (medir procesos y leer la clave)
from companion import lifecycle  # noqa: E402

from websockets.asyncio.client import connect  # noqa: E402

ROOT = _prueba.ROOT
API = _prueba.URL
ELECTRON = _prueba.ELECTRON
CDP = 9336
fallos: list[str] = []


def ok(cond: bool, texto: str):
    print(("  ✔ " if cond else "  ✘ ") + texto)
    if not cond:
        fallos.append(texto)


def ajustes_nube() -> dict:
    key = prueba_nube.clave()
    cloud = {"preset": "gemini", "base": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "", "key": key}
    return {"provider": "gemini", "cloud": cloud, "ear": {"engine": "nube"}, "voice_engine": "ligera", "model": "avatar1"}


def arbol_vivo(pid: int) -> list[int]:
    return [p for p in prueba_nube.arbol(pid)]


def esperar(cond, segundos: float, paso: float = 0.3) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if cond():
            return True
        time.sleep(paso)
    return False


def puerto_libre() -> bool:
    try:
        httpx.get(f"{API}/api/config", timeout=1)
        return False
    except httpx.HTTPError:
        return True


def parte_servidor():
    print("== 1-2. Carga al cambiar el oído y apagado si muere la ventana")
    srv = _prueba.Servidor(ajustes=ajustes_nube()).__enter__()
    try:
        r = httpx.get(f"{API}/api/loading", timeout=5).json()
        ok(not r["busy"] and r["items"][0]["state"] == "listo", f"con el oído en la nube no hay nada cargando ({r['items'][0]['detail']})")
        httpx.post(f"{API}/api/setup", json={"ear": {"engine": "local"}}, timeout=10).raise_for_status()
        visto = []

        def listo():
            it = httpx.get(f"{API}/api/loading", timeout=5).json()["items"][0]
            visto.append(it["state"])
            return it["state"] == "listo"
        ok(esperar(listo, 60, 0.2), "el oído local termina de cargar")
        ok("cargando" in visto, f"mientras carga, /api/loading dice «cargando» ({visto.count('cargando')} veces)")
        dueno = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        httpx.post(f"{API}/api/owner", json={"pid": dueno.pid}, timeout=5).raise_for_status()
        procesos = arbol_vivo(srv.proc.pid)
        time.sleep(4)
        ok(not puerto_libre(), "con la ventana viva, el servidor sigue")
        dueno.kill()
        t = time.monotonic()
        ok(esperar(puerto_libre, 25), f"al morir la ventana, el servidor se apaga solo ({time.monotonic() - t:.1f} s)")
        ok(esperar(lambda: not any(lifecycle.pid_alive(p) for p in procesos), 10),
           f"no queda ninguno de sus {len(procesos)} procesos")
    finally:
        srv.__exit__()


def _escucha(puerto: int) -> bool:
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"[bool](Get-NetTCPConnection -LocalPort {puerto} -State Listen -ErrorAction SilentlyContinue)"],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip() == "True"


def parte_detener():
    print("== 3. detener.ps1 -PuertoPrueba 8201 -SoloServidor")
    srv = _prueba.Servidor(ajustes=ajustes_nube()).__enter__()
    try:
        procesos = arbol_vivo(srv.proc.pid)
        real_antes = _escucha(8200)
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "detener.ps1"),
                            "-PuertoPrueba", str(_prueba.PORT), "-SoloServidor"], capture_output=True, text=True, timeout=60)
        ok("detenido" in r.stdout, f"detener.ps1 dice: {r.stdout.strip()[:80]}")
        ok(_escucha(8200) == real_antes, f"el companion real (8200) sigue como estaba ({'abierto' if real_antes else 'cerrado'})")
        ok(esperar(puerto_libre, 10), "el puerto queda libre")
        ok(esperar(lambda: not any(lifecycle.pid_alive(p) for p in procesos), 10), f"no queda ninguno de sus {len(procesos)} procesos")
        log = (_prueba.TEST_DIR / "servidor.log").read_text(encoding="utf-8", errors="replace")
        ok("Apagando el companion (pedido al cerrar)" in log, "fue un apagado ordenado (/api/shutdown), no a la fuerza")
    finally:
        srv.__exit__()


# ---------------------------------------------------------------- la app
class Pagina:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def cmd(self, method: str, **params):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                return msg.get("result", {})

    async def js(self, code: str):
        r = await self.cmd("Runtime.evaluate", expression=code, awaitPromise=True, returnByValue=True)
        return r.get("result", {}).get("value")

    async def foto(self, nombre: str):
        r = await self.cmd("Page.captureScreenshot", format="png")
        if r.get("data"):
            (_prueba.TEST_DIR / f"carga_{nombre}.png").write_bytes(base64.b64decode(r["data"]))


def paginas() -> list[dict]:
    try:
        return [t for t in httpx.get(f"http://127.0.0.1:{CDP}/json/list", timeout=2).json() if t["type"] == "page"]
    except Exception:  # noqa: BLE001
        return []


def abrir_app(extra: dict) -> subprocess.Popen:
    env = {**os.environ, "COMPANION_TEST": "1", "COMPANION_TEST_PORT": str(CDP), "COMPANION_URL": API, **extra}
    env.pop("COMPANION_SERVER_PID", None) if "COMPANION_SERVER_PID" not in extra else None
    return subprocess.Popen([str(ELECTRON), str(ROOT / "desktop")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def parte_app():
    print("== 4. La app abre ya y espera al servidor con su pantalla de carga")
    assert puerto_libre(), "el puerto 8201 tiene que estar libre"
    app = abrir_app({})
    srv = None
    try:
        ok(esperar(lambda: any("cargando.html" in t["url"] for t in paginas()), 20), "sin servidor, la ventana enseña cargando.html")
        t = next(t for t in paginas() if "cargando.html" in t["url"])
        async with connect(t["webSocketDebuggerUrl"], max_size=None) as ws:
            p = Pagina(ws)
            await asyncio.sleep(1.5)
            texto = await p.js("document.getElementById('titulo').textContent + ' · ' + document.getElementById('texto').textContent")
            ok(texto and texto.startswith("Abriendo Companion"), f"dice «{texto}»")
            await p.foto("1_arranque")
        # con el oído local para que haya algo que cargar al abrir
        srv = _prueba.Servidor(ajustes={**ajustes_nube(), "ear": {"engine": "local"}})
        hilo = asyncio.get_running_loop().run_in_executor(None, srv.__enter__)
        ok(await asyncio.to_thread(esperar, lambda: any(t["url"].startswith(API) for t in paginas()), 60),
           "cuando el servidor responde, la ventana pasa a la interfaz")
        t = next(t for t in paginas() if t["url"].startswith(API))
        async with connect(t["webSocketDebuggerUrl"], max_size=None) as ws:
            p = Pagina(ws)
            visto, foto = [], False
            for _ in range(120):
                e = await p.js("({v: !document.getElementById('loading').hidden, t: document.getElementById('loading-title').textContent,"
                               " items: [...document.querySelectorAll('#loading-items li')].map(li => li.className + ':' + li.firstChild.textContent)})")
                if e:
                    visto.append(e)
                    if e["v"] and len(e["items"]) >= 3 and not foto:
                        await p.foto("2_cargando")
                        foto = True
                    if not e["v"] and len(visto) > 3:
                        break
                await asyncio.sleep(0.25)
            vistos = [v for v in visto if v["v"]]
            ok(bool(vistos), f"la pantalla de carga aparece («{vistos[0]['t'] if vistos else ''}»)")
            if vistos:
                ok(any("avatar" in json.dumps(v) or "personaje 3D" in json.dumps(v, ensure_ascii=False) for v in vistos),
                   "incluye el personaje 3D: " + ", ".join(vistos[-1]["items"]))
            ok(bool(visto) and not visto[-1]["v"], "y se quita sola cuando todo está listo")
            await p.foto("3_listo")
        await hilo
    finally:
        _prueba.cerrar(app)
        if srv and getattr(srv, "proc", None):
            srv.__exit__()

    print("== 5. Si el servidor se cierra al arrancar, la app lo dice")
    muerto = subprocess.Popen([sys.executable, "-c", "pass"])
    muerto.wait()
    app = abrir_app({"COMPANION_SERVER_PID": str(muerto.pid)})
    try:
        ok(esperar(lambda: any("cargando.html" in t["url"] for t in paginas()), 20), "abre cargando.html")
        t = next(t for t in paginas() if "cargando.html" in t["url"])
        async with connect(t["webSocketDebuggerUrl"], max_size=None) as ws:
            p = Pagina(ws)
            texto = ""
            for _ in range(20):
                texto = await p.js("document.body.className + ' · ' + document.getElementById('titulo').textContent") or ""
                if texto.startswith("error"):
                    break
                await asyncio.sleep(0.5)
            ok(texto.startswith("error") and "No se pudo abrir" in texto, f"lo dice al momento: «{texto}»")
            await p.foto("4_error")
    finally:
        _prueba.cerrar(app)


def main():
    if not prueba_nube.clave():
        raise SystemExit("No hay clave del cerebro en data\\settings.json.")
    parte_servidor()
    parte_detener()
    asyncio.run(parte_app())
    print("\nTodo bien." if not fallos else f"\n{len(fallos)} fallo(s): " + "; ".join(fallos))
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
