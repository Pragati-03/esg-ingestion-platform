"""
Tests for TravelParser
Run with: python manage.py test apps.ingestion.tests.test_travel_parser
"""

import os
import tempfile
from datetime import date
from apps.ingestion.parsers.travel import TravelParser


def write_csv(content: str) -> str:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return f.name


HEADERS = "expense_id,employee_id,department,travel_date,travel_type,origin,destination,distance_km,distance_unit,nights,transport_class,vendor,cost_gbp,notes\n"


class TestTravelParser:

    def setup_method(self):
        self.parser = TravelParser()

    # ------------------------------------------------------------------
    # Flights
    # ------------------------------------------------------------------

    def test_flight_with_known_airport_codes(self):
        path = write_csv(
            HEADERS +
            "EXP-001,EMP-042,Eng,15/01/2024,flight,LHR,MUC,,,,economy,Lufthansa,320,offsite\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)

        assert not result.has_fatal_error
        assert len(result.parsed_rows) == 1
        row = result.parsed_rows[0]
        assert row.quantity == 1447          # LHR-MUC great circle distance
        assert row.unit == "km"
        assert row.scope == 3
        assert row.extra["travel_class"] == "economy"
        assert round(row.co2e_kg, 2) == round(1447 * 0.18817, 2)

    def test_business_class_higher_factor_than_economy(self):
        path_eco = write_csv(
            HEADERS +
            "EXP-001,EMP-001,Sales,22/01/2024,flight,LHR,JFK,,,,economy,BA,500,\n"
        )
        path_biz = write_csv(
            HEADERS +
            "EXP-002,EMP-001,Sales,22/01/2024,flight,LHR,JFK,,,,business,BA,1800,\n"
        )
        result_eco = self.parser.parse(path_eco)
        result_biz = self.parser.parse(path_biz)
        os.unlink(path_eco)
        os.unlink(path_biz)

        assert result_biz.parsed_rows[0].co2e_kg > result_eco.parsed_rows[0].co2e_kg

    def test_first_class_parsed_and_extra_flagged(self):
        path = write_csv(
            HEADERS +
            "EXP-017,EMP-310,HR,01/01/2024,flight,LHR,DXB,,,,first,Emirates,8500,\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.parsed_rows) == 1
        assert result.parsed_rows[0].extra["first_class"] is True

    def test_unknown_airport_route_flagged(self):
        path = write_csv(
            HEADERS +
            "EXP-001,EMP-001,Eng,15/01/2024,flight,LHR,XYZ,,,,economy,BA,200,\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.flagged_rows) == 1
        assert result.flagged_rows[0].flag_type == "missing_value"

    def test_same_origin_destination_flagged(self):
        path = write_csv(
            HEADERS +
            "EXP-016,EMP-055,Mkt,14/02/2024,flight,LHR,LHR,,,,economy,BA,50,\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.flagged_rows) == 1
        assert result.flagged_rows[0].flag_type == "out_of_range"

    # ------------------------------------------------------------------
    # Hotels
    # ------------------------------------------------------------------

    def test_hotel_calculates_co2e_per_night(self):
        path = write_csv(
            HEADERS +
            "EXP-003,EMP-042,Eng,15/01/2024,hotel,,Munich,,,,, Marriott,450,3 nights\n"
        )
        # Note: nights field is column 10 (index 9)
        path2 = write_csv(
            "expense_id,employee_id,department,travel_date,travel_type,origin,destination,distance_km,distance_unit,nights,transport_class,vendor,cost_gbp,notes\n"
            "EXP-003,EMP-042,Eng,15/01/2024,hotel,,Munich,,,3,,Marriott,450,3 nights\n"
        )
        result = self.parser.parse(path2)
        os.unlink(path2)
        assert len(result.parsed_rows) == 1
        row = result.parsed_rows[0]
        assert row.quantity == 3
        assert row.unit == "nights"
        assert row.co2e_kg == round(3 * 20.8, 4)

    def test_hotel_missing_nights_flagged(self):
        path = write_csv(
            HEADERS +
            "EXP-003,EMP-042,Eng,15/01/2024,hotel,,Munich,,,,,,450,\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.flagged_rows) == 1
        assert result.flagged_rows[0].flag_type == "missing_value"

    # ------------------------------------------------------------------
    # Rail and Taxi
    # ------------------------------------------------------------------

    def test_rail_calculates_correctly(self):
        path = write_csv(
            HEADERS +
            "EXP-007,EMP-201,Ops,05/02/2024,rail,London,Birmingham,188,km,,,Avanti,85,\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.parsed_rows) == 1
        assert result.parsed_rows[0].co2e_kg == round(188 * 0.03549, 4)

    def test_taxi_excessive_distance_flagged(self):
        path = write_csv(
            HEADERS +
            "EXP-015,EMP-201,Ops,10/02/2024,taxi,London,,999,km,,,Uber,35,\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.flagged_rows) == 1
        assert result.flagged_rows[0].flag_type == "out_of_range"

    def test_miles_converted_to_km(self):
        path = write_csv(
            HEADERS +
            "EXP-007,EMP-201,Ops,05/02/2024,rail,London,Birmingham,117,miles,,,Avanti,85,\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.parsed_rows) == 1
        # 117 miles ≈ 188.3 km
        assert result.parsed_rows[0].quantity > 185

    # ------------------------------------------------------------------
    # General validation
    # ------------------------------------------------------------------

    def test_future_date_flagged(self):
        path = write_csv(
            HEADERS +
            "EXP-001,EMP-001,Eng,15/01/2099,flight,LHR,MUC,,,,economy,LH,300,\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert result.flagged_rows[0].flag_type == "future_date"

    def test_unknown_travel_type_flagged(self):
        path = write_csv(
            HEADERS +
            "EXP-001,EMP-001,Eng,15/01/2024,helicopter,LHR,MUC,,,,economy,LH,300,\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert result.flagged_rows[0].flag_type == "unknown_unit"

    def test_all_scope_3(self):
        path = write_csv(
            HEADERS +
            "EXP-001,EMP-042,Eng,15/01/2024,flight,LHR,MUC,,,,economy,LH,320,\n"
            "EXP-002,EMP-201,Ops,05/02/2024,rail,London,Birmingham,188,km,,,Avanti,85,\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert all(r.scope == 3 for r in result.parsed_rows)
