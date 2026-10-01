#!/usr/bin/env bash
# ============================================================================
# Safe & Complete Teardown of Laptop Docker, GCP, and AWS Lab Resources
# Tears down VMs, Disks, Key Pairs, Security Groups/Firewalls, Route Tables,
# Internet Gateways/NATs, Subnets, and VPCs recorded in run/*.env.
# ============================================================================
set -euo pipefail

echo "[*] Stopping local Spanner Omni Docker container (if running)..."
docker stop spanneromni 2>/dev/null || true

if [[ "${REMOVE_LOCAL_VOLUME:-false}" == "true" ]]; then
  echo "[*] Removing local container 'spanneromni' and volume 'omni-retail-data'..."
  docker rm spanneromni 2>/dev/null || true
  docker volume rm omni-retail-data 2>/dev/null || true
fi

# ----------------------------------------------------------------------------
# GCP Cleanup (from run/gcp-resources.env or environment variables)
# ----------------------------------------------------------------------------
if [[ -f "run/gcp-resources.env" ]]; then
  # shellcheck disable=SC1091
  source "run/gcp-resources.env"
fi

if [[ -n "${GCP_PROJECT:-}" && -n "${GCP_ZONE:-}" && -n "${DEMO_PREFIX:-}" ]]; then
  GCP_REGION="${GCP_REGION:-${GCP_ZONE%-*}}"
  GCP_VPC="${GCP_VPC:-${DEMO_PREFIX}-vpc}"
  GCP_SUBNET="${GCP_SUBNET:-${DEMO_PREFIX}-subnet}"
  GCP_ROUTER="${GCP_ROUTER:-${DEMO_PREFIX}-router}"
  GCP_NAT="${GCP_NAT:-${DEMO_PREFIX}-nat}"
  GCP_FW_SSH="${GCP_FW_SSH:-${DEMO_PREFIX}-allow-ssh}"
  GCP_FW_INTERNAL="${GCP_FW_INTERNAL:-${DEMO_PREFIX}-allow-internal}"
  GCP_INSTANCE="${GCP_INSTANCE:-${DEMO_PREFIX}-vm}"

  echo "[*] Cleaning up GCP resources in project ${GCP_PROJECT}..."
  gcloud compute instances delete "${GCP_INSTANCE}" --project "${GCP_PROJECT}" --zone "${GCP_ZONE}" --delete-disks=all --quiet || true
  gcloud compute firewall-rules delete "${GCP_FW_SSH}" --project "${GCP_PROJECT}" --quiet || true
  gcloud compute firewall-rules delete "${GCP_FW_INTERNAL}" --project "${GCP_PROJECT}" --quiet || true
  gcloud compute routers nats delete "${GCP_NAT}" --router="${GCP_ROUTER}" --region="${GCP_REGION}" --project "${GCP_PROJECT}" --quiet || true
  gcloud compute routers delete "${GCP_ROUTER}" --region="${GCP_REGION}" --project "${GCP_PROJECT}" --quiet || true
  gcloud compute networks subnets delete "${GCP_SUBNET}" --region="${GCP_REGION}" --project "${GCP_PROJECT}" --quiet || true
  gcloud compute networks delete "${GCP_VPC}" --project "${GCP_PROJECT}" --quiet || true
  rm -f "run/gcp-resources.env"
  echo "[+] GCP VPC, Subnet, Router/NAT, Firewalls, and VM deleted."
fi

# ----------------------------------------------------------------------------
# AWS Cleanup (from run/aws-resources.env)
# ----------------------------------------------------------------------------
if [[ -f "run/aws-resources.env" ]]; then
  # shellcheck disable=SC1091
  source "run/aws-resources.env"
  echo "[*] Cleaning up AWS resources in ${AWS_REGION}..."

  if [[ -n "${OMNI_INSTANCE:-}" ]]; then
    echo "    - Terminating EC2 instance ${OMNI_INSTANCE}..."
    aws ec2 terminate-instances --region "${AWS_REGION}" --instance-ids "${OMNI_INSTANCE}" >/dev/null || true
    aws ec2 wait instance-terminated --region "${AWS_REGION}" --instance-ids "${OMNI_INSTANCE}" || true
  fi

  if [[ "${OMNI_KEY_CREATED:-false}" == "true" && -n "${AWS_KEY_NAME:-}" ]]; then
    echo "    - Deleting generated EC2 key pair ${AWS_KEY_NAME}..."
    aws ec2 delete-key-pair --region "${AWS_REGION}" --key-name "${AWS_KEY_NAME}" || true
    rm -f "${AWS_SSH_KEY:-}"
  fi

  if [[ -n "${OMNI_SG:-}" ]]; then
    echo "    - Deleting Security Group ${OMNI_SG}..."
    aws ec2 delete-security-group --region "${AWS_REGION}" --group-id "${OMNI_SG}" || true
  fi

  if [[ -n "${OMNI_RTB_ASSOC:-}" ]]; then
    aws ec2 disassociate-route-table --region "${AWS_REGION}" --association-id "${OMNI_RTB_ASSOC}" || true
  fi

  if [[ -n "${OMNI_RTB:-}" ]]; then
    echo "    - Deleting Route Table ${OMNI_RTB}..."
    aws ec2 delete-route-table --region "${AWS_REGION}" --route-table-id "${OMNI_RTB}" || true
  fi

  if [[ -n "${OMNI_IGW:-}" && -n "${OMNI_VPC:-}" ]]; then
    echo "    - Detaching and deleting Internet Gateway ${OMNI_IGW}..."
    aws ec2 detach-internet-gateway --region "${AWS_REGION}" --internet-gateway-id "${OMNI_IGW}" --vpc-id "${OMNI_VPC}" || true
    aws ec2 delete-internet-gateway --region "${AWS_REGION}" --internet-gateway-id "${OMNI_IGW}" || true
  fi

  if [[ -n "${OMNI_SUBNET:-}" ]]; then
    echo "    - Deleting Subnet ${OMNI_SUBNET}..."
    aws ec2 delete-subnet --region "${AWS_REGION}" --subnet-id "${OMNI_SUBNET}" || true
  fi

  if [[ -n "${OMNI_VPC:-}" ]]; then
    echo "    - Deleting VPC ${OMNI_VPC}..."
    aws ec2 delete-vpc --region "${AWS_REGION}" --vpc-id "${OMNI_VPC}" || true
  fi

  rm -f "run/aws-resources.env"
  echo "[+] AWS VPC, Subnet, IGW, Route Table, Security Group, Key Pair, and EC2 instance deleted."
fi
