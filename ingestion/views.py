"""
API Views
----------

DESIGN PHILOSOPHY:
- Views are thin — business logic lives in services
- Each view does one thing
- Filtering is explicit, not magic
- Error responses are consistent

URL STRUCTURE:
    /api/{tenant_slug}/uploads/                    GET, POST
    /api/{tenant_slug}/uploads/{id}/               GET
    /api/{tenant_slug}/records/                    GET
    /api/{tenant_slug}/records/flagged/            GET
    /api/{tenant_slug}/records/{id}/               GET
    /api/{tenant_slug}/records/{id}/approve/       POST
    /api/{tenant_slug}/records/{id}/reject/        POST
    /api/{tenant_slug}/records/bulk-approve/       POST

WHY NO VIEWSETS:
ViewSets are convenient but they generate routes automatically, which
makes the API harder to reason about. Explicit views + explicit routes
is more defensible in a technical review.
"""

import logging
from django.utils import timezone
from django.db.models import Sum
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated

from tenants.middleware import TenantMixin
from ingestion.models import DataSource, IngestionStatus
from emissions.models import EmissionRecord, ApprovalStatus
from audit.models import AuditLog, EventType
from .serializers import (
    DataSourceUploadSerializer,
    DataSourceListSerializer,
    DataSourceDetailSerializer,
    EmissionRecordListSerializer,
    ApproveRecordSerializer,
    RejectRecordSerializer,
    BulkApproveSerializer,
)
from .service import ingest_data_source

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Upload endpoints
# ---------------------------------------------------------------------------

class UploadListView(TenantMixin, APIView):
    """
    GET  /api/{tenant_slug}/uploads/   — list all uploads for this tenant
    POST /api/{tenant_slug}/uploads/   — upload a new file and trigger ingestion
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, tenant_slug):
        uploads = DataSource.objects.filter(
            tenant=self.tenant
        ).select_related("uploaded_by").order_by("-created_at")

        # Optional filter by status
        status_filter = request.query_params.get("status")
        if status_filter:
            uploads = uploads.filter(status=status_filter)

        # Optional filter by source_type
        source_filter = request.query_params.get("source_type")
        if source_filter:
            uploads = uploads.filter(source_type=source_filter)

        serializer = DataSourceListSerializer(uploads, many=True)
        return Response({
            "count": uploads.count(),
            "results": serializer.data,
        })

    def post(self, request, tenant_slug):
        serializer = DataSourceUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        file = serializer.validated_data["file"]
        source_type = serializer.validated_data["source_type"]

        # Create DataSource record
        data_source = DataSource.objects.create(
            tenant=self.tenant,
            uploaded_by=request.user,
            source_type=source_type,
            original_filename=file.name,
            file=file,
            status=IngestionStatus.PENDING,
        )

        # Write audit event for upload start
        AuditLog.objects.create(
            tenant=self.tenant,
            actor=request.user,
            actor_email_snapshot=request.user.email,
            event_type=EventType.UPLOAD_STARTED,
            delta={"source_type": source_type, "filename": file.name},
            description=f"Upload started: {file.name}",
            ip_address=self._get_client_ip(request),
        )

        # Run ingestion synchronously
        # WHY SYNCHRONOUS: See ingestion/service.py for full explanation.
        # For files <10k rows this completes in <2 seconds.
        data_source = ingest_data_source(data_source, actor=request.user)

        response_serializer = DataSourceDetailSerializer(data_source)
        http_status = (
            status.HTTP_201_CREATED
            if data_source.status == IngestionStatus.DONE
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return Response(response_serializer.data, status=http_status)

    def _get_client_ip(self, request):
        x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded:
            return x_forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


class UploadDetailView(TenantMixin, APIView):
    """
    GET /api/{tenant_slug}/uploads/{upload_id}/
    Returns full detail including scope breakdown and approval progress.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, tenant_slug, upload_id):
        data_source = self._get_upload(upload_id)
        serializer = DataSourceDetailSerializer(data_source)
        return Response(serializer.data)

    def _get_upload(self, upload_id):
        try:
            return DataSource.objects.select_related("uploaded_by").get(
                id=upload_id,
                tenant=self.tenant,
            )
        except DataSource.DoesNotExist:
            from django.http import Http404
            raise Http404


# ---------------------------------------------------------------------------
# Records endpoints
# ---------------------------------------------------------------------------

class RecordListView(TenantMixin, APIView):
    """
    GET /api/{tenant_slug}/records/

    Query params:
        status         — filter by approval status
        source_type    — filter by source
        scope          — filter by GHG scope (1, 2, 3)
        upload_id      — filter by parent upload
        date_from      — activity_date >= (YYYY-MM-DD)
        date_to        — activity_date <= (YYYY-MM-DD)

    WHY EXPLICIT QUERY PARAMS OVER django-filter:
    django-filter is powerful but adds a dependency and generates
    magic filtering behaviour. Explicit params are readable and
    easy to document for the frontend developer.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, tenant_slug):
        records = EmissionRecord.objects.filter(
            tenant=self.tenant
        ).select_related(
            "raw_record", "data_source", "approved_by"
        ).order_by("-activity_date")

        # Apply filters
        records = self._apply_filters(records, request.query_params)

        # Simple pagination — offset/limit
        limit = min(int(request.query_params.get("limit", 50)), 200)
        offset = int(request.query_params.get("offset", 0))
        total = records.count()
        page = records[offset:offset + limit]

        serializer = EmissionRecordListSerializer(page, many=True)
        return Response({
            "count": total,
            "limit": limit,
            "offset": offset,
            "results": serializer.data,
        })

    def _apply_filters(self, qs, params):
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("source_type"):
            qs = qs.filter(source_type=params["source_type"])
        if params.get("scope"):
            qs = qs.filter(scope=params["scope"])
        if params.get("upload_id"):
            qs = qs.filter(data_source_id=params["upload_id"])
        if params.get("date_from"):
            qs = qs.filter(activity_date__gte=params["date_from"])
        if params.get("date_to"):
            qs = qs.filter(activity_date__lte=params["date_to"])
        return qs


class FlaggedRecordListView(TenantMixin, APIView):
    """
    GET /api/{tenant_slug}/records/flagged/

    Dedicated endpoint for the analyst approval queue.
    Only returns flagged records — this is the primary analyst workflow view.

    WHY A SEPARATE ENDPOINT (not just ?status=flagged):
    The approval queue has different sorting (oldest first — work through
    the queue) and different default fields than the general records list.
    Separating it makes the frontend integration explicit.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, tenant_slug):
        records = EmissionRecord.objects.filter(
            tenant=self.tenant,
            status=ApprovalStatus.FLAGGED,
        ).select_related(
            "raw_record", "data_source", "approved_by"
        ).order_by("created_at")   # oldest flagged first

        # Optional filter by source_type
        source_filter = request.query_params.get("source_type")
        if source_filter:
            records = records.filter(source_type=source_filter)

        total = records.count()
        limit = min(int(request.query_params.get("limit", 50)), 200)
        offset = int(request.query_params.get("offset", 0))
        page = records[offset:offset + limit]

        serializer = EmissionRecordListSerializer(page, many=True)
        return Response({
            "count": total,
            "limit": limit,
            "offset": offset,
            "results": serializer.data,
        })


class RecordDetailView(TenantMixin, APIView):
    """
    GET /api/{tenant_slug}/records/{record_id}/
    Full detail including raw source row.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, tenant_slug, record_id):
        record = self._get_record(record_id)
        serializer = EmissionRecordListSerializer(record)
        return Response(serializer.data)

    def _get_record(self, record_id):
        try:
            return EmissionRecord.objects.select_related(
                "raw_record", "data_source", "approved_by"
            ).get(id=record_id, tenant=self.tenant)
        except EmissionRecord.DoesNotExist:
            from django.http import Http404
            raise Http404


# ---------------------------------------------------------------------------
# Approval workflow endpoints
# ---------------------------------------------------------------------------

class ApproveRecordView(TenantMixin, APIView):
    """
    POST /api/{tenant_slug}/records/{record_id}/approve/

    Transitions a record from pending_review or flagged → approved.
    Writes audit log entry.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, tenant_slug, record_id):
        record = self._get_record(record_id)

        # Guard: can only approve pending or flagged records
        if record.status == ApprovalStatus.APPROVED:
            return Response(
                {"detail": "Record is already approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if record.status == ApprovalStatus.REJECTED:
            return Response(
                {"detail": "Rejected records cannot be approved. Create a new record instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ApproveRecordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        previous_status = record.status

        record.status = ApprovalStatus.APPROVED
        record.approved_by = request.user
        record.approved_at = timezone.now()
        record.analyst_note = serializer.validated_data.get("analyst_note", "")
        record.save(update_fields=[
            "status", "approved_by", "approved_at", "analyst_note", "updated_at"
        ])

        AuditLog.objects.create(
            tenant=self.tenant,
            actor=request.user,
            actor_email_snapshot=request.user.email,
            event_type=EventType.RECORD_APPROVED,
            delta={
                "before": {"status": previous_status},
                "after": {"status": "approved"},
                "analyst_note": record.analyst_note,
            },
            description=f"Record approved by {request.user.email}",
        )

        return Response(
            EmissionRecordListSerializer(record).data,
            status=status.HTTP_200_OK,
        )

    def _get_record(self, record_id):
        try:
            return EmissionRecord.objects.select_related(
                "raw_record", "data_source", "approved_by"
            ).get(id=record_id, tenant=self.tenant)
        except EmissionRecord.DoesNotExist:
            from django.http import Http404
            raise Http404


class RejectRecordView(TenantMixin, APIView):
    """
    POST /api/{tenant_slug}/records/{record_id}/reject/
    Transitions a record to rejected. Requires analyst_note.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, tenant_slug, record_id):
        record = self._get_record(record_id)

        if record.status == ApprovalStatus.REJECTED:
            return Response(
                {"detail": "Record is already rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if record.status == ApprovalStatus.APPROVED:
            return Response(
                {"detail": "Approved records cannot be rejected directly. Contact your administrator."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RejectRecordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        previous_status = record.status

        record.status = ApprovalStatus.REJECTED
        record.approved_by = request.user
        record.approved_at = timezone.now()
        record.analyst_note = serializer.validated_data["analyst_note"]
        record.save(update_fields=[
            "status", "approved_by", "approved_at", "analyst_note", "updated_at"
        ])

        AuditLog.objects.create(
            tenant=self.tenant,
            actor=request.user,
            actor_email_snapshot=request.user.email,
            event_type=EventType.RECORD_REJECTED,
            delta={
                "before": {"status": previous_status},
                "after": {"status": "rejected"},
                "analyst_note": record.analyst_note,
            },
            description=f"Record rejected by {request.user.email}: {record.analyst_note[:100]}",
        )

        return Response(
            EmissionRecordListSerializer(record).data,
            status=status.HTTP_200_OK,
        )

    def _get_record(self, record_id):
        try:
            return EmissionRecord.objects.select_related(
                "raw_record", "data_source", "approved_by"
            ).get(id=record_id, tenant=self.tenant)
        except EmissionRecord.DoesNotExist:
            from django.http import Http404
            raise Http404


class BulkApproveView(TenantMixin, APIView):
    """
    POST /api/{tenant_slug}/records/bulk-approve/

    Approves multiple records in one request.
    Only approves pending_review records — skips already-approved or flagged.

    WHY SKIP FLAGGED ON BULK:
    Flagged records need individual analyst attention. Bulk approve is for
    the common case: analyst scans a list of clean records and approves all.
    Flagged records must go through individual approve with a note.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, tenant_slug):
        serializer = BulkApproveSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        record_ids = serializer.validated_data["record_ids"]
        analyst_note = serializer.validated_data.get("analyst_note", "")

        # Only approve pending_review records from this tenant
        records = EmissionRecord.objects.filter(
            id__in=record_ids,
            tenant=self.tenant,
            status=ApprovalStatus.PENDING_REVIEW,
        )

        approved_ids = list(records.values_list("id", flat=True))
        skipped_count = len(record_ids) - len(approved_ids)

        now = timezone.now()
        records.update(
            status=ApprovalStatus.APPROVED,
            approved_by=request.user,
            approved_at=now,
            analyst_note=analyst_note,
        )

        AuditLog.objects.create(
            tenant=self.tenant,
            actor=request.user,
            actor_email_snapshot=request.user.email,
            event_type=EventType.RECORD_APPROVED,
            delta={
                "approved_count": len(approved_ids),
                "skipped_count": skipped_count,
                "record_ids": [str(i) for i in approved_ids],
                "analyst_note": analyst_note,
            },
            description=(
                f"Bulk approval: {len(approved_ids)} records approved by {request.user.email}. "
                f"{skipped_count} skipped (already approved or flagged)."
            ),
        )

        return Response({
            "approved_count": len(approved_ids),
            "skipped_count": skipped_count,
            "detail": (
                f"{len(approved_ids)} records approved."
                + (f" {skipped_count} skipped (not in pending_review status)."
                   if skipped_count else "")
            ),
        }, status=status.HTTP_200_OK)
