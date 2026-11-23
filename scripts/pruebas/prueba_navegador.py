"""Prueba la interfaz en un Chrome real y oculto, con un micrófono simulado que «dice» una pregunta.

Comprueba lo que el panel de pruebas no deja probar: el permiso, la lista de micrófonos, el cambio de
micrófono y que la voz capturada por el navegador llegue al companion y reciba respuesta.
Chrome corre sin ventana y sin sonido, con un perfil temporal. El servidor debe estar en marcha.

    .venv\\Scripts\\python.exe scripts\\pruebas\\prueba_navegador.py
"""
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import httpx
import numpy as np
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _prueba  # noqa: E402  (antes que companion.*: servidor, datos y modelos de prueba, no los reales)

if "--local" in sys.argv:                 # con el cerebro local (Ollama) en vez de Gemini
    import os
    os.environ["LLM_PROVIDER"] = "local"

from companion import tts  # noqa: E402
from companion.config import settings  # noqa: E402

CHROME = [p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                      r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                      r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe") if Path(p).exists()]
PORT = 9333
URL = f"http://{settings.host}:{settings.port}/"
FRASE = "Mika, ¿me escuchas bien por este micrófono?"
ESPERA = 12        # segundos de silencio antes de la pregunta (deja terminar el saludo)


async def wav_falso(path: Path):
    pcm = b"".join([c async for c in tts.stream_speech(FRASE, settings.tts_voice)])
    voz = np.repeat(np.frombuffer(pcm, dtype=np.int16), 2)             # 24 kHz → 48 kHz
    audio = np.concatenate([np.zeros(48000 * ESPERA, np.int16), voz, np.zeros(48000 * 60, np.int16)])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(audio.tobytes())


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


ESTADO = """(() => { const $ = (i) => document.getElementById(i); const a = window.companion.audio; return {
  permitir: !$('mic-allow').hidden, selector: !$('mic-picker').hidden, empezar: !$('start-btn').hidden,
  error: $('mic-error').hidden ? null : $('mic-error').textContent,
  opciones: [...$('mic-select').options].map(o => o.text), elegido: $('mic-select').selectedOptions[0]?.text,
  hasMic: a.hasMic, micLabel: a.micLabel || null, nivel: +a.micLevel.toFixed(4),
  estado: document.body.dataset.state, tu: $('user-line').textContent, mika: $('mika-line').textContent }; })()"""


async def main():
    if not CHROME:
        sys.exit("No encontré Chrome ni Edge")
    tmp = Path(tempfile.mkdtemp(prefix="companion-chrome-"))
    wav = tmp / "mic.wav"
    await wav_falso(wav)
    proc = subprocess.Popen([CHROME[0], "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={tmp / 'perfil'}",
                             "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                             f"--use-file-for-fake-audio-capture={wav}", "--autoplay-policy=no-user-gesture-required",
                             "--mute-audio", "--no-first-run", "--no-default-browser-check", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        target = None
        for _ in range(40):
            try:
                target = next(t for t in httpx.get(f"http://127.0.0.1:{PORT}/json/list", timeout=2).json() if t["type"] == "page")
                break
            except Exception:  # noqa: BLE001
                await asyncio.sleep(0.25)
        if not target:
            sys.exit("Chrome no abrió el puerto de depuración")
        async with connect(target["webSocketDebuggerUrl"], max_size=None) as ws:
            p = Pagina(ws)
            await p.cmd("Page.enable")
            await p.cmd("Runtime.enable")
            await p.cmd("Page.navigate", url=URL)
            await asyncio.sleep(4)
            print("1. al abrir        :", await p.js(ESTADO))

            await p.js("document.getElementById(document.getElementById('mic-allow').hidden ? 'mic-select' : 'mic-allow').click()")
            if not (await p.js("window.companion.audio.hasMic")):
                await p.js("window.companion.audio.hasMic || document.getElementById('mic-allow').click()")
            await asyncio.sleep(2)
            e = await p.js(ESTADO)
            print("2. tras permitir   :", e)
            assert e["hasMic"] and e["selector"] and e["empezar"], "el micrófono no quedó abierto"

            if len(e["opciones"]) > 1:
                otra = next(o for o in e["opciones"] if o != e["elegido"])
                await p.js(f"(() => {{ const s = document.getElementById('mic-select'); s.value = [...s.options].find(o => o.text === {json.dumps(otra)}).value; s.dispatchEvent(new Event('change')); }})()")
                await asyncio.sleep(2)
                e = await p.js(ESTADO)
                print("3. tras cambiar    :", {k: e[k] for k in ("elegido", "micLabel", "hasMic", "error")})
                assert e["micLabel"] == otra, "no cambió de micrófono"
                print("   guardado        :", await p.js("localStorage.getItem('companion.mic') === window.companion.audio.micId"))

            t0 = time.perf_counter()
            await p.js("document.getElementById('start-btn').click()")
            visto, pico, ultimo = set(), 0.0, None
            while time.perf_counter() - t0 < 50:
                await asyncio.sleep(0.5)
                e = await p.js(ESTADO)
                pico = max(pico, e["nivel"])
                clave = (e["estado"], e["tu"], e["mika"][:60])
                if clave != ultimo:
                    ultimo = clave
                    print(f"   [{time.perf_counter() - t0:5.1f}s] {e['estado']:9} tú={e['tu']!r} mika={e['mika'][:70]!r}")
                visto.add(e["estado"])
                if e["tu"] and e["mika"] and e["estado"] == "idle":
                    break
            print(f"4. conversación    : estados={sorted(visto)} · nivel máximo del micrófono={pico:.3f}")
            assert e["tu"], "el companion no oyó la pregunta del micrófono"
            assert e["mika"], "no hubo respuesta"
            print("OK: el micrófono del navegador llega al companion y Mika responde.")
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    with _prueba.Servidor():
        asyncio.run(main())
