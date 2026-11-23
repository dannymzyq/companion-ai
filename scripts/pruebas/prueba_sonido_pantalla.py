"""Prueba el interruptor «Escuchar también el sonido» al compartir, en la app de escritorio, sin que se vea nada
(ventanas fuera de pantalla, servidor de prueba aislado) y sin cerebro: no se pregunta nada a ningún modelo.

Se comparte solo la tarjeta de prueba. El sonido de la PC se captura un par de segundos y se corta: menos que un
tramo de transcripción, así que nada llega a Whisper.

    .venv\\Scripts\\python.exe scripts\\pruebas\\prueba_sonido_pantalla.py
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _prueba  # noqa: E402
import prueba_escritorio as pe  # noqa: E402  (mismas piezas: Pagina, pagina, elegir)

ESTADO = """(() => { const v = window.companion.vision, s = v.sources.screen, b = document.getElementById('screen-sound');
    return { compartiendo: !!s, pistas_audio: s ? s.stream.getAudioTracks().length : 0, boton: !b.hidden,
             silenciado: b.classList.contains('off'),
             rotulo: document.querySelector('#preview-screen figcaption').textContent }; })()"""


async def compartir(p, con_sonido: bool, pensar: float = 0) -> dict:
    """`pensar`: segundos que tarda en elegir (el sonido se pide después de la imagen, ya sin el clic reciente)."""
    await p.js("window.__c = window.companion.vision.start('screen').then(() => 'ok', (e) => e.name); null")
    eleccion = (f"await new Promise(r => setTimeout(r, {int(pensar * 1000)})); "
                f"document.getElementById('sound-on').checked = {json.dumps(con_sonido)}; "
                f"[...document.querySelectorAll('#windows .card')].find(c => c.title === {json.dumps(pe.TARJETA)}).click()")
    await pe.elegir(f"(async () => {{ {eleccion} }})()")
    assert await p.js("window.__c") == "ok", "no se pudo compartir la tarjeta"
    await asyncio.sleep(0.8)
    return await p.js(ESTADO)


async def main():
    env = {**os.environ, "COMPANION_TEST": "1", "COMPANION_TEST_PORT": str(pe.PORT), "COMPANION_URL": pe.API,
           "COMPANION_TEST_CARD": "1"}
    env.pop("ELECTRON_RUN_AS_NODE", None)
    proc = subprocess.Popen([str(pe.ELECTRON), str(_prueba.ROOT / "desktop")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fallos = []

    def ok(nombre, cond, detalle):
        print(f"{'OK ' if cond else 'MAL'} {nombre}: {detalle}")
        if not cond:
            fallos.append(nombre)
    try:
        url, _ = await pe.pagina(pe.API)
        async with connect(url, max_size=None) as ws:
            p = pe.Pagina(ws)
            await p.cmd("Runtime.enable")
            await asyncio.sleep(3)

            # 1) el selector ofrece el interruptor
            await p.js("window.__c = window.companion.vision.start('screen').then(() => 'ok', (e) => e.name); null")
            url_sel, _ = await pe.pagina("picker.html")
            async with connect(url_sel, max_size=None) as ws2:
                q = pe.Pagina(ws2)
                await q.cmd("Runtime.enable")
                for _ in range(40):
                    if await q.js("document.body.dataset.ready === '1'"):
                        break
                    await asyncio.sleep(0.25)
                await asyncio.sleep(0.3)
                sel = await q.js("({ visible: !document.getElementById('sound').hidden, texto: document.querySelector('#sound b').textContent })")
                try:
                    await q.js("window.picker.cancel(); null")
                except Exception:  # noqa: BLE001
                    pass
            await asyncio.sleep(0.6)
            ok("interruptor en el selector", sel["visible"] and "sonido" in sel["texto"], sel)

            # 2) sin sonido: solo imagen
            e = await compartir(p, False)
            ok("sin sonido", e["compartiendo"] and e["pistas_audio"] == 0 and not e["boton"] and "oye" not in e["rotulo"], e)
            await p.js("window.companion.vision.stop('screen')")

            # 3) con sonido: pista de audio, botón del altavoz y rótulo; el botón lo silencia sin dejar de compartir
            e = await compartir(p, True, pensar=6)
            avisos = await p.js("[...document.querySelectorAll('.toast, #toast')].map(t => t.textContent).join(' | ')")
            ok("con sonido (tras 6 s eligiendo)", not e.get("error") and "No pude" not in (avisos or ""), avisos or "sin avisos")
            ok("con sonido", e["compartiendo"] and e["pistas_audio"] == 1 and e["boton"] and "oye el sonido" in e["rotulo"], e)
            await p.js("document.getElementById('screen-sound').click()")
            e2 = await p.js(ESTADO)
            ok("silenciar sin dejar de compartir", e2["compartiendo"] and e2["silenciado"] and "oye" not in e2["rotulo"], e2)
            await p.js("window.companion.vision.stop('screen')")

            # 4) si Windows no entrega el sonido, la imagen sigue compartida y el aviso dice el motivo
            await p.js("""(() => { const real = navigator.mediaDevices.getDisplayMedia.bind(navigator.mediaDevices); let n = 0;
                navigator.mediaDevices.getDisplayMedia = (c) => (++n === 2
                    ? Promise.reject(new DOMException('Could not start audio source', 'NotReadableError')) : real(c)); })(); null""")
            e = await compartir(p, True)
            aviso = await p.js("document.getElementById('toast').textContent")
            ok("si el sonido falla, sigue la imagen", e["compartiendo"] and e["pistas_audio"] == 0 and not e["boton"]
               and "NotReadableError" in aviso and "ve la imagen igual" in aviso, aviso)
            await p.js("window.companion.vision.stop('screen'); delete navigator.mediaDevices.getDisplayMedia; null")

            # 5) se recuerda la elección: la próxima vez el interruptor sale encendido
            await p.js("window.__c = window.companion.vision.start('screen').then(() => 'ok', (e) => e.name); null")
            url_sel, _ = await pe.pagina("picker.html")
            async with connect(url_sel, max_size=None) as ws2:
                q = pe.Pagina(ws2)
                await q.cmd("Runtime.enable")
                await asyncio.sleep(1)
                recordado = await q.js("document.getElementById('sound-on').checked")
                await q.js("document.getElementById('sound-on').checked = false; null")
                try:
                    await q.js("window.picker.cancel(); null")
                except Exception:  # noqa: BLE001
                    pass
            ok("recuerda la última elección", recordado is True, recordado)
            await asyncio.sleep(0.5)
            errores = await p.js("window.__c")
            ok("cancelar sigue funcionando", errores == "AbortError", errores)
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        _prueba.cerrar(proc)
    print("\nTodo bien." if not fallos else f"\nFALLOS: {fallos}")
    return 1 if fallos else 0


if __name__ == "__main__":
    with _prueba.Servidor():
        sys.exit(asyncio.run(main()))
