# AGENTS.md — AI Coding Agent & Automation Instructions

> **Disclaimer**: This is a **personal project** built for architectural exploration, hands-on learning, and technical demonstration. It is **not** an official Google Cloud product or supported reference implementation. Always refer to the [Official Google Cloud Spanner Omni Documentation](https://docs.cloud.google.com/spanner-omni/overview) and [Spanner Omni Release Notes](https://docs.cloud.google.com/spanner-omni/release-notes) for the latest product capabilities, licensing terms, and operational guidance.

---

## 1. Purpose of This Repository

This self-contained repository demonstrates **Google Cloud Spanner Omni (`2026.r4-lts`)** running across three environments:
1. **Laptop Workstation (`laptop`)**: Local Docker container (`127.0.0.1:15000`)
2. **Google Cloud (`gcp`)**: Compute Engine VM (`e2-standard-4` + `pd-ssd`) or GKE cluster (`127.0.0.1:25000` via SSH tunnel)
3. **Amazon Web Services (`aws`)**: EC2 `m7a.xlarge` VM (Amazon Linux 2023 + `gp3` EBS + `/dev/vmclock0`) or EKS cluster (`127.0.0.1:35000` via SSH tunnel)

It showcases:
- **Self-Contained Sample Application ([`sample-app/`](./sample-app))**: Portable FastAPI service (`PayMesh` + `OmniRetail`) combining relational ACID transactions, interleaved tables (`Customers -> Orders`), Full-Text Search, Vector Similarity Search (`COSINE_DISTANCE`), and ISO GQL Property Graphs (`PayGraph` & `RetailGraph`).
- **Write Anywhere, Update Everywhere**: Real-time cross-environment replication across connected sites.
- **Network Disruption & TrueTime Reconciliation (`Recon`)**: Transactional outbox queuing (`SyncMutations`) during network partitions, followed by deterministic TrueTime anti-entropy reconciliation (`recon_engine.py`) with commutative balance delta merging, split-brain stock compensation (`BACKORDERED_RECON_COMPENSATED`), and cryptographic `SHA-256` convergence verification.

---

## 2. Quick Verification Commands for Agents

Before or after modifying any Python, SQL, or shell files in this repository, run the following verification suite from the repository root:

```bash
# 1. Run the automated unit & integration test suite (<1 second, zero external dependencies required)
python3 -m unittest discover -s tests -p "test_*.py" -v

# 2. Run the self-contained sample application end-to-end multi-environment demo
python3 sample-app/init_db.py --all-sites
python3 sample-app/client_demo.py

# 3. Run the CLI cross-cloud replication, partition & TrueTime reconciliation report
python3 manage.py simulate-recon
python3 manage.py verify

# 4. Validate shell script syntax across all provisioning and teardown scripts
bash -n scripts/*.sh
```

---

## 3. Repository Layout

- [`README.md`](./README.md) — Comprehensive architectural guide, edition comparison, prerequisites, and step-by-step runbook.
- [`AGENTS.md`](./AGENTS.md) — Instructions and guardrails for AI coding agents.
- [`schema.sql`](./schema.sql) — Canonical GoogleSQL DDL for all tables, full-text indexes, property graphs, and reconciliation outbox tables.
- [`db.py`](./db.py) — Multi-endpoint Spanner Omni client (`InstanceType.OMNI`) and deterministic per-site transactional engine (`SiteNodeEngine`).
- [`recon_engine.py`](./recon_engine.py) — `HybridOmniMesh` coordinator for live cross-cloud replication, network link chaos controls, and TrueTime reconciliation.
- [`app.py`](./app.py) & [`static/index.html`](./static/index.html) — Unified 3-environment Control Plane FastAPI server and browser UI.
- [`sample-app/`](./sample-app) — Self-contained sample application directory:
  - [`sample-app/app.py`](./sample-app/app.py) — Portable FastAPI application (`PayMesh` + `OmniRetail`).
  - [`sample-app/init_db.py`](./sample-app/init_db.py) — Standalone DDL and seed data initializer.
  - [`sample-app/client_demo.py`](./sample-app/client_demo.py) — End-to-end multi-environment test and reconciliation client.
  - [`sample-app/README.md`](./sample-app/README.md) — Sample application documentation.
- [`scripts/`](./scripts) — Zero-pre-provisioning infrastructure automation scripts:
  - [`scripts/laptop-start.sh`](./scripts/laptop-start.sh) — Pulls and starts Spanner Omni in Docker on the laptop.
  - [`scripts/gcp-create.sh`](./scripts/gcp-create.sh) — Automatically creates a new GCP VPC, Subnet, Cloud Router/NAT, Firewall Rules, `pd-ssd` disk, and GCE VM.
  - [`scripts/aws-create.sh`](./scripts/aws-create.sh) — Automatically creates a new AWS VPC, Internet Gateway, Public Subnet, Route Table, Security Group, SSH Key Pair, and `m7a.xlarge` EC2 instance with `/dev/vmclock0`.
  - [`scripts/cleanup.sh`](./scripts/cleanup.sh) — Safely tears down all auto-created resources recorded in `run/gcp-resources.env` and `run/aws-resources.env`.
- [`k8s/`](./k8s) — Helm chart values (`1.0.0`) for 3-zone GKE, 3-zone EKS, and cross-cloud GKE+EKS Paxos deployments.
- [`tests/`](./tests) — Automated unit tests ([`tests/test_recon_and_sync.py`](./tests/test_recon_and_sync.py)) and 12-worker concurrent checkout race test ([`tests/race.py`](./tests/race.py)).
- [`blog/`](./blog) — Accompanying Medium blog post ([`blog/medium_blog_spanner_omni_hybrid.md`](./blog/medium_blog_spanner_omni_hybrid.md)) and Nano Banana generated diagrams.

---

## 4. Spanner Omni Engineering Rules & Guardrails

1. **SDK Connection Pattern**:
   - Always connect to Spanner Omni using `ClientOptions(api_endpoint=ENDPOINT)`, `instance_type=InstanceType.OMNI`, and `client.instance("default").database(DATABASE)`.
   - **Never** set `SPANNER_EMULATOR_HOST` when targeting Spanner Omni.
2. **Developer Edition vs. Commercial Edition Constraints**:
   - **Developer Edition** is free for non-production development, testing, and demos:
     - Single-server deployments with **$\le 4$ vCPUs** do **not** expire and support Backup & Restore without a license key.
     - Multi-server or **$> 4$ vCPU** Developer deployments have a **90-day write limit** (reads remain available after 90 days).
     - Installing a free perpetual Developer license key removes the 90-day write limit for non-production use, but **disables Backup & Restore**.
     - Stateless ANN **Workers** (`workers.enabled=true`, port `15027`) are **not** available in Developer Edition; they require the **Commercial Edition**.
3. **Hardware Timekeeping & VM Maintenance**:
   - **AWS**: Must run on Nitro instances that expose `/dev/vmclock0` (such as `m7a.xlarge` with Amazon Linux 2023) and pass `--device /dev/vmclock0:/dev/vmclock0` to the container.
   - **GCP**: Must set `--maintenance-policy=TERMINATE` on Compute Engine VMs running Spanner Omni to prevent live-migration clock discontinuities.
4. **Zero-Pre-Provisioning Cloud Scripts & Safe Cleanup**:
   - Both [`scripts/gcp-create.sh`](./scripts/gcp-create.sh) and [`scripts/aws-create.sh`](./scripts/aws-create.sh) create their own isolated VPC, Subnet, Router/IGW, Firewall/Security Group, and SSH keys from scratch, recording resource IDs in `run/gcp-resources.env` and `run/aws-resources.env`.
   - Never modify [`scripts/cleanup.sh`](./scripts/cleanup.sh) to delete resources outside those tracked in `run/*.env`.
5. **Secret Hygiene**:
   - Never commit `.pem` SSH keys, Personal Access Tokens (PATs), service account JSON keys, or `run/*.env` files to Git.
