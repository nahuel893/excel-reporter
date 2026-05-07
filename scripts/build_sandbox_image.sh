#!/usr/bin/env bash
# scripts/build_sandbox_image.sh — Build the bd-agent-sandbox Docker image.
#
# Usage:
#   bash scripts/build_sandbox_image.sh
#
# Idempotent: running twice is safe (Docker layer cache skips unchanged steps).
# Expected build time: 3-8 min on first run (numpy/matplotlib/pandas layers);
# subsequent runs with unchanged Dockerfile: ~5 s from cache.

set -euo pipefail

IMAGE_TAG="${SANDBOX_IMAGE_TAG:-latest}"
IMAGE_NAME="bd-agent-sandbox:${IMAGE_TAG}"

echo "[build_sandbox_image] Building ${IMAGE_NAME} ..."
echo "[build_sandbox_image] Context: bd_agent/sandbox/  Dockerfile: bd_agent/sandbox/Dockerfile"
echo "[build_sandbox_image] Estimated build time: ~3-8 min (first run) / ~5 s (cached)"

docker build \
    -t "${IMAGE_NAME}" \
    -f bd_agent/sandbox/Dockerfile \
    bd_agent/sandbox/

echo "[build_sandbox_image] Done. Image: ${IMAGE_NAME}"
