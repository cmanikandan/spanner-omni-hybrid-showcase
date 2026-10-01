"""Spanner Omni Hybrid Multi-Cloud Showcase — FastAPI Application & Control Plane (app.py).

Exposes:
  1. Single-site portable endpoints (/whereami, /accounts, /transfer, /search, /network/{account_id})
  2. Multi-Cloud Mesh Control Plane endpoints (/api/mesh, /api/site/{site}/transfer, /api/site/{site}/checkout)
  3. Network Disruption & Reconciliation endpoints (/api/chaos/link, /api/chaos/isolate/{site}, /api/chaos/heal, /api/reconcile)
  4. Multi-Model query endpoints (Full-Text Search, Vector KNN Similarity, ISO GQL Property Graphs)
  5. Guided Partition & Reconciliation Demo endpoint (/api/demo/guided-recon)
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from recon_engine import HybridOmniMesh, SITES

DEFAULT_SITE = os.environ.get("OMNI_SITE", os.environ.get("DEMO_ENV", "laptop")).lower()
if DEFAULT_SITE not in SITES:
    DEFAULT_SITE = "laptop"

mesh = HybridOmniMesh()
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Spanner Omni Hybrid Multi-Cloud Showcase (Laptop • GCP • AWS)",
    version="2026.r4-lts",
    description=(
        "Demonstrates Google Cloud Spanner Omni across Local Docker, GCP Compute Engine/GKE, "
        "and AWS EC2/EKS with real-time cross-environment replication and deterministic "
        "TrueTime network-partition reconciliation."
    ),
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class TransferRequest(BaseModel):
    src: str = Field(..., description="Source AccountId (e.g. acc-1)")
    dst: str = Field(..., description="Destination AccountId (e.g. acc-2)")
    amount: Decimal = Field(..., description="Positive transfer amount")
    transfer_id: Optional[str] = Field(None, description="Optional idempotency key")


class CheckoutRequest(BaseModel):
    customer_id: str = Field("cust-asha", description="CustomerId (e.g. cust-asha, cust-ben, cust-chen)")
    product_id: str = Field(..., description="ProductId (e.g. p1..p6)")
    quantity: int = Field(1, ge=1, description="Units to purchase")
    order_id: Optional[str] = Field(None, description="Optional idempotency key for safe retries")


class CreateProductRequest(BaseModel):
    product_id: str
    name: str
    description: str = "Automated concurrency race test product"
    price_cents: int = 9900
    initial_stock: int = 10


class LinkToggleRequest(BaseModel):
    site_a: str
    site_b: str
    connected: bool


# ---------------------------------------------------------------------------
# Browser UI & Portable Single-Site Endpoints
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>Spanner Omni Hybrid Multi-Cloud Control Plane</h1>")


@app.get("/whereami")
def whereami(site: str = Query(DEFAULT_SITE)):
    site = site.lower()
    if site not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'. Valid sites: {SITES}")
    node = mesh.nodes[site]
    return {
        "site": node.site,
        "endpoint": node.endpoint,
        "database": node.database_name,
        "engine_mode": "LIVE_SPANNER_OMNI_GA" if node.is_live_omni else "SPANNER_OMNI_REPLICA_SIM",
        "state_digest": node.compute_state_digest(),
    }


@app.get("/accounts")
def accounts(site: str = Query(DEFAULT_SITE)):
    site = site.lower()
    if site not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    snap = mesh.nodes[site].snapshot_state()
    return snap["accounts"]


@app.post("/transfer")
def transfer(
    src: str = Query(...),
    dst: str = Query(...),
    amount: Decimal = Query(...),
    site: str = Query(DEFAULT_SITE),
    transfer_id: Optional[str] = Query(None),
):
    """Portable PayMesh transfer endpoint (supports query parameters & cross-site propagation)."""
    site = site.lower()
    if site not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    if amount <= 0 or src == dst:
        raise HTTPException(400, "amount must be positive and accounts must differ")
    try:
        res = mesh.submit_transfer(site=site, src=src, dst=dst, amount=amount, transfer_id=transfer_id)
        return {
            "transfer_id": res["transfer"]["TransferId"],
            "site": site,
            "idempotent_replay": res["idempotent_replay"],
            "propagation": res["propagation"],
        }
    except ValueError as err:
        raise HTTPException(409, str(err))


@app.get("/search")
def search(q: str = Query(..., min_length=1), site: str = Query(DEFAULT_SITE)):
    """Full-text search across Account Owners and Retail Products on the selected site."""
    site = site.lower()
    if site not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    return mesh.nodes[site].search_accounts_and_products(q)


@app.get("/network/{account_id}")
def network(account_id: str, site: str = Query(DEFAULT_SITE)):
    """ISO GQL Property Graph traversal over PayGraph (1 to 3 hops)."""
    site = site.lower()
    if site not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    return mesh.nodes[site].query_pay_graph(account_id)


# ---------------------------------------------------------------------------
# Multi-Cloud Mesh, Retail Checkout, Vector & Graph Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/mesh")
def get_mesh():
    """Return full 3-environment state (Laptop, GCP, AWS), network links, digests, and recon logs."""
    return mesh.get_mesh_overview()


@app.post("/api/site/{site}/transfer")
def api_site_transfer(site: str, req: TransferRequest):
    site = site.lower()
    if site not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    try:
        return mesh.submit_transfer(
            site=site,
            src=req.src,
            dst=req.dst,
            amount=req.amount,
            transfer_id=req.transfer_id,
        )
    except ValueError as err:
        raise HTTPException(409, str(err))


@app.post("/api/site/{site}/checkout")
def api_site_checkout(site: str, req: CheckoutRequest):
    site = site.lower()
    if site not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    try:
        return mesh.submit_checkout(
            site=site,
            customer_id=req.customer_id,
            product_id=req.product_id,
            quantity=req.quantity,
            order_id=req.order_id,
        )
    except ValueError as err:
        raise HTTPException(409, str(err))


@app.post("/api/site/{site}/products")
def api_create_product(site: str, req: CreateProductRequest):
    site = site.lower()
    if site not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    return mesh.submit_product(
        site=site,
        product_id=req.product_id,
        name=req.name,
        description=req.description,
        price_cents=req.price_cents,
        initial_stock=req.initial_stock,
    )


@app.get("/api/site/{site}/similar/{product_id}")
def api_similar_products(site: str, product_id: str):
    site = site.lower()
    if site not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    try:
        return {
            "site": site,
            "product_id": product_id,
            "similar": mesh.nodes[site].vector_similar_products(product_id),
        }
    except ValueError as err:
        raise HTTPException(404, str(err))


@app.get("/api/site/{site}/graph/retail")
def api_retail_graph(site: str):
    site = site.lower()
    if site not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    return {
        "site": site,
        "edges": mesh.nodes[site].query_retail_graph(),
    }


@app.get("/api/site/{site}/verify")
def api_verify_site(site: str):
    site = site.lower()
    if site not in SITES:
        raise HTTPException(400, f"Unknown site '{site}'")
    return mesh.nodes[site].verify_invariants()


# ---------------------------------------------------------------------------
# Network Partition / Chaos Simulation & TrueTime Reconciliation Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/chaos/link")
def api_toggle_link(req: LinkToggleRequest):
    try:
        return mesh.set_link_state(req.site_a.lower(), req.site_b.lower(), req.connected)
    except ValueError as err:
        raise HTTPException(400, str(err))


@app.post("/api/chaos/isolate/{site}")
def api_isolate_site(site: str):
    try:
        return mesh.isolate_site(site.lower())
    except ValueError as err:
        raise HTTPException(400, str(err))


@app.post("/api/chaos/heal")
def api_heal_network(auto_reconcile: bool = Query(True)):
    return mesh.heal_all_links(auto_reconcile=auto_reconcile)


@app.post("/api/reconcile")
def api_reconcile():
    return mesh.reconcile_all()


@app.post("/api/demo/guided-recon")
def api_guided_recon_demo():
    """Run the complete Partition -> Concurrent Writes -> TrueTime Reconciliation walkthrough."""
    return mesh.run_guided_partition_recon_scenario()


@app.post("/api/reset")
def api_reset():
    return mesh.reset_all()
