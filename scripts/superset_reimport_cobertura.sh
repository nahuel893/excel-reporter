#!/usr/bin/env bash
# ============================================================================
# superset_reimport_cobertura.sh
# ----------------------------------------------------------------------------
# Import (or re-import) the Cobertura Zonas Superset bundle via the REST API.
#
# Usage:
#   SUPERSET_URL=https://bi.badie.site \
#   SUPERSET_USER=admin \
#   SUPERSET_PASSWORD='<password>' \
#   SUPERSET_RO_PASSWORD='<password>' \
#     ./scripts/superset_reimport_cobertura.sh
#
# Optional env overrides:
#   BUNDLE_DIR       (default: superset/bundle/graficos-cobertura)
#   TMP_ZIP          (default: /tmp/cobertura_zonas_bundle.zip)
#
# Notes:
#   - This script is NOT meant to run in CI. Superset isn't CI-reachable.
#   - The `passwords` field in the import call is required because
#     `databases/Medallion_Gold.yaml` has the password masked (XXXXXXXXXX).
#   - JWT + CSRF + Referer headers are mandatory for the assets/import/ endpoint.
#   - After import, re-export the bundle from Superset to capture `chartId`
#     assignments and any metadata drift, then commit the export.
# ============================================================================
set -euo pipefail

BUNDLE_DIR="${BUNDLE_DIR:-superset/bundle/graficos-cobertura}"
TMP_ZIP="${TMP_ZIP:-/tmp/cobertura_zonas_bundle.zip}"

: "${SUPERSET_URL:?SUPERSET_URL is required (e.g. https://bi.badie.site)}"
: "${SUPERSET_USER:?SUPERSET_USER is required}"
: "${SUPERSET_PASSWORD:?SUPERSET_PASSWORD is required}"
: "${SUPERSET_RO_PASSWORD:?SUPERSET_RO_PASSWORD is required (password for superset_ro)}"

if [[ ! -d "$BUNDLE_DIR" ]]; then
    echo "ERROR: bundle directory not found: $BUNDLE_DIR" >&2
    exit 1
fi

# Step 1: Zip the bundle (without the parent path)
echo "[1/5] Zipping bundle: $BUNDLE_DIR -> $TMP_ZIP"
rm -f "$TMP_ZIP"
(cd "$(dirname "$BUNDLE_DIR")" && zip -r "$TMP_ZIP" "$(basename "$BUNDLE_DIR")" >/dev/null)

# Step 2: Authenticate to get JWT + CSRF
echo "[2/5] Authenticating against $SUPERSET_URL as $SUPERSET_USER"
COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

LOGIN_RESPONSE=$(curl -sS -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
    -H "Referer: $SUPERSET_URL/" \
    -H "Content-Type: application/json" \
    -X POST "$SUPERSET_URL/api/v1/security/login" \
    -d "{\"username\":\"$SUPERSET_USER\",\"password\":\"$SUPERSET_PASSWORD\",\"provider\":\"db\",\"refresh\":true}")

JWT=$(echo "$LOGIN_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))")
if [[ -z "$JWT" ]]; then
    echo "ERROR: login did not return an access_token" >&2
    echo "Response: $LOGIN_RESPONSE" >&2
    exit 2
fi

CSRF=$(grep -i 'superset_csrftoken' "$COOKIE_JAR" | awk '{print $NF}' | tail -1)
if [[ -z "$CSRF" ]]; then
    echo "ERROR: no CSRF token in cookies" >&2
    exit 3
fi

# Step 3: POST the bundle to the assets import endpoint
echo "[3/5] Importing bundle via /api/v1/assets/import/"
IMPORT_RESPONSE=$(curl -sS -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
    -H "Authorization: Bearer $JWT" \
    -H "X-CSRFToken: $CSRF" \
    -H "Referer: $SUPERSET_URL/" \
    -F "bundle=@$TMP_ZIP" \
    -F "passwords={\"databases/Medallion_Gold.yaml\": \"$SUPERSET_RO_PASSWORD\"}" \
    -X POST "$SUPERSET_URL/api/v1/assets/import/")

echo "$IMPORT_RESPONSE" | python3 -m json.tool || echo "$IMPORT_RESPONSE"

# Step 4: Verify the dashboard was created / updated
echo "[4/5] Verifying dashboard 'cobertura-zonas' is reachable"
DASH_RESPONSE=$(curl -sS -b "$COOKIE_JAR" \
    -H "Authorization: Bearer $JWT" \
    -H "X-CSRFToken: $CSRF" \
    -H "Referer: $SUPERSET_URL/" \
    "$SUPERSET_URL/api/v1/dashboard/cobertura-zonas")

DASH_UUID=$(echo "$DASH_RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin).get('result',{}); print(d.get('uuid',''))")
DASH_ID=$(echo "$DASH_RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin).get('result',{}); print(d.get('id',''))")
echo "  uuid=$DASH_UUID  id=$DASH_ID"

# Step 5: List charts and native filters for verification
echo "[5/5] Listing charts and native filters on the dashboard"
CHARTS=$(curl -sS -b "$COOKIE_JAR" \
    -H "Authorization: Bearer $JWT" \
    -H "X-CSRFToken: $CSRF" \
    -H "Referer: $SUPERSET_URL/" \
    "$SUPERSET_URL/api/v1/dashboard/$DASH_ID/charts")
echo "$CHARTS" | python3 -c "
import json, sys
data = json.load(sys.stdin)
result = data.get('result', [])
print(f'  charts: {len(result)}')
for c in result:
    print(f'    - chartId={c.get(\"id\")} name={c.get(\"slice_name\")!r}')
" || echo "  (could not parse chart listing)"

echo
echo "DONE. If charts/native-filters look correct, re-export the bundle"
echo "from Superset (UI: Manage -> Export) and commit the export."
echo "Empty defaults on Período/Zona/Genérico/Marca are intentional (enableEmptyFilter: true)."
