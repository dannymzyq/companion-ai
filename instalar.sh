#!/usr/bin/env bash
# Instalador del companion para bash. Deja todo dentro de esta carpeta: Python, entornos y modelos.
#   bash instalar.sh [--voz=auto|completa|ligera|ambas] [--sin-ollama] [--sin-modelo-local] [--instalar-ollama]
#
# En Windows (Git Bash) llama a instalar.ps1, que es el instalador probado. En Linux y macOS hace lo mismo
# con las herramientas de bash; ahi no hay app de escritorio: el companion se abre en el navegador.
set -euo pipefail
cd "$(dirname "$0")"
RAIZ="$(pwd)"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    args=()
    for a in "$@"; do
      case "$a" in
        --voz=*) args+=(-Voz "${a#--voz=}") ;;
        --sin-ollama) args+=(-SinOllama) ;;
        --sin-modelo-local) args+=(-SinModeloLocal) ;;
        --no-rehacer) args+=(-NoRehacer) ;;
      esac
    done
    exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$RAIZ/instalar.ps1")" "${args[@]}"
    ;;
esac

VOZ=auto; OLLAMA=1; MODELO=1; INSTALAR_OLLAMA=0
for a in "$@"; do
  case "$a" in
    --voz=*) VOZ="${a#--voz=}" ;;
    --sin-ollama) OLLAMA=0 ;;
    --sin-modelo-local) MODELO=0 ;;
    --instalar-ollama) INSTALAR_OLLAMA=1 ;;
    *) echo "Opcion desconocida: $a"; exit 2 ;;
  esac
done
paso() { printf '\n== %s\n' "$1"; }

# ---------------------------------------------------------------- 1. uv y Python propios
paso "Python propio (runtime/)"
UV="$RAIZ/runtime/uv"
export UV_PYTHON_INSTALL_DIR="$RAIZ/runtime/python" UV_CACHE_DIR="$RAIZ/runtime/cache"
if [ ! -x "$UV" ]; then
  mkdir -p runtime
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) T=uv-x86_64-unknown-linux-gnu ;;
    Linux-aarch64) T=uv-aarch64-unknown-linux-gnu ;;
    Darwin-arm64) T=uv-aarch64-apple-darwin ;;
    Darwin-x86_64) T=uv-x86_64-apple-darwin ;;
    *) echo "Sistema no previsto: $(uname -s) $(uname -m)"; exit 1 ;;
  esac
  echo "Descargando uv (gestor de Python) de github.com/astral-sh/uv..."
  curl -fsSL "https://github.com/astral-sh/uv/releases/latest/download/$T.tar.gz" | tar -xz -C runtime --strip-components=1
fi
"$UV" python install 3.13

entorno() {   # crea el entorno con el Python de runtime/; uno hecho con un Python de fuera se rehace
  if [ -x "$1/bin/python" ] && grep -i '^ *home' "$1/pyvenv.cfg" 2>/dev/null | grep -qF "$RAIZ"; then return; fi
  rm -rf "$1"
  "$UV" venv --python 3.13 "$1"
}

# ---------------------------------------------------------------- 2. el companion
paso "Entorno del companion (.venv)"
entorno "$RAIZ/.venv"
PY="$RAIZ/.venv/bin/python"
REQ=requirements.txt
if [ "$(uname -s)" = Darwin ]; then   # las librerias de NVIDIA no existen en macOS: el oido va en el procesador
  grep -v '^nvidia' requirements.txt > runtime/requirements-mac.txt; REQ=runtime/requirements-mac.txt
fi
"$UV" pip install --python "$PY" -r "$REQ"

paso "Librerias de la interfaz (web/vendor)"
THREE=0.180.0; VRM=3.5.5; CDN=https://cdn.jsdelivr.net/npm
while read -r url dst; do
  [ -f "$dst" ] && continue
  mkdir -p "$(dirname "$dst")"; echo "Descargando $url"; curl -fsSL "$url" -o "$dst"
done <<EOF
$CDN/three@$THREE/build/three.module.min.js web/vendor/three/build/three.module.min.js
$CDN/three@$THREE/build/three.core.min.js web/vendor/three/build/three.core.min.js
$CDN/three@$THREE/examples/jsm/loaders/GLTFLoader.js web/vendor/three/examples/jsm/loaders/GLTFLoader.js
$CDN/three@$THREE/examples/jsm/utils/BufferGeometryUtils.js web/vendor/three/examples/jsm/utils/BufferGeometryUtils.js
$CDN/three@$THREE/examples/jsm/controls/OrbitControls.js web/vendor/three/examples/jsm/controls/OrbitControls.js
$CDN/@pixiv/three-vrm@$VRM/lib/three-vrm.module.min.js web/vendor/three-vrm/three-vrm.module.min.js
EOF

# ---------------------------------------------------------------- 3. modelos segun la tarjeta
paso "Recursos segun tu PC"
read -r VOZ_REC MODELO_REC GB <<<"$("$PY" scripts/preparar_recursos.py --recomendar)"
echo "Memoria de video: $GB GB -> voz recomendada: $VOZ_REC, modelo local recomendado: $MODELO_REC"
if [ "$VOZ" = auto ]; then if [ "$VOZ_REC" = completa ]; then VOZ=ambas; else VOZ=ligera; fi; fi

"$PY" scripts/preparar_recursos.py --oido
case "$VOZ" in ligera|ambas) "$PY" scripts/preparar_recursos.py --ligera ;; esac
case "$VOZ" in completa|ambas)
  paso "Voz completa (voz/): PyTorch + F5-TTS, varios GB"
  entorno "$RAIZ/voz/.venv"
  "$UV" pip install --python "$RAIZ/voz/.venv/bin/python" torch==2.12.1 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130
  "$UV" pip install --python "$RAIZ/voz/.venv/bin/python" -r voz/requirements.txt
  "$PY" scripts/preparar_recursos.py --completa ;;
esac

# ---------------------------------------------------------------- 4. cerebro local (Ollama)
if [ "$OLLAMA" = 1 ]; then
  paso "Cerebro local (Ollama)"
  if ! command -v ollama >/dev/null 2>&1; then
    if [ "$INSTALAR_OLLAMA" = 1 ]; then curl -fsSL https://ollama.com/install.sh | sh
    else echo "Ollama no esta instalado. Instalalo desde https://ollama.com/download (o repite con --instalar-ollama) para usar el cerebro local."; fi
  fi
  if command -v ollama >/dev/null 2>&1 && [ "$MODELO" = 1 ]; then
    curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 || { nohup ollama serve >/dev/null 2>&1 & sleep 4; }
    if ollama list 2>/dev/null | grep -qF "$MODELO_REC"; then echo "El modelo $MODELO_REC ya esta descargado."
    else echo "Descargando el modelo local $MODELO_REC..."; ollama pull "$MODELO_REC"; fi
  fi
fi

[ -f .env ] || cp .env.example .env
mkdir -p data
paso "Listo"
echo "Abre el companion con:  bash iniciar.sh"
