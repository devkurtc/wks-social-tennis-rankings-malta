# San Michel Team T'ment 2023

**Club:** Vittoriosa Lawn Tennis Club (VLTC), Malta
**Year:** 2023
**Source:** Club website
**Source URL:** [https://www.vltc.com.mt/tournament.aspx?id=121](https://www.vltc.com.mt/tournament.aspx?id=121)
**Extraction method:** HTTP scrape — `tournament.aspx?id=121` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:56 UTC

## Files in this folder

- `San Michel Team T'ment 2023.xlsx` (Google Sheet ID `1LF7gRLryi1Mzp1p1h1KrtqCwqYCL5zvn`, sha256 `2bdbcdc83124…`)
- `raw/detail-page.html` — original HTML of the tournament detail page at scrape time.

## Provenance

This folder contains data extracted automatically from the VLTC public tournament archive
by `scripts/scraper/vltc.py`. The detail page is captured as raw HTML for audit purposes;
the `.xlsx` files are downloaded via Google Sheets' public `export?format=xlsx` endpoint.

To re-extract: `python scripts/scraper/vltc.py download` (idempotent — only re-writes
files whose Google Sheet content has changed).
