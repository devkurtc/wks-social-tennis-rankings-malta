# `_DATA_/` — RallyRank source data

Authoritative tournament data, organized by **year → club → tournament**.

> **Read-only by convention.** Cleanup belongs in the parsers, not in the source
> files (per `CLAUDE.md`). Two exceptions: (1) the scrapers in
> `scripts/scraper/` write into this tree, and (2) the one-shot reorganizer
> `scripts/scraper/organize.py` re-shaped the legacy flat layout.

## Structure

```
_DATA_/
├── README.md                                  ← this file
├── 2017/ … 2026/                              ← year of the tournament
│   └── <CLUB>/                                ← e.g. VLTC, TCK
│       └── <tournament-slug>/
│           ├── README.md                      ← provenance: source, date, method
│           ├── <Original Tournament Name>.xlsx
│           └── raw/
│               └── detail-page.html           ← snapshot of the source HTML, if scraped
├── _clubs/                                    ← per-club scrape manifests
│   └── TCK/manifest.json
├── _templates/                                ← blank template files (no tournament data)
├── _unsorted/                                 ← files where year couldn't be inferred
└── VLTC/scraped/manifest.json                 ← VLTC scrape manifest (legacy path)
```

Each tournament folder holds **all sources for that tournament** —
both files extracted from a club website (with raw HTML snapshot for audit) and
local copies that pre-existed in this repo. Sources can co-exist; the parser
dispatcher in `scripts/phase0/cli.py` matches on filename substring (after
lowercasing), so any of them can be loaded with `cli.py load --file <path>`.

## How data lands here

| Source | Tooling | Marker in tournament README |
|---|---|---|
| **VLTC website** (www.vltc.com.mt) | `python scripts/scraper/vltc.py all` | `Source: Club website` + the live `tournament.aspx?id=N` URL |
| **TCK website** (tennisclubkordin.com) | `python scripts/scraper/tck.py all` | `Source: Club website` + the archive URL |
| **Local file upload** (legacy `_DATA_/VLTC/*.xlsx`) | `python scripts/scraper/organize.py` (one-shot reorg) | `Source: Local file upload` + file mtime |

## Re-extracting

All scrapers are **idempotent**: re-running won't duplicate data, only re-write
files whose Google Sheet content has changed. To refresh everything:

```bash
python scripts/scraper/vltc.py all       # discover + download VLTC
python scripts/scraper/tck.py all        # download TCK
```

## Legal status

VLTC and TCK tournament Excels are publicly accessible from the respective
club websites. Fair-use processing for ranking analysis. See project memory:
`data_sources.md`.

## Adding a new club

1. Write `scripts/scraper/<club>.py` (use `tck.py` as a template — much simpler
   than VLTC's ASP.NET one).
2. Output to `_DATA_/<year>/<CLUB>/<tournament-slug>/` with the same per-file
   README pattern.
3. If the club hosts tournaments whose names overlap with VLTC/TCK (San Michel,
   Tennis Trade, etc.), keep the club prefix in mind for the parser dispatcher.
