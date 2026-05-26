import uuid
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class SourceType(models.TextChoices):
    SAP_FUEL = "sap_fuel", "SAP Fuel / Procurement"
    UTILITY = "utility", "Utility Electricity"
    TRAVEL = "travel", "Corporate Travel"


class IngestionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"


class DataSource(models.Model):
    """
    Represents a single file upload / ingestion event.

    WHY THIS EXISTS:
    We need a parent record that groups all rows from one import together.
    This lets analysts see 'the July utility upload had 240 rows, 12 flagged'
    at a glance, without querying RawRecord directly.

    It also gives us a clean place to track processing state without
    polluting RawRecord or EmissionRecord with upload-level metadata.

    DESIGN DECISIONS:
    - `source_type` drives which parser is invoked. The parser registry
      maps this enum to the correct class (SAPFuelParser, UtilityParser, etc.)
    - `original_filename` is stored for auditability — analysts need to know
      which file a set of records came from.
    - `row_count` and `flagged_count` are denormalised summaries. Yes, they
      can be derived by COUNT queries, but they are read constantly on the
      uploads list view and not worth re-computing on every page load.
    - `status` tracks the lifecycle of the ingestion job itself, separate
      from the approval status of individual records.
    - `checksum` (SHA-256 of the file) prevents double-ingestion of the same
      export. Enterprise users frequently re-upload the same file.

    TRADEOFF:
    We store the file reference (path/URL) rather than file content. If using
    Django's FileField with S3/local storage, this is standard. Raw file bytes
    do not belong in PostgreSQL.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        related_name="data_sources",
    )
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploads",
    )
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    original_filename = models.CharField(max_length=500)
    file = models.FileField(upload_to="uploads/%Y/%m/")
    checksum = models.CharField(max_length=64, blank=True)  # SHA-256 hex
    status = models.CharField(
        max_length=20,
        choices=IngestionStatus.choices,
        default=IngestionStatus.PENDING,
    )
    row_count = models.PositiveIntegerField(default=0)
    flagged_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)  # populated on status=failed
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "data_sources"
        ordering = ["-created_at"]
        # Prevent re-ingestion of identical files per tenant
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "checksum"],
                name="unique_upload_per_tenant",
                condition=models.Q(checksum__gt=""),  # only enforce when checksum present
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "source_type"]),
        ]

    def __str__(self):
        return f"{self.source_type} — {self.original_filename} ({self.status})"
