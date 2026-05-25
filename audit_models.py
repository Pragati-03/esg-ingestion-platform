import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

User = get_user_model()


class EventType(models.TextChoices):
    # Ingestion events
    UPLOAD_STARTED = "upload_started", "Upload Started"
    UPLOAD_COMPLETED = "upload_completed", "Upload Completed"
    UPLOAD_FAILED = "upload_failed", "Upload Failed"

    # Record events
    RECORD_CREATED = "record_created", "Emission Record Created"
    RECORD_FLAGGED = "record_flagged", "Record Flagged"
    RECORD_APPROVED = "record_approved", "Record Approved"
    RECORD_REJECTED = "record_rejected", "Record Rejected"

    # Admin events
    TENANT_CREATED = "tenant_created", "Tenant Created"
    USER_PERMISSION_CHANGED = "user_permission_changed", "User Permission Changed"


class AuditLog(models.Model):
    """
    Append-only log of every significant action in the system.

    WHY THIS EXISTS:
    ESG data is submitted to regulators, boards, and third-party verifiers.
    Any question of 'who changed this, and when?' must be answerable with
    certainty. The audit log is that certainty.

    It is also the primary defence against internal data manipulation. If
    an emission record's CO2e changes between ingestion and final reporting,
    the audit log explains exactly why.

    DESIGN DECISIONS:
    - Append-only: no update or delete on this table, ever. Enforced in
      save() and should also be enforced at the DB role level in production.
    - `actor` is SET_NULL on user deletion, not CASCADE. We must retain the
      audit record even if a user account is deleted — the action happened.
    - GenericForeignKey via ContentType allows us to point at any model
      (DataSource, EmissionRecord, Tenant) without separate FK columns per
      type. This is the standard Django pattern for polymorphic audit logs.
    - `delta` is a JSONField storing before/after state as a dict:
        {"before": {"status": "pending_review"}, "after": {"status": "approved"}}
      This is the most useful format for an auditor — they see what changed,
      not just that a change occurred.
    - `ip_address` is captured at the view layer and passed in. Useful for
      security investigations.
    - `actor_email_snapshot` stores the actor's email at the time of the event.
      If a user is renamed or deleted, the audit trail remains readable.
    - No FKs to tenant on audit events for actor-system events (like
      TENANT_CREATED). For all resource events, tenant is recorded via
      the target object's relationship.

    WHAT TRIGGERS AN AUDIT EVENT:
    Audit events are written by Django signals or explicit service calls —
    NOT by model save() hooks. This keeps models lean and makes it easy to
    test business logic without triggering audit side-effects.

    TRADEOFF:
    GenericForeignKey is convenient but means we lose referential integrity
    on the `object_id` column — a deleted object leaves a dangling reference.
    This is acceptable: audit logs should outlive the objects they describe.
    An alternative is separate AuditLog subclasses per domain object, but
    that's unnecessary complexity for this scope.

    PRODUCTION NOTE:
    In production, this table should be in a separate DB schema or database
    with a write-only application role. For this build, same schema is fine.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        null=True,          # null for system-level events (e.g. tenant creation)
        blank=True,
        related_name="audit_logs",
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_actions",
    )
    actor_email_snapshot = models.EmailField(blank=True)  # preserved if user is deleted
    event_type = models.CharField(max_length=50, choices=EventType.choices)

    # Generic pointer to any model instance
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    object_id = models.UUIDField(null=True, blank=True)
    target = GenericForeignKey("content_type", "object_id")

    # What changed
    delta = models.JSONField(
        default=dict,
        help_text='{"before": {...}, "after": {...}}'
    )
    description = models.TextField(blank=True)  # human-readable summary

    # Request context
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "event_type"]),
            models.Index(fields=["tenant", "created_at"]),
            models.Index(fields=["actor"]),
            # Support queries like 'all audit events for EmissionRecord X'
            models.Index(fields=["content_type", "object_id"]),
        ]

    def save(self, *args, **kwargs):
        """
        Enforce append-only: audit log records cannot be updated.
        """
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise ValueError(
                "AuditLog is append-only. Records cannot be modified after creation."
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.event_type} by {self.actor_email_snapshot} at {self.created_at}"
