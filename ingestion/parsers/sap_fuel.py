"""
SAP Fuel / Procurement CSV Parser
----------------------------------

Parses flat-file CSV exports from SAP ECC or S4HANA procurement modules.

REALISTIC ASSUMPTIONS BAKED IN:
1. German column headers with known variants (Buchungsdatum, Werk, etc.)
2. Mixed date formats depending on user locale at export time
3. Unit variants: 'L', 'Liter', 'l', 'm3', 'm³', 'KG', 'kg'
4. Numeric values may use comma as decimal separator (German locale)
5. Some rows will be missing quantity or unit (failed postings in SAP)
6. Some rows will be implausibly large (test bookings, data entry errors)
7. Material descriptions are the most reliable fuel type identifier

WHAT WOULD BREAK IN REAL PRODUCTION:
- SAP can export with BOM (byte-order mark) — handle with utf-8-sig encoding
- Some clients export with semicolons as delimiters, not commas
- Plant codes may need a lookup table to map to real site names
- Material numbers may be more reliable than descriptions for some clients
- Emission factors need versioning — a DEFRA update changes historical CO2e
- Cost centre could drive scope assignment in complex organisations
"""

import csv
import logging
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from .base import BaseParser, ParseResult, ParsedRow, FlaggedRow
from .sap_constants import (
    COLUMN_ALIASES,
    REQUIRED_COLUMNS,
    UNIT_ALIASES,
    MATERIAL_TO_FUEL,
    DATE_FORMATS,
    QUANTITY_BOUNDS,
)

logger = logging.getLogger(__name__)

# Emission factors keyed by fuel type.
# In production these come from the DB (EmissionFactor model + fixture).
# Here they're inline to keep the parser self-contained and testable
# without a DB connection.
#
# WHY INLINE FOR NOW:
# A 4-day build should not have the parser depend on a DB query.
# Extracting to a DB lookup is a one-line change once the fixture is loaded.
EMISSION_FACTORS = {
    "diesel": {
        "co2e_per_litre": 2.6391,
        "co2e_per_kg": 3.1760,
        "density_kg_per_litre": 0.8320,
        "source": "DEFRA 2023 — Liquid fuels",
    },
    "natural_gas": {
        "co2e_per_m3": 2.0399,
        "source": "DEFRA 2023 — Gaseous fuels",
    },
    "heating_oil": {
        "co2e_per_litre": 2.5185,
        "co2e_per_kg": 2.9620,
        "density_kg_per_litre": 0.8500,
        "source": "DEFRA 2023 — Liquid fuels",
    },
    "kerosene": {
        "co2e_per_litre": 2.5210,
        "co2e_per_kg": 3.1500,
        "density_kg_per_litre": 0.8000,
        "source": "DEFRA 2023 — Liquid fuels",
    },
}


class SAPFuelParser(BaseParser):
    """
    Parses SAP fuel/procurement CSV exports into ParseResult.

    Usage:
        parser = SAPFuelParser()
        result = parser.parse("/path/to/export.csv")

        for row in result.parsed_rows:
            # write RawRecord + EmissionRecord

        for row in result.flagged_rows:
            # write RawRecord + flagged EmissionRecord
    """

    source_type = "sap_fuel"

    def parse(self, file_path: str) -> ParseResult:
        result = ParseResult()

        try:
            rows, headers = self._read_csv(file_path)
        except Exception as exc:
            result.fatal_error = f"Could not read file: {exc}"
            return result

        # Resolve column aliases before any row processing.
        # Fatal if required columns are missing — no point processing rows.
        column_map = self._resolve_columns(headers)
        missing = REQUIRED_COLUMNS - set(column_map.values())
        if missing:
            result.fatal_error = (
                f"Missing required columns after alias resolution: {missing}. "
                f"Headers found: {headers}"
            )
            return result

        for row_number, raw_row in enumerate(rows, start=2):  # start=2: row 1 is header
            # Always store the raw row exactly as received.
            raw_data = dict(zip(headers, raw_row))

            # Map raw column names → canonical names for this row.
            normalised_row = {
                column_map[h]: v
                for h, v in raw_data.items()
                if h in column_map
            }

            flagged = self._validate_and_parse_row(
                row_number, raw_data, normalised_row, result
            )
            if flagged:
                result.flagged_rows.append(flagged)
            # parsed_rows are appended inside _validate_and_parse_row on success

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_csv(self, file_path: str) -> tuple[list, list]:
        """
        Read CSV, handling BOM and common encoding issues.

        WHY utf-8-sig:
        SAP's export tool frequently prepends a UTF-8 BOM. Python's
        utf-8-sig codec strips it silently. Using plain utf-8 would leave
        a \ufeff prefix on the first column name, breaking all lookups.
        """
        rows = []
        with open(file_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            headers = [h.strip() for h in next(reader)]
            for row in reader:
                # Skip entirely empty rows (common at end of SAP exports)
                if any(cell.strip() for cell in row):
                    rows.append([cell.strip() for cell in row])
        return rows, headers

    def _resolve_columns(self, headers: list[str]) -> dict[str, str]:
        """
        Map raw header names → canonical names via COLUMN_ALIASES.
        Matching is case-insensitive to handle SAP capitalisation quirks.

        Returns: {raw_header: canonical_name}
        """
        mapping = {}
        for header in headers:
            canonical = COLUMN_ALIASES.get(header.lower())
            if canonical:
                mapping[header] = canonical
            else:
                # Keep unmapped columns under their original name.
                # We don't discard unknown columns — they stay in raw_data.
                mapping[header] = header
        return mapping

    def _validate_and_parse_row(
        self,
        row_number: int,
        raw_data: dict,
        row: dict,
        result: ParseResult,
    ) -> FlaggedRow | None:
        """
        Validate one row. On success, appends to result.parsed_rows and returns None.
        On failure, returns a FlaggedRow describing the problem.

        WHY RETURN EARLY ON FIRST ERROR:
        In a batch import context, collecting the first meaningful error per row
        is sufficient. Collecting all errors per row adds complexity for marginal
        benefit — analysts fix one issue at a time anyway.
        """

        # --- 1. Date parsing ---
        raw_date = row.get("activity_date", "").strip()
        if not raw_date:
            return FlaggedRow(
                row_number=row_number,
                raw_data=raw_data,
                flag_type="missing_value",
                flag_reason="activity_date is empty",
            )

        parsed_date = self._parse_date(raw_date)
        if parsed_date is None:
            return FlaggedRow(
                row_number=row_number,
                raw_data=raw_data,
                flag_type="missing_value",
                flag_reason=f"Cannot parse date '{raw_date}'. Tried formats: {DATE_FORMATS}",
            )

        if parsed_date > date.today():
            return FlaggedRow(
                row_number=row_number,
                raw_data=raw_data,
                flag_type="future_date",
                flag_reason=f"activity_date {parsed_date} is in the future",
            )

        # --- 2. Quantity parsing ---
        raw_quantity = row.get("quantity", "").strip()
        if not raw_quantity:
            return FlaggedRow(
                row_number=row_number,
                raw_data=raw_data,
                flag_type="missing_value",
                flag_reason="quantity is empty (likely a failed SAP posting)",
            )

        quantity = self._parse_quantity(raw_quantity)
        if quantity is None:
            return FlaggedRow(
                row_number=row_number,
                raw_data=raw_data,
                flag_type="missing_value",
                flag_reason=f"Cannot parse quantity '{raw_quantity}' as a number",
            )

        # --- 3. Unit normalisation ---
        raw_unit = row.get("unit", "").strip()
        canonical_unit = UNIT_ALIASES.get(raw_unit)
        if canonical_unit is None:
            return FlaggedRow(
                row_number=row_number,
                raw_data=raw_data,
                flag_type="unknown_unit",
                flag_reason=(
                    f"Unit '{raw_unit}' is not in the unit lookup table. "
                    f"Known units: {list(UNIT_ALIASES.keys())}"
                ),
            )

        # --- 4. Plausibility check ---
        bounds = QUANTITY_BOUNDS.get(canonical_unit)
        if bounds:
            lo, hi = bounds
            if not (lo <= quantity <= hi):
                return FlaggedRow(
                    row_number=row_number,
                    raw_data=raw_data,
                    flag_type="out_of_range",
                    flag_reason=(
                        f"Quantity {quantity} {canonical_unit} is outside plausible range "
                        f"[{lo}, {hi}]. Possible test booking or data entry error."
                    ),
                )

        # --- 5. Fuel type resolution ---
        description = row.get("description", "").strip()
        fuel_key = MATERIAL_TO_FUEL.get(description.lower())
        if fuel_key is None:
            return FlaggedRow(
                row_number=row_number,
                raw_data=raw_data,
                flag_type="unknown_unit",  # reusing — closest semantic fit
                flag_reason=(
                    f"Cannot map material description '{description}' to a fuel type. "
                    f"Known materials: {list(MATERIAL_TO_FUEL.keys())}"
                ),
            )

        # --- 6. CO2e calculation ---
        co2e_kg, factor, factor_source = self._calculate_co2e(
            quantity, canonical_unit, fuel_key
        )
        if co2e_kg is None:
            return FlaggedRow(
                row_number=row_number,
                raw_data=raw_data,
                flag_type="unknown_unit",
                flag_reason=(
                    f"No emission factor available for fuel '{fuel_key}' "
                    f"in unit '{canonical_unit}'"
                ),
            )

        # --- All checks passed — build ParsedRow ---
        result.parsed_rows.append(
            ParsedRow(
                row_number=row_number,
                raw_data=raw_data,
                activity_date=parsed_date,
                description=description,
                quantity=quantity,
                unit=canonical_unit,
                co2e_kg=round(co2e_kg, 4),
                emission_factor=factor,
                emission_factor_source=factor_source,
                scope=1,   # SAP fuel combustion is always Scope 1
                source_type=self.source_type,
                extra={
                    "plant_code": row.get("plant_code", ""),
                    "cost_centre": row.get("cost_centre", ""),
                    "notes": row.get("notes", ""),
                    "fuel_key": fuel_key,
                },
            )
        )
        return None

    def _parse_date(self, value: str) -> date | None:
        """
        Try each known date format in order, return first that parses.

        WHY NOT dateutil.parser:
        dateutil is ambiguous — '01/02/2024' could be Jan 2 or Feb 1 depending
        on locale. We prefer explicit format matching so we know exactly what
        we're accepting.
        """
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    def _parse_quantity(self, value: str) -> float | None:
        """
        Parse numeric quantity, handling German decimal comma.

        WHY:
        SAP in German locale exports '450,5' not '450.5'.
        We detect the pattern and convert before parsing.
        """
        # German decimal: has comma but no period, e.g. '1.200,50' or '450,5'
        if "," in value and "." not in value:
            value = value.replace(",", ".")
        elif "," in value and "." in value:
            # Thousands separator: '1.200,50' → '1200.50'
            value = value.replace(".", "").replace(",", ".")

        try:
            return float(Decimal(value))
        except (InvalidOperation, ValueError):
            return None

    def _calculate_co2e(
        self, quantity: float, unit: str, fuel_key: str
    ) -> tuple[float | None, float | None, str | None]:
        """
        Apply emission factor to calculate kg CO2e.

        Returns (co2e_kg, factor_used, factor_source) or (None, None, None).

        UNIT ROUTING LOGIC:
        - litre → use co2e_per_litre directly (most common case)
        - kg    → use co2e_per_kg directly
        - m3    → use co2e_per_m3 (natural gas only)

        WHY WE DON'T CONVERT UNITS BEFORE APPLYING FACTORS:
        Converting litre→kg requires density, which varies by fuel batch
        temperature. It's more defensible to use the per-litre factor directly
        rather than introducing a density conversion step.
        """
        factors = EMISSION_FACTORS.get(fuel_key)
        if not factors:
            return None, None, None

        source = factors["source"]

        if unit == "litre":
            factor = factors.get("co2e_per_litre")
            if factor:
                return quantity * factor, factor, source

        elif unit == "kg":
            factor = factors.get("co2e_per_kg")
            if factor:
                return quantity * factor, factor, source

        elif unit == "m3":
            factor = factors.get("co2e_per_m3")
            if factor:
                return quantity * factor, factor, source

        return None, None, None
