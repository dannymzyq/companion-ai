"""Hojas de contactos de las poses de la mascota de escritorio (sentada de costado, andar) con cada modelo: los
incluidos y los VRM propios del usuario. Sin que se vea nada: app de prueba fuera de pantalla, servidor de prueba en
el 8201. Los VRM propios se copian solo a data/prueba (nunca salen de esta PC) y las hojas quedan en
data/prueba/hoja_<n>.png.

    .venv\\Scripts\\python.exe scripts\\hoja_modelos.py [--sin-propios]
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _prueba  # noqa: E402

ROOT = _prueba.ROOT
API = _prueba.URL
PORT = 9338
ELECTRON = _prueba.ELECTRON
POSES = """[
  {activity: 'sit', opts: {side: 1}, label: 'sentada (derecha)'}, {activity: 'sit', opts: {side: -1}, label: 'sentada (izquierda)'},
  {activity: 'walk', opts: {dir: 1}, phase: 0, label: 'andar 1'}, {activity: 'walk', opts: {dir: 1}, phase: 1.2, label: 'andar 2'},
  {activity: 'walk', opts: {dir: 1}, phase: 2.4, label: 'andar 3'}, {activity: 'walk', opts: {dir: 1}, phase: 3.6, label: 'andar 4'},
  {activity: 'walk', opts: {dir: -1}, phase: 4.8, label: 'andar 5'}, {activity: 'walk', opts: {dir: -1}, phase: 6.0, label: 'andar 6'}
]"""


async def js(ws, n, code):
    await ws.send(json.dumps({"id": n, "method": "Runtime.evaluate",
                              "params": {"expression": code, "awaitPromise": True, "returnByValue": True}}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == n:
            r = msg["result"]
            if "exceptionDetails" in r:
                raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description"))
            return r["result"].get("value")


async def main():
    ids = ["avatar1", "avatar2"]
    if "--sin-propios" not in sys.argv:
        destino = _prueba.TEST_DIR / "models" / "custom"
        destino.mkdir(parents=True, exist_ok=True)
        for f in sorted((ROOT / "models" / "custom").glob("*.vrm")):
            shutil.copy2(f, destino / f.name)
            ids.append(f.stem)
    env = {**os.environ, "COMPANION_TEST": "1", "COMPANION_TEST_PORT": str(PORT), "COMPANION_URL": API}
    env.pop("ELECTRON_RUN_AS_NODE", None)
    proc = subprocess.Popen([str(ELECTRON), str(ROOT / "desktop")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        limite, pag = time.monotonic() + 30, []
        while not pag and time.monotonic() < limite:
            try:
                pag = [t for t in httpx.get(f"http://127.0.0.1:{PORT}/json/list", timeout=2).json()
                       if t["type"] == "page" and t["url"].startswith(API)]
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.3)
        async with connect(pag[0]["webSocketDebuggerUrl"], max_size=None) as ws:
            n = 0
            for _ in range(160):
                n += 1
                if await js(ws, n, "!!(window.companion && window.companion.avatar && window.companion.avatar.loaded)"):
                    break
                await asyncio.sleep(0.25)
            for i, mid in enumerate(ids, 1):
                httpx.post(f"{API}/api/models/select", json={"id": mid}, timeout=30).raise_for_status()
                n += 1
                await js(ws, n, f"window.companion.avatar.load('/api/model?h={i}').then(() => null)")
                n += 1
                png = await js(ws, n, f"window.companion.avatar.sheet({POSES}, 4, 300, 460).toDataURL('image/png')")
                salida = _prueba.TEST_DIR / f"hoja_{i}.png"
                salida.write_bytes(base64.b64decode(png.split(",", 1)[1]))
                print(f"{i}. {'incluido ' + mid if mid.startswith('avatar') else 'modelo propio'}: {salida}")
    finally:
        _prueba.cerrar(proc)


if __name__ == "__main__":
    with _prueba.Servidor():
        asyncio.run(main())
