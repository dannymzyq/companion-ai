"""Prueba las acciones en la PC con permiso, sin hacer nada de verdad en la PC: el servidor de prueba corre con
COMPANION_ACTIONS_DRY=1 (comprueba y registra cada acción, pero no abre ni pulsa nada), una lista fija de
aplicaciones y una carpeta de archivos de prueba para las búsquedas. La interfaz va en la app de escritorio
oculta (fuera de pantalla y sin sonido). Usa el cerebro local (gemma4:e2b-it-qat): no la corras mientras se
conversa con el cerebro local.

    .venv\\Scripts\\python.exe scripts\\pruebas\\prueba_acciones.py
"""
import asyncio
import base64
import json
import re
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _prueba  # noqa: E402

ARCHIVOS = _prueba.TEST_DIR / "archivos"
APPS = [{"Name": "Spotify", "AppID": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"},
        {"Name": "Desinstalar Spotify", "AppID": "uninstall-spotify"},
        {"Name": "Calculadora", "AppID": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"},
        {"Name": "Google Chrome", "AppID": "Chrome"}]
os.environ.update(COMPANION_ACTIONS_DRY="1", COMPANION_ACTIONS_APPS=json.dumps(APPS),
                  COMPANION_ACTIONS_ROOTS=str(ARCHIVOS), LLM_PROVIDER="local", WATCH_INTERVAL="2")

from companion import actions, llm  # noqa: E402
from companion.config import settings  # noqa: E402
from prueba_escritorio import ELECTRON, PORT, ROOT, Pagina, pagina  # noqa: E402

MODELO = "gemma4:e2b-it-qat"
FOTO = Path(os.environ.get("TEMP", ".")) / "companion_tarjeta_permiso.png"


def preparar():
    """1. El catálogo, sin modelo: qué se acepta, qué se rechaza y cómo se describe en la tarjeta."""
    casos = [("abrir_app", ["spotify"]), ("abrir_app", ["la calculadora"]), ("abrir_app", ["Photoshop"]),
             ("abrir_web", ["youtube.com"]), ("abrir_web", ["receta de pan casero"]), ("abrir_web", ["javascript:alert(1)"]),
             ("abrir_carpeta", ["descargas"]), ("abrir_carpeta", ["C:\\no\\existe"]), ("buscar_archivo", ["factura octubre"]),
             ("temporizador", ["10 minutos", "la pasta"]), ("temporizador", ["media hora"]), ("temporizador", ["3 días"]),
             ("multimedia", ["siguiente"]), ("volumen", ["bajar 10"]), ("borrar_archivo", ["factura"]),
             ("ejecutar", ["format c:"])]
    print("1. catálogo")
    for name, args in casos:
        try:
            r = actions.prepare(name, args)
            print(f"   {name:15} {args!s:28} → «{r.detail}»")
        except actions.ActionError as e:
            print(f"   {name:15} {args!s:28} → rechazada: {e}")
    ok = lambda n, a: actions.prepare(n, a)  # noqa: E731
    assert ok("abrir_app", ["spotify"]).target["app"]["id"].startswith("SpotifyAB"), "eligió el desinstalador"
    assert ok("abrir_web", ["javascript:alert(1)"]).target["url"].startswith("https://www.google.com/search")
    assert ok("temporizador", ["media hora"]).target["seconds"] == 1800
    for n, a in (("abrir_app", ["Photoshop"]), ("abrir_carpeta", ["C:\\no\\existe"]), ("temporizador", ["3 días"]),
                 ("borrar_archivo", ["factura"]), ("ejecutar", ["format c:"])):
        try:
            actions.prepare(n, a)
            raise AssertionError(f"aceptó {n} {a}")
        except actions.ActionError:
            pass
    # con los modelos locales más pequeños las acciones se apagan
    antes = (settings.llm_provider, settings.ollama_model)
    settings.llm_provider, settings.ollama_model = "local", "gemma3:1b-it-qat"
    pequeno = llm.can_act()
    settings.ollama_model = MODELO
    grande = llm.can_act()
    settings.llm_provider, settings.ollama_model = antes
    print(f"   acciones con gemma3:1b={pequeno} · con {MODELO}={grande}")
    assert not pequeno and grande


async def main():
    preparar()
    api = httpx.Client(base_url=_prueba.URL, timeout=60)
    assert api.post("/api/setup", json={"local_model": MODELO, "provider": "local"}).status_code == 200
    api.post("/api/actions", json={"ask": True})          # esta prueba revisa las tarjetas de permiso: se encienden
    env = {**os.environ, "COMPANION_TEST": "1", "COMPANION_TEST_PORT": str(PORT), "COMPANION_URL": _prueba.URL}
    env.pop("ELECTRON_RUN_AS_NODE", None)
    proc = subprocess.Popen([str(ELECTRON), str(ROOT / "desktop")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url, _ = await pagina(_prueba.URL)
        async with connect(url, max_size=None) as ws:
            p = Pagina(ws)
            await p.cmd("Runtime.enable")
            await asyncio.sleep(4)
            await p.js("document.getElementById('start-text').click(); null")
            await asyncio.sleep(3)

            async def decir(texto: str):
                await p.js(f"window.companion.send({{type: 'text', text: {json.dumps(texto)}}}); null")

            async def tarjeta(espera: float = 60):
                limite = time.monotonic() + espera
                while time.monotonic() < limite:
                    c = await p.js("(() => { const c = document.querySelector('#asks .ask:not(.done)'); return c && "
                                   "{id: c.dataset.id, texto: c.innerText, botones: c.querySelectorAll('button').length}; })()")
                    if c:
                        return c
                    await asyncio.sleep(0.4)
                return None

            async def resultado(id_: str, espera: float = 30):
                limite = time.monotonic() + espera
                while time.monotonic() < limite:
                    t = await p.js(f"(() => {{ const c = document.querySelector('#asks [data-id=\"{id_}\"]'); return c && c.classList.contains('done') ? c.innerText : null; }})()")
                    if t:
                        return t
                    await asyncio.sleep(0.4)
                return None

            async def respuesta(espera: float = 60):
                """Espera a que termine de hablar y devuelve lo último que dijo."""
                await asyncio.sleep(1.5)
                limite = time.monotonic() + espera
                while time.monotonic() < limite:
                    e = await p.js("({s: window.companion.status().state, m: document.getElementById('mika-line').textContent})")
                    if e["s"] == "idle" and e["m"]:
                        return e["m"]
                    await asyncio.sleep(0.5)
                return ""

            def pulsar(id_, cual):
                return p.js(f"[...document.querySelectorAll('#asks [data-id=\"{id_}\"] button')].find(b => b.textContent === {json.dumps(cual)}).click(); null")

            print("2. con la interfaz (simulado: no se abre nada)")
            await decir("Abre Spotify, por favor.")
            c = await tarjeta()
            assert c and "Spotify" in c["texto"] and c["botones"] == 3, c
            png = base64.b64decode((await p.cmd("Page.captureScreenshot", format="png"))["data"])
            FOTO.write_bytes(png)
            await pulsar(c["id"], "Permitir")
            hecho = await resultado(c["id"])
            print(f"   «Abre Spotify»          → tarjeta {c['texto']!r} → Permitir → {hecho!r}")
            assert hecho and "(simulado) Abrir Spotify" in hecho
            await respuesta()

            await decir("Busca mi archivo de la factura de octubre.")
            c = await tarjeta()
            assert c and "factura" in c["texto"].lower(), c
            await asyncio.sleep(1.5)
            await decir("sí")                                      # responder hablando
            hecho = await resultado(c["id"])
            dijo = await respuesta(60)
            print(f"   «Busca la factura»      → «sí» → {hecho!r}\n      y cuenta: {dijo!r}")
            assert hecho and "factura_octubre" in hecho and "factura" in dijo.lower()

            await decir("Pon un temporizador de 5 segundos para el té.")
            c = await tarjeta()
            assert c and "5 s" in c["texto"], c
            await pulsar(c["id"], "Permitir siempre")
            hecho = await resultado(c["id"])
            await asyncio.sleep(7)
            aviso = await respuesta(60)
            print(f"   «Temporizador 5 s»      → Permitir siempre → {hecho!r} · al terminar dice: {aviso!r}")
            assert hecho and aviso

            await decir("Abre la carpeta de descargas.")
            c = await tarjeta()
            assert c and "Downloads" in c["texto"], c
            await pulsar(c["id"], "No")
            hecho = await resultado(c["id"])
            print(f"   «Carpeta descargas»     → No → {hecho!r}")
            assert hecho and "No se hizo" in hecho
            await respuesta()

            n = len(api.get("/api/actions").json()["history"])
            await decir("Pon otro temporizador de 3 segundos.")
            await respuesta()
            await asyncio.sleep(1)
            sin_tarjeta = await tarjeta(3) is None
            h = api.get("/api/actions").json()
            print(f"   «Otro temporizador»     → sin preguntar (permitido siempre)={sin_tarjeta} · registro: {h['history'][0]}")
            assert sin_tarjeta and len(h["history"]) > n and h["history"][0]["decision"] == "siempre"
            await asyncio.sleep(5)
            await respuesta()

            await decir("Borra el archivo de la factura de octubre.")
            dijo = await respuesta()
            otra = await tarjeta(3)
            print(f"   «Borra la factura»      → tarjeta={otra and otra['texto']!r} · dice: {dijo!r}")
            assert otra is None, "pidió otra acción en lugar de decir que no puede"
            sin_no = re.sub(r"\bno (?:te |se |lo |la |los |las )?puedo", "", dijo.lower())   # «No (te) puedo borrar» es la respuesta buena
            assert not any(w in sin_no for w in ("puedo borr", "puedo elimin", "lo borro", "la borro")), dijo

            api.post("/api/actions", json={"enabled": False})
            await decir("Abre la calculadora.")
            dijo = await respuesta()
            apagado = await tarjeta(4) is None
            print(f"   apagadas en Ajustes     → «Abre la calculadora» sin tarjeta={apagado} · dice: {dijo!r}")
            assert apagado
            api.post("/api/actions", json={"enabled": True, "forget_always": "temporizador"})

            await p.js("document.getElementById('open-settings').click(); null")
            await asyncio.sleep(1.5)
            ajustes = await p.js("({on: document.getElementById('actions-on').checked, siempre: document.getElementById('actions-always').innerText, "
                                 "registro: [...document.querySelectorAll('#actions-log div')].slice(0, 3).map(d => d.innerText)})")
            print(f"3. Ajustes               : {ajustes}")
            assert ajustes["on"] and not ajustes["siempre"] and len(ajustes["registro"]) == 3
        print(f"OK: cada acción pide permiso y se hace solo al aprobarla. Captura de la tarjeta: {FOTO}")
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        _prueba.cerrar(proc)


if __name__ == "__main__":
    (ARCHIVOS / "Facturas").mkdir(parents=True, exist_ok=True)
    (ARCHIVOS / "Facturas" / "factura_octubre_2026.pdf").write_bytes(b"%PDF-1.4 prueba")
    (ARCHIVOS / "notas_reunion.txt").write_text("prueba", encoding="utf-8")
    (_prueba.TEST_DIR / "acciones.jsonl").unlink(missing_ok=True)
    with _prueba.Servidor():
        asyncio.run(main())
