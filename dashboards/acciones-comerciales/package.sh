#!/usr/bin/env bash
# package.sh — Empaqueta dashboard.html + README + data en un zip portable
# para mandar por mail o subir a Drive.

set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f "dashboard.html" ]; then
    echo "ERROR: dashboard.html no existe. Corré primero: python build_dashboard.py" >&2
    exit 1
fi

STAMP=$(date +%Y-%m-%d)
OUT="acciones-comerciales-dashboard-${STAMP}.zip"

# Stage a temp dir so the zip is clean
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE"
cp dashboard.html "$STAGE/"
cp README.md "$STAGE/"
if [ -d "docs" ]; then cp -r docs "$STAGE/"; fi
if [ -f "data/dashboard.json" ]; then cp data/dashboard.json "$STAGE/"; fi

(cd "$STAGE" && zip -qr "$OLDPWD/$OUT" .)
echo "Wrote $OUT ($(du -h "$OUT" | cut -f1))"
