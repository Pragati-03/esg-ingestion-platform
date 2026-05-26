"""
SAP Export Column Mappings and Lookup Tables
--------------------------------------------

WHY THESE EXIST AS CONSTANTS:
SAP exports use German field names that vary slightly between ECC and S4HANA
versions, and between client configurations. Rather than hardcoding string
comparisons in the parser, we centralise all mappings here.

This means when a new client sends 'Buchungsdatum ' (trailing space) or
'buchungsdatum' (lowercase), we fix it in one place.
"""

# ---------------------------------------------------------------------------
# Column name aliases
# Maps every known variant → our internal canonical name.
# WHY: SAP column names vary by client config, ECC vs S4HANA, and export tool.
# We've seen all of these in real exports.
# ---------------------------------------------------------------------------
COLUMN_ALIASES = {
    # Date
    "buchungsdatum": "activity_date",
    "belegdatum": "activity_date",
    "datum": "activity_date",

    # Plant / site
    "werk": "plant_code",
    "werkscode": "plant_code",
    "plant": "plant_code",

    # Material
    "materialnummer": "material_number",
    "matnr": "material_number",
    "material": "material_number",

    # Description
    "materialbezeichnung": "description",
    "bezeichnung": "description",
    "maktx": "description",

    # Quantity
    "menge": "quantity",
    "verbrauchsmenge": "quantity",
    "quantity": "quantity",

    # Unit
    "einheit": "unit",
    "mengeneinheit": "unit",
    "meins": "unit",
    "unit": "unit",

    # Cost centre
    "kostenstelle": "cost_centre",
    "kostenst": "cost_centre",

    # Document text / notes
    "belegtext": "notes",
    "text": "notes",
}

# Required columns after alias resolution.
# If any of these are missing, the entire upload is rejected before row parsing.
REQUIRED_COLUMNS = {"activity_date", "quantity", "unit", "description"}

# ---------------------------------------------------------------------------
# Unit normalisation
# Maps every observed unit variant → canonical internal unit.
#
# WHY THIS IS NECESSARY:
# SAP unit fields are free-text in many configurations. Real exports contain:
# - 'L', 'l', 'Liter', 'liter', 'litre' all meaning the same thing
# - 'm3' and 'm³' (with unicode superscript) both meaning cubic metres
# - 'KG' and 'kg' differing only in case
# This table is the single source of truth for unit resolution.
# ---------------------------------------------------------------------------
UNIT_ALIASES = {
    # Litres
    "l": "litre",
    "L": "litre",
    "liter": "litre",
    "Liter": "litre",
    "litre": "litre",
    "litres": "litre",
    "lt": "litre",

    # Kilograms
    "kg": "kg",
    "KG": "kg",
    "kilogramm": "kg",
    "kilogram": "kg",

    # Cubic metres (note: m³ uses unicode superscript — real SAP exports contain this)
    "m3": "m3",
    "m³": "m3",
    "cbm": "m3",
    "kubikmeter": "m3",
}

# ---------------------------------------------------------------------------
# Material → fuel type mapping
# Maps SAP material descriptions (lowercased) → internal fuel key.
# The fuel key must match a row in emission_factors.json.
#
# WHY DESCRIPTION-BASED, NOT MATERIAL-NUMBER:
# Material numbers (MAT-10023 etc.) are client-specific and change between
# SAP systems. Description matching is more portable, though less precise.
# In production this would be a configurable mapping table per tenant.
# ---------------------------------------------------------------------------
MATERIAL_TO_FUEL = {
    "dieselkraftstoff": "diesel",
    "diesel": "diesel",
    "erdgas": "natural_gas",
    "heizoel el": "heating_oil",
    "heizöl el": "heating_oil",
    "flugtreibstoff kerosin": "kerosene",
    "kerosin": "kerosene",
}

# ---------------------------------------------------------------------------
# Date format patterns to try, in order of likelihood.
#
# WHY MULTIPLE FORMATS:
# SAP date export format depends on the user's locale settings at export time.
# A Munich plant and a Hamburg plant on the same SAP system can export
# different date formats if users have different locale preferences.
# We try formats in order and take the first that parses.
# ---------------------------------------------------------------------------
DATE_FORMATS = [
    "%d.%m.%Y",   # 15.01.2024  — German locale (most common in SAP DE)
    "%Y-%m-%d",   # 2024-01-18  — ISO 8601 (S4HANA default)
    "%d/%m/%Y",   # 20/01/2024  — British/EU variant
    "%m/%d/%Y",   # 01/20/2024  — US variant (rare but seen)
]

# ---------------------------------------------------------------------------
# Plausibility bounds for quantity validation.
# Values outside these ranges are flagged as out_of_range.
#
# WHY THESE NUMBERS:
# Based on typical quarterly consumption for a mid-size manufacturing site.
# A single booking of >50,000 litres diesel is implausible for one entry —
# that would be a bulk tank delivery, recorded differently in SAP.
# These are starting defaults; in production they'd be configurable per tenant.
# ---------------------------------------------------------------------------
QUANTITY_BOUNDS = {
    "litre": (0.1, 50_000),
    "kg":    (0.1, 50_000),
    "m3":    (0.1, 100_000),
}
