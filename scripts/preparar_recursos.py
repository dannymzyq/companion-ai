"""Trae a la carpeta del proyecto los modelos que el companion necesita (lo llama el instalador):

    --oido      Whisper large-v3-turbo        → models/whisper/large-v3-turbo   (1,5 GB)
    --ligera    voces de Piper                → models/piper                    (380 MB)
    --completa  F5-TTS en español y su vocoder → voz/modelos                    (1,3 GB)
    --ollama M  el modelo local M con Ollama, por su API (para ver el progreso)
    --recomendar  imprime «voz modelo» recomendados para la tarjeta de esta PC

Lo que ya está no se vuelve a bajar. Los modelos salen de huggingface.co (y el local, de ollama.com).
Con COMPANION_UI=1 (la ventana de instalación) imprime marcas de progreso «::progreso::NN::texto».
"""
import asyncio
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
UI = os.getenv("COMPANION_UI") == "1"


def progreso(pct: float, texto: str):
    if UI:
        print(f"::progreso::{max(0, min(100, int(pct)))}::{texto}", flush=True)


def gb(n: float) -> str:
    return f"{n / 2**30:.1f} GB".replace(".", ",") if n >= 2**30 else f"{n / 2**20:.0f} MB"


def vigilar(carpeta: Path, total: int, texto: str):
    """Enseña cuánto lleva una descarga mirando cuánto ocupa su carpeta (huggingface_hub no da el progreso).
    Devuelve la función que la para."""
    parar = threading.Event()

    def ocupa():
        return sum(f.stat().st_size for f in carpeta.rglob("*") if f.is_file()) if carpeta.is_dir() else 0
    inicio = ocupa()

    def bucle():
        while not parar.wait(0.7):
            hecho = max(0, ocupa() - inicio)
            progreso(min(99, 100 * hecho / total), f"{texto}: {gb(hecho)} de unos {gb(total)}")
    threading.Thread(target=bucle, daemon=True).start()
    return parar.set


def oido(nombre: str = "large-v3-turbo"):
    destino = ROOT / "models" / "whisper" / nombre
    if (destino / "model.bin").is_file():
        return print(f"Oido: {nombre} ya esta en models/whisper")
    from faster_whisper import download_model
    print(f"Oido: descargando Whisper {nombre} (1,5 GB)...", flush=True)
    destino.mkdir(parents=True, exist_ok=True)
    parar = vigilar(destino, int(1.62 * 2**30), "Oído (Whisper)")
    try:
        download_model(nombre, output_dir=str(destino))
    finally:
        parar()


def ligera():
    from companion import tts_light
    if not tts_light.missing():
        return print("Voz ligera: los modelos de Piper ya estan en models/piper")
    print(f"Voz ligera: descargando los modelos de Piper ({tts_light.SIZE_MB} MB)...", flush=True)

    async def con_progreso():
        tarea = asyncio.create_task(tts_light.install())
        while not tarea.done():
            await asyncio.sleep(0.5)
            if tts_light.progress.get("status") == "descargando":
                pct = tts_light.progress.get("percent", 0)
                progreso(pct, f"Voz ligera (Piper): {pct} % de {tts_light.SIZE_MB} MB")
        await tarea
    asyncio.run(con_progreso())
    if tts_light.progress.get("error"):
        sys.exit(f"Voz ligera: {tts_light.progress['error']}")


def completa():
    from huggingface_hub import hf_hub_download
    f5, vocos = ROOT / "voz" / "modelos" / "f5-spanish", ROOT / "voz" / "modelos" / "vocos"
    falta = any(not (c / n).is_file() for c, n in ((f5, "model_1250000.safetensors"), (vocos, "pytorch_model.bin")))
    parar = vigilar(ROOT / "voz" / "modelos", int(1.36 * 2**30), "Modelo de la voz completa") if falta else (lambda: None)
    try:
        for carpeta, repo, archivos in ((f5, "jpgallegoar/F5-Spanish", ("model_1250000.safetensors", "vocab.txt")),
                                        (vocos, "charactr/vocos-mel-24khz", ("config.yaml", "pytorch_model.bin"))):
            carpeta.mkdir(parents=True, exist_ok=True)
            for nombre in archivos:
                if (carpeta / nombre).is_file():
                    continue
                print(f"Voz completa: descargando {repo}/{nombre}...", flush=True)
                hf_hub_download(repo, nombre, local_dir=str(carpeta))
    finally:
        parar()
    print("Voz completa: modelo F5-TTS y vocoder en voz/modelos")


def ollama(modelo: str):
    """Descarga el modelo local con la API de Ollama, enseñando cuánto lleva."""
    import json

    import httpx
    url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    tags = httpx.get(f"{url}/api/tags", timeout=5).json().get("models", [])
    if any(m.get("name") in (modelo, f"{modelo}:latest") for m in tags):
        return print(f"Cerebro local: {modelo} ya está descargado")
    print(f"Cerebro local: descargando {modelo}...", flush=True)
    ultimo = 0.0
    with httpx.stream("POST", f"{url}/api/pull", json={"model": modelo, "stream": True},
                      timeout=httpx.Timeout(None, connect=5)) as r:
        for linea in r.iter_lines():
            try:
                d = json.loads(linea)
            except ValueError:
                continue
            if d.get("error"):
                sys.exit(f"Cerebro local: {d['error']}")
            total, hecho = d.get("total") or 0, d.get("completed") or 0
            if total and time.monotonic() - ultimo > 0.5:
                ultimo = time.monotonic()
                progreso(100 * hecho / total, f"Modelo local {modelo}: {gb(hecho)} de {gb(total)}")
    print(f"Cerebro local: {modelo} listo")


def recomendar():
    from companion import llm, profile
    r = profile.resources(llm.gpu_memory(), is_cloud=False, local_model=profile.TOP_RECOMMENDED, node_ok=True)
    print(r["recommended_pair"], r["recommended_model"], r["total_gb"])


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--ollama"]:
        ollama(args[1])
    else:
        for paso in args:
            {"--oido": oido, "--ligera": ligera, "--completa": completa, "--recomendar": recomendar}[paso]()
