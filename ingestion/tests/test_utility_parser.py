"""
Tests for UtilityParser

Run with: python manage.py test apps.ingestion.tests.test_utility_parser
"""

import os
import tempfile
import pytest
from datetime import date

from apps.ingestion.parsers.utility import UtilityParser


def write_csv(content: str) -> str:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return f.name


HEADERS = "account_id,meter_id,site_name,billing_period_start,billing_period_end,usage_kwh,tariff_code,supplier,invoice_number,cost_gbp\n"


class TestUtilityParser:

    def setup_method(self):
        self.parser = UtilityParser(country_code="UK")

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_clean_row_parses_correctly(self):
        path = write_csv(
            HEADERS +
            "ACC-1001,MTR-A001,Munich HQ,01/01/2024,31/01/2024,12450.50,HV-INDUSTRIAL,E.ON,INV-001,2856.32\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)

        assert not result.has_fatal_error
        assert len(result.parsed_rows) == 1
        assert len(result.flagged_rows) == 0

        row = result.parsed_rows[0]
        assert row.quantity == 12450.50
        assert row.unit == "kWh"
        assert row.scope == 2
        assert row.co2e_kg == round(12450.50 * 0.20707, 4)
        assert row.extra["meter_id"] == "MTR-A001"
        assert row.extra["invoice_number"] == "INV-001"

    def test_iso_date_format_parses(self):
        path = write_csv(
            HEADERS +
            "ACC-1003,MTR-C003,Berlin,2024-01-01,2024-01-31,3200.50,LV-SME,Vattenfall,INV-001,698.43\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.parsed_rows) == 1

    def test_activity_date_is_midpoint_of_billing_period(self):
        path = write_csv(
            HEADERS +
            "ACC-1001,MTR-A001,HQ,01/01/2024,31/01/2024,5000,HV,E.ON,INV-001,1000\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        row = result.parsed_rows[0]
        # Midpoint of Jan 1 - Jan 31 = Jan 16
        assert row.activity_date == date(2024, 1, 16)

    def test_quarterly_bill_parses(self):
        path = write_csv(
            HEADERS +
            "ACC-1005,MTR-E005,Office,01/01/2024,31/03/2024,6100.00,LV-SME,Vattenfall,INV-Q1,1342.00\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.parsed_rows) == 1
        assert result.parsed_rows[0].extra["period_days"] == 90

    def test_thousands_comma_separator_parses(self):
        path = write_csv(
            HEADERS +
            "ACC-1001,MTR-A001,HQ,01/01/2024,31/01/2024,12,450.50,HV,E.ON,INV-001,2856\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert result.parsed_rows[0].quantity == 12450.50

    def test_eu_grid_factor_applied_correctly(self):
        parser_de = UtilityParser(country_code="DE")
        path = write_csv(
            HEADERS +
            "ACC-1001,MTR-A001,HQ,01/01/2024,31/01/2024,1000,HV,E.ON,INV-001,200\n"
        )
        result = parser_de.parse(path)
        os.unlink(path)
        assert result.parsed_rows[0].co2e_kg == round(1000 * 0.384, 4)

    # ------------------------------------------------------------------
    # Flagging rules
    # ------------------------------------------------------------------

    def test_missing_kwh_flags_row(self):
        path = write_csv(
            HEADERS +
            "ACC-1002,MTR-B002,Warehouse,01/02/2024,29/02/2024,,LV-SME,Vattenfall,INV-002,1654\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.flagged_rows) == 1
        assert result.flagged_rows[0].flag_type == "missing_value"

    def test_negative_kwh_flagged_as_credit_note(self):
        path = write_csv(
            HEADERS +
            "ACC-1001,MTR-A001,HQ,01/03/2024,31/03/2024,-500.00,HV,E.ON,INV-CREDIT,0\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.flagged_rows) == 1
        assert result.flagged_rows[0].flag_type == "out_of_range"
        assert "credit note" in result.flagged_rows[0].flag_reason

    def test_overlapping_billing_period_too_long_flagged(self):
        path = write_csv(
            HEADERS +
            "ACC-1005,MTR-E005,Office,01/01/2024,30/06/2024,6100.00,LV,Vattenfall,INV-H1,1342\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.flagged_rows) == 1
        assert result.flagged_rows[0].flag_type == "out_of_range"

    def test_duplicate_invoice_flagged(self):
        path = write_csv(
            HEADERS +
            "ACC-1003,MTR-C003,Berlin,01/02/2024,29/02/2024,2980.00,LV,Vattenfall,INV-BER-002,650\n"
            "ACC-1003,MTR-C003,Berlin,01/02/2024,29/02/2024,2980.00,LV,Vattenfall,INV-BER-002,650\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert len(result.parsed_rows) == 1
        assert len(result.flagged_rows) == 1
        assert result.flagged_rows[0].flag_type == "duplicate"

    def test_implausibly_high_kwh_flagged(self):
        path = write_csv(
            HEADERS +
            "ACC-1004,MTR-D004,Factory,01/01/2024,31/01/2024,95000.00,HV,E.ON,INV-F-001,21280\n"
            "ACC-1004,MTR-D004,Factory,01/01/2024,31/01/2024,250000.00,HV,E.ON,INV-F-002,55000\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        flagged_reasons = [r.flag_type for r in result.flagged_rows]
        assert "out_of_range" in flagged_reasons

    def test_future_period_end_flagged(self):
        path = write_csv(
            HEADERS +
            "ACC-1001,MTR-A001,HQ,01/01/2024,31/12/2099,5000,HV,E.ON,INV-001,1000\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert result.flagged_rows[0].flag_type == "future_date"

    def test_period_end_before_start_flagged(self):
        path = write_csv(
            HEADERS +
            "ACC-1001,MTR-A001,HQ,31/01/2024,01/01/2024,5000,HV,E.ON,INV-001,1000\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert result.flagged_rows[0].flag_type == "out_of_range"

    # ------------------------------------------------------------------
    # Fatal errors
    # ------------------------------------------------------------------

    def test_missing_required_column_fatal(self):
        path = write_csv(
            "meter_id,site_name,usage_kwh\n"
            "MTR-A001,HQ,5000\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert result.has_fatal_error
        assert "Missing required columns" in result.fatal_error
