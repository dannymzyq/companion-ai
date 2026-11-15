#!/usr/bin/env bash
# Arranca el companion desde bash. En Windows (Git Bash) usa iniciar.ps1; en Linux y macOS arranca el servidor
# y lo abre en el navegador (en el Mac, la app Companion.app lo arranca con --sin-ventana y lo muestra ella).
# La voz completa la arranca y la para el propio companion (voz/servidor.py).
#   bash iniciar.sh [--sin-ventana]
set -euo pipefail
cd "$(dirname "$0")"
RAIZ="$(pwd)"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    args=(); [ "${1:-}" = --sin-ventana ] && args+=(-SinVentana)
    exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$RAIZ/iniciar.ps1")" "${args[@]}" ;;
  Darwin) export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:/Applications/Ollama.app/Contents/Resources" ;;
esac

[ -x .venv/bin/python ] || bash instalar.sh
[ -f .env ] || cp .env.example .env
leer_puerto() { grep -E '^\s*PORT\s*=' .env | head -1 | tr -dc '0-9' || true; }
PUERTO="$(leer_puerto)"; PUERTO="${PUERTO:-8200}"
URL="http://127.0.0.1:$PUERTO"
vivo() { curl -fsS "$URL/api/config" >/dev/null 2>&1; }
ocupado() { .venv/bin/python -c "import socket,sys; s=socket.socket(); sys.exit(s.connect_ex(('127.0.0.1', int(sys.argv[1]))) != 0)" "$1"; }

if command -v ollama >/dev/null 2>&1 && ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  mkdir -p data   # se anota que lo abrió el companion: detener.sh lo cierra al salir (si ya estaba abierto, no)
  if [ "$(uname -s)" = Darwin ] && [ -d /Applications/Ollama.app ]; then open -ga Ollama && echo app >data/ollama.started
  else nohup ollama serve >/dev/null 2>&1 & echo $! >data/ollama.started; fi
fi
if ! vivo; then
  if ocupado "$PUERTO"; then   # otro programa usa ese puerto: se elige uno libre y se guarda en .env
    NUEVO="$(.venv/bin/python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])")"
    echo "El puerto $PUERTO lo usa otro programa: el companion usara el $NUEVO."
    if grep -qE '^\s*PORT\s*=' .env; then sed -i.bak -E "s/^\s*PORT\s*=.*/PORT=$NUEVO/" .env && rm -f .env.bak
    else printf '\nPORT=%s\n' "$NUEVO" >>.env; fi
    PUERTO="$NUEVO"; URL="http://127.0.0.1:$PUERTO"
  fi
  mkdir -p data
  for n in 3 2 1; do   # se guardan los registros de las tres veces anteriores (companion.1.log es la última)
    if [ "$n" = 1 ]; then antes=data/companion.log; else antes="data/companion.$((n - 1)).log"; fi
    [ -f "$antes" ] && mv -f "$antes" "data/companion.$n.log"
  done
  nohup .venv/bin/python -m companion >data/companion.log 2>&1 &
  echo $! >data/companion.pid
  for _ in $(seq 1 120); do sleep 0.5; vivo && break; done
  vivo || { echo "El companion no arranco. Mira data/companion.log."; exit 1; }
fi
echo "Companion en $URL"
[ "${1:-}" = --sin-ventana ] && exit 0
if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then open "$URL"; fi
