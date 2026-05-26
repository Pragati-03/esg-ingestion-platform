"""
Root URL Configuration
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),

    # All ESG API endpoints — tenant-scoped
    path(
        "api/<slug:tenant_slug>/",
        include("ingestion.urls"),
    ),
]
