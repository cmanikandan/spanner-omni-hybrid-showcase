#!/usr/bin/env bash
# ============================================================================
# Provision Spanner Omni GA on Google Compute Engine (Self-Managed VM)
# Uses terminate-on-maintenance policy for Software TrueTime compliance.
# ============================================================================
set -euo pipefail

: "${GCP_PROJECT:?Set GCP_PROJECT to your target Google Cloud project ID}"
GCP_ZONE="${GCP_ZONE:-us-central1-a}"
GCP_REGION="${GCP_ZONE%-*}"
DEMO_PREFIX="${DEMO_PREFIX:-omni-demo}"
MY_IP_CIDR="${MY_IP_CIDR:?Set MY_IP_CIDR to your approved public IPv4/32}"
OMNI_VERSION="${OMNI_VERSION:-2026.r4-lts}"

echo "[*] Creating isolated VPC and subnet (${DEMO_PREFIX}) in ${GCP_REGION}..."
gcloud compute networks create "${DEMO_PREFIX}" \
  --project "${GCP_PROJECT}" --subnet-mode=custom || true

gcloud compute networks subnets create "${DEMO_PREFIX}" \
  --project "${GCP_PROJECT}" --network="${DEMO_PREFIX}" \
  --region="${GCP_REGION}" --range="10.10.0.0/24" || true

echo "[*] Creating SSH-only ingress firewall rule (${DEMO_PREFIX}-ssh) from ${MY_IP_CIDR}..."
gcloud compute firewall-rules create "${DEMO_PREFIX}-ssh" \
  --project "${GCP_PROJECT}" --network="${DEMO_PREFIX}" \
  --allow=tcp:22 --source-ranges="${MY_IP_CIDR}" || true

echo "[*] Provisioning Compute Engine VM (${DEMO_PREFIX}) with dedicated 100GB pd-ssd data disk..."
gcloud compute instances create "${DEMO_PREFIX}" \
  --project "${GCP_PROJECT}" \
  --zone "${GCP_ZONE}" \
  --machine-type=e2-standard-4 \
  --subnet="${DEMO_PREFIX}" \
  --maintenance-policy=TERMINATE \
  --no-service-account --no-scopes \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-balanced \
  --create-disk="name=${DEMO_PREFIX}-data,size=100GB,type=pd-ssd,auto-delete=yes,device-name=omni-data" \
  --metadata=startup-script="#!/usr/bin/env bash
set -euxo pipefail
apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \$(. /etc/os-release && echo \$VERSION_CODENAME) stable\" > /etc/apt/sources.list.d/docker.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io

DATA_DEV=/dev/disk/by-id/google-omni-data
if ! blkid \"\${DATA_DEV}\"; then
  mkfs.ext4 -F \"\${DATA_DEV}\"
fi
mkdir -p /mnt/omni-data
mount \"\${DATA_DEV}\" /mnt/omni-data || true

docker pull us-docker.pkg.dev/spanner-omni/images/spanner-omni:${OMNI_VERSION}
docker rm -f spanneromni || true
docker run -d --name spanneromni --restart unless-stopped \
  --network host \
  -v /mnt/omni-data:/spanner \
  us-docker.pkg.dev/spanner-omni/images/spanner-omni:${OMNI_VERSION} \
  start-single-server --base-dir=/spanner
"

echo "[+] GCP VM '${DEMO_PREFIX}' provisioned. Connect via SSH tunnel on port 25000:"
echo "    gcloud compute ssh ${DEMO_PREFIX} --project ${GCP_PROJECT} --zone ${GCP_ZONE} -- -N -L 127.0.0.1:25000:127.0.0.1:15000"
