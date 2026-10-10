#!/usr/bin/env bash
# Costruisce l'AppImage del GoPro Anamorphic Toolkit con python-appimage.
#
# L'AppImage include: un runtime Python, PySide6 (GUI) e il pacchetto `gat`
# con il profilo lente di default. NON include Gyroflow né ffmpeg: restano
# requisiti esterni (vedi README).
#
# Uso:
#   packaging/build_appimage.sh [PYTHON_VERSION] [LINUX_TAG]
# Esempi:
#   packaging/build_appimage.sh              # default: 3.12 / manylinux_2_28_x86_64
#   packaging/build_appimage.sh 3.11
set -euo pipefail

PY_VER="${1:-3.12}"
LINUX_TAG="${2:-manylinux_2_28_x86_64}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RECIPE="$ROOT/packaging/appimage"
BUILD_DIR="$ROOT/packaging/build"

# Su sistemi senza FUSE appimagetool deve estrarsi ed eseguirsi.
export APPIMAGE_EXTRACT_AND_RUN=1

# Serve python-appimage e il pacchetto gat importabile (per "local+gat").
PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c "import python_appimage" 2>/dev/null; then
  echo "python-appimage non trovato. Installa con: pip install python-appimage" >&2
  exit 1
fi
if ! "$PYTHON" -c "import gat" 2>/dev/null; then
  echo "Il pacchetto 'gat' non è importabile. Installa prima: pip install -e ." >&2
  exit 1
fi

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

echo ">> Costruzione AppImage (Python $PY_VER, $LINUX_TAG)…"
"$PYTHON" -m python_appimage build app \
  -p "$PY_VER" \
  -l "$LINUX_TAG" \
  -n GoProAnamorphic \
  "$RECIPE"

# python-appimage produce un file *.AppImage nella cwd.
OUT="$(ls -t "$BUILD_DIR"/*.AppImage 2>/dev/null | head -n1 || true)"
if [ -z "$OUT" ]; then
  echo "Build fallita: nessun .AppImage prodotto." >&2
  exit 1
fi
FINAL="$ROOT/packaging/GoProAnamorphic-x86_64.AppImage"
mv -f "$OUT" "$FINAL"
chmod +x "$FINAL"
echo ">> Fatto: $FINAL ($(du -h "$FINAL" | cut -f1))"
