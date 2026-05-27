# ESG Ingestion Platform

A Django REST Framework backend and React frontend for ingesting, normalising, and reviewing ESG emissions data from enterprise source systems.

Built as a 4-day technical assignment for Breathe ESG. The focus was on realistic enterprise assumptions, a defensible data model, and a working analyst review workflow — not on feature breadth.

---

## What It Does

The platform accepts CSV exports from three source systems, parses and normalises each into GHG-scoped emission records, flags suspicious rows, and presents a review queue where analysts can approve or reject records before they are included in reporting.

Every source row is stored verbatim and immutably before any transformation is applied. Every approval, rejection, and flag event is written to an append-only audit log. The CO2e figure on any record can be traced back to the exact source row that produced it, the emission factor applied, and the analyst who signed it off.

---

## Supported Data Sources

**SAP Fuel / Procurement (Scope 1)**
Flat-file CSV exports from SAP ECC or S4HANA procurement transactions (MB51, ME2M). Handles German column headers, mixed date formats, locale-specific decimal separators, and unit variants (`L`, `Liter`, `m3`, `m³`, `KG`).

**Utility Electricity (Scope 2)**
CSV exports from utility supplier portals (E.ON, Vattenfall, British Gas, and equivalents). Handles non-calendar billing periods, overlapping period detection, duplicate invoice detection, and negative kWh credit notes.

**Corporate Travel (Scope 3)**
CSV exports from Concur or Navan expense systems. Handles flights (with airport code to distance lookup), hotels (per room-night), rail, and taxi. Cabin class is used to select the correct DEFRA emission factor for flights.

---

## Core Features

**Ingestion pipeline**
- Column alias resolution handles variant header names across source systems
- Unit normalisation maps all variants to a canonical form before factor application
- Emission factors sourced from DEFRA 2023 and IEA 2023, stored at calculation time per record
- Synchronous processing is used intentionally — realistic quarterly exports are 200–5,000 rows and complete in under 3 seconds

**Validation and flagging**
- Parser-level validation catches format problems: missing fields, unparseable dates, unknown units
- Semantic validation runs after ingestion: statistical outlier detection, cross-upload duplicate detection, implausible values, future dates
- Nine validation rules, each independently testable, each producing a structured issue with severity and suggested action

**Analyst review workflow**
- Flagged records appear in a dedicated review queue
- Individual approve and reject with optional/required analyst notes respectively
- Bulk approve for clean records
- Every state transition is recorded in the audit log with before/after state

**Auditability**
- `RawRecord` stores the verbatim source row as JSONB and is write-once
- `EmissionRecord` stores pre-conversion quantity, canonical CO2e, and the exact emission factor applied
- `AuditLog` is append-only and references any model via Django's ContentType framework

**Multi-tenancy**
- All data is scoped to a tenant via URL prefix and queryset filtering
- Shared PostgreSQL schema with `tenant_id` on every significant table
- `PROTECT` cascades throughout — no silent data loss

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | Django 5.x, Django REST Framework |
| Database | PostgreSQL (JSONB for raw row storage) |
| Frontend | React 18, Vite, Tailwind CSS |
| HTTP client | Axios |
| Auth | Django session authentication |

No Celery, no Redis, no message queue. The ingestion service is structured as a standalone function to make async extraction straightforward if the scale requires it — but adding infrastructure for files that process in two seconds is not a tradeoff worth making in a prototype.

---

## Project Structure

```
.
├── config/                  Django project settings and root URLs
├── tenants/                 Tenant model and middleware
├── ingestion/
│   ├── models/
│   │   ├── data_source.py   Upload event tracking
│   │   └── raw_record.py    Immutable source rows
│   ├── parsers/
│   │   ├── base.py          ParsedRow, FlaggedRow, ParseResult types
│   │   ├── sap_fuel.py      SAP parser
│   │   ├── utility.py       Utility parser
│   │   └── travel.py        Travel parser
│   ├── validation/
│   │   ├── rules.py         Nine validation rules
│   │   └── service.py       Validation orchestrator
│   ├── serializers.py       DRF serializers
│   ├── views.py             API views
│   ├── urls.py              Ingestion URL routes
│   └── service.py           Ingestion orchestrator
├── emissions/               EmissionRecord model and approval workflow
├── audit/                   AuditLog model
├── fixtures/                Sample CSV files and emission factor data
├── frontend/
│   └── src/
│       ├── api/             Axios client
│       ├── components/      Shared UI components
│       └── pages/           Upload, History, Review Queue, Dashboard
├── MODELS.md                Data model design document
├── DECISIONS.md             Ambiguities resolved and open questions
├── TRADEOFFS.md             Deliberate omissions with rationale
└── SOURCES.md               Real-world format research per source type
```

---

## Local Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Node.js 18+

### Backend

```bash
# Clone and set up virtual environment
git clone https://github.com/Pragati-03/esg-ingestion-platform.git
cd esg-ingestion-platform
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# Install dependencies
pip install django djangorestframework psycopg2-binary python-dotenv

# Configure environment
cp .env.example .env
# Edit .env: set DB_NAME, DB_USER, DB_PASSWORD, SECRET_KEY

# Run migrations
python manage.py migrate

# Create a superuser for admin access
python manage.py createsuperuser

# Start the development server
python manage.py runserver
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
# Edit .env: set VITE_TENANT_SLUG to match a tenant slug in your database

npm run dev
```

The frontend runs at `http://localhost:5173`. The Vite dev server proxies `/api` requests to Django at `http://localhost:8000`.

### Create a test tenant

```bash
python manage.py shell
```

```python
from tenants.models import Tenant
Tenant.objects.create(name="Demo Corp", slug="demo-tenant")
```

Set `VITE_TENANT_SLUG=demo-tenant` in `frontend/.env`.

### Load sample data

The `fixtures/` directory contains realistic sample CSV files for each source type. Upload them through the frontend or via the API directly.

---

## API Overview

All routes are prefixed with `/api/{tenant_slug}/`.

```
POST   /api/{tenant}/uploads/                Upload file and trigger ingestion
GET    /api/{tenant}/uploads/                List uploads with status and progress
GET    /api/{tenant}/uploads/{id}/           Upload detail with scope summary

GET    /api/{tenant}/records/                All records, filterable by status/scope/date
GET    /api/{tenant}/records/flagged/        Analyst review queue
GET    /api/{tenant}/records/{id}/           Record detail with raw source row

POST   /api/{tenant}/records/{id}/approve/   Approve one record
POST   /api/{tenant}/records/{id}/reject/    Reject one record (note required)
POST   /api/{tenant}/records/bulk-approve/   Approve multiple records
```

Full request and response examples are in `API_EXAMPLES.md`.

---

## Key Design Decisions

**CSV ingestion over API integration**
Real enterprise onboarding rarely starts with live API connections. SAP exports are triggered manually by ERP admins. Utility data is downloaded monthly from supplier portals. Connecting to these systems directly requires client-specific OAuth configuration, network access, and weeks of setup per client. CSV upload is what actually happens on day one. The parser interface accepts any file-shaped input — API adapters can be added upstream without changing the normalisation or storage layer.

**Immutable raw records**
`RawRecord` is written once and never updated. The verbatim source row is stored as JSONB, preserving every column from the original file regardless of whether the parser recognised it. If an emission figure is ever disputed, the exact input that produced it is always retrievable. This is the audit foundation of the platform.

**Two-phase validation**
Parsers validate format — "can this row be read?" Semantic validation runs after DB writes — "does this row make sense?" The separation means parser logic stays testable without a database, and cross-record checks (statistical outliers, cross-upload duplicates) have access to existing data without complicating the parsing step.

**Emission factors stored at calculation time**
DEFRA updates its emission factors annually. A record approved in 2024 must retain the factor that was used to calculate its CO2e, not the current factor. `EmissionRecord` stores both the factor value and its source reference. Historical records are not silently affected by factor updates.

**No auto-approval**
Validation moves records to `flagged`. Only a human analyst moves records to `approved`. This is a deliberate constraint — automated approval of ESG data submitted to regulators or verifiers is not appropriate regardless of how clean the source data looks.

---

## Known Limitations

These are documented deliberate omissions, not oversights. Full rationale is in `TRADEOFFS.md`.

**No async task queue.** Ingestion runs synchronously. Appropriate for files up to ~10,000 rows. The ingestion service is structured as a standalone function with no HTTP context dependency — converting it to a Celery task is a one-line change when scale requires it.

**No role-based access control.** Any authenticated user can upload, view, and approve. Attribution is recorded correctly (`approved_by`, `uploaded_by`) but not enforced. A `TenantMembership` model and custom permission classes are the natural extension.

**No emission factor versioning.** Factors are stored as constants in parser files. Each record captures the factor value at calculation time, so historical records are not affected by updates. A versioned `EmissionFactor` model with effective date ranges is the extension point — the `emission_factor_source` string on each record identifies the factor without requiring a FK.

**No PDF parsing.** Utility invoices often arrive as PDFs. The platform accepts pre-extracted CSV only. PDF parsing is a separate engineering problem with high error rates on scanned documents.

**Airport lookup table covers ~30 routes.** Flights between airports not in the table are flagged for manual distance entry. Coverage is sufficient for a European-headquartered company's most common routes.

---

## Running Tests

```bash
# Parser tests (no database required)
python manage.py test ingestion.tests.test_sap_parser
python manage.py test ingestion.tests.test_utility_parser
python manage.py test ingestion.tests.test_travel_parser

# Validation rule tests (no database required)
python manage.py test ingestion.tests.test_validation_rules
```

The parser and validation tests use mock objects and temporary files. They do not require a running database or any fixtures.

---

## Documentation

| File | Contents |
|---|---|
| `MODELS.md` | Entity relationships, normalisation strategy, index rationale |
| `DECISIONS.md` | Ambiguities resolved, assumptions made, questions for the PM |
| `TRADEOFFS.md` | Three deliberate omissions with full engineering rationale |
| `SOURCES.md` | Real-world format research for each source type |
| `API_EXAMPLES.md` | Request and response examples for all endpoints |
