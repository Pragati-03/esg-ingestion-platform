"""
Serializers
------------

DESIGN PRINCIPLES:
- One serializer per use case, not one per model
- Read serializers are verbose (frontend needs the data)
- Write serializers are strict (only accept what we expect)
- No nested writes — keep mutations flat and explicit

WHY NOT ModelSerializer FOR EVERYTHING:
ModelSerializer is convenient but exposes too many fields by default.
We define fields explicitly so the API contract is clear and stable.
Adding a field to a model doesn't accidentally expose it to the frontend.
"""

from rest_framework import serializers
from ingestion.models import DataSource, RawRecord
from emissions.models import EmissionRecord, ApprovalStatus


# ---------------------------------------------------------------------------
# DataSource (Upload) serializers
# ---------------------------------------------------------------------------

class DataSourceUploadSerializer(serializers.ModelSerializer):
    """
    Write serializer — used for POST /uploads/
    Only accepts file and source_type. Everything else is set by the service.
    """
    class Meta:
        model = DataSource
        fields = ["source_type", "file"]

    def validate_source_type(self, value):
        valid = {"sap_fuel", "utility", "travel"}
        if value not in valid:
            raise serializers.ValidationError(
                f"source_type must be one of {valid}"
            )
        return value

    def validate_file(self, value):
        # 50MB hard limit — large enough for any realistic quarterly export
        max_size = 50 * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError(
                "File exceeds 50MB limit. Split large exports before uploading."
            )
        allowed_extensions = {".csv", ".xlsx", ".xls"}
        name = value.name.lower()
        if not any(name.endswith(ext) for ext in allowed_extensions):
            raise serializers.ValidationError(
                f"File type not supported. Allowed: {allowed_extensions}"
            )
        return value


class DataSourceListSerializer(serializers.ModelSerializer):
    """
    Read serializer — used for GET /uploads/
    Analyst-facing summary — no file path exposed.
    """
    uploaded_by_name = serializers.SerializerMethodField()
    approval_progress = serializers.SerializerMethodField()

    class Meta:
        model = DataSource
        fields = [
            "id",
            "source_type",
            "original_filename",
            "status",
            "row_count",
            "flagged_count",
            "uploaded_by_name",
            "approval_progress",
            "created_at",
            "completed_at",
            "error_message",
        ]

    def get_uploaded_by_name(self, obj):
        if obj.uploaded_by:
            return obj.uploaded_by.get_full_name() or obj.uploaded_by.email
        return None

    def get_approval_progress(self, obj):
        """
        Returns how many records in this upload have been approved/rejected.
        Gives analysts a progress indicator on the review queue.

        WHY ANNOTATE HERE NOT ON MODEL:
        This is a read-time calculation for the UI. It doesn't belong on
        the model. In production, cache this on DataSource as a denorm field
        if it becomes a performance concern.
        """
        records = obj.emission_records.all()
        total = records.count()
        if total == 0:
            return None
        approved = records.filter(status=ApprovalStatus.APPROVED).count()
        rejected = records.filter(status=ApprovalStatus.REJECTED).count()
        return {
            "total": total,
            "approved": approved,
            "rejected": rejected,
            "pending": total - approved - rejected,
        }


class DataSourceDetailSerializer(DataSourceListSerializer):
    """
    Extends list serializer with per-scope CO2e breakdown.
    Used for GET /uploads/{id}/
    """
    scope_summary = serializers.SerializerMethodField()

    class Meta(DataSourceListSerializer.Meta):
        fields = DataSourceListSerializer.Meta.fields + ["scope_summary"]

    def get_scope_summary(self, obj):
        from django.db.models import Sum
        result = {}
        for scope in [1, 2, 3]:
            total = obj.emission_records.filter(
                scope=scope,
                status=ApprovalStatus.APPROVED,
            ).aggregate(total=Sum("co2e_kg"))["total"]
            if total:
                result[f"scope_{scope}_co2e_kg"] = float(total)
        return result


# ---------------------------------------------------------------------------
# EmissionRecord serializers
# ---------------------------------------------------------------------------

class EmissionRecordListSerializer(serializers.ModelSerializer):
    """
    Read serializer for the records list and approval queue.
    Includes raw_data from the source row for analyst reference.
    """
    raw_data = serializers.SerializerMethodField()
    data_source_filename = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = EmissionRecord
        fields = [
            "id",
            "source_type",
            "activity_date",
            "description",
            "quantity",
            "unit",
            "co2e_kg",
            "scope",
            "emission_factor",
            "emission_factor_source",
            "status",
            "flag_type",
            "flag_reason",
            "analyst_note",
            "approved_by_name",
            "approved_at",
            "data_source_filename",
            "raw_data",
            "created_at",
        ]

    def get_raw_data(self, obj):
        # Expose raw source row so analyst can verify against original file
        return obj.raw_record.raw_data if obj.raw_record_id else None

    def get_data_source_filename(self, obj):
        return obj.data_source.original_filename if obj.data_source_id else None

    def get_approved_by_name(self, obj):
        if obj.approved_by:
            return obj.approved_by.get_full_name() or obj.approved_by.email
        return None


# ---------------------------------------------------------------------------
# Approval workflow serializers
# ---------------------------------------------------------------------------

class ApproveRecordSerializer(serializers.Serializer):
    """
    Write serializer for POST /records/{id}/approve/

    WHY NOT ModelSerializer:
    Approval is a state transition, not a model update.
    We accept only the analyst's note — everything else is set by the view.
    """
    analyst_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text="Optional note explaining why this record was approved",
    )


class RejectRecordSerializer(serializers.Serializer):
    """
    Write serializer for POST /records/{id}/reject/
    Rejection requires a reason — this is enforced for audit trail quality.
    """
    analyst_note = serializers.CharField(
        required=True,
        min_length=10,
        max_length=1000,
        help_text="Required: explain why this record is being rejected",
    )


class BulkApproveSerializer(serializers.Serializer):
    """
    Write serializer for POST /records/bulk-approve/
    Allows analysts to approve multiple clean records at once.

    WHY BULK APPROVE EXISTS:
    A typical monthly SAP upload has 200-500 rows, most of which are clean.
    Requiring one API call per record makes the approval workflow unusable.
    Bulk approve handles the common case; individual approve handles flagged records.
    """
    record_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=500,    # hard cap — prevents accidental bulk approval of entire dataset
        help_text="List of EmissionRecord UUIDs to approve",
    )
    analyst_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
    )

    def validate_record_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate record IDs in list.")
        return value
