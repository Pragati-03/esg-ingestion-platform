"""
URL Configuration
------------------

All routes are prefixed with /api/{tenant_slug}/ for multi-tenancy.

WHY TENANT IN URL (NOT HEADER OR SUBDOMAIN):
- URL-based: simplest to implement, easiest to test, no special DNS needed
- Header-based (X-Tenant-ID): cleaner URLs but harder to test in browser
- Subdomain-based: best UX but requires wildcard DNS + SSL — overkill here

ROUTE MAP:
    POST   /api/{tenant}/uploads/                      Upload file + trigger ingestion
    GET    /api/{tenant}/uploads/                      List all uploads
    GET    /api/{tenant}/uploads/{id}/                 Upload detail + scope summary

    GET    /api/{tenant}/records/                      All records (filterable)
    GET    /api/{tenant}/records/flagged/              Analyst approval queue
    GET    /api/{tenant}/records/{id}/                 Record detail

    POST   /api/{tenant}/records/{id}/approve/         Approve one record
    POST   /api/{tenant}/records/{id}/reject/          Reject one record
    POST   /api/{tenant}/records/bulk-approve/         Approve many at once
"""

from django.urls import path
from .views import (
    UploadListView,
    UploadDetailView,
    RecordListView,
    FlaggedRecordListView,
    RecordDetailView,
    ApproveRecordView,
    RejectRecordView,
    BulkApproveView,
)

# These are included under /api/{tenant_slug}/ in the root urls.py
urlpatterns = [
    # Upload endpoints
    path("uploads/", UploadListView.as_view(), name="upload-list"),
    path("uploads/<uuid:upload_id>/", UploadDetailView.as_view(), name="upload-detail"),

    # Record endpoints
    path("records/", RecordListView.as_view(), name="record-list"),
    path("records/flagged/", FlaggedRecordListView.as_view(), name="record-flagged"),
    path("records/bulk-approve/", BulkApproveView.as_view(), name="record-bulk-approve"),
    path("records/<uuid:record_id>/", RecordDetailView.as_view(), name="record-detail"),
    path("records/<uuid:record_id>/approve/", ApproveRecordView.as_view(), name="record-approve"),
    path("records/<uuid:record_id>/reject/", RejectRecordView.as_view(), name="record-reject"),
]
