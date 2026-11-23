"""Muestra corta de cada voz (16 nov 2026): añade `short` (tramo de 3,5 a 5,2 s, cortado en un final de frase, con
su texto y el ajuste de velocidad) al .json de las muestras de voices/. voz/servidor.py la usa con VOZ_REF_CORTA=1
(el Mac): F5 genera la muestra junto con cada frase, y con la mitad de muestra cada frase tarda la mitad.

    .venv\\Scripts\\python.exe scripts\\herramientas\\recortar_muestras.py            (las que no lo tienen)
    .venv\\Scripts\\python.exe scripts\\herramientas\\recortar_muestras.py --rehacer  (todas otra vez)

Usa el Whisper instalado (models/whisper) en el procesador: no ocupa memoria de vídeo. Las voces propias del usuario
(data/voces) se preparan solas al arrancar en el Mac (server._load_ear)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from companion import voice_import  # noqa: E402
from companion.config import settings  # noqa: E402


def main():
    from faster_whisper import WhisperModel
    local = ROOT / "models" / "whisper" / settings.stt_model
    model = WhisperModel(str(local) if (local / "model.bin").is_file() else settings.stt_model,
                         device="cpu", compute_type="int8")
    rehacer = "--rehacer" in sys.argv
    for cfg_path in sorted((ROOT / "voices").glob("*_es.json")):
        base = cfg_path.with_suffix("")
        if rehacer:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg.pop("short", None)
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        voice_import.add_short(model, base)
        short = json.loads(cfg_path.read_text(encoding="utf-8")).get("short")
        print(f"{base.name:14}", f"{short['start']:.2f}–{short['end']:.2f} s · ritmo ×{short['speed']} · {short['text']}"
              if short else "sin tramo corto (usará la muestra entera)")


if __name__ == "__main__":
    main()
