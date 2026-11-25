"""Entorno aislado para las pruebas automáticas.

Las pruebas no usan el companion real (puede estar en uso): levantan otro servidor en el puerto 8201 con su
propia carpeta de datos y de modelos (data/prueba), así nunca tocan la conversación, los recuerdos ni los
modelos del usuario, ni reinician su servidor.

Importar este módulo ANTES que `companion.*`: fija las variables de entorno que lee companion.config.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
TEST_DIR = ROOT / "data" / "prueba"
PORT = 8201
URL = f"http://127.0.0.1:{PORT}"
# El Electron de desktop/electron (scripts/instalacion/instalar_escritorio.ps1 en Windows; en el Mac, Electron.app de
# electron-vX-darwin-arm64.zip descomprimido ahí). COMPANION_ELECTRON elige otro.
ELECTRON = Path(os.environ.get("COMPANION_ELECTRON") or (
    ROOT / "desktop" / "electron" / ("Electron.app/Contents/MacOS/Electron" if sys.platform == "darwin" else "electron.exe")))

os.environ.update(VOICE_INSTALL="0",      # las pruebas no copian voces a la carpeta del nodo de voz
                  PORT=str(PORT), HOST="127.0.0.1", DATA_DIR=str(TEST_DIR), MODELS_DIR=str(TEST_DIR / "models"))
sys.path.insert(0, str(ROOT))


def cerrar(proc):
    """Cierra un proceso de prueba (Electron, el servidor) con sus hijos, en Windows y en Mac/Linux."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        return
    subprocess.run(["pkill", "-TERM", "-P", str(proc.pid)], capture_output=True)
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


class Servidor:
    """with Servidor(): ...  → servidor de prueba listo (Whisper cargado) y apagado al salir.
    Por defecto arranca con la bienvenida ya hecha (un usuario adulto de prueba); `nuevo=True` la deja pendiente."""

    def __init__(self, nuevo: bool = False, ajustes: dict | None = None):
        self.nuevo = nuevo
        self.ajustes = ajustes or {}      # más ajustes guardados de partida (p. ej. «solo nube»)

    def __enter__(self):
        modelos = TEST_DIR / "models"
        modelos.mkdir(parents=True, exist_ok=True)
        # Una prueba que importó companion.actions (que importa store) tiene abierta la base de prueba: se cierra
        # antes de borrarla (si no, en Windows «está siendo utilizado por otro proceso»).
        abierta = sys.modules.get("companion.store")
        if abierta is not None and str(getattr(abierta.settings, "data_dir", "")) == str(TEST_DIR):
            abierta._db.close()
        for sobrante in (TEST_DIR / "companion.db", TEST_DIR / "settings.json"):
            sobrante.unlink(missing_ok=True)
        if not self.nuevo:
            import json
            (TEST_DIR / "settings.json").write_text(json.dumps(
                {"onboarded": True, "profile": {"name": "Danny", "birth_year": 1990, "gender": "hombre"}, **self.ajustes},
                ensure_ascii=False), encoding="utf-8")
        shutil.rmtree(modelos / "custom", ignore_errors=True)
        for nombre in ("avatar1.vrm", "avatar2.vrm"):                # los personajes incluidos
            original = ROOT / "models" / nombre
            if original.exists() and not (modelos / nombre).exists():
                shutil.copy2(original, modelos / nombre)
        self.log = open(TEST_DIR / "servidor.log", "w", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, "-m", "companion"], cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                     stdout=self.log, stderr=subprocess.STDOUT)
        limite = time.monotonic() + 120
        while time.monotonic() < limite:
            if self.proc.poll() is not None:
                raise SystemExit(f"El servidor de prueba no arrancó: mira {TEST_DIR / 'servidor.log'}")
            try:
                if httpx.get(f"{URL}/api/config", timeout=2).json()["stt"]["ready"]:
                    return self
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        self.__exit__()
        raise SystemExit("El servidor de prueba tardó demasiado en estar listo")

    def __exit__(self, *_):
        cerrar(self.proc)   # el servidor y sus hijos (la voz completa, si la arrancó)
        self.log.close()
