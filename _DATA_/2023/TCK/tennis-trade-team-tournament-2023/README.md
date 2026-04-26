# TENNIS TRADE TEAM TOURNAMENT | 2023

**Club:** Tennis Club Kordin (TCK), Malta
**Year:** 2023
**Source:** Club website
**Source URL:** [https://www.tennisclubkordin.com/tournament-archive](https://www.tennisclubkordin.com/tournament-archive)
**Source spreadsheet:** [docs.google.com/spreadsheets/d/1a86V0pyRIWafRwiy5PawvPwdyzlcPGJPA5k8gQMxEBA](https://docs.google.com/spreadsheets/d/1a86V0pyRIWafRwiy5PawvPwdyzlcPGJPA5k8gQMxEBA)
**Extraction method:** HTTP scrape — `tournament-archive` page parsed for `<a aria-label>` + Google Sheets `export?format=xlsx`
**Last extracted:** 2026-04-26 06:44 UTC

## Files in this folder

- `TENNIS TRADE TEAM TOURNAMENT 2023.xlsx` (sha256 `a4c29c160ce8…`)
- `raw/archive-page.html` — full archive HTML at scrape time (single page lists every TCK tournament).

## Provenance

Extracted from the public TCK tournament archive by `scripts/scraper/tck.py`.
The site is built on Wix; tournament-to-sheet mapping is recovered from the
`aria-label` attribute on each Wix button.

To re-extract: `python scripts/scraper/tck.py all` (idempotent).
