"""
Validation Service
-------------------

Orchestrates running all validation rules against the EmissionRecords
produced by a DataSource ingestion.

WHEN THIS RUNS:
After the ingestion service has written RawRecords and EmissionRecords to DB.
The ingestion service calls validate_data_source() as its final step.

WHY AFTER DB WRITES (NOT BEFORE):
- Statistical outlier detection requires querying existing records
- Duplicate detection requires querying the DB
- Running validation before writes would require passing all context
  in memory, which breaks for large files

WHAT IT DOES:
1. Pre-computes aggregate context (stats, existing fingerprints)
2. Runs all rules against each EmissionRecord in the DataSource
3. Updates EmissionRecord.status to 'flagged' where issues found
4. Writes ValidationIssues to AuditLog as structured delta data
5. Returns a summary

WHAT IT DOES NOT DO:
- It does not approve records (only humans do that)
- It does not delete records
- It does not modify raw_records
"""

import logging
import statistics
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.emissions.models import EmissionRecord, ApprovalStatus, FlagType
from apps.audit.models import AuditLog, EventType
from .base import ValidationResult, Severity
from .rules import RULE_REGISTRY

logger = logging.getLogger(__name__)


@dataclass
class ValidationSummary:
    """What the service returns after validating a DataSource."""
    data_source_id: str
    total_records: int = 0
    flagged_count: int = 0
    warning_only_count: int = 0
    clean_count: int = 0
    rule_hit_counts: dict = field(default_factory=dict)


def validate_data_source(data_source, actor=None) -> ValidationSummary:
    """
    Run all validation rules against all EmissionRecords for a DataSource.

    Args:
        data_source: DataSource instance (status must be 'done')
        actor: User who triggered this (for audit log). None = system-triggered.

    Returns:
        ValidationSummary with counts of flagged/clean records.

    TRANSACTION STRATEGY:
    Each record update is committed immediately, not in one giant transaction.
    WHY: If validation fails at record 500 of 1000, we keep the first 499
    validated rather than rolling everything back. Validation is idempotent —
    safe to re-run.
    """
    summary = ValidationSummary(data_source_id=str(data_source.id))

    # Fetch all pending_review records for this upload
    records = list(
        EmissionRecord.objects.filter(
            data_source=data_source,
            status=ApprovalStatus.PENDING_REVIEW,
        ).select_related("tenant", "raw_record")
    )

    if not records:
        logger.info("No pending_review records found for DataSource %s", data_source.id)
        return summary

    summary.total_records = len(records)

    # Pre-compute context — shared across all rule checks
    context = _build_context(records, data_source.tenant)

    for record in records:
        result = _run_rules(record, context)
        _apply_result(record, result, actor, summary)

    logger.info(
        "Validation complete for DataSource %s: %d records, %d flagged",
        data_source.id,
        summary.total_records,
        summary.flagged_count,
    )
    return summary


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------

def _build_context(records: list, tenant) -> dict:
    """
    Pre-compute all aggregate data needed by rules.

    This runs ONCE before rule evaluation — not once per record.
    Avoids N+1 queries inside rule.check() calls.

    Context structure:
    {
        "quantity_stats": {
            "sap_fuel": {"mean": 350.0, "stdev": 120.0, "count": 45},
            "utility":  {"mean": 8200.0, "stdev": 1500.0, "count": 12},
        },
        "existing_fingerprints": {("tenant-uuid", "sap_fuel", "2024-01-15", "450.5", "litre"), ...}
    }
    """
    context: dict = {}

    # --- Statistical context ---
    # Group quantities by source_type to compute per-type statistics
    quantities_by_type: dict[str, list[float]] = {}
    for record in records:
        quantities_by_type.setdefault(record.source_type, []).append(
            float(record.quantity)
        )

    quantity_stats = {}
    for source_type, quantities in quantities_by_type.items():
        if len(quantities) >= 2:
            quantity_stats[source_type] = {
                "mean": statistics.mean(quantities),
                "stdev": statistics.stdev(quantities),
                "count": len(quantities),
            }
    context["quantity_stats"] = quantity_stats

    # --- Duplicate fingerprints from existing DB records ---
    # Query records already in DB for this tenant that are NOT in this upload.
    # These are the ones we need to check for cross-upload duplicates.
    existing = EmissionRecord.objects.filter(
        tenant=tenant,
        status__in=[
            ApprovalStatus.APPROVED,
            ApprovalStatus.PENDING_REVIEW,
        ]
    ).exclude(
        data_source_id__in=[records[0].data_source_id] if records else []
    ).values_list("tenant_id", "source_type", "activity_date", "quantity", "unit")

    context["existing_fingerprints"] = {
        (str(t), st, str(d), str(q), u)
        for t, st, d, q, u in existing
    }

    return context


def _run_rules(record, context: dict) -> ValidationResult:
    """Run all rules in RULE_REGISTRY against one record."""
    result = ValidationResult(record_id=str(record.id))
    for rule in RULE_REGISTRY:
        try:
            issues = rule.check(record, context)
            result.issues.extend(issues)
        except Exception as exc:
            # A rule crashing should not stop validation of other records.
            # Log and continue.
            logger.exception(
                "Rule %s raised an exception on record %s: %s",
                rule.code, record.id, exc
            )
    return result


def _apply_result(record, result: ValidationResult, actor, summary: ValidationSummary) -> None:
    """
    Apply ValidationResult to one EmissionRecord:
    - Update status if issues found
    - Set flag_type and flag_reason from primary issue
    - Write AuditLog entry
    - Update summary counts
    """
    if result.is_clean:
        summary.clean_count += 1
        return

    primary = result.primary_issue()

    # Map rule severity to flag type for EmissionRecord
    # ERROR → stays flagged (needs analyst action)
    # WARNING → also flagged, but message indicates lower urgency
    new_status = ApprovalStatus.FLAGGED

    # Map RuleCode → FlagType (EmissionRecord's existing enum)
    flag_type_map = {
        "negative_quantity":       FlagType.OUT_OF_RANGE,
        "zero_quantity":           FlagType.OUT_OF_RANGE,
        "negative_co2e":           FlagType.OUT_OF_RANGE,
        "zero_emission_factor":    FlagType.OUT_OF_RANGE,
        "invalid_unit":            FlagType.UNKNOWN_UNIT,
        "missing_unit":            FlagType.UNKNOWN_UNIT,
        "future_date":             FlagType.FUTURE_DATE,
        "implausible_date":        FlagType.FUTURE_DATE,
        "statistical_outlier":     FlagType.OUT_OF_RANGE,
        "duplicate_record":        FlagType.DUPLICATE,
        "unknown_airport":         FlagType.MISSING_VALUE,
        "same_origin_destination": FlagType.OUT_OF_RANGE,
        "credit_note":             FlagType.OUT_OF_RANGE,
        "excessive_cost":          FlagType.OUT_OF_RANGE,
    }

    flag_type = flag_type_map.get(primary.rule_code.value, FlagType.OUT_OF_RANGE)

    # Build full flag_reason from all issues
    all_messages = "\n".join(
        f"[{i.severity.upper()}] {i.message}"
        for i in result.issues
    )

    record.status = new_status
    record.flag_type = flag_type
    record.flag_reason = all_messages
    record.save(update_fields=["status", "flag_type", "flag_reason", "updated_at"])

    # Audit log entry
    AuditLog.objects.create(
        tenant=record.tenant,
        actor=actor,
        actor_email_snapshot=actor.email if actor else "system",
        event_type=EventType.RECORD_FLAGGED,
        delta={
            "before": {"status": "pending_review"},
            "after": {"status": "flagged"},
            "issues": [
                {
                    "rule": i.rule_code.value,
                    "severity": i.severity.value,
                    "message": i.message,
                }
                for i in result.issues
            ],
        },
        description=(
            f"Record flagged by validation: {primary.message[:200]}"
        ),
    )

    # Update summary
    summary.flagged_count += 1
    if not result.has_errors:
        summary.warning_only_count += 1

    for issue in result.issues:
        code = issue.rule_code.value
        summary.rule_hit_counts[code] = summary.rule_hit_counts.get(code, 0) + 1
