"""Automated Test Suite for Spanner Omni Hybrid Multi-Cloud Sync & Reconciliation.

Runnable via both:
  - python3 -m unittest discover -s tests -p "test_*.py" -v
  - pytest -v tests/test_recon_and_sync.py
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from recon_engine import HybridOmniMesh, SITES

try:
    from fastapi.testclient import TestClient
    from app import app
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


class TestSpannerOmniHybridMesh(unittest.TestCase):
    def test_cross_environment_live_replication(self):
        """Verify that writes on any environment (Laptop, GCP, AWS) immediately update all connected peers."""
        mesh = HybridOmniMesh()
        initial_digests = {s: mesh.nodes[s].compute_state_digest() for s in SITES}
        self.assertEqual(len(set(initial_digests.values())), 1)

        # 1. Write on Laptop -> replicates to GCP and AWS
        res_laptop = mesh.submit_transfer(
            site="laptop", src="acc-1", dst="acc-3", amount=Decimal("150.00"), transfer_id="tx-live-1"
        )
        self.assertEqual(res_laptop["propagation"], {"gcp": "LIVE_REPLICATED", "aws": "LIVE_REPLICATED"})
        for s in SITES:
            self.assertEqual(mesh.nodes[s].accounts["acc-1"]["Balance"], Decimal("4850.00"))
            self.assertEqual(mesh.nodes[s].accounts["acc-3"]["Balance"], Decimal("950.00"))

        # 2. Write on AWS -> replicates to Laptop and GCP
        res_aws = mesh.submit_checkout(
            site="aws", customer_id="cust-chen", product_id="p1", quantity=2, order_id="ord-live-aws-1"
        )
        self.assertEqual(res_aws["propagation"], {"laptop": "LIVE_REPLICATED", "gcp": "LIVE_REPLICATED"})
        for s in SITES:
            self.assertEqual(mesh.nodes[s].products["p1"]["Stock"], 8)

        # 3. Write on GCP -> replicates to Laptop and AWS
        res_gcp = mesh.submit_checkout(
            site="gcp", customer_id="cust-ben", product_id="p4", quantity=3, order_id="ord-live-gcp-1"
        )
        self.assertEqual(res_gcp["propagation"], {"laptop": "LIVE_REPLICATED", "aws": "LIVE_REPLICATED"})
        for s in SITES:
            self.assertEqual(mesh.nodes[s].products["p4"]["Stock"], 17)
            self.assertTrue(mesh.nodes[s].verify_invariants()["valid"])

        final_digests = {s: mesh.nodes[s].compute_state_digest() for s in SITES}
        self.assertEqual(len(set(final_digests.values())), 1)

    def test_network_disruption_divergence_and_truetime_reconciliation(self):
        """Verify disconnection queuing, state divergence, conflict resolution, and 100% convergence."""
        mesh = HybridOmniMesh()
        report = mesh.run_guided_partition_recon_scenario()

        self.assertTrue(report["step1_connected_write"]["all_converged"])
        self.assertTrue(report["step2_partitioned_writes"]["all_diverged"])
        self.assertTrue(report["step3_reconciliation"]["all_converged"])

        # Verify commutative account balance merge ($5000 - $300 on laptop - $200 on aws = $4500)
        for s in SITES:
            self.assertEqual(mesh.nodes[s].accounts["acc-1"]["Balance"], Decimal("4500.00"))
            # Verify p1 inventory conflict resolution: 10 initial - 7 confirmed on GCP = 3 remaining
            self.assertEqual(mesh.nodes[s].products["p1"]["Stock"], 3)
            self.assertEqual(mesh.nodes[s].orders["ord-partition-gcp-7u"]["Status"], "CONFIRMED")
            self.assertEqual(
                mesh.nodes[s].orders["ord-partition-aws-6u"]["Status"],
                "BACKORDERED_RECON_COMPENSATED",
            )
            self.assertTrue(mesh.nodes[s].verify_invariants()["valid"])

    def test_multimodel_search_vector_and_graphs(self):
        """Verify Full-Text Search, Vector Cosine Similarity, and ISO GQL Property Graphs."""
        mesh = HybridOmniMesh()
        node = mesh.nodes["laptop"]

        # Full-text search
        ft = node.search_accounts_and_products("waterproof")
        self.assertGreaterEqual(len(ft["products"]), 3)
        self.assertTrue(any(p["ProductId"] == "p1" for p in ft["products"]))

        # Vector KNN similarity
        sim = node.vector_similar_products("p1", limit=3)
        self.assertEqual(len(sim), 3)
        self.assertEqual(sim[0]["ProductId"], "p2")

        # Property Graphs
        pay_graph = node.query_pay_graph("acc-2", max_hops=3)
        reachable_ids = {r["AccountId"] for r in pay_graph["reachable_accounts"]}
        self.assertIn("acc-1", reachable_ids)
        self.assertIn("acc-3", reachable_ids)
        self.assertIn("acc-4", reachable_ids)

        retail_graph = node.query_retail_graph()
        self.assertGreaterEqual(len(retail_graph), 2)

    @unittest.skipUnless(HAS_FASTAPI, "FastAPI not installed in current interpreter")
    def test_fastapi_control_plane_endpoints(self):
        """Verify FastAPI HTTP endpoints for transfers, checkouts, chaos links, and reconciliation."""
        client = TestClient(app)
        client.post("/api/reset")

        r_mesh = client.get("/api/mesh")
        self.assertEqual(r_mesh.status_code, 200)
        self.assertTrue(r_mesh.json()["topology"]["state_converged"])

        # Isolate AWS and perform a checkout on AWS
        r_iso = client.post("/api/chaos/isolate/aws")
        self.assertEqual(r_iso.status_code, 200)
        self.assertFalse(r_iso.json()["all_links_healthy"])

        r_buy = client.post(
            "/api/site/aws/checkout",
            json={"customer_id": "cust-chen", "product_id": "p5", "quantity": 2, "order_id": "ord-aws-isolated"},
        )
        self.assertEqual(r_buy.status_code, 200)
        self.assertEqual(r_buy.json()["propagation"]["laptop"], "QUEUED_NETWORK_PARTITION")

        # Verify state is diverged while AWS is isolated
        r_mesh_div = client.get("/api/mesh").json()
        self.assertFalse(r_mesh_div["topology"]["state_converged"])
        self.assertEqual(r_mesh_div["sites"]["aws"]["products"][4]["Stock"], 6)
        self.assertEqual(r_mesh_div["sites"]["laptop"]["products"][4]["Stock"], 8)

        # Heal and reconcile
        r_heal = client.post("/api/chaos/heal?auto_reconcile=true")
        self.assertEqual(r_heal.status_code, 200)
        self.assertTrue(r_heal.json()["reconciliation"]["state_converged"])

        r_mesh_healed = client.get("/api/mesh").json()
        self.assertEqual(r_mesh_healed["sites"]["laptop"]["products"][4]["Stock"], 6)
        self.assertEqual(r_mesh_healed["sites"]["gcp"]["products"][4]["Stock"], 6)
        self.assertEqual(r_mesh_healed["sites"]["aws"]["products"][4]["Stock"], 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
