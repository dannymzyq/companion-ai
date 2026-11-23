"""Prueba el micrófono y la cámara FÍSICOS en la app de escritorio, sin que se vea ni se oiga nada.

Hace lo mismo que una persona al abrir a Mika: elige el micrófono y la cámara en la tarjeta de inicio, pulsa
«Empezar a hablar» y comprueba durante unos segundos que el micrófono entrega sonido y la cámara imagen.
Sirve para dispositivos que son micrófono y cámara a la vez (una webcam).

Nada sale de la PC ni llega a ningún modelo: el servidor de prueba arranca sin clave de Gemini y sin modelo
local, con la mirada en vivo apagada y sin saludo. La luz de la cámara se enciende mientras dura la prueba.

    .venv\\Scripts\\python.exe scripts\\pruebas\\prueba_dispositivos.py --mic BRIO --cam BRIO
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _prueba  # noqa: E402  (antes que companion.*: aísla datos, modelos y puerto)

# Sin cerebro (ni nube ni local) y con el oído más ligero en la CPU: la prueba no toca la GPU ni gasta cuota.
os.environ.update(LLM_PROVIDER="gemini", GEMINI_API_KEY="", LOCAL_FALLBACK="false", STT_DEVICE="cpu", STT_MODEL="tiny")

from prueba_escritorio import ELECTRON, PORT, ROOT, Pagina, pagina  # noqa: E402

ESTADO = """(() => { const c = window.companion, a = c.audio, v = c.vision.sources.camera;
  const t = a.stream && a.stream.getAudioTracks()[0], k = v && v.stream.getVideoTracks()[0];
  return { mic: a.hasMic, micNombre: a.micLabel || null, micPista: t ? t.readyState + (t.muted ? ' (sin señal)' : '') + (t.enabled ? '' : ' (desactivada)') : null,
           nivel: +a.micLevel.toFixed(5), contexto: a.ctx ? a.ctx.state : null,
           camara: c.vision.active('camera'), camPista: k ? k.readyState + (k.muted ? ' (sin señal)' : '') : null,
           camNombre: k ? k.label : null, ancho: v ? v.video.videoWidth : 0, alto: v ? v.video.videoHeight : 0,
           kb: Math.round((c.vision.grab('camera') || '').length * 0.75 / 1024),
           vista: !document.getElementById('preview-camera').hidden && document.querySelector('#preview-camera video').videoWidth > 0,
           aviso: document.getElementById('toast').hidden ? null : document.getElementById('toast').textContent,
           errorMic: document.getElementById('mic-error').hidden ? null : document.getElementById('mic-error').textContent }; })()"""

# Dos segundos de micrófono: nivel máximo y cuántas lecturas fueron silencio absoluto (señal de micrófono muerto).
MUESTRA = """(async () => { const a = window.companion.audio; let max = 0, n = 0, ceros = 0; const t0 = performance.now();
  while (performance.now() - t0 < 2000) { await new Promise(r => setTimeout(r, 40)); max = Math.max(max, a.micLevel); n++; if (a.micLevel === 0) ceros++; }
  return { max: +max.toFixed(5), silencio: ceros + '/' + n, pista: a.stream.getAudioTracks()[0].readyState }; })()"""

ELEGIR = """((id, texto) => { const s = document.getElementById(id);
  const o = [...s.options].find(o => o.text.toLowerCase().includes(texto.toLowerCase()) && !/^(predeterminado|default|comunicaciones|communications)/i.test(o.text))
         || [...s.options].find(o => o.text.toLowerCase().includes(texto.toLowerCase()));
  if (!o) return null; s.value = o.value; s.dispatchEvent(new Event('change')); return o.text; })"""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mic", default="BRIO", help="texto que contiene el nombre del micrófono")
    ap.add_argument("--cam", default="BRIO", help="texto que contiene el nombre de la cámara")
    ap.add_argument("--segundos", type=float, default=10, help="cuánto observar tras empezar")
    ap.add_argument("--orden", choices=["mic-cam", "cam-mic"], default="mic-cam", help="qué se elige primero")
    args = ap.parse_args()
    if not ELECTRON.exists():
        sys.exit("Falta Electron: ejecuta scripts\\instalacion\\instalar_escritorio.ps1")

    env = {**os.environ, "COMPANION_TEST": "1", "COMPANION_TEST_PORT": str(PORT), "COMPANION_URL": _prueba.URL,
           "COMPANION_TEST_REAL_MEDIA": "1"}
    env.pop("ELECTRON_RUN_AS_NODE", None)
    proc = subprocess.Popen([str(ELECTRON), str(ROOT / "desktop")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url, _ = await pagina(_prueba.URL)
        async with connect(url, max_size=None) as ws:
            p = Pagina(ws)
            await p.cmd("Runtime.enable")
            await p.cmd("Page.enable")
            await asyncio.sleep(2)
            # perfil limpio, sin saludo y con la mirada en vivo apagada (ninguna imagen llega a un modelo)
            await p.js("['companion.cam', 'companion.cam.on', 'companion.mic'].forEach(k => localStorage.removeItem(k)); localStorage.setItem('companion.watch', '0'); null")
            await p.cmd("Page.navigate", url=f"{_prueba.URL}/?saludo=0")
            await asyncio.sleep(4)
            await p.js("document.getElementById('mic-allow').hidden ? null : document.getElementById('mic-allow').click()")
            await asyncio.sleep(2.5)
            listas = await p.js("({mics: [...document.getElementById('mic-select').options].map(o => o.text), cams: [...document.getElementById('cam-select').options].map(o => o.text)})")
            print("1. dispositivos    :", listas)
            assert await p.js("typeof window.companion.audio.heal === 'function'"), "la ventana cargó una versión antigua de la interfaz (caché)"

            pasos = [("mic-select", args.mic, "micrófono"), ("cam-select", args.cam, "cámara")]
            for selector, texto, nombre in (pasos if args.orden == "mic-cam" else pasos[::-1]):
                elegido = await p.js(f"{ELEGIR}({json.dumps(selector)}, {json.dumps(texto)})")
                assert elegido, f"no hay ningún {nombre} cuyo nombre contenga «{texto}»"
                await asyncio.sleep(3)
                print(f"2. elegido {nombre:9}: {elegido!r}")
            antes = await p.js(ESTADO)
            prueba = await p.js("({visible: !document.getElementById('cam-test').hidden, ancho: document.getElementById('cam-test').videoWidth, ayuda: document.getElementById('cam-help').textContent})")
            pico = 0.0
            for _ in range(10):
                await asyncio.sleep(0.3)
                pico = max(pico, (await p.js(ESTADO))["nivel"])
            print(f"3. antes de empezar: micrófono abierto={antes['mic']} ({antes['micNombre']}) · pista={antes['micPista']} · nivel máximo={pico} · "
                  f"vista de prueba de la cámara={prueba}")

            await p.js("document.getElementById('start-btn').click()")
            pico, ultimo, muestras = 0.0, None, []
            for i in range(int(args.segundos / 0.5)):
                await asyncio.sleep(0.5)
                e = await p.js(ESTADO)
                pico = max(pico, e["nivel"])
                muestras.append(e["nivel"])
                clave = (e["mic"], e["micPista"], e["camara"], e["camPista"], e["ancho"], e["vista"], e["aviso"], e["errorMic"])
                if clave != ultimo:
                    ultimo = clave
                    print(f"   [{(i + 1) * 0.5:4.1f}s] {e}")
            print(f"4. tras empezar    : nivel máximo del micrófono={pico} · últimos niveles={muestras[-6:]}")
            servidor = (_prueba.TEST_DIR / "servidor.log").read_text(encoding="utf-8", errors="replace")
            print(f"   el servidor oyó voz {servidor.count('companion.session: STT')} vez/veces durante la prueba")
            ok_mic = e["mic"] and e["micPista"] == "live" and pico > 0
            ok_cam = e["camara"] and e["camPista"] == "live" and e["ancho"] > 0 and e["kb"] > 3 and e["vista"]

            # Apagar y encender la cámara con su botón: con una webcam eso reinicia también su micrófono,
            # que tiene que recuperarse solo en pocos segundos.
            for accion, espera in (("apagar la cámara", 10), ("encender la cámara", 8)):
                await p.js("document.getElementById('camera').click()")
                await asyncio.sleep(espera)
                m = await p.js(MUESTRA)
                e = await p.js(ESTADO)
                print(f"5. tras {accion:19}: cámara encendida={e['camara']} ({e['ancho']}x{e['alto']}) · micrófono {m} · "
                      f"reaperturas={await p.js('window.companion.audio.healLog.splice(0)')}")
                ok_mic = ok_mic and m["pista"] == "live" and m["max"] > 0
            ok_cam = ok_cam and e["camara"] and e["ancho"] > 0
            print(f"RESULTADO: micrófono {'OK' if ok_mic else 'FALLA'} · cámara {'OK' if ok_cam else 'FALLA'}")
            await p.js("window.companion.vision.stop('camera'); null")
            await asyncio.sleep(1)
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        _prueba.cerrar(proc)


if __name__ == "__main__":
    with _prueba.Servidor():
        asyncio.run(main())
