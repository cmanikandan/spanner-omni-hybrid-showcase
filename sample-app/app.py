#!/usr/bin/env python3
"""PayMesh + OmniRetail Sample Application (sample-app/app.py).

One portable FastAPI service that runs unchanged on any Spanner Omni endpoint:
  - Laptop Docker container (OMNI_ENDPOINT=127.0.0.1:15000, OMNI_SITE=laptop)
  - Google Cloud GCE / GKE  (OMNI_ENDPOINT=127.0.0.1:25000, OMNI_SITE=gcp)
  - AWS EC2 m7a / EKS       (OMNI_ENDPOINT=127.0.0.1:35000, OMNI_SITE=aws)

Supports:
  - Atomic payment transfers (/accounts, /transfer)
  - Atomic retail inventory checkout (/products, /checkout)
  - Full-text search (/search?q=...)
  - Vector cosine similarity search (/similar/{product_id})
  - ISO GQL property graph traversal (/network/{account_id}, /graph/retail)
  - Cross-environment replication & network disruption reconciliation (/mesh, /chaos/*, /reconcile)
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from recon_engine import HybridOmniMesh, SITES

ENDPOINT = os.environ.get("OMNI_ENDPOINT", "127.0.0.1:15000")
DATABASE = os.environ.get("OMNI_DATABASE", "paymesh")
SITE = os.environ.get("OMNI_SITE", "laptop").lower()
if SITE not in SITES:
    SITE = "laptop"

mesh = HybridOmniMesh()
mesh.nodes[SITE].endpoint = ENDPOINT
mesh.nodes[SITE].database_name = DATABASE

app = FastAPI(title=f"PayMesh & OmniRetail on Spanner Omni ({SITE.upper()} @ {ENDPOINT})")


@app.get("/whereami")
def whereami(site: str = Query(SITE)):
    s = site.lower()
    if s not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    node = mesh.nodes[s]
    return {
        "site": node.site,
        "endpoint": node.endpoint,
        "database": node.database_name,
        "engine_mode": "LIVE_SPANNER_OMNI_GA" if node.is_live_omni else "SPANNER_OMNI_REPLICA_SIM",
        "state_digest": node.compute_state_digest(),
    }


@app.get("/accounts")
def accounts(site: str = Query(SITE)):
    s = site.lower()
    if s not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    return mesh.nodes[s].snapshot_state()["accounts"]


@app.post("/transfer")
def transfer(
    src: str = Query(..., description="Source AccountId, e.g. acc-1"),
    dst: str = Query(..., description="Destination AccountId, e.g. acc-2"),
    amount: Decimal = Query(..., description="Positive amount to transfer"),
    site: str = Query(SITE, description="Environment executing the write (laptop, gcp, aws)"),
    transfer_id: Optional[str] = Query(None, description="Optional idempotency key"),
):
    """Debit, credit, ledger entry, and outbox mutation commit together or not at all."""
    s = site.lower()
    if s not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    if amount <= 0 or src == dst:
        raise HTTPException(400, "amount must be positive and accounts must differ")
    try:
        res = mesh.submit_transfer(site=s, src=src, dst=dst, amount=amount, transfer_id=transfer_id)
    except ValueError as err:
        raise HTTPException(409, str(err))
    return {
        "transfer_id": res["transfer"]["TransferId"],
        "site": s,
        "idempotent_replay": res["idempotent_replay"],
        "propagation": res["propagation"],
        "site_digests": res.get("topology", {}).get("site_digests", {}),
    }


@app.get("/products")
def products(site: str = Query(SITE)):
    s = site.lower()
    if s not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    return mesh.nodes[s].snapshot_state()["products"]


@app.post("/checkout")
def checkout(
    product_id: str = Query(..., description="ProductId, e.g. p1"),
    quantity: int = Query(1, ge=1, description="Units to buy"),
    customer_id: str = Query("cust-asha", description="CustomerId"),
    site: str = Query(SITE, description="Environment executing the write (laptop, gcp, aws)"),
    order_id: Optional[str] = Query(None, description="Optional idempotency key"),
):
    """Verify stock, decrement inventory, insert interleaved Order, and propagate across connected environments."""
    s = site.lower()
    if s not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    try:
        res = mesh.submit_checkout(
            site=s,
            customer_id=customer_id,
            product_id=product_id,
            quantity=quantity,
            order_id=order_id,
        )
    except ValueError as err:
        raise HTTPException(409, str(err))
    return {
        "order": res["order"],
        "site": s,
        "idempotent_replay": res["idempotent_replay"],
        "propagation": res["propagation"],
        "site_digests": res.get("topology", {}).get("site_digests", {}),
    }


@app.get("/search")
def search(q: str = Query(..., min_length=1), site: str = Query(SITE)):
    """Full-text search over account owners and product catalog."""
    s = site.lower()
    if s not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    return mesh.nodes[s].search_accounts_and_products(q)


@app.get("/similar/{product_id}")
def similar(product_id: str, site: str = Query(SITE)):
    """Vector similarity search (COSINE_DISTANCE) filtered by transactional Stock > 0."""
    s = site.lower()
    if s not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    try:
        return mesh.nodes[s].vector_similar_products(product_id)
    except ValueError as err:
        raise HTTPException(404, str(err))


@app.get("/network/{account_id}")
def network(account_id: str, site: str = Query(SITE)):
    """ISO GQL Graph query: every account reachable within three payments."""
    s = site.lower()
    if s not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    return mesh.nodes[s].query_pay_graph(account_id)


@app.get("/graph/retail")
def retail_graph(site: str = Query(SITE)):
    """ISO GQL Graph query: Customer -> Purchased -> Product relationships."""
    s = site.lower()
    if s not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    return mesh.nodes[s].query_retail_graph()


@app.post("/chaos/disconnect")
def chaos_disconnect(site_a: str = Query(...), site_b: str = Query(...)):
    """Simulate a network link disruption between two environments."""
    return mesh.set_link_state(site_a.lower(), site_b.lower(), False)


@app.post("/chaos/heal")
def chaos_heal():
    """Restore all network links and run TrueTime reconciliation across Laptop, GCP, and AWS."""
    return mesh.heal_all_links(auto_reconcile=True)


@app.get("/mesh")
def mesh_overview():
    """Inspect all three environments, network link states, outbox queues, and SHA-256 digests."""
    return mesh.get_mesh_overview()
