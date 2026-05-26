"""
Validation Layer — Core Types
------------------------------

WHY A SEPARATE VALIDATION LAYER:
The parsers already do row-level validation (missing fields, unknown units,
bad dates). But that's format validation — "can we read this row at all?"

This layer does semantic validation — "does this row make sense given
everything else we know?" It runs AFTER parsing and AFTER DB writes,
operating on EmissionRecord objects rather than raw CSV rows.

The distinction matters:
- Parser validation: "quantity field is empty" → flag before writing
- Semantic validation: "this quantity is 50x the site's monthly average" → flag after writing

Separating them keeps each concern testable and replaceable independently.

VALIDATION STATUS FLOW:
    pending_review
         │
         ├──[clean]──→ pending_review  (analyst approves → approved)
         │
         └──[issues]──→ flagged        (analyst reviews → approved or rejected)

We don't auto-approve anything. Validation only promotes TO flagged,
never directly to approved. Humans approve.
"""

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    """
    How serious is this validation issue?

    WARNING  — analyst should be aware but record is likely valid
    ERROR    — record is probably wrong; analyst must explicitly accept it
    """
    WARNING = "warning"
    ERROR = "error"


class RuleCode(str, Enum):
    """
    Machine-readable codes for each validation rule.
    Stable identifiers — safe to store in DB and filter on.
    """
    NEGATIVE_QUANTITY        = "negative_quantity"
    ZERO_QUANTITY            = "zero_quantity"
    MISSING_UNIT             = "missing_unit"
    INVALID_UNIT             = "invalid_unit"
    FUTURE_DATE              = "future_date"
    IMPLAUSIBLE_DATE         = "implausible_date"
    STATISTICAL_OUTLIER      = "statistical_outlier"
    DUPLICATE_RECORD         = "duplicate_record"
    UNKNOWN_AIRPORT          = "unknown_airport"
    SAME_ORIGIN_DESTINATION  = "same_origin_destination"
    NEGATIVE_CO2E            = "negative_co2e"
    ZERO_EMISSION_FACTOR     = "zero_emission_factor"
    CREDIT_NOTE              = "credit_note"
    EXCESSIVE_COST           = "excessive_cost"


@dataclass
class ValidationIssue:
    """One problem found by one rule on one record."""
    rule_code: RuleCode
    severity: Severity
    message: str              # human-readable, shown to analyst
    field_name: str = ""      # which field triggered this (for UI highlighting)
    suggested_action: str = ""  # what the analyst should do


@dataclass
class ValidationResult:
    """
    Outcome of running all rules against one EmissionRecord.
    Carried back to the service layer which decides what to write to DB.
    """
    record_id: str                          # EmissionRecord UUID
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == Severity.ERROR for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == Severity.WARNING for i in self.issues)

    @property
    def is_clean(self) -> bool:
        return not self.issues

    @property
    def worst_severity(self) -> Severity | None:
        if self.has_errors:
            return Severity.ERROR
        if self.has_warnings:
            return Severity.WARNING
        return None

    def primary_issue(self) -> ValidationIssue | None:
        """Return the most serious issue — used to set flag_type on EmissionRecord."""
        errors = [i for i in self.issues if i.severity == Severity.ERROR]
        if errors:
            return errors[0]
        return self.issues[0] if self.issues else None


class BaseRule:
    """
    All validation rules inherit from this.

    A rule receives one EmissionRecord and returns a list of
    ValidationIssues (empty = no problems found).

    WHY A CLASS PER RULE, NOT FUNCTIONS:
    Classes can carry configuration (thresholds, lookup tables) without
    polluting function signatures. They're also independently testable
    and can be enabled/disabled per tenant in future.
    """
    code: RuleCode
    severity: Severity

    def check(self, record, context: dict) -> list[ValidationIssue]:
        """
        Args:
            record: EmissionRecord instance
            context: dict of aggregate data (site averages, seen invoices, etc.)
                     populated by the ValidationService before running rules
        """
        raise NotImplementedError
