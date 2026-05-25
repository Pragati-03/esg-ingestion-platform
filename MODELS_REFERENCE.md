# Breathe ESG — Django Models Reference

## File Locations

```
apps/
├── tenants/
│   └── models.py           → Tenant
├── ingestion/
│   └── models/
│       ├── __init__.py
│       ├── data_source.py  → DataSource, SourceType, IngestionStatus
│       └── raw_record.py   → RawRecord
├── emissions/
│   └── models.py           → EmissionRecord, GHGScope, ApprovalStatus, FlagType
└── audit/
    └── models.py           → AuditLog, EventType
```

---

## Relationship Map

```
Tenant ──────────────────────────────────────────────────────┐
  │                                                           │
  ├── DataSource (many)                                       │
  │     │                                                     │
  │     ├── RawRecord (many)  ──────────────────────────┐    │
  │     │                                               │    │
  │     └── EmissionRecord (many) ←── raw_record FK ───┘    │
  │               │                                          │
  │               └── approved_by → User                     │
  │                                                          │
  └── AuditLog (many) → [any model via GenericForeignKey] ───┘
```

### FK Cascade Choices — Why Each One

| Relationship | on_delete | Rationale |
|---|---|---|
| DataSource → Tenant | PROTECT | Cannot delete a tenant with uploaded data |
| RawRecord → DataSource | PROTECT | Cannot delete an upload that has raw records |
| RawRecord → Tenant | PROTECT | Raw records must outlive all workflow changes |
| EmissionRecord → RawRecord | PROTECT | Normalised record must trace to its source |
| EmissionRecord → Tenant | PROTECT | Same — no orphaned emission data |
| EmissionRecord.approved_by → User | SET_NULL | Preserve record if analyst account deleted |
| AuditLog.actor → User | SET_NULL | Preserve audit event if user is deleted |
| AuditLog → Tenant | PROTECT | Audit trail must not be silently removed |

**Why PROTECT everywhere sensitive?**
Django's default CASCADE is dangerous for financial/compliance data. A misconfigured
admin action deleting a Tenant could silently cascade to thousands of records.
PROTECT raises a ProtectedError, forcing an explicit decision at every level.

---

## Table-by-Table Reference

### `tenants` — Tenant

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | Safe to expose in URLs |
| name | VARCHAR(255) | Display name |
| slug | SLUG unique | URL-safe identifier |
| is_active | BOOL | Soft disable |
| created_at | TIMESTAMP | Auto |

**Indexes:** `slug` (unique, implicit). No composite needed — tenant is always
looked up by slug or PK.

---

### `data_sources` — DataSource

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID FK | Tenancy scope |
| uploaded_by_id | INT FK | Nullable — user may be deleted |
| source_type | VARCHAR(20) | `sap_fuel` / `utility` / `travel` |
| original_filename | VARCHAR(500) | For display and audit |
| file | FileField | Stored path, not bytes |
| checksum | VARCHAR(64) | SHA-256 — prevents re-ingestion |
| status | VARCHAR(20) | `pending` / `processing` / `done` / `failed` |
| row_count | INT | Denormalised summary |
| flagged_count | INT | Denormalised summary |
| error_message | TEXT | Populated on status=failed |
| created_at | TIMESTAMP | Auto |
| completed_at | TIMESTAMP | Nullable |

**Indexes:**
- `(tenant, status)` — approval dashboard: "show me all pending uploads for this tenant"
- `(tenant, source_type)` — source-type breakdown in dashboard

**Unique constraint:** `(tenant, checksum)` where checksum is non-empty — prevents
double-ingestion of the same file by the same client.

---

### `raw_records` — RawRecord

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| data_source_id | UUID FK | Parent upload |
| tenant_id | UUID FK | Tenancy scope (denorm for fast queries) |
| row_number | INT | 1-based position in source file |
| raw_data | JSONB | Verbatim row — never modified |
| is_flagged | BOOL | Fast lookup — avoids JOIN to EmissionRecord |
| ingested_at | TIMESTAMP | Auto |

**Indexes:**
- `(tenant, data_source)` — fetch all rows for a given upload
- `(tenant, is_flagged)` — flag summary queries

**Unique constraint:** `(data_source, row_number)` — guarantees each row in an
upload is stored exactly once. Protects against double-processing bugs.

**Immutability:** `save()` raises `ValueError` on update. This is belt-and-
suspenders. In production, the DB role used by the app should not have UPDATE
permission on this table.

---

### `emission_records` — EmissionRecord

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| raw_record_id | UUID FK | Source row traceability |
| data_source_id | UUID FK | Denorm for fast filtering |
| tenant_id | UUID FK | Tenancy scope |
| source_type | VARCHAR(20) | Denorm from DataSource |
| activity_date | DATE | When the emission activity occurred |
| description | VARCHAR(500) | Human-readable activity label |
| quantity | DECIMAL(15,4) | Pre-conversion value |
| unit | VARCHAR(50) | Original unit (`litres`, `kWh`, `km`) |
| co2e_kg | DECIMAL(15,4) | Normalised CO2e — always kg |
| scope | SMALLINT | 1, 2, or 3 |
| emission_factor | DECIMAL(15,6) | Factor used in calculation |
| emission_factor_source | VARCHAR(200) | e.g. 'DEFRA 2023 — Natural Gas' |
| status | VARCHAR(20) | Approval workflow state |
| flag_type | VARCHAR(30) | Nullable — type of flag |
| flag_reason | TEXT | Nullable — explanation |
| approved_by_id | INT FK | Nullable — set on approval/rejection |
| approved_at | TIMESTAMP | Nullable |
| analyst_note | TEXT | Analyst sign-off comment |
| created_at | TIMESTAMP | Auto |
| updated_at | TIMESTAMP | Auto |

**Indexes:**
- `(tenant, status)` — approval queue: most-read query in the system
- `(tenant, scope, activity_date)` — scope reporting with date range
- `(tenant, source_type)` — source breakdown
- `(tenant, activity_date)` — dashboard time-series

**Check constraints:**
- `co2e_kg >= 0` — physically impossible to have negative emissions (in this model)
- `scope IN (1, 2, 3)` — enforces GHG Protocol scopes at DB level

---

### `audit_logs` — AuditLog

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID FK | Nullable for system events |
| actor_id | INT FK | SET_NULL on user delete |
| actor_email_snapshot | EMAIL | Preserved after user deletion |
| event_type | VARCHAR(50) | Controlled vocabulary |
| content_type_id | INT FK | Points to Django ContentType |
| object_id | UUID | ID of the affected record |
| delta | JSONB | `{"before": {...}, "after": {...}}` |
| description | TEXT | Human-readable summary |
| ip_address | INET | Request context |
| created_at | TIMESTAMP | Auto |

**Indexes:**
- `(tenant, event_type)` — "show me all approvals for this tenant"
- `(tenant, created_at)` — time-ordered audit trail
- `(content_type, object_id)` — "show me all events for EmissionRecord X"
- `(actor)` — "show me all actions by this analyst"

**Append-only:** `save()` raises `ValueError` on update.

---

## Enum Reference

### SourceType
```python
SAP_FUEL  = "sap_fuel"   # Scope 1 — fuel/energy procurement
UTILITY   = "utility"    # Scope 2 — purchased electricity
TRAVEL    = "travel"     # Scope 3 — business travel
```

### ApprovalStatus (EmissionRecord.status)
```
pending_review  →  approved       # analyst approves clean record
pending_review  →  rejected       # analyst rejects
pending_review  →  flagged        # system flags during ingestion
flagged         →  approved       # analyst reviews flag, accepts
flagged         →  rejected       # analyst reviews flag, rejects
```

### GHGScope
```
1 = Direct combustion (SAP fuel/procurement)
2 = Purchased energy (utility electricity)
3 = Value chain (corporate travel)
```

### FlagType
```
missing_value   — quantity or date is null/empty
out_of_range    — value is negative or >3σ from column mean
unknown_unit    — unit string not in lookup table
future_date     — activity_date is after today
duplicate       — row appears to duplicate an existing record
```

---

## Key Design Decisions — Summary

| Decision | Why |
|---|---|
| UUID PKs on all models | Safe to expose; no guessable sequence |
| PROTECT on all safety-critical FKs | Prevents silent cascade data loss |
| Raw data in JSONB, not typed columns | Schema-resilient across source file variations |
| EmissionRecord stores pre-AND post-conversion | Auditor can verify every calculation |
| Emission factor recorded per-record | Factors change; each record captures the factor it used |
| Audit log uses GenericForeignKey | Single log table works across all domains |
| `delta` field as JSON before/after | More useful than a plain "changed" flag |
| Immutability enforced in save() | Belt-and-suspenders; DB role restriction is the real guard |
| Denormalised `tenant` on RawRecord | Avoids JOIN through DataSource on every tenancy check |
| `actor_email_snapshot` on AuditLog | Audit trail survives user deletion |
