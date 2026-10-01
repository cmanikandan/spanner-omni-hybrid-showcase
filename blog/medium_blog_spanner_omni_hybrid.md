# Spanner Omni Everywhere: Building a Hybrid Multi-Cloud Database Mesh Across GCP, AWS, and Laptop Docker — With Live Replication & TrueTime Partition Reconciliation

*How Google Cloud’s Spanner Omni (GA `2026.r4-lts`) breaks the hardware atomic-clock barrier—and how to architect "Write Anywhere, Update Everywhere" with deterministic reconciliation when network connections fail.*

> **Disclaimer**: This article and its companion repository represent a **personal project** built for architectural exploration, multi-cloud testing, and hands-on learning. It is **not** an official Google Cloud publication or supported reference implementation. Always refer to the [Official Google Cloud Spanner Omni Documentation](https://docs.cloud.google.com/spanner-omni/overview) and [Spanner Omni Release Notes](https://docs.cloud.google.com/spanner-omni/release-notes) for the latest product capabilities, system requirements, and licensing terms.

![Spanner Omni Hybrid Multi-Cloud Architecture](./images/hero_spanner_omni_hybrid.jpg)

---

## Introduction: When Globally Consistent SQL Leaves the Datacenter

For over a decade, **Google Cloud Spanner** held a unique place in distributed systems engineering: it delivered **external consistency (strict serializability)** at global scale without sacrificing high availability. Yet there was a catch—Spanner required Google’s proprietary datacenter hardware: rubidium atomic clocks and GPS receivers wired into every rack to bound clock uncertainty ($\epsilon$).

With the General Availability of **Spanner Omni (`2026.r4-lts`)**, Google has decoupled the core Spanner database engine from Google-owned hardware. You can now run the exact same battle-tested Spanner engine—complete with **GoogleSQL**, **PostgreSQL (via PGAdapter)**, **Full-Text Search**, **Vector Similarity Search**, and **ISO GQL Property Graphs**—on:

1. **A developer laptop** running a single Docker container (`127.0.0.1:15000`)
2. **Google Cloud** customer-managed Compute Engine VMs or GKE clusters (for sovereign or air-gapped environments)
3. **Amazon Web Services (AWS)** EC2 instances (`m7a.xlarge` with `/dev/vmclock0`) or EKS clusters
4. **On-premises bare-metal or edge sites**

In this hands-on architectural deep dive, we will build and run a self-contained **Hybrid Multi-Cloud Showcase (`PayMesh + OmniRetail`)** spanning **GCP**, **AWS**, and a **Local Laptop Docker Container**. Most importantly, we will demonstrate two capabilities every enterprise architect asks about:

- **Live Cross-Environment Synchronization**: When a database record is updated in *any* environment (Laptop, GCP, or AWS), how is it immediately reflected in the other environments?
- **Network Disruption & Deterministic Reconciliation (`Recon`)**: When connections between environments are severed—and conflicting transactions occur independently during the outage—how does reconciliation happen without losing money or violating inventory invariants?

---

## 1. The Core Breakthrough: Software-Based TrueTime & Paxos Quorum

How can Spanner Omni guarantee external consistency on an AWS EC2 instance or a local workstation without a rubidium atomic clock?

![Software-Based TrueTime and Paxos Consensus](./images/truetime_paxos_clock_sync.jpg)

### Bounding Clock Uncertainty ($\epsilon$) in Software

In traditional Spanner, TrueTime exposes an API `TT.now()` that returns a time interval $[t_{\text{earliest}}, t_{\text{latest}}]$ where $t_{\text{latest}} - t_{\text{earliest}} = 2\epsilon$. To guarantee that if Transaction $T_2$ starts after Transaction $T_1$ commits ($t_{\text{start}}(T_2) > t_{\text{commit}}(T_1)$), then $T_2$'s assigned commit timestamp is strictly greater than $T_1$'s, the coordinator simply performs a **Commit Wait** of $2\epsilon$.

Spanner Omni replaces specialized rack hardware with a **Software-Based TrueTime daemon**:
- **Primary Time Server + Host Time Clients**: Omni continuously measures network round-trip times and bounds local quartz oscillator drift rate between synchronizations.
- **Hardware Clock Assist on Cloud VMs**:
  - On **AWS EC2 (`m7a.xlarge` with Amazon Linux 2023)**, Omni binds directly to the Nitro hypervisor PTP hardware clock device (`/dev/vmclock0` passed into the container via `--device /dev/vmclock0:/dev/vmclock0`), keeping $\epsilon$ in the hundreds of microseconds.
  - On **Google Compute Engine**, Omni leverages gVNIC precision time synchronization with a `TERMINATE` host-maintenance policy (avoiding uncalibrated live-migration clock jumps).
  - On a **Laptop Docker Container**, Omni uses the host kernel clock for zero-friction inner-loop development.

---

## 2. Spanner Omni Editions: Developer Edition vs. Commercial Edition vs. Managed Cloud Spanner

One of the most practical aspects of Spanner Omni is that it ships with a built-in **Developer Edition** alongside the **Commercial Edition**. Understanding the exact boundaries between these editions is essential when planning development, PoCs, and production rollouts:

| Capability / Licensing Dimension | Spanner Omni **Developer Edition** (Default in Container) | Spanner Omni **Commercial Edition** | **Managed Cloud Spanner** (GCP Service) |
| :--- | :--- | :--- | :--- |
| **Target Use Case** | Local developer inner-loop, CI/CD pipelines, functional PoCs, and architectural demos (non-production) | Mission-critical production workloads on AWS, Azure, On-Premises, Sovereign GCP, or Edge | Cloud-native workloads on GCP wanting zero database ops & Google SLAs |
| **Licensing Model** | **Free** out of the box (optional free perpetual Developer key for extended multi-node dev) | **Annual per-vCPU subscription** (including worker vCPUs) or **paid 90-day PoC license** | Managed consumption pricing (nodes/processing units + storage) |
| **Single-Server ($\le 4$ vCPUs) Behavior** | **Never expires** (unlimited reads & writes) and **includes full Backup & Restore** without any license key | Never expires during active subscription | N/A (Managed continuous service) |
| **Multi-Server or $> 4$ vCPUs Behavior** | **90-day write limit** by default; after 90 days, writes are blocked and the database becomes **read-only** | Unlimited reads & writes across multi-zone and multi-cloud Paxos topologies | Elastic multi-region and regional scale |
| **Perpetual Developer Key Trade-off** | Installing the free perpetual Developer key removes the 90-day write limit for dev/test, **but disables Backup & Restore** | Full **Backup & Restore** enabled across all topologies (GCS, S3, or S3-compatible storage) | Automated Managed Backups, PITR & Export |
| **Stateless ANN Vector Workers** | **Not available** (exact KNN via `COSINE_DISTANCE` works, but dedicated worker nodes on port `15027` are disabled) | **Available** (stateless workers build ANN vector indexes on tables $>1\text{M}$ rows up to **1 Billion vectors**) | Native high-scale vector indexing |
| **Multi-Model SQL, Search & Graph** | GoogleSQL, PostgreSQL (`PGAdapter`), Full-Text Search, and ISO GQL Property Graph | GoogleSQL, PostgreSQL (`PGAdapter`), Full-Text Search, and ISO GQL Property Graph | GoogleSQL, PostgreSQL, Search, Vector, Graph + BigQuery Data Boost |

---

## 3. One Engine, Four Data Models: No External Sync Pipelines

In most enterprise architectures, building an application that needs **ACID financial ledgers**, **full-text search**, **vector similarity recommendations**, and **graph relationship traversal** requires stitching together four separate databases (e.g., Postgres + Elasticsearch + Pinecone + Neo4j) with fragile CDC pipelines.

Spanner Omni executes all four workloads inside a **single ACID storage engine**:

![Spanner Omni Unified Multi-Model Engine](./images/unified_multimodel_engine.jpg)

In our showcase schema ([`schema.sql`](../schema.sql)), we combine:

### A. Physical Table Interleaving (`Customers` $\rightarrow$ `Orders`)
By interleaving `Orders` inside `Customers`, child order rows are physically co-located on the same storage split as their parent customer record—eliminating cross-node network hops during joins:

```sql
CREATE TABLE Customers (
  CustomerId   STRING(64)  NOT NULL,
  Name         STRING(128) NOT NULL,
  Region       STRING(32)  NOT NULL,
  UpdatedSite  STRING(32)  NOT NULL,
  CreatedAt    TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp = true)
) PRIMARY KEY (CustomerId);

CREATE TABLE Orders (
  CustomerId     STRING(64) NOT NULL,
  OrderId        STRING(64) NOT NULL,
  ProductId      STRING(64) NOT NULL,
  Quantity       INT64      NOT NULL,
  UnitPriceCents INT64      NOT NULL,
  Status         STRING(32) NOT NULL,
  OriginSite     STRING(32) NOT NULL,
  CommitTs       TIMESTAMP  NOT NULL OPTIONS (allow_commit_timestamp = true)
) PRIMARY KEY (CustomerId, OrderId),
  INTERLEAVE IN PARENT Customers ON DELETE CASCADE;
```

### B. Full-Text Search & Vector KNN Filtering Over Live Inventory
`Products` enforces a hard database invariant (`CONSTRAINT StockNonnegative CHECK (Stock >= 0)`), maintains an automatic full-text `TOKENLIST` search index, and stores `ARRAY<FLOAT64>` vector embeddings:

```sql
-- Full-Text Search maintained automatically inside ACID transactions
SELECT ProductId, Name, Stock
FROM Products
WHERE SEARCH(SearchTokens, 'waterproof')
ORDER BY Name;

-- Exact Vector Cosine Distance filtered by live transactional stock
SELECT p.ProductId, p.Name, p.Stock,
       COSINE_DISTANCE(p.Embedding, r.Embedding) AS Distance
FROM Products p CROSS JOIN Products r
WHERE r.ProductId = 'p1'
  AND p.ProductId != 'p1'
  AND p.Stock > 0
ORDER BY Distance, p.ProductId
LIMIT 3;
```

### C. ISO GQL Property Graphs (`PayGraph` & `RetailGraph`)
Without any graph ETL job, committed `Transfers` and `Orders` rows are immediately traversable as graph edges using ISO Graph Query Language (GQL):

```sql
-- Find every account reachable within 1 to 3 payment hops
GRAPH PayGraph
MATCH (a:Accounts)-[:Paid]->{1,3}(b:Accounts)
WHERE a.AccountId = @id AND b.AccountId != @id
RETURN DISTINCT b.AccountId AS account_id, b.Owner AS owner;
```

---

## 4. Zero-Pre-Provisioning Deployment Across Laptop Docker, GCP, and AWS

The exact same Python sample application ([`sample-app/app.py`](../sample-app/app.py)) connects to any Spanner Omni endpoint using `InstanceType.OMNI` and `ClientOptions(api_endpoint=...)`:

```python
from google.api_core.client_options import ClientOptions
from google.cloud import spanner
from google.cloud.spanner_v1 import InstanceType

client = spanner.Client(
    client_options=ClientOptions(api_endpoint=ENDPOINT),
    instance_type=InstanceType.OMNI,
    use_plain_text=True,
)
database = client.instance("default").database("omni-hybrid")
```

To make the deployment 100% self-contained, our cloud scripts require **zero pre-created VPCs, Subnets, Security Groups, or SSH Key Pairs**:

1. **Laptop Workstation (`127.0.0.1:15000`)**:
   - `bash scripts/laptop-start.sh` pulls `us-docker.pkg.dev/spanner-omni/images/spanner-omni:2026.r4-lts`, creates a persistent Docker volume, caps the container at 4 CPUs (for non-expiring Developer Edition use), and starts `spanneromni`.
2. **Google Cloud Compute Engine (`127.0.0.1:25000` via SSH Tunnel)**:
   - `bash scripts/gcp-create.sh` automatically enables the Compute Engine API, creates an isolated VPC (`omni-demo-vpc`), Subnet (`10.10.0.0/24`), Cloud Router & Cloud NAT, SSH/Internal Firewall Rules, a `100GB pd-ssd` data disk, and an `e2-standard-4` VM (`--maintenance-policy=TERMINATE`).
3. **AWS EC2 `m7a.xlarge` (`127.0.0.1:35000` via SSH Tunnel)**:
   - `bash scripts/aws-create.sh` automatically creates a dedicated AWS VPC (`10.20.0.0/16`), Internet Gateway, Public Subnet (`10.20.1.0/24`), Route Table, Security Group, a new EC2 SSH Key Pair (`run/omni-demo-key-*.pem`), and an `m7a.xlarge` Amazon Linux 2023 instance with encrypted `gp3` EBS volumes and `/dev/vmclock0` mounted into the container.

---

## 5. When Connections Break: How Cross-Cloud Sync & Reconciliation (`Recon`) Work

Now let’s tackle the central architectural question:

> **How do we ensure that updating the database in any environment updates every other environment—and when connections are disrupted (e.g., an AWS-to-GCP WAN outage or a laptop going offline), how does reconciliation happen when connectivity returns?**

![Disconnected Operations & TrueTime Reconciliation Flow](./images/network_partition_recon_flow.jpg)

There are two complementary architectural patterns supported in this repository:

### Pattern A: Single Distributed Paxos Database Across Clouds (`k8s/values-multi-cloud.yaml`)
When you deploy Spanner Omni across routable private networks spanning **GCP GKE**, **AWS EKS**, and a third failure domain (or witness zone) using `k8s/values-multi-cloud.yaml` and `k8s/spanner-multi-cloud.yaml`, all nodes participate in a **single Paxos quorum**:
- Every write commits synchronously across a majority quorum ($N/2 + 1$).
- If **one environment loses connectivity**, the surviving majority quorum continues serving strong reads and writes with zero data loss.
- When the disconnected environment reconnects, **Paxos log catch-up** automatically streams the missing log entries to bring the lagging replica back to the current TrueTime watermark.

### Pattern B: Disconnected Edge & Multi-Master Hybrid Mesh (`recon_engine.py`)
What if an environment (such as a **laptop on an airplane**, a **disconnected retail store edge container**, or an **isolated cloud region during a full WAN sever**) needs to **continue accepting local writes while completely cut off from the quorum**, and reconcile deterministically once reconnected?

Naive "Last-Write-Wins" (LWW) on row values fails catastrophically in financial and retail systems:
- **The LWW Money-Loss Trap**: Suppose Account `acc-1` starts at `$5,000`. While disconnected, **Laptop** debits `$300` (`Balance -> $4,700`), and **AWS** debits `$200` (`Balance -> $4,800`). If LWW simply overwrites `Balance` with AWS’s `$4,800`, the `$300` debit on the laptop vanishes into thin air!
- **The Split-Brain Inventory Trap**: Suppose Product `p1` (Alpine Waterproof Jacket) has **10 units** in stock. While the network between **GCP** and **AWS** is severed, a customer on **GCP** buys **7 units** at $T_1$ (leaving 3 locally on GCP), and a customer on **AWS** buys **6 units** at $T_2 > T_1$ (leaving 4 locally on AWS). Together, $7 + 6 = 13$ units were sold for only 10 physical items!

### Our 4-Phase TrueTime Reconciliation Engine (`recon_engine.py`)

To solve both problems deterministically, our showcase implements a **Transactional Outbox + TrueTime Anti-Entropy Reconciliation Engine**:

1. **Atomic Transactional Outbox (`SyncMutations`)**:
   Every business transaction (`execute_transfer` or `execute_checkout`) writes both the domain table update (`Accounts`/`Transfers` or `Products`/`Orders`) **and** a `SyncMutations` record inside the **same atomic Spanner transaction** stamped with `COMMIT_TIMESTAMP`.
2. **Real-Time Propagation When Connected**:
   When network links (`laptop <-> gcp`, `gcp <-> aws`, `laptop <-> aws`) are healthy, committed mutations propagate immediately to all reachable peer environments, keeping their cryptographic `SHA-256` state digests identical.
3. **TrueTime-Ordered Replay & Commutative Delta Merging**:
   When a disrupted network link is healed, `reconcile_all()` exchanges `SiteSyncWatermarks`, collects all pending `SyncMutations`, and orders them globally by `(CommitTs, OriginSite, MutationId)`:
   - **Commutative Balance Deltas**: Instead of overwriting `Balance = $4,800`, the engine replays signed deltas (`-$300` from Laptop and `-$200` from AWS), converging all three environments to the exact conservation-safe balance: **`$4,500.00`**.
   - **Invariant-Preserving Stock Compensation**: When replaying the two partitioned orders for `p1` (10 initial stock):
     - The earlier TrueTime order on **GCP** (`ord-partition-gcp-7u`, 7 units at $T_1$) commits across all sites (`Stock: 10 -> 3`).
     - When the later TrueTime order from **AWS** (`ord-partition-aws-6u`, 6 units at $T_2$) is evaluated against the remaining 3 units, enforcing `CONSTRAINT StockNonnegative CHECK (Stock >= 0)` triggers **automated conflict compensation**: `ord-partition-aws-6u` is transitioned to `Status = 'BACKORDERED_RECON_COMPENSATED'`, the over-allocated local stock on AWS is restored so all three environments converge on **`Stock = 3`**, and an immutable audit entry is written to `ReconciliationEvents`.
4. **Cryptographic Convergence Verification (`SHA-256`)**:
   After reconciliation completes, the engine computes a canonical `SHA-256` digest across `Accounts`, `Transfers`, `Products`, and `Orders` on **Laptop**, **GCP**, and **AWS** to verify 100% bit-for-bit convergence.

---

## 6. Seeing It in Action: Self-Contained Sample App & Interactive Control Plane

You can run the self-contained sample app walkthrough across all three environments in under two seconds:

```bash
python3 sample-app/init_db.py --all-sites
python3 sample-app/client_demo.py
```

Or run the CLI simulation report:

```bash
python3 manage.py simulate-recon
```

Or launch the interactive **3-Environment Control Plane Web UI** on `http://127.0.0.1:8080`:

```bash
bash scripts/start-app.sh
```

From the browser dashboard, you can:
1. Click **Buy 1** or **Transfer** inside **Laptop**, **GCP**, or **AWS** and watch all three environments update in real time.
2. Click **LAPTOP ↔ GCP**, **GCP ↔ AWS**, or **LAPTOP ↔ AWS** to sever network links—or click **Isolate Laptop** / **Isolate AWS**.
3. Execute conflicting orders and transfers across the disconnected environments and watch the `SHA-256` state digests diverge and the `Pending Recon` outbox counters climb.
4. Click **Heal Network & Reconcile** (or **Run Guided Partition & Recon Demo**) and inspect the `ReconciliationEvents` audit log as every environment converges back to a single `SHA-256` digest.

---

## 7. Key Takeaways for Cloud Architects

1. **Zero Application Rework Across Form Factors**: Whether your code runs against a local Docker container on your MacBook, a self-managed VM in AWS or GCP, or managed Cloud Spanner, the SQL dialect, transaction semantics, and Python client calls remain identical.
2. **Use Developer Edition Strategically**: Single-server deployments $\le 4$ vCPUs never expire and include full Backup & Restore for free; scale-out production clusters and high-scale ANN vector workers use the Commercial Edition.
3. **Respect Clock & Storage Physics**: On AWS, always use qualified instance types (`m7a.xlarge` with AL2023) that expose `/dev/vmclock0` to bound TrueTime uncertainty. On GCP VMs, use `TERMINATE` on host maintenance and durable SSD block storage.
4. **Design Explicitly for Network Partitions**: Use multi-zone/multi-cloud Paxos quorums when synchronous majority consensus is reachable, and pair transactional outboxes (`SyncMutations`) with commutative delta merging and TrueTime invariant compensation for disconnected edge environments.
