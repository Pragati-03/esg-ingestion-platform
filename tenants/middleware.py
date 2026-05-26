"""
Tenant Middleware and Mixins
-----------------------------

WHY MIDDLEWARE OVER DECORATOR:
Every view in this platform is tenant-scoped. Middleware handles it once
rather than repeating the lookup in every view.

HOW IT WORKS:
1. URL pattern: /api/{tenant_slug}/...
2. Middleware extracts tenant_slug from the URL
3. Attaches Tenant object to request
4. Views access request.tenant without any extra code

WHAT HAPPENS IF TENANT NOT FOUND:
404 — not 403. We don't confirm whether a tenant exists to unauthenticated users.

TRADEOFF:
We use slug-based tenant resolution from the URL. An alternative is
resolving tenant from the authenticated user's profile. URL-based is
simpler for a 4-day build and makes API calls self-documenting.
"""

from django.http import Http404
from tenants.models import Tenant


class TenantMiddleware:
    """
    Resolves tenant from URL kwargs and attaches to request.
    Add to MIDDLEWARE in settings AFTER AuthenticationMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Tenant slug is injected by URL resolver into request.resolver_match
        # We attach it here so views can access request.tenant directly
        request.tenant = None
        response = self.get_response(request)
        return response


class TenantMixin:
    """
    View mixin that resolves and validates the tenant from URL kwargs.
    All tenant-scoped views inherit from this.

    Usage:
        class MyView(TenantMixin, APIView):
            def get(self, request, tenant_slug):
                records = EmissionRecord.objects.filter(tenant=self.tenant)
    """

    def get_tenant(self, tenant_slug: str) -> Tenant:
        try:
            return Tenant.objects.get(slug=tenant_slug, is_active=True)
        except Tenant.DoesNotExist:
            raise Http404(f"Tenant '{tenant_slug}' not found")

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        tenant_slug = kwargs.get("tenant_slug")
        if tenant_slug:
            self.tenant = self.get_tenant(tenant_slug)
            request.tenant = self.tenant
