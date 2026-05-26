"""
Tests for validation rules.

These tests use a mock record object rather than a real Django model,
so they run without a database. This is intentional — rules should be
testable in complete isolation.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock
import pytest

from apps.ingestion.validation.rules import (
    NegativeQuantityRule,
    ZeroQuantityRule,
    NegativeCO2eRule,
    ZeroEmissionFactorRule,
    FutureDateRule,
    ImplausibleDateRule,
    StatisticalOutlierRule,
    DuplicateRecordRule,
    InvalidUnitRule,
)
from apps.ingestion.validation.base import Severity


def mock_record(**kwargs):
    """
    Build a mock EmissionRecord with sensible defaults.
    Only override what each test needs.
    """
    defaults = {
        "id": "test-uuid-001",
        "tenant_id": "tenant-uuid-001",
        "source_type": "sap_fuel",
        "activity_date": date(2024, 1, 15),
        "quantity": 450.5,
        "unit": "litre",
        "co2e_kg": 1189.0,
        "emission_factor": 2.6391,
        "emission_factor_source": "DEFRA 2023",
        "status": "pending_review",
    }
    defaults.update(kwargs)
    record = MagicMock()
    for k, v in defaults.items():
        setattr(record, k, v)
    return record


EMPTY_CONTEXT = {
    "quantity_stats": {},
    "existing_fingerprints": set(),
}


class TestNegativeQuantityRule:
    rule = NegativeQuantityRule()

    def test_negative_quantity_flagged(self):
        record = mock_record(quantity=-100, source_type="sap_fuel")
        issues = self.rule.check(record, EMPTY_CONTEXT)
        assert len(issues) == 1
        assert issues[0].severity == Severity.ERROR

    def test_negative_utility_kwh_flagged_as_credit_note(self):
        record = mock_record(quantity=-500, source_type="utility")
        issues = self.rule.check(record, EMPTY_CONTEXT)
        assert len(issues) == 1
        assert "credit note" in issues[0].message.lower()

    def test_positive_quantity_clean(self):
        record = mock_record(quantity=450.5)
        issues = self.rule.check(record, EMPTY_CONTEXT)
        assert issues == []


class TestZeroQuantityRule:
    rule = ZeroQuantityRule()

    def test_zero_quantity_warns(self):
        record = mock_record(quantity=0)
        issues = self.rule.check(record, EMPTY_CONTEXT)
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING

    def test_nonzero_clean(self):
        record = mock_record(quantity=100)
        assert self.rule.check(record, EMPTY_CONTEXT) == []


class TestNegativeCO2eRule:
    rule = NegativeCO2eRule()

    def test_negative_co2e_is_error(self):
        record = mock_record(co2e_kg=-50)
        issues = self.rule.check(record, EMPTY_CONTEXT)
        assert len(issues) == 1
        assert issues[0].severity == Severity.ERROR

    def test_zero_co2e_is_clean(self):
        # Zero CO2e is caught by ZeroEmissionFactorRule, not this one
        record = mock_record(co2e_kg=0)
        assert self.rule.check(record, EMPTY_CONTEXT) == []


class TestFutureDateRule:
    rule = FutureDateRule()

    def test_future_date_is_error(self):
        record = mock_record(activity_date=date.today() + timedelta(days=10))
        issues = self.rule.check(record, EMPTY_CONTEXT)
        assert len(issues) == 1
        assert issues[0].severity == Severity.ERROR

    def test_today_is_clean(self):
        record = mock_record(activity_date=date.today())
        assert self.rule.check(record, EMPTY_CONTEXT) == []

    def test_past_date_is_clean(self):
        record = mock_record(activity_date=date(2023, 6, 15))
        assert self.rule.check(record, EMPTY_CONTEXT) == []


class TestImplausibleDateRule:
    rule = ImplausibleDateRule()

    def test_pre_2010_date_warns(self):
        record = mock_record(activity_date=date(2005, 3, 1))
        issues = self.rule.check(record, EMPTY_CONTEXT)
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING

    def test_2010_is_clean(self):
        record = mock_record(activity_date=date(2010, 1, 1))
        assert self.rule.check(record, EMPTY_CONTEXT) == []


class TestStatisticalOutlierRule:
    rule = StatisticalOutlierRule()

    def _context_with_stats(self, mean, stdev, count=20):
        return {
            "quantity_stats": {
                "sap_fuel": {"mean": mean, "stdev": stdev, "count": count}
            },
            "existing_fingerprints": set(),
        }

    def test_outlier_flagged(self):
        # Mean=400, stdev=50 → threshold at 400 + 3*50 = 550
        context = self._context_with_stats(mean=400, stdev=50)
        record = mock_record(quantity=700, source_type="sap_fuel")
        issues = self.rule.check(record, context)
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING

    def test_normal_value_clean(self):
        context = self._context_with_stats(mean=400, stdev=50)
        record = mock_record(quantity=420, source_type="sap_fuel")
        assert self.rule.check(record, context) == []

    def test_skipped_with_insufficient_data(self):
        context = self._context_with_stats(mean=400, stdev=50, count=5)
        record = mock_record(quantity=9999, source_type="sap_fuel")
        # Fewer than MIN_SAMPLE_SIZE records → rule skipped
        assert self.rule.check(record, context) == []

    def test_skipped_when_no_stats_for_type(self):
        record = mock_record(quantity=9999, source_type="travel")
        assert self.rule.check(record, EMPTY_CONTEXT) == []


class TestDuplicateRecordRule:
    rule = DuplicateRecordRule()

    def test_duplicate_fingerprint_warns(self):
        record = mock_record(
            tenant_id="tenant-1",
            source_type="utility",
            activity_date=date(2024, 1, 15),
            quantity=5000,
            unit="kWh",
        )
        context = {
            "quantity_stats": {},
            "existing_fingerprints": {
                ("tenant-1", "utility", "2024-01-15", "5000", "kWh")
            },
        }
        issues = self.rule.check(record, context)
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING

    def test_unique_record_clean(self):
        record = mock_record()
        assert self.rule.check(record, EMPTY_CONTEXT) == []


class TestInvalidUnitRule:
    rule = InvalidUnitRule()

    def test_wrong_unit_for_source_type(self):
        record = mock_record(source_type="utility", unit="litre")
        issues = self.rule.check(record, EMPTY_CONTEXT)
        assert len(issues) == 1
        assert issues[0].severity == Severity.ERROR

    def test_correct_unit_clean(self):
        record = mock_record(source_type="utility", unit="kWh")
        assert self.rule.check(record, EMPTY_CONTEXT) == []

    def test_unknown_source_type_skipped(self):
        # No valid units defined for unknown type — rule skips
        record = mock_record(source_type="unknown_type", unit="anything")
        assert self.rule.check(record, EMPTY_CONTEXT) == []
