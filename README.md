# Spanner Omni Hybrid & Multi-Cloud Showcase (Google Cloud • Any External Cloud / On-Premises Datacenter • Laptop Docker)

> [!IMPORTANT]
> **Personal Project Disclaimer**: This repository is a **personal project** created for architectural exploration, hands-on hybrid/multi-cloud testing, and technical education. It is **not** an official Google Cloud product, nor is it an officially supported Google reference implementation. Refer to the **[Official Google Cloud Spanner Omni GA Launch Announcement](https://cloud.google.com/blog/products/databases/spanner-omni-deploy-anywhere-version-of-spanner-is-now-ga)**, the **[Official Google Cloud Spanner Omni Documentation](https://docs.cloud.google.com/spanner-omni/overview)**, and the **[Spanner Omni Release Notes](https://docs.cloud.google.com/spanner-omni/release-notes)** for authoritative product capabilities, system requirements, and licensing terms.

![Spanner Omni Hybrid Multi-Cloud Architecture](./blog/images/hero_spanner_omni_hybrid.jpg)

---

## Table of Contents

1. [Overview & Deploy-Anywhere Portability](#1-overview--deploy-anywhere-portability)
2. [Spanner Omni Editions & Licensing Deep Dive (Developer vs. Commercial vs. Managed)](#2-spanner-omni-editions--licensing-deep-dive-developer-vs-commercial-vs-managed)
3. [Prerequisites to Create All Three Environments](#3-prerequisites-to-create-all-three-environments)
4. [Repository Structure (100% Self-Contained)](#4-repository-structure-100-self-contained)
5. [Step-by-Step Deployment Guide Across All Three Environments](#5-step-by-step-deployment-guide-across-all-three-environments)
6. [Testing Cross-Environment Sync & Network Disruption Reconciliation (`Recon`)](#6-testing-cross-environment-sync--network-disruption-reconciliation-recon)
7. [Running the Self-Contained Sample Application (`sample-app/`)](#7-running-the-self-contained-sample-application-sample-app)
8. [Extending to Any Kubernetes Cluster or On-Premises Datacenter](#8-extending-to-any-kubernetes-cluster-or-on-premises-datacenter)
9. [Troubleshooting & Safe Teardown](#9-troubleshooting--safe-teardown)
10. [Accompanying Medium Blog & Official References](#10-accompanying-medium-blog--official-references)

---

## 1. Overview & Deploy-Anywhere Portability

With the General Availability of **Google Cloud Spanner Omni (`2026.r4-lts`)**, Google has decoupled the core Spanner database engine from Google’s proprietary datacenter atomic clocks and GPS receivers by introducing **Software-Based TrueTime ($\epsilon$-drift bounding)**.

Spanner Omni is the **deploy-anywhere, self-managed version of Spanner Omni**, giving organizations full operational control to deploy on any external cloud or on-premises infrastructure, while **Cloud Spanner** remains available as a **fully managed**, zero-ops cloud database natively on Google Cloud.

Because Spanner Omni is distributed as a standard OCI container image (`us-docker.pkg.dev/spanner-omni/images/spanner-omni:2026.r4-lts`) and Kubernetes Helm chart (`oci://us-docker.pkg.dev/spanner-omni/charts/spanner-omni`), it enables a **true hybrid and multi-cloud architecture** across any environment:
- **Google Cloud** (Customer-managed Compute Engine VMs or GKE — e.g., for sovereign, air-gapped, regulated, or customer-operated deployments where self-management is preferred over fully managed Cloud Spanner)
- **Any External Public Cloud** — **Microsoft Azure** (Azure VMs / AKS), **Oracle Cloud Infrastructure / OCI** (OCI Compute / OKE), or **Amazon Web Services / AWS** (EC2 / EKS)
- **Private On-Premises Datacenters & Edge Sites** — Bare-metal Linux servers (RHEL 9 / Ubuntu 22.04+), VMware/KVM virtual machines, or on-premises Kubernetes clusters (OpenShift, Anthos/GDC, Rancher, vanilla K8s)
- **Local Developer Workstations** — A single Docker container on macOS or Linux (`127.0.0.1:15000`)

> [!NOTE]
> **Why AWS is used in the third environment’s sample script**: To provide a concrete, runnable 3-environment demonstration (**Laptop Docker** + **Google Cloud** + **External Cloud / On-Prem**), we included an automated AWS provisioning script ([`scripts/aws-create.sh`](./scripts/aws-create.sh)) as the third node (`aws` / port `35000`). However, **there is nothing AWS-specific about the application, schema, or Spanner Omni engine**—you can point that third endpoint (`127.0.0.1:35000`) to a VM or Kubernetes pod running in **Microsoft Azure**, **Oracle Cloud (OCI)**, an **on-premises datacenter**, or a second local container with zero code changes.

### Cross-Platform Mapping Matrix

| Environment Target | Compute / Runtime | Persistent Block Storage | Software TrueTime Clock Source | Sample Endpoint in Repo |
| :--- | :--- | :--- | :--- | :--- |
| **Local Laptop Workstation** | Docker Desktop / Docker Engine (`--cpus="4"`) | Named Docker Volume (`omni-retail-data`) | Host Kernel Clock / NTP | `127.0.0.1:15000` (`laptop`) |
| **Google Cloud (Self-Managed)** | Compute Engine (`e2-standard-4` / `c3-standard-4`) or GKE | SSD Persistent Disk (`pd-ssd` / `premium-rwo`) | gVNIC PTP / Google NTP (`TERMINATE` maintenance) | `127.0.0.1:25000` (`gcp`) |
| **Microsoft Azure** | Azure VM (`Standard_D4s_v5`) or AKS | Azure Managed Premium SSD (`managed-csi-premium`) | Hyper-V PTP (`/dev/ptp_hyperv`) + Chrony NTP | `127.0.0.1:35000` *(interchangeable)* |
| **Oracle Cloud (OCI)** | OCI Compute (`VM.Standard3.Flex` 4 OCPU) or OKE | OCI Block Volume (High Performance `ext4`) | OCI Stratum-1 NTP / PTP (`chronyd`) | `127.0.0.1:35000` *(interchangeable)* |
| **On-Premises Datacenter / Edge** | Bare-Metal Linux (Ubuntu 22.04+ / RHEL 9+) or K8s | Local Enterprise NVMe SSD or SAN (`ext4`) | Local PTP Grandmaster (`ptp4l`) / NTP (`chronyd`) | `127.0.0.1:35000` *(interchangeable)* |
| **Amazon Web Services (Sample Script)** | EC2 (`m7a.xlarge` AL2023) or EKS | EBS `gp3` Encrypted (`ext4` / `aws-gp3`) | Nitro Hardware PTP (`/dev/vmclock0`) | `127.0.0.1:35000` (`aws`) |

### Core Capabilities Demonstrated

1. **True Hybrid and Multi-Cloud Portability & Architectural Synergy**:
   - Run the exact same Spanner Omni container image, schemas, and queries seamlessly across multiple cloud providers, sovereign enclaves, and on-premises datacenters without vendor lock-in.
   - Combine **self-managed Spanner Omni** on external infrastructure with **fully managed Cloud Spanner** on Google Cloud to match diverse compliance, sovereignty, latency, and operational requirements.
2. **Native AI Vector Similarity Search & Multi-Model Engine (Zero-CDC AI Architecture)**:
   - Spanner Omni stores high-dimensional embeddings (`ARRAY<FLOAT64>`) directly in operational tables and executes real-time semantic vector similarity search (`COSINE_DISTANCE`) alongside transactional inventory checks in the **same atomic Spanner Omni transaction**.
   - Eliminates brittle CDC streaming pipelines (Kafka/Debezium) and external vector databases.
   - Combines Relational SQL, Transactional Full-Text Search, and **Graph-Augmented AI (GraphRAG)** using ISO GQL Property Graphs (`PayGraph` & `RetailGraph`) in a single ACID engine.
3. **Self-Contained Sample Application ([`sample-app/`](./sample-app)) & Control Plane ([`app.py`](./app.py))**:
   - Combines **PayMesh** (financial accounts, atomic transfers, full-text search, and 3-hop payment reachability graph `PayGraph`) with **OmniRetail** (customers, physically interleaved orders `Customers -> Orders`, inventory check constraints, vector similarity search `COSINE_DISTANCE`, and purchase graph `RetailGraph`).
4. **Write Anywhere, Update Everywhere (Cross-Environment Replication)**:
   - When a payment transfer or retail checkout is committed in **any** environment (`laptop`, `gcp`, or the external cloud/datacenter node), the mutation is atomically recorded in `SyncMutations` and replicated in real time to all connected peer environments.
5. **Network Disruption & Deterministic Reconciliation (`Recon`)**:
   - Simulate WAN outages or flight-mode disconnections by severing links via the Web UI, REST API, or CLI.
   - Continue writing independently to each disconnected environment while mutations queue in `SyncMutations`.
   - Restore connectivity and execute our **4-Phase TrueTime Anti-Entropy Reconciliation Engine** ([`recon_engine.py`](./recon_engine.py)):
     - **Commutative Delta Merging**: Concurrent financial debits/credits across partitioned sites merge cleanly without Last-Write-Wins (LWW) lost updates.
     - **Split-Brain Stock Compensation**: If concurrent orders across disconnected sites exceed physical stock, TrueTime commit ordering (`CommitTs`) honors the earlier transaction and automatically transitions the later conflicting transaction to `BACKORDERED_RECON_COMPENSATED`, preserving `CONSTRAINT StockNonnegative CHECK (Stock >= 0)`.
     - **Cryptographic State Verification**: Computes canonical `SHA-256` digests across all tables on all three environments to prove 100% state convergence.

---

## 2. Spanner Omni Editions & Licensing Deep Dive (Developer vs. Commercial vs. Managed)

Before deploying Spanner Omni, it is critical to understand the differences between the **Developer Edition**, the **Commercial Edition**, and **Managed Cloud Spanner**:

| Feature / Dimension | Spanner Omni **Developer Edition** (Default in Image) | Spanner Omni **Commercial Edition** | **Managed Cloud Spanner** (GCP Native) |
| :--- | :--- | :--- | :--- |
| **Intended Use** | Non-production, non-commercial development, local CI/CD, functional PoCs, and demos | Mission-critical production workloads on any cloud (Azure, OCI, AWS, Sovereign GCP), On-Premises Datacenters, or Edge | Workloads running on Google Cloud desiring zero database ops & Google SLAs |
| **Cost / Licensing Model** | **Free** (included by default in container image; optional free perpetual Developer key) | **Annual per-vCPU subscription** (including worker vCPUs) or **paid 90-day PoC license** | Pay-as-you-go per node / processing unit + storage + network |
| **Single-Server ($\le 4$ vCPUs) Expiration** | **Never expires** (unlimited reads & writes) and **supports Backup & Restore** without a license key | Never expires while subscription is active | N/A (Managed continuous service) |
| **Multi-Server or $> 4$ vCPUs Expiration** | **90-day write limit** by default (after 90 days, writes stop and database becomes **read-only**) | No 90-day write limit; scales out across multi-zone/multi-cloud/on-prem Paxos quorums | Scales seamlessly to thousands of nodes |
| **Perpetual Developer Key Behavior** | Free key removes the 90-day write limit on larger/multi-server dev clusters, **but disables Backup & Restore** when installed | Full **Backup & Restore** enabled at all cluster sizes (to GCS, S3, Azure Blob/S3-compatible object storage) | Native automated Backups, PITR, and Export/Import |
| **High-Scale ANN Vector Search Workers** | **Not supported** (exact KNN via `COSINE_DISTANCE` works, but stateless worker pods on port `15027` are disabled) | **Supported** (stateless workers build ANN vector indexes on tables $>1\text{M}$ rows up to **1 Billion vectors**) | Supported natively |
| **Core SQL, Search & Graph Engine** | Full GoogleSQL, PostgreSQL (`PGAdapter`), Full-Text Search, and ISO GQL Property Graph | Full GoogleSQL, PostgreSQL (`PGAdapter`), Full-Text Search, and ISO GQL Property Graph | Full GoogleSQL, PostgreSQL, Search, Vector, Graph + BigQuery Data Boost & Geo-Partitioning |
| **TLS / mTLS & Internal RBAC** | Supported (`spanner certificates`, OPAQUE password auth, mTLS, internal database roles) | Supported | Managed Google Cloud IAM & CMEK |

> [!TIP]
> **Why our lab uses 4 vCPUs per single-server node (`--cpus="4"` / `e2-standard-4` / 4-vCPU VM)**: In the **Developer Edition**, a single server with **4 vCPUs or fewer** never expires and retains full **Backup & Restore** capability without needing to install a separate license key.

---

## 3. Prerequisites to Create All Three Environments

You do **not** need to pre-create any VPCs, Subnets, Internet Gateways, Route Tables, Security Groups, Firewall Rules, or SSH Key Pairs in Google Cloud or the external cloud—our provisioning scripts (`scripts/gcp-create.sh` and `scripts/aws-create.sh`) create all networking, security, and compute resources from scratch and record their IDs in `run/*.env` for one-command teardown (`scripts/cleanup.sh`).

### 3.1 Local Workstation (Laptop) Prerequisites

| Requirement | Minimum / Recommended Specification | Verification Command |
| :--- | :--- | :--- |
| **Operating System** | macOS 14.7+ (Apple Silicon `arm64` or Intel `x86_64`) or Linux (Ubuntu 22.04+ / RHEL 9+) | `uname -s -m` |
| **Docker Runtime** | Docker Engine 24+ or Docker Desktop 4.34+ (allocate **$\ge 4$ CPUs** and **8–16 GB RAM** in Docker settings) | `docker version && docker info \| grep -E "CPUs\|Total Memory"` |
| **Python** | Python 3.11 or 3.12+ with `venv` and `pip` | `python3 --version` |
| **Google Cloud CLI** | `gcloud` SDK installed and authenticated | `gcloud version` |
| **External Cloud / SSH Tooling** | `ssh`, `curl`, `tar`, `git` (plus `aws` CLI v2 if using the included AWS sample script, or `az` / `oci` / SSH for Azure, Oracle Cloud, or On-Prem) | `ssh -V && curl --version` |
| **Local TCP Ports Free** | `15000`, `15026`, `5432` (Laptop Omni), `25000` (GCP tunnel), `35000` (External Cloud / On-Prem tunnel), `8080–8082` (Web UI / Sample App) | `lsof -i :15000 -i :25000 -i :35000 -i :8080` |

### 3.2 Google Cloud (GCP) Prerequisites

1. **Active Billed GCP Project**: A sandbox or development project where you have permissions to create networking and compute resources.
2. **Required IAM Roles** on your active `gcloud` identity:
   - `roles/serviceusage.serviceUsageAdmin` (to enable `compute.googleapis.com`)
   - `roles/compute.networkAdmin` (to create the isolated VPC, subnet, Cloud Router, Cloud NAT, and firewall rules)
   - `roles/compute.instanceAdmin.v1` (to create the `e2-standard-4` VM and `100GB pd-ssd` disk)
   - `roles/compute.securityAdmin` (to manage firewall rules)
3. **Regional Quota (`us-central1`)**: At least **4 E2 vCPUs**, **100 GB SSD Persistent Disk (`pd-ssd`)**, and **1 VPC Network**.
4. **Authenticate & Select Project**:
   ```bash
   gcloud auth login
   gcloud config set project YOUR_GCP_PROJECT_ID
   ```

### 3.3 External Cloud / On-Premises Datacenter Prerequisites (Sample Script Uses AWS; Equally Applicable to Azure, OCI, or Datacenter)

1. **If using the included AWS sample script ([`scripts/aws-create.sh`](./scripts/aws-create.sh))**:
   - Active AWS account/sandbox authenticated via `aws sso login` or IAM credentials (`aws sts get-caller-identity`).
   - Permissions to create a VPC, Internet Gateway, Subnet, Route Table, Security Group, Key Pair, `m7a.xlarge` EC2 instance, `gp3` EBS volumes, and `ssm:GetParameter`.
   - Note: AWS Nitro instances (`m7a.xlarge` with Amazon Linux 2023) expose `/dev/vmclock0` for hardware-assisted PTP timekeeping.
2. **If deploying on Microsoft Azure, Oracle Cloud (OCI), or an On-Premises Datacenter**:
   - Provision any 4-vCPU, 16 GB RAM Linux VM or bare-metal host (Ubuntu 22.04+ or RHEL 9+) with a dedicated `100GB+` ext4 SSD volume mounted at `/mnt/omni-data` and Docker Engine 24+ installed.
   - Ensure NTP/PTP time synchronization (`chronyd` or `/dev/ptp*`) is active, run the exact same `docker run` command from [`scripts/laptop-start.sh`](./scripts/laptop-start.sh), and forward local port `35000` to `127.0.0.1:15000` over SSH!

---

## 4. Repository Structure (100% Self-Contained)

```text
spanner-omni-hybrid-showcase/
├── README.md                          # Comprehensive architectural & operational guide
├── AGENTS.md                          # Instructions & guardrails for AI coding agents
├── schema.sql                         # Canonical GoogleSQL DDL (Interleaved tables, Search, Vectors, Graphs, Outbox)
├── db.py                              # Spanner Omni multi-endpoint connection manager & local replica engine
├── recon_engine.py                    # Cross-environment replication & 4-phase TrueTime reconciliation engine
├── app.py                             # Unified 3-Environment Control Plane FastAPI server
├── manage.py                          # CLI for schema init, invariant verification & guided recon simulation
├── init_db.py                         # Root schema initializer convenience wrapper
├── docker-compose.yml                 # Local Docker Compose for Laptop & 3-node local mesh simulation
├── requirements.txt                   # Compatible Python SDK dependencies (google-cloud-spanner>=3.71.0)
├── requirements-ga.txt                # Strict GA SDK floor (google-cloud-spanner>=3.72.0)
├── sample-app/                        # Self-contained PayMesh + OmniRetail sample application
│   ├── README.md                      # Sample app standalone & multi-environment instructions
│   ├── app.py                         # Portable FastAPI sample app (/whereami, /accounts, /transfer, /checkout, /search, /similar, /network)
│   ├── init_db.py                     # Standalone DDL & seed data initializer (--all-sites supported)
│   ├── client_demo.py                 # End-to-end multi-environment test & reconciliation walkthrough script
│   └── requirements.txt               # Sample app dependencies
├── static/
│   └── index.html                     # Interactive 3-Environment Browser Control Plane UI
├── env/
│   ├── laptop.env                     # Laptop Docker profile (127.0.0.1:15000)
│   ├── gcp.env                        # GCP Compute Engine tunnel profile (127.0.0.1:25000)
│   ├── aws.env                        # External Cloud / On-Prem tunnel profile (127.0.0.1:35000)
│   └── mesh.env                       # Unified 3-environment mesh profile
├── scripts/
│   ├── laptop-start.sh                # Pull & launch Spanner Omni 2026.r4-lts in local Docker
│   ├── gcp-create.sh                  # Auto-creates GCP VPC, Subnet, Router/NAT, Firewalls, pd-ssd & GCE VM
│   ├── aws-create.sh                  # Sample External Cloud script: Auto-creates AWS VPC, IGW, Subnet, SG, Key & EC2
│   ├── start-tunnels.sh               # Helper commands for GCP (25000) and External Cloud/On-Prem (35000) SSH tunnels
│   ├── start-app.sh                   # Launch the FastAPI Control Plane web server
│   └── cleanup.sh                     # Safe teardown of all auto-created lab resources
├── k8s/
│   ├── regional-gke.yaml              # 3-zone regional GKE Helm values (Chart 1.0.0)
│   ├── regional-eks.yaml              # 3-zone regional Kubernetes Helm values (EKS / AKS / OKE / On-Prem K8s)
│   ├── values-multi-cloud.yaml        # Cross-cloud / hybrid K8s Helm values for single distributed database
│   └── spanner-multi-cloud.yaml       # Multi-cloud / hybrid Paxos quorum server topology
├── tests/
│   ├── test_recon_and_sync.py         # Automated unit & integration test suite (unittest & pytest compatible)
│   └── race.py                        # 12-worker concurrent checkout & idempotency verification test
└── blog/
    ├── medium_blog_spanner_omni_hybrid.md  # Accompanying Medium blog post
    └── images/                             # Nano Banana generated architectural illustrations
```

---

## 5. Step-by-Step Deployment Guide Across All Three Environments

### Step 5.0: Set Up Your Local Python Environment

```bash
git clone https://github.com/cmanikandan/spanner-omni-hybrid-showcase.git
cd spanner-omni-hybrid-showcase

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Step 5.1: Environment 1 — Laptop Workstation (Docker on `127.0.0.1:15000`)

```bash
bash scripts/laptop-start.sh

source env/laptop.env
python3 manage.py init
python3 manage.py verify
```

### Step 5.2: Environment 2 — Google Cloud Compute Engine (`127.0.0.1:25000`)

`scripts/gcp-create.sh` requires **no pre-existing VPC or firewall rules**. It automatically creates `omni-demo-vpc`, `omni-demo-subnet` (`10.10.0.0/24`), Cloud Router & Cloud NAT, SSH/Internal Firewall Rules, a `100GB pd-ssd` disk, and an `e2-standard-4` VM running Spanner Omni:

```bash
export GCP_PROJECT=$(gcloud config get-value project)
export GCP_ZONE=us-central1-a
export DEMO_PREFIX=omni-demo

bash scripts/gcp-create.sh
```

Open the SSH tunnel on port `25000` and initialize:

```bash
source run/gcp-resources.env
gcloud compute ssh "${GCP_INSTANCE}" \
  --project "${GCP_PROJECT}" --zone "${GCP_ZONE}" -- \
  -N -L 127.0.0.1:25000:127.0.0.1:15000 \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=30
```

```bash
source env/gcp.env
python3 manage.py init
python3 manage.py verify
```

### Step 5.3: Environment 3 — External Cloud or On-Premises Datacenter (`127.0.0.1:35000`)

- **Option A: Using the included AWS auto-provisioning script (`scripts/aws-create.sh`)** — Requires **no pre-existing VPC, Subnet, Security Group, or Key Pair**:
  ```bash
  export AWS_REGION=us-east-1
  export DEMO_PREFIX=omni-demo
  bash scripts/aws-create.sh

  source run/aws-resources.env
  ssh -i "${AWS_SSH_KEY}" -N -L 127.0.0.1:35000:127.0.0.1:15000 ec2-user@"${AWS_PUBLIC_IP}"
  ```
- **Option B: Using Azure, Oracle Cloud (OCI), or an On-Premises Linux Host** — Run the Spanner Omni container on your target host and forward local port `35000` to `127.0.0.1:15000`:
  ```bash
  ssh user@YOUR_AZURE_OCI_OR_DATACENTER_HOST -N -L 127.0.0.1:35000:127.0.0.1:15000
  ```

Then initialize the third environment from your laptop:

```bash
source env/aws.env
python3 manage.py init
python3 manage.py verify
```

---

## 6. Testing Cross-Environment Sync & Network Disruption Reconciliation (`Recon`)

![Disconnected Operations & TrueTime Reconciliation Flow](./blog/images/network_partition_recon_flow.jpg)

### 6.1 Run the Guided 3-Phase CLI Simulation

```bash
python3 manage.py simulate-recon
```

### 6.2 Launch the Interactive 3-Environment Control Plane UI

```bash
bash scripts/start-app.sh
```

Open **`http://127.0.0.1:8080`** in your browser to test live writes, network link disruptions, and TrueTime reconciliation across all three environments.

### 6.3 Visual Walkthrough of Key Scenarios

#### 1. Multi-Cloud Mesh Topology & Software TrueTime Drift Bounding
![Multi-Cloud Mesh Topology](./blog/images/screenshot_01_multi_cloud_topology.png)
*Live dashboard showing three interconnected Spanner Omni environments: Local Laptop Docker (`127.0.0.1:15000`), Google Cloud Compute Engine (`127.0.0.1:25000`), and AWS EC2 (`127.0.0.1:35000`), displaying live latency, TrueTime clock sources (Host kernel, gVNIC PTP, AWS Nitro `/dev/vmclock0`), and 100% cryptographic SHA-256 state convergence.*

#### 2. PayMesh Cross-Cloud Financial Ledger & Atomic Propagation
![PayMesh Financial Ledger](./blog/images/screenshot_02_paymesh_cross_cloud_transfers.png)
*Real-time funds transfer across multi-region accounts (`acc-2` to `acc-1`). Every transaction atomically commits domain ledger tables and a `SyncMutations` record that replicates instantly across clouds.*

#### 3. OmniRetail Unified Multi-Model Engine (Vectors, Interleaving & Check Constraints)
![OmniRetail Vector Search and Catalog](./blog/images/screenshot_03_omniretail_vector_search_catalog.png)
*Product catalog with physical stock check constraints (`CHECK (Stock >= 0)`), exact vector similarity search with embeddings (`COSINE_DISTANCE`), and customer order interleaving.*

#### 4. Chaos Engineering: Simulated WAN Outage & Split-Brain Writes
![Simulated Multi-Cloud Partition](./blog/images/screenshot_04_chaos_network_partition.png)
*Simulating a WAN link disruption between clouds. Each disconnected environment continues accepting local writes independently, entering temporary state divergence (`all_diverged: true`).*

#### 5. 4-Phase TrueTime Anti-Entropy Reconciliation & Convergence
![TrueTime Reconciliation Report](./blog/images/screenshot_05_truetime_reconciliation.png)
*Healing network partitions triggers the TrueTime anti-entropy engine: replaying commutative balance deltas and resolving split-brain stock contention using TrueTime commit timestamps (`CommitTs`), re-converging all 3 sites to 100% matching state.*

#### 6. Built-in Spanner Omni Native Web Console (Port 15026)
![Spanner Omni Native Web Console](./blog/images/screenshot_06_spanner_omni_web_console.png)
*Native Google Spanner Omni web management console running on `127.0.0.1:15026` showing database list (`omni-hybrid`, `paymesh`), operational metrics, and query execution.*

---

## 7. Running the Self-Contained Sample Application (`sample-app/`)

```bash
# 1. Initialize all 3 environments
python3 sample-app/init_db.py --all-sites

# 2. Run the self-contained end-to-end multi-environment client walkthrough
python3 sample-app/client_demo.py

# 3. Run the automated unit & integration test suite
python3 -m unittest discover -s tests -p "test_*.py" -v
```

---

## 8. Extending to Any Kubernetes Cluster or On-Premises Datacenter

The [`k8s/`](./k8s) directory provides Helm configuration values for `oci://us-docker.pkg.dev/spanner-omni/charts/spanner-omni` (version `1.0.0`) that can be adapted to **GKE**, **EKS**, **Azure AKS**, **Oracle OKE**, or **on-premises Kubernetes (OpenShift / Bare-Metal)** simply by setting `storage.data.storageClassName` and matching `topology.kubernetes.io/zone` labels to your cluster's failure domains.

---

## 9. Troubleshooting & Safe Teardown

To stop the local Docker container and delete **all** auto-created cloud resources (VMs, Disks, SSH Keys, Security Groups, Firewalls, Route Tables, Internet Gateways, Cloud NAT/Routers, Subnets, and VPCs recorded in `run/*.env`):

```bash
bash scripts/cleanup.sh
```

---

## 10. Accompanying Medium Blog & Official References

- **Official Google Cloud Launch Blog**:
  - [Spanner Omni: Deploy-Anywhere Version of Spanner is Now GA](https://cloud.google.com/blog/products/databases/spanner-omni-deploy-anywhere-version-of-spanner-is-now-ga)
- **Medium Blog Post**: [`blog/medium_blog_spanner_omni_hybrid.md`](./blog/medium_blog_spanner_omni_hybrid.md)
- **Official Google Cloud Spanner Omni Documentation**:
  - [Spanner Omni Overview](https://docs.cloud.google.com/spanner-omni/overview)
  - [Spanner Omni Editions & Licensing Overview](https://docs.cloud.google.com/spanner-omni/editions-overview)
  - [Spanner Omni System & Platform Requirements](https://docs.cloud.google.com/spanner-omni/system-requirements)
  - [TrueTime & External Consistency in Spanner Omni](https://docs.cloud.google.com/spanner-omni/true-time-external-consistency)
  - [Spanner Omni Release Notes (`2026.r4-lts`)](https://docs.cloud.google.com/spanner-omni/release-notes)
