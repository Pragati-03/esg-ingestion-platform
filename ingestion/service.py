"""
Ingestion Service
-----------------
Orchestrates the full ingestion pipeline for a DataSource:
  1. Route to the correct parser
  2. Write all RawRecords (immutable)
  3. Write EmissionRecords (normalised, with approval status)
  4. Write AuditLog event
  5. Update DataSource status and counts

WHY THIS IS A SERVICE, NOT A VIEW:
Business logic does not belong in views. Views handle HTTP; services handle
work. This function can be called from a view, a management command, or a
test — without any HTTP context.

WHY SYNCHRONOUS:
File uploads in this domain are batch exports, typically 100-5,000 rows.
At that scale, synchronous processing completes in under 2 seconds.
Introducing Celery/Redis for async processing adds significant infrastructure
overhead that isn't justified here.

WHAT WOULD BREAK IN PRODUCTION:
- Files >50k rows would block the request worker thread
- No retry logic if DB write fails mid-file
- No partial recovery — if the process dies at row 3000, you restart from 0
  (mitigated by the checksum dedup on DataSource)
"""

import hashlib
import logging
from datetime import datetime, timezone

from django.db import transaction

from ingestion.models import DataSource, IngestionStatus, RawRecord
from emissions.models import EmissionRecord, ApprovalStatus
from audit.models import AuditLog, EventType
from .parsers.sap_fuel import SAPFuelParser
from .parsers.base import ParsedRow, FlaggedRow

logger = logging.getLogger(__name__)

# Parser registry — maps source_type string → parser class.
# Adding a new source type = add one line here + write the parser.
PARSER_REGISTRY = {
    "sap_fuel": SAPFuelParser,
    # "utility": UtilityParser,   # Day 3
    # "travel": TravelParser,     # Day 3
}


def ingest_data_source(data_source: DataSource, actor) -> DataSource:
    """
    Run the full ingestion pipeline for a DataSource.

    Wraps everything in a transaction so a failure mid-file leaves the DB
    clean — either all rows are written or none are.

    Args:
        data_source: DataSource instance with status=pending
        actor: User instance (for audit log)

    Returns:
        Updated DataSource instance
    """
    logger.info(
        "Starting ingestion for DataSource %s (%s)",
        data_source.id,
        data_source.source_type,
    )

    # --- 1. Resolve parser ---
    parser_class = PARSER_REGISTRY.get(data_source.source_type)
    if not parser_class:
        return _fail(
            data_source,
            actor,
            f"No parser registered for source_type '{data_source.source_type}'",
        )

    # --- 2. Compute and verify checksum ---
    try:
        checksum = _compute_checksum(data_source.file.path)
    except Exception as exc:
        return _fail(data_source, actor, f"Could not read uploaded file: {exc}")

    # Update checksum so the UniqueConstraint on DataSource can catch re-uploads
    DataSource.objects.filter(pk=data_source.pk).update(checksum=checksum)

    # --- 3. Mark as processing ---
    data_source.status = IngestionStatus.PROCESSING
    data_source.save(update_fields=["status"])

    # --- 4. Parse ---
    parser = parser_class()
    result = parser.parse(data_source.file.path)

    if result.has_fatal_error:
        return _fail(data_source, actor, result.fatal_error)

    # --- 5. Write to DB inside a single transaction ---
    try:
        with transaction.atomic():
            _write_parsed_rows(data_source, result.parsed_rows)
            _write_flagged_rows(data_source, result.flagged_rows)

            # Update DataSource summary fields
            data_source.status = IngestionStatus.DONE
            data_source.row_count = result.total_rows
            data_source.flagged_count = len(result.flagged_rows)
            data_source.completed_at = datetime.now(tz=timezone.utc)
            data_source.save(
                update_fields=["status", "row_count", "flagged_count", "completed_at"]
            )

            # Audit event
            AuditLog.objects.create(
                tenant=data_source.tenant,
                actor=actor,
                actor_email_snapshot=actor.email if actor else "",
                event_type=EventType.UPLOAD_COMPLETED,
                delta={
                    "row_count": result.total_rows,
                    "flagged_count": len(result.flagged_rows),
                    "parsed_count": len(result.parsed_rows),
                },
                description=(
                    f"Ingested {result.total_rows} rows from "
                    f"'{data_source.original_filename}'. "
                    f"{len(result.flagged_rows)} flagged."
                ),
            )

    except Exception as exc:
        logger.exception("DB write failed for DataSource %s", data_source.id)
        return _fail(data_source, actor, f"Database write failed: {exc}")

    logger.info(
        "Ingestion complete for DataSource %s. %d rows, %d flagged.",
        data_source.id,
        result.total_rows,
        len(result.flagged_rows),
    )
    return data_source


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------

def _write_parsed_rows(data_source: DataSource, rows: list[ParsedRow]) -> None:
    """
    Bulk-create RawRecords and EmissionRecords for clean parsed rows.

    WHY BULK_CREATE:
    Individual .save() calls in a loop issue one INSERT per row.
    For 1,000 rows that's 2,000 queries. bulk_create does it in 2.
    We set batch_size=500 to avoid hitting PostgreSQL's parameter limit.
    """
    raw_records = [
        RawRecord(
            data_source=data_source,
            tenant=data_source.tenant,
            row_number=row.row_number,
            raw_data=row.raw_data,
            is_flagged=False,
        )
        for row in rows
    ]
    created_raws = RawRecord.objects.bulk_create(raw_records, batch_size=500)

    # Map row_number → created RawRecord for the FK on EmissionRecord
    raw_by_row = {r.row_number: r for r in created_raws}

    emission_records = [
        EmissionRecord(
            raw_record=raw_by_row[row.row_number],
            data_source=data_source,
            tenant=data_source.tenant,
            source_type=row.source_type,
            activity_date=row.activity_date,
            description=row.description,
            quantity=row.quantity,
            unit=row.unit,
            co2e_kg=row.co2e_kg,
            scope=row.scope,
            emission_factor=row.emission_factor,
            emission_factor_source=row.emission_factor_source,
            status=ApprovalStatus.PENDING_REVIEW,
        )
        for row in rows
    ]
    EmissionRecord.objects.bulk_create(emission_records, batch_size=500)


def _write_flagged_rows(data_source: DataSource, rows: list[FlaggedRow]) -> None:
    """
    Bulk-create RawRecords and flagged EmissionRecords for invalid rows.

    Flagged EmissionRecords have minimal normalised data — we can't compute
    CO2e for a row with a missing quantity. We store what we have and let
    the analyst decide.
    """
    raw_records = [
        RawRecord(
            data_source=data_source,
            tenant=data_source.tenant,
            row_number=row.row_number,
            raw_data=row.raw_data,
            is_flagged=True,
        )
        for row in rows
    ]
    created_raws = RawRecord.objects.bulk_create(raw_records, batch_size=500)
    raw_by_row = {r.row_number: r for r in created_raws}

    emission_records = [
        EmissionRecord(
            raw_record=raw_by_row[row.row_number],
            data_source=data_source,
            tenant=data_source.tenant,
            source_type=data_source.source_type,
            # Use safe defaults for missing values — these are placeholders only
            activity_date=_extract_date_best_effort(row.raw_data),
            description=row.raw_data.get("Materialbezeichnung", "")
                        or row.raw_data.get("description", ""),
            quantity=0,
            unit="unknown",
            co2e_kg=0,
            scope=1,
            emission_factor=0,
            emission_factor_source="N/A — record flagged before factor applied",
            status=ApprovalStatus.FLAGGED,
            flag_type=row.flag_type,
            flag_reason=row.flag_reason,
        )
        for row in rows
    ]
    EmissionRecord.objects.bulk_create(emission_records, batch_size=500)


def _fail(data_source: DataSource, actor, error_message: str) -> DataSource:
    """Mark a DataSource as failed and write an audit event."""
    data_source.status = IngestionStatus.FAILED
    data_source.error_message = error_message
    data_source.save(update_fields=["status", "error_message"])

    AuditLog.objects.create(
        tenant=data_source.tenant,
        actor=actor,
        actor_email_snapshot=actor.email if actor else "",
        event_type=EventType.UPLOAD_FAILED,
        delta={"error": error_message},
        description=f"Ingestion failed for '{data_source.original_filename}': {error_message}",
    )

    logger.error("Ingestion failed for DataSource %s: %s", data_source.id, error_message)
    return data_source


def _compute_checksum(file_path: str) -> str:
    """SHA-256 checksum of file contents. Used to detect duplicate uploads."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _extract_date_best_effort(raw_data: dict):
    """
    Try to extract a date from raw_data for a flagged row.
    Returns today's date as fallback — the flag_reason explains the real problem.
    """
    from datetime import date
    from ingestion.parsers.sap_constants import DATE_FORMATS

    for key in ("Buchungsdatum", "activity_date", "datum", "Datum"):
        value = raw_data.get(key, "")
        if value:
            for fmt in DATE_FORMATS:
                try:
                    from datetime import datetime
                    return datetime.strptime(value.strip(), fmt).date()
                except ValueError:
                    continue

    return date.today()
