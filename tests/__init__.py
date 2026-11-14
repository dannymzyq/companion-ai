"""Pruebas rápidas: piezas sueltas del companion, en segundos y sin GPU, micrófono, Ollama, nube ni servidores.

    .venv\\Scripts\\python.exe -m unittest discover -s tests -t .

Nada de esto toca lo del usuario: se usa una carpeta de datos temporal, las acciones van en seco
(COMPANION_ACTIONS_DRY) y el control de ventanas no puede usar el teclado ni el ratón reales. Las direcciones del
cerebro y de la voz apuntan a un puerto cerrado, así que ninguna prueba llega a un modelo.
Las pruebas completas (servidor de prueba, voz, Electron) siguen en scripts\\prueba_*.py.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="companion_pruebas_"))
NOWHERE = "http://127.0.0.1:9"                 # puerto cerrado: si algo intentara salir, falla al momento

# Antes de importar companion.*: companion.config lee el entorno (y .env, que no pisa lo que ya está aquí).
os.environ.update(DATA_DIR=str(TMP / "data"), MODELS_DIR=str(TMP / "models"), VOICE_INSTALL="0", VOICE_ENGINE="ligera",
                  LLM_PROVIDER="local", GEMINI_API_KEY="", OLLAMA_URL=NOWHERE, TTS_URL=NOWHERE, TTS_TOKEN="",
                  COMPANION_ACTIONS_DRY="1", COMPANION_CONTROL_NO_INPUT="1", HOST="127.0.0.1", PORT="8299",
                  USER_NAME="Ana")
sys.path.insert(0, str(ROOT))
