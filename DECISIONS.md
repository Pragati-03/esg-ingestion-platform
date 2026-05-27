# Engineering Decisions — ESG Ingestion Platform

This document records the decisions made during a 4-day build, the ambiguities encountered, the assumptions that resolved them, and the questions that remain open. It is written for a technical reviewer who wants to understand not just what was built, but why, and what was consciously left out.

---

## Ambiguities Resolved

### 1. What does "ingest SAP fuel data" mean exactly?

**Ambiguity:** SAP is a platform, not a file format. SAP ECC and S4HANA both support dozens of export formats depending on the transaction used (ME2M, MB51, custom ABAP reports). The phrase "SAP fuel/procurement export" could mean any of them.

**Resolution:** I assumed a flat CSV export from a standard procurement or material movement transaction, with German column headers (Buchungsdatum, Werk, Menge, Einheit, etc.), since the platform appears to serve a German or DACH-region client base. The parser handles the most common column name variants and date format variants seen in real SAP exports.

**What I'd ask the PM:** Which SAP transaction generates the export? Does the client have a custom ABAP report or are they using standard MM transactions? Is the export always triggered manually or is there an automated scheduler?

---

### 2. How should overlapping utility billing periods be handled?

**Ambiguity:** Utility bills frequently cover non-calendar periods (e.g. 15 Jan – 14 Feb). If a client uploads January and February bills separately, and one covers a partial overlap, should we prorate, reject, or flag?

**Resolution:** I flag overlapping periods for analyst review rather than attempting automated proration. Proration requires knowing the exact meter profile (daily consumption is not uniform), which we don't have. The analyst is better positioned to decide whether an overlap represents an amended bill, a duplicate, or a genuine split billing period.

**What I'd ask the PM:** Do clients typically get monthly bills or quarterly? Are bill periods calendar-aligned? Do any clients provide half-hourly smart meter data rather than invoice-level summaries?

---

### 3. How should flight distances be calculated when only airport codes are available?

**Ambiguity:** Corporate travel exports from Concur and Navan typically contain origin and destination airport codes (IATA), not distances. There is no universally agreed methodology for converting airport pairs to CO2e.

**Resolution:** I used a lookup table of great-circle distances for the ~30 most common routes a European-headquartered company would fly. Unknown routes are flagged for analyst manual entry. The GHG Protocol allows great-circle distance as a reasonable approximation; DEFRA's emission factors are designed to be applied to it.

I did not apply a routing uplift factor (typically 8–9% to account for air traffic control deviations from great-circle), which means flight CO2e is slightly understated. This is documented as a known limitation.

**What I'd ask the PM:** Is the client required to report aviation with or without radiative forcing index (RFI)? DEFRA provides factors both ways and it roughly doubles the CO2e figure for flights. This is a significant reporting decision that should be made at the product level, not by the engineer.

---

### 4. What counts as a "duplicate" record?

**Ambiguity:** Duplicates can mean different things: the same file uploaded twice, the same invoice number in two different files, or two rows with identical data but different invoice numbers (a re-issued bill).

**Resolution:** I implemented two levels of duplicate detection. At the file level, the SAP and utility parsers use a fingerprint (meter ID + invoice number + quantity + dates) to detect within-file duplicates. At the cross-upload level, the validation service checks for existing records with identical tenant + source type + date + quantity + unit. Both flag for review rather than auto-reject, because "duplicate" in enterprise finance data is often legitimate (amended bills, corrections).

**What I'd ask the PM:** Should duplicate detection be configurable per tenant? Some clients re-upload entire quarters every month as a reconciliation step. For them, cross-upload duplicate detection would flag everything and be useless.

---

### 5. Which grid emission factor should be applied to utility records?

**Ambiguity:** Grid electricity emission factors vary by country, by year, and by whether the client has renewable energy certificates (REGOs, PPAs). A client in Germany has a very different grid intensity than a client in France or the UK.

**Resolution:** I stored country-level grid factors from DEFRA 2023 (UK) and UBA 2023 (DE) as constants, with a fallback to IEA EU average. The country code is passed at the parser level and defaults to EU average. I did not implement renewable energy certificate handling — a client with 100% renewable PPAs should have a zero Scope 2 figure, but verifying that claim requires document review that is outside the scope of this build.

**What I'd ask the PM:** Do any clients have renewable energy contracts that would affect their Scope 2 reporting? How should location-based vs market-based Scope 2 reporting be handled? These are methodologically distinct approaches and the platform should eventually support both.

---

## Ingestion Format Choices

### Why CSV only, not PDF or API

Enterprise utility and procurement data arrives in three forms in practice: PDF invoices, portal CSV exports, and live ERP API calls. I built for CSV exports because:

- PDF parsing requires OCR and layout understanding, which is a separate engineering problem with high error rates on scanned invoices.
- Live ERP API integration (SAP OData, utility REST APIs) requires OAuth setup, network configuration, and client-specific credentials — weeks of work per client, not days.
- CSV exports are what facilities and finance teams actually do. When asked to "download the data", a non-technical user downloads a CSV. This is the realistic default.

The parser architecture uses a `BaseParser` interface. A PDF-to-CSV pre-processor or an API adapter can be inserted upstream of the parser without changing anything downstream.

### Why not XLSX parsing

The file upload endpoint accepts `.xlsx` but the parsers are CSV-only. This is a documented gap. Most enterprise tools export to CSV from their download dialogs even when the file is named `.xlsx`. Full XLSX parsing (handling merged cells, multi-sheet workbooks, header rows at row 3) is disproportionate complexity for a first version.

### Why German column headers in the SAP fixture

SAP ECC systems in German-speaking markets default to German UI language, which affects export column names. A UK company using SAP with English language settings produces different headers. The column alias table in `sap_constants.py` handles both variants, but the sample data uses German headers because they are the harder case and demonstrate the parser's robustness.

---

## Assumptions Made

**On file size:**
A typical quarterly SAP fuel export for a mid-size manufacturing company has 200–2,000 rows. A utility export has 12–50 rows per meter per year. A travel export has 500–5,000 rows per quarter. The synchronous ingestion approach is appropriate for all of these. Files above 50,000 rows would need an async task queue.

**On authentication:**
I used Django's built-in authentication. The platform assumes a separate identity provider or Django admin is used to provision user accounts. I did not build login/registration flows because they are not specific to ESG ingestion and would consume disproportionate time.

**On emission factors:**
All factors are from DEFRA 2023 and IEA 2023, stored as constants in the parser files. This is appropriate for a prototype. Production would require a versioned emission factor database, updated annually, with a migration path for re-calculating historical records when factors change.

**On Scope 3 completeness:**
Corporate travel is one category of Scope 3 (Category 6 — Business Travel). The GHG Protocol defines 15 Scope 3 categories. I did not attempt to cover the others (supply chain, employee commuting, downstream product use, etc.). The data model supports any Scope 3 source type — the limitation is parser coverage, not schema design.

**On currency:**
All cost fields are assumed to be in GBP. No currency conversion is implemented. A multi-currency deployment would need to store the original currency and convert to a reporting currency at query time, not at ingestion time (exchange rates change).

**On user roles:**
The approval workflow distinguishes between users who can upload and users who can approve, but no formal RBAC system is implemented. Django's `IsAuthenticated` permission class is applied to all endpoints. A production system would separate uploader, analyst, and admin roles with explicit permission checks.

---

## What I Intentionally Ignored

**Celery / async task queue:**
Ingestion runs synchronously in the request-response cycle. This is a deliberate choice for a 4-day build. The ingestion service is already extracted into a standalone function (`ingest_data_source`) that takes a `DataSource` and returns it. Converting to a Celery task is a one-line change at the call site. I noted this explicitly in the code rather than building infrastructure that couldn't be tested in the available time.

**Real-time progress updates:**
The upload endpoint returns only when ingestion is complete. A production platform would stream progress via Server-Sent Events or WebSockets. For files under 5,000 rows this is a latency of 1–3 seconds, which is acceptable for a prototype.

**Pagination cursor:**
Records are paginated with offset/limit rather than cursor-based pagination. Cursor pagination is more efficient at scale (no COUNT query, stable under concurrent writes) but harder to implement and harder for a frontend developer to integrate without documentation. Offset/limit with a 200-record cap is sufficient for the expected data volumes.

**Email notifications:**
No email is sent when ingestion completes or when records are flagged. A production system would notify the uploader on completion and notify analysts when the review queue grows. This is a clear product requirement that was deprioritised in favour of core ingestion functionality.

**Soft deletes:**
`EmissionRecord` has no soft-delete mechanism. If a record needs to be removed from reporting, it is rejected (not deleted). Rejected records remain in the database and in the audit log. This is the correct behaviour for a compliance platform — hard deletion of records that have been through any approval workflow step is dangerous and should require explicit admin intervention.

**Frontend authentication:**
The React frontend makes API calls without an authentication token. A production integration would use Django's session authentication or a JWT flow. The API is protected by `IsAuthenticated` on the backend; the frontend just needs a login page and session management to complete the loop.

**Test coverage for views and services:**
Parser tests are comprehensive (14 tests for SAP, 13 for utility, 12 for travel, 10 for validation rules). View and service tests are not written. In a full sprint these would be integration tests using Django's test client against an in-memory SQLite database. They were deprioritised because parser logic is where the real complexity lives — the views are thin orchestrators.

---

## What I Would Ask the PM

These are the questions that would change the architecture if answered differently. They should be resolved before a production build begins.

**1. Market-based vs location-based Scope 2 reporting?**
These are the GHG Protocol's two methods for calculating purchased electricity emissions. Location-based uses the average grid intensity of the country. Market-based uses the specific tariff the client is on, including renewable energy certificates. Both are valid; many large companies report both. The data model and parsers currently support location-based only. Market-based requires storing tariff information and certificate documentation.

**2. Is multi-currency a day-one requirement?**
Cost fields are currently GBP only. If clients operate in multiple currencies and need to report cost alongside CO2e, a currency field and conversion mechanism is needed from the start. This affects the data model.

**3. What is the regulatory reporting target?**
TCFD, CDP, GRI, and SECR all have different disclosure requirements and different levels of assurance. The audit trail built here supports all of them, but the output format (report templates, verification statements) differs. Knowing the target informs how the approval workflow should be documented.

**4. How many tenants at launch, and what is the expected data volume per tenant per year?**
The shared-schema tenancy approach works well up to ~50 tenants with moderate data volumes. If the answer is "hundreds of tenants" or "one tenant with 10 million rows", the architecture needs revisiting before launch, not after.

**5. Who performs the analyst review — the client's own staff or Breathe's analysts?**
This affects user provisioning, permission design, and the UI. If Breathe's analysts review data on behalf of clients, the multi-tenancy model needs to support cross-tenant analyst access with a clear permission boundary. If clients review their own data, the current model is sufficient.

**6. What is the data retention policy?**
ESG data may need to be retained for 7–10 years for regulatory purposes. Does "deleting a tenant" mean soft-disable or hard purge? If hard purge, what is the process for extracting and archiving records before deletion? The current `PROTECT` cascade design prevents accidental deletion but does not define a purge process.

**7. Is there a requirement for re-calculation when emission factors are updated?**
DEFRA updates its emission factors annually, sometimes with significant changes. If a client approved 1,000 records using 2023 factors and the 2024 factors are released, does the platform need to flag those records for re-review? This is a product decision with significant engineering implications.
