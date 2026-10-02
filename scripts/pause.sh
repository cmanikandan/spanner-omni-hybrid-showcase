#!/usr/bin/env bash
# ============================================================================
# Pause / Stop All Environments (Laptop, GCP, AWS) without destroying data
# Stops compute instances to eliminate active compute billing overnight.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

echo "=== [1/4] Stopping Local SSH Port-Forwarding Tunnels ==="
pkill -f "127.0.0.1:25000:127.0.0.1:15000" 2>/dev/null && echo "[+] Closed GCP SSH tunnel." || echo "[-] No active GCP SSH tunnel found."
pkill -f "127.0.0.1:35000:127.0.0.1:15000" 2>/dev/null && echo "[+] Closed AWS SSH tunnel." || echo "[-] No active AWS SSH tunnel found."

echo ""
echo "=== [2/4] Stopping Local Docker Container ==="
if docker ps --format '{{.Names}}' | grep -qx "spanneromni"; then
  docker stop spanneromni >/dev/null
  echo "[+] Stopped local 'spanneromni' container (data preserved in volume 'omni-retail-data')."
else
  echo "[-] Local 'spanneromni' container is not running."
fi

echo ""
echo "=== [3/4] Stopping GCP Compute Engine VM ==="
if [[ -f "run/gcp-resources.env" ]]; then
  # shellcheck disable=SC1091
  source "run/gcp-resources.env"
  if [[ -n "${GCP_INSTANCE:-}" && -n "${GCP_PROJECT:-}" && -n "${GCP_ZONE:-}" ]]; then
    echo "[*] Stopping GCP VM '${GCP_INSTANCE}' (compute charges halted, pd-ssd disk preserved)..."
    gcloud compute instances stop "${GCP_INSTANCE}" \
      --project "${GCP_PROJECT}" \
      --zone "${GCP_ZONE}" \
      --quiet
    echo "[+] GCP VM '${GCP_INSTANCE}' successfully stopped."
  fi
else
  echo "[-] run/gcp-resources.env not found; skipping GCP."
fi

echo ""
echo "=== [4/4] Stopping AWS EC2 Instance ==="
if [[ -f "run/aws-resources.env" ]]; then
  # shellcheck disable=SC1091
  source "run/aws-resources.env"
  if [[ -n "${OMNI_INSTANCE:-}" && -n "${AWS_REGION:-}" ]]; then
    echo "[*] Stopping AWS EC2 instance '${OMNI_INSTANCE}' (compute charges halted, gp3 EBS preserved)..."
    aws ec2 stop-instances \
      --region "${AWS_REGION}" \
      --instance-ids "${OMNI_INSTANCE}" >/dev/null
    echo "[+] AWS EC2 instance '${OMNI_INSTANCE}' stop initiated."
  fi
else
  echo "[-] run/aws-resources.env not found; skipping AWS."
fi

echo ""
echo "=============================================================================="
echo " All three environments paused! Disks, databases, and schemas are preserved."
echo " To resume tomorrow and reconnect tunnels, run:  bash scripts/resume.sh"
echo "=============================================================================="
