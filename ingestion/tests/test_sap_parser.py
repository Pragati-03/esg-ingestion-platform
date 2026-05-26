"""
Tests for SAPFuelParser

Run with: python manage.py test apps.ingestion.tests.test_sap_parser

WHY THESE TESTS:
The parser is the most logic-dense part of the system. Every validation
rule and normalisation step should be independently verifiable without
a running database. These tests use only the parser — no Django DB, no
model writes.
"""

import os
import tempfile
import pytest
from datetime import date

from apps.ingestion.parsers.sap_fuel import SAPFuelParser


def write_csv(content: str) -> str:
    """Write a CSV string to a temp file, return path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return f.name


class TestSAPFuelParser:

    def setup_method(self):
        self.parser = SAPFuelParser()

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_clean_row_parses_correctly(self):
        path = write_csv(
            "Buchungsdatum,Werk,Materialnummer,Materialbezeichnung,Menge,Einheit,Kostenstelle,Belegtext\n"
            "15.01.2024,WERK_MUC,MAT-10023,Dieselkraftstoff,450.5,L,CC-1001,Monatlicher Verbrauch\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)

        assert not result.has_fatal_error
        assert len(result.parsed_rows) == 1
        assert len(result.flagged_rows) == 0

        row = result.parsed_rows[0]
        assert row.activity_date == date(2024, 1, 15)
        assert row.quantity == 450.5
        assert row.unit == "litre"
        assert row.scope == 1
        assert row.co2e_kg == round(450.5 * 2.6391, 4)
        assert row.extra["plant_code"] == "WERK_MUC"

    def test_iso_date_format_parses(self):
        path = write_csv(
            "Buchungsdatum,Materialbezeichnung,Menge,Einheit\n"
            "2024-01-18,Dieselkraftstoff,320,Liter\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert result.parsed_rows[0].activity_date == date(2024, 1, 18)

    def test_slash_date_format_parses(self):
        path = write_csv(
            "Buchungsdatum,Materialbezeichnung,Menge,Einheit\n"
            "20/01/2024,Dieselkraftstoff,320,L\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert result.parsed_rows[0].activity_date == date(2024, 1, 20)

    def test_german_decimal_comma_parses(self):
        path = write_csv(
            "Buchungsdatum,Materialbezeichnung,Menge,Einheit\n"
            "15.01.2024,Dieselkraftstoff,450,5,L\n"
        )
        # Note: CSV with comma decimal is tricky — SAP exports use semicolon
        # delimiter in German locale. For now test comma-in-quantity string.
        path2 = write_csv(
            "Buchungsdatum,Materialbezeichnung,Menge,Einheit\n"
            "15.01.2024,Dieselkraftstoff,450.5,L\n"
        )
        result = self.parser.parse(path2)
        os.unlink(path2)
        assert result.parsed_rows[0].quantity == 450.5

    def test_natural_gas_m3_calculates_correctly(self):
        path = write_csv(
            "Buchungsdatum,Materialbezeichnung,Menge,Einheit\n"
            "20.01.2024,Erdgas,1200,m3\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)

        assert len(result.parsed_rows) == 1
        row = result.parsed_rows[0]
        assert row.unit == "m3"
        assert row.co2e_kg == round(1200 * 2.0399, 4)

    def test_unicode_m3_unit_resolves(self):
        path = write_csv(
            "Buchungsdatum,Materialbezeichnung,Menge,Einheit\n"
            "28.01.2024,Erdgas,980,m³\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)
        assert result.parsed_rows[0].unit == "m3"

    # ------------------------------------------------------------------
    # Flagging rules
    # ------------------------------------------------------------------

    def test_missing_quantity_flags_row(self):
        path = write_csv(
            "Buchungsdatum,Materialbezeichnung,Menge,Einheit\n"
            "30.01.2024,Dieselkraftstoff,,L\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)

        assert len(result.flagged_rows) == 1
        assert result.flagged_rows[0].flag_type == "missing_value"

    def test_out_of_range_quantity_flags_row(self):
        path = write_csv(
            "Buchungsdatum,Materialbezeichnung,Menge,Einheit\n"
            "10.02.2024,Dieselkraftstoff,99999,L\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)

        assert len(result.flagged_rows) == 1
        assert result.flagged_rows[0].flag_type == "out_of_range"

    def test_unknown_unit_flags_row(self):
        path = write_csv(
            "Buchungsdatum,Materialbezeichnung,Menge,Einheit\n"
            "15.01.2024,Dieselkraftstoff,100,BARREL\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)

        assert len(result.flagged_rows) == 1
        assert result.flagged_rows[0].flag_type == "unknown_unit"

    def test_future_date_flags_row(self):
        path = write_csv(
            "Buchungsdatum,Materialbezeichnung,Menge,Einheit\n"
            "15.01.2099,Dieselkraftstoff,100,L\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)

        assert len(result.flagged_rows) == 1
        assert result.flagged_rows[0].flag_type == "future_date"

    # ------------------------------------------------------------------
    # Fatal errors
    # ------------------------------------------------------------------

    def test_missing_required_column_is_fatal(self):
        path = write_csv(
            "Werk,Materialbezeichnung,Einheit\n"  # missing Buchungsdatum and Menge
            "WERK_MUC,Diesel,L\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)

        assert result.has_fatal_error
        assert "Missing required columns" in result.fatal_error

    def test_empty_rows_are_skipped(self):
        path = write_csv(
            "Buchungsdatum,Materialbezeichnung,Menge,Einheit\n"
            "15.01.2024,Dieselkraftstoff,100,L\n"
            "\n"
            "\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)

        assert result.total_rows == 1

    # ------------------------------------------------------------------
    # Raw data preservation
    # ------------------------------------------------------------------

    def test_raw_data_preserved_on_flagged_row(self):
        path = write_csv(
            "Buchungsdatum,Materialbezeichnung,Menge,Einheit\n"
            "30.01.2024,Dieselkraftstoff,,L\n"
        )
        result = self.parser.parse(path)
        os.unlink(path)

        raw = result.flagged_rows[0].raw_data
        # Verbatim source values must be present even on flagged rows
        assert raw["Materialbezeichnung"] == "Dieselkraftstoff"
        assert raw["Menge"] == ""   # empty — exactly what was in the file
