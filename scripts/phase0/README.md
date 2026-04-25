# RallyRank — Phase 0 (local proof of concept)

Local SQLite-based proof of the doubles rating model on real VLTC data. Validates the rating + pair-recommender approach before any infrastructure investment (Postgres, web app, agentic ingestion).

See [PLAN.md §7](../../PLAN.md) for phase scope. See [TASKS.md](../../TASKS.md) Phase 0 section for individual tasks (T-P0-001..010).

## Setup

```bash
python3 -m venv scripts/phase0/.venv
source scripts/phase0/.venv/bin/activate
pip install -r requirements-phase0.txt
```

The venv lives at `scripts/phase0/.venv` and is gitignored.

## Usage

All commands run via `python scripts/phase0/cli.py <subcommand>`. Run `--help` on any of them to see flags.

```bash
# Initialize a fresh SQLite DB (T-P0-002)
python scripts/phase0/cli.py load --init-only

# Load a tournament file (T-P0-004)
python scripts/phase0/cli.py load --file "_DATA_/VLTC/Sports Experience Chosen Doubles 2025 result sheet.xlsx"

# Recompute OpenSkill ratings for all loaded matches (T-P0-006)
python scripts/phase0/cli.py rate

# Top 20 doubles players, active in last 12 months (T-P0-007)
python scripts/phase0/cli.py rank --top 20 --active-months 12

# Recommend optimal pairings for a 6-12 player roster (T-P0-008)
python scripts/phase0/cli.py recommend-pairs --players "Player A,Player B,Player C,Player D"
```

## Status

Phase 0 deliverables are tracked task-by-task in [TASKS.md](../../TASKS.md) (T-P0-001 through T-P0-010). Subcommands print "not implemented" until the corresponding task lands and is wired into `cli.py`.

## Files (planned shape)

| File | Purpose | Task |
|---|---|---|
| `cli.py` | argparse entry point, subcommand dispatch | T-P0-001 ✓ |
| `schema.sql` | SQLite schema (model-agnostic — matches PLAN.md §6 shape) | T-P0-002 |
| `db.py` | DB init + connection helper | T-P0-002 |
| `players.py` | Player name normalization + alias storage | T-P0-005 |
| `parsers/` | Per-tournament parsers (one file per template) | T-P0-004 |
| `parser_spec_*.md` | Parser specifications produced by `tennis-data-explorer` agent | T-P0-003 |
| `rating.py` | OpenSkill rating engine + score margin + sigma drift | T-P0-006 |
