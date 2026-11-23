#!/usr/bin/env bash
# Crea la app para Mac con Apple Silicon: dist/Companion-X.Y.Z-mac.dmg con Companion.app dentro. Solo en macOS
# (lo hace .github/workflows/mac.yml en un Mac de GitHub; también a mano en un Mac).
#   bash scripts/instalacion/crear_app_mac.sh [X.Y.Z]
#
# Companion.app es Electron (la misma versión que la app de Windows, scripts/instalacion/instalar_escritorio.ps1) con:
#   Contents/Resources/app       la parte de escritorio (desktop/), que arranca por desktop/mac.js
#   Contents/Resources/programa  lo que está en git + manifest.json (huella SHA-256 y tamaño de cada archivo),
#                                que mac.js copia a ~/Library/Application Support/Companion e instala allí
# Va firmada «ad hoc» (sin cuenta de desarrollador de Apple): la primera vez macOS pide confirmar que se abra.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ="$(pwd)"
[ "$(uname -s)" = Darwin ] || { echo "Este script solo funciona en macOS."; exit 1; }
VERSION="${1:-$(tr -d '[:space:]' < VERSION)}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Version no valida: $VERSION"; exit 1; }
ELECTRON="$(grep -Eo 'Version = "[0-9.]+"' scripts/instalacion/instalar_escritorio.ps1 | grep -Eo '[0-9.]+')"
SALIDA="$RAIZ/dist"; mkdir -p "$SALIDA"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# ---------------------------------------------------------------- Electron para Apple Silicon (comprobado)
ARCHIVO="electron-v$ELECTRON-darwin-arm64.zip"
BASE="https://github.com/electron/electron/releases/download/v$ELECTRON"
echo "Descargando $ARCHIVO..."
curl -fsSL "$BASE/$ARCHIVO" -o "$TMP/$ARCHIVO"
ESPERADA="$(curl -fsSL "$BASE/SHASUMS256.txt" | grep -E "[ *]$ARCHIVO\$" | cut -d' ' -f1)"
REAL="$(shasum -a 256 "$TMP/$ARCHIVO" | cut -d' ' -f1)"
[ -n "$ESPERADA" ] && [ "$ESPERADA" = "$REAL" ] || { echo "La suma SHA-256 de Electron no coincide."; exit 1; }
mkdir "$TMP/electron"; ditto -x -k "$TMP/$ARCHIVO" "$TMP/electron"     # ditto conserva los enlaces de los frameworks
APP="$TMP/dmg/Companion.app"; mkdir -p "$TMP/dmg"
mv "$TMP/electron/Electron.app" "$APP"
RES="$APP/Contents/Resources"
rm -f "$RES/default_app.asar"

# ---------------------------------------------------------------- la parte de escritorio
mkdir -p "$RES/app"
# Todos los .js y .html de desktop/ (con una lista fija, la 0.8.0 se quedaba sin pet.js y main.js no arrancaba).
for f in desktop/*.js desktop/*.html desktop/icono.png; do
  cp "$f" "$RES/app/"
done
cat > "$RES/app/package.json" <<EOF
{ "name": "companion", "productName": "Companion", "version": "$VERSION", "main": "mac.js", "private": true }
EOF

# ---------------------------------------------------------------- el programa (lo que está en git)
P="$RES/programa"; mkdir -p "$P"
git -c core.quotepath=off ls-files -z --cached --others --exclude-standard |
  while IFS= read -r -d '' f; do
    case "$f" in .github/*|.gitignore|.gitattributes|movil/*|rust-live/*|docs/*) continue ;; esac
    [ -f "$f" ] || continue
    mkdir -p "$P/$(dirname "$f")"; cp -p "$f" "$P/$f"
  done
printf '%s' "$VERSION" > "$P/VERSION"
python3 - "$P" "$VERSION" <<'EOF'
import hashlib, json, os, sys
raiz, version = sys.argv[1], sys.argv[2]
files = []
for base, _, names in os.walk(raiz):
    for n in names:
        full = os.path.join(base, n)
        rel = os.path.relpath(full, raiz).replace(os.sep, "/")
        if rel == "manifest.json":
            continue
        data = open(full, "rb").read()
        files.append({"p": rel, "h": hashlib.sha256(data).hexdigest().upper(), "s": len(data)})
files.sort(key=lambda f: f["p"])
json.dump({"version": version, "files": files}, open(os.path.join(raiz, "manifest.json"), "w"), separators=(",", ":"))
print(f"manifest.json: {len(files)} archivos")
EOF

# ---------------------------------------------------------------- icono, nombre y permisos
if cp desktop/icono.png "$TMP/icono.png" 2>/dev/null; then   # 1024 px (scripts/instalacion/crear_icono.py)
  mkdir "$TMP/icono.iconset"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$TMP/icono.png" --out "$TMP/icono.iconset/icon_${s}x${s}.png" >/dev/null
    sips -z $((s * 2)) $((s * 2)) "$TMP/icono.png" --out "$TMP/icono.iconset/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$TMP/icono.iconset" -o "$RES/electron.icns" && echo "Icono listo."
else
  echo "No pude convertir el icono: se queda el de Electron."
fi
PL="$APP/Contents/Info.plist"
plutil -replace CFBundleName -string "Companion" "$PL"
plutil -replace CFBundleDisplayName -string "Companion" "$PL"
plutil -replace CFBundleIdentifier -string "app.companion.desktop" "$PL"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PL"
plutil -replace CFBundleVersion -string "$VERSION" "$PL"
plutil -replace LSMinimumSystemVersion -string "14.0" "$PL"
plutil -replace NSMicrophoneUsageDescription -string "Companion te escucha para conversar contigo. Lo que dices se transcribe en este Mac." "$PL"
plutil -replace NSCameraUsageDescription -string "Companion usa la cámara solo cuando la activas, para ver lo que le enseñas." "$PL"
plutil -replace NSScreenCaptureUsageDescription -string "Companion ve la pantalla o la ventana que eliges compartir." "$PL"

# Firma «ad hoc»: cambiar Info.plist y Resources invalida la firma de Electron, y en Apple Silicon todo
# ejecutable tiene que estar firmado.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP" && echo "Firma ad hoc correcta."

# ---------------------------------------------------------------- el .dmg
ln -s /Applications "$TMP/dmg/Aplicaciones"
cat > "$TMP/dmg/Léeme.txt" <<'EOF'
Companion para Mac (Apple Silicon, macOS 14 o posterior)

1. Arrastra Companion a la carpeta Aplicaciones.
2. Ábrelo. La app no está firmada por un desarrollador de Apple, así que la primera vez macOS no la deja abrir:
   ve a Ajustes del Sistema › Privacidad y seguridad y pulsa «Abrir igualmente» junto a Companion
   (en macOS 14 también vale clic derecho sobre la app › Abrir).
3. La primera vez descarga Python, el oído y las voces (unos 5 GB) y los guarda en
   ~/Library/Application Support/Companion, donde también quedan tus datos.

Para el cerebro local, instala Ollama desde https://ollama.com/download (opcional: también funciona con la nube).
EOF
DMG="$SALIDA/Companion-$VERSION-mac.dmg"
rm -f "$DMG"
hdiutil create -volname "Companion $VERSION" -srcfolder "$TMP/dmg" -ov -format UDZO "$DMG" >/dev/null
echo "Listo: $DMG ($(du -h "$DMG" | cut -f1))"
