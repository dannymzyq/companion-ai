#!/usr/bin/env bash
# Arranca el companion desde bash. En Windows (Git Bash) usa iniciar.ps1; en Linux y macOS arranca el servidor
# y lo abre en el navegador. La voz completa la arranca y la para el propio companion (voz/servidor.py).
#   bash iniciar.sh [--sin-ventana]
set -euo pipefail
cd "$(dirname "$0")"
RAIZ="$(pwd)"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    args=(); [ "${1:-}" = --sin-ventana ] && args+=(-SinVentana)
    exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$RAIZ/iniciar.ps1")" "${args[@]}" ;;
esac

[ -x .venv/bin/python ] || bash instalar.sh
[ -f .env ] || cp .env.example .env
PUERTO="$(grep -E '^\s*PORT\s*=' .env | head -1 | tr -dc '0-9' || true)"; PUERTO="${PUERTO:-8200}"
URL="http://127.0.0.1:$PUERTO"
vivo() { curl -fsS "$URL/api/config" >/dev/null 2>&1; }

if command -v ollama >/dev/null 2>&1 && ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  nohup ollama serve >/dev/null 2>&1 &
fi
if ! vivo; then
  mkdir -p data
  nohup .venv/bin/python -m companion >data/companion.log 2>&1 &
  echo $! >data/companion.pid
  for _ in $(seq 1 40); do sleep 0.5; vivo && break; done
  vivo || { echo "El companion no arranco. Ultimas lineas del registro:"; tail -15 data/companion.log; exit 1; }
fi
echo "Companion en $URL"
[ "${1:-}" = --sin-ventana ] && exit 0
if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then open "$URL"; fi
