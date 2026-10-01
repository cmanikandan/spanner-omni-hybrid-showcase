-- ============================================================================
-- Spanner Omni Hybrid Multi-Cloud Showcase — Unified GoogleSQL Schema
-- Release Baseline: Spanner Omni GA 2026.r4-lts
-- Environments: Laptop (Docker), GCP (Compute Engine / GKE), AWS (EC2 / EKS)
-- ============================================================================

-- 1. PayMesh Financial Accounts (Relational + Full-Text Search)
CREATE TABLE Accounts (
  AccountId    STRING(36)  NOT NULL,
  Owner        STRING(MAX) NOT NULL,
  Region       STRING(32)  NOT NULL,
  Balance      NUMERIC     NOT NULL,
  UpdatedSite  STRING(32)  NOT NULL,
  UpdatedAt    TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp = true),
  Owner_Tokens TOKENLIST AS (TOKENIZE_FULLTEXT(Owner)) HIDDEN
) PRIMARY KEY (AccountId);

CREATE SEARCH INDEX AccountsOwnerIdx ON Accounts (Owner_Tokens);

-- 2. PayMesh Transfers Ledger (Graph Edge Source + Commit Timestamps)
CREATE TABLE Transfers (
  TransferId   STRING(36) NOT NULL,
  FromAccount  STRING(36) NOT NULL,
  ToAccount    STRING(36) NOT NULL,
  Amount       NUMERIC    NOT NULL,
  OriginSite   STRING(32) NOT NULL,
  Status       STRING(32) NOT NULL,
  CreatedAt    TIMESTAMP  NOT NULL OPTIONS (allow_commit_timestamp = true)
) PRIMARY KEY (TransferId);

-- 3. OmniRetail Customers (Parent Table for Physical Storage Interleaving)
CREATE TABLE Customers (
  CustomerId   STRING(64)  NOT NULL,
  Name         STRING(128) NOT NULL,
  Region       STRING(32)  NOT NULL,
  UpdatedSite  STRING(32)  NOT NULL,
  CreatedAt    TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp = true)
) PRIMARY KEY (CustomerId);

-- 4. OmniRetail Products (Inventory Invariant + Full-Text + Vector Embeddings)
CREATE TABLE Products (
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
) PRIMARY KEY (ProductId);

CREATE SEARCH INDEX ProductSearch ON Products (SearchTokens);

-- 5. OmniRetail Orders (Interleaved in Customers for Locality + Graph Edge)
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

-- 6. Transactional Outbox for Cross-Environment Sync & Disconnected Recon
CREATE TABLE SyncMutations (
  MutationId   STRING(64)  NOT NULL,
  OriginSite   STRING(32)  NOT NULL,
  EntityType   STRING(32)  NOT NULL,
  EntityKey    STRING(128) NOT NULL,
  Operation    STRING(32)  NOT NULL,
  PayloadJson  STRING(MAX) NOT NULL,
  SyncStatus   STRING(32)  NOT NULL,
  CommitTs     TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp = true)
) PRIMARY KEY (MutationId);

-- 7. Anti-Entropy Watermarks & Reconciliation Audit Trail
CREATE TABLE SiteSyncWatermarks (
  PeerSite          STRING(32) NOT NULL,
  LastMutationId    STRING(64),
  LastCommitTs      TIMESTAMP,
  AppliedCount      INT64      NOT NULL,
  UpdatedAt         TIMESTAMP  NOT NULL OPTIONS (allow_commit_timestamp = true)
) PRIMARY KEY (PeerSite);

CREATE TABLE ReconciliationEvents (
  ReconId           STRING(64)  NOT NULL,
  SourceSite        STRING(32)  NOT NULL,
  TargetSite        STRING(32)  NOT NULL,
  MutationId        STRING(64)  NOT NULL,
  EntityType        STRING(32)  NOT NULL,
  EntityKey         STRING(128) NOT NULL,
  ResolutionStrategy STRING(64) NOT NULL,
  Outcome           STRING(32)  NOT NULL,
  Details           STRING(MAX) NOT NULL,
  ReconciledAt      TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp = true)
) PRIMARY KEY (ReconId);

-- 8. ISO GQL Property Graphs (Financial Network & Retail Purchase Graph)
CREATE PROPERTY GRAPH PayGraph
  NODE TABLES (Accounts)
  EDGE TABLES (
    Transfers
      SOURCE KEY (FromAccount) REFERENCES Accounts (AccountId)
      DESTINATION KEY (ToAccount) REFERENCES Accounts (AccountId)
      LABEL Paid
  );

CREATE PROPERTY GRAPH RetailGraph
  NODE TABLES (
    Customers LABEL Customer PROPERTIES (CustomerId, Name, Region),
    Products  LABEL Product  PROPERTIES (ProductId, Name, PriceCents, Stock)
  )
  EDGE TABLES (
    Orders
      SOURCE KEY (CustomerId) REFERENCES Customers (CustomerId)
      DESTINATION KEY (ProductId) REFERENCES Products (ProductId)
      LABEL Purchased PROPERTIES (OrderId, Quantity, UnitPriceCents, Status, OriginSite)
  );
