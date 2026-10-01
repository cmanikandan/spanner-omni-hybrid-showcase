#!/usr/bin/env bash
# ============================================================================
# Safe Cleanup Helper for Laptop Docker, GCP Compute Engine, and AWS EC2 Labs
# ============================================================================
set -euo pipefail

echo "[*] Stopping local Spanner Omni Docker container (if running)..."
docker stop spanneromni 2>/dev/null || true

if [[ "${REMOVE_LOCAL_VOLUME:-false}" == "true" ]]; then
  docker rm spanneromni 2>/dev/null || true
  docker volume rm omni-retail-data 2>/dev/null || true
fi

if [[ -n "${GCP_PROJECT:-}" && -n "${GCP_ZONE:-}" && -n "${DEMO_PREFIX:-}" ]]; then
  echo "[*] Cleaning up GCP lab resources (${DEMO_PREFIX}) in ${GCP_PROJECT}..."
  gcloud compute instances delete "${DEMO_PREFIX}" --project "${GCP_PROJECT}" --zone "${GCP_ZONE}" --quiet || true
  gcloud compute firewall-rules delete "${DEMO_PREFIX}-ssh" --project "${GCP_PROJECT}" --quiet || true
  gcloud compute networks subnets delete "${DEMO_PREFIX}" --region "${GCP_ZONE%-*}" --project "${GCP_PROJECT}" --quiet || true
  gcloud compute networks delete "${DEMO_PREFIX}" --project "${GCP_PROJECT}" --quiet || true
fi

if [[ -f "run/aws-resources.env" ]]; then
  source run/aws-resources.env
  echo "[*] Terminating AWS EC2 instance ${OMNI_INSTANCE} and security group ${OMNI_SG}..."
  aws ec2 terminate-instances --region "${AWS_REGION}" --instance-ids "${OMNI_INSTANCE}" || true
  aws ec2 wait instance-terminated --region "${AWS_REGION}" --instance-ids "${OMNI_INSTANCE}" || true
  aws ec2 delete-security-group --region "${AWS_REGION}" --group-id "${OMNI_SG}" || true
fi
