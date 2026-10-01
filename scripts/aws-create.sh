#!/usr/bin/env bash
# ============================================================================
# Provision Spanner Omni GA on AWS EC2 (m7a.xlarge + AL2023 + /dev/vmclock0)
# Exposes hardware PTP clock (/dev/vmclock0) to the Spanner Omni container.
# ============================================================================
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
: "${AWS_SUBNET_ID:?Set AWS_SUBNET_ID to your public subnet ID}"
: "${AWS_KEY_NAME:?Set AWS_KEY_NAME to your EC2 key pair name}"
: "${MY_IP_CIDR:?Set MY_IP_CIDR to your approved public IPv4/32}"
DEMO_PREFIX="${DEMO_PREFIX:-omni-demo}"
OMNI_VERSION="${OMNI_VERSION:-2026.r4-lts}"

mkdir -p run

VPC_ID=$(aws ec2 describe-subnets --region "${AWS_REGION}" --subnet-ids "${AWS_SUBNET_ID}" \
  --query 'Subnets[0].VpcId' --output text)

AMI_ID=$(aws ssm get-parameter --region "${AWS_REGION}" \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query 'Parameter.Value' --output text)

echo "[*] Creating AWS Security Group (${DEMO_PREFIX}-sg) in VPC ${VPC_ID}..."
OMNI_SG=$(aws ec2 create-security-group --region "${AWS_REGION}" \
  --group-name "${DEMO_PREFIX}-sg-$(date +%s)" \
  --description "Spanner Omni Hybrid Lab SSH" \
  --vpc-id "${VPC_ID}" --query 'GroupId' --output text)

aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" \
  --group-id "${OMNI_SG}" --protocol tcp --port 22 --cidr "${MY_IP_CIDR}"

USER_DATA=$(cat <<EOF
#!/usr/bin/env bash
set -euxo pipefail
dnf update -y
dnf install -y docker util-linux nvme-cli
systemctl enable --now docker

# Ensure Nitro hardware PTP clock /dev/vmclock0 is readable by container
if [ -e /dev/vmclock0 ]; then
  chmod 0644 /dev/vmclock0
  echo 'KERNEL=="vmclock0", MODE="0644"' > /etc/udev/rules.d/99-vmclock.rules
fi

# Format and mount dedicated EBS volume
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
docker run -d --name spanneromni --restart unless-stopped \
  --network host \
  --device /dev/vmclock0:/dev/vmclock0 \
  -v /mnt/omni-data:/spanner \
  us-docker.pkg.dev/spanner-omni/images/spanner-omni:${OMNI_VERSION} \
  start-single-server --base-dir=/spanner
EOF
)

echo "[*] Launching m7a.xlarge EC2 instance (${DEMO_PREFIX}) with encrypted gp3 storage..."
OMNI_INSTANCE=$(aws ec2 run-instances --region "${AWS_REGION}" \
  --image-id "${AMI_ID}" \
  --instance-type m7a.xlarge \
  --key-name "${AWS_KEY_NAME}" \
  --subnet-id "${AWS_SUBNET_ID}" \
  --security-group-ids "${OMNI_SG}" \
  --associate-public-ip-address \
  --block-device-mappings '[
    {"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":30,"VolumeType":"gp3","Encrypted":true}},
    {"DeviceName":"/dev/sdf","Ebs":{"VolumeSize":100,"VolumeType":"gp3","Encrypted":true}}
  ]' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${DEMO_PREFIX}}]" \
  --user-data "${USER_DATA}" \
  --query 'Instances[0].InstanceId' --output text)

cat > run/aws-resources.env <<EOF
export AWS_REGION=${AWS_REGION}
export OMNI_SG=${OMNI_SG}
export OMNI_INSTANCE=${OMNI_INSTANCE}
EOF

echo "[+] AWS EC2 instance ${OMNI_INSTANCE} created. Saved state to run/aws-resources.env."
