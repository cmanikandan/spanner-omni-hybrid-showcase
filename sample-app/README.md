# PayMesh & OmniRetail Self-Contained Sample Application (`sample-app/`)

This directory contains the self-contained **PayMesh + OmniRetail** sample application designed to test **Google Cloud Spanner Omni (`2026.r4-lts`)** across:

1. **Laptop Workstation (`127.0.0.1:15000`)** — Local Docker container
2. **Google Cloud (`127.0.0.1:25000`)** — Compute Engine VM / GKE cluster
3. **Any External Cloud or On-Premises Datacenter (`127.0.0.1:35000`)** — Works identically on **Microsoft Azure**, **Oracle Cloud (OCI)**, **Amazon Web Services (AWS)**, or **On-Premises Datacenters / Bare-Metal** (sample provisioning script uses AWS EC2/EKS)

---

## Files in `sample-app/`

| File | Description |
| :--- | :--- |
| [`app.py`](./app.py) | Portable FastAPI service exposing `/whereami`, `/accounts`, `/transfer`, `/products`, `/checkout`, `/search`, `/similar/{product_id}`, `/network/{account_id}`, `/graph/retail`, and `/chaos/*` endpoints. |
| [`init_db.py`](./init_db.py) | Schema and seed initializer (`Accounts`, `Transfers`, `Customers`, `Products`, interleaved `Orders`, `SyncMutations`, `PayGraph`, and `RetailGraph`). |
| [`client_demo.py`](./client_demo.py) | Automated end-to-end walkthrough script that tests cross-environment writes, network link disruption, concurrent conflicting transactions, TrueTime reconciliation, and multi-model queries. |
| [`requirements.txt`](./requirements.txt) | Python dependencies for running the sample app standalone. |

---

## Quickstart

### 1. Run the Self-Contained Multi-Environment Sync & Reconciliation Demo
From either the repository root or inside `sample-app/`:

```bash
python3 sample-app/init_db.py --all-sites
python3 sample-app/client_demo.py
```

### 2. Run the Sample App Against Each Environment

```bash
# Terminal 1 — Laptop Docker endpoint (http://127.0.0.1:8080)
OMNI_SITE=laptop OMNI_ENDPOINT=127.0.0.1:15000 uvicorn sample-app.app:app --port 8080

# Terminal 2 — GCP VM endpoint (http://127.0.0.1:8081)
OMNI_SITE=gcp OMNI_ENDPOINT=127.0.0.1:25000 uvicorn sample-app.app:app --port 8081

# Terminal 3 — AWS EC2 endpoint (http://127.0.0.1:8082)
OMNI_SITE=aws OMNI_ENDPOINT=127.0.0.1:35000 uvicorn sample-app.app:app --port 8082
```

### 3. Test API Calls with `curl`

```bash
# Check active site & SHA-256 state digest
curl -s http://127.0.0.1:8080/whereami | jq

# Execute an atomic transfer on Laptop and observe propagation to GCP & AWS
curl -s -X POST "http://127.0.0.1:8080/transfer?src=acc-2&dst=acc-1&amount=125.00&site=laptop" | jq

# Execute an atomic retail checkout on AWS
curl -s -X POST "http://127.0.0.1:8080/checkout?product_id=p1&quantity=1&customer_id=cust-asha&site=aws" | jq

# Full-text search for 'waterproof'
curl -s "http://127.0.0.1:8080/search?q=waterproof" | jq

# Vector similarity search (COSINE_DISTANCE) for product 'p1'
curl -s "http://127.0.0.1:8080/similar/p1" | jq

# ISO GQL Property Graph traversal (1 to 3 payment hops from acc-2)
curl -s "http://127.0.0.1:8080/network/acc-2" | jq
```
