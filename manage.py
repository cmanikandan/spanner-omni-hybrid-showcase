#!/usr/bin/env python3
"""Spanner Omni Hybrid Multi-Cloud Management & Verification CLI (manage.py).

Commands:
  python manage.py init           # Initialize schema and seed data on target OMNI_ENDPOINT
  python manage.py verify         # Verify inventory & financial ledger invariants across sites
  python manage.py simulate-recon # Run end-to-end cross-cloud replication, partition & recon demo
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

from db import (
    HAS_SPANNER_SDK,
    SEED_ACCOUNTS,
    SEED_CUSTOMERS,
    SEED_ORDERS,
    SEED_PRODUCTS,
    SEED_TRANSFERS,
    SiteNodeEngine,
    _is_tcp_reachable,
    create_omni_spanner_client,
)
from recon_engine import HybridOmniMesh


def parse_ddl_statements(schema_path: Path):
    text = schema_path.read_text(encoding="utf-8")
    lines = [
        line for line in text.splitlines() if not line.strip().startswith("--")
    ]
    cleaned = "\n".join(lines)
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


def cmd_init(args: argparse.Namespace) -> int:
    endpoint = os.environ.get("OMNI_ENDPOINT", "127.0.0.1:15000")
    database_name = os.environ.get("OMNI_DATABASE", "omni-hybrid")
    site = os.environ.get("OMNI_SITE", os.environ.get("DEMO_ENV", "laptop")).lower()

    print(f"[*] Target site='{site}' endpoint='{endpoint}' database='{database_name}'")

    if HAS_SPANNER_SDK and _is_tcp_reachable(endpoint) and not args.sim_only:
        print(f"[*] Live Spanner Omni endpoint detected at {endpoint}. Applying DDL from schema.sql...")
        client = create_omni_spanner_client(endpoint)
        db = client.instance("default").database(database_name)

        # Refuse to overwrite existing user tables unless --force is passed
        with db.snapshot() as snap:
            existing = list(
                snap.execute_sql(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = ''"
                )
            )
        if existing and not args.force:
            print(
                f"[!] Database '{database_name}' at {endpoint} already contains {len(existing)} tables. "
                "Refusing to overwrite existing schema (pass --force or choose a fresh OMNI_DATABASE)."
            )
            return 1

        ddl_statements = parse_ddl_statements(Path(__file__).parent / "schema.sql")
        if not existing:
            operation = db.update_ddl(ddl_statements)
            operation.result(300)
            print(f"[+] Applied {len(ddl_statements)} DDL statements to '{database_name}'.")

        from google.cloud import spanner

        with db.batch() as batch:
            batch.insert_or_update(
                "Accounts",
                ("AccountId", "Owner", "Region", "Balance", "UpdatedSite", "UpdatedAt"),
                [
                    (aid, owner, reg, bal, site, spanner.COMMIT_TIMESTAMP)
                    for aid, owner, reg, bal in SEED_ACCOUNTS
                ],
            )
            batch.insert_or_update(
                "Customers",
                ("CustomerId", "Name", "Region", "UpdatedSite", "CreatedAt"),
                [
                    (cid, name, reg, site, spanner.COMMIT_TIMESTAMP)
                    for cid, name, reg in SEED_CUSTOMERS
                ],
            )
            batch.insert_or_update(
                "Products",
                (
                    "ProductId",
                    "Name",
                    "Description",
                    "PriceCents",
                    "InitialStock",
                    "Stock",
                    "Embedding",
                    "UpdatedSite",
                ),
                [
                    (pid, name, desc, price, init_s, stock, emb, site)
                    for pid, name, desc, price, init_s, stock, emb in SEED_PRODUCTS
                ],
            )
            batch.insert_or_update(
                "Orders",
                (
                    "CustomerId",
                    "OrderId",
                    "ProductId",
                    "Quantity",
                    "UnitPriceCents",
                    "Status",
                    "OriginSite",
                    "CommitTs",
                ),
                [
                    (cid, oid, pid, qty, price, status, orig, spanner.COMMIT_TIMESTAMP)
                    for cid, oid, pid, qty, price, status, orig in SEED_ORDERS
                ],
            )
            batch.insert_or_update(
                "Transfers",
                ("TransferId", "FromAccount", "ToAccount", "Amount", "OriginSite", "Status", "CreatedAt"),
                [
                    (tid, src, dst, amt, orig, status, spanner.COMMIT_TIMESTAMP)
                    for tid, src, dst, amt, orig, status in SEED_TRANSFERS
                ],
            )
        print(f"[+] Seeded Accounts, Customers, Products, Orders, and Transfers on {endpoint}/{database_name}.")
        return 0

    node = SiteNodeEngine(site=site, endpoint=endpoint, database_name=database_name)
    node.init_seed_state()
    inv = node.verify_invariants()
    print(
        f"[+] Initialized local replica state for site='{site}' "
        f"(digest={inv['state_digest']}, ledger_total=${inv['total_ledger_balance']})"
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    mesh = HybridOmniMesh()
    all_ok = True
    for site, node in mesh.nodes.items():
        inv = node.verify_invariants()
        status = "PASS" if inv["valid"] else "FAIL"
        print(
            f"[{status}] site={site:<6} endpoint={node.endpoint:<16} "
            f"digest={inv['state_digest']} total_balance=${inv['total_ledger_balance']}"
        )
        if not inv["valid"]:
            all_ok = False
            for v in inv["violations"]:
                print(f"   ! Violation: {v}")
    return 0 if all_ok else 1


def cmd_simulate_recon(args: argparse.Namespace) -> int:
    mesh = HybridOmniMesh()
    report = mesh.run_guided_partition_recon_scenario()
    print("=" * 78)
    print("SPANNER OMNI HYBRID MULTI-CLOUD SYNC & PARTITION RECONCILIATION REPORT")
    print("=" * 78)
    print("\n[Phase 1] Connected Multi-Cloud Write (GCP -> Laptop & AWS):")
    print(json.dumps(report["step1_connected_write"], indent=2))
    print("\n[Phase 2] Network Disrupted — Independent Concurrent Writes Across Clouds:")
    print(json.dumps(report["step2_partitioned_writes"], indent=2))
    print("\n[Phase 3] Network Healed — TrueTime Anti-Entropy Reconciliation & Convergence:")
    recon = report["step3_reconciliation"]
    print(f"  - Total Mutations Evaluated : {recon['recon_summary']['total_mutations_evaluated']}")
    print(f"  - Events Applied            : {recon['recon_summary']['events_applied_count']}")
    print(f"  - Conflicts Compensated     : {recon['recon_summary']['conflicts_compensated_count']}")
    print(f"  - Post-Recon p1 Stock       : {recon['converged_p1_stock']}")
    print(f"  - Post-Recon acc-1 Balance  : {recon['converged_acc1_balance']}")
    print(f"  - Post-Recon SHA-256 Digests: {recon['converged_digests']}")
    print(f"  - 100% State Converged      : {recon['all_converged']}")
    print("=" * 78)
    return 0 if recon["all_converged"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Spanner Omni Hybrid Multi-Cloud CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize schema and seed records")
    p_init.add_argument("--force", action="store_true", help="Allow seeding over existing tables")
    p_init.add_argument("--sim-only", action="store_true", help="Initialize local simulation state only")
    p_init.set_defaults(func=cmd_init)

    p_verify = sub.add_parser("verify", help="Verify inventory and financial ledger invariants")
    p_verify.set_defaults(func=cmd_verify)

    p_recon = sub.add_parser(
        "simulate-recon",
        help="Run guided cross-cloud replication, network disruption, and TrueTime reconciliation demo",
    )
    p_recon.set_defaults(func=cmd_simulate_recon)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
