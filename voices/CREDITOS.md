# Voces incluidas

El personaje toma el nombre de la voz elegida. Las voces no llevan etiqueta de género en la interfaz.

| Voz | Origen | Tono de la muestra | Tono al hablar (clonada) |
| --- | --- | --- | --- |
| Mika | Voz original del proyecto (`mika_es`, ya estaba en el nodo de voz) | – | 216 Hz |
| Kenji | Sintética: [Piper](https://github.com/OHF-Voice/piper1-gpl), modelo `es_ES-davefx-medium` con el tono ×0,76 (datos de OHF-Voice/voice-datasets · CC0). Se regenera con `scripts\generar_voces.py` | – | 142 Hz |
| Natsumi | Grabación aportada por el usuario: `Natalia2.mp3` | 282 Hz | 298 Hz |
| Ayaka | Grabación aportada por el usuario: `AnaMaria2.mp3` | 250 Hz | 222 Hz |
| Chiaki | Grabación aportada por el usuario: `Cristina1.mp3` | 238 Hz | 238 Hz |
| Akira | Grabación aportada por el usuario: `Antonio2.mp3` | 173 Hz | 162 Hz |
| Goro | Grabación aportada por el usuario: `Gork1.mp3` | 154 Hz | 141 Hz |
| Ryo | Grabación aportada por el usuario: `Rocco2.mp3` | 123 Hz | 130 Hz |
| Satoshi | Grabación aportada por el usuario: `Salvatore2.mp3` | 114 Hz | 89 Hz |

Las siete grabaciones las entregó el usuario el 12 nov 2026 (dos archivos de ~55 s por voz). El origen y los
derechos de esas voces los conoce él: aquí no consta ninguna licencia, así que no deben redistribuirse sin
comprobarlo. `scripts\importar_voces.py` eligió de cada pareja el tramo de frases completas más claro que cabe
en los 12 s que usa el nodo de voz, lo transcribió con Whisper (el nodo necesita el texto exacto) y lo guardó
aquí como `<voz>_es.wav` + `.json`; con `--instalar` los copia a `pc-gpu\voices` de waifuv3.

Los tonos son la frecuencia media medida ese día: «muestra» en el tramo recortado, «clonada» en una frase nueva
dicha por el nodo de voz con esa muestra.

## Voz ligera (Piper)

Con la voz ligera no se usan las muestras de arriba: cada nombre suena con un modelo de
[Piper](https://github.com/OHF-Voice/piper1-gpl) y el tono cambiado (`light` en `voices.json`), así que solo se
parece en tono a su voz completa. Los modelos se descargan a `models\piper` desde
<https://huggingface.co/rhasspy/piper-voices>:

| Modelo | Voces que lo usan | Datos de origen y licencia |
| --- | --- | --- |
| `es_MX-claude-high` | Mika, Natsumi | HirCoir/Piper-TTS-Spanish · Apache 2.0 |
| `es_AR-daniela-high` | Ayaka | OpenSLR 61 · CC BY-SA 4.0 |
| `es_ES-sharvard-medium` | Chiaki, Ryo, Satoshi | Sharvard corpus (Univ. de Edimburgo) · CC BY 3.0 |
| `es_ES-davefx-medium` | Kenji | OHF-Voice/voice-datasets · CC0 |
| `es_MX-ald-medium` | Akira, Goro | rmcpantoja/Ald_Mexican_Spanish_speech_dataset · Unlicense |

Voces retiradas del catálogo: Aiko (12 nov 2026) y las sintéticas Yuki, Hana, Haru, Riku, Aki y Sora (12 nov 2026).
Sus archivos siguen en `pc-gpu\voices` de waifuv3, sin usar: desde este proyecto no se borra nada de allí.
