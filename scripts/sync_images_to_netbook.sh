#!/usr/bin/env bash
# Sync report PNG images to netbook, organized by service folder.
#
# Source: data/output/{servicio}/{periodo}/*.png
# Dest:   nahuel@192.168.1.10:~/Imagenes/informes/{servicio}/{periodo}/*.png
#
# Usage:
#   scripts/sync_images_to_netbook.sh            # sync everything (default)
#   scripts/sync_images_to_netbook.sh --today    # only today's date dirs (YYYY-MM-DD + YYYY-MM)
#   scripts/sync_images_to_netbook.sh --dry-run  # preview without copying
#   DEST_HOST=otro.ip scripts/sync_images_to_netbook.sh  # override host
#
# Notes:
# - Solo copia archivos .png (y subcarpetas necesarias). xlsx no se tocan.
# - Si es la primera vez, acepta el host key automáticamente (StrictHostKeyChecking=accept-new).
# - rsync preserva timestamps y solo manda lo que cambió.

set -euo pipefail

DEST_USER="${DEST_USER:-nahuel}"
DEST_HOST="${DEST_HOST:-192.168.1.10}"
DEST_PATH="${DEST_PATH:-~/Imagenes/informes}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$ROOT/data/output"

DRY_FLAG=""
DATE_FILTER=""

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_FLAG="--dry-run" ;;
    --today)
      TODAY_YMD="$(date +%Y-%m-%d)"
      TODAY_YM="$(date +%Y-%m)"
      DATE_FILTER="${TODAY_YMD}|${TODAY_YM}"
      ;;
    -h|--help)
      sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done

if [[ ! -d "$SRC_DIR" ]]; then
  echo "ERROR: $SRC_DIR not found" >&2
  exit 1
fi

echo "→ Source: $SRC_DIR"
echo "→ Dest:   ${DEST_USER}@${DEST_HOST}:${DEST_PATH}"
[[ -n "$DATE_FILTER" ]] && echo "→ Filter: $DATE_FILTER"
[[ -n "$DRY_FLAG"   ]] && echo "→ DRY RUN — no files will be transferred"
echo

# Ensure destination root exists on the netbook
ssh -o StrictHostKeyChecking=accept-new "${DEST_USER}@${DEST_HOST}" \
  "mkdir -p ${DEST_PATH}"

# Build rsync include/exclude rules:
# - descend into all subdirectories
# - include any *.png file
# - exclude everything else
# - if --today filter is on, only descend into dirs matching today's YYYY-MM-DD or YYYY-MM
RSYNC_FILTERS=(
  --include='*/'
  --include='*.png'
  --exclude='*'
)

if [[ -n "$DATE_FILTER" ]]; then
  # Prepend a prune rule that drops period directories not matching today.
  # Period dirs look like YYYY-MM-DD or YYYY-MM at depth 2 inside data/output.
  RSYNC_FILTERS=(
    --include='*/'
    --include='*.png'
    --exclude='2[0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/'   # date-day dirs that won't match
    --exclude='2[0-9][0-9][0-9]-[0-9][0-9]/'              # month dirs that won't match
    --include="$(date +%Y-%m-%d)/"
    --include="$(date +%Y-%m)/"
    --exclude='*'
  )
fi

rsync -avh --prune-empty-dirs $DRY_FLAG \
  "${RSYNC_FILTERS[@]}" \
  -e "ssh -o StrictHostKeyChecking=accept-new" \
  "$SRC_DIR/" \
  "${DEST_USER}@${DEST_HOST}:${DEST_PATH}/"

echo
echo "✓ Sync complete"
