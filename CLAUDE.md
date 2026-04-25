# CLAUDE.md

Orientation file for Claude Code sessions on this repo. Skim on every session start; defer to `PLAN.md` for anything substantive.

## Project

Multi-club tennis doubles ranking system + partner-recommendation engine + agentic spreadsheet ingestion. Self-hosted on Proxmox. VLTC (Vittoriosa Lawn Tennis Club, Malta) is the bootstrap data source; more clubs will follow.

**Repo:** https://github.com/devkurtc/wks-social-tennis-rankings-malta

## Source of truth

`PLAN.md` (repo root) is canonical for: scope, architecture, rating-engine choice, phasing, risks, open questions, and pros/cons of every major decision. Read it first when in doubt.

This file (CLAUDE.md) is just orientation. It never overrides `PLAN.md`. If they disagree, fix CLAUDE.md.

## Tech stack (locked — see PLAN.md §5 for rationale)

| Layer | Choice |
|---|---|
| Web + API | Next.js + TypeScript |
| Database | Postgres |
| Worker | Python (rating engine + ingestion agent) |
| Queue | Redis |
| Object storage | MinIO |
| LLM | Claude API (ingestion only) |
| Deploy | docker-compose on a Proxmox LXC, behind Caddy |

## Current phase

**Phase 0 — Local proof of concept.** Goal: validate the rating model on real VLTC data using SQLite + a hand-written parser for one file + OpenSkill (pending confirmation in PLAN.md §11) + a CLI for rankings and pair recommendation. Nothing else built yet. Phases 1–5 are described in PLAN.md §7.

## Repo structure

```
PLAN.md                  ← canonical project plan
CLAUDE.md                ← this file
.gitignore
.claude/
  skills/
    inspect-xlsx/        ← quick xlsx structural dump (Phase 0 helper)
  agents/
    tennis-data-explorer.md  ← deeper template analysis (Phase 1 helper)
_DATA_/
  VLTC/                  ← source tournament Excel files (read-only)
```

Code (parsers, rating engine, web app) will land in `scripts/`, `apps/web/`, `apps/worker/` etc. as phases proceed.

## Conventions for code (when it arrives)

- **Python:** black + ruff; type hints on public functions; pytest. Pure stdlib + a small set of pinned deps (openpyxl, openskill, psycopg, etc.).
- **TypeScript:** strict mode; biome (or prettier+eslint); vitest. No `any` without a comment explaining why.
- **SQL migrations:** plain SQL files with a versioning scheme (TBD in Phase 1).
- **Player names:** always normalized on insert (NFKC, straight quotes, collapsed whitespace). Original names retained in `player_aliases`. Rationale in PLAN.md §5.4.
- **Audit:** every mutation goes through a helper that writes to `audit_log` in the same transaction (PLAN.md §5.5).

## Things NOT to do

- **Don't modify files in `_DATA_/`.** They're authoritative source data; treat as read-only. Any cleanup belongs in the parser, not in the source files.
- **Don't propose Vercel, SQLite-in-prod, skipping the audit log, or all-Python (Django).** These are settled in PLAN.md.
- **Don't commit** secrets, `.env*` files, generated DB dumps, or `~$*.xlsx` Excel lock files. The `.gitignore` covers known cases — extend it before committing anything new and unfamiliar.
- **Don't rename `PLAN.md`** or restructure its sections without checking. The pros/cons-table format is intentional.
- **Don't expand schema or rename tables.** PLAN.md §6 is the schema source. Propose changes there first, then implement.

## Project-local skills

Invoked with `/<name>` from the slash-command menu:

- `/inspect-xlsx <file>` — dump sheets and first rows of a tournament file. Quick structural read.

## Project-local agents

Spawned via the `Agent` tool with `subagent_type="tennis-data-explorer"`:

- `tennis-data-explorer` — produces a parser-ready specification for a tournament file or a family of similar files. Use when you need deep structural understanding before writing a parser, not just a quick dump.

## Memory

Cross-session project context lives at `~/.claude/projects/-Users-kurtcarabott-WKS-SOCIAL-TENNIS/memory/`. Stack decisions, data-source legal status, and project goals are recorded there. The MEMORY.md index in that folder is auto-loaded each session.
