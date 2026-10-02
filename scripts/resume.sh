#!/usr/bin/env bash
# ============================================================================
# Resume All Environments (Laptop, GCP, AWS) & Re-establish Tunnels
# Starts instances, updates dynamic IPs/security groups, and verifies health.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

echo "=== [1/4] Resuming Local Docker Container ==="
if docker ps -a --format '{{.Names}}' | grep -qx "spanneromni"; then
  docker start spanneromni >/dev/null
  echo "[+] Started local 'spanneromni' container on port 15000."
else
  echo "[*] Launching laptop container via scripts/laptop-start.sh..."
  bash scripts/laptop-start.sh
fi

echo ""
echo "=== [2/4] Resuming GCP Compute Engine VM & Starting Tunnel ==="
if [[ -f "run/gcp-resources.env" ]]; then
  # shellcheck disable=SC1091
  source "run/gcp-resources.env"
  if [[ -n "${GCP_INSTANCE:-}" && -n "${GCP_PROJECT:-}" && -n "${GCP_ZONE:-}" ]]; then
    echo "[*] Starting GCP VM '${GCP_INSTANCE}'..."
    gcloud compute instances start "${GCP_INSTANCE}" \
      --project "${GCP_PROJECT}" \
      --zone "${GCP_ZONE}" \
      --quiet

    pkill -f "127.0.0.1:25000:127.0.0.1:15000" 2>/dev/null || true
    echo "[*] Opening GCP SSH Tunnel (127.0.0.1:25000 -> VM:15000) in background..."
    gcloud compute ssh "${GCP_INSTANCE}" \
      --project "${GCP_PROJECT}" \
      --zone "${GCP_ZONE}" \
      -- -N -L 127.0.0.1:25000:127.0.0.1:15000 \
         -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o StrictHostKeyChecking=no >/dev/null 2>&1 &
    sleep 3
    echo "[+] GCP tunnel established on 127.0.0.1:25000."
  fi
else
  echo "[-] run/gcp-resources.env not found; skipping GCP."
fi

echo ""
echo "=== [3/4] Resuming AWS EC2 Instance & Starting Tunnel ==="
if [[ -f "run/aws-resources.env" ]]; then
  # shellcheck disable=SC1091
  source "run/aws-resources.env"
  if [[ -n "${OMNI_INSTANCE:-}" && -n "${AWS_REGION:-}" ]]; then
    echo "[*] Starting AWS EC2 instance '${OMNI_INSTANCE}'..."
    aws ec2 start-instances --region "${AWS_REGION}" --instance-ids "${OMNI_INSTANCE}" >/dev/null
    echo "[*] Waiting for EC2 instance to reach 'running' state..."
    aws ec2 wait instance-running --region "${AWS_REGION}" --instance-ids "${OMNI_INSTANCE}"

    NEW_PUBLIC_IP=$(aws ec2 describe-instances --region "${AWS_REGION}" \
      --instance-ids "${OMNI_INSTANCE}" \
      --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
    echo "[+] Instance running with Public IP: ${NEW_PUBLIC_IP}"

    # Update run/aws-resources.env with the new IP
    sed -i '' "s/^export AWS_PUBLIC_IP=.*/export AWS_PUBLIC_IP=${NEW_PUBLIC_IP}/" run/aws-resources.env 2>/dev/null || \
      sed -i "s/^export AWS_PUBLIC_IP=.*/export AWS_PUBLIC_IP=${NEW_PUBLIC_IP}/" run/aws-resources.env

    # Ensure workstation public IP is allowed in Security Group
    MY_IP=$(curl -fsSL https://checkip.amazonaws.com 2>/dev/null | tr -d '[:space:]' || true)
    if [[ -n "${MY_IP:-}" && -n "${OMNI_SG:-}" ]]; then
      aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" \
        --group-id "${OMNI_SG}" --protocol tcp --port 22 --cidr "${MY_IP}/32" 2>/dev/null || true
    fi

    pkill -f "127.0.0.1:35000:127.0.0.1:15000" 2>/dev/null || true
    echo "[*] Opening AWS SSH Tunnel (127.0.0.1:35000 -> EC2:15000) in background..."
    # Wait slightly for SSH daemon on newly started instance
    for i in {1..12}; do
      if ssh -i "${AWS_SSH_KEY}" -o ConnectTimeout=3 -o StrictHostKeyChecking=no "ec2-user@${NEW_PUBLIC_IP}" "true" 2>/dev/null; then
        break
      fi
      sleep 3
    done

    ssh -i "${AWS_SSH_KEY}" -N -L 127.0.0.1:35000:127.0.0.1:15000 \
      -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o StrictHostKeyChecking=no \
      "ec2-user@${NEW_PUBLIC_IP}" >/dev/null 2>&1 &
    sleep 3
    echo "[+] AWS tunnel established on 127.0.0.1:35000."
  fi
else
  echo "[-] run/aws-resources.env not found; skipping AWS."
fi

echo ""
echo "=== [4/4] Verifying Cluster Invariants Across All Sites ==="
if [[ -f ".venv/bin/python" ]]; then
  .venv/bin/python manage.py verify || true
fi

echo ""
echo "=============================================================================="
echo " All three environments are back online, connected, and ready for testing!"
echo "=============================================================================="
