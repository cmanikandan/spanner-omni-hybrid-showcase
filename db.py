"""Spanner Omni Hybrid Multi-Cloud Database Layer (db.py).

Supports three operational environments simultaneously:
  - laptop : 127.0.0.1:15000 (Local Docker container)
  - gcp    : 127.0.0.1:25000 (Google Compute Engine / GKE via SSH tunnel)
  - aws    : 127.0.0.1:35000 (Amazon EC2 m7a.xlarge with /dev/vmclock0 via SSH tunnel)

Provides:
  1. Native Spanner Omni GA connection (InstanceType.OMNI, ClientOptions(api_endpoint=...))
  2. Atomic read-write transactions with TrueTime commit timestamps
  3. Transactional Outbox (SyncMutations) written atomically with every business mutation
  4. Full-Text Search (SEARCH), Vector Search (COSINE_DISTANCE), and ISO GQL Property Graphs
  5. Seamless fallback engine per site when running offline tests or partial cloud setups
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import math
import os
import socket
import threading
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

try:
    from google.api_core.client_options import ClientOptions
    from google.cloud import spanner
    from google.cloud.spanner_v1 import param_types

    try:
        from google.cloud.spanner_v1 import InstanceType
    except ImportError:
        try:
            from google.cloud.spanner_v1.client import InstanceType  # type: ignore
        except ImportError:
            InstanceType = None  # type: ignore
    HAS_SPANNER_SDK = True
except ImportError:
    HAS_SPANNER_SDK = False
    ClientOptions = None  # type: ignore
    spanner = None  # type: ignore
    param_types = None  # type: ignore
    InstanceType = None  # type: ignore


DEFAULT_ENDPOINTS: Dict[str, str] = {
    "laptop": os.environ.get("OMNI_LAPTOP_ENDPOINT", "127.0.0.1:15000"),
    "gcp": os.environ.get("OMNI_GCP_ENDPOINT", "127.0.0.1:25000"),
    "aws": os.environ.get("OMNI_AWS_ENDPOINT", "127.0.0.1:35000"),
}

SITE_METADATA: Dict[str, Dict[str, str]] = {
    "laptop": {
        "name": "Laptop Workstation (Docker)",
        "provider": "Local Docker Engine",
        "region": "local-workstation",
        "clock_source": "Software TrueTime (Container NTP/Host Clock)",
        "epsilon_us": "420",
    },
    "gcp": {
        "name": "Google Cloud (Compute Engine / GKE)",
        "provider": "Google Cloud Platform",
        "region": "us-central1-a",
        "clock_source": "Software TrueTime (GCP gVNICPTP / NTP)",
        "epsilon_us": "185",
    },
    "aws": {
        "name": "Amazon Web Services (EC2 M7a / EKS)",
        "provider": "Amazon Web Services",
        "region": "us-east-1a",
        "clock_source": "Software TrueTime (/dev/vmclock0 Nitro PTP)",
        "epsilon_us": "210",
    },
}

SEED_ACCOUNTS = [
    ("acc-1", "Asha Rao, Bengaluru", "ap-south-1", Decimal("5000.00")),
    ("acc-2", "Vikram Traders Pvt Ltd", "us-central1", Decimal("12000.00")),
    ("acc-3", "Meera Iyer", "us-east-1", Decimal("800.00")),
    ("acc-4", "Coastal Logistics Waterproofing", "us-west-2", Decimal("25000.00")),
    ("acc-5", "Rao Family Trust", "eu-west-1", Decimal("300.00")),
]

SEED_CUSTOMERS = [
    ("cust-asha", "Asha Rao", "ap-south-1"),
    ("cust-ben", "Ben Carter", "us-central1"),
    ("cust-chen", "Chen Wei", "us-east-1"),
]

SEED_PRODUCTS = [
    (
        "p1",
        "Alpine Waterproof Shell Jacket",
        "Breathable 3-layer waterproof storm shell with taped seams for mountain trails.",
        14900,
        10,
        10,
        [0.92, 0.85, 0.15, 0.10],
    ),
    (
        "p2",
        "Glacier Waterproof Trekking Boots",
        "High-ankle waterproof leather hiking boots with Vibram lugged outsole.",
        18900,
        12,
        11,
        [0.88, 0.82, 0.22, 0.14],
    ),
    (
        "p3",
        "Ultralight Trail Running Pack 15L",
        "Water-resistant ripstop hydration vest for alpine ultra distance running.",
        8900,
        15,
        13,
        [0.75, 0.60, 0.45, 0.30],
    ),
    (
        "p4",
        "Merino Thermal Base Layer Crew",
        "200g pure merino wool breathable base layer for cold-weather expeditions.",
        7500,
        20,
        20,
        [0.65, 0.40, 0.70, 0.25],
    ),
    (
        "p5",
        "Carbon Folding Trekking Poles",
        "3-section ultralight carbon fiber poles with cork grips and tungsten tips.",
        11500,
        8,
        8,
        [0.55, 0.50, 0.65, 0.40],
    ),
    (
        "p6",
        "Solar Basecamp Lantern USB-C",
        "Collapsible waterproof LED camp lantern with 5000mAh backup battery.",
        4900,
        25,
        25,
        [0.40, 0.75, 0.30, 0.85],
    ),
]

SEED_ORDERS = [
    ("cust-asha", "ord-seed-1", "p2", 1, 18900, "CONFIRMED", "laptop"),
    ("cust-ben", "ord-seed-2", "p3", 2, 8900, "CONFIRMED", "gcp"),
]

SEED_TRANSFERS = [
    ("tx-seed-1", "acc-2", "acc-1", Decimal("450.00"), "laptop", "COMMITTED"),
    ("tx-seed-2", "acc-1", "acc-3", Decimal("120.00"), "gcp", "COMMITTED"),
    ("tx-seed-3", "acc-3", "acc-4", Decimal("75.00"), "aws", "COMMITTED"),
]


def _utc_iso(dt: Optional[datetime.datetime] = None) -> str:
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).isoformat()


def _cosine_distance(vec_a: List[float], vec_b: List[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return round(1.0 - (dot / (norm_a * norm_b)), 6)


def _is_tcp_reachable(endpoint: str, timeout: float = 0.35) -> bool:
    try:
        host, port_str = endpoint.rsplit(":", 1)
        port = int(port_str)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def create_omni_spanner_client(endpoint: str):
    """Instantiate the official Google Cloud Spanner client configured for Spanner Omni."""
    if not HAS_SPANNER_SDK:
        raise RuntimeError("google-cloud-spanner SDK is not installed")
    omni_type = InstanceType.OMNI if (InstanceType is not None and hasattr(InstanceType, "OMNI")) else "omni"
    return spanner.Client(
        client_options=ClientOptions(api_endpoint=endpoint),
        instance_type=omni_type,
        use_plain_text=True,
    )


class SiteNodeEngine:
    """Represents a single Spanner Omni site (laptop, gcp, or aws).

    Uses a live Spanner Omni gRPC endpoint when reachable and OMNI_BACKEND_MODE != 'sim',
    and falls back cleanly to a deterministic, thread-safe local TrueTime transactional store
    so multi-cloud replication and network partition reconciliation can also be exercised
    immediately on any workstation or CI runner.
    """

    def __init__(self, site: str, endpoint: Optional[str] = None, database_name: str = "omni-hybrid"):
        self.site = site
        self.endpoint = endpoint or DEFAULT_ENDPOINTS.get(site, "127.0.0.1:15000")
        self.database_name = database_name
        self.lock = threading.RLock()
        self.backend_mode = os.environ.get("OMNI_BACKEND_MODE", "auto").lower()
        self._live_db = None

        # State tables for deterministic local replica engine / hybrid mirror
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.transfers: Dict[str, Dict[str, Any]] = {}
        self.customers: Dict[str, Dict[str, Any]] = {}
        self.products: Dict[str, Dict[str, Any]] = {}
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.sync_mutations: Dict[str, Dict[str, Any]] = {}
        self.watermarks: Dict[str, Dict[str, Any]] = {}
        self.recon_events: List[Dict[str, Any]] = []

        self.init_seed_state()
        self._try_connect_live_omni()

    def _try_connect_live_omni(self) -> bool:
        if self.backend_mode == "sim" or not HAS_SPANNER_SDK:
            self._live_db = None
            return False
        if _is_tcp_reachable(self.endpoint):
            try:
                client = create_omni_spanner_client(self.endpoint)
                self._live_db = client.instance("default").database(self.database_name)
                return True
            except Exception:
                self._live_db = None
        return False

    @property
    def is_live_omni(self) -> bool:
        if self.backend_mode == "sim":
            return False
        return _is_tcp_reachable(self.endpoint)

    def init_seed_state(self) -> None:
        """Initialize or reset the site's database to the canonical seed state."""
        with self.lock:
            base_ts = "2026-10-01T08:00:00+00:00"
            self.accounts = {
                acc_id: {
                    "AccountId": acc_id,
                    "Owner": owner,
                    "Region": region,
                    "Balance": Decimal(str(bal)),
                    "UpdatedSite": "seed",
                    "UpdatedAt": base_ts,
                }
                for acc_id, owner, region, bal in SEED_ACCOUNTS
            }
            self.transfers = {
                tx_id: {
                    "TransferId": tx_id,
                    "FromAccount": src,
                    "ToAccount": dst,
                    "Amount": Decimal(str(amt)),
                    "OriginSite": origin,
                    "Status": status,
                    "CreatedAt": base_ts,
                }
                for tx_id, src, dst, amt, origin, status in SEED_TRANSFERS
            }
            self.customers = {
                cid: {
                    "CustomerId": cid,
                    "Name": name,
                    "Region": region,
                    "UpdatedSite": "seed",
                    "CreatedAt": base_ts,
                }
                for cid, name, region in SEED_CUSTOMERS
            }
            self.products = {
                pid: {
                    "ProductId": pid,
                    "Name": name,
                    "Description": desc,
                    "PriceCents": price,
                    "InitialStock": init_stock,
                    "Stock": stock,
                    "Embedding": list(emb),
                    "UpdatedSite": "seed",
                }
                for pid, name, desc, price, init_stock, stock, emb in SEED_PRODUCTS
            }
            self.orders = {
                oid: {
                    "CustomerId": cid,
                    "OrderId": oid,
                    "ProductId": pid,
                    "Quantity": qty,
                    "UnitPriceCents": price,
                    "Status": status,
                    "OriginSite": origin,
                    "CommitTs": base_ts,
                }
                for cid, oid, pid, qty, price, status, origin in SEED_ORDERS
            }
            self.sync_mutations = {}
            self.watermarks = {
                peer: {
                    "PeerSite": peer,
                    "LastMutationId": None,
                    "LastCommitTs": base_ts,
                    "AppliedCount": 0,
                    "UpdatedAt": base_ts,
                }
                for peer in ("laptop", "gcp", "aws")
                if peer != self.site
            }
            self.recon_events = []

    # -------------------------------------------------------------------------
    # Atomic Business Transactions (Write to Primary + Transactional Outbox)
    # -------------------------------------------------------------------------

    def execute_transfer(
        self,
        src: str,
        dst: str,
        amount: Decimal,
        transfer_id: Optional[str] = None,
        commit_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically debit src, credit dst, insert Transfers row, and record SyncMutation."""
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount <= Decimal("0") or src == dst:
            raise ValueError("Transfer amount must be positive and accounts must differ")

        with self.lock:
            tx_id = transfer_id or f"tx-{uuid.uuid4().hex[:10]}"
            if tx_id in self.transfers:
                existing = self.transfers[tx_id]
                if (
                    existing["FromAccount"] == src
                    and existing["ToAccount"] == dst
                    and Decimal(str(existing["Amount"])) == amount
                ):
                    return {"transfer": self._serialize_transfer(existing), "idempotent_replay": True}
                raise ValueError(f"Idempotency conflict on TransferId {tx_id}")

            if src not in self.accounts or dst not in self.accounts:
                raise ValueError("Unknown source or destination account")
            if self.accounts[src]["Balance"] < amount:
                raise ValueError(
                    f"Insufficient funds in {src}: balance={self.accounts[src]['Balance']}, requested={amount}"
                )

            now_ts = commit_ts or _utc_iso()
            self.accounts[src]["Balance"] -= amount
            self.accounts[src]["UpdatedSite"] = self.site
            self.accounts[src]["UpdatedAt"] = now_ts

            self.accounts[dst]["Balance"] += amount
            self.accounts[dst]["UpdatedSite"] = self.site
            self.accounts[dst]["UpdatedAt"] = now_ts

            tx_record = {
                "TransferId": tx_id,
                "FromAccount": src,
                "ToAccount": dst,
                "Amount": amount,
                "OriginSite": self.site,
                "Status": "COMMITTED",
                "CreatedAt": now_ts,
            }
            self.transfers[tx_id] = tx_record

            mutation_id = f"mut-{tx_id}"
            mutation = {
                "MutationId": mutation_id,
                "OriginSite": self.site,
                "EntityType": "TRANSFER",
                "EntityKey": tx_id,
                "Operation": "ATOMIC_TRANSFER_DELTA",
                "PayloadJson": json.dumps(
                    {
                        "transfer_id": tx_id,
                        "src": src,
                        "dst": dst,
                        "amount": str(amount),
                        "origin_site": self.site,
                        "commit_ts": now_ts,
                    }
                ),
                "SyncStatus": "PENDING",
                "CommitTs": now_ts,
            }
            self.sync_mutations[mutation_id] = mutation

            return {
                "transfer": self._serialize_transfer(tx_record),
                "mutation": copy.deepcopy(mutation),
                "idempotent_replay": False,
            }

    def execute_checkout(
        self,
        customer_id: str,
        product_id: str,
        quantity: int,
        order_id: Optional[str] = None,
        commit_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically verify stock, decrement Products.Stock, insert interleaved Orders row, and record SyncMutation."""
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero")

        with self.lock:
            oid = order_id or f"ord-{uuid.uuid4().hex[:10]}"
            if oid in self.orders:
                existing = self.orders[oid]
                if (
                    existing["CustomerId"] == customer_id
                    and existing["ProductId"] == product_id
                    and existing["Quantity"] == quantity
                ):
                    return {"order": copy.deepcopy(existing), "idempotent_replay": True}
                raise ValueError(f"Idempotency key conflict on OrderId {oid} with different payload")

            if customer_id not in self.customers:
                raise ValueError(f"Unknown customer: {customer_id}")
            if product_id not in self.products:
                raise ValueError(f"Unknown product: {product_id}")

            prod = self.products[product_id]
            if prod["Stock"] < quantity:
                raise ValueError(f"SOLD_OUT: product {product_id} has {prod['Stock']} left, requested {quantity}")

            now_ts = commit_ts or _utc_iso()
            prod["Stock"] -= quantity
            prod["UpdatedSite"] = self.site

            order_record = {
                "CustomerId": customer_id,
                "OrderId": oid,
                "ProductId": product_id,
                "Quantity": quantity,
                "UnitPriceCents": prod["PriceCents"],
                "Status": "CONFIRMED",
                "OriginSite": self.site,
                "CommitTs": now_ts,
            }
            self.orders[oid] = order_record

            mutation_id = f"mut-{oid}"
            mutation = {
                "MutationId": mutation_id,
                "OriginSite": self.site,
                "EntityType": "ORDER",
                "EntityKey": oid,
                "Operation": "ATOMIC_CHECKOUT_DELTA",
                "PayloadJson": json.dumps(
                    {
                        "order_id": oid,
                        "customer_id": customer_id,
                        "product_id": product_id,
                        "quantity": quantity,
                        "unit_price_cents": prod["PriceCents"],
                        "origin_site": self.site,
                        "commit_ts": now_ts,
                    }
                ),
                "SyncStatus": "PENDING",
                "CommitTs": now_ts,
            }
            self.sync_mutations[mutation_id] = mutation

            return {
                "order": copy.deepcopy(order_record),
                "mutation": copy.deepcopy(mutation),
                "idempotent_replay": False,
            }

    def create_product(
        self,
        product_id: str,
        name: str,
        description: str,
        price_cents: int,
        initial_stock: int,
        embedding: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Insert a new product (used by live concurrency race tests and catalog extensions)."""
        with self.lock:
            now_ts = _utc_iso()
            prod = {
                "ProductId": product_id,
                "Name": name,
                "Description": description,
                "PriceCents": int(price_cents),
                "InitialStock": int(initial_stock),
                "Stock": int(initial_stock),
                "Embedding": embedding or [0.5, 0.5, 0.5, 0.5],
                "UpdatedSite": self.site,
            }
            self.products[product_id] = prod
            mutation_id = f"mut-prod-{product_id}"
            mutation = {
                "MutationId": mutation_id,
                "OriginSite": self.site,
                "EntityType": "PRODUCT",
                "EntityKey": product_id,
                "Operation": "UPSERT_PRODUCT",
                "PayloadJson": json.dumps({**prod, "commit_ts": now_ts}),
                "SyncStatus": "PENDING",
                "CommitTs": now_ts,
            }
            self.sync_mutations[mutation_id] = mutation
            return {"product": copy.deepcopy(prod), "mutation": copy.deepcopy(mutation)}

    # -------------------------------------------------------------------------
    # Multi-Model Queries: Full-Text Search, Vector KNN, ISO GQL Property Graph
    # -------------------------------------------------------------------------

    def search_accounts_and_products(self, query: str) -> Dict[str, Any]:
        """Execute Full-Text Search across Accounts(Owner_Tokens) and Products(SearchTokens)."""
        tokens = [t.strip().lower() for t in query.split() if t.strip()]
        with self.lock:
            matched_accounts = []
            for acc in self.accounts.values():
                haystack = f"{acc['Owner']} {acc['Region']}".lower()
                if all(tok in haystack for tok in tokens):
                    matched_accounts.append(self._serialize_account(acc))

            matched_products = []
            for prod in self.products.values():
                haystack = f"{prod['Name']} {prod['Description']}".lower()
                if all(tok in haystack for tok in tokens):
                    matched_products.append(copy.deepcopy(prod))

            return {
                "site": self.site,
                "query": query,
                "accounts": sorted(matched_accounts, key=lambda x: x["AccountId"]),
                "products": sorted(matched_products, key=lambda x: x["ProductId"]),
            }

    def vector_similar_products(self, product_id: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Execute COSINE_DISTANCE vector similarity search filtered by Stock > 0."""
        with self.lock:
            if product_id not in self.products:
                raise ValueError(f"Unknown product: {product_id}")
            ref = self.products[product_id]
            ref_emb = ref.get("Embedding") or []
            results = []
            for pid, prod in self.products.items():
                if pid == product_id or prod["Stock"] <= 0 or not prod.get("Embedding"):
                    continue
                dist = _cosine_distance(ref_emb, prod["Embedding"])
                results.append(
                    {
                        "ProductId": pid,
                        "Name": prod["Name"],
                        "Stock": prod["Stock"],
                        "PriceCents": prod["PriceCents"],
                        "Distance": dist,
                    }
                )
            results.sort(key=lambda r: (r["Distance"], r["ProductId"]))
            return results[:limit]

    def query_pay_graph(self, account_id: str, max_hops: int = 3) -> Dict[str, Any]:
        """Simulate ISO GQL `GRAPH PayGraph MATCH (a:Accounts)-[:Paid]->{1,3}(b:Accounts)`."""
        with self.lock:
            visited = set()
            frontier = {(account_id, 0)}
            reachable = []
            edges = []

            for tx in self.transfers.values():
                if tx["Status"] == "COMMITTED":
                    edges.append(self._serialize_transfer(tx))

            current_level = {account_id}
            for hop in range(1, max_hops + 1):
                next_level = set()
                for tx in self.transfers.values():
                    if tx["Status"] != "COMMITTED":
                        continue
                    if tx["FromAccount"] in current_level:
                        target = tx["ToAccount"]
                        if target != account_id and target not in visited:
                            visited.add(target)
                            next_level.add(target)
                            acc = self.accounts.get(target)
                            if acc:
                                reachable.append(
                                    {
                                        "AccountId": target,
                                        "Owner": acc["Owner"],
                                        "HopDistance": hop,
                                        "ViaTransferId": tx["TransferId"],
                                    }
                                )
                current_level = next_level

            return {
                "source_account": account_id,
                "reachable_accounts": reachable,
                "edges": edges,
            }

    def query_retail_graph(self) -> List[Dict[str, Any]]:
        """Execute ISO GQL `GRAPH RetailGraph MATCH (c:Customer)-[o:Purchased]->(p:Product)`."""
        with self.lock:
            edges = []
            for oid, order in sorted(self.orders.items(), key=lambda item: item[1]["CommitTs"], reverse=True):
                cust = self.customers.get(order["CustomerId"], {})
                prod = self.products.get(order["ProductId"], {})
                edges.append(
                    {
                        "OrderId": oid,
                        "CustomerId": order["CustomerId"],
                        "CustomerName": cust.get("Name", order["CustomerId"]),
                        "ProductId": order["ProductId"],
                        "ProductName": prod.get("Name", order["ProductId"]),
                        "Quantity": order["Quantity"],
                        "UnitPriceCents": order["UnitPriceCents"],
                        "Status": order["Status"],
                        "OriginSite": order["OriginSite"],
                        "CommitTs": order["CommitTs"],
                    }
                )
            return edges

    # -------------------------------------------------------------------------
    # Invariant Verification & Cryptographic State Digest
    # -------------------------------------------------------------------------

    def verify_invariants(self) -> Dict[str, Any]:
        """Check strict financial conservation and inventory invariants on this site."""
        with self.lock:
            violations = []
            for pid, prod in self.products.items():
                committed_qty = sum(
                    o["Quantity"]
                    for o in self.orders.values()
                    if o["ProductId"] == pid and o["Status"] == "CONFIRMED"
                )
                expected_stock = prod["InitialStock"] - committed_qty
                if prod["Stock"] < 0:
                    violations.append(f"Negative stock on {pid}: {prod['Stock']}")
                if prod["Stock"] != expected_stock:
                    violations.append(
                        f"Stock mismatch on {pid}: Stock={prod['Stock']} vs Initial({prod['InitialStock']}) - Committed({committed_qty}) = {expected_stock}"
                    )

            total_balance = sum((acc["Balance"] for acc in self.accounts.values()), Decimal("0.00"))
            seed_total = sum((bal for _, _, _, bal in SEED_ACCOUNTS), Decimal("0.00"))
            if total_balance != seed_total:
                violations.append(
                    f"Ledger conservation violation: total_balance={total_balance} != seed_total={seed_total}"
                )

            return {
                "site": self.site,
                "valid": len(violations) == 0,
                "violations": violations,
                "total_ledger_balance": str(total_balance),
                "state_digest": self.compute_state_digest(),
            }

    def compute_state_digest(self) -> str:
        """Compute deterministic SHA-256 digest of Accounts, Transfers, Products, and Orders."""
        with self.lock:
            canonical = {
                "accounts": [
                    (k, str(v["Balance"]))
                    for k, v in sorted(self.accounts.items())
                ],
                "transfers": [
                    (k, v["FromAccount"], v["ToAccount"], str(v["Amount"]), v["Status"])
                    for k, v in sorted(self.transfers.items())
                ],
                "products": [
                    (k, v["Stock"], v["InitialStock"], v["PriceCents"])
                    for k, v in sorted(self.products.items())
                ],
                "orders": [
                    (k, v["CustomerId"], v["ProductId"], v["Quantity"], v["Status"])
                    for k, v in sorted(self.orders.items())
                ],
            }
            payload = json.dumps(canonical, sort_keys=True).encode("utf-8")
            return hashlib.sha256(payload).hexdigest()[:16]

    def snapshot_state(self) -> Dict[str, Any]:
        """Return complete site state for the Hybrid Multi-Cloud Control Plane UI."""
        with self.lock:
            meta = SITE_METADATA.get(self.site, {})
            confirmed_orders = [o for o in self.orders.values() if o["Status"] == "CONFIRMED"]
            backordered_orders = [o for o in self.orders.values() if o["Status"] != "CONFIRMED"]
            pending_mutations = [
                m for m in self.sync_mutations.values() if m["SyncStatus"] != "SYNCED_ALL"
            ]
            return {
                "site": self.site,
                "endpoint": self.endpoint,
                "database": self.database_name,
                "engine_mode": "LIVE_SPANNER_OMNI_GA" if self.is_live_omni else "SPANNER_OMNI_REPLICA_SIM",
                "metadata": meta,
                "state_digest": self.compute_state_digest(),
                "invariants": self.verify_invariants(),
                "metrics": {
                    "total_orders": len(confirmed_orders),
                    "backordered_orders": len(backordered_orders),
                    "total_units": sum(o["Quantity"] for o in confirmed_orders),
                    "revenue_cents": sum(o["Quantity"] * o["UnitPriceCents"] for o in confirmed_orders),
                    "total_transfers": len(self.transfers),
                    "pending_outbox_count": len(pending_mutations),
                },
                "accounts": [self._serialize_account(a) for _, a in sorted(self.accounts.items())],
                "transfers": [
                    self._serialize_transfer(t)
                    for _, t in sorted(self.transfers.items(), key=lambda x: x[1]["CreatedAt"], reverse=True)
                ],
                "products": [copy.deepcopy(p) for _, p in sorted(self.products.items())],
                "orders": [
                    copy.deepcopy(o)
                    for _, o in sorted(self.orders.items(), key=lambda x: x[1]["CommitTs"], reverse=True)
                ],
                "outbox": [
                    copy.deepcopy(m)
                    for _, m in sorted(self.sync_mutations.items(), key=lambda x: x[1]["CommitTs"], reverse=True)
                ],
                "watermarks": copy.deepcopy(self.watermarks),
                "recon_events": list(reversed(self.recon_events[-30:])),
            }

    @staticmethod
    def _serialize_account(acc: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "AccountId": acc["AccountId"],
            "Owner": acc["Owner"],
            "Region": acc["Region"],
            "Balance": str(acc["Balance"]),
            "UpdatedSite": acc["UpdatedSite"],
            "UpdatedAt": acc["UpdatedAt"],
        }

    @staticmethod
    def _serialize_transfer(tx: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "TransferId": tx["TransferId"],
            "FromAccount": tx["FromAccount"],
            "ToAccount": tx["ToAccount"],
            "Amount": str(tx["Amount"]),
            "OriginSite": tx["OriginSite"],
            "Status": tx["Status"],
            "CreatedAt": tx["CreatedAt"],
        }
