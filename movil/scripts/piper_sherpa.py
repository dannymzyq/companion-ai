"""Convierte una voz Piper (<voz>.onnx + <voz>.onnx.json) al formato vits-piper de sherpa-onnx, sin librerías:
añade al ONNX los metadatos que pide sherpa (un ModelProto de protobuf admite campos repetidos añadidos al final),
escribe tokens.txt con el phoneme_id_map y copia espeak-ng-data. Solo para probar en el Mac: la app baja las voces
ya convertidas de Hugging Face (csukuangfj/vits-piper-*), que salen del mismo procedimiento.

  python3 piper_sherpa.py <voz.onnx> <espeak-ng-data> <carpeta de salida>
"""
import json
import shutil
import sys
from pathlib import Path


def varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def field(num: int, payload: bytes) -> bytes:          # tipo 2: longitud + datos
    return varint(num << 3 | 2) + varint(len(payload)) + payload


def entry(key: str, value: str) -> bytes:              # ModelProto.metadata_props = 14 (StringStringEntryProto)
    return field(14, field(1, key.encode()) + field(2, value.encode()))


def main(onnx: str, espeak: str, out: str):
    onnx_path = Path(onnx)
    cfg = json.loads(Path(onnx + ".json").read_text(encoding="utf-8"))
    dst = Path(out)
    dst.mkdir(parents=True, exist_ok=True)
    meta = {
        "model_type": "vits", "comment": "piper", "language": cfg.get("language", {}).get("name_english", "Spanish"),
        "voice": cfg["espeak"]["voice"], "has_espeak": "1", "n_speakers": str(cfg.get("num_speakers", 1)),
        "sample_rate": str(cfg["audio"]["sample_rate"]),
    }
    (dst / onnx_path.name).write_bytes(onnx_path.read_bytes() + b"".join(entry(k, v) for k, v in meta.items()))
    with open(dst / "tokens.txt", "w", encoding="utf-8") as f:
        for sym, ids in cfg["phoneme_id_map"].items():
            f.write(f"{sym} {ids[0]}\n")
    if not (dst / "espeak-ng-data").exists():
        shutil.copytree(espeak, dst / "espeak-ng-data")
    print("listo:", dst, meta)


if __name__ == "__main__":
    main(*sys.argv[1:4])
