#!/usr/bin/env bash
# ============================================================================
# Provision Spanner Omni GA (2026.r4-lts) on AWS EC2 (m7a.xlarge + AL2023)
# Zero Pre-Provisioning Required: Automatically creates a new isolated VPC,
# Internet Gateway, Public Subnet, Route Table, Security Group, SSH Key Pair,
# and encrypted gp3 EBS volumes with /dev/vmclock0 exposed to Spanner Omni.
# ============================================================================
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ZONE="${AWS_ZONE:-${AWS_REGION}a}"
DEMO_PREFIX="${DEMO_PREFIX:-omni-demo}"
OMNI_VERSION="${OMNI_VERSION:-2026.r4-lts}"
RUN_ID="$(date +%s)"

if [[ -z "${MY_IP_CIDR:-}" ]]; then
  DETECTED_IP=$(curl -fsSL https://checkip.amazonaws.com | tr -d '[:space:]')
  MY_IP_CIDR="${DETECTED_IP}/32"
  echo "[*] Auto-detected workstation public IP CIDR: ${MY_IP_CIDR}"
fi

mkdir -p run

echo "[*] Creating dedicated AWS VPC (10.20.0.0/16) in ${AWS_REGION}..."
OMNI_VPC=$(aws ec2 create-vpc --region "${AWS_REGION}" \
  --cidr-block "10.20.0.0/16" \
  --tag-specifications "ResourceType=vpc,Tags=[{Key=Name,Value=${DEMO_PREFIX}-vpc}]" \
  --query 'Vpc.VpcId' --output text)

aws ec2 modify-vpc-attribute --region "${AWS_REGION}" --vpc-id "${OMNI_VPC}" --enable-dns-support "{\"Value\":true}"
aws ec2 modify-vpc-attribute --region "${AWS_REGION}" --vpc-id "${OMNI_VPC}" --enable-dns-hostnames "{\"Value\":true}"

echo "[*] Creating and attaching Internet Gateway (${DEMO_PREFIX}-igw)..."
OMNI_IGW=$(aws ec2 create-internet-gateway --region "${AWS_REGION}" \
  --tag-specifications "ResourceType=internet-gateway,Tags=[{Key=Name,Value=${DEMO_PREFIX}-igw}]" \
  --query 'InternetGateway.InternetGatewayId' --output text)

aws ec2 attach-internet-gateway --region "${AWS_REGION}" \
  --vpc-id "${OMNI_VPC}" --internet-gateway-id "${OMNI_IGW}"

echo "[*] Creating public subnet (10.20.1.0/24) in ${AWS_ZONE}..."
OMNI_SUBNET=$(aws ec2 create-subnet --region "${AWS_REGION}" \
  --vpc-id "${OMNI_VPC}" \
  --cidr-block "10.20.1.0/24" \
  --availability-zone "${AWS_ZONE}" \
  --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=${DEMO_PREFIX}-subnet}]" \
  --query 'Subnet.SubnetId' --output text)

aws ec2 modify-subnet-attribute --region "${AWS_REGION}" \
  --subnet-id "${OMNI_SUBNET}" --map-public-ip-on-launch

echo "[*] Creating Route Table (${DEMO_PREFIX}-rtb) and default route to Internet Gateway..."
OMNI_RTB=$(aws ec2 create-route-table --region "${AWS_REGION}" \
  --vpc-id "${OMNI_VPC}" \
  --tag-specifications "ResourceType=route-table,Tags=[{Key=Name,Value=${DEMO_PREFIX}-rtb}]" \
  --query 'RouteTable.RouteTableId' --output text)

aws ec2 create-route --region "${AWS_REGION}" \
  --route-table-id "${OMNI_RTB}" \
  --destination-cidr-block "0.0.0.0/0" \
  --gateway-id "${OMNI_IGW}" >/dev/null

OMNI_RTB_ASSOC=$(aws ec2 associate-route-table --region "${AWS_REGION}" \
  --subnet-id "${OMNI_SUBNET}" \
  --route-table-id "${OMNI_RTB}" \
  --query 'AssociationId' --output text)

echo "[*] Creating Security Group (${DEMO_PREFIX}-sg) in VPC ${OMNI_VPC}..."
OMNI_SG=$(aws ec2 create-security-group --region "${AWS_REGION}" \
  --group-name "${DEMO_PREFIX}-sg-${RUN_ID}" \
  --description "Spanner Omni Hybrid Lab Security Group" \
  --vpc-id "${OMNI_VPC}" \
  --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=${DEMO_PREFIX}-sg}]" \
  --query 'GroupId' --output text)

# Allow SSH from workstation IP and internal Spanner Omni ports within the VPC
aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" \
  --group-id "${OMNI_SG}" --protocol tcp --port 22 --cidr "${MY_IP_CIDR}"

aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" \
  --group-id "${OMNI_SG}" --protocol tcp --port 15000-15027 --cidr "10.20.0.0/16"

aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" \
  --group-id "${OMNI_SG}" --protocol tcp --port 5432 --cidr "10.20.0.0/16"

# Create a dedicated SSH key pair automatically if AWS_KEY_NAME is not supplied
OMNI_KEY_CREATED="false"
if [[ -z "${AWS_KEY_NAME:-}" ]]; then
  AWS_KEY_NAME="${DEMO_PREFIX}-key-${RUN_ID}"
  AWS_SSH_KEY="${PWD}/run/${AWS_KEY_NAME}.pem"
  echo "[*] Creating new EC2 SSH Key Pair (${AWS_KEY_NAME}) and saving private key to ${AWS_SSH_KEY}..."
  aws ec2 create-key-pair --region "${AWS_REGION}" \
    --key-name "${AWS_KEY_NAME}" \
    --query 'KeyMaterial' --output text > "${AWS_SSH_KEY}"
  chmod 600 "${AWS_SSH_KEY}"
  OMNI_KEY_CREATED="true"
else
  AWS_SSH_KEY="${AWS_SSH_KEY:-${HOME}/.ssh/${AWS_KEY_NAME}.pem}"
fi

echo "[*] Resolving latest Amazon Linux 2023 x86_64 AMI in ${AWS_REGION}..."
AMI_ID=$(aws ssm get-parameter --region "${AWS_REGION}" \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query 'Parameter.Value' --output text)

USER_DATA=$(cat <<EOF
#!/usr/bin/env bash
set -euxo pipefail
dnf update -y
dnf install -y docker util-linux nvme-cli
systemctl enable --now docker

# Ensure Nitro hardware PTP clock /dev/vmclock0 is readable by the container
if [ -e /dev/vmclock0 ]; then
  chmod 0644 /dev/vmclock0
  echo 'KERNEL=="vmclock0", MODE="0644"' > /etc/udev/rules.d/99-vmclock.rules
fi

# Format and mount dedicated 100GB gp3 EBS volume
DATA_DEV=""
for dev in /dev/nvme1n1 /dev/sdf /dev/xvdf; do
  if [ -b "\$dev" ]; then DATA_DEV="\$dev"; break; fi
done
if [ -n "\$DATA_DEV" ]; then
  if ! blkid "\$DATA_DEV"; then mkfs.ext4 -F "\$DATA_DEV"; fi
  mkdir -p /mnt/omni-data
  mount "\$DATA_DEV" /mnt/omni-data
fi

docker pull us-docker.pkg.dev/spanner-omni/images/spanner-omni:${OMNI_VERSION}
docker rm -f spanneromni || true
docker run -d --name spanneromni --restart unless-stopped \
  --network host \
  --device /dev/vmclock0:/dev/vmclock0 \
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
EOF
)

echo "[*] Launching m7a.xlarge EC2 instance (${DEMO_PREFIX}-ec2) with encrypted gp3 storage..."
OMNI_INSTANCE=$(aws ec2 run-instances --region "${AWS_REGION}" \
  --image-id "${AMI_ID}" \
  --instance-type m7a.xlarge \
  --key-name "${AWS_KEY_NAME}" \
  --subnet-id "${OMNI_SUBNET}" \
  --security-group-ids "${OMNI_SG}" \
  --associate-public-ip-address \
  --block-device-mappings '[
    {"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":30,"VolumeType":"gp3","Encrypted":true,"DeleteOnTermination":true}},
    {"DeviceName":"/dev/sdf","Ebs":{"VolumeSize":100,"VolumeType":"gp3","Encrypted":true,"DeleteOnTermination":true}}
  ]' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${DEMO_PREFIX}-ec2}]" \
  --user-data "${USER_DATA}" \
  --query 'Instances[0].InstanceId' --output text)

echo "[*] Waiting for EC2 instance ${OMNI_INSTANCE} to enter 'running' state..."
aws ec2 wait instance-running --region "${AWS_REGION}" --instance-ids "${OMNI_INSTANCE}"

AWS_PUBLIC_IP=$(aws ec2 describe-instances --region "${AWS_REGION}" \
  --instance-ids "${OMNI_INSTANCE}" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

cat > run/aws-resources.env <<EOF
export AWS_REGION=${AWS_REGION}
export AWS_ZONE=${AWS_ZONE}
export OMNI_VPC=${OMNI_VPC}
export OMNI_IGW=${OMNI_IGW}
export OMNI_SUBNET=${OMNI_SUBNET}
export OMNI_RTB=${OMNI_RTB}
export OMNI_RTB_ASSOC=${OMNI_RTB_ASSOC}
export OMNI_SG=${OMNI_SG}
export AWS_KEY_NAME=${AWS_KEY_NAME}
export OMNI_KEY_CREATED=${OMNI_KEY_CREATED}
export AWS_SSH_KEY=${AWS_SSH_KEY}
export OMNI_INSTANCE=${OMNI_INSTANCE}
export AWS_PUBLIC_IP=${AWS_PUBLIC_IP}
EOF

echo "[+] AWS environment provisioned and recorded in run/aws-resources.env!"
echo "[+] Open SSH tunnel on local port 35000:"
echo "    ssh -i \"${AWS_SSH_KEY}\" -N -L 127.0.0.1:35000:127.0.0.1:15000 ec2-user@${AWS_PUBLIC_IP}"
