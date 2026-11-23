"""Mac con Apple Silicon: el companion con el cerebro local en un modelo MLX de Ollama (15 nov 2026).

Arranca el servidor aislado de pruebas (puerto 8201, data/prueba) con el cerebro local y un modelo guardado con su
nombre de PC (gemma4:e4b-it-qat), y comprueba que:
  1. el catálogo de Ajustes ofrece los MLX y recomienda uno de ellos;
  2. lo guardado con el nombre de PC pasa a su versión MLX;
  3. una conversación escrita responde con el modelo MLX, que corre con el motor MLX (`ollama ps`).
Con la voz ligera (la completa en el Mac tarda en cargar y aquí no se mide). Necesita el modelo MLX descargado.

    .venv/bin/python scripts/pruebas/prueba_mlx.py [gemma4:e4b-mlx]
No la corras mientras el usuario conversa con el modelo local: Ollama tiene una sola cola."""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _prueba  # noqa: E402  (antes que companion.*)

import httpx  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

from companion.config import MAC, MLX_EQUIV  # noqa: E402

FRASES = ["Hola, ¿qué tal tu día?", "Cuéntame en una frase qué te gusta hacer cuando llueve."]


async def charlar(modelo: str) -> list[dict]:
    out = []
    async with connect(f"ws://127.0.0.1:{_prueba.PORT}/ws", max_size=None) as ws:
        hello = json.loads(await ws.recv())
        print("hello:", {k: hello.get(k) for k in ("llm", "model")})
        for frase in FRASES:
            t = time.perf_counter()
            await ws.send(json.dumps({"type": "text", "text": frase}))
            primero, texto = None, ""
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=120)
                if isinstance(msg, bytes):
                    primero = primero or time.perf_counter() - t
                    continue
                ev = json.loads(msg)
                if ev["type"] == "error":
                    raise SystemExit(f"Error del companion: {ev.get('message')}")
                if ev["type"] == "reply_end":
                    texto = ev.get("text", "")
                    await ws.send(json.dumps({"type": "playback_end"}))
                    break
            out.append({"frase": frase, "respuesta": texto[:200], "total_s": round(time.perf_counter() - t, 2),
                        "primer_audio_s": round(primero, 2) if primero else None})
            print(json.dumps(out[-1], ensure_ascii=False))
    return out


def main():
    if not MAC:
        raise SystemExit("Esta prueba es para un Mac con Apple Silicon.")
    modelo = next((a for a in sys.argv[1:] if not a.startswith("--")), "gemma4:e4b-mlx")
    pc = next((k for k, v in MLX_EQUIV.items() if v == modelo and k.endswith("-it-qat")), modelo)
    ajustes = {"provider": "local", "local_model": pc, "voice_engine": "ligera", "voice_auto": False}
    fallos = []
    with _prueba.Servidor(ajustes=ajustes):
        setup = httpx.get(f"{_prueba.URL}/api/setup", timeout=30).json()
        local = setup["local"]
        catalogo = [m["id"] for m in local["models"]]
        rec = local["recommended"]
        print("catálogo:", catalogo, "· elegido:", local["selected"])
        if not catalogo[0].endswith("-mlx"):
            fallos.append(f"el catálogo no empieza por los MLX: {catalogo}")
        print("recomendado:", rec, "· memoria para la GPU:", setup["resources"]["total_gb"], "GB")
        if not rec.endswith("-mlx"):
            fallos.append(f"el recomendado no es MLX: {rec}")
        guardado = json.loads((_prueba.TEST_DIR / "settings.json").read_text(encoding="utf-8")).get("local_model")
        print("guardado:", guardado)
        if guardado != modelo:
            fallos.append(f"lo guardado ({pc}) no pasó a {modelo}: {guardado}")
        charla = asyncio.run(charlar(modelo))
        ps = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10).stdout
        print(ps)
        fila = next((linea for linea in ps.splitlines() if linea.startswith(modelo)), "")
        if not fila:
            fallos.append(f"{modelo} no está cargado en Ollama")
        elif "mlx" not in fila.lower():
            fallos.append(f"{modelo} no corre con el motor MLX: {fila}")
        if not all(c["respuesta"] for c in charla):
            fallos.append("alguna respuesta vino vacía")
    print("\nOK" if not fallos else "\nFALLOS:\n  " + "\n  ".join(fallos))
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
