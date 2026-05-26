# API Response Examples

## POST /api/acme-corp/uploads/
Upload a file and trigger ingestion.

**Request** (multipart/form-data):
```
source_type = "sap_fuel"
file        = @quarterly_fuel_export.csv
```

**Response 201 — Success:**
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "source_type": "sap_fuel",
  "original_filename": "quarterly_fuel_export.csv",
  "status": "done",
  "row_count": 124,
  "flagged_count": 7,
  "uploaded_by_name": "Jane Smith",
  "approval_progress": {
    "total": 124,
    "approved": 0,
    "rejected": 0,
    "pending": 124
  },
  "scope_summary": {},
  "created_at": "2024-01-15T09:23:11Z",
  "completed_at": "2024-01-15T09:23:13Z",
  "error_message": ""
}
```

**Response 422 — Ingestion Failed:**
```json
{
  "status": "failed",
  "error_message": "Missing required columns after alias resolution: {'activity_date'}. Headers found: ['Werk', 'Menge', 'Einheit']"
}
```

**Response 400 — Validation Error:**
```json
{
  "source_type": ["source_type must be one of {'sap_fuel', 'utility', 'travel'}"],
  "file": ["File exceeds 50MB limit. Split large exports before uploading."]
}
```

---

## GET /api/acme-corp/uploads/
List all uploads.

**Query params:** `?status=done&source_type=sap_fuel`

**Response 200:**
```json
{
  "count": 3,
  "results": [
    {
      "id": "a1b2c3d4-...",
      "source_type": "sap_fuel",
      "original_filename": "jan_fuel.csv",
      "status": "done",
      "row_count": 124,
      "flagged_count": 7,
      "uploaded_by_name": "Jane Smith",
      "approval_progress": {
        "total": 124,
        "approved": 117,
        "rejected": 2,
        "pending": 5
      },
      "created_at": "2024-01-15T09:23:11Z",
      "completed_at": "2024-01-15T09:23:13Z"
    }
  ]
}
```

---

## GET /api/acme-corp/records/flagged/
Analyst approval queue — flagged records only.

**Response 200:**
```json
{
  "count": 7,
  "limit": 50,
  "offset": 0,
  "results": [
    {
      "id": "rec-uuid-001",
      "source_type": "sap_fuel",
      "activity_date": "2024-01-30",
      "description": "Dieselkraftstoff",
      "quantity": "99999.0000",
      "unit": "litre",
      "co2e_kg": "0.0000",
      "scope": 1,
      "emission_factor": "0.000000",
      "emission_factor_source": "N/A — record flagged before factor applied",
      "status": "flagged",
      "flag_type": "out_of_range",
      "flag_reason": "[ERROR] Quantity 99999.0 litre is outside plausible range [0.1, 50000]. Possible test booking or data entry error.",
      "analyst_note": "",
      "approved_by_name": null,
      "approved_at": null,
      "data_source_filename": "jan_fuel.csv",
      "raw_data": {
        "Buchungsdatum": "10.02.2024",
        "Werk": "WERK_MUC",
        "Materialnummer": "MAT-10023",
        "Materialbezeichnung": "Diesel",
        "Menge": "99999",
        "Einheit": "L",
        "Kostenstelle": "CC-1001",
        "Belegtext": "TESTBUCHUNG BITTE IGNORIEREN"
      },
      "created_at": "2024-01-15T09:23:12Z"
    }
  ]
}
```

---

## POST /api/acme-corp/records/{id}/approve/

**Request:**
```json
{
  "analyst_note": "Verified against physical fuel log — quantity confirmed correct."
}
```

**Response 200:**
```json
{
  "id": "rec-uuid-001",
  "status": "approved",
  "approved_by_name": "Jane Smith",
  "approved_at": "2024-01-16T14:32:00Z",
  "analyst_note": "Verified against physical fuel log — quantity confirmed correct.",
  ...
}
```

**Response 400 — Already Approved:**
```json
{
  "detail": "Record is already approved."
}
```

---

## POST /api/acme-corp/records/{id}/reject/

**Request:**
```json
{
  "analyst_note": "This is a test booking (TESTBUCHUNG). Confirmed with SAP admin."
}
```

**Response 200:**
```json
{
  "id": "rec-uuid-001",
  "status": "rejected",
  "approved_by_name": "Jane Smith",
  "approved_at": "2024-01-16T14:35:00Z",
  "analyst_note": "This is a test booking (TESTBUCHUNG). Confirmed with SAP admin.",
  ...
}
```

**Response 400 — Missing or too short analyst_note:**
```json
{
  "analyst_note": ["This field is required."]
}
```

---

## POST /api/acme-corp/records/bulk-approve/

**Request:**
```json
{
  "record_ids": [
    "rec-uuid-002",
    "rec-uuid-003",
    "rec-uuid-004"
  ],
  "analyst_note": "Batch approved after manual spot-check of Jan fuel records."
}
```

**Response 200:**
```json
{
  "approved_count": 3,
  "skipped_count": 0,
  "detail": "3 records approved."
}
```

---

## GET /api/acme-corp/records/?scope=1&date_from=2024-01-01&date_to=2024-03-31

Filter records by scope and date range.

**Response 200:**
```json
{
  "count": 117,
  "limit": 50,
  "offset": 0,
  "results": [...]
}
```

---

## Error Responses (consistent across all endpoints)

**401 Unauthenticated:**
```json
{"detail": "Authentication credentials were not provided."}
```

**404 Not Found:**
```json
{"detail": "Not found."}
```

**400 Bad Request:**
```json
{"field_name": ["Error message here."]}
```
