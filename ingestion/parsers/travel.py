"""
Corporate Travel CSV Parser
-----------------------------

Parses Concur / Navan expense exports into Scope 3 emission records.

SCOPE 3 CATEGORY:
All corporate travel falls under GHG Protocol Scope 3, Category 6
(Business Travel). We assign this automatically — no analyst decision needed.

FLIGHT DISTANCE INFERENCE:
When origin/destination are IATA airport codes and no distance is provided,
we look up great-circle distance from our lookup table.

WHY GREAT-CIRCLE AND NOT ACTUAL ROUTING:
- Actual routing requires a flight data API (e.g. OAG, FlightAware)
- Great-circle is the DEFRA-recommended approximation for Scope 3 reporting
- We apply no routing factor in this build (production would add ~8%)

WHAT WOULD BREAK IN PRODUCTION:
- Airport codes not in our lookup table → flagged, not calculated
- Multi-leg itineraries in Concur export as one row → distance undercounted
- Currency conversion needed if expenses in EUR/USD not GBP
- Hotel emission factors vary significantly by star rating and country
- Rail emission factors differ: UK rail vs European rail vs Eurostar
"""

import csv
import logging
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from .base import BaseParser, ParseResult, ParsedRow, FlaggedRow
from .travel_constants import (
    COLUMN_ALIASES,
    REQUIRED_COLUMNS,
    TRAVEL_TYPE_ALIASES,
    AIRPORT_DISTANCES_KM,
    EMISSION_FACTORS,
    DATE_FORMATS,
    MAX_TAXI_KM,
    MAX_FLIGHT_KM,
    MAX_HOTEL_NIGHTS,
    MAX_COST_GBP,
)

logger = logging.getLogger(__name__)


class TravelParser(BaseParser):

    source_type = "travel"

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

        for row_number, raw_row in enumerate(rows, start=2):
            raw_data = dict(zip(headers, raw_row))
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

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_csv(self, file_path: str) -> tuple[list, list]:
        rows = []
        with open(file_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
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
    ) -> FlaggedRow | None:

        # --- 1. Date ---
        raw_date = row.get("travel_date", "").strip()
        travel_date = self._parse_date(raw_date)
        if not travel_date:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="missing_value",
                flag_reason=f"Cannot parse travel_date '{raw_date}'",
            )

        if travel_date > date.today():
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="future_date",
                flag_reason=f"travel_date {travel_date} is in the future",
            )

        # --- 2. Travel type ---
        raw_type = row.get("travel_type", "").strip().lower()
        travel_type = TRAVEL_TYPE_ALIASES.get(raw_type)
        if not travel_type:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="unknown_unit",
                flag_reason=(
                    f"Unrecognised travel_type '{raw_type}'. "
                    f"Expected one of: {list(TRAVEL_TYPE_ALIASES.keys())}"
                ),
            )

        # --- 3. Route to correct handler ---
        if travel_type == "flight":
            return self._handle_flight(row_number, raw_data, row, result, travel_date)
        elif travel_type == "hotel":
            return self._handle_hotel(row_number, raw_data, row, result, travel_date)
        elif travel_type in ("rail", "taxi"):
            return self._handle_ground(
                row_number, raw_data, row, result, travel_date, travel_type
            )

        return FlaggedRow(
            row_number=row_number, raw_data=raw_data,
            flag_type="missing_value",
            flag_reason=f"No handler for travel_type '{travel_type}'",
        )

    # ------------------------------------------------------------------
    # Type-specific handlers
    # ------------------------------------------------------------------

    def _handle_flight(self, row_number, raw_data, row, result, travel_date) -> FlaggedRow | None:
        origin = row.get("origin", "").strip().upper()
        destination = row.get("destination", "").strip().upper()

        # --- Same origin and destination ---
        if origin and destination and origin == destination:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="out_of_range",
                flag_reason=(
                    f"Flight origin and destination are both '{origin}'. "
                    f"Possible data entry error."
                ),
            )

        # --- Distance resolution ---
        distance_km = self._resolve_flight_distance(row, origin, destination)

        if distance_km is None:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="missing_value",
                flag_reason=(
                    f"Cannot determine flight distance for {origin}→{destination}. "
                    f"Route not in lookup table and no distance_km provided. "
                    f"Add distance manually or extend the airport lookup table."
                ),
            )

        if distance_km > MAX_FLIGHT_KM:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="out_of_range",
                flag_reason=(
                    f"Flight distance {distance_km}km exceeds maximum plausible "
                    f"commercial route ({MAX_FLIGHT_KM}km)."
                ),
            )

        # --- Class of travel → emission factor ---
        travel_class = row.get("travel_class", "").strip().lower()
        if travel_class not in EMISSION_FACTORS["flight"]:
            travel_class = "unknown"

        factor_data = EMISSION_FACTORS["flight"][travel_class]
        co2e_kg = round(distance_km * factor_data["co2e_per_pkm"], 4)

        # Flag first class — legitimate but high-impact, analyst should see it
        first_class_flag = travel_class == "first"

        description = (
            f"Flight {origin}→{destination} ({travel_class}) "
            f"— {row.get('vendor', '')} {travel_date}"
        )

        result.parsed_rows.append(ParsedRow(
            row_number=row_number,
            raw_data=raw_data,
            activity_date=travel_date,
            description=description,
            quantity=distance_km,
            unit="km",
            co2e_kg=co2e_kg,
            emission_factor=factor_data["co2e_per_pkm"],
            emission_factor_source=factor_data["source"],
            scope=3,
            source_type=self.source_type,
            extra={
                "travel_type": "flight",
                "origin": origin,
                "destination": destination,
                "travel_class": travel_class,
                "employee_id": row.get("employee_id", ""),
                "department": row.get("department", ""),
                "vendor": row.get("vendor", ""),
                "expense_id": row.get("expense_id", ""),
                "first_class": first_class_flag,
            },
        ))
        return None

    def _handle_hotel(self, row_number, raw_data, row, result, travel_date) -> FlaggedRow | None:
        raw_nights = row.get("nights", "").strip()

        if not raw_nights:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="missing_value",
                flag_reason="Hotel record is missing 'nights' — cannot calculate CO2e",
            )

        try:
            nights = int(float(raw_nights))
        except (ValueError, TypeError):
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="missing_value",
                flag_reason=f"Cannot parse nights '{raw_nights}' as a number",
            )

        if nights <= 0:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="out_of_range",
                flag_reason=f"Hotel nights must be > 0, got {nights}",
            )

        if nights > MAX_HOTEL_NIGHTS:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="out_of_range",
                flag_reason=(
                    f"Hotel nights {nights} exceeds {MAX_HOTEL_NIGHTS}. "
                    f"Possible data entry error or extended assignment."
                ),
            )

        factor_data = EMISSION_FACTORS["hotel"]["unknown"]
        co2e_kg = round(nights * factor_data["co2e_per_night"], 4)
        destination = row.get("destination", "").strip()

        result.parsed_rows.append(ParsedRow(
            row_number=row_number,
            raw_data=raw_data,
            activity_date=travel_date,
            description=f"Hotel {destination} {nights} night(s) — {row.get('vendor', '')}",
            quantity=nights,
            unit="nights",
            co2e_kg=co2e_kg,
            emission_factor=factor_data["co2e_per_night"],
            emission_factor_source=factor_data["source"],
            scope=3,
            source_type=self.source_type,
            extra={
                "travel_type": "hotel",
                "destination": destination,
                "nights": nights,
                "employee_id": row.get("employee_id", ""),
                "department": row.get("department", ""),
                "vendor": row.get("vendor", ""),
                "expense_id": row.get("expense_id", ""),
            },
        ))
        return None

    def _handle_ground(
        self, row_number, raw_data, row, result, travel_date, travel_type
    ) -> FlaggedRow | None:
        raw_distance = row.get("distance", "").strip()

        if not raw_distance:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="missing_value",
                flag_reason=(
                    f"{travel_type.title()} record missing distance. "
                    f"Cannot calculate CO2e without distance."
                ),
            )

        distance = self._parse_number(raw_distance)
        if distance is None:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="missing_value",
                flag_reason=f"Cannot parse distance '{raw_distance}'",
            )

        # Convert miles to km if needed
        distance_unit = row.get("distance_unit", "km").strip().lower()
        if distance_unit in ("miles", "mi", "mile"):
            distance = round(distance * 1.60934, 2)

        # Taxi-specific plausibility check
        if travel_type == "taxi" and distance > MAX_TAXI_KM:
            return FlaggedRow(
                row_number=row_number, raw_data=raw_data,
                flag_type="out_of_range",
                flag_reason=(
                    f"Taxi distance {distance}km exceeds {MAX_TAXI_KM}km. "
                    f"Likely a data entry error or wrong category."
                ),
            )

        factor_data = EMISSION_FACTORS[travel_type]["unknown"]
        co2e_kg = round(distance * factor_data["co2e_per_pkm"], 4)
        origin = row.get("origin", "").strip()
        destination = row.get("destination", "").strip()

        result.parsed_rows.append(ParsedRow(
            row_number=row_number,
            raw_data=raw_data,
            activity_date=travel_date,
            description=(
                f"{travel_type.title()} {origin}→{destination} "
                f"{distance}km — {row.get('vendor', '')}"
            ),
            quantity=distance,
            unit="km",
            co2e_kg=co2e_kg,
            emission_factor=factor_data["co2e_per_pkm"],
            emission_factor_source=factor_data["source"],
            scope=3,
            source_type=self.source_type,
            extra={
                "travel_type": travel_type,
                "origin": origin,
                "destination": destination,
                "employee_id": row.get("employee_id", ""),
                "department": row.get("department", ""),
                "vendor": row.get("vendor", ""),
                "expense_id": row.get("expense_id", ""),
            },
        ))
        return None

    # ------------------------------------------------------------------
    # Distance resolution
    # ------------------------------------------------------------------

    def _resolve_flight_distance(
        self, row: dict, origin: str, destination: str
    ) -> float | None:
        """
        Resolve flight distance in km.

        Priority order:
        1. Explicit distance_km in the row (most accurate)
        2. Airport code lookup table
        3. None — caller will flag the row

        WHY EXPLICIT DISTANCE TAKES PRIORITY:
        Some Concur configurations calculate distance server-side using
        actual routing. If present, we trust it over our lookup table.
        """
        # Try explicit distance field first
        raw_distance = row.get("distance", "").strip()
        if raw_distance:
            distance = self._parse_number(raw_distance)
            if distance and distance > 0:
                # Convert miles if needed
                unit = row.get("distance_unit", "km").strip().lower()
                if unit in ("miles", "mi", "mile"):
                    distance = round(distance * 1.60934, 2)
                return distance

        # Try airport code lookup
        if origin and destination and len(origin) == 3 and len(destination) == 3:
            route = frozenset({origin, destination})
            return AIRPORT_DISTANCES_KM.get(route)

        return None

    def _parse_date(self, value: str) -> date | None:
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
        return None

    def _parse_number(self, value: str) -> float | None:
        value = value.replace(",", "").strip()
        try:
            return float(Decimal(value))
        except (InvalidOperation, ValueError):
            return None
