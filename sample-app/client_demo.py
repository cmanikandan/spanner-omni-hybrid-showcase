#!/usr/bin/env python3
"""Self-Contained End-to-End Sample App Verification & Demo Runner (sample-app/client_demo.py).

Exercises the sample application across all three environments (Laptop, GCP, AWS):
  1. Verifies initial seed state and SHA-256 convergence across Laptop, GCP, and AWS.
  2. Executes a live payment transfer on Laptop and a product purchase on AWS while connected,
     proving immediate cross-environment updates in GCP, AWS, and Laptop.
  3. Disrupts network connections between Laptop, GCP, and AWS.
  4. Executes concurrent, conflicting updates across disconnected environments:
     - Concurrent debits to Account 'acc-1' on Laptop (-$300) and AWS (-$200)
     - Concurrent purchases of Product 'p2' exceeding remaining stock across GCP and AWS
  5. Restores network connections and triggers TrueTime Reconciliation, proving:
     - Commutative balance deltas merge without losing updates
     - Split-brain oversold inventory is deterministically compensated (Stock >= 0 preserved)
     - All three environments converge to the exact same SHA-256 state digest
  6. Exercises Full-Text Search, Vector Cosine Similarity, and ISO GQL Property Graphs.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from recon_engine import HybridOmniMesh, SITES


def print_banner(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_site_summary(mesh: HybridOmniMesh) -> None:
    topo = mesh.get_network_topology()
    print(f"  Network Links   : {topo['links']}")
    print(f"  State Converged : {topo['state_converged']}")
    for s in SITES:
        node = mesh.nodes[s]
        acc1 = node.accounts["acc-1"]["Balance"]
        p1_stock = node.products["p1"]["Stock"]
        pending = sum(1 for m in node.sync_mutations.values() if m["SyncStatus"] != "SYNCED_ALL")
        print(
            f"    - [{s.upper():<6}] endpoint={node.endpoint:<16} "
            f"digest={topo['site_digests'][s]} | acc-1=${acc1:<8} | p1_stock={p1_stock:<2} | pending_outbox={pending}"
        )


def main() -> int:
    mesh = HybridOmniMesh()

    print_banner("STEP 1: INITIAL SEED STATE ACROSS LAPTOP (DOCKER), GCP, AND AWS")
    print_site_summary(mesh)

    print_banner("STEP 2: CONNECTED MULTI-CLOUD WRITES (WRITE ANYWHERE -> UPDATE EVERYWHERE)")
    print("[>] Executing Transfer on LAPTOP: $250.00 from acc-2 (Vikram) -> acc-3 (Meera)...")
    tx_res = mesh.submit_transfer(
        site="laptop", src="acc-2", dst="acc-3", amount=Decimal("250.00"), transfer_id="demo-tx-laptop-1"
    )
    print(f"    Propagation result: {tx_res['propagation']}")

    print("[>] Executing Checkout on AWS: Customer 'cust-chen' buys 2 units of 'p4' (Merino Base Layer)...")
    ord_res = mesh.submit_checkout(
        site="aws", customer_id="cust-chen", product_id="p4", quantity=2, order_id="demo-ord-aws-1"
    )
    print(f"    Propagation result: {ord_res['propagation']}")
    print_site_summary(mesh)

    print_banner("STEP 3: SIMULATE NETWORK DISRUPTION (CUTTING LINKS BETWEEN LAPTOP, GCP, AND AWS)")
    mesh.set_link_state("laptop", "gcp", False)
    mesh.set_link_state("gcp", "aws", False)
    mesh.set_link_state("laptop", "aws", False)
    print("[!] All inter-environment WAN links severed. Environments are now operating independently.")

    print("\n[>] Disconnected Write #1 (on GCP @ T1): 'cust-ben' orders 7 units of 'p1' (10 in stock)...")
    gcp_buy = mesh.nodes["gcp"].execute_checkout(
        customer_id="cust-ben",
        product_id="p1",
        quantity=7,
        order_id="demo-partition-gcp-7u",
        commit_ts="2026-10-01T15:00:01+00:00",
    )
    mesh._propagate_mutation("gcp", gcp_buy["mutation"])

    print("[>] Disconnected Write #2 (on AWS @ T2): 'cust-chen' orders 6 units of 'p1' (10 in stock locally on AWS!)...")
    aws_buy = mesh.nodes["aws"].execute_checkout(
        customer_id="cust-chen",
        product_id="p1",
        quantity=6,
        order_id="demo-partition-aws-6u",
        commit_ts="2026-10-01T15:00:02+00:00",
    )
    mesh._propagate_mutation("aws", aws_buy["mutation"])

    print("[>] Disconnected Write #3 (on LAPTOP @ T3): Transfer $300.00 from acc-1 -> acc-5...")
    lap_tx = mesh.nodes["laptop"].execute_transfer(
        src="acc-1",
        dst="acc-5",
        amount=Decimal("300.00"),
        transfer_id="demo-partition-laptop-300",
        commit_ts="2026-10-01T15:00:03+00:00",
    )
    mesh._propagate_mutation("laptop", lap_tx["mutation"])

    print("[>] Disconnected Write #4 (on AWS @ T4): Concurrent Transfer $200.00 from acc-1 -> acc-4...")
    aws_tx = mesh.nodes["aws"].execute_transfer(
        src="acc-1",
        dst="acc-4",
        amount=Decimal("200.00"),
        transfer_id="demo-partition-aws-200",
        commit_ts="2026-10-01T15:00:04+00:00",
    )
    mesh._propagate_mutation("aws", aws_tx["mutation"])

    print("\n[*] State across environments DURING network disruption (note diverged digests & balances):")
    print_site_summary(mesh)

    print_banner("STEP 4: RESTORE CONNECTIONS & RUN TRUETIME RECONCILIATION (RECON)")
    heal = mesh.heal_all_links(auto_reconcile=True)
    recon = heal["reconciliation"]
    print(f"[+] TrueTime Reconciliation evaluated {recon['total_mutations_evaluated']} mutations:")
    print(f"    - Mutations Replayed Across Peers : {recon['events_applied_count']}")
    print(f"    - Split-Brain Conflicts Resolved  : {recon['conflicts_compensated_count']}")
    for c in recon["compensated_conflicts"]:
        print(f"      * [{c['TargetSite'].upper()}] {c['Outcome']}: {c['Details']}")

    print("\n[*] State across environments AFTER TrueTime Reconciliation:")
    print_site_summary(mesh)

    print_banner("STEP 5: MULTI-MODEL QUERIES (FULL-TEXT SEARCH, VECTOR KNN, ISO GQL GRAPH)")
    gcp_node = mesh.nodes["gcp"]
    ft_results = gcp_node.search_accounts_and_products("waterproof")
    print(f"[1] Full-Text Search for 'waterproof' on GCP found {len(ft_results['products'])} products and {len(ft_results['accounts'])} accounts.")

    vec_results = gcp_node.vector_similar_products("p1", limit=2)
    print(f"[2] Vector KNN Similarity (COSINE_DISTANCE to 'p1' with Stock > 0): {json.dumps(vec_results)}")

    pay_graph = gcp_node.query_pay_graph("acc-1", max_hops=3)
    print(
        f"[3] ISO GQL PayGraph (1..3 hops from acc-1): "
        f"{[r['AccountId'] for r in pay_graph['reachable_accounts']]}"
    )

    assert recon["state_converged"] is True
    assert recon["invariants_valid"] is True
    print("\n[SUCCESS] All 3 environments (Laptop, GCP, AWS) converged with 0 invariant violations!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
