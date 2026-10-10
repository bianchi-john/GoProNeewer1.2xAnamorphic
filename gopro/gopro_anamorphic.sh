#!/usr/bin/env bash
# GoPro Hero 11 + Neewer LS-56 1.2x: stabilization (Gyroflow) + desqueeze + 1080p export
#
# HISTORICAL REFERENCE: this is the original bash script the Python toolkit was
# rewritten from. It is kept for reference only — use the `gat` CLI/GUI instead
# (which, unlike this script, exports at full resolution and supports 16:9 only).
#
# Usage:
#   ./gopro_anamorphic.sh INPUT_FOLDER OUTPUT_FOLDER [preset.gyroflow]
#
# Examples:
#   ./gopro_anamorphic.sh ~/gopro_raw ~/gopro_final neewer.gyroflow   # stabilize + desqueeze
#   ./gopro_anamorphic.sh ~/gopro_raw ~/gopro_final                   # desqueeze only (no preset)
#
# Optional variables:
#   SQUEEZE=1.2        anamorphic factor of the lens
#   ASPECT=16:9        final format: 16:9 (TV) or 2:1, 2.39:1 etc.
#   WIDTH=1920         final width
#   ZOOM=1.0           extra center crop (e.g. 1.2 = trims 20% to remove the vignetting)
#   CRF=22             H.265 quality (lower = better and heavier; 20-24 is a good range)
#   GYROFLOW=gyroflow  path of the Gyroflow executable/AppImage

set -euo pipefail

IN_DIR="${1:?Specify the folder with the original GoPro files}"
OUT_DIR="${2:?Specify the output folder}"
PRESET="${3:-}"

SQUEEZE="${SQUEEZE:-1.2}"
ASPECT="${ASPECT:-16:9}"
WIDTH="${WIDTH:-1920}"
ZOOM="${ZOOM:-1.0}"
CRF="${CRF:-22}"
GYROFLOW="${GYROFLOW:-gyroflow}"

command -v ffmpeg >/dev/null || { echo "ffmpeg not found: sudo apt install ffmpeg"; exit 1; }

if [[ -n "$PRESET" ]]; then
  [[ -f "$PRESET" ]] || { echo "Preset not found: $PRESET"; exit 1; }
  command -v "$GYROFLOW" >/dev/null || [[ -x "$GYROFLOW" ]] || {
    echo "Gyroflow not found. Download the AppImage from gyroflow.xyz and run with GYROFLOW=/path/Gyroflow.AppImage"; exit 1; }
fi

mkdir -p "$OUT_DIR"
WORK_DIR="$OUT_DIR/.tmp_stabilized"
mkdir -p "$WORK_DIR"

# Final aspect ratio as a number (e.g. 16:9 -> 1.7778)
AR=$(awk -F: '{ if (NF==2) printf "%.6f", $1/$2; else printf "%.6f", $1 }' <<< "$ASPECT")
HEIGHT=$(awk -v w="$WIDTH" -v ar="$AR" 'BEGIN { h=int(w/ar+0.5); if (h%2) h--; print h }')

# Filter: horizontal desqueeze -> centered crop to the chosen format -> resize
# The crop also removes the vignetted corners of 4:3.
VF="scale=trunc(iw*${SQUEEZE}/2)*2:ih:flags=lanczos,setsar=1,\
crop='min(iw,trunc(ih*${AR}/2)*2)':'min(ih,trunc(iw/${AR}/2)*2)',\
crop=trunc(iw/${ZOOM}/2)*2:trunc(ih/${ZOOM}/2)*2,\
scale=${WIDTH}:${HEIGHT}:flags=lanczos"

shopt -s nullglob nocaseglob
FILES=("$IN_DIR"/*.mp4)
shopt -u nocaseglob
[[ ${#FILES[@]} -gt 0 ]] || { echo "No .MP4 in $IN_DIR"; exit 1; }

for SRC in "${FILES[@]}"; do
  NAME=$(basename "${SRC%.*}")
  FINAL="$OUT_DIR/${NAME}_anamorphic_${WIDTH}x${HEIGHT}.mp4"
  echo "=== $NAME ==="

  if [[ -f "$FINAL" ]]; then
    echo "Already done, skipping."; continue
  fi

  INPUT_FOR_FFMPEG="$SRC"

  if [[ -n "$PRESET" ]]; then
    # Gyroflow reads the gyro data (GPMF) straight from the original file
    cp -n "$SRC" "$WORK_DIR/"
    "$GYROFLOW" "$WORK_DIR/$(basename "$SRC")" --preset "$PRESET" -f
    STAB=$(ls -t "$WORK_DIR/${NAME}_stabilized".* 2>/dev/null | head -n1 || true)
    if [[ -z "$STAB" ]]; then
      echo "Gyroflow output not found for $NAME, skipping."; continue
    fi
    INPUT_FOR_FFMPEG="$STAB"
  fi

  ffmpeg -hide_banner -loglevel warning -stats -y \
    -i "$INPUT_FOR_FFMPEG" \
    -map 0:v:0 -map "0:a:0?" \
    -vf "$VF" \
    -c:v libx265 -crf "$CRF" -preset medium -tag:v hvc1 -pix_fmt yuv420p \
    -c:a aac -b:a 192k \
    -movflags +faststart \
    "$FINAL"

  echo "-> $FINAL ($(du -h "$FINAL" | cut -f1))"
done

rm -rf "$WORK_DIR"
echo "Done. Check the results before deleting the originals!"
