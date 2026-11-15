"""Convierte grabaciones propias (mp3/wav) en muestras para el servidor de voz. De las grabaciones de cada voz
elige el mejor tramo de frases completas de 5 a 8,5 s, lo transcribe con Whisper
(el servidor necesita el texto exacto de la muestra) y escribe voices/<voz>_es.wav + .json, que voz/servidor.py
lee directamente. Las piezas son las de companion/voice_import.py (las voces propias que se suben desde Ajustes).

    .venv\\Scripts\\python.exe scripts\\importar_voces.py <carpeta con las grabaciones> [--voz=mika=Mika]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "voices"

from companion.voice_import import SR, decode, f0, transcribe_words, windows, write_sample  # noqa: E402

# voz del companion → prefijo de los archivos grabados (Natalia1.mp3, Natalia2.mp3…)
VOCES = {"natsumi": "Natalia", "chiaki": "Cristina", "ayaka": "AnaMaria",
         "goro": "Gork", "ryo": "Rocco", "satoshi": "Salvatore", "akira": "Antonio"}


def main():
    src = Path(sys.argv[1])
    global VOCES
    for arg in sys.argv[2:]:                          # --voz mika=Mika: solo esa voz (archivos Mika*.wav|mp3)
        if arg.startswith("--voz="):
            nombre, prefijo = arg[6:].split("=", 1)
            VOCES = {nombre: prefijo}
    from faster_whisper import WhisperModel

    from companion.stt import _add_cuda_dlls
    _add_cuda_dlls()
    model = WhisperModel("large-v3-turbo", device="cuda", compute_type="int8_float16")
    OUT.mkdir(exist_ok=True)
    for voz, prefijo in VOCES.items():
        best = None
        for path in sorted(p for p in src.glob(f"{prefijo}*") if p.suffix.lower() in (".mp3", ".wav", ".flac", ".m4a")):
            x = decode(path)
            for t0, t1, text, score in windows(transcribe_words(model, x)):
                if not best or score > best[0]:
                    best = (score, path.name, x[int(t0 * SR):int(t1 * SR)], text, len(x) / SR)
        if not best:
            print(f"{voz:8} SIN TRAMO VÁLIDO")
            continue
        _, origen, y, text, total = best
        secs = write_sample(OUT, f"{voz}_es", y, text)
        print(f"{voz:8} ← {origen} ({total:.0f} s) · tramo de {secs:.1f} s · tono {f0(y):.0f} Hz · {text!r}")


if __name__ == "__main__":
    main()
