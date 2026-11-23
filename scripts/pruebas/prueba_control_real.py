"""Prueba con el TECLADO Y EL RATÓN DE VERDAD. Abre el reproductor de prueba A LA VISTA, lo trae al frente y
escribe y hace clic en él durante un minuto o dos: mientras tanto no uses la PC (y no la corras con un juego
abierto). Solo se ejecuta con --si, y solo cuando el usuario lo ha pedido.

· el servidor de prueba solo puede manejar esa ventana (COMPANION_CONTROL_ONLY)
· COMPANION_CONTROL_FORCE_INPUT=1: aunque el control admita accesibilidad, usa el teclado y el ratón de verdad
· simula que compartes la pantalla, así el modelo recibe una captura de la ventana en cada paso

Comprueba: escribir un párrafo con acentos tecleando (como en Word), reproducir una canción con doble clic de
ratón, que mira la ventana (captura) y que al terminar devuelve el foco a la ventana que tenías.

    .venv\\Scripts\\python.exe scripts\\pruebas\\prueba_control_real.py --si [modelo]
"""
import asyncio
import base64
import ctypes
import io
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

TITULO = "Reproductor de prueba"
os.environ.update(COMPANION_CONTROL_ONLY=TITULO, COMPANION_CONTROL_FORCE_INPUT="1", LLM_PROVIDER="local",
                  COMPANION_ACTIONS_DRY="1")
os.environ.pop("COMPANION_CONTROL_NO_INPUT", None)

from companion import control  # noqa: E402
from prueba_control import EXE, compilar  # noqa: E402

# prueba_control prohíbe el teclado y el ratón reales al importarse: aquí se quitan otra vez (esta prueba los usa)
os.environ.pop("COMPANION_CONTROL_NO_INPUT", None)
os.environ["COMPANION_CONTROL_FORCE_INPUT"] = "1"

MODELO = next((a for a in sys.argv[1:] if not a.startswith("--")), "gemma4:e4b-it-qat")
user32 = ctypes.windll.user32


def jpeg_minimo() -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (40, 40, 60)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


async def tarea(ws, texto: str, espera: float = 240) -> dict:
    """Manda una orden y sigue el control hasta el final. Las confirmaciones se responden siempre «No»."""
    await ws.send(json.dumps({"type": "text", "text": texto}))
    pasos, final, limite = [], None, time.monotonic() + espera
    while time.monotonic() < limite:
        try:
            msg = await asyncio.wait_for(ws.recv(), 5)
        except asyncio.TimeoutError:
            await ws.send(json.dumps({"type": "frame", "source": "screen", "jpeg": FRAME}))   # sigue «compartiendo»
            continue
        if isinstance(msg, bytes):
            continue
        ev = json.loads(msg)
        if ev["type"] == "control_step":
            pasos.append(ev["text"])
        elif ev["type"] == "action_request":
            await ws.send(json.dumps({"type": "action_answer", "id": ev["id"], "answer": "deny"}))
            pasos.append(f"(confirmación pedida: {ev['detail']} → No)")
        elif ev["type"] in ("reply_end",):
            await ws.send(json.dumps({"type": "playback_end"}))
        elif ev["type"] == "control_end":
            final = ev
            break
    return {"pasos": pasos, "final": final}


async def main():
    api = httpx.Client(base_url=_prueba.URL, timeout=60)
    assert api.post("/api/setup", json={"local_model": MODELO, "provider": "local"}).status_code == 200
    antes = user32.GetForegroundWindow()
    win = control.find_window(TITULO)
    async with connect(f"ws://127.0.0.1:{_prueba.PORT}/ws", max_size=None) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "frame", "source": "screen", "jpeg": FRAME}))      # «compartiendo pantalla»

        r = await tarea(ws, "En el reproductor de prueba escribe en el documento un párrafo corto sobre el mar.")
        items, _ = control.snapshot(win.hwnd)
        doc = next((i.value for i in items if i.name == "Documento"), "")
        print(f"1. párrafo tecleado : pasos={r['pasos']}\n                      final={r['final']}\n                      documento={doc!r}")
        assert len(doc) >= 40, "no escribió el párrafo"

        r = await tarea(ws, "En el reproductor de prueba reproduce la canción Jazz suave.")
        _, texts = control.snapshot(win.hwnd)
        est = next((t for t in texts if t.startswith("Estado")), "?")
        print(f"2. reproducir       : pasos={r['pasos']}\n                      final={r['final']} · {est}")
        assert "sonando Jazz" in est, "no puso Jazz suave"

    log = (_prueba.TEST_DIR / "servidor.log").read_text(encoding="utf-8", errors="replace")
    imagen = log.count("(con imagen)")
    reales = [h for h in api.get("/api/actions").json()["history"] if h["decision"] == "paso" and h["result"] in ("con el teclado", "con el ratón")]
    print(f"3. mirar la ventana : {imagen} pasos con captura · {len(reales)} pasos con teclado o ratón de verdad")
    print(f"4. foco devuelto    : {user32.GetForegroundWindow() == antes}")
    assert imagen and reales
    print(f"OK con {MODELO}: teclea párrafos, hace doble clic, mira la ventana y devuelve el foco.")


FRAME = ""
if __name__ == "__main__":
    if "--si" not in sys.argv:
        sys.exit("Esta prueba usa tu teclado y tu ratón de verdad durante un par de minutos. Ejecútala con --si.")
    compilar()
    FRAME = jpeg_minimo()
    (_prueba.TEST_DIR / "acciones.jsonl").unlink(missing_ok=True)
    ventana = subprocess.Popen([str(EXE), "--visible"])
    try:
        time.sleep(2.5)
        with _prueba.Servidor():
            asyncio.run(main())
    finally:
        ventana.kill()
