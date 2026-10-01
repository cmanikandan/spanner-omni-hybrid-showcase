#!/usr/bin/env bash
# ============================================================================
# Launch the Spanner Omni Hybrid Multi-Cloud Control Plane Web Application
# ============================================================================
set -euo pipefail

APP_PORT="${APP_PORT:-8080}"
echo "[*] Starting Spanner Omni Hybrid Multi-Cloud Control Plane on http://127.0.0.1:${APP_PORT}"
exec python3 -m uvicorn app:app --host 127.0.0.1 --port "${APP_PORT}"
