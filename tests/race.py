#!/usr/bin/env python3
"""Live Concurrency, Idempotency & Cross-Cloud Sync Acceptance Test (tests/race.py).

Creates a uniquely named product with 10 units on the selected site, then sends
30 concurrent purchase attempts across 12 worker threads. Verifies:
  1. Exactly 10 orders succeed (200 OK)
  2. Exactly 20 attempts are rejected as SOLD_OUT (409 Conflict)
  3. Replaying a committed order_id with the identical payload succeeds idempotently
  4. Reusing a committed order_id with a different payload is rejected (409 Conflict)
  5. Stock invariant holds across all connected Spanner Omni environments
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import sys
import time
import uuid

import httpx


def run_race(base_url: str, site: str = "laptop", workers: int = 12, attempts: int = 30) -> int:
    product_id = f"race-{uuid.uuid4().hex[:8]}"
    initial_stock = 10

    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        # 1. Create the 10-unit test product
        create_res = client.post(
            f"/api/site/{site}/products",
            json={
                "product_id": product_id,
                "name": f"Race Test Product {product_id}",
                "description": "Concurrency and inventory invariant test item",
                "price_cents": 5000,
                "initial_stock": initial_stock,
            },
        )
        create_res.raise_for_status()

    latencies_ms = []
    accepted_orders = []
    sold_out_count = 0
    unexpected_errors = []

    def attempt_purchase(idx: int):
        order_id = f"ord-{product_id}-{idx}"
        t0 = time.perf_counter()
        with httpx.Client(base_url=base_url, timeout=15.0) as c:
            resp = c.post(
                f"/api/site/{site}/checkout",
                json={
                    "customer_id": "cust-asha",
                    "product_id": product_id,
                    "quantity": 1,
                    "order_id": order_id,
                },
            )
        dt_ms = (time.perf_counter() - t0) * 1000.0
        return idx, order_id, resp.status_code, resp.json(), dt_ms

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(attempt_purchase, i) for i in range(attempts)]
        for fut in concurrent.futures.as_completed(futures):
            idx, oid, status, body, dt_ms = fut.result()
            latencies_ms.append(dt_ms)
            if status == 200:
                accepted_orders.append(oid)
            elif status == 409 and "SOLD_OUT" in json.dumps(body):
                sold_out_count += 1
            else:
                unexpected_errors.append((idx, status, body))

    # Test idempotent duplicate replay of the first accepted order
    replay_safe = False
    payload_conflict_rejected = False
    if accepted_orders:
        winner_oid = accepted_orders[0]
        with httpx.Client(base_url=base_url, timeout=15.0) as client:
            replay_res = client.post(
                f"/api/site/{site}/checkout",
                json={
                    "customer_id": "cust-asha",
                    "product_id": product_id,
                    "quantity": 1,
                    "order_id": winner_oid,
                },
            )
            replay_safe = (
                replay_res.status_code == 200
                and replay_res.json().get("idempotent_replay") is True
            )

            conflict_res = client.post(
                f"/api/site/{site}/checkout",
                json={
                    "customer_id": "cust-ben",
                    "product_id": product_id,
                    "quantity": 2,
                    "order_id": winner_oid,
                },
            )
            payload_conflict_rejected = conflict_res.status_code == 409

            verify_res = client.get(f"/api/site/{site}/verify").json()

    latencies_ms.sort()
    p50 = round(statistics.median(latencies_ms), 2) if latencies_ms else 0.0
    p95_idx = min(len(latencies_ms) - 1, int(len(latencies_ms) * 0.95))
    p95 = round(latencies_ms[p95_idx], 2) if latencies_ms else 0.0

    summary = {
        "site": site,
        "product_id": product_id,
        "accepted": len(accepted_orders),
        "sold_out": sold_out_count,
        "unexpected_errors": len(unexpected_errors),
        "replay_safe": replay_safe,
        "payload_conflict_rejected": payload_conflict_rejected,
        "invariants_valid": verify_res.get("valid", False),
        "latency_p50_ms": p50,
        "latency_p95_ms": p95,
    }
    print(json.dumps(summary, indent=2))

    passed = (
        len(accepted_orders) == initial_stock
        and sold_out_count == (attempts - initial_stock)
        and len(unexpected_errors) == 0
        and replay_safe
        and payload_conflict_rejected
        and verify_res.get("valid", False)
    )
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Live concurrency & idempotency test")
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="Base URL of the running app")
    parser.add_argument("--site", default="laptop", choices=["laptop", "gcp", "aws"])
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--attempts", type=int, default=30)
    args = parser.parse_args()
    return run_race(args.url, args.site, args.workers, args.attempts)


if __name__ == "__main__":
    sys.exit(main())
