"""Elige cómo escribir cada palabra en inglés para que la voz la pronuncie bien, y lo guarda en
voices/pronunciacion.json. Para cada palabra prueba sus candidatas (escritas a la española) dentro de una frase,
varias veces, y Whisper dice si se entiende. Se queda con la primera candidata que se entiende en casi todas las
pasadas; si ninguna, deja la palabra como está.

Ojo: Whisper tiende a «corregir» hacia el nombre conocido, así que mide que se ENTIENDA, no que suene a inglés
perfecto: las candidatas ya están escritas para sonar a inglés. Usa el servidor de voz en marcha (puerto 8210).

    .venv\\Scripts\\python.exe scripts\\herramientas\\calibrar_pronunciacion.py [palabra ...]
"""
import asyncio
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from companion import tts  # noqa: E402
from companion.pronounce import FILE  # noqa: E402
from companion.stt import _add_cuda_dlls  # noqa: E402

PASADAS = 3
# palabra → candidatas (la primera que se entienda gana). Frase de prueba: «Ahora te lo pongo en X, ¿vale?»
CANDIDATAS = {
    "Apple Music": ["Ápel Miúsik", "Apel Miúsik", "Áppel Miúsik", "Ápel Míusik", "Ápol Miúsik"],
    "Apple TV": ["Ápel Ti Vi", "Apel Tivi"],
    "Apple": ["Ápel", "Apel", "Áppel"],
    "Spotify": ["Espótifai", "Spótifai"],
    "YouTube": ["Iutiub", "Yutiub"],
    "YouTube Music": ["Iutiub Miúsik"],
    "Netflix": ["Nétflix"],
    "WhatsApp": ["Uatsap", "Guatsap"],
    "TikTok": ["Tik Tok"],
    "Facebook": ["Féisbuk", "Feisbuk"],
    "Google": ["Gúgol", "Gugol"],
    "Gmail": ["Yi Méil", "Yiméil"],
    "Chrome": ["Króum", "Krom"],
    "Firefox": ["Fáierfox", "Fáiarfox"],
    "Word": ["Uérd", "Güerd", "Güord", "Uord"],
    "Excel": ["Éksel", "Exel"],
    "PowerPoint": ["Páuer Póint", "Páuerpoint"],
    "Outlook": ["Áutluk", "Autluk"],
    "Teams": ["Tims", "Tiims"],
    "OneDrive": ["Guan Dráiv", "Uan Dráiv", "Uán Draif"],
    "Windows": ["Uíndous", "Güíndous"],
    "Discord": ["Díscord"],
    "Steam": ["Estím", "Stiim"],
    "Twitch": ["Tuích", "Tuich"],
    "Twitter": ["Tuíter"],
    "Claude": ["Clod", "Clood", "Cloud"],
    "ChatGPT": ["Chat Yi Pi Ti", "Chat Yipiti", "Chat Ye Pe Te"],
    "iPhone": ["Áifon", "Aifon"],
    "Microsoft": ["Máicrosoft", "Maicrosoft"],
    "Amazon": ["Ámazon"],
    "Zoom": ["Zum", "Sum"],
    "Bluetooth": ["Blútuz", "Blutut"],
    "Wi-Fi": ["Uái fai", "Guaifai"],
    "WiFi": ["Uái fai", "Guaifai"],
    "playlist": ["pléilist", "pleilist"],
    "online": ["onláin"],
    "email": ["ímeil", "imeil"],
    "streaming": ["estrímin", "estríming"],
    "okay": ["okéi", "oukéi"],
    "OK": ["okéi"],
    "laptop": ["láptop"],
    "software": ["sófguer", "sóftuer"],
    "hardware": ["járdguer", "járduer"],
    "mouse": ["máus"],
    "gamer": ["guéimer"],
    "Lofi": ["Lóufai", "Lo fai"],
}
# «en Ápel» se junta («Empel»): la palabra va detrás de una pausa y no de «en»
FRASE = "Listo, abro {} ahora mismo."


def plain(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))


async def main():
    _add_cuda_dlls()
    from faster_whisper import WhisperModel
    model = WhisperModel(str(ROOT / "models" / "whisper" / "large-v3-turbo"), device="cuda", compute_type="int8_float16")
    data = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {"qu_como_k": True, "palabras": {}}
    elegidas = dict(data.get("palabras") or {})
    pedidas = sys.argv[1:] or list(CANDIDATAS)

    async def oir(texto: str) -> str:
        pcm = b"".join([c async for c in tts.stream_speech(texto, "mika_es")])
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        x16 = np.interp(np.arange(0, len(x), 1.5), np.arange(len(x)), x).astype(np.float32)
        return " ".join(s.text for s in model.transcribe(x16, language="es", beam_size=5)[0])

    for palabra in pedidas:
        objetivo = plain(palabra)
        elegida = None
        for cand in CANDIDATAS.get(palabra, []):
            # se manda la candidata tal cual: la capa de pronunciación no la vuelve a tocar (no es la palabra original)
            oidos = [await oir(FRASE.format(cand)) for _ in range(PASADAS)]
            aciertos = sum(objetivo in plain(o) for o in oidos)
            print(f"{palabra:14} «{cand}»: {aciertos}/{PASADAS} · {oidos[0][:60]!r}", flush=True)
            if aciertos >= PASADAS - 1:
                elegida = cand
                break
        if elegida:
            elegidas[palabra] = elegida
        else:
            elegidas.pop(palabra, None)
            print(f"{palabra:14} → se queda como está (ninguna candidata se entendió lo bastante)", flush=True)
    data["palabras"] = dict(sorted(elegidas.items(), key=lambda kv: kv[0].lower()))
    data.setdefault("qu_como_k", True)
    data["_"] = ("Cómo se pronuncian en voz alta las palabras en inglés: «palabra»: «cómo suena, escrito a la española». "
                 "Solo afecta a la voz, no al texto en pantalla. Se puede editar sin reiniciar. qu_como_k: «qué» se dice «ké».")
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Guardado {FILE} con {len(data['palabras'])} palabras.")


asyncio.run(main())
