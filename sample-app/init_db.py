#!/usr/bin/env python3
"""Create the PayMesh + OmniRetail schema and seed data on any Spanner Omni endpoint (sample-app/init_db.py).

Can be run directly against a live Spanner Omni endpoint (via OMNI_ENDPOINT) or in
multi-environment mode across Laptop (15000), GCP (25000), and AWS (35000).
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

# Allow importing shared helpers from parent showcase root when run from sample-app/
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

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

ENDPOINT = os.environ.get("OMNI_ENDPOINT", "127.0.0.1:15000")
DATABASE = os.environ.get("OMNI_DATABASE", "paymesh")
SITE = os.environ.get("OMNI_SITE", "laptop")

DDL = [
    """CREATE TABLE Accounts (
         AccountId    STRING(36)  NOT NULL,
         Owner        STRING(MAX) NOT NULL,
         Region       STRING(32)  NOT NULL,
         Balance      NUMERIC     NOT NULL,
         UpdatedSite  STRING(32)  NOT NULL,
         UpdatedAt    TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp = true),
         Owner_Tokens TOKENLIST AS (TOKENIZE_FULLTEXT(Owner)) HIDDEN
       ) PRIMARY KEY (AccountId)""",
    "CREATE SEARCH INDEX AccountsOwnerIdx ON Accounts (Owner_Tokens)",
    """CREATE TABLE Transfers (
         TransferId   STRING(36) NOT NULL,
         FromAccount  STRING(36) NOT NULL,
         ToAccount    STRING(36) NOT NULL,
         Amount       NUMERIC    NOT NULL,
         OriginSite   STRING(32) NOT NULL,
         Status       STRING(32) NOT NULL,
         CreatedAt    TIMESTAMP  NOT NULL OPTIONS (allow_commit_timestamp = true)
       ) PRIMARY KEY (TransferId)""",
    """CREATE TABLE Customers (
         CustomerId   STRING(64)  NOT NULL,
         Name         STRING(128) NOT NULL,
         Region       STRING(32)  NOT NULL,
         UpdatedSite  STRING(32)  NOT NULL,
         CreatedAt    TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp = true)
       ) PRIMARY KEY (CustomerId)""",
    """CREATE TABLE Products (
         ProductId    STRING(64)  NOT NULL,
         Name         STRING(200) NOT NULL,
         Description  STRING(MAX) NOT NULL,
         PriceCents   INT64       NOT NULL,
         InitialStock INT64       NOT NULL,
         Stock        INT64       NOT NULL,
         Embedding    ARRAY<FLOAT64>,
         UpdatedSite  STRING(32)  NOT NULL,
         SearchTokens TOKENLIST AS (TOKENIZE_FULLTEXT(CONCAT(Name, ' ', Description))) HIDDEN,
         CONSTRAINT StockNonnegative CHECK (Stock >= 0),
         CONSTRAINT PricePositive CHECK (PriceCents > 0)
       ) PRIMARY KEY (ProductId)""",
    "CREATE SEARCH INDEX ProductSearch ON Products (SearchTokens)",
    """CREATE TABLE Orders (
         CustomerId     STRING(64) NOT NULL,
         OrderId        STRING(64) NOT NULL,
         ProductId      STRING(64) NOT NULL,
         Quantity       INT64      NOT NULL,
         UnitPriceCents INT64      NOT NULL,
         Status         STRING(32) NOT NULL,
         OriginSite     STRING(32) NOT NULL,
         CommitTs       TIMESTAMP  NOT NULL OPTIONS (allow_commit_timestamp = true)
       ) PRIMARY KEY (CustomerId, OrderId),
         INTERLEAVE IN PARENT Customers ON DELETE CASCADE""",
    """CREATE TABLE SyncMutations (
         MutationId   STRING(64)  NOT NULL,
         OriginSite   STRING(32)  NOT NULL,
         EntityType   STRING(32)  NOT NULL,
         EntityKey    STRING(128) NOT NULL,
         Operation    STRING(32)  NOT NULL,
         PayloadJson  STRING(MAX) NOT NULL,
         SyncStatus   STRING(32)  NOT NULL,
         CommitTs     TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp = true)
       ) PRIMARY KEY (MutationId)""",
    """CREATE PROPERTY GRAPH PayGraph
         NODE TABLES (Accounts)
         EDGE TABLES (
           Transfers
             SOURCE KEY (FromAccount) REFERENCES Accounts (AccountId)
             DESTINATION KEY (ToAccount) REFERENCES Accounts (AccountId)
             LABEL Paid
         )""",
    """CREATE PROPERTY GRAPH RetailGraph
         NODE TABLES (
           Customers LABEL Customer PROPERTIES (CustomerId, Name, Region),
           Products  LABEL Product  PROPERTIES (ProductId, Name, PriceCents, Stock)
         )
         EDGE TABLES (
           Orders
             SOURCE KEY (CustomerId) REFERENCES Customers (CustomerId)
             DESTINATION KEY (ProductId) REFERENCES Products (ProductId)
             LABEL Purchased PROPERTIES (OrderId, Quantity, UnitPriceCents, Status, OriginSite)
         )""",
]


def init_endpoint(site: str, endpoint: str, database: str) -> None:
    if HAS_SPANNER_SDK and _is_tcp_reachable(endpoint):
        from google.cloud import spanner

        client = create_omni_spanner_client(endpoint)
        db = client.instance("default").database(database)
        db.update_ddl(DDL).result(300)
        with db.batch() as batch:
            batch.insert_or_update(
                "Accounts",
                ("AccountId", "Owner", "Region", "Balance", "UpdatedSite", "UpdatedAt"),
                [(a, o, r, b, site, spanner.COMMIT_TIMESTAMP) for a, o, r, b in SEED_ACCOUNTS],
            )
            batch.insert_or_update(
                "Customers",
                ("CustomerId", "Name", "Region", "UpdatedSite", "CreatedAt"),
                [(c, n, r, site, spanner.COMMIT_TIMESTAMP) for c, n, r in SEED_CUSTOMERS],
            )
            batch.insert_or_update(
                "Products",
                ("ProductId", "Name", "Description", "PriceCents", "InitialStock", "Stock", "Embedding", "UpdatedSite"),
                [(p, n, d, pr, init_s, s, emb, site) for p, n, d, pr, init_s, s, emb in SEED_PRODUCTS],
            )
            batch.insert_or_update(
                "Orders",
                ("CustomerId", "OrderId", "ProductId", "Quantity", "UnitPriceCents", "Status", "OriginSite", "CommitTs"),
                [(c, o, p, q, pr, st, orig, spanner.COMMIT_TIMESTAMP) for c, o, p, q, pr, st, orig in SEED_ORDERS],
            )
            batch.insert_or_update(
                "Transfers",
                ("TransferId", "FromAccount", "ToAccount", "Amount", "OriginSite", "Status", "CreatedAt"),
                [(t, src, dst, amt, orig, st, spanner.COMMIT_TIMESTAMP) for t, src, dst, amt, orig, st in SEED_TRANSFERS],
            )
        print(
            f"[+] Live Spanner Omni schema and {len(SEED_ACCOUNTS)} accounts + {len(SEED_PRODUCTS)} products "
            f"ready in '{database}' at {endpoint} ({site})"
        )
    else:
        node = SiteNodeEngine(site=site, endpoint=endpoint, database_name=database)
        node.init_seed_state()
        print(
            f"[+] Initialized replica state for '{database}' at {endpoint} ({site}) "
            f"[digest={node.compute_state_digest()}]"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize PayMesh + OmniRetail schema and seed data")
    parser.add_argument("--site", default=SITE, help="Target site label (laptop, gcp, aws)")
    parser.add_argument("--endpoint", default=ENDPOINT, help="Spanner Omni gRPC endpoint")
    parser.add_argument("--database", default=DATABASE, help="Spanner Omni database name")
    parser.add_argument(
        "--all-sites",
        action="store_true",
        help="Initialize all three environments (laptop:15000, gcp:25000, aws:35000)",
    )
    args = parser.parse_args()

    if args.all_sites:
        for s, ep in [("laptop", "127.0.0.1:15000"), ("gcp", "127.0.0.1:25000"), ("aws", "127.0.0.1:35000")]:
            init_endpoint(s, ep, args.database)
    else:
        init_endpoint(args.site, args.endpoint, args.database)
    return 0


if __name__ == "__main__":
    sys.exit(main())
