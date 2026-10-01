"""Spanner Omni Hybrid Multi-Cloud Sync & Reconciliation Engine (recon_engine.py).

Implements:
  1. Active-Active Cross-Environment Replication across Laptop (Docker), GCP (GCE/GKE), and AWS (EC2/EKS)
  2. Network Partition / Link Disruption Simulator (per-link or per-site isolation)
  3. TrueTime-Ordered Anti-Entropy Reconciliation Engine:
     - Commutative Delta Merging for concurrent financial transfers and inventory updates
     - Invariant-Preserving Conflict Resolution (StockNonnegative & Overdraft Compensation)
     - Idempotent Mutation Deduplication
     - Cryptographic SHA-256 Convergence Verification across all 3 environments
"""

from __future__ import annotations

import copy
import datetime
import json
import threading
import uuid
from collections import deque
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

from db import SiteNodeEngine, _utc_iso

SITES = ("laptop", "gcp", "aws")


class HybridOmniMesh:
    """Coordinates the 3-environment Spanner Omni Hybrid Multi-Cloud Mesh."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.nodes: Dict[str, SiteNodeEngine] = {
            site: SiteNodeEngine(site=site) for site in SITES
        }
        # Undirected network link states between pairs of environments
        self.links: Dict[Tuple[str, str], bool] = {
            ("laptop", "gcp"): True,
            ("gcp", "aws"): True,
            ("laptop", "aws"): True,
        }
        self.recon_history: List[Dict[str, Any]] = []

    @staticmethod
    def _norm_pair(site_a: str, site_b: str) -> Tuple[str, str]:
        for pair in (("laptop", "gcp"), ("gcp", "aws"), ("laptop", "aws")):
            if {site_a, site_b} == set(pair):
                return pair
        raise ValueError(f"Invalid site pair: {site_a}, {site_b}")

    # -------------------------------------------------------------------------
    # Network Topology & Link Disruption Controls
    # -------------------------------------------------------------------------

    def set_link_state(self, site_a: str, site_b: str, connected: bool) -> Dict[str, Any]:
        with self.lock:
            pair = self._norm_pair(site_a, site_b)
            self.links[pair] = bool(connected)
            return self.get_network_topology()

    def isolate_site(self, site: str) -> Dict[str, Any]:
        """Sever all network connections to/from the specified environment."""
        if site not in self.nodes:
            raise ValueError(f"Unknown site: {site}")
        with self.lock:
            for pair in list(self.links.keys()):
                if site in pair:
                    self.links[pair] = False
            return self.get_network_topology()

    def heal_all_links(self, auto_reconcile: bool = True) -> Dict[str, Any]:
        """Restore all network links across Laptop, GCP, and AWS and optionally trigger reconciliation."""
        with self.lock:
            for pair in list(self.links.keys()):
                self.links[pair] = True
            recon_report = self.reconcile_all() if auto_reconcile else None
            return {
                "topology": self.get_network_topology(),
                "reconciliation": recon_report,
            }

    def reachable_peers(self, origin: str) -> List[str]:
        """Return all peer sites reachable from `origin` over active network links (BFS)."""
        with self.lock:
            visited: Set[str] = {origin}
            queue = deque([origin])
            while queue:
                curr = queue.popleft()
                for (a, b), up in self.links.items():
                    if not up:
                        continue
                    neighbor = b if curr == a else (a if curr == b else None)
                    if neighbor and neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            return [s for s in SITES if s in visited and s != origin]

    def get_network_topology(self) -> Dict[str, Any]:
        with self.lock:
            digests = {s: self.nodes[s].compute_state_digest() for s in SITES}
            converged = len(set(digests.values())) == 1
            return {
                "links": {
                    f"{a}<->{b}": up for (a, b), up in self.links.items()
                },
                "reachability": {
                    s: self.reachable_peers(s) for s in SITES
                },
                "all_links_healthy": all(self.links.values()),
                "state_converged": converged,
                "site_digests": digests,
            }

    # -------------------------------------------------------------------------
    # Write Anywhere -> Propagate to Connected Peers (or Queue for Recon)
    # -------------------------------------------------------------------------

    def submit_transfer(
        self,
        site: str,
        src: str,
        dst: str,
        amount: Decimal,
        transfer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if site not in self.nodes:
            raise ValueError(f"Unknown site: {site}")
        with self.lock:
            node = self.nodes[site]
            res = node.execute_transfer(src=src, dst=dst, amount=amount, transfer_id=transfer_id)
            if res.get("idempotent_replay"):
                return {
                    "origin_site": site,
                    "transfer": res["transfer"],
                    "idempotent_replay": True,
                    "propagation": {},
                }
            mutation = res["mutation"]
            propagation = self._propagate_mutation(origin_site=site, mutation=mutation)
            return {
                "origin_site": site,
                "transfer": res["transfer"],
                "idempotent_replay": False,
                "propagation": propagation,
                "topology": self.get_network_topology(),
            }

    def submit_checkout(
        self,
        site: str,
        customer_id: str,
        product_id: str,
        quantity: int,
        order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if site not in self.nodes:
            raise ValueError(f"Unknown site: {site}")
        with self.lock:
            node = self.nodes[site]
            res = node.execute_checkout(
                customer_id=customer_id,
                product_id=product_id,
                quantity=quantity,
                order_id=order_id,
            )
            if res.get("idempotent_replay"):
                return {
                    "origin_site": site,
                    "order": res["order"],
                    "idempotent_replay": True,
                    "propagation": {},
                }
            mutation = res["mutation"]
            propagation = self._propagate_mutation(origin_site=site, mutation=mutation)
            return {
                "origin_site": site,
                "order": res["order"],
                "idempotent_replay": False,
                "propagation": propagation,
                "topology": self.get_network_topology(),
            }

    def submit_product(
        self,
        site: str,
        product_id: str,
        name: str,
        description: str,
        price_cents: int,
        initial_stock: int,
        embedding: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        if site not in self.nodes:
            raise ValueError(f"Unknown site: {site}")
        with self.lock:
            node = self.nodes[site]
            res = node.create_product(
                product_id=product_id,
                name=name,
                description=description,
                price_cents=price_cents,
                initial_stock=initial_stock,
                embedding=embedding,
            )
            propagation = self._propagate_mutation(origin_site=site, mutation=res["mutation"])
            return {
                "origin_site": site,
                "product": res["product"],
                "propagation": propagation,
            }

    def _propagate_mutation(self, origin_site: str, mutation: Dict[str, Any]) -> Dict[str, Any]:
        """Replicate mutation immediately to reachable peers; mark queued for unreachable peers."""
        reachable = set(self.reachable_peers(origin_site))
        peer_results: Dict[str, str] = {}
        origin_node = self.nodes[origin_site]

        for peer in SITES:
            if peer == origin_site:
                continue
            if peer in reachable:
                outcome = self._apply_mutation_to_target(
                    target_node=self.nodes[peer],
                    mutation=mutation,
                    is_recon=False,
                )
                peer_results[peer] = outcome["Outcome"]
            else:
                peer_results[peer] = "QUEUED_NETWORK_PARTITION"

        if len(reachable) == len(SITES) - 1:
            origin_node.sync_mutations[mutation["MutationId"]]["SyncStatus"] = "SYNCED_ALL"
        else:
            origin_node.sync_mutations[mutation["MutationId"]]["SyncStatus"] = "PENDING_RECON"

        return peer_results

    # -------------------------------------------------------------------------
    # Deterministic Reconciliation Engine (Anti-Entropy + TrueTime Resolution)
    # -------------------------------------------------------------------------

    def _apply_mutation_to_target(
        self,
        target_node: SiteNodeEngine,
        mutation: Dict[str, Any],
        is_recon: bool = True,
    ) -> Dict[str, Any]:
        """Apply a remote mutation onto `target_node` using commutative delta & invariant rules."""
        mut_id = mutation["MutationId"]
        origin = mutation["OriginSite"]
        entity_type = mutation["EntityType"]
        entity_key = mutation["EntityKey"]
        payload = json.loads(mutation["PayloadJson"])
        commit_ts = mutation["CommitTs"]

        with target_node.lock:
            # 1. Idempotency check: has this exact mutation already been applied on target_node?
            if mut_id in target_node.sync_mutations:
                return {
                    "Outcome": "IDEMPOTENT_SKIP",
                    "ResolutionStrategy": "IDEMPOTENCY_KEY_DEDUP",
                    "Details": f"Mutation {mut_id} already present on {target_node.site}",
                }

            strategy = "COMMUTATIVE_DELTA_MERGE"
            outcome = "APPLIED"
            details = ""

            if entity_type == "PRODUCT" and mutation["Operation"] == "UPSERT_PRODUCT":
                pid = payload["ProductId"]
                if pid not in target_node.products:
                    target_node.products[pid] = {
                        "ProductId": pid,
                        "Name": payload["Name"],
                        "Description": payload["Description"],
                        "PriceCents": payload["PriceCents"],
                        "InitialStock": payload["InitialStock"],
                        "Stock": payload["Stock"],
                        "Embedding": payload.get("Embedding", [0.5, 0.5, 0.5, 0.5]),
                        "UpdatedSite": origin,
                    }
                details = f"Replicated product definition {pid} from {origin}"

            elif entity_type == "TRANSFER":
                tx_id = payload["transfer_id"]
                src = payload["src"]
                dst = payload["dst"]
                amt = Decimal(str(payload["amount"])).quantize(Decimal("0.01"))

                if tx_id in target_node.transfers:
                    outcome = "IDEMPOTENT_SKIP"
                    strategy = "IDEMPOTENCY_KEY_DEDUP"
                    details = f"Transfer {tx_id} already committed on {target_node.site}"
                else:
                    src_acc = target_node.accounts[src]
                    dst_acc = target_node.accounts[dst]
                    if src_acc["Balance"] >= amt:
                        src_acc["Balance"] -= amt
                        src_acc["UpdatedSite"] = origin
                        src_acc["UpdatedAt"] = commit_ts

                        dst_acc["Balance"] += amt
                        dst_acc["UpdatedSite"] = origin
                        dst_acc["UpdatedAt"] = commit_ts

                        target_node.transfers[tx_id] = {
                            "TransferId": tx_id,
                            "FromAccount": src,
                            "ToAccount": dst,
                            "Amount": amt,
                            "OriginSite": origin,
                            "Status": "COMMITTED",
                            "CreatedAt": commit_ts,
                        }
                        outcome = "RECON_APPLIED" if is_recon else "LIVE_REPLICATED"
                        details = (
                            f"Applied commutative transfer delta {src} -> {dst} (${amt}) "
                            f"from {origin} onto {target_node.site}"
                        )
                    else:
                        # Concurrent partition double-spend overdraft detected!
                        strategy = "TRUETIME_OVERDRAFT_COMPENSATION"
                        outcome = "OVERDRAFT_COMPENSATED"
                        target_node.transfers[tx_id] = {
                            "TransferId": tx_id,
                            "FromAccount": src,
                            "ToAccount": dst,
                            "Amount": amt,
                            "OriginSite": origin,
                            "Status": "REVERSED_OVERDRAFT_RECON",
                            "CreatedAt": commit_ts,
                        }
                        details = (
                            f"Conflict detected during recon: {src} had ${src_acc['Balance']} on {target_node.site} "
                            f"when applying ${amt} transfer {tx_id} from {origin}. Marked REVERSED_OVERDRAFT_RECON."
                        )

            elif entity_type == "ORDER":
                oid = payload["order_id"]
                cid = payload["customer_id"]
                pid = payload["product_id"]
                qty = int(payload["quantity"])
                unit_price = int(payload["unit_price_cents"])

                if oid in target_node.orders:
                    outcome = "IDEMPOTENT_SKIP"
                    strategy = "IDEMPOTENCY_KEY_DEDUP"
                    details = f"Order {oid} already present on {target_node.site}"
                else:
                    prod = target_node.products[pid]
                    if prod["Stock"] >= qty:
                        prod["Stock"] -= qty
                        prod["UpdatedSite"] = origin
                        target_node.orders[oid] = {
                            "CustomerId": cid,
                            "OrderId": oid,
                            "ProductId": pid,
                            "Quantity": qty,
                            "UnitPriceCents": unit_price,
                            "Status": "CONFIRMED",
                            "OriginSite": origin,
                            "CommitTs": commit_ts,
                        }
                        outcome = "RECON_APPLIED" if is_recon else "LIVE_REPLICATED"
                        details = (
                            f"Applied commutative stock delta (-{qty} on {pid}, remaining={prod['Stock']}) "
                            f"for Order {oid} from {origin} onto {target_node.site}"
                        )
                    else:
                        # Split-brain inventory over-subscription conflict!
                        strategy = "TRUETIME_INVENTORY_COMPENSATION"
                        outcome = "INVENTORY_CONFLICT_COMPENSATED"
                        target_node.orders[oid] = {
                            "CustomerId": cid,
                            "OrderId": oid,
                            "ProductId": pid,
                            "Quantity": qty,
                            "UnitPriceCents": unit_price,
                            "Status": "BACKORDERED_RECON_COMPENSATED",
                            "OriginSite": origin,
                            "CommitTs": commit_ts,
                        }
                        details = (
                            f"Split-brain stock conflict on {pid}: {origin} ordered {qty} units ({oid}), "
                            f"but only {prod['Stock']} remained after earlier TrueTime commits. "
                            f"Transitioned {oid} to BACKORDERED_RECON_COMPENSATED to preserve Stock >= 0."
                        )

            # Record mutation and watermark on target_node
            copied_mut = copy.deepcopy(mutation)
            copied_mut["SyncStatus"] = "SYNCED_ALL"
            target_node.sync_mutations[mut_id] = copied_mut

            wm = target_node.watermarks.get(origin)
            if wm:
                wm["LastMutationId"] = mut_id
                wm["LastCommitTs"] = commit_ts
                wm["AppliedCount"] += 1
                wm["UpdatedAt"] = _utc_iso()

            event = {
                "ReconId": f"rec-{uuid.uuid4().hex[:10]}",
                "SourceSite": origin,
                "TargetSite": target_node.site,
                "MutationId": mut_id,
                "EntityType": entity_type,
                "EntityKey": entity_key,
                "ResolutionStrategy": strategy,
                "Outcome": outcome,
                "Details": details,
                "ReconciledAt": _utc_iso(),
            }
            target_node.recon_events.append(event)
            return event

    def reconcile_all(self) -> Dict[str, Any]:
        """Execute deterministic TrueTime-ordered reconciliation across all reachable sites."""
        with self.lock:
            # Gather all unique mutations across all sites
            all_mutations: Dict[str, Dict[str, Any]] = {}
            for site, node in self.nodes.items():
                for mut_id, mut in node.sync_mutations.items():
                    if mut_id not in all_mutations:
                        all_mutations[mut_id] = copy.deepcopy(mut)

            # Sort mutations deterministically by Software TrueTime (CommitTs, OriginSite, MutationId)
            ordered_mutations = sorted(
                all_mutations.values(),
                key=lambda m: (m["CommitTs"], m["OriginSite"], m["MutationId"]),
            )

            applied_events: List[Dict[str, Any]] = []
            compensated_conflicts: List[Dict[str, Any]] = []

            # Phase 1 & 2: Replay missing mutations in TrueTime order across reachable pairs
            for mut in ordered_mutations:
                origin = mut["OriginSite"]
                reachable = self.reachable_peers(origin)
                for target_site in reachable:
                    ev = self._apply_mutation_to_target(
                        target_node=self.nodes[target_site],
                        mutation=mut,
                        is_recon=True,
                    )
                    if ev["Outcome"] != "IDEMPOTENT_SKIP":
                        applied_events.append(ev)
                    if ev["Outcome"] in ("INVENTORY_CONFLICT_COMPENSATED", "OVERDRAFT_COMPENSATED"):
                        compensated_conflicts.append(ev)

            # Phase 3: Ensure origin sites also reflect any TrueTime conflict compensation
            # (e.g., if two partitioned sites both committed conflicting orders that exceeded total stock,
            # replay canonical TrueTime state across connected components so every connected site converges 100%)
            self._enforce_canonical_truetime_convergence(ordered_mutations, applied_events, compensated_conflicts)

            # Mark mutations as SYNCED_ALL if all links are up
            if all(self.links.values()):
                for node in self.nodes.values():
                    for mut in node.sync_mutations.values():
                        mut["SyncStatus"] = "SYNCED_ALL"

            digests = {s: self.nodes[s].compute_state_digest() for s in SITES}
            invariants = {s: self.nodes[s].verify_invariants() for s in SITES}
            converged = len(set(digests.values())) == 1

            summary = {
                "reconciled_at": _utc_iso(),
                "total_mutations_evaluated": len(ordered_mutations),
                "events_applied_count": len(applied_events),
                "conflicts_compensated_count": len(compensated_conflicts),
                "applied_events": applied_events,
                "compensated_conflicts": compensated_conflicts,
                "state_converged": converged,
                "site_digests": digests,
                "invariants_valid": all(v["valid"] for v in invariants.values()),
            }
            self.recon_history.append(summary)
            return summary

    def _enforce_canonical_truetime_convergence(
        self,
        ordered_mutations: List[Dict[str, Any]],
        applied_events: List[Dict[str, Any]],
        compensated_conflicts: List[Dict[str, Any]],
    ) -> None:
        """When all sites are connected, ensure TrueTime serializable replay produces identical state."""
        if not all(self.links.values()):
            return

        # Check if digests already match
        digests = {s: self.nodes[s].compute_state_digest() for s in SITES}
        if len(set(digests.values())) == 1:
            return

        # Build canonical state from seed + TrueTime-ordered mutation log
        canonical = SiteNodeEngine(site="canonical")
        canonical.backend_mode = "sim"
        canonical.init_seed_state()

        for mut in ordered_mutations:
            ev = self._apply_mutation_to_target(target_node=canonical, mutation=mut, is_recon=True)
            if ev["Outcome"] in ("INVENTORY_CONFLICT_COMPENSATED", "OVERDRAFT_COMPENSATED"):
                # Ensure the origin site of the later conflicting transaction records the compensation
                origin_site = mut["OriginSite"]
                origin_node = self.nodes[origin_site]
                comp_event = {
                    "ReconId": f"rec-comp-{uuid.uuid4().hex[:8]}",
                    "SourceSite": "truetime-quorum",
                    "TargetSite": origin_site,
                    "MutationId": mut["MutationId"],
                    "EntityType": mut["EntityType"],
                    "EntityKey": mut["EntityKey"],
                    "ResolutionStrategy": ev["ResolutionStrategy"],
                    "Outcome": ev["Outcome"],
                    "Details": (
                        f"Origin site {origin_site} reconciled local optimistic commit {mut['EntityKey']} "
                        f"against earlier global TrueTime commit: {ev['Details']}"
                    ),
                    "ReconciledAt": _utc_iso(),
                }
                origin_node.recon_events.append(comp_event)
                applied_events.append(comp_event)
                compensated_conflicts.append(comp_event)

        # Synchronize the canonical post-reconciliation state across all connected sites
        for site, node in self.nodes.items():
            with node.lock:
                node.accounts = copy.deepcopy(canonical.accounts)
                node.transfers = copy.deepcopy(canonical.transfers)
                node.customers = copy.deepcopy(canonical.customers)
                node.products = copy.deepcopy(canonical.products)
                node.orders = copy.deepcopy(canonical.orders)
                for mut_id, mut in canonical.sync_mutations.items():
                    node.sync_mutations[mut_id] = copy.deepcopy(mut)

    # -------------------------------------------------------------------------
    # Automated Guided Demo Scenario: Partition -> Divergent Writes -> Recon
    # -------------------------------------------------------------------------

    def run_guided_partition_recon_scenario(self) -> Dict[str, Any]:
        """Execute an end-to-end multi-cloud disruption & reconciliation scenario in one call.

        Steps:
          1. Reset all 3 sites (laptop, gcp, aws) to identical seed state (converged SHA-256).
          2. Execute a live transfer on GCP ($250 from acc-2 -> acc-3) while connected ->
             verify immediate replication to Laptop and AWS.
          3. Disrupt connections: isolate Laptop and sever GCP <-> AWS link.
          4. Execute concurrent writes across all 3 disconnected environments:
             - On GCP (T1): Customer Ben buys 7 units of 'p1' (Alpine Jacket, stock 10 -> 3 on GCP)
             - On AWS (T2): Customer Chen buys 6 units of 'p1' (Alpine Jacket, stock 10 -> 4 on AWS) ->
               Total ordered across partitions = 13 units (> 10 available!)
             - On Laptop (T3): Asha transfers $300 from acc-1 -> acc-5, and AWS transfers $200 from acc-1 -> acc-4
               (Commutative balance deltas on acc-1!)
          5. Capture diverged state digests across Laptop, GCP, and AWS.
          6. Heal network links and run TrueTime Reconciliation Engine:
             - Commutative transfers on acc-1 merge cleanly ($5000 - $300 - $200 = $4500)
             - Earlier TrueTime order on GCP (7 units of p1) is CONFIRMED (stock = 3)
             - Later conflicting order on AWS (6 units of p1) is compensated to BACKORDERED_RECON_COMPENSATED
             - All 3 environments converge on the exact same SHA-256 state digest and pass all invariants!
        """
        with self.lock:
            self.reset_all()

            # Step 1: Connected write on GCP -> propagates to Laptop & AWS immediately
            connected_write = self.submit_transfer(
                site="gcp",
                src="acc-2",
                dst="acc-3",
                amount=Decimal("250.00"),
                transfer_id="tx-connected-gcp-1",
            )
            after_connected_digests = {s: self.nodes[s].compute_state_digest() for s in SITES}

            # Step 2: Sever all network links (simulate multi-cloud WAN disruption & offline laptop)
            self.set_link_state("laptop", "gcp", False)
            self.set_link_state("gcp", "aws", False)
            self.set_link_state("laptop", "aws", False)

            # Step 3: Concurrent writes during network disruption
            t_base = datetime.datetime(2026, 10, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
            t1 = (t_base + datetime.timedelta(seconds=1)).isoformat()
            t2 = (t_base + datetime.timedelta(seconds=2)).isoformat()
            t3 = (t_base + datetime.timedelta(seconds=3)).isoformat()
            t4 = (t_base + datetime.timedelta(seconds=4)).isoformat()

            # GCP: Order 7 units of p1 (10 in stock) at T1
            gcp_order = self.nodes["gcp"].execute_checkout(
                customer_id="cust-ben",
                product_id="p1",
                quantity=7,
                order_id="ord-partition-gcp-7u",
                commit_ts=t1,
            )
            self._propagate_mutation("gcp", gcp_order["mutation"])

            # AWS: Concurrently order 6 units of p1 (10 in stock locally on AWS!) at T2 > T1
            aws_order = self.nodes["aws"].execute_checkout(
                customer_id="cust-chen",
                product_id="p1",
                quantity=6,
                order_id="ord-partition-aws-6u",
                commit_ts=t2,
            )
            self._propagate_mutation("aws", aws_order["mutation"])

            # Laptop: Transfer $300 from acc-1 -> acc-5 at T3
            laptop_tx = self.nodes["laptop"].execute_transfer(
                src="acc-1",
                dst="acc-5",
                amount=Decimal("300.00"),
                transfer_id="tx-partition-laptop-300",
                commit_ts=t3,
            )
            self._propagate_mutation("laptop", laptop_tx["mutation"])

            # AWS: Concurrently transfer $200 from acc-1 -> acc-4 at T4
            aws_tx = self.nodes["aws"].execute_transfer(
                src="acc-1",
                dst="acc-4",
                amount=Decimal("200.00"),
                transfer_id="tx-partition-aws-200",
                commit_ts=t4,
            )
            self._propagate_mutation("aws", aws_tx["mutation"])

            diverged_digests = {s: self.nodes[s].compute_state_digest() for s in SITES}
            diverged_p1_stock = {s: self.nodes[s].products["p1"]["Stock"] for s in SITES}
            diverged_acc1_bal = {s: str(self.nodes[s].accounts["acc-1"]["Balance"]) for s in SITES}

            # Step 4: Restore connections & run TrueTime Reconciliation
            heal_result = self.heal_all_links(auto_reconcile=True)
            converged_digests = {s: self.nodes[s].compute_state_digest() for s in SITES}
            converged_p1_stock = {s: self.nodes[s].products["p1"]["Stock"] for s in SITES}
            converged_acc1_bal = {s: str(self.nodes[s].accounts["acc-1"]["Balance"]) for s in SITES}

            return {
                "step1_connected_write": {
                    "description": "Write on GCP ($250 acc-2 -> acc-3) replicated immediately to Laptop & AWS",
                    "propagation": connected_write["propagation"],
                    "digests_after_live_sync": after_connected_digests,
                    "all_converged": len(set(after_connected_digests.values())) == 1,
                },
                "step2_partitioned_writes": {
                    "description": "All 3 environments disconnected; concurrent conflicting stock orders & account transfers executed",
                    "diverged_digests": diverged_digests,
                    "diverged_p1_stock": diverged_p1_stock,
                    "diverged_acc1_balance": diverged_acc1_bal,
                    "all_diverged": len(set(diverged_digests.values())) == 3,
                },
                "step3_reconciliation": {
                    "description": "Network healed; TrueTime Recon Engine merged commutative transfers and compensated oversold stock",
                    "recon_summary": heal_result["reconciliation"],
                    "converged_digests": converged_digests,
                    "converged_p1_stock": converged_p1_stock,
                    "converged_acc1_balance": converged_acc1_bal,
                    "all_converged": len(set(converged_digests.values())) == 1,
                },
            }

    def reset_all(self) -> Dict[str, Any]:
        with self.lock:
            for node in self.nodes.values():
                node.init_seed_state()
            for pair in list(self.links.keys()):
                self.links[pair] = True
            self.recon_history = []
            return self.get_mesh_overview()

    def get_mesh_overview(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "topology": self.get_network_topology(),
                "sites": {s: self.nodes[s].snapshot_state() for s in SITES},
                "recon_history": list(reversed(self.recon_history[-10:])),
            }
