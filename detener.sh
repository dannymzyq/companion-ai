#!/usr/bin/env bash
# Apaga el companion desde bash (al cerrarse apaga tambien el servidor de voz y descarga el modelo local).
cd "$(dirname "$0")"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$(pwd)/detener.ps1")" ;;
esac
if [ -f data/companion.pid ] && kill "$(cat data/companion.pid)" 2>/dev/null; then echo "Companion detenido."
else echo "El companion no estaba en marcha."; fi
rm -f data/companion.pid
