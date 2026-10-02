#!/usr/bin/env bash
# ============================================================================
# Launch Spanner Omni GA (2026.r4-lts) on Local Workstation Docker
# ============================================================================
set -euo pipefail

OMNI_VERSION="${OMNI_VERSION:-2026.r4-lts}"
OMNI_IMAGE="${OMNI_IMAGE:-us-docker.pkg.dev/spanner-omni/images/spanner-omni:${OMNI_VERSION}}"
CONTAINER_NAME="${CONTAINER_NAME:-spanneromni}"
VOLUME_NAME="${VOLUME_NAME:-omni-retail-data}"
OMNI_DATABASE="${OMNI_DATABASE:-omni-hybrid}"

echo "[*] Creating persistent Docker volume: ${VOLUME_NAME}"
docker volume create "${VOLUME_NAME}" >/dev/null

if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  echo "[*] Container ${CONTAINER_NAME} already exists; starting..."
  docker start "${CONTAINER_NAME}"
else
  echo "[*] Pulling and launching ${OMNI_IMAGE} on 127.0.0.1:15000 (API) and 127.0.0.1:15026 (Console)..."
  docker run -d \
    --name "${CONTAINER_NAME}" \
    --cpus="4" \
    -p 127.0.0.1:15000:15000 \
    -p 127.0.0.1:15026:15026 \
    -p 127.0.0.1:5432:5432 \
    -v "${VOLUME_NAME}:/spanner" \
    "${OMNI_IMAGE}" \
    start-single-server --base-dir=/spanner --listen-addresses=0.0.0.0
fi

echo "[*] Waiting for Spanner Omni gRPC listener on 127.0.0.1:15000..."
for i in {1..30}; do
  if docker exec "${CONTAINER_NAME}" /google/spanner/bin/spanner databases list >/dev/null 2>&1; then
    echo "[+] Spanner Omni is ready!"
    break
  fi
  sleep 2
done

echo "[*] Ensuring database '${OMNI_DATABASE}' exists..."
docker exec "${CONTAINER_NAME}" /google/spanner/bin/spanner databases create "${OMNI_DATABASE}" 2>/dev/null || true
docker exec "${CONTAINER_NAME}" /google/spanner/bin/spanner databases list
