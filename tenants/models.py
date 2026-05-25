import uuid
from django.db import models


class Tenant(models.Model):
    """
    Represents a client organisation using the platform.

    WHY THIS EXISTS:
    Every meaningful query in this system is scoped to a tenant. Rather than
    relying on URL namespacing alone, we carry tenant_id as a FK on every
    major table. This means a misconfigured view cannot accidentally leak
    cross-tenant data — the queryset filter is the last line of defence.

    DESIGN DECISIONS:
    - UUIDs as primary keys so tenant IDs are safe to expose in URLs/APIs
      without revealing record counts or insertion order.
    - `slug` enables human-readable URLs (/api/acme-corp/uploads/) without
      exposing internal IDs.
    - `is_active` is a soft-disable. Deactivating a tenant suspends access
      without destroying audit history — important for contractual offboarding.
    - No CASCADE deletes. Tenant data must be explicitly purged, never
      accidentally lost.

    TRADEOFF:
    We use a shared schema (single DB, tenant_id FK) rather than schema-per-
    tenant or DB-per-tenant. This is appropriate for a 4-day build and for
    tenants with similar scale. Schema-per-tenant adds migration complexity
    that isn't justified here.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenants"
        ordering = ["name"]

    def __str__(self):
        return self.name
