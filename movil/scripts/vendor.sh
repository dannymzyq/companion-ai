#!/bin/bash
# Librerías 3D de la interfaz (las mismas versiones que instalar.sh) en movil/vendor/, fuera de git.
# Uso: movil/scripts/vendor.sh [carpeta web/vendor ya descargada, para copiarla en vez de bajarla]
set -euo pipefail
cd "$(dirname "$0")/.."
DST=vendor
THREE=0.180.0; VRM=3.5.5; CDN=https://cdn.jsdelivr.net/npm
if [ -n "${1:-}" ]; then
  mkdir -p "$DST" && cp -R "$1"/. "$DST"/ && echo "Copiado de $1" && exit 0
fi
while read -r url dst; do
  [ -f "$DST/$dst" ] && continue
  mkdir -p "$(dirname "$DST/$dst")"; echo "Descargando $url"; curl -fsSL "$url" -o "$DST/$dst"
done <<LISTA
$CDN/three@$THREE/build/three.module.min.js three/build/three.module.min.js
$CDN/three@$THREE/build/three.core.min.js three/build/three.core.min.js
$CDN/three@$THREE/examples/jsm/loaders/GLTFLoader.js three/examples/jsm/loaders/GLTFLoader.js
$CDN/three@$THREE/examples/jsm/utils/BufferGeometryUtils.js three/examples/jsm/utils/BufferGeometryUtils.js
$CDN/three@$THREE/examples/jsm/controls/OrbitControls.js three/examples/jsm/controls/OrbitControls.js
$CDN/@pixiv/three-vrm@$VRM/lib/three-vrm.module.min.js three-vrm/three-vrm.module.min.js
LISTA
