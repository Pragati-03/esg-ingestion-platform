# Data Model Design — ESG Ingestion Platform

## Overview

This document describes the data model for the ESG ingestion platform, covering the reasoning behind each table, how tables relate to each other, and the tradeoffs made in favour of auditability, defensibility, and pragmatic scope.

The model supports three source types — SAP fuel/procurement (Scope 1), utility electricity (Scope 2), and corporate travel (Scope 3) — across multiple tenants, with a full analyst approval workflow and append-only audit trail.

---

## Entity Relationship Summary

```
Tenant
  └── DataSource (one per file upload)
        ├── RawRecord (one per CSV row, immutable)
        │     └── EmissionRecord (one per RawRecord, mutable by workflow)
        │           └── approved_by → User
        └── AuditLog (append-only event log, points at any entity)
```

Every significant table carries a `tenant_id` foreign key. Tenancy is enforced at the application layer via Django middleware on every queryset, and reinforced at the model layer through `PROTECT` cascades that prevent silent data loss.

---

## Tables

### Tenant

Represents a client organisation. All data in the system is scoped to a tenant.

**Key decisions:**

- UUID primary key — safe to expose in URLs without revealing record counts or insertion order.
- `slug` field enables human-readable URL scoping (`/api/acme-corp/uploads/`) without exposing internal IDs.
- `is_active` is a soft-disable flag. Deactivating a tenant suspends access without destroying historical data, which matters for contractual offboarding and audit retention obligations.
- No cascade deletes anywhere in the model. Tenant deactivation is a business decision that must be made explicitly, not triggered accidentally by an admin action.

**Tradeoff — shared schema vs schema-per-tenant:**
We use a shared PostgreSQL schema with `tenant_id` on every table. Schema-per-tenant offers stronger data isolation but adds significant migration complexity — every `makemigrations` run would need to target N schemas. For a platform at this scale, shared schema with application-layer scoping is the defensible choice.

---

### DataSource

Represents one file upload event. Groups all rows from a single import together.

**Key decisions:**

- `source_type` is an enum (`sap_fuel`, `utility`, `travel`). It drives which parser is invoked and which emission factor table applies. Adding a new source type means adding one parser class and one enum value.
- `original_filename` is stored verbatim. Analysts need to know which physical file a set of records came from, especially when disputes arise months later.
- `checksum` (SHA-256 of file contents) enforces a unique constraint per tenant. This prevents the common enterprise failure mode of a facilities team re-uploading the same quarterly export and double-counting emissions.
- `row_count` and `flagged_count` are denormalised summary fields. They are read on every upload list view and are not worth recomputing via COUNT queries on every page load. They are written once at ingestion completion and never updated after that.
- `status` tracks the ingestion job lifecycle (`pending` → `processing` → `done` / `failed`), separately from the approval status of individual records. These are distinct concerns.
- `error_message` is populated only on `status=failed`. It captures the parser's fatal error message so analysts understand why an upload produced no records.

---

### RawRecord

An immutable, verbatim copy of a single row from the source file.

**This is the audit foundation of the platform.**

Every transformation, normalisation, and flagging decision made downstream must be traceable to exactly what was received. If an analyst or external auditor disputes a CO2e figure six months later, the answer to "what did the original SAP export say for this row?" must be answerable with certainty.

**Key decisions:**

- `raw_data` is a `JSONField` (PostgreSQL JSONB). Source files have inconsistent column names across clients, SAP versions, and export configurations. Storing the full row as JSON means we never lose data because a column wasn't anticipated in the schema, and we don't need a migration every time a new client sends a differently-structured export.
- `row_number` records the 1-based position in the source file. An analyst can open the original CSV and navigate to the exact row that produced a suspicious record.
- Immutability is enforced at two levels: the model's `save()` method raises `ValueError` on any update attempt, and in production the database role used by the application should not have `UPDATE` permission on this table.
- `is_flagged` is a denormalised boolean copied from the parser's output. It exists purely to avoid a JOIN to `EmissionRecord` when counting flagged rows on the `DataSource` summary.

**What this table is not:**
It is not a staging table that gets cleaned up after processing. It is a permanent record. Raw records must outlive the emission records derived from them, which is why the FK from `EmissionRecord` to `RawRecord` uses `PROTECT`.

---

### EmissionRecord

The normalised, analyst-facing representation of one emission activity. This is the working record that moves through the approval workflow.

**The separation between RawRecord and EmissionRecord is intentional:**
`RawRecord` preserves what we received. `EmissionRecord` represents what we understood from it — after column mapping, unit conversion, scope assignment, and CO2e calculation. These are different things and must not be conflated on the same row.

**Key decisions:**

- `quantity` and `unit` store the pre-conversion value for transparency. An analyst reviewing a record should be able to see "450.5 litres" as well as the derived "1189.23 kg CO2e", and verify the calculation themselves.
- `co2e_kg` is always in kilograms, always normalised. No other unit appears in the fact table. Mixed units in a fact table are a reporting disaster.
- `emission_factor` and `emission_factor_source` are stored at calculation time, not looked up dynamically. Emission factors are updated annually (DEFRA, IEA, EPA). A record approved in January 2024 must retain the factor that was applied at that time. Retroactive factor application would silently change historical CO2e figures, which is unacceptable in an audited ESG context.
- `scope` (1, 2, or 3) is assigned deterministically by the parser based on `source_type`. SAP fuel = Scope 1, utility electricity = Scope 2, corporate travel = Scope 3. This mapping is documented and does not require analyst judgement.
- `flag_type` and `flag_reason` are stored on `EmissionRecord` rather than a separate `FlaggedRow` table. The approval queue queries flagged records constantly. Storing flag information inline avoids a JOIN on the most-read query pattern in the system. If flagging logic becomes complex enough to warrant multiple flags per record or a flag resolution history, a separate `FlagEvent` table is the natural extraction point.
- `approved_by` and `approved_at` are set once on approval or rejection and never overwritten. If a rejected record needs to be reconsidered, the correct action is to create a new `EmissionRecord`, not mutate the existing one.
- `analyst_note` is required on rejection, optional on approval. This asymmetry is deliberate: a rejection without a documented reason is not defensible in an ESG audit.

**Check constraints (database-level):**
- `co2e_kg >= 0` — negative emissions are not physically possible in this model.
- `scope IN (1, 2, 3)` — enforces GHG Protocol scope values at the DB layer, not just application layer.

---

### AuditLog

An append-only log of every significant action in the system.

ESG data is submitted to regulators, boards, and third-party verifiers. The question "who changed this, and when, and from what to what?" must be answerable with certainty. The audit log is that certainty.

**Key decisions:**

- Append-only: `save()` raises `ValueError` on any update attempt. In production, the application DB role should not have `UPDATE` or `DELETE` permission on this table.
- `actor` uses `SET_NULL` on user deletion, not `CASCADE`. The audit record of an action must survive the deletion of the user who performed it. `actor_email_snapshot` preserves the actor's email at the time of the event so the record remains human-readable even after the user account is gone.
- `GenericForeignKey` (via Django's `ContentType` framework) allows a single audit log table to reference any model — `DataSource`, `EmissionRecord`, `Tenant` — without separate FK columns per type. The tradeoff is that referential integrity on `object_id` is not enforced at the DB level. This is acceptable: audit events should outlive the objects they describe.
- `delta` is a `JSONField` storing `{"before": {...}, "after": {...}}`. This is the most useful format for an auditor: they see exactly what changed, not just that a change occurred. A log entry that says "status changed" is substantially less useful than one that says "status changed from `pending_review` to `approved`".
- `ip_address` is captured from the request context and stored for security investigations.

---

## Normalization Strategy

The model is intentionally partially denormalised in specific, documented places:

| Denormalisation | Location | Reason |
|---|---|---|
| `tenant_id` on `RawRecord` | Avoids JOIN through `DataSource` on every tenancy-scoped query |
| `source_type` on `EmissionRecord` | Dashboard filters by source type constantly; avoids JOIN back to `DataSource` |
| `row_count`, `flagged_count` on `DataSource` | Read on every uploads list view; recomputing via COUNT is wasteful |
| `is_flagged` on `RawRecord` | Avoids JOIN to `EmissionRecord` for upload summary counts |
| `actor_email_snapshot` on `AuditLog` | Audit trail survives user deletion |

Every other field is in its natural home. The denormalisations are additive — the source-of-truth fields still exist in their canonical location.

---

## Multi-Tenancy

Tenancy is enforced through three layers:

**1. URL scoping** — all API routes are prefixed with `/api/{tenant_slug}/`. A request to a tenant's data must include the correct slug.

**2. Application middleware** — `TenantMixin` resolves the tenant from the URL slug and attaches it to the request. Every view inheriting from `TenantMixin` has `self.tenant` available without additional lookups.

**3. Queryset filtering** — every queryset in the system includes `.filter(tenant=self.tenant)`. This is the last line of defence. A misconfigured view that skips URL scoping still cannot return cross-tenant data if the queryset filter is applied correctly.

**What is not implemented:**
Row-level security at the PostgreSQL layer. This would add meaningful protection but also significant complexity — every connection would need a session variable set, and Django's ORM doesn't support this natively. The application-layer enforcement described above is appropriate for this scale and is auditable in code review.

---

## Auditability

The platform maintains auditability through four mechanisms:

**1. Immutable raw records** — `RawRecord` is written once and never modified. The original source data is always available for comparison against derived records.

**2. Emission factor provenance** — `EmissionRecord` stores the exact factor value and its source at calculation time. The CO2e figure for any record can be reconstructed and verified independently.

**3. Approval attribution** — every approval and rejection records the analyst (`approved_by`), the timestamp (`approved_at`), and a note (`analyst_note`). Rejections require a minimum-length note by API validation.

**4. Append-only event log** — `AuditLog` captures every upload, ingestion completion, flag event, approval, and rejection with before/after state. The log cannot be modified or deleted through the application layer.

---

## Source Tracking

Every `EmissionRecord` carries a complete provenance chain:

```
EmissionRecord
  └── raw_record → RawRecord (verbatim source row)
        └── data_source → DataSource (upload event)
              └── tenant → Tenant (client organisation)
```

This chain is navigable in both directions. Given an `EmissionRecord`, you can retrieve the exact CSV row that produced it. Given a `DataSource`, you can retrieve every raw row and every derived emission record.

All foreign keys in this chain use `on_delete=PROTECT`. No record in the chain can be deleted while records downstream of it exist. This is intentional: silent cascade deletion of source data is not acceptable in a compliance context.

---

## Approval Workflow

The approval workflow is a simple state machine on `EmissionRecord.status`:

```
                    ┌─────────────────┐
                    │  pending_review │  ← set at ingestion
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     [analyst approves] [analyst rejects] [validation flags]
              │              │              │
              ▼              ▼              ▼
         approved        rejected        flagged
                                            │
                              ┌─────────────┴──────────────┐
                              │                            │
                    [analyst reviews + approves]  [analyst reviews + rejects]
                              │                            │
                              ▼                            ▼
                          approved                     rejected
```

**Design decisions:**

- The system never auto-approves. Validation moves records to `flagged`; only a human analyst moves records to `approved`.
- `approved` → `rejected` is not permitted through the UI. If an approved record is later found to be incorrect, a new `EmissionRecord` is created (from a corrected re-upload), not the existing one mutated. This preserves the integrity of the approval record.
- Bulk approve exists for the common case: a monthly SAP upload with 300 rows, 290 of which are clean. Requiring 290 individual API calls is not a viable analyst workflow.
- Flagged records are excluded from bulk approve. They require individual review by design.

---

## Index Strategy

Indexes are added only where a named query pattern justifies them:

| Index | Query it serves |
|---|---|
| `(tenant, status)` on `EmissionRecord` | Approval queue — most-read query in the system |
| `(tenant, scope, activity_date)` on `EmissionRecord` | Scope reporting with date range filters |
| `(tenant, source_type)` on `EmissionRecord` | Dashboard source breakdown |
| `(tenant, status)` on `DataSource` | Upload list filtered by status |
| `(tenant, data_source)` on `RawRecord` | Fetch all rows for a given upload |
| `(content_type, object_id)` on `AuditLog` | All events for a specific record |
| `(tenant, created_at)` on `AuditLog` | Time-ordered audit trail per tenant |

No speculative indexes. Every index adds write overhead; each one here has a specific, documented justification.

---

## Known Limitations and Extension Points

| Limitation | Extension |
|---|---|
| Single emission factor per record | Add `EmissionFactorVersion` model with effective date ranges |
| No multi-stage approval | Add `ApprovalStage` model; `EmissionRecord` tracks current stage |
| No per-tenant factor configuration | Add `TenantEmissionFactor` override table |
| Shared schema tenancy | Migrate to schema-per-tenant using `django-tenants` if isolation requirements increase |
| No soft-delete on `EmissionRecord` | Add `is_deleted` + `deleted_at` if records need to be hidden without removal |
| No versioning on `EmissionRecord` | Add `EmissionRecordVersion` for full change history if regulatory requirements demand it |
