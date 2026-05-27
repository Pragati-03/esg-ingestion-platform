# Deliberate Tradeoffs — ESG Ingestion Platform

This document explains three things that were consciously not built, why they were excluded, and what building them would actually require. The goal is to demonstrate that these are prioritisation decisions, not oversights.

A 4-day build cannot be everything. The question is not "what could be added?" — the answer is always "everything." The question is "what does the core problem actually require?" and "what creates defensible scope boundaries?"

---

## 1. Asynchronous Task Queue (Celery + Redis)

### What was built instead

Ingestion runs synchronously inside the Django request-response cycle. When a file is uploaded, the view calls `ingest_data_source()` directly, waits for it to complete, and returns the result. For files under ~10,000 rows — the realistic upper bound for a quarterly batch export — this completes in under 3 seconds.

### Why it was excluded

Celery introduces four distinct infrastructure components that each require configuration, monitoring, and failure handling: a message broker (Redis or RabbitMQ), one or more worker processes, a result backend, and a beat scheduler if periodic tasks are needed. Each of these is a new failure mode.

In a 4-day build, the cost of that infrastructure is disproportionate to the benefit. The ingestion service is already written as a standalone function that takes a `DataSource` and an actor and returns a result. Converting it to a Celery task at the call site is a one-line change:

```python
# Synchronous (current)
data_source = ingest_data_source(data_source, actor=request.user)

# Async (future)
ingest_data_source.delay(data_source.id, actor_id=request.user.id)
```

The architecture was designed to make this easy. The service has no HTTP context dependency, no request object, no response object. It is already task-shaped.

### What building it properly would require

Beyond the infrastructure, async ingestion changes the user-facing contract significantly. The upload endpoint can no longer return the ingestion result — it returns a job ID. The frontend needs a polling mechanism or a WebSocket connection to receive completion status. The upload page needs a "processing" state and an error recovery path for jobs that fail after the HTTP response has already been sent. None of this is difficult, but it is a substantial amount of additional surface area for a prototype whose primary goal is demonstrating the ingestion pipeline.

### The honest scope boundary

If the platform needs to handle files with more than 50,000 rows, or if uploads need to be non-blocking for a busy analyst interface, async ingestion is not optional. The decision to build synchronous first was made knowing this. It is documented, it is reversible, and the code is structured to make the reversal straightforward.

---

## 2. Role-Based Access Control (RBAC)

### What was built instead

All API endpoints require authentication via `IsAuthenticated`. Any authenticated user can upload files, view records, and approve or reject records. There is no distinction between an uploader, an analyst, and an administrator at the permission layer.

The data model does record who approved each record (`approved_by`) and who uploaded each file (`uploaded_by`), so the attribution chain is intact. The gap is enforcement — nothing prevents an uploader from approving their own submission.

### Why it was excluded

A defensible RBAC system for a multi-tenant ESG platform has three distinct concerns that compound in complexity when combined:

**Role definition:** What roles exist? Uploader, Analyst, Reviewer, Tenant Admin, Platform Admin? Do roles differ per tenant? Can a user be an analyst for one tenant and read-only for another?

**Permission enforcement:** Django's built-in permission system works at the model level (`can_add`, `can_change`, `can_delete`). A workflow-based system — "analysts can approve, but cannot approve records they uploaded" — requires custom permission classes and object-level checks that go beyond what Django provides out of the box. `django-guardian` handles object-level permissions but adds a dependency and a non-trivial integration surface.

**Tenant-scoped role assignment:** In a multi-tenant system, roles must be scoped to tenants. A `TenantMembership` join table (user × tenant × role) is needed, with a management interface to assign and revoke roles.

Building this correctly in 4 days would have consumed approximately one full day — time that would have come directly from the ingestion pipeline, which is the core of the assignment.

### What building it properly would require

At minimum: a `TenantMembership` model, a custom `BasePermission` subclass per sensitive action, object-level checks on the approval endpoints to prevent self-approval, and a minimal admin interface for role assignment. The frontend would also need to conditionally render actions based on the current user's role — the approve/reject buttons should not appear for users who lack permission.

### The honest scope boundary

The approval workflow records attribution correctly. The missing piece is enforcement. In a single-tenant pilot with a trusted team, the absence of RBAC is a known and acceptable risk. In a multi-tenant production system with external clients, it is not. The `approved_by` field on `EmissionRecord` and the `uploaded_by` field on `DataSource` provide the data needed to enforce a self-approval rule when permissions are added — no schema changes required.

---

## 3. Emission Factor Versioning

### What was built instead

Emission factors are stored as constants in the parser files (`sap_constants.py`, `utility_constants.py`, `travel_constants.py`). Each `EmissionRecord` stores the factor value and its source string at calculation time:

```python
emission_factor        = 2.6391
emission_factor_source = "DEFRA 2023 — Liquid fuels"
```

This means the factor applied to a specific record is always retrievable. A historical record approved in January 2024 will always show the factor that was used to compute its CO2e, regardless of what the current factors are.

### Why it was excluded

Proper emission factor versioning is a product problem as much as an engineering problem, and it has two distinct sub-problems:

**Factor management:** DEFRA publishes updated conversion factors annually, typically in June. IEA publishes grid intensity data with an 18-month lag. A versioned factor database needs an update process, a publication date, an effective date range, and a source reference. Someone needs to own that update process — it is not automatic.

**Historical re-calculation:** When new factors are published, does the platform re-calculate CO2e for previously approved records? This is a contested question in ESG reporting. Some frameworks require re-stating prior years when methodology changes. Others permit a clear break with prior methodology documented. If re-calculation is required, the platform needs a job that finds all approved records using a superseded factor version, re-computes CO2e, sets them back to `pending_review`, and notifies the analyst team. That is a significant workflow with significant UI implications.

Building a `EmissionFactor` model with `valid_from` and `valid_to` date fields is straightforward. Building the re-calculation workflow and the product decisions around it is not.

### What building it properly would require

A minimum viable versioned factor system needs: an `EmissionFactor` model (fuel key, factor value, unit, scope, valid from, valid to, source, created by), a management interface or fixtures-based update process, a lookup function in the parsers that queries the DB for the factor valid at the `activity_date` of each record, and a migration for existing constants into the new table. The re-calculation feature would require an additional background job, analyst notification, and a UI state for "re-calculation pending."

The `emission_factor_source` string on `EmissionRecord` was designed to make this addition non-breaking. When a versioned `EmissionFactor` model is added, the source string can be replaced with a FK to that model. Records created before the migration retain their string value; records created after point to a versioned factor row. No historical data is lost either way.

### The honest scope boundary

Storing the factor value and source at calculation time is the minimum viable approach to factor auditability. It answers "what factor was used for this record?" reliably. It does not answer "is this factor still current?" or "what would this record's CO2e be under 2024 factors?" Those are important questions for a production platform, and the architecture leaves room for them. They are not essential for demonstrating that the ingestion and approval pipeline works correctly.

---

## Summary

| Omission | What it would require | Why deferred |
|---|---|---|
| Async task queue | Celery, Redis, result backend, frontend polling, failure recovery | Service is already task-shaped; one-line change to add; not needed at prototype file sizes |
| Role-based access control | TenantMembership model, custom permission classes, object-level enforcement, frontend conditional rendering | Attribution is recorded; enforcement is missing; acceptable risk for a trusted pilot team |
| Emission factor versioning | EmissionFactor model, DB-backed lookup, re-calculation job, analyst notification | Factor value is stored per-record today; versioning is a product decision as much as an engineering one; architecture leaves a clean extension point |

Each of these omissions was made with a specific condition under which it becomes non-negotiable. Async ingestion becomes mandatory above ~50,000 rows or when the analyst interface needs to be non-blocking. RBAC becomes mandatory before external clients access each other's tenants. Factor versioning becomes mandatory when a regulatory framework requires restating prior years. None of those conditions apply to a 4-day prototype. All of them should be on the roadmap for production.
