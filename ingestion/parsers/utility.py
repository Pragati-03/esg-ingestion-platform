"""
Utility Electricity CSV Parser
--------------------------------

Parses CSV exports from utility supplier portals (E.ON, Vattenfall,
British Gas, EDF, etc.) into normalised Scope 2 emission records.

REALISTIC ASSUMPTIONS:
1. No standard format exists — every supplier exports differently
2. Billing periods can span multiple months (quarterly bills)
3. Billing periods can overlap (amended bills, re-issues)
4. Duplicate invoices are common — same invoice_number, same data
5. Credit notes appear as negative kWh (supplier corrections)
6. Some portals export kWh with commas as thousands separators
7. Date formats vary even within the same supplier's exports

SCOPE 2 ASSIGNMENT:
All utility electricity records are Scope 2 (purchased energy).
Grid emission factor is applied based on country code, defaulting
to EU average if unknown.

WHAT WOULD BREAK IN PRODUCTION:
- Renewable energy tariffs should have a zero or reduced emission factor
  (REGO certificates, PPAs). We don't handle this — flag for analyst.
- Half-hourly meter data (HH data) from smart meters has a completely
  different format — one row per 30-minute interval, not per bill.
- Some suppliers export in MWh not kWh — a 1000x error if not caught.
- Multi-site accounts may roll up multiple meters into one invoice row.
"""

import csv
import hashlib
import logging
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from .base import BaseParser, ParseResult, ParsedRow, FlaggedRow
from .utility_constants import (
    COLUMN_ALIASES,
    REQUIRED_COLUMNS,
    DATE_FORMATS,
    GRID_EMISSION_FACTORS,
    MAX_BILLING_DAYS,
    MIN_BILLING_DAYS,
    MIN_KWH,
    MAX_KWH,
)

logger = logging.getLogger(__name__)


class UtilityParser(BaseParser):
    """
    Parses utility electricity CSV exports into ParseResult.

    Args:
        country_code: ISO country code for grid emission factor selection.
                      Defaults to 'DEFAULT' (EU average).
                      In production this would come from the tenant's site config.
    """

    source_type = "utility"

    def __init__(self, country_code: str = "DEFAULT"):
        self.country_code = country_code
        factor_data = GRID_EMISSION_FACTORS.get(
            country_code, GRID_EMISSION_FACTORS["DEFAULT"]
        )
        self.emission_factor = factor_data["co2e_per_kwh"]
        self.emission_factor_source = factor_data["source"]

    def parse(self, file_path: str) -> ParseResult:
        result = ParseResult()

        try:
            rows, headers = self._read_csv(file_path)
        except Exception as exc:
            result.fatal_error = f"Could not read file: {exc}"
            return result

        column_map = self._resolve_columns(headers)
        missing = REQUIRED_COLUMNS - set(column_map.values())
        if missing:
            result.fatal_error = (
                f"Missing required columns: {missing}. Headers found: {headers}"
            )
            return result

        # Track seen invoice numbers to detect duplicates within this file.
        # WHY: Utility portals frequently re-export the same bill in a
        # corrected download. We flag duplicates rather than silently skip them
        # so the analyst can confirm which version is correct.
        seen_invoice_hashes: set[str] = set()

        for row_number, raw_row in enumerate(rows, start=2):
            raw_data = dict(zip(headers, raw_row))
            normalised_row = {
                column_map[h]: v
                for h, v in raw_data.items()
                if h in column_map
            }

            flagged = self._validate_and_parse_row(
                row_number, raw_data, normalised_row,
                result, seen_invoice_hashes,
            )
            if flagged:
                result.flagged_rows.append(flagged)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_csv(self, file_path: str) -> tuple[list, list]:
        rows = []
        with open(file_path, encoding="utf-8-sig", newline="") as f:
            # Auto-detect delimiter — some portals use semicolons
            sample = f.read(2048)
            f.seek(0)
            delimiter = ";" if sample.count(";") > sample.count(",") else ","
            reader = csv.reader(f, delimiter=delimiter)
            headers = [h.strip() for h in next(reader)]
            for row in reader:
                if any(cell.strip() for cell in row):
                    rows.append([cell.strip() for cell in row])
        return rows, headers

    def _resolve_columns(self, headers: list[str]) -> dict[str, str]:
        mapping = {}
        for header in headers:
            canonical = COLUMN_ALIASES.get(header.strip().lower())
            mapping[header] = canonical if canonical else header
        return mapping

    def _validate_and_parse_row(
        self,
        row_number: int,
        raw_data: dict,
        row: dict,
        result: ParseResult,
        seen_invoice_hashes: set,
    ) -> FlaggedRow | None:

        # --- 1. Parse period start and end ---
        raw_start = row.get("period_start", "").strip()
        raw_end = row.get("period_end", "").strip()

        period_start = self._parse_date(raw_start)
        period_end = self._parse_date(raw_end)

        if not period_start:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="missing_value",
                flag_reason=f"Cannot parse billing period start '{raw_start}'",
            )
        if not period_end:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="missing_value",
                flag_reason=f"Cannot parse billing period end '{raw_end}'",
            )

        if period_end < period_start:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="out_of_range",
                flag_reason=(
                    f"period_end {period_end} is before period_start {period_start}"
                ),
            )

        # --- 2. Billing period length check ---
        period_days = (period_end - period_start).days

        if period_days < MIN_BILLING_DAYS:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="out_of_range",
                flag_reason=f"Billing period is {period_days} days — suspiciously short",
            )

        if period_days > MAX_BILLING_DAYS:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="out_of_range",
                flag_reason=(
                    f"Billing period is {period_days} days (start: {period_start}, "
                    f"end: {period_end}). Quarterly bills max out at ~92 days. "
                    f"Possible merged bills or wrong year."
                ),
            )

        if period_end > date.today():
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="future_date",
                flag_reason=f"Billing period end {period_end} is in the future",
            )

        # --- 3. Parse kWh ---
        raw_kwh = row.get("usage_kwh", "").strip()
        if not raw_kwh:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="missing_value",
                flag_reason="usage_kwh is empty — possible missing meter read",
            )

        kwh = self._parse_number(raw_kwh)
        if kwh is None:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="missing_value",
                flag_reason=f"Cannot parse usage_kwh '{raw_kwh}' as a number",
            )

        # --- 4. Credit note detection ---
        # Negative kWh = supplier credit note (e.g. billing correction).
        # We don't reject these — they're legitimate — but we flag for analyst
        # awareness. A credit note should offset a previous bill.
        if kwh < 0:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="out_of_range",
                flag_reason=(
                    f"usage_kwh is negative ({kwh}). This appears to be a supplier "
                    f"credit note. Verify against original invoice and approve manually."
                ),
            )

        # --- 5. kWh plausibility ---
        if kwh < MIN_KWH:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="out_of_range",
                flag_reason=f"usage_kwh {kwh} is implausibly low for a billing period",
            )

        if kwh > MAX_KWH:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="out_of_range",
                flag_reason=(
                    f"usage_kwh {kwh} exceeds {MAX_KWH}. Possible unit error "
                    f"(MWh exported instead of kWh)? Verify with supplier invoice."
                ),
            )

        # --- 6. Duplicate detection ---
        # Build a fingerprint from meter_id + invoice_number + kwh.
        # If the same combination appears twice in the file, it's a duplicate export.
        invoice_number = row.get("invoice_number", "").strip()
        meter_id = row.get("meter_id", "").strip()

        row_fingerprint = hashlib.md5(
            f"{meter_id}|{invoice_number}|{raw_kwh}|{raw_start}|{raw_end}"
            .encode()
        ).hexdigest()

        if row_fingerprint in seen_invoice_hashes:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="duplicate",
                flag_reason=(
                    f"Row appears to be a duplicate of an earlier row in this file. "
                    f"Meter: {meter_id}, Invoice: {invoice_number}, "
                    f"kWh: {kwh}. Possible re-export of same bill."
                ),
            )
        seen_invoice_hashes.add(row_fingerprint)

        # --- 7. CO2e calculation ---
        # We use the midpoint of the billing period as the activity_date.
        # WHY MIDPOINT: A bill covering Jan 1–31 doesn't have a single activity
        # date. The midpoint (Jan 16) is a defensible convention for reporting.
        period_midpoint = period_start + (period_end - period_start) / 2
        co2e_kg = round(kwh * self.emission_factor, 4)

        # --- All checks passed ---
        result.parsed_rows.append(
            ParsedRow(
                row_number=row_number,
                raw_data=raw_data,
                activity_date=period_midpoint,
                description=(
                    f"{row.get('site_name', meter_id)} — "
                    f"{period_start} to {period_end}"
                ),
                quantity=kwh,
                unit="kWh",
                co2e_kg=co2e_kg,
                emission_factor=self.emission_factor,
                emission_factor_source=self.emission_factor_source,
                scope=2,   # Purchased electricity is always Scope 2
                source_type=self.source_type,
                extra={
                    "meter_id": meter_id,
                    "account_id": row.get("account_id", ""),
                    "site_name": row.get("site_name", ""),
                    "period_start": str(period_start),
                    "period_end": str(period_end),
                    "period_days": period_days,
                    "invoice_number": invoice_number,
                    "tariff_code": row.get("tariff_code", ""),
                    "supplier": row.get("supplier", ""),
                },
            )
        )
        return None

    def _parse_date(self, value: str) -> date | None:
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
        return None

    def _parse_number(self, value: str) -> float | None:
        """
        Parse kWh value handling thousands separators and decimal variants.

        WHY:
        Utility portals commonly export '12,450.50' (comma thousands separator)
        or '12.450,50' (European format). Both must parse to 12450.50.
        """
        # Remove currency symbols if present
        value = value.replace("£", "").replace("€", "").strip()

        # European format: '12.450,50' → '12450.50'
        if "," in value and "." in value:
            if value.index(",") > value.index("."):
                # Comma is decimal separator: '12.450,50'
                value = value.replace(".", "").replace(",", ".")
            else:
                # Comma is thousands separator: '12,450.50'
                value = value.replace(",", "")
        elif "," in value and "." not in value:
            # Could be decimal comma '450,5' or thousands '12,450'
            # If one comma and <=2 digits after: decimal. Else thousands.
            parts = value.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                value = value.replace(",", ".")
            else:
                value = value.replace(",", "")

        try:
            return float(Decimal(value))
        except (InvalidOperation, ValueError):
            return None
