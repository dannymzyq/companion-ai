#!/usr/bin/env bash
# Instalador del companion para bash. Deja todo dentro de esta carpeta: Python, entornos y modelos.
#   bash instalar.sh [--voz=auto|completa|ligera|ambas] [--sin-ollama] [--sin-modelo-local] [--instalar-ollama]
#
# En Windows (Git Bash) llama a instalar.ps1, que es el instalador probado. En macOS (Apple Silicon, 14 o
# posterior) lo usa la app Companion.app (desktop/mac.js) la primera vez y en cada versión nueva; en Linux, el
# companion se abre en el navegador. Con COMPANION_UI=1 imprime las mismas marcas que instalar.ps1
# (::paso::id, ::omitido::id, ::progreso::NN::texto, ::error::texto, ::fin::) para la ventana de instalación.
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
MAC=0; [ "$(uname -s)" = Darwin ] && MAC=1
UI="${COMPANION_UI:-0}"
marca() { if [ "$UI" = 1 ]; then printf '::%s::%s\n' "$1" "${2:-}"; fi; }
paso() { marca paso "$1"; printf '\n== %s\n' "$2"; }
trap 'marca error "Fallo: $BASH_COMMAND (linea $LINENO)"' ERR
# Ollama para Mac es una app: su programa de consola vive dentro de ella.
[ "$MAC" = 1 ] && export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:/Applications/Ollama.app/Contents/Resources"

# ---------------------------------------------------------------- 1. uv y Python propios
paso python "Python propio (runtime/)"
UV="$RAIZ/runtime/uv"
export UV_PYTHON_INSTALL_DIR="$RAIZ/runtime/python" UV_CACHE_DIR="$RAIZ/runtime/cache"
if [ ! -x "$UV" ]; then
  mkdir -p runtime
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) T=uv-x86_64-unknown-linux-gnu ;;
    Linux-aarch64) T=uv-aarch64-unknown-linux-gnu ;;
    Darwin-arm64) T=uv-aarch64-apple-darwin ;;
    *) echo "Sistema no previsto: $(uname -s) $(uname -m) (en Mac hace falta Apple Silicon)"; marca error "Este Mac no tiene Apple Silicon"; exit 1 ;;
  esac
  UV_VERSION=0.13.8   # la misma que instalar.ps1; se comprueba con la suma SHA-256 que publica uv
  echo "Descargando uv $UV_VERSION (gestor de Python) de github.com/astral-sh/uv..."
  base="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$T.tar.gz"
  curl -fsSL "$base" -o runtime/uv.tar.gz
  suma="$(curl -fsSL "$base.sha256" | cut -d' ' -f1)"
  real="$( (sha256sum runtime/uv.tar.gz 2>/dev/null || shasum -a 256 runtime/uv.tar.gz) | cut -d' ' -f1)"
  if [ -z "$suma" ] || [ "$suma" != "$real" ]; then rm -f runtime/uv.tar.gz; marca error "La descarga de uv no coincide con su suma SHA-256"; exit 1; fi
  tar -xzf runtime/uv.tar.gz -C runtime --strip-components=1 && rm -f runtime/uv.tar.gz
fi
"$UV" python install 3.13 --no-bin          # nada fuera de esta carpeta

entorno() {   # crea el entorno con el Python de runtime/; uno hecho con un Python de fuera se rehace
  if [ -x "$1/bin/python" ] && grep -i '^ *home' "$1/pyvenv.cfg" 2>/dev/null | grep -qF "$RAIZ"; then return; fi
  rm -rf "$1"
  "$UV" venv --python 3.13 "$1"
}

# ---------------------------------------------------------------- 2. el companion
paso companion "Entorno del companion (.venv)"
entorno "$RAIZ/.venv"
PY="$RAIZ/.venv/bin/python"
if [ "$MAC" = 1 ]; then   # versiones fijas para el Mac (sin las librerias de NVIDIA: el oido va en el procesador)
  "$UV" pip install --python "$PY" -r requirements-mac.lock
else
  "$UV" pip install --python "$PY" -r requirements.txt
fi

paso interfaz "Librerias de la interfaz (web/vendor)"
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
paso recursos "Recursos segun tu equipo"
read -r VOZ_REC MODELO_REC GB <<<"$("$PY" scripts/preparar_recursos.py --recomendar)"
echo "Memoria de video: $GB GB -> voz recomendada: $VOZ_REC, modelo local recomendado: $MODELO_REC"
# Las dos voces desde 6 GB (si con el modelo local no cabe la completa, el companion pasa solo a la ligera).
if [ "$VOZ" = auto ]; then if awk "BEGIN{exit !($GB >= 5.5)}"; then VOZ=ambas; else VOZ=ligera; fi; fi

paso oido "El oido (Whisper)"
"$PY" scripts/preparar_recursos.py --oido
case "$VOZ" in
  ligera|ambas) paso ligera "Voz ligera (Piper)"; "$PY" scripts/preparar_recursos.py --ligera ;;
  *) marca omitido ligera ;;
esac
case "$VOZ" in
  completa|ambas)
    paso torch "Voz completa (voz/): PyTorch + F5-TTS, varios GB"
    entorno "$RAIZ/voz/.venv"
    if [ "$MAC" = 1 ]; then   # PyTorch para Apple Silicon (usa la GPU del Mac: MPS) va en el lock del Mac
      "$UV" pip install --python "$RAIZ/voz/.venv/bin/python" -r voz/requirements-mac.lock
    else
      "$UV" pip install --python "$RAIZ/voz/.venv/bin/python" torch==2.12.1 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130
      "$UV" pip install --python "$RAIZ/voz/.venv/bin/python" -r voz/requirements.txt
    fi
    paso f5 "Voz completa: modelo de F5-TTS"
    "$PY" scripts/preparar_recursos.py --completa ;;
  *) marca omitido torch; marca omitido f5 ;;
esac

# ---------------------------------------------------------------- 4. cerebro local (Ollama)
if [ "$OLLAMA" = 1 ]; then
  paso ollama "Cerebro local (Ollama)"
  if ! command -v ollama >/dev/null 2>&1; then
    if [ "$INSTALAR_OLLAMA" = 1 ] && [ "$MAC" = 0 ]; then curl -fsSL https://ollama.com/install.sh | sh
    else echo "Ollama no esta instalado. Para usar el cerebro local, instalalo desde https://ollama.com/download"; fi
  fi
  if command -v ollama >/dev/null 2>&1 && [ "$MODELO" = 1 ]; then
    if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      if [ "$MAC" = 1 ] && [ -d /Applications/Ollama.app ]; then open -ga Ollama; else nohup ollama serve >/dev/null 2>&1 & fi
      sleep 4
    fi
    if ollama list 2>/dev/null | grep -qF "$MODELO_REC"; then echo "El modelo $MODELO_REC ya esta descargado."
    else echo "Descargando el modelo local $MODELO_REC..."; "$PY" scripts/preparar_recursos.py --ollama "$MODELO_REC"; fi
  fi
else
  marca omitido ollama
fi

paso final "Ultimos detalles"
[ -f .env ] || cp .env.example .env
mkdir -p data
printf '\n== Listo\n'
echo "Abre el companion con:  bash iniciar.sh"
marca fin
