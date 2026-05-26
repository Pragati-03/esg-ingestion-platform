import uuid
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class GHGScope(models.IntegerChoices):
    SCOPE_1 = 1, "Scope 1 — Direct emissions"
    SCOPE_2 = 2, "Scope 2 — Purchased energy"
    SCOPE_3 = 3, "Scope 3 — Value chain"


class ApprovalStatus(models.TextChoices):
    PENDING_REVIEW = "pending_review", "Pending Review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    FLAGGED = "flagged", "Flagged — Needs Attention"


class FlagType(models.TextChoices):
    MISSING_VALUE = "missing_value", "Missing required value"
    OUT_OF_RANGE = "out_of_range", "Value out of plausible range"
    UNKNOWN_UNIT = "unknown_unit", "Unrecognised unit"
    FUTURE_DATE = "future_date", "Activity date is in the future"
    DUPLICATE = "duplicate", "Possible duplicate row"


class EmissionRecord(models.Model):
    """
    The normalised, analyst-facing representation of one emission activity.

    WHY THIS EXISTS:
    RawRecord preserves what we received. EmissionRecord represents what we
    understood from it — after parsing, unit conversion, scope assignment,
    and CO2e calculation. These are intentionally separate concerns.

    An analyst approves or rejects EmissionRecords, not RawRecords. The raw
    record is read-only evidence; this is the working record.

    DESIGN DECISIONS:
    - `raw_record` FK: every EmissionRecord traces back to exactly one source
      row. One-to-one in practice, but FK not OneToOneField because future
      aggregated records (e.g. monthly summaries) may cite multiple raws.
    - `quantity` + `unit` preserve the pre-conversion value for transparency.
      `co2e_kg` is always the canonical, unit-normalised output.
    - `emission_factor` and `emission_factor_source` are stored at calculation
      time. Factors change over time; we must know which factor was used to
      produce a given CO2e figure, or the audit trail is incomplete.
    - `scope` is assigned by the parser based on source_type. Scope 1 = fuel
      combustion (SAP), Scope 2 = purchased electricity (utility), Scope 3 =
      business travel. This mapping is deterministic and documented.
    - `status` drives the approval workflow. FLAGGED records require analyst
      review before they can be moved to APPROVED.
    - `flag_type` and `flag_reason` are nullable — only set when status=FLAGGED.
      Storing them on EmissionRecord (not a separate FlaggedRow table) keeps
      the common case simple and avoids a JOIN on every approval queue query.
    - `approved_by` and `approved_at` are the approval audit fields. These are
      set once and never changed. If a record is rejected then re-submitted,
      a new EmissionRecord is created, not the old one modified.
    - `analyst_note` allows an analyst to document why they approved or rejected
      a suspicious record. This is required for defensible ESG reporting.

    APPROVAL WORKFLOW:
    pending_review → approved        (clean record, analyst sign-off)
    pending_review → rejected        (analyst rejects)
    pending_review → flagged         (system flags, needs analyst attention)
    flagged        → approved        (analyst reviews flag and accepts)
    flagged        → rejected        (analyst reviews flag and rejects)

    TRADEOFF:
    We store flag information on EmissionRecord rather than a separate
    FlaggedRow table. This reduces JOIN complexity in the approval queue.
    If flagging logic becomes complex (multiple flags per record, flag
    resolution history), extract to a separate FlagEvent table at that point.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Source traceability
    raw_record = models.ForeignKey(
        "ingestion.RawRecord",
        on_delete=models.PROTECT,
        related_name="emission_records",
    )
    data_source = models.ForeignKey(
        "ingestion.DataSource",
        on_delete=models.PROTECT,
        related_name="emission_records",
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        related_name="emission_records",
    )

    # Normalised activity data
    source_type = models.CharField(max_length=20)   # denorm from DataSource for fast filtering
    activity_date = models.DateField()
    description = models.CharField(max_length=500, blank=True)

    # Pre-conversion values (for transparency)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit = models.CharField(max_length=50)          # e.g. 'litres', 'kWh', 'km'

    # Normalised output
    co2e_kg = models.DecimalField(max_digits=15, decimal_places=4)
    scope = models.IntegerField(choices=GHGScope.choices)

    # Emission factor audit trail
    emission_factor = models.DecimalField(
        max_digits=15, decimal_places=6,
        help_text="Factor applied to compute co2e_kg"
    )
    emission_factor_source = models.CharField(
        max_length=200,
        help_text="e.g. 'DEFRA 2023 — Natural Gas' or 'UK Grid Intensity Q3 2023'"
    )

    # Approval workflow
    status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING_REVIEW,
    )
    flag_type = models.CharField(
        max_length=30,
        choices=FlagType.choices,
        blank=True,
    )
    flag_reason = models.TextField(blank=True)      # human-readable explanation of flag
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_records",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    analyst_note = models.TextField(blank=True)     # analyst's sign-off comment

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "emission_records"
        ordering = ["-activity_date"]
        indexes = [
            # Core approval queue filter
            models.Index(fields=["tenant", "status"]),
            # Scope reporting
            models.Index(fields=["tenant", "scope", "activity_date"]),
            # Source drill-down
            models.Index(fields=["tenant", "source_type"]),
            # Date range queries for dashboards
            models.Index(fields=["tenant", "activity_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(co2e_kg__gte=0),
                name="co2e_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(scope__in=[1, 2, 3]),
                name="valid_ghg_scope",
            ),
        ]

    def __str__(self):
        return (
            f"{self.source_type} | {self.activity_date} | "
            f"{self.co2e_kg} kg CO2e | {self.status}"
        )
