#!/usr/bin/env bash
# ============================================================================
# Provision Spanner Omni GA (2026.r4-lts) on Google Compute Engine
# Zero Pre-Provisioning Required: Automatically creates a new isolated VPC,
# Subnet, Cloud Router/NAT, Firewall Rules, Dedicated pd-ssd Disk, and VM.
# ============================================================================
set -euo pipefail

GCP_PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
: "${GCP_PROJECT:?Set GCP_PROJECT to your target Google Cloud project ID}"

GCP_ZONE="${GCP_ZONE:-us-central1-a}"
GCP_REGION="${GCP_ZONE%-*}"
DEMO_PREFIX="${DEMO_PREFIX:-omni-demo}"
OMNI_VERSION="${OMNI_VERSION:-2026.r4-lts}"

if [[ -z "${MY_IP_CIDR:-}" ]]; then
  DETECTED_IP=$(curl -fsSL https://checkip.amazonaws.com | tr -d '[:space:]')
  MY_IP_CIDR="${DETECTED_IP}/32"
  echo "[*] Auto-detected workstation public IP CIDR: ${MY_IP_CIDR}"
fi

GCP_VPC="${DEMO_PREFIX}-vpc"
GCP_SUBNET="${DEMO_PREFIX}-subnet"
GCP_ROUTER="${DEMO_PREFIX}-router"
GCP_NAT="${DEMO_PREFIX}-nat"
GCP_FW_SSH="${DEMO_PREFIX}-allow-ssh"
GCP_FW_INTERNAL="${DEMO_PREFIX}-allow-internal"
GCP_INSTANCE="${DEMO_PREFIX}-vm"
GCP_DATA_DISK="${DEMO_PREFIX}-data"

mkdir -p run

echo "[*] Ensuring Compute Engine API is enabled in project ${GCP_PROJECT}..."
gcloud services enable compute.googleapis.com --project "${GCP_PROJECT}"

echo "[*] Creating isolated custom VPC (${GCP_VPC})..."
gcloud compute networks create "${GCP_VPC}" \
  --project "${GCP_PROJECT}" \
  --subnet-mode=custom || true

echo "[*] Creating regional subnet (${GCP_SUBNET}: 10.10.0.0/24) in ${GCP_REGION}..."
gcloud compute networks subnets create "${GCP_SUBNET}" \
  --project "${GCP_PROJECT}" \
  --network="${GCP_VPC}" \
  --region="${GCP_REGION}" \
  --range="10.10.0.0/24" || true

echo "[*] Creating Cloud Router (${GCP_ROUTER}) and Cloud NAT (${GCP_NAT}) for reliable outbound registry access..."
gcloud compute routers create "${GCP_ROUTER}" \
  --project "${GCP_PROJECT}" \
  --network="${GCP_VPC}" \
  --region="${GCP_REGION}" || true

gcloud compute routers nats create "${GCP_NAT}" \
  --project "${GCP_PROJECT}" \
  --router="${GCP_ROUTER}" \
  --region="${GCP_REGION}" \
  --nat-all-subnet-ip-ranges \
  --auto-allocate-nat-external-ips || true

echo "[*] Creating Firewall Rules (${GCP_FW_SSH} & ${GCP_FW_INTERNAL})..."
gcloud compute firewall-rules create "${GCP_FW_SSH}" \
  --project "${GCP_PROJECT}" \
  --network="${GCP_VPC}" \
  --allow=tcp:22 \
  --source-ranges="${MY_IP_CIDR},35.235.240.0/20" \
  --description="Allow SSH from workstation and Cloud IAP" || true

gcloud compute firewall-rules create "${GCP_FW_INTERNAL}" \
  --project "${GCP_PROJECT}" \
  --network="${GCP_VPC}" \
  --allow=tcp:15000-15027,tcp:5432,icmp \
  --source-ranges="10.10.0.0/24" \
  --description="Allow internal Spanner Omni Paxos gRPC, Console, and PGAdapter traffic" || true

echo "[*] Provisioning Compute Engine VM (${GCP_INSTANCE}) with dedicated 100GB pd-ssd data disk..."
gcloud compute instances create "${GCP_INSTANCE}" \
  --project "${GCP_PROJECT}" \
  --zone "${GCP_ZONE}" \
  --machine-type=e2-standard-4 \
  --subnet="${GCP_SUBNET}" \
  --maintenance-policy=MIGRATE \
  --no-service-account --no-scopes \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-balanced \
  --create-disk="name=${GCP_DATA_DISK},size=100GB,type=pd-ssd,auto-delete=yes,device-name=omni-data" \
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

for i in {1..30}; do
  if docker exec spanneromni /google/spanner/bin/spanner databases list >/dev/null 2>&1; then
    docker exec spanneromni /google/spanner/bin/spanner databases create omni-hybrid || true
    docker exec spanneromni /google/spanner/bin/spanner databases create paymesh || true
    break
  fi
  sleep 2
done
"

cat > run/gcp-resources.env <<EOF
export GCP_PROJECT=${GCP_PROJECT}
export GCP_ZONE=${GCP_ZONE}
export GCP_REGION=${GCP_REGION}
export DEMO_PREFIX=${DEMO_PREFIX}
export GCP_VPC=${GCP_VPC}
export GCP_SUBNET=${GCP_SUBNET}
export GCP_ROUTER=${GCP_ROUTER}
export GCP_NAT=${GCP_NAT}
export GCP_FW_SSH=${GCP_FW_SSH}
export GCP_FW_INTERNAL=${GCP_FW_INTERNAL}
export GCP_INSTANCE=${GCP_INSTANCE}
export GCP_DATA_DISK=${GCP_DATA_DISK}
EOF

echo "[+] GCP environment provisioned and recorded in run/gcp-resources.env!"
echo "[+] Open SSH tunnel on local port 25000:"
echo "    gcloud compute ssh ${GCP_INSTANCE} --project ${GCP_PROJECT} --zone ${GCP_ZONE} -- -N -L 127.0.0.1:25000:127.0.0.1:15000"
