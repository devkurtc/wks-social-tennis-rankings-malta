# RallyRank

Open-source multi-club tennis doubles ranking system + agentic spreadsheet ingestion. Built for community clubs that already track tournament results in Excel and want a public, data-driven leaderboard without re-entering anything.

**Live demo:** https://devkurtc.github.io/wks-social-tennis-rankings-malta/
**Status:** Phase 0 — proof of concept on real Vittoriosa Lawn Tennis Club (VLTC, Malta) data, with one additional club (TCK) onboarded. Phase 1+ ports to Postgres and adds the multi-club platform; see [`PLAN.md`](PLAN.md) for the full roadmap.

## What it does today

- **Reads tournament Excels** from `_DATA_/<year>/<club>/<slug>/*.xlsx` via per-template parsers (round-robin divisions, team tournaments, mixed doubles, knockout brackets).
- **Resolves player identities** across files (typo merger, case-only collisions, captain-class confidence dampener, manual review CLI + web UI). 700-ish active players, ~600 audit-logged merges.
- **Computes doubles ratings** with OpenSkill Plackett-Luce ([PLAN.md §5.2](PLAN.md)) — schema-level multi-model support so champion/challenger algorithms can run side-by-side ([§5.7](PLAN.md)).
- **Generates a static leaderboard site** with per-player pages, match feeds, model-disagreement views, and a "How it works" explainer.
- **Audits every mutation** to `audit_log` in the same transaction.

## Architecture

| Layer | Stack |
|---|---|
| Site (today) | Static HTML generated from SQLite, served via GitHub Pages |
| Database (today) | SQLite (`phase0.sqlite`) — Phase 1 ports to Postgres |
| Rating engine | Python + OpenSkill |
| Ingestion | Python parsers per template; Phase 1+ adds an LLM-driven agent for unknown templates |
| Web + API (Phase 1+) | Next.js + TypeScript |
| Worker, queue, storage (Phase 1+) | Python, Redis, MinIO |

The decisions and the *why* behind each choice live in [`PLAN.md`](PLAN.md). Don't propose stack changes without reading it first.

## Quickstart

```bash
git clone https://github.com/devkurtc/wks-social-tennis-rankings-malta.git
cd wks-social-tennis-rankings-malta

# Python 3.11+ recommended
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-phase0.txt

# Build the leaderboard locally from the committed sample data
python3 -m scripts.phase0.cli ingest        # parse _DATA_/ → phase0.sqlite
python3 -m scripts.phase0.cli rate          # recompute OpenSkill ratings
python3 scripts/phase0/generate_site.py     # write site/

# Serve and open
python3 -m http.server -d site 8000
# → http://localhost:8000/
```

`phase0.sqlite` is gitignored; the ingest step rebuilds it from the source Excels in `_DATA_/`.

## Repo layout

```
PLAN.md                       canonical decisions + rationale
TASKS.md                      live work tracker (multi-agent friendly)
CLAUDE.md                     orientation for Claude Code agents
CONTRIBUTING.md               how to set up + open a PR
LICENSE                       AGPL-3.0
_DATA_/                       source tournament Excels (read-only)
_RESEARCH_/                   rating-model literature + design docs
scripts/phase0/               parsers, rating engine, CLI, site generator
scripts/deploy-site.sh        regenerate site/ + force-push to gh-pages
.claude/skills/, .claude/agents/   Claude Code helpers (see CLAUDE.md)
prompt-for-df-agent.md        sample brief: how to add a new rating model
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Highlights:

- Don't modify anything inside `_DATA_/` — it's authoritative source. Cleanup belongs in the parser.
- Don't widen the schema or rename tables without proposing it in `PLAN.md` first.
- Don't deploy to `gh-pages`. Open a PR to `main`; the maintainer ships.
- All work is tracked in `TASKS.md`. Pick a task whose `Depends on` are all `done`.

## License

[AGPL-3.0](LICENSE). Free for community use, modification, and self-hosting. If you run a modified version as a network service, you must publish your source. This is intentional — it keeps the project open and prevents proprietary forks.

## Acknowledgements

- VLTC and TCK for making tournament results publicly available.
- The OpenSkill maintainers for a clean, well-documented Plackett-Luce implementation.
- Everyone whose name appears in the `_RESEARCH_/` folder — domain references this project leans on.
