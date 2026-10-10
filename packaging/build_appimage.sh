#!/usr/bin/env bash
# Build the GoPro Anamorphic Toolkit AppImage with python-appimage.
#
# The AppImage bundles a Python runtime, PySide6 (GUI) and the `gat` package
# with its resources (default lens profile, preview images). It does NOT bundle
# Gyroflow or ffmpeg: those stay external requirements (see README).
#
# Usage:
#   packaging/build_appimage.sh [PYTHON_VERSION] [LINUX_TAG]
# Examples:
#   packaging/build_appimage.sh              # default: 3.12 / manylinux_2_28_x86_64
#   packaging/build_appimage.sh 3.11
set -euo pipefail

PY_VER="${1:-3.12}"
LINUX_TAG="${2:-manylinux_2_28_x86_64}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RECIPE="$ROOT/packaging/appimage"
BUILD_DIR="$ROOT/packaging/build"

# Without FUSE, appimagetool must extract itself and run.
export APPIMAGE_EXTRACT_AND_RUN=1

# python-appimage is required, and `gat` must be importable (for "local+gat").
PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c "import python_appimage" 2>/dev/null; then
  echo "python-appimage not found. Install it with: pip install python-appimage" >&2
  exit 1
fi
if ! "$PYTHON" -c "import gat" 2>/dev/null; then
  echo "The 'gat' package is not importable. Install it first: pip install -e ." >&2
  exit 1
fi

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

echo ">> Building AppImage (Python $PY_VER, $LINUX_TAG)…"
# Note: the desktop file Name= must not contain spaces — python-appimage passes
# the output name to appimagetool unquoted.
"$PYTHON" -m python_appimage build app \
  -p "$PY_VER" \
  -l "$LINUX_TAG" \
  -n GoProAnamorphic \
  "$RECIPE"

# python-appimage writes a *.AppImage into the current directory.
OUT="$(ls -t "$BUILD_DIR"/*.AppImage 2>/dev/null | head -n1 || true)"
if [ -z "$OUT" ]; then
  echo "Build failed: no .AppImage produced." >&2
  exit 1
fi
FINAL="$ROOT/packaging/GoProAnamorphic-x86_64.AppImage"
mv -f "$OUT" "$FINAL"
chmod +x "$FINAL"
echo ">> Done: $FINAL ($(du -h "$FINAL" | cut -f1))"
