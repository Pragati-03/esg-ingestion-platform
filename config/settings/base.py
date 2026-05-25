INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",  # needed for AuditLog's GenericForeignKey
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third party
    "rest_framework",

    # Your apps
    "apps.tenants",
    "apps.ingestion",
    "apps.emissions",
    "apps.audit",
]