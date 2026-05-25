import uuid
from django.db import models


class RawRecord(models.Model):
    """
    Immutable verbatim copy of a single row from the source file.

    WHY THIS EXISTS:
    This is the audit foundation of the entire platform. Every transformation,
    normalisation, and flagging decision we make downstream must be traceable
    back to exactly what we received. If an analyst disputes a CO2e figure,
    we can show them the raw source row that produced it.

    Without this table, the answer to 'what did the original SAP export say?'
    is 'we don't know' — which is disqualifying in any ESG audit context.

    DESIGN DECISIONS:
    - `raw_data` is a JSONField. Source files have inconsistent column names
      across clients and time. Storing the full row as JSON means we never
      lose data because a column wasn't in our schema, and we don't need
      a migration every time a new client sends a different export format.
    - `row_number` records the 1-based position in the source file. This
      lets an analyst open the original file and navigate to the exact row.
    - NO update allowed on this table. It is written once at ingestion and
      never modified. Downstream corrections happen on EmissionRecord only.
    - We deliberately do NOT store normalised or computed values here.
      Mixing raw and derived data on the same record destroys the audit trail.
    - `is_flagged` is a fast-lookup field. The full flag reason lives on
      EmissionRecord. This boolean exists purely to avoid a JOIN when
      counting flagged rows on the DataSource summary.

    IMMUTABILITY ENFORCEMENT:
    The model's save() is overridden to prevent updates after creation.
    This is belt-and-suspenders alongside database-level permissions — the
    application layer should never issue UPDATE on this table.

    TRADEOFF:
    JSONField is schema-less, which means we can't put DB-level NOT NULL
    constraints on individual source columns. That validation belongs in the
    parser layer, not the model layer. The raw record is a snapshot; the
    parser decides what's usable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    data_source = models.ForeignKey(
        "ingestion.DataSource",
        on_delete=models.PROTECT,  # PROTECT: never silently delete source records
        related_name="raw_records",
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        related_name="raw_records",
    )
    row_number = models.PositiveIntegerField()  # 1-based position in source file
    raw_data = models.JSONField()               # verbatim row from source file
    is_flagged = models.BooleanField(default=False)
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "raw_records"
        ordering = ["data_source", "row_number"]
        indexes = [
            models.Index(fields=["tenant", "data_source"]),
            models.Index(fields=["tenant", "is_flagged"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["data_source", "row_number"],
                name="unique_row_per_upload",
            )
        ]

    def save(self, *args, **kwargs):
        """
        Enforce immutability: raw records are write-once.
        Any attempt to update an existing record raises an error.
        """
        if self.pk and RawRecord.objects.filter(pk=self.pk).exists():
            raise ValueError(
                "RawRecord is immutable. Create a new record instead of updating."
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Row {self.row_number} of {self.data_source_id}"
