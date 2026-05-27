# Source Research Notes — ESG Ingestion Platform

This document records what was researched about each real-world data source before building the parsers, what the sample data is based on, and what a production implementation would need to handle that the prototype does not.

---

## 1. SAP Fuel / Procurement Exports

### What was researched

SAP ECC and S4HANA procurement exports can be generated from several standard transactions depending on what the client is tracking:

- **MB51** (Material Document List) — the most common source for fuel and consumable tracking. Produces one row per goods movement posting with material number, plant, quantity, unit, and posting date.
- **ME2M** (Purchase Orders by Material) — used when fuel is tracked through purchase orders rather than goods receipts. Columns differ from MB51.
- **Custom ABAP reports** — many SAP installations have client-specific reports that pull from EKPO/EKKO (purchasing tables) or MSEG (material movement tables) with client-defined column names.

The column names in a standard MB51 export in German locale are: `Buchungsdatum`, `Werk`, `Materialnummer`, `Materialbezeichnung`, `Menge`, `Einheit`, `Kostenstelle`, `Belegtext`. These are stable across ECC 6.0 and S4HANA in German language settings.

The date field (`Buchungsdatum`) exports in the format `DD.MM.YYYY` when the user's SAP locale is set to German, and `YYYY-MM-DD` when set to ISO/international. Both formats appear in real exports from the same SAP system if different users trigger the export with different profile settings.

Numeric values follow the locale setting: German locale produces `1.200,50` (period as thousands separator, comma as decimal). This is a common and silent failure mode — `float("1.200,50")` raises a `ValueError` in Python without locale-aware parsing.

The `Einheit` (unit) field is free-text in many SAP configurations and reflects whatever unit of measure was set on the material master. Real exports contain `L`, `l`, `Liter`, `liter`, `m3`, `m³` (with unicode superscript three), `KG`, `kg` — all meaning the same things, all requiring normalisation.

SAP exports frequently include a UTF-8 BOM (byte order mark, `\xef\xbb\xbf`) prepended to the file. Python's default `utf-8` codec does not strip this, which means the first column header reads as `\ufeffBuchungsdatum` rather than `Buchungsdatum`, silently breaking all column lookups. The `utf-8-sig` codec strips it automatically.

### Why the sample data looks realistic

The sample file (`fixtures/sample_sap_fuel.csv`) was constructed to represent the actual variance seen in SAP exports:

- Three date formats in the same file (`15.01.2024`, `2024-01-18`, `20/01/2024`) — reflecting different user locale settings
- Unit variants in the same file (`L`, `Liter`, `l`, `m3`, `m³`) — reflecting different material master configurations
- One row with an empty `Menge` field (`Fehlbuchung` — "incorrect posting") — SAP allows posting reversals that leave quantity blank
- One row with quantity `99999` and note `TESTBUCHUNG BITTE IGNORIEREN` — test postings that reach production exports are common in SAP environments without strict posting controls
- Plant codes in `WERK_XXX` format — standard SAP plant code convention for German manufacturing sites
- Cost centres in `CC-XXXX` format — standard cost centre notation

### What would fail in production

**Semicolon delimiters.** SAP exports in German locale use semicolons as CSV delimiters by default, not commas, because the comma is the decimal separator. The parser currently assumes comma-delimited input. A German-locale SAP export would be misread entirely. The fix is delimiter auto-detection using Python's `csv.Sniffer`.

**Multi-line text fields.** The `Belegtext` (document text) field can contain line breaks if the SAP user entered multi-line notes. Standard CSV parsing breaks on unquoted line breaks. SAP's export tool does not consistently quote fields containing line breaks.

**Encoding beyond UTF-8.** Older SAP ECC installations may export in Windows-1252 or ISO-8859-1 encoding, particularly if the system was set up before Unicode was standard in SAP. A file that opens correctly in Excel (which auto-detects encoding) will fail in Python with a `UnicodeDecodeError`.

**Material number vs description matching.** The parser currently maps fuel type from the `Materialbezeichnung` (material description) field. Material descriptions are free-text and change when a client renames a material in SAP. A production system would need a configurable mapping table per tenant that maps material numbers (which are stable identifiers) to fuel types, with description matching as a fallback only.

**Split postings.** A single fuel delivery in SAP is sometimes posted across multiple cost centres, producing multiple rows with fractions of the total quantity. The parser treats each row independently, which would double-count the delivery if both rows are approved. Detection requires grouping by delivery document number (`Belegnummer`), which is not always present in standard exports.

---

## 2. Utility Portal Exports

### What was researched

Utility electricity data does not have a standard export format. Each supplier portal produces different CSV structures. The most common patterns across UK and European suppliers were:

**E.ON, EDF, British Gas (UK):** Account-based exports with one row per invoice, columns for billing period start/end, kWh consumption, maximum demand (kW), unit rate, standing charge, and total cost. Column names vary between portal versions.

**Vattenfall, E.ON (Germany/Sweden):** Similar structure but with European date formatting, period dates as `DD.MM.YYYY`, and cost in EUR rather than GBP.

**Half-hourly (HH) data:** Large industrial sites with smart meters receive half-hourly consumption data — one row per 30-minute interval per meter point. This is a fundamentally different format: a monthly bill produces ~1,440 rows rather than 1. HH data requires aggregation before emission factor application.

**MPAN numbers:** UK electricity meters are identified by a Master Point Access Number (MPAN) — a 21-digit identifier. Some portal exports use MPAN as the meter identifier, others use an account-specific meter serial number. Both appear in real exports from the same supplier depending on which download option the user selects.

Billing periods in utility data are frequently non-calendar-aligned. A bill covering 15 January to 14 February is common. Quarterly bills covering 90–92 days are standard for smaller SME accounts. Six-month consolidated bills appear when a client misses a download cycle and downloads two periods at once.

Duplicate invoices are a genuine and common problem. Utility portals allow re-downloading historical bills, which produces identical invoice numbers and data. Finance teams frequently re-download when reconciling against accounting systems, producing the same bill in two separate uploads.

Negative kWh values represent credit notes — supplier corrections to a previously overbilled period. These are legitimate accounting entries and should not be rejected outright. A credit note typically references the original invoice number in the notes field, though this is not standardised.

### Why the sample data looks realistic

The sample file (`fixtures/sample_utility.csv`) was constructed to cover the variance patterns that cause real parsing failures:

- Mixed date formats in the same file (`01/01/2024` and `2024-01-01`) — reflecting different portal export versions
- One row with empty `usage_kwh` — a meter read that failed to transmit, common with smart meters on poor connectivity
- An exact duplicate row (`INV-BER-002` appears twice) — simulating a re-downloaded bill
- An overlapping billing period (`INV-2024-001` appears as both a January-only bill and a 15 Jan – 15 Feb bill) — simulating an amended bill re-issued by the supplier
- A quarterly bill (`INV-HAM-OFF-Q1`, covering January–March) — legitimate, not a parsing error
- A negative kWh row (`INV-2024-CREDIT`, -500 kWh) — a supplier credit note
- An implausibly high consumption row (95,000 kWh for a single month) — near the upper plausibility bound for a large industrial site

### What would fail in production

**Half-hourly meter data.** The parser is built for invoice-level data (one row per bill). HH data produces thousands of rows per meter per month, each representing 30 minutes of consumption. Applying emission factors to HH data requires knowing the grid intensity at each half-hour interval, not just a monthly average — a requirement that the current flat factor table does not support.

**Renewable energy certificate handling.** A client with a 100% renewable electricity contract (Power Purchase Agreement or REGO certificates) should report zero Scope 2 emissions under the market-based method. The parser has no awareness of tariff type and would incorrectly calculate CO2e for renewable tariffs. The `tariff_code` field is captured in raw data but not used in any calculation.

**Multi-site account rollups.** Some utility accounts cover multiple meters or multiple sites under a single invoice number. A single invoice row may represent the aggregate consumption of an entire building portfolio. The parser treats each row as one meter point, which would attribute all consumption to no specific site when the account covers several.

**Supplier portal changes.** Utility portals update their export formats periodically without notice. A column that was called `usage_kwh` in 2023 may be called `consumption_kwh` or `energy_consumed` in 2024. The column alias table in `utility_constants.py` covers the known variants but cannot anticipate future changes. Production would require a monitoring process that alerts when column names change.

**VAT and tax components.** Some portal exports include VAT, Climate Change Levy (CCL), and other tax components as separate line items in the cost breakdown. The current parser takes `cost_gbp` as a total. If the export breaks down cost by component, the total cost may need to be reconstructed from multiple columns.

---

## 3. Corporate Travel Exports

### What was researched

The two dominant corporate travel and expense platforms are SAP Concur and Navan (formerly TripActions). Both support CSV exports of expense reports, but with different field names and different levels of detail.

**SAP Concur:** Expense reports export with columns for expense type, transaction date, merchant name, amount, currency, and custom fields configured by the client's expense policy administrator. Travel-specific fields (origin, destination, distance) are populated only if the client has enabled the travel booking integration. Many Concur deployments use it as an expense approval tool only, without booking integration, in which case flight details are typed manually by the traveller.

**Navan:** More opaque exports. Navan captures booking data directly and can produce structured exports with airport codes, booking class, and distance where known. Field names differ from Concur.

**The flight class problem:** Economy, premium economy, business, and first class have significantly different emission factors under DEFRA methodology — business class produces approximately 3× the CO2e of economy for the same route due to the greater physical space allocated per passenger. Expense systems sometimes capture booking class at the fare level (`Y`, `B`, `J`, `F` IATA codes) rather than the readable category level. Mapping fare codes to cabin classes requires an IATA fare code lookup table.

**Airport code coverage:** IATA publishes approximately 10,000 active airport codes. A European company's travel data will typically involve 20–50 distinct airports covering major European hubs, transatlantic routes, and Middle East/Asia connections. A lookup table of common city pairs covers 80–90% of routes without requiring an API call.

**Hotel emissions:** The GHG Protocol methodology for hotel stays is per room-night, with factors varying by star rating, country, and whether the hotel has its own renewable energy. DEFRA publishes a single UK average factor. Concur exports rarely include hotel star rating or location granularity beyond city name, making differentiated factor application impractical without additional data sources.

**Ground transport mix:** Taxi and rail entries in expense systems are inconsistently categorised. An Uber journey may be categorised as "taxi", "car hire", "transportation", or "ground transport" depending on the client's expense category configuration. Distance is almost never captured for taxis — the parser falls back to flagging taxi records without explicit distance for manual entry.

### Why the sample data looks realistic

The sample file (`fixtures/sample_travel.csv`) was constructed to reflect the patterns that create real parsing challenges:

- Flights with only airport codes and no distance (`LHR → MUC`) — the common case where Concur has no booking integration and the traveller provides only route
- All three cabin classes represented (economy, business, first) with realistic cost differentials
- A hotel record with explicit nights (`3` nights, Munich) — how Concur structures accommodation
- Rail with explicit distance (`London → Birmingham, 188 km`) — how ground transport appears when distance is known
- A taxi with an implausible distance (`999 km`) — a data entry error or miscategorised intercity transfer
- A flight with identical origin and destination (`LHR → LHR`) — a data entry error that would produce zero distance and zero CO2e without detection
- A long-haul route at the edge of the lookup table (`LHR → SYD`, 16,993 km) — to verify the lookup handles extreme distances correctly
- First class Emirates (`LHR → DXB`) — legitimate but high CO2e, surfaced to analysts via `extra["first_class"]: True`

### What would fail in production

**Routes not in the lookup table.** The airport distance lookup covers ~30 common routes. Any route outside this set is flagged for manual distance entry. A company with operations in South America, Africa, or Southeast Asia would see a high flag rate for flights. Production would require either a comprehensive IATA distance database or integration with a flight data API (OAG, FlightAware, or similar).

**Multi-leg itineraries as single rows.** Concur sometimes rolls a multi-leg journey into a single expense row with the origin of the first leg and the destination of the last. A London → Frankfurt → Singapore itinerary might appear as `LHR → SIN` with the Frankfurt connection invisible. Great-circle distance from LHR to SIN understates the actual routing. The parser has no mechanism to detect or correct this.

**Fare code to cabin class mapping.** When Concur exports fare codes (`Y`, `B`, `J`, `F`) rather than cabin names, the parser cannot determine the emission factor without an IATA fare code lookup table. The current implementation falls back to economy class in this case, which would understate CO2e for business and first class bookings if fare codes are present.

**Currency conversion.** Expense reports from international employees are submitted in local currency. A New York-based employee's expenses are in USD; a Paris-based employee's are in EUR. The `cost_gbp` field in the parser assumes GBP. A production system would need to capture original currency, store the exchange rate at the time of the expense, and convert to reporting currency at ingestion — or at query time, depending on the reporting requirement.

**Personal vs business travel.** Concur exports include all approved expense claims. Some companies allow personal travel to be booked through the corporate travel tool and expensed at a partial rate. Personal travel should not be included in Scope 3 business travel reporting. The parser has no way to distinguish personal from business travel without an expense category filter that is specific to each client's Concur configuration.

**Hotel country for emission factor selection.** The parser uses a single DEFRA UK average factor for all hotel stays regardless of country. A hotel stay in Germany, France, or the US has a different emission profile. Accurate hotel emission reporting requires the country of the hotel, which is available in Concur's location field but not always exported in the standard CSV format.
