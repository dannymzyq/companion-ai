"""Trae a la carpeta del proyecto los modelos que el companion necesita (lo llama el instalador):

    --oido      Whisper large-v3-turbo        → models/whisper/large-v3-turbo   (1,5 GB)
    --ligera    voces de Piper                → models/piper                    (380 MB)
    --completa  F5-TTS en español y su vocoder → voz/modelos                    (1,3 GB)
    --recomendar  imprime «voz modelo» recomendados para la tarjeta de esta PC

Lo que ya está no se vuelve a bajar. Todo sale de huggingface.co.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def oido(nombre: str = "large-v3-turbo"):
    destino = ROOT / "models" / "whisper" / nombre
    if (destino / "model.bin").is_file():
        return print(f"Oido: {nombre} ya esta en models/whisper")
    from faster_whisper import download_model
    print(f"Oido: descargando Whisper {nombre} (1,5 GB)...")
    destino.mkdir(parents=True, exist_ok=True)
    download_model(nombre, output_dir=str(destino))


def ligera():
    from companion import tts_light
    if not tts_light.missing():
        return print("Voz ligera: los modelos de Piper ya estan en models/piper")
    print(f"Voz ligera: descargando los modelos de Piper ({tts_light.SIZE_MB} MB)...")
    asyncio.run(tts_light.install())
    if tts_light.progress.get("error"):
        sys.exit(f"Voz ligera: {tts_light.progress['error']}")


def completa():
    from huggingface_hub import hf_hub_download
    f5, vocos = ROOT / "voz" / "modelos" / "f5-spanish", ROOT / "voz" / "modelos" / "vocos"
    for carpeta, repo, archivos in ((f5, "jpgallegoar/F5-Spanish", ("model_1250000.safetensors", "vocab.txt")),
                                    (vocos, "charactr/vocos-mel-24khz", ("config.yaml", "pytorch_model.bin"))):
        carpeta.mkdir(parents=True, exist_ok=True)
        for nombre in archivos:
            if (carpeta / nombre).is_file():
                continue
            print(f"Voz completa: descargando {repo}/{nombre}...")
            hf_hub_download(repo, nombre, local_dir=str(carpeta))
    print("Voz completa: modelo F5-TTS y vocoder en voz/modelos")


def recomendar():
    from companion import llm, profile
    r = profile.resources(llm.gpu_memory(), is_cloud=False, local_model=profile.LOCAL_MODELS[0]["id"], node_ok=True)
    print(r["recommended_pair"], r["recommended_model"], r["total_gb"])


if __name__ == "__main__":
    for paso in sys.argv[1:]:
        {"--oido": oido, "--ligera": ligera, "--completa": completa, "--recomendar": recomendar}[paso]()
