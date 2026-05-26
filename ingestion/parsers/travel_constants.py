"""
Corporate Travel Parser — Constants
-------------------------------------

AIRPORT DISTANCE APPROACH:
We store great-circle distances between common airport pairs.
This is a deliberate simplification for a 4-day build.

WHY NOT A REAL DISTANCE API:
- Requires an API key and network call per row
- Adds latency and failure modes to ingestion
- Overkill for a prototype — ICAO distances are stable facts

WHAT THIS MISSES IN PRODUCTION:
- Actual flight routing is rarely great-circle (air traffic control)
- Real tools use ICAO routing factors (~8-9% longer than great-circle)
- GHG Protocol aviation methodology includes radiative forcing multiplier (RFI)
  which doubles the effective CO2e for high-altitude emissions
"""

# ---------------------------------------------------------------------------
# Column aliases — Concur and Navan use slightly different export headers
# ---------------------------------------------------------------------------
COLUMN_ALIASES = {
    # Expense ID
    "expense_id": "expense_id",
    "expense_report_id": "expense_id",
    "report_id": "expense_id",
    "transaction_id": "expense_id",

    # Employee
    "employee_id": "employee_id",
    "emp_id": "employee_id",
    "user_id": "employee_id",
    "traveller_id": "employee_id",

    # Department
    "department": "department",
    "cost_center": "department",
    "cost_centre": "department",
    "business_unit": "department",

    # Date
    "travel_date": "travel_date",
    "expense_date": "travel_date",
    "transaction_date": "travel_date",
    "departure_date": "travel_date",
    "date": "travel_date",

    # Travel type
    "travel_type": "travel_type",
    "expense_type": "travel_type",
    "category": "travel_type",
    "type": "travel_type",
    "mode": "travel_type",

    # Origin / destination
    "origin": "origin",
    "from": "origin",
    "departure": "origin",
    "origin_airport": "origin",

    "destination": "destination",
    "to": "destination",
    "arrival": "destination",
    "destination_airport": "destination",

    # Distance
    "distance_km": "distance",
    "distance": "distance",
    "miles": "distance",
    "km": "distance",

    "distance_unit": "distance_unit",
    "unit": "distance_unit",

    # Hotel nights
    "nights": "nights",
    "no_of_nights": "nights",
    "hotel_nights": "nights",

    # Class of travel
    "transport_class": "travel_class",
    "class": "travel_class",
    "cabin_class": "travel_class",
    "fare_class": "travel_class",

    # Vendor
    "vendor": "vendor",
    "airline": "vendor",
    "carrier": "vendor",
    "hotel_name": "vendor",
    "supplier": "vendor",

    # Cost
    "cost_gbp": "cost_gbp",
    "amount": "cost_gbp",
    "total_cost": "cost_gbp",
    "cost": "cost_gbp",

    # Notes
    "notes": "notes",
    "description": "notes",
    "memo": "notes",
}

REQUIRED_COLUMNS = {"travel_date", "travel_type"}

# ---------------------------------------------------------------------------
# Travel type normalisation
# Maps Concur/Navan category strings → our canonical types
# ---------------------------------------------------------------------------
TRAVEL_TYPE_ALIASES = {
    "flight": "flight",
    "air": "flight",
    "airline": "flight",
    "plane": "flight",
    "aviation": "flight",

    "hotel": "hotel",
    "accommodation": "hotel",
    "lodging": "hotel",

    "rail": "rail",
    "train": "rail",
    "eurostar": "rail",
    "railway": "rail",

    "taxi": "taxi",
    "cab": "taxi",
    "uber": "taxi",
    "car": "taxi",
    "rental car": "taxi",
    "car hire": "taxi",
    "rideshare": "taxi",
}

# ---------------------------------------------------------------------------
# Great-circle distances between common airport pairs (km)
# Stored as frozenset so {LHR, MUC} == {MUC, LHR}
#
# Source: calculated from IATA coordinates, rounded to nearest km
# Coverage: routes most likely to appear in a European HQ company's travel
# ---------------------------------------------------------------------------
AIRPORT_DISTANCES_KM: dict[frozenset, int] = {
    frozenset({"LHR", "MUC"}): 1447,
    frozenset({"LHR", "JFK"}): 5541,
    frozenset({"LHR", "CDG"}): 342,
    frozenset({"LHR", "FRA"}): 641,
    frozenset({"LHR", "AMS"}): 370,
    frozenset({"LHR", "DXB"}): 5494,
    frozenset({"LHR", "SYD"}): 16993,
    frozenset({"LHR", "SIN"}): 10841,
    frozenset({"LHR", "BOS"}): 5265,
    frozenset({"LHR", "ORD"}): 6343,
    frozenset({"LHR", "LAX"}): 8741,
    frozenset({"LHR", "HKG"}): 9648,
    frozenset({"LHR", "NRT"}): 9552,
    frozenset({"LHR", "ZRH"}): 784,
    frozenset({"LHR", "BCN"}): 1138,
    frozenset({"LHR", "MAD"}): 1244,
    frozenset({"LHR", "FCO"}): 1443,
    frozenset({"LHR", "BRU"}): 319,
    frozenset({"LHR", "VIE"}): 1238,
    frozenset({"LHR", "WAW"}): 1452,
    frozenset({"MUC", "JFK"}): 6448,
    frozenset({"MUC", "CDG"}): 828,
    frozenset({"MUC", "FRA"}): 304,
    frozenset({"MUC", "DXB"}): 4739,
    frozenset({"CDG", "JFK"}): 5834,
    frozenset({"CDG", "FRA"}): 449,
    frozenset({"JFK", "DXB"}): 11016,
    frozenset({"JFK", "LAX"}): 3983,
    frozenset({"FRA", "DXB"}): 4846,
    frozenset({"FRA", "JFK"}): 6198,
}

# ---------------------------------------------------------------------------
# Emission factors — kg CO2e per passenger km
#
# Source: DEFRA 2023 — Business Travel
# These are per-passenger factors including radiative forcing for flights.
#
# WHY INCLUDE RADIATIVE FORCING (RFI):
# Aviation emissions at altitude have ~2x the warming effect vs ground level.
# GHG Protocol recommends including RFI for Scope 3 aviation reporting.
# DEFRA's factors already include this for 'with RFI' variants.
# ---------------------------------------------------------------------------
EMISSION_FACTORS: dict[str, dict] = {
    "flight": {
        "economy":          {"co2e_per_pkm": 0.18817, "source": "DEFRA 2023 — Aviation economy with RFI"},
        "business":         {"co2e_per_pkm": 0.56451, "source": "DEFRA 2023 — Aviation business with RFI"},
        "first":            {"co2e_per_pkm": 0.75268, "source": "DEFRA 2023 — Aviation first with RFI"},
        "premium_economy":  {"co2e_per_pkm": 0.28226, "source": "DEFRA 2023 — Aviation premium economy with RFI"},
        "unknown":          {"co2e_per_pkm": 0.18817, "source": "DEFRA 2023 — Aviation economy with RFI (default)"},
    },
    "rail": {
        "unknown":          {"co2e_per_pkm": 0.03549, "source": "DEFRA 2023 — Rail (UK average)"},
    },
    "taxi": {
        "unknown":          {"co2e_per_pkm": 0.14868, "source": "DEFRA 2023 — Taxi/rideshare average"},
    },
    "hotel": {
        # Per room-night, not per km
        "unknown":          {"co2e_per_night": 20.8, "source": "DEFRA 2023 — Hotel stay UK average"},
    },
}

# ---------------------------------------------------------------------------
# Date formats
# ---------------------------------------------------------------------------
DATE_FORMATS = [
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%m/%d/%Y",
    "%d %b %Y",
]

# ---------------------------------------------------------------------------
# Validation bounds
# ---------------------------------------------------------------------------
MAX_TAXI_KM = 200        # anything over 200km by taxi is implausible
MAX_FLIGHT_KM = 20_000   # longest commercial route ~17,000km (LHR-SYD)
MAX_HOTEL_NIGHTS = 30    # monthly stay is the sensible upper bound
MAX_COST_GBP = 15_000    # single expense above this warrants a flag
