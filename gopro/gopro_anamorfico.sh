#!/usr/bin/env bash
# GoPro Hero 11 + Neewer LS-56 1.2x: stabilizzazione (Gyroflow) + desqueeze + export 1080p
#
# Uso:
#   ./gopro_anamorfico.sh CARTELLA_INPUT CARTELLA_OUTPUT [preset.gyroflow]
#
# Esempi:
#   ./gopro_anamorfico.sh ~/gopro_raw ~/gopro_finali neewer.gyroflow   # stabilizza + desqueeze
#   ./gopro_anamorfico.sh ~/gopro_raw ~/gopro_finali                   # solo desqueeze (nessun preset)
#
# Variabili opzionali:
#   SQUEEZE=1.2        fattore anamorfico della lente
#   ASPECT=16:9        formato finale: 16:9 (TV) oppure 2:1, 2.39:1 ecc.
#   WIDTH=1920         larghezza finale
#   ZOOM=1.0           ritaglio centrale extra (es. 1.2 = taglia il 20% per eliminare la vignettatura)
#   CRF=22             qualita' H.265 (piu' basso = migliore e piu' pesante; 20-24 e' un buon range)
#   GYROFLOW=gyroflow  percorso dell'eseguibile/AppImage di Gyroflow

set -euo pipefail

IN_DIR="${1:?Specifica la cartella con i file originali della GoPro}"
OUT_DIR="${2:?Specifica la cartella di output}"
PRESET="${3:-}"

SQUEEZE="${SQUEEZE:-1.2}"
ASPECT="${ASPECT:-16:9}"
WIDTH="${WIDTH:-1920}"
ZOOM="${ZOOM:-1.0}"
CRF="${CRF:-22}"
GYROFLOW="${GYROFLOW:-gyroflow}"

command -v ffmpeg >/dev/null || { echo "ffmpeg non trovato: sudo apt install ffmpeg"; exit 1; }

if [[ -n "$PRESET" ]]; then
  [[ -f "$PRESET" ]] || { echo "Preset non trovato: $PRESET"; exit 1; }
  command -v "$GYROFLOW" >/dev/null || [[ -x "$GYROFLOW" ]] || {
    echo "Gyroflow non trovato. Scarica l'AppImage da gyroflow.xyz e lancia con GYROFLOW=/percorso/Gyroflow.AppImage"; exit 1; }
fi

mkdir -p "$OUT_DIR"
WORK_DIR="$OUT_DIR/.tmp_stabilizzati"
mkdir -p "$WORK_DIR"

# Rapporto finale come numero (es. 16:9 -> 1.7778)
AR=$(awk -F: '{ if (NF==2) printf "%.6f", $1/$2; else printf "%.6f", $1 }' <<< "$ASPECT")
HEIGHT=$(awk -v w="$WIDTH" -v ar="$AR" 'BEGIN { h=int(w/ar+0.5); if (h%2) h--; print h }')

# Filtro: desqueeze orizzontale -> crop centrato al formato scelto -> ridimensiona
# Il crop rimuove anche gli angoli vignettati del 4:3.
VF="scale=trunc(iw*${SQUEEZE}/2)*2:ih:flags=lanczos,setsar=1,\
crop='min(iw,trunc(ih*${AR}/2)*2)':'min(ih,trunc(iw/${AR}/2)*2)',\
crop=trunc(iw/${ZOOM}/2)*2:trunc(ih/${ZOOM}/2)*2,\
scale=${WIDTH}:${HEIGHT}:flags=lanczos"

shopt -s nullglob nocaseglob
FILES=("$IN_DIR"/*.mp4)
shopt -u nocaseglob
[[ ${#FILES[@]} -gt 0 ]] || { echo "Nessun .MP4 in $IN_DIR"; exit 1; }

for SRC in "${FILES[@]}"; do
  NAME=$(basename "${SRC%.*}")
  FINAL="$OUT_DIR/${NAME}_anamorfico_${WIDTH}x${HEIGHT}.mp4"
  echo "=== $NAME ==="

  if [[ -f "$FINAL" ]]; then
    echo "Gia' fatto, salto."; continue
  fi

  INPUT_FOR_FFMPEG="$SRC"

  if [[ -n "$PRESET" ]]; then
    # Gyroflow legge i dati del giroscopio (GPMF) direttamente dal file originale
    cp -n "$SRC" "$WORK_DIR/"
    "$GYROFLOW" "$WORK_DIR/$(basename "$SRC")" --preset "$PRESET" -f
    STAB=$(ls -t "$WORK_DIR/${NAME}_stabilized".* 2>/dev/null | head -n1 || true)
    if [[ -z "$STAB" ]]; then
      echo "Output di Gyroflow non trovato per $NAME, salto."; continue
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
echo "Fatto. Controlla i risultati prima di cancellare gli originali!"
