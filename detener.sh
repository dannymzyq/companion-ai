#!/usr/bin/env bash
# Apaga todo lo que arrancó el companion (lo ejecuta la app al cerrarse): primero un apagado ordenado del servidor
# (/api/shutdown para la voz completa y saca el modelo local), luego lo que quede con sus hijos, y Ollama si lo
# abrió iniciar.sh (data/ollama.started).
cd "$(dirname "$0")"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$(pwd)/detener.ps1")" ;;
esac
PUERTO="$(grep -E '^\s*PORT\s*=' .env 2>/dev/null | head -1 | tr -dc '0-9')"; PUERTO="${PUERTO:-8200}"
PID="$(cat data/companion.pid 2>/dev/null || true)"
vivo() { [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; }
if vivo; then
  curl -fsS -m 4 -X POST "http://127.0.0.1:$PUERTO/api/shutdown" >/dev/null 2>&1 || true
  for _ in $(seq 1 40); do vivo || break; sleep 0.25; done
  if vivo; then
    pkill -TERM -P "$PID" 2>/dev/null || true; kill -TERM "$PID" 2>/dev/null || true
    for _ in $(seq 1 20); do vivo || break; sleep 0.25; done
    pkill -KILL -P "$PID" 2>/dev/null || true; kill -KILL "$PID" 2>/dev/null || true
  fi
  echo "Companion detenido."
else
  echo "El companion no estaba en marcha."
fi
rm -f data/companion.pid
# la voz completa, por si quedó suelta (voz/servidor.py en el puerto 8210)
pkill -f "uvicorn servidor:app --app-dir $(pwd)/voz" 2>/dev/null || true
if [ -f data/ollama.started ]; then
  QUIEN="$(cat data/ollama.started)"
  if [ "$QUIEN" = app ]; then osascript -e 'quit app "Ollama"' >/dev/null 2>&1 || true
  elif [ -n "$QUIEN" ]; then kill "$QUIEN" 2>/dev/null || true; fi
  rm -f data/ollama.started
  echo "Ollama cerrado (lo había abierto el companion)."
fi
