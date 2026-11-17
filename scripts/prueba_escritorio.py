"""Prueba la app de escritorio (Electron) sin que se vea ni se oiga nada: las ventanas se abren fuera de la
pantalla, en silencio, con micrófono y cámara simulados y un perfil aparte. Usa su propio servidor de prueba
(scripts/_prueba.py), no el companion real.

Comprueba: modelos propios (subir, elegir, quitar), cámara → el LLM describe lo que ve, captura de pantalla
(solo que funciona; esa imagen no se envía a ningún sitio), y el modo flotante (ventana transparente y siempre
encima, clics que atraviesan el fondo, cambio de tamaño y vuelta a la ventana normal).

    .venv\\Scripts\\python.exe scripts\\prueba_escritorio.py
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
from maniqui_vrm import build as maniqui  # noqa: E402

if "--local" in sys.argv:                 # todo el recorrido con el cerebro local (Ollama) en vez de Gemini
    os.environ["LLM_PROVIDER"] = "local"
os.environ.update(WATCH_INTERVAL="3", WATCH_GAP="6")     # mirada en vivo: más seguida, para no alargar la prueba

ROOT = _prueba.ROOT
API = _prueba.URL
PORT = 9334
ELECTRON = ROOT / "desktop" / "electron" / "electron.exe"
TARJETA = "Tarjeta de prueba del companion"      # ventana propia con un texto conocido (desktop/tarjeta-prueba.html)


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


async def pagina(contiene: str, espera: float = 15):
    """Se conecta a la ventana cuya dirección contiene ese texto (las ventanas cambian al flotar y al volver)."""
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        try:
            for t in httpx.get(f"http://127.0.0.1:{PORT}/json/list", timeout=2).json():
                if t["type"] == "page" and contiene in t["url"]:
                    return t["webSocketDebuggerUrl"], t["url"]
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.3)
    raise SystemExit(f"No apareció la ventana con «{contiene}»")


async def preguntar(p: Pagina, texto: str, espera: float = 60) -> str:
    """Escribe una pregunta y devuelve lo que Mika responde (las dos últimas frases, que es lo que muestra la interfaz)."""
    await p.js(f"window.companion.send({{type: 'text', text: {json.dumps(texto)}}}); null")
    limite, visto = time.monotonic() + espera, ""
    while time.monotonic() < limite:
        await asyncio.sleep(0.5)
        e = await p.js("({s: window.companion.status().state, tu: document.getElementById('user-line').textContent, "
                       "m: document.getElementById('mika-line').textContent})")
        if e["tu"] == texto and e["m"]:
            visto = e["m"]
            if e["s"] == "idle":
                break
    return visto


async def elegir(accion: str) -> dict:
    """Abre la ventana «¿Qué quieres que vea Mika?», cuenta lo que ofrece y ejecuta en ella `accion`.
    Los títulos de las ventanas reales no salen de esa ventana: aquí solo se cuentan."""
    url, _ = await pagina("picker.html")
    async with connect(url, max_size=None) as ws:
        q = Pagina(ws)
        await q.cmd("Runtime.enable")
        for _ in range(40):
            if await q.js("document.body.dataset.ready === '1'"):
                break
            await asyncio.sleep(0.25)
        lista = await q.js(f"""(() => {{ const t = [...document.querySelectorAll('#windows .card')].map(c => c.title);
            return {{ pantallas: document.querySelectorAll('#screens .card').length, ventanas: t.length,
                      tarjeta: t.includes({json.dumps(TARJETA)}), mika: t.includes('Mika') }}; }})()""")
        try:
            await q.js(accion + "; null")
        except Exception:  # noqa: BLE001  (la ventana se cierra al elegir)
            pass
    await asyncio.sleep(0.8)
    return lista


def prueba_modelos():
    c = httpx.Client(base_url=API, timeout=30)
    antes = c.get("/api/models").json()
    assert all(b["available"] for b in antes["builtin"]), "falta un avatar incluido"
    r = c.post("/api/models", params={"filename": "Maniquí de prueba.vrm"}, content=maniqui(False))
    assert r.status_code == 200, r.text
    nuevo = r.json()
    assert nuevo["active"] == nuevo["id"] and any(m["id"] == nuevo["id"] for m in nuevo["custom"])
    propio = c.get("/api/model").content
    assert len(propio) < 100_000, "no se está sirviendo el modelo propio"
    assert c.post("/api/models", params={"filename": "roto.vrm"}, content=b"esto no es un vrm").status_code == 400
    assert c.post("/api/models/select", json={"id": "avatar1"}).json()["active"] == "avatar1"
    assert len(c.get("/api/model").content) > 1_000_000, "no volvió al avatar incluido"
    assert c.delete("/api/models/avatar1").status_code == 400, "se dejó borrar un avatar incluido"
    despues = c.delete(f"/api/models/{nuevo['id']}").json()
    assert despues["active"] == "avatar1" and len(despues["custom"]) == len(antes["custom"])
    print(f"1. modelos         : subir «{nuevo['meta']['name']}» → activo, VRM inválido rechazado, vuelta a "
          f"«Avatar 1», el incluido no se puede borrar, propio quitado. OK")


async def main():
    if not ELECTRON.exists():
        sys.exit("Falta Electron: ejecuta scripts\\instalar_escritorio.ps1")
    prueba_modelos()

    env = {**os.environ, "COMPANION_TEST": "1", "COMPANION_TEST_PORT": str(PORT), "COMPANION_URL": API, "COMPANION_TEST_CARD": "1"}
    env.pop("ELECTRON_RUN_AS_NODE", None)
    proc = subprocess.Popen([str(ELECTRON), str(ROOT / "desktop")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # ---------------- ventana normal
        url, _ = await pagina(API)
        async with connect(url, max_size=None) as ws:
            p = Pagina(ws)
            await p.cmd("Runtime.enable")
            await asyncio.sleep(3)
            info = await p.js("window.desktop.info()")
            print(f"2. ventana normal  : Electron {info['electron']} · modo={info['mode']} · siempre encima={info['alwaysOnTop']} · "
                  f"botón flotar visible={not await p.js('document.getElementById(\"float-btn\").hidden')}")
            assert info["mode"] == "window" and not info["alwaysOnTop"]

            # perfil como recién instalado: sin cámara elegida ni ajustes de una prueba anterior
            await p.js("['companion.cam', 'companion.cam.on', 'companion.watch'].forEach(k => localStorage.removeItem(k)); location.reload(); null")
            await asyncio.sleep(4)
            await p.js("document.getElementById('mic-allow').hidden ? null : document.getElementById('mic-allow').click()")
            await asyncio.sleep(2.0)
            # al iniciar se elige también la cámara: «apagada» por defecto, y una vista de prueba al elegir una
            antes = await p.js("""({ selector: !document.getElementById('cam-picker').hidden, elegido: document.getElementById('cam-select').value,
                opciones: [...document.getElementById('cam-select').options].map(o => o.value === 'off' ? 'apagada' : o.value === 'ask' ? 'pedir permiso' : 'cámara') })""")
            await p.js("""(() => { const s = document.getElementById('cam-select'); s.value = [...s.options].find(o => !['off', 'ask'].includes(o.value)).value;
                s.dispatchEvent(new Event('change')); })()""")
            await asyncio.sleep(2.0)
            prueba = await p.js("!document.getElementById('cam-test').hidden && document.getElementById('cam-test').videoWidth > 0")
            print(f"3. inicio          : selector de cámara={antes} · vista de prueba al elegir una={prueba}")
            assert antes["selector"] and antes["elegido"] == "off" and "cámara" in antes["opciones"] and prueba

            await p.js("document.getElementById('start-btn').click()")
            await asyncio.sleep(3.0)
            st = await p.js("window.companion.status()")
            assert st["started"], "no arrancó la conversación"

            # la cámara elegida se enciende sola al empezar → el LLM dice lo que ve
            cam = await p.js("({activa: window.companion.vision.active('camera'), vista: !document.getElementById('preview-camera').hidden, "
                             "kb: Math.round((window.companion.vision.grab('camera') || '').length * 0.75 / 1024), "
                             "enAjustes: document.getElementById('cam-select-2').options.length})")
            print(f"   cámara          : {cam}")
            assert cam["activa"] and cam["vista"] and cam["kb"] > 1 and cam["enAjustes"] >= 1
            for _ in range(40):                       # espera a que termine el saludo
                if (await p.js("window.companion.status().state")) == "idle":
                    break
                await asyncio.sleep(0.5)
            await p.js("window.companion.vision.push('camera'); null")
            respuesta = await preguntar(p, "Mira la imagen de mi cámara y dime en una frase qué ves, con sus colores.")
            print(f"   Mika ve         : {respuesta!r}")
            assert respuesta, "no hubo respuesta con la cámara activa"

            # mirada en vivo: sin que nadie le hable, mira la cámara (la simulada se mueve) y comenta o calla
            registro, mirada = _prueba.TEST_DIR / "servidor.log", ""
            for _ in range(70):
                await asyncio.sleep(0.5)
                lineas = [x for x in registro.read_text(encoding="utf-8", errors="replace").splitlines() if "Mirada en vivo" in x]
                if lineas:
                    mirada = lineas[-1].split("Mirada en vivo", 1)[1]
                    break
            print(f"   mirada en vivo  : {mirada or 'no miró'}")
            assert mirada, "la mirada en vivo no se activó con la cámara encendida"
            await asyncio.sleep(4)
            await p.js("document.getElementById('watch').click()")      # se apaga para que no hable durante el resto de la prueba
            assert not await p.js("document.getElementById('watch').checked")
            for _ in range(40):
                if (await p.js("window.companion.status().state")) == "idle":
                    break
                await asyncio.sleep(0.5)

            # ---- compartir: la ventana de selección (pantallas y ventanas)
            compartir = "window.__compartir = window.companion.vision.start('screen').then(() => 'ok', (e) => e.name); null"
            medir = """(async () => { await new Promise(r => setTimeout(r, 1200)); const v = window.companion.vision, s = v.sources.screen;
                return { ancho: s.video.videoWidth, alto: s.video.videoHeight, detalle: v.detail('screen'),
                         rotulo: document.querySelector('#preview-screen figcaption').textContent,
                         kb: Math.round((v.grab('screen') || '').length * 0.75 / 1024) }; })()"""

            await p.js(compartir)
            lista = await elegir("document.getElementById('cancel').click()")
            cancelado = await p.js("window.__compartir")
            print(f"4. selector        : {lista['pantallas']} pantalla(s) y {lista['ventanas']} ventana(s) para elegir, "
                  f"tarjeta de prueba en la lista={lista['tarjeta']}, la propia Mika en la lista={lista['mika']} · "
                  f"al cancelar → {cancelado}, compartiendo={await p.js('window.companion.vision.active(\"screen\")')}")
            assert lista["pantallas"] >= 1 and lista["tarjeta"] and not lista["mika"], "la lista de fuentes no es la esperada"
            assert cancelado == "AbortError" and not await p.js("window.companion.vision.active('screen')")

            # una sola ventana (la tarjeta de prueba, no una ventana real): el LLM tiene que leer lo que hay en ella
            await p.js(compartir)
            await elegir(f"[...document.querySelectorAll('#windows .card')].find(c => c.title === {json.dumps(TARJETA)}).click()")
            assert await p.js("window.__compartir") == "ok", "no se pudo compartir la ventana"
            ventana = await p.js(medir)
            print(f"5. una ventana     : {ventana}")
            assert ventana["detalle"] == {"surface": "window", "name": TARJETA} and ventana["kb"] > 5 and TARJETA in ventana["rotulo"]
            assert ventana["ancho"] < 1400, "se capturó algo más grande que la ventana elegida"
            respuesta = await preguntar(p, "Mira la ventana que te comparto. ¿Qué título tiene la lista y cuál es el código de pedido?")
            print(f"   Mika ve         : {respuesta!r}")
            assert any(x in respuesta.lower() for x in ("7419", "siete", "compras")), "el LLM no leyó la ventana compartida"
            await p.js("document.querySelector('[data-stop=screen]').click()")
            assert not await p.js("window.companion.vision.active('screen')")

            # una pantalla entera: solo se comprueba la captura; se corta al momento y no se pregunta nada
            await p.js(compartir)
            await elegir("document.querySelector('#screens .card').click()")
            assert await p.js("window.__compartir") == "ok", "no se pudo compartir la pantalla"
            pantalla = await p.js(medir)
            await p.js("window.companion.vision.stop('screen')")
            print(f"6. una pantalla    : {pantalla} (captura local, detenida al instante)")
            assert pantalla["detalle"]["surface"] == "screen" and pantalla["ancho"] > ventana["ancho"] and pantalla["kb"] > 5

            await p.js("document.getElementById('float-btn').click()")     # con la cámara encendida

        # ---------------- ventana flotante
        url, direccion = await pagina(API)        # la misma página: al flotar no se recarga (16 nov 2026)
        async with connect(url, max_size=None) as ws:
            p = Pagina(ws)
            await p.cmd("Runtime.enable")
            await p.cmd("Page.enable")
            await asyncio.sleep(5)
            info = await p.js("window.desktop.info()")
            st = await p.js("({...window.companion.status(), clase: document.body.classList.contains('floating'), mic: window.companion.audio.hasMic, "
                            "camara: window.companion.vision.active('camera'), "
                            "cabecera: getComputedStyle(document.querySelector('header')).display, modelo: window.companion.avatar.loaded})")
            assert st["camara"], "la cámara no siguió encendida al pasar a flotante"
            print(f"7. flotante        : modo={info['mode']} · siempre encima={info['alwaysOnTop']} · {info['bounds']['width']}x{info['bounds']['height']} · {st}")
            assert info["mode"] == "float" and info["alwaysOnTop"] and st["clase"] and st["started"] and st["mic"] and st["modelo"]

            ancho, alto = info["bounds"]["width"], info["bounds"]["height"]
            await p.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=5, y=5)          # esquina: fondo transparente
            await asyncio.sleep(0.4)
            fuera = await p.js("({...window.companion.status(), barra: document.body.classList.contains('hover')})")
            await p.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=ancho // 2, y=int(alto * 0.45))   # sobre Mika
            await asyncio.sleep(0.4)
            dentro = await p.js("({...window.companion.status(), barra: document.body.classList.contains('hover')})")
            print(f"8. clics           : en el fondo → atraviesan={fuera['ignoring']} · sobre Mika → atraviesan={dentro['ignoring']}, botones visibles={dentro['barra']}")
            assert fuera["ignoring"] is True and dentro["ignoring"] is False and dentro["barra"]

            await p.js("window.desktop.resize(1); window.desktop.resize(1); null")
            await asyncio.sleep(0.5)
            grande = (await p.js("window.desktop.info()"))["bounds"]
            print(f"9. tamaño          : {ancho}x{alto} → {grande['width']}x{grande['height']}")
            assert grande["width"] > ancho

            await p.cmd("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
            png = base64.b64decode((await p.cmd("Page.captureScreenshot", format="png"))["data"])
            salida = ROOT / "data" / "flotante.png"
            salida.write_bytes(png)
            print(f"10. captura        : {salida} ({len(png) // 1024} KB)")

            await p.js("window.desktop.float(false); null")

        # ---------------- vuelta a la ventana normal
        url, direccion = await pagina(API)
        async with connect(url, max_size=None) as ws:
            p = Pagina(ws)
            await p.cmd("Runtime.enable")
            await asyncio.sleep(4)
            info = await p.js("window.desktop.info()")
            st = await p.js("window.companion.status()")
            cerebro = httpx.get(f"{API}/api/config", timeout=10).json()
            print(f"11. vuelta         : modo={info['mode']} · siempre encima={info['alwaysOnTop']} · conversación en marcha={st['started']}")
            assert info["mode"] == "window" and not info["alwaysOnTop"] and st["started"] and not st["floating"]
        gpu = cerebro.get("gpu") or {}
        print(f"OK: app de escritorio, cámara, selector de pantalla o ventana y modo flotante funcionan. "
              f"Cerebro: {cerebro['llm']['provider']} · {cerebro['llm']['model']} · memoria de vídeo {gpu.get('used')} de {gpu.get('total')} MB")
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)


if __name__ == "__main__":
    with _prueba.Servidor():
        asyncio.run(main())
