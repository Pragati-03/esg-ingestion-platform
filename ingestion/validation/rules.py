"""
Validation Rules
-----------------

Each rule is a self-contained class. Rules are collected into RULE_REGISTRY
at the bottom of this file. The ValidationService runs all applicable rules
against each EmissionRecord.

RULE DESIGN PRINCIPLES:
1. Each rule checks exactly one thing
2. Rules never modify records — they only report issues
3. Rules use context dict for cross-record data (averages, seen values)
4. Rules are deterministic — same input always produces same output

TRADEOFF — STATISTICAL OUTLIER DETECTION:
We use a simple mean ± 3 standard deviations approach. This requires
at least 10 records in the same source_type + tenant group to be meaningful.
With fewer records the threshold is too wide to catch real outliers.
A production system would use a rolling 12-month window per meter/site.
"""

import statistics
from datetime import date, datetime

from .base import BaseRule, RuleCode, Severity, ValidationIssue

# Earliest plausible ESG reporting date.
# Records before this are almost certainly data errors.
EARLIEST_VALID_DATE = date(2010, 1, 1)

# Known valid units per source type
VALID_UNITS = {
    "sap_fuel": {"litre", "kg", "m3"},
    "utility":  {"kwh", "mwh"},
    "travel":   {"km", "miles", "nights"},
}


# ---------------------------------------------------------------------------
# Quantity rules
# ---------------------------------------------------------------------------

class NegativeQuantityRule(BaseRule):
    """
    Catches negative quantities that aren't credit notes.

    WHY: Negative kWh on a utility bill is a credit note — legitimate.
    Negative litres of diesel is never legitimate.
    We flag both as errors but give different messages.
    """
    code = RuleCode.NEGATIVE_QUANTITY
    severity = Severity.ERROR

    def check(self, record, context: dict) -> list[ValidationIssue]:
        if float(record.quantity) < 0:
            is_utility = record.source_type == "utility"
            return [ValidationIssue(
                rule_code=self.code,
                severity=self.severity,
                field_name="quantity",
                message=(
                    f"Quantity is negative ({record.quantity} {record.unit}). "
                    + ("This may be a supplier credit note — verify against invoice."
                       if is_utility else
                       "Negative fuel quantities are not physically possible.")
                ),
                suggested_action=(
                    "Verify against original invoice. Approve if confirmed credit note, reject otherwise."
                    if is_utility else
                    "Reject this record and re-check the source file."
                ),
            )]
        return []


class ZeroQuantityRule(BaseRule):
    """
    Flags zero-quantity records. Usually a failed SAP posting or export error.
    Warning not error — some legitimate zero-usage periods exist (site shutdown).
    """
    code = RuleCode.ZERO_QUANTITY
    severity = Severity.WARNING

    def check(self, record, context: dict) -> list[ValidationIssue]:
        if float(record.quantity) == 0:
            return [ValidationIssue(
                rule_code=self.code,
                severity=self.severity,
                field_name="quantity",
                message=(
                    f"Quantity is zero. This may be a failed SAP posting, "
                    f"a site shutdown period, or a data export error."
                ),
                suggested_action="Confirm with data owner whether zero usage is expected for this period.",
            )]
        return []


class NegativeCO2eRule(BaseRule):
    """
    CO2e should never be negative in our model.
    If it is, the emission factor or calculation is wrong.
    """
    code = RuleCode.NEGATIVE_CO2E
    severity = Severity.ERROR

    def check(self, record, context: dict) -> list[ValidationIssue]:
        if float(record.co2e_kg) < 0:
            return [ValidationIssue(
                rule_code=self.code,
                severity=self.severity,
                field_name="co2e_kg",
                message=(
                    f"Calculated CO2e is negative ({record.co2e_kg} kg). "
                    f"This indicates a calculation error, not a real-world value."
                ),
                suggested_action="Reject record. Check emission factor and quantity sign.",
            )]
        return []


class ZeroEmissionFactorRule(BaseRule):
    """
    An emission factor of zero means CO2e will always be zero.
    This is suspicious — it usually means a factor was not found and
    a fallback zero was used rather than raising an error.
    """
    code = RuleCode.ZERO_EMISSION_FACTOR
    severity = Severity.WARNING

    def check(self, record, context: dict) -> list[ValidationIssue]:
        if float(record.emission_factor) == 0:
            return [ValidationIssue(
                rule_code=self.code,
                severity=self.severity,
                field_name="emission_factor",
                message=(
                    f"Emission factor is zero. CO2e will be reported as zero "
                    f"which is likely incorrect. Factor source: '{record.emission_factor_source}'"
                ),
                suggested_action="Verify correct emission factor is applied for this fuel/activity type.",
            )]
        return []


# ---------------------------------------------------------------------------
# Unit rules
# ---------------------------------------------------------------------------

class InvalidUnitRule(BaseRule):
    """
    Checks that the unit on a record is valid for its source type.
    An unexpected unit often means a unit conversion was missed.
    """
    code = RuleCode.INVALID_UNIT
    severity = Severity.ERROR

    def check(self, record, context: dict) -> list[ValidationIssue]:
        valid = VALID_UNITS.get(record.source_type, set())
        if valid and record.unit.lower() not in valid:
            return [ValidationIssue(
                rule_code=self.code,
                severity=self.severity,
                field_name="unit",
                message=(
                    f"Unit '{record.unit}' is not expected for source type "
                    f"'{record.source_type}'. Expected: {valid}"
                ),
                suggested_action="Check parser unit normalisation for this source type.",
            )]
        return []


# ---------------------------------------------------------------------------
# Date rules
# ---------------------------------------------------------------------------

class FutureDateRule(BaseRule):
    code = RuleCode.FUTURE_DATE
    severity = Severity.ERROR

    def check(self, record, context: dict) -> list[ValidationIssue]:
        if record.activity_date > date.today():
            return [ValidationIssue(
                rule_code=self.code,
                severity=self.severity,
                field_name="activity_date",
                message=(
                    f"Activity date {record.activity_date} is in the future. "
                    f"ESG records must represent past activity."
                ),
                suggested_action="Reject this record. Check source file for date entry errors.",
            )]
        return []


class ImplausibleDateRule(BaseRule):
    """
    Catches dates that are technically valid but implausible for ESG reporting.
    A fuel record from 1995 almost certainly means the year was typed wrong.
    """
    code = RuleCode.IMPLAUSIBLE_DATE
    severity = Severity.WARNING

    def check(self, record, context: dict) -> list[ValidationIssue]:
        if record.activity_date < EARLIEST_VALID_DATE:
            return [ValidationIssue(
                rule_code=self.code,
                severity=self.severity,
                field_name="activity_date",
                message=(
                    f"Activity date {record.activity_date} is before "
                    f"{EARLIEST_VALID_DATE}. Verify year is correct — "
                    f"possible two-digit year parsing error (e.g. '24' read as 1924)."
                ),
                suggested_action="Verify date with data owner. Reject if year is wrong.",
            )]
        return []


# ---------------------------------------------------------------------------
# Statistical outlier rule
# ---------------------------------------------------------------------------

class StatisticalOutlierRule(BaseRule):
    """
    Flags records whose quantity is more than 3 standard deviations
    from the mean for their source_type within this tenant's dataset.

    WHY 3 SIGMA:
    3σ captures ~99.7% of normal variation. Values outside this are
    statistically unusual enough to warrant human review.

    CONTEXT REQUIREMENT:
    Requires context["quantity_stats"][source_type] = {"mean": x, "stdev": y}
    This is pre-computed by ValidationService before running rules.

    TRADEOFF:
    Requires at least 10 records of the same type to compute meaningful stats.
    With fewer records, we skip this rule entirely rather than produce
    misleading thresholds.
    """
    code = RuleCode.STATISTICAL_OUTLIER
    severity = Severity.WARNING
    MIN_SAMPLE_SIZE = 10
    SIGMA_THRESHOLD = 3.0

    def check(self, record, context: dict) -> list[ValidationIssue]:
        stats = context.get("quantity_stats", {}).get(record.source_type)
        if not stats or stats.get("count", 0) < self.MIN_SAMPLE_SIZE:
            return []   # Not enough data — skip rule

        mean = stats["mean"]
        stdev = stats["stdev"]

        if stdev == 0:
            return []   # All values identical — no outlier detection possible

        quantity = float(record.quantity)
        z_score = abs(quantity - mean) / stdev

        if z_score > self.SIGMA_THRESHOLD:
            return [ValidationIssue(
                rule_code=self.code,
                severity=self.severity,
                field_name="quantity",
                message=(
                    f"Quantity {quantity} {record.unit} is {z_score:.1f} standard "
                    f"deviations from the mean ({mean:.1f} {record.unit}) for "
                    f"{record.source_type} records. "
                    f"This is statistically unusual."
                ),
                suggested_action=(
                    "Compare against previous periods. Approve if confirmed "
                    "(e.g. seasonal peak, new equipment), reject if data error."
                ),
            )]
        return []


# ---------------------------------------------------------------------------
# Duplicate detection rule
# ---------------------------------------------------------------------------

class DuplicateRecordRule(BaseRule):
    """
    Flags records that appear to duplicate an existing EmissionRecord
    in the database (not just within the current file — the parser handles that).

    Duplicate fingerprint: tenant + source_type + activity_date + quantity + unit
    Stored in context["existing_fingerprints"] by ValidationService.

    WHY THIS IS SEPARATE FROM PARSER DUPLICATE DETECTION:
    The parser catches duplicates within one file.
    This rule catches the same bill being re-uploaded in a new file next month.
    """
    code = RuleCode.DUPLICATE_RECORD
    severity = Severity.WARNING

    def check(self, record, context: dict) -> list[ValidationIssue]:
        existing = context.get("existing_fingerprints", set())
        fingerprint = (
            str(record.tenant_id),
            record.source_type,
            str(record.activity_date),
            str(record.quantity),
            record.unit,
        )
        if fingerprint in existing:
            return [ValidationIssue(
                rule_code=self.code,
                severity=self.severity,
                field_name="quantity",
                message=(
                    f"A record with identical source_type, date, quantity, and unit "
                    f"already exists in the database. Possible duplicate upload."
                ),
                suggested_action=(
                    "Check if this file was already imported. "
                    "Reject if confirmed duplicate."
                ),
            )]
        return []


# ---------------------------------------------------------------------------
# Rule registry — all rules that will be run by the ValidationService
# Order matters: errors first, then warnings
# ---------------------------------------------------------------------------

RULE_REGISTRY: list[BaseRule] = [
    # Errors — most serious first
    NegativeQuantityRule(),
    NegativeCO2eRule(),
    FutureDateRule(),
    InvalidUnitRule(),

    # Warnings
    ZeroQuantityRule(),
    ZeroEmissionFactorRule(),
    ImplausibleDateRule(),
    StatisticalOutlierRule(),
    DuplicateRecordRule(),
]
