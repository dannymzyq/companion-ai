"""Prueba la mascota de escritorio (modo flotante) sin que se vea nada: la app de prueba usa una pantalla inventada
fuera de la tuya (x=-4000) y ventanas inventadas (nunca mira las de verdad), sin sonido, sin ratón ni teclado
reales y sin cerebro. Servidor de prueba en el 8201.

Comprueba: gravedad (cae a la «barra de tareas»), paseo, sentarse sobre una ventana y seguirla, caer cuando se
minimiza, acompañar una acción «controlar» (va al lado de la ventana, de espaldas, teclea y vuelve), reacciones al
tocarla, seguir el ratón y la hoja de contactos de las poses nuevas (data/prueba/mascota_poses.png).

    .venv\\Scripts\\python.exe scripts\\prueba_mascota.py
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

import _prueba  # noqa: E402

ROOT = _prueba.ROOT
API = _prueba.URL
PORT = 9337
ELECTRON = ROOT / "desktop" / "electron" / "electron.exe"
SUELO = -4000 + 900                      # borde de arriba de la «barra de tareas» de la pantalla inventada


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


async def esperar(p: Pagina, expr: str, segundos: float = 20, que: str = ""):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if await p.js(expr):
            return
        await asyncio.sleep(0.25)
    raise SystemExit(f"No se cumplió ({que or expr})")


ESTADO = """(async () => { const i = await window.desktop.pet.info(), w = await window.desktop.info(), a = window.companion.avatar.anchors();
  return { modo: i.mode, act: window.companion.avatar.act.name, bounds: w.bounds, pies: w.bounds.y + a.feet.y,
           asiento: w.bounds.y + a.seat.y, x: w.bounds.x + a.feet.x, yaw: window.companion.avatar.yaw, info: i,
           ui: !document.body.classList.contains('pet-moving') }; })()"""


def escena(fg=None, ventanas=None):
    return json.dumps({"fg": fg, "windows": ventanas or {}})


async def main():
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
            p = Pagina(ws)
            await p.cmd("Runtime.enable")
            await esperar(p, "!!(window.companion && window.companion.avatar && window.companion.avatar.loaded)", 40, "modelo cargado")
            await p.js("window.companion.savePet({follow: true, react: true, gravity: true, walk: 'nunca', sit: false, work: true, fade: false}); null")
            await p.js("document.getElementById('float-btn').click(); null")
            await esperar(p, "document.body.classList.contains('floating')")
            await esperar(p, "window.desktop.pet.info().then(i => i.anchors)", 10, "la app recibe los pies")
            await p.js("window.companion.avatar.hobbyOn = false; null")    # sin pasatiempos: un salto movería los pies
            await asyncio.sleep(1.5)

            # ---------------- gravedad
            e = await p.js(ESTADO)
            print(f"1. al flotar       : pies en y={e['pies']} (suelo {SUELO}) · modo={e['modo']}")
            assert abs(e["pies"] - SUELO) <= 2 and e["modo"] == "stand"
            await p.js("window.desktop.pet.test({cmd: 'lift', dy: 350}); null")
            await asyncio.sleep(0.15)
            cayendo = await p.js(ESTADO)
            await esperar(p, "window.desktop.pet.info().then(i => i.mode === 'stand')", 5, "aterriza")
            muestras = []
            for _ in range(8):
                muestras.append(round(await p.js("window.companion.avatar.anchors().feet.y"), 1))
                await asyncio.sleep(0.2)
            print(f"   pies en la página tras aterrizar: {muestras}")
            e = await p.js(ESTADO)
            print(f"2. gravedad        : en el aire modo={cayendo['modo']}/{cayendo['act']} → pies en y={e['pies']} (app {e['info']['feetY']}, página {e['pies'] - e['bounds']['y']}) · {e['act']}")
            assert cayendo["modo"] == "fall" and abs(e["pies"] - SUELO) <= 2
            # Fluidez (17 nov 2026): antes, setInterval(16) daba ~32 cuadros por segundo en Windows.
            print(f"2b. fluidez        : caída a {e['info']['lastMoveFps']} (fps, % de cuadros marcados por la página) · barra cayendo={cayendo['ui']} → tras aterrizar={e['ui']}")
            assert e["info"]["lastMoveFps"]["fps"] >= 50 and not cayendo["ui"] and e["ui"]

            # ---------------- paseo
            await p.js("window.companion.savePet({walk: 'amenudo'}); null")
            x0 = (await p.js(ESTADO))["x"]
            await p.js("window.desktop.pet.test({cmd: 'walk'}); null")
            await asyncio.sleep(0.2)
            andando = await p.js(ESTADO)
            await esperar(p, "window.desktop.pet.info().then(i => i.mode === 'stand')", 15, "termina el paseo")
            e = await p.js(ESTADO)
            print(f"3. paseo           : {andando['modo']}/{andando['act']} giro={andando['yaw']:.2f} · x {x0:.0f} → {e['x']:.0f} · pies {e['pies']:.0f} · {e['modo']} · app {e['info']['feetY']} · bounds {e['bounds']}")
            assert andando["modo"] == "walk" and andando["act"] == "walk" and abs(e["x"] - x0) > 50 and abs(e["pies"] - SUELO) <= 2
            print(f"3b. barra          : paseando={andando['ui']} · al acabar={e['ui']} · paseo a {e['info']['lastMoveFps']}")
            assert not andando["ui"] and e["ui"] and e["info"]["lastMoveFps"]["fps"] >= 50
            await p.js("window.companion.savePet({walk: 'nunca'}); null")

            # ---------------- sentarse sobre una ventana inventada
            v = {"id": 7, "rect": [-3500, -3600, -2900, -3250], "minimized": False, "maximized": False, "fullscreen": False, "own": False}
            await p.js("window.companion.savePet({sit: true}); null")
            await p.js(f"window.desktop.pet.testScene({escena(v, {7: v})}); null")
            await esperar(p, "window.desktop.pet.info().then(i => i.mode === 'sit')", 8, "salta a sentarse")
            await asyncio.sleep(0.4)
            e = await p.js(ESTADO)
            print(f"4. sentarse        : modo={e['modo']}/{e['act']} · asiento y={e['asiento']} (borde {v['rect'][1]}) · x={e['x']:.0f}")
            assert e["act"] == "sit" and abs(e["asiento"] - v["rect"][1]) <= 2 and v["rect"][0] < e["x"] < v["rect"][2]
            movida = {**v, "rect": [-3300, -3500, -2700, -3150]}
            await p.js(f"window.desktop.pet.testScene({escena(movida, {7: movida})}); null")
            await asyncio.sleep(1.5)
            e = await p.js(ESTADO)
            print(f"5. la sigue        : asiento y={e['asiento']} (borde {movida['rect'][1]})")
            assert abs(e["asiento"] - movida["rect"][1]) <= 2
            minimizada = {**movida, "minimized": True}
            await p.js(f"window.desktop.pet.testScene({escena(None, {7: minimizada})}); null")
            await esperar(p, "window.desktop.pet.info().then(i => i.mode === 'stand')", 8, "cae al minimizar")
            e = await p.js(ESTADO)
            print(f"6. minimizada      : cae al suelo · pies y={e['pies']}")
            assert abs(e["pies"] - SUELO) <= 2
            await p.js("window.companion.savePet({sit: false}); null")
            await p.js(f"window.desktop.pet.testScene({escena()}); null")

            # ---------------- acompañar una acción «controlar» (eventos simulados: no se maneja ninguna ventana)
            casa = await p.js(ESTADO)
            ventana = {"rect": [-3950, -3900, -3500, -3300], "minimized": False, "maximized": False}
            await p.js("window.companion.handle({type: 'control_start', title: 'Ventana de prueba', task: 'probar', max: 25, "
                       f"window: {json.dumps(ventana)}}}); null")
            await esperar(p, "window.desktop.pet.info().then(i => i.mode === 'work')", 8, "va a la ventana")
            await asyncio.sleep(1.4)
            e = await p.js(ESTADO)
            print(f"7. trabajar        : modo={e['modo']}/{e['act']} · x={e['x']:.0f} (ventana hasta {ventana['rect'][2]}) · giro={e['yaw']:.2f} "
                  f"· clics al modelo={not (await p.js('window.companion.status().petWorking'))}")
            assert e["act"] == "work" and e["x"] > ventana["rect"][2] and abs(e["yaw"]) > 2 and await p.js("window.companion.status().petWorking")
            assert not e["ui"], "trabajando no debe verse la barra"
            await p.js("window.companion.handle({type: 'control_step', n: 1, max: 25, text: 'Escribir', kind: 'type', point: null}); null")
            await asyncio.sleep(0.5)
            modo = await p.js("window.companion.avatar.workMode")
            # Mano de puntero (16 nov 2026): cada paso con punto la lleva a él, con la postura según su altura.
            posturas = []
            for punto, que in (([-3700, -3250], "abajo"), ([-3600, -3880], "arriba")):
                await p.js(f"window.companion.handle({{type: 'control_step', n: 2, max: 25, text: 'Pulsar', kind: 'click', point: {punto}}}); null")
                await esperar(p, f"window.desktop.pet.info().then(i => i.activity === 'work' && i.hand && Math.hypot(i.hand.x - ({punto[0]}), i.hand.y - ({punto[1]})) < 14)",
                              10, f"la mano llega al punto de {que}")
                i = await p.js("window.desktop.pet.info()")
                posturas.append(await p.js("window.companion.avatar.stance"))
                print(f"7b. punto {que:<7}: postura={posturas[-1]} · mano a {abs(i['hand']['x'] - punto[0]):.0f},{abs(i['hand']['y'] - punto[1]):.0f} px del punto")
            assert posturas[0] in ("crouch", "kneel") and posturas[1] == "reach"
            await p.js("window.companion.handle({type: 'control_end', ok: true, text: 'hecho'}); null")
            await asyncio.sleep(0.8)
            fin = await p.js(ESTADO)
            await p.js("window.desktop.pet.state('speaking'); null")         # cuenta el resultado…
            await asyncio.sleep(0.4)
            await p.js("window.desktop.pet.state('idle'); null")             # …y vuelve a su sitio
            await esperar(p, "window.desktop.pet.info().then(i => !i.working && i.mode === 'stand')", 8, "vuelve a casa")
            e = await p.js(ESTADO)
            print(f"8. paso y vuelta   : teclea={modo == 'type'} · al terminar {fin['act']} · vuelve a x={e['x']:.0f} (estaba en {casa['x']:.0f})")
            assert modo == "type" and fin["act"] == "none" and abs(e["x"] - casa["x"]) <= 2 and abs(e["pies"] - SUELO) <= 2
            assert e["ui"], "de vuelta, la barra vuelve"

            # ---------------- acercada o alejada con Ctrl + rueda: la barra sigue a la vista (sobre la barra de tareas)
            for factor in (0.5, 1.9):
                await p.js("window.companion.avatar.resetView(); null")
                await asyncio.sleep(0.8)
                await p.js(f"window.companion.avatar.zoom({factor}); null")
                await asyncio.sleep(1.8)
                z = await p.js("""(async () => { const w = await window.desktop.info(), r = document.querySelector('.controls').getBoundingClientRect();
                  return { abajo: w.bounds.y + r.bottom, arriba: w.bounds.y + r.top, corte: getComputedStyle(document.body).getPropertyValue('--pet-cut-bottom'),
                           vb: w.bounds.y + w.bounds.height, pies: w.bounds.y + window.companion.avatar.anchors().feet.y }; })()""")
                print(f"8b. zoom ×{factor}       : pies y={z["pies"]:.0f} · ventana hasta y={z['vb']} (suelo {SUELO}) · fuera {z['corte']} · barra y={z['arriba']:.0f}..{z['abajo']:.0f}")
                assert z["abajo"] <= SUELO + 1 and z["vb"] >= SUELO - 2, "la barra se ve y la ventana llega al suelo"
            await p.js("window.companion.avatar.resetView(); null")
            await asyncio.sleep(1)
            # ---------------- ventana al mínimo (rueda): la barra encoge y cabe entera
            for _ in range(12):
                await p.js("window.desktop.resize(-1); null")
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.8)
            m = await p.js("""(() => { const r = document.querySelector('footer > .controls').getBoundingClientRect();
              return { izq: r.left, der: r.right, ancho: innerWidth, zoom: document.querySelector('footer > .controls').style.zoom }; })()""")
            print(f"8c. ventana mínima : ancho {m['ancho']} px · barra {m['izq']:.0f}..{m['der']:.0f} · escala {m['zoom']}")
            assert m["izq"] >= 0 and m["der"] <= m["ancho"], "la barra cabe en la ventana"
            for _ in range(12):
                await p.js("window.desktop.resize(1); null")
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.8)

            # ---------------- le entra sueño: va a una esquina y se recuesta con la tablet o el móvil (17 nov 2026)
            x0 = (await p.js(ESTADO))["x"]
            await p.js("document.getElementById('keyboard').click(); null")   # el chat abierto…
            await p.js("window.companion.avatar.sleepNow('lean'); null")
            chat = await p.js("!document.getElementById('text-form').hidden")   # …se cierra al dormirse
            await esperar(p, "window.companion.avatar.sleep.ready", 25, "llega a la esquina")
            await asyncio.sleep(3.5)
            e = await p.js(ESTADO)
            dev = await p.js("(() => { const d = window.companion.avatar.device; "
                             "return d ? {kind: d.kind, visible: d.group.visible} : null; })()")
            png = base64.b64decode((await p.cmd("Page.captureScreenshot", format="png"))["data"])
            (_prueba.TEST_DIR / "mascota_recostada.png").write_bytes(png)
            print(f"8d. sueño          : de x={x0:.0f} a x={e['x']:.0f} (pantalla -4000..-2400) · {dev} · "
                  f"mascota={e['info']['mode']} · {_prueba.TEST_DIR / 'mascota_recostada.png'}")
            b = e["bounds"]
            assert not chat, "al dormirse se cierra el chat"
            assert dev and dev["visible"] and (abs(b["x"] + 4000) <= 4 or abs(b["x"] + b["width"] + 2400) <= 4), "en una esquina, con la pantalla en la mano"
            await p.js("window.companion.avatar.wake(); null")
            await esperar(p, "!window.companion.avatar.sleeping", 8, "se despierta")
            await asyncio.sleep(1.5)

            # ---------------- tocarla y seguir el ratón
            await p.js("window.companion.avatar.gestures = []; window.companion.avatar.react('head'); null")
            g = await p.js("window.companion.avatar.gestures.map(g => g.name)")
            # Toques repetidos (16 nov 2026): al 6.º seguido en la cabeza, nivel 3 y corazones grandes.
            n = await p.js("(() => { const a = window.companion.avatar; let r; for (let i = 0; i < 5; i++) r = a.react('head'); "
                           "return {level: r.level, hearts: a.effects.parts.filter(q => q.kind === 'heart' && q.size > 0.6).length}; })()")
            print(f"9b. toques seguidos: nivel {n['level']} · corazones grandes {n['hearts']}")
            assert n["level"] == 3 and n["hearts"] >= 4
            await p.js("window.companion.avatar.setCursor(-2000, 100); null")
            await asyncio.sleep(1.2)
            seguir = await p.js("window.companion.avatar.followW")
            print(f"9. tocar y mirar   : gesto al tocar la cabeza={g} · sigue el ratón={seguir:.2f}")
            assert g and g[0] in ("risita", "_mimos", "_toque") and seguir > 0.5

            # ---------------- transparencia: se ve entera con el ratón encima
            await p.js("window.companion.savePet({alpha: 60}); document.body.classList.remove('hover'); null")
            await asyncio.sleep(0.5)
            lejos = await p.js("getComputedStyle(document.getElementById('canvas')).opacity")
            await p.js("document.body.classList.add('hover'); null")
            await asyncio.sleep(0.5)
            encima = await p.js("getComputedStyle(document.getElementById('canvas')).opacity")
            print(f"10. transparencia  : 60 % → opacidad {lejos} lejos del ratón · {encima} con el ratón encima")
            assert abs(float(lejos) - 0.4) < 0.02 and float(encima) == 1
            await p.js("window.companion.savePet({alpha: 0}); null")

            # ---------------- hoja de contactos de las poses nuevas
            await p.js("window.desktop.float(false); null")
            await esperar(p, "!document.body.classList.contains('floating')")
            await asyncio.sleep(0.8)
            png = await p.js("""window.companion.avatar.sheet([
                {activity: 'walk', opts: {dir: 1}, label: 'andar'}, {activity: 'walk', opts: {dir: -1}, phase: 2.4, label: 'andar (otro paso)'},
                {activity: 'carried', label: 'en brazos'}, {activity: 'fall', label: 'cayendo'},
                {activity: 'sit', label: 'sentada'}, {activity: 'work', work: 'type', opts: {side: 1}, label: 'trabajando: teclea'},
                {activity: 'work', work: 'click', opts: {side: -1}, label: 'trabajando: señala'}, {gesture: '_aterrizar', at: 0.25, label: 'aterriza'}
            ], 4, 300, 460).toDataURL('image/png')""")
            salida = _prueba.TEST_DIR / "mascota_poses.png"
            salida.write_bytes(base64.b64decode(png.split(",", 1)[1]))
            esfera = await p.js("""(() => { const a = window.companion.avatar; a.loadOrb(); return a.sheet([
                {activity: 'walk', label: 'andar'}, {activity: 'carried', label: 'en brazos'}, {activity: 'sit', label: 'sentada'},
                {activity: 'work', work: 'type', opts: {side: 1}, label: 'trabajando'}], 4, 240, 300).toDataURL('image/png'); })()""")
            (_prueba.TEST_DIR / "mascota_esfera.png").write_bytes(base64.b64decode(esfera.split(",", 1)[1]))
            print(f"11. poses          : {salida} · esfera: {_prueba.TEST_DIR / 'mascota_esfera.png'}")
        print("OK: gravedad, paseo, sentarse y seguir la ventana, acompañar una acción y reacciones.")
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)


if __name__ == "__main__":
    with _prueba.Servidor():
        asyncio.run(main())
