#!/usr/bin/env bash
# ============================================================================
# Establish SSH Port-Forwarding Tunnels to GCP (25000) and AWS (35000)
# ============================================================================
set -euo pipefail

echo "=== Spanner Omni Hybrid Multi-Cloud SSH Tunnel Helper ==="
echo "1) GCP Compute Engine Tunnel (127.0.0.1:25000 -> VM 127.0.0.1:15000):"
echo "   gcloud compute ssh \"\${DEMO_PREFIX:-omni-demo}\" --project \"\${GCP_PROJECT}\" --zone \"\${GCP_ZONE:-us-central1-a}\" -- -N -L 127.0.0.1:25000:127.0.0.1:15000 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30"
echo ""
echo "2) AWS EC2 Tunnel (127.0.0.1:35000 -> EC2 127.0.0.1:15000):"
echo "   ssh -i \"\${AWS_SSH_KEY}\" -N -L 127.0.0.1:35000:127.0.0.1:15000 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 ec2-user@\"\${AWS_PUBLIC_IP}\""
