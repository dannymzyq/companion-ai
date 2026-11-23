# Voces incluidas

El personaje toma el nombre de la voz elegida. Las voces no llevan etiqueta de género en la interfaz.

| Voz | Origen | Tono de la muestra | Tono al hablar (clonada) |
| --- | --- | --- | --- |
| Mika | Desde el 13 nov 2026: audio que el usuario generó en ElevenLabs con textos de muestra (`Mika-2.wav`, tramo de 8,1 s). La anterior (la voz original del proyecto) está en `voices\anterior\mika_es_original.*` | 212 Hz | 207–218 Hz |
| Kenji | Sintética: [Piper](https://github.com/OHF-Voice/piper1-gpl), modelo `es_ES-davefx-medium` con el tono ×0,76 (datos de OHF-Voice/voice-datasets · CC0). Se regenera con `scripts\herramientas\generar_voces.py` | – | 142 Hz |
| Natsumi | Grabación aportada por el usuario: `Natalia2.mp3` | 282 Hz | 298 Hz |
| Ayaka | Grabación aportada por el usuario: `AnaMaria2.mp3` | 250 Hz | 222 Hz |
| Chiaki | Grabación aportada por el usuario: `Cristina1.mp3` | 238 Hz | 238 Hz |
| Akira | Grabación aportada por el usuario: `Antonio2.mp3` | 173 Hz | 162 Hz |
| Goro | Grabación aportada por el usuario: `Gork1.mp3` | 154 Hz | 141 Hz |
| Ryo | Grabación aportada por el usuario: `Rocco2.mp3` | 123 Hz | 130 Hz |
| Satoshi | Grabación aportada por el usuario: `Salvatore2.mp3` | 114 Hz | 89 Hz |

Las siete grabaciones las entregó el usuario el 12 nov 2026 (dos archivos de ~55 s por voz). El origen y los
derechos de esas voces los conoce él: aquí no consta ninguna licencia, así que no deben redistribuirse sin
comprobarlo. `scripts\herramientas\importar_voces.py` eligió de cada pareja el tramo de frases completas más claro que cabe
en los 12 s que usa el servidor de voz, lo transcribió con Whisper (necesita el texto exacto) y lo guardó
aquí como `<voz>_es.wav` + `.json`, que `voz\servidor.py` lee directamente.

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

La muestra nueva de Mika se eligió comparando seis tramos de los tres audios con la anterior: cada uno dijo las
mismas cinco frases dos veces y se midió con Whisper cuánto se entiende (97 %, igual que la anterior) y a qué
velocidad habla. Para volver a la voz anterior: copiar `voices\anterior\mika_es_original.wav` y `.json` sobre
`voices\mika_es.*` (y `mika_preview_original.wav` sobre `voices\previews\mika.wav`). Los audios de ElevenLabs
están sujetos a sus condiciones de uso.

Voces retiradas del catálogo: Aiko (12 nov 2026) y las sintéticas Yuki, Hana, Haru, Riku, Aki y Sora (12 nov 2026).
Sus archivos siguen en `pc-gpu\voices` de waifuv3, sin usar: desde este proyecto no se borra nada de allí.
