"""Prueba el cambio entre la ventana normal y el modo flotante sin que se vea ni se oiga nada (ventanas fuera de
pantalla, sin sonido, micrófono simulado, servidor de prueba en el 8201). No usa ningún cerebro: la «voz» es un
tono de 6 s que se pone a sonar en la página.

Comprueba (16 nov 2026):
  · al pasar a flotante y al volver, la página es la misma (no se recarga): la voz que sonaba sigue sonando y la
    conversación sigue en marcha
  · «Desvanecer los pies al flotar» apagado: sin degradado y con el modelo entero (captura en data/prueba)
  · la cámara del modelo gira del todo y se puede desplazar y acercar

    .venv\\Scripts\\python.exe scripts\\pruebas\\prueba_flotante.py
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
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _prueba  # noqa: E402  (antes que companion.*: aísla datos, modelos y puerto)

ROOT = _prueba.ROOT
API = _prueba.URL
PORT = 9336
ELECTRON = _prueba.ELECTRON
TONO = """(() => { const a = window.companion.audio; const n = 24000 * 6, pcm = new Int16Array(n);
  for (let i = 0; i < n; i++) pcm[i] = Math.round(9000 * Math.sin(2 * Math.PI * 220 * i / 24000));
  a.beginSentence({ id: 99, text: 'Tono de prueba', emotion: null, gestures: [] }); a.enqueue(pcm.buffer); a.endSentence();
  return a.sources.size; })()"""
SONANDO = "({fuentes: window.companion.audio.sources.size, vol: window.companion.audio.analyse().vol})"


class Pagina:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def cmd(self, method: str, **params):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg["result"]

    async def js(self, code: str):
        r = await self.cmd("Runtime.evaluate", expression=code, awaitPromise=True, returnByValue=True, userGesture=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", r["exceptionDetails"]))
        return r["result"].get("value")


def paginas() -> list[dict]:
    try:
        return [t for t in httpx.get(f"http://127.0.0.1:{PORT}/json/list", timeout=2).json()
                if t["type"] == "page" and t["url"].startswith(API)]
    except Exception:  # noqa: BLE001
        return []


async def esperar(p: Pagina, expr: str, segundos: float = 20):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if await p.js(expr):
            return True
        await asyncio.sleep(0.3)
    raise SystemExit(f"No se cumplió: {expr}")


async def main():
    if not ELECTRON.exists():
        sys.exit("Falta Electron: ejecuta scripts\\instalacion\\instalar_escritorio.ps1")
    env = {**os.environ, "COMPANION_TEST": "1", "COMPANION_TEST_PORT": str(PORT), "COMPANION_URL": API}
    env.pop("ELECTRON_RUN_AS_NODE", None)
    proc = subprocess.Popen([str(ELECTRON), str(ROOT / "desktop")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        limite = time.monotonic() + 30
        while not paginas() and time.monotonic() < limite:
            await asyncio.sleep(0.3)
        pag = paginas()
        assert len(pag) == 1, f"tendría que haber una sola página: {pag}"
        objetivo = pag[0]["id"]
        async with connect(pag[0]["webSocketDebuggerUrl"], max_size=None) as ws:
            p = Pagina(ws)
            await p.cmd("Runtime.enable")
            await p.cmd("Page.enable")
            await esperar(p, "!!window.companion && !!window.desktop")
            await p.js("window.__marca = 'misma página'; null")
            # Sin pasar por la tarjeta de inicio: pasar a flotante arranca la conversación (micrófono simulado).
            await esperar(p, "window.companion.avatar && window.companion.avatar.loaded", 40)
            await p.js("document.getElementById('float-btn').click(); null")
            await esperar(p, "document.body.classList.contains('floating') && window.companion.status().started")
            await asyncio.sleep(1)
            await p.js("window.desktop.float(false); null")          # vuelta, para empezar desde la ventana con voz
            await esperar(p, "!document.body.classList.contains('floating')")

            # ---------------- 1. la voz no se corta al cambiar de modo
            assert await p.js(TONO) >= 1
            await asyncio.sleep(0.8)
            antes = await p.js(SONANDO)
            await p.js("window.desktop.float(true); null")
            await esperar(p, "document.body.classList.contains('floating')")
            await asyncio.sleep(0.8)
            info = await p.js("window.desktop.info()")
            flot = await p.js(f"({{...{SONANDO}, marca: window.__marca, empezada: window.companion.status().started}})")
            print(f"1. a flotante      : antes {antes} → después {flot} · modo={info['mode']} · encima={info['alwaysOnTop']}")
            assert info["mode"] == "float" and info["alwaysOnTop"]
            assert flot["marca"] == "misma página", "la página se recargó al flotar"
            assert flot["fuentes"] >= 1 and flot["vol"] > 0.01, "la voz se cortó al pasar a flotante"
            assert flot["empezada"]
            await p.js("window.desktop.float(false); null")
            await esperar(p, "!document.body.classList.contains('floating')")
            await asyncio.sleep(0.6)
            vuelta = await p.js(f"({{...{SONANDO}, marca: window.__marca}})")
            info = await p.js("window.desktop.info()")
            print(f"2. a la ventana    : {vuelta} · modo={info['mode']} · encima={info['alwaysOnTop']}")
            assert info["mode"] == "window" and not info["alwaysOnTop"]
            assert vuelta["marca"] == "misma página" and vuelta["fuentes"] >= 1 and vuelta["vol"] > 0.01, "la voz se cortó al volver"
            ids = [t["id"] for t in paginas()]
            assert ids == [objetivo], f"apareció otra página: {ids}"

            # ---------------- 2. cámara libre
            c = await p.js("(() => { const c = window.companion.avatar.controls; return {pan: c.enablePan, "
                           "polar: [c.minPolarAngle, c.maxPolarAngle], azimut: [String(c.minAzimuthAngle), String(c.maxAzimuthAngle)], "
                           "zoom: [c.minDistance, c.maxDistance], cursor: c.zoomToCursor}; })()")
            print(f"3. cámara libre    : {c}")
            assert c["pan"] and c["polar"][0] == 0 and c["polar"][1] > 3.1 and c["azimut"] == ["-Infinity", "Infinity"] and c["cursor"]

            # ---------------- 3. sin degradado: el modelo entero
            await p.js("window.desktop.float(true); null")
            await esperar(p, "document.body.classList.contains('floating')")
            await asyncio.sleep(1)
            await p.cmd("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
            for fade in (True, False):
                await p.js(f"(() => {{ const t = document.getElementById('float-fade'); t.checked = {str(fade).lower()}; "
                           "t.dispatchEvent(new Event('change')); })()")
                await asyncio.sleep(1.2)
                st = await p.js("({mascara: getComputedStyle(document.getElementById('canvas')).maskImage, "
                                "entero: window.companion.avatar.fullBody})")
                png = base64.b64decode((await p.cmd("Page.captureScreenshot", format="png"))["data"])
                salida = _prueba.TEST_DIR / f"flotante_{'degradado' if fade else 'entero'}.png"
                salida.write_bytes(png)
                print(f"4. degradado={'sí' if fade else 'no'}  : {st} · {salida}")
                assert (st["mascara"] != "none") == fade and st["entero"] == (not fade)
            await p.js("(() => { const t = document.getElementById('float-fade'); t.checked = true; t.dispatchEvent(new Event('change')); })()")
        print("OK: el cambio de modo no corta la voz ni recarga la página; degradado opcional; cámara libre.")
    finally:
        _prueba.cerrar(proc)


if __name__ == "__main__":
    with _prueba.Servidor():
        asyncio.run(main())
