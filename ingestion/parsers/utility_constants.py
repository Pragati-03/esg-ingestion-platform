"""
Utility Electricity Parser — Constants
---------------------------------------

WHY SEPARATE FROM SAP CONSTANTS:
Each source type has completely different column names, units, and validation
rules. Keeping constants per-parser makes each parser self-contained and
independently testable.
"""

# ---------------------------------------------------------------------------
# Column aliases
# Utility portal exports vary significantly by supplier.
# E.ON, Vattenfall, British Gas, EDF all use different column names for
# the same data. This table covers the most common variants.
# ---------------------------------------------------------------------------
COLUMN_ALIASES = {
    # Account
    "account_id": "account_id",
    "account": "account_id",
    "account_number": "account_id",
    "accountid": "account_id",

    # Meter
    "meter_id": "meter_id",
    "meter": "meter_id",
    "mpan": "meter_id",           # UK Master Point Access Number
    "meter_serial": "meter_id",
    "meternumber": "meter_id",

    # Site
    "site_name": "site_name",
    "site": "site_name",
    "location": "site_name",
    "premises": "site_name",
    "property": "site_name",

    # Billing period
    "billing_period_start": "period_start",
    "period_start": "period_start",
    "bill_start": "period_start",
    "from": "period_start",
    "start_date": "period_start",
    "read_date_from": "period_start",

    "billing_period_end": "period_end",
    "period_end": "period_end",
    "bill_end": "period_end",
    "to": "period_end",
    "end_date": "period_end",
    "read_date_to": "period_end",

    # Usage
    "usage_kwh": "usage_kwh",
    "kwh": "usage_kwh",
    "consumption_kwh": "usage_kwh",
    "units_consumed": "usage_kwh",
    "consumption": "usage_kwh",
    "energy_kwh": "usage_kwh",

    # Demand
    "demand_kw": "demand_kw",
    "peak_demand_kw": "demand_kw",
    "max_demand": "demand_kw",
    "kva": "demand_kw",           # sometimes suppliers use kVA instead of kW

    # Tariff
    "tariff_code": "tariff_code",
    "tariff": "tariff_code",
    "rate_code": "tariff_code",
    "product_code": "tariff_code",

    # Supplier
    "supplier": "supplier",
    "utility_provider": "supplier",
    "provider": "supplier",

    # Invoice
    "invoice_number": "invoice_number",
    "invoice_no": "invoice_number",
    "bill_reference": "invoice_number",
    "invoice_ref": "invoice_number",

    # Cost
    "cost_gbp": "cost_gbp",
    "cost": "cost_gbp",
    "amount_gbp": "cost_gbp",
    "total_cost": "cost_gbp",
    "charge_gbp": "cost_gbp",
}

REQUIRED_COLUMNS = {"meter_id", "period_start", "period_end", "usage_kwh"}

# ---------------------------------------------------------------------------
# Date formats
# Utility portals use inconsistent date formats even within the same supplier.
# ---------------------------------------------------------------------------
DATE_FORMATS = [
    "%d/%m/%Y",     # 01/01/2024 — UK/EU standard
    "%Y-%m-%d",     # 2024-01-01 — ISO 8601
    "%d-%m-%Y",     # 01-01-2024 — variant
    "%m/%d/%Y",     # 01/31/2024 — US format (rare but seen)
    "%d %b %Y",     # 01 Jan 2024 — some PDF-extracted formats
    "%Y/%m/%d",     # 2024/01/01 — another variant
]

# ---------------------------------------------------------------------------
# Grid emission factors (kg CO2e per kWh)
# These are country/region-specific and change annually.
#
# WHY STORED HERE:
# In production these would be a DB table versioned by year and region.
# For this build, inline constants are honest and testable.
# Source: DEFRA 2023 UK grid, IEA 2023 for EU countries.
# ---------------------------------------------------------------------------
GRID_EMISSION_FACTORS = {
    "UK":  {"co2e_per_kwh": 0.20707, "source": "DEFRA 2023 — UK Grid Intensity"},
    "DE":  {"co2e_per_kwh": 0.38400, "source": "UBA 2023 — German Grid Intensity"},
    "EU":  {"co2e_per_kwh": 0.27600, "source": "IEA 2023 — EU Average Grid Intensity"},
    "DEFAULT": {"co2e_per_kwh": 0.27600, "source": "IEA 2023 — EU Average (default)"},
}

# ---------------------------------------------------------------------------
# Validation bounds
# ---------------------------------------------------------------------------

# Max billing period length in days.
# WHY 100: quarterly bills are common (92 days). A 6-month bill (180 days)
# almost certainly means two bills were merged or a date was wrong.
MAX_BILLING_DAYS = 100

# Min billing period in days.
# A 0-day period means start == end — likely a data export error.
MIN_BILLING_DAYS = 1

# kWh plausibility bounds per billing period
# WHY THESE NUMBERS:
# A small office might use 500 kWh/month. A large industrial site might use
# 100,000 kWh/month. Anything above 200,000 for a single meter in one period
# is implausible for a single invoice — likely a unit error (MWh vs kWh).
MIN_KWH = 0.1
MAX_KWH = 200_000
