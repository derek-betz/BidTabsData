# Tools Directory

This directory contains utilities and scripts for working with the BidTabs data.

## Purpose

Tools in this directory can be used for:
- Processing BidTabs .xls files
- Validating data integrity
- Converting or transforming data
- Automating release processes

## Usage

Refer to individual tool documentation for specific usage instructions.

## Default macOS Pull Path: Public INDOT Unit Tab Results

`indot_public_bidtabs_puller.py` is the proposed/default pull path for
BidTabsData going forward. It uses INDOT's public contract letting pages,
letting archives, and Unit Tab Results PDFs. It does not need BidTabs/Oman
credentials and works on macOS with `pdftotext` available.

The parser is intended for the modern public PDF layout used from 2018 forward.
INDOT public archive pages exist farther back, but older pre-2018 layouts often
split Unit Tab Results by category and should be handled by a future historical
backfill parser.

Generated CSVs keep the legacy BidTabsData columns and append:

- `DistrictIDs`: comma-separated numeric INDOT district IDs, e.g. `2,4`.
- `DistrictNames`: comma-separated canonical names, e.g. `FORT WAYNE,LAPORTE`.

`DistrictIDs` is the authoritative field for new consumers. `Region` remains a
single legacy numeric value for backward compatibility; for multi-district
contracts it is the first district listed by INDOT.

Discover public letting pages:

```sh
tools/indot_public_bidtabs_puller.py list
```

Export new public Unit Tab Results into `data/BidTabsData`:

```sh
tools/indot_public_bidtabs_puller.py weekly --output-dir data/BidTabsData
```

Weekly automation command:

```sh
tools/indot_public_bidtabs_puller.py weekly --output-dir data/BidTabsData
git status --short
```

The weekly command exports missing public CSVs in the lookback window, skips
dates already represented by legacy `.xls` files, and upgrades older generated
public CSVs when the schema improves.

Export one or more specific dates:

```sh
tools/indot_public_bidtabs_puller.py export-date 2026-04-08 2026-05-07 --output-dir data/BidTabsData
```

Validate generated CSV headers and required fields:

```sh
tools/indot_public_bidtabs_puller.py validate-csv data/BidTabsData/2026-04-08.csv
```

Compare public CSV output to legacy `.xls` exports:

```sh
tools/indot_public_bidtabs_puller.py compare-xls \
  2026-01-14 2026-02-11 2026-03-11 2026-04-15 \
  --refresh-public
```

The compare command reports old rows recovered, exact and penny-tolerant
financial matches, public-only contracts/rows, missing required fields, and
multi-district rows. It uses `xlrd` for legacy `.xls` reads.

### Legacy Diagnostic/Fallback: Oman SOAP Puller

`bidtabs_mac_puller.py` talks directly to the BidTabs.NET SOAP service used by
the Windows ClickOnce app. It needs valid BidTabs license credentials for
protected data calls, and the protected path appears machine/license-bound. Keep
it for diagnostics or fallback checks only; do not use it as the normal macOS
weekly pull path.

Secrets are read from environment variables first and then macOS Keychain.
Use a local text or RTF file with `BIDTABS_*` lines, then import it:

```sh
tools/bidtabs_mac_puller.py import-credentials ~/Downloads/BidTabs\ Credentials.rtf
```

Check readiness without revealing secrets:

```sh
tools/bidtabs_mac_puller.py status
```

Protected data exports require `BIDTABS_CUSTOMER_ID`, `BIDTABS_USER_ID`, and
`BIDTABS_PASSWORD`. Once those are present:

```sh
tools/bidtabs_mac_puller.py weekly --state IN --output-dir data/BidTabsData
```
