"""
Base parser interface.

WHY A BASE CLASS:
Every parser (SAP, utility, travel) shares the same contract:
  - receive a file path and metadata
  - return a ParseResult

This means the ingestion service doesn't need to know which parser it's
calling. It calls parse() and gets back a consistent structure.
New source types plug in without touching the ingestion service.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedRow:
    """
    One successfully parsed and normalised row.
    Both raw_data and normalised fields are carried together so the
    ingestion service can write RawRecord and EmissionRecord in one pass.
    """
    row_number: int
    raw_data: dict[str, Any]          # verbatim source row — goes to RawRecord
    activity_date: Any                # datetime.date
    description: str
    quantity: float
    unit: str                         # canonical unit after normalisation
    co2e_kg: float
    emission_factor: float
    emission_factor_source: str
    scope: int
    source_type: str
    extra: dict = field(default_factory=dict)   # source-specific fields (plant_code etc.)


@dataclass
class FlaggedRow:
    """
    One row that failed validation.
    Carries enough information to write a RawRecord and a flagged EmissionRecord.
    """
    row_number: int
    raw_data: dict[str, Any]
    flag_type: str                    # matches FlagType enum values
    flag_reason: str


@dataclass
class ParseResult:
    """
    Everything the ingestion service needs after parsing completes.
    """
    parsed_rows: list[ParsedRow] = field(default_factory=list)
    flagged_rows: list[FlaggedRow] = field(default_factory=list)
    fatal_error: str = ""             # non-empty = entire file rejected

    @property
    def has_fatal_error(self) -> bool:
        return bool(self.fatal_error)

    @property
    def total_rows(self) -> int:
        return len(self.parsed_rows) + len(self.flagged_rows)


class BaseParser:
    """
    All parsers inherit from this and implement parse().
    """
    source_type: str = ""

    def parse(self, file_path: str) -> ParseResult:
        raise NotImplementedError
