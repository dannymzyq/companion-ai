#!/bin/bash
# Fase de compilación de Xcode: copia la interfaz y el núcleo dentro de la app (carpeta www del paquete).
# Lo mismo servirá para Android (assets/www) cambiando DEST.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="${DEST:-$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH/www}"
if [ ! -f "$REPO/movil/vendor/three-vrm/three-vrm.module.min.js" ]; then
  echo "error: faltan las librerías 3D: ejecuta movil/scripts/vendor.sh" >&2; exit 1
fi
rm -rf "$DEST"; mkdir -p "$DEST/models" "$DEST/data" "$DEST/voices"
rsync -a --exclude vendor "$REPO/web/" "$DEST/"
rsync -a "$REPO/movil/vendor/" "$DEST/vendor/"
rsync -a --exclude '*.test.js' "$REPO/movil/core/" "$DEST/core/"
cp "$REPO/models/avatar1.vrm" "$REPO/models/avatar2.vrm" "$DEST/models/"
rsync -a "$REPO/voices/previews/" "$DEST/voices/previews/"
cp "$REPO/personas/mika.json" "$DEST/data/persona.json"
cp "$REPO/voices.json" "$DEST/data/voices.json"
