# SAN MICHEL TEAM TOURNAMENT | 2025

**Club:** Tennis Club Kordin (TCK), Malta
**Year:** 2025
**Source:** Club website
**Source URL:** [https://www.tennisclubkordin.com/tournament-archive](https://www.tennisclubkordin.com/tournament-archive)
**Source spreadsheet:** [docs.google.com/spreadsheets/d/12Q3amFJlIA4fxhIMj8ZwC5MTdELcCpnc6TD5CHREmAs](https://docs.google.com/spreadsheets/d/12Q3amFJlIA4fxhIMj8ZwC5MTdELcCpnc6TD5CHREmAs)
**Extraction method:** HTTP scrape — `tournament-archive` page parsed for `<a aria-label>` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:44 UTC

## Files in this folder

- `SAN MICHEL TEAM TOURNAMENT 2025.xlsx` (sha256 `a51588c8609c…`)
- `raw/archive-page.html` — full archive HTML at scrape time (single page lists every TCK tournament).

## Provenance

Extracted from the public TCK tournament archive by `scripts/scraper/tck.py`.
The site is built on Wix; tournament-to-sheet mapping is recovered from the
`aria-label` attribute on each Wix button.

To re-extract: `python scripts/scraper/tck.py all` (idempotent).
