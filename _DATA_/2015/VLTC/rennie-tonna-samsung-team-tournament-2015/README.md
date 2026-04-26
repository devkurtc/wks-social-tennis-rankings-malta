# Rennie Tonna Samsung Team Tournament 2015

**Club:** Vittoriosa Lawn Tennis Club (VLTC), Malta
**Year:** 2015
**Source:** Club website
**Source URL:** [https://www.vltc.com.mt/tournament.aspx?id=41](https://www.vltc.com.mt/tournament.aspx?id=41)
**Extraction method:** HTTP scrape — `tournament.aspx?id=41` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:54 UTC

## Files in this folder

- `Rennie Tonna Samsung Team Tournament 2015.xlsx` (Google Sheet ID `1m31ChBkGoCV04cwQvNKzTIl8YcR9aXsu_N43c9RTOck`, sha256 `…`)
- `raw/detail-page.html` — original HTML of the tournament detail page at scrape time.

## Provenance

This folder contains data extracted automatically from the VLTC public tournament archive
by `scripts/scraper/vltc.py`. The detail page is captured as raw HTML for audit purposes;
the `.xlsx` files are downloaded via Google Sheets' public `export?format=xlsx` endpoint.

To re-extract: `python scripts/scraper/vltc.py download` (idempotent — only re-writes
files whose Google Sheet content has changed).
