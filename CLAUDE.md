# CLAUDE.md

Orientation file for Claude Code sessions on this repo. Skim on every session start; defer to `PLAN.md` for anything substantive.

## Project

**RallyRank** — multi-club tennis doubles ranking system + partner-recommendation engine + agentic spreadsheet ingestion. Self-hosted on Proxmox. VLTC (Vittoriosa Lawn Tennis Club, Malta) is the bootstrap data source; more clubs will follow.

**Repo:** https://github.com/devkurtc/wks-social-tennis-rankings-malta (descriptive name, kept separate from brand)
**Code identifiers:** use `rallyrank` prefix (e.g., `rallyrank-web`, `rallyrank-worker`)

## Source of truth

- `PLAN.md` (repo root) — canonical for **decisions and rationale**: scope, architecture, rating-engine choice, phasing, risks, pros/cons. Read first when in doubt about *why* something is the way it is.
- `TASKS.md` (repo root) — operational **task tracker**. Multi-agent friendly: every task is self-contained with goal, dependencies, references, acceptance criteria, and an append-only progress log. Read first when picking up work.

This file (CLAUDE.md) is just orientation. It never overrides `PLAN.md` or `TASKS.md`. If they disagree, fix CLAUDE.md.

**Workflow when picking up work:**
1. Read `TASKS.md` "Current focus" section to find what's next.
2. Pick a task whose `Depends on` are all `done`.
3. Set status to `in-progress`, add a progress-log line, follow the task's "Picking up a task" protocol in `TASKS.md`.
4. Read the task's referenced `PLAN.md` sections for context.
5. Work the task; commit in small chunks; append progress notes.
6. On completion: verify all acceptance criteria; mark `done`; final progress note.

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

| Skill | Purpose |
|---|---|
| `/pickup-task [task-id]` | Start work on a TASKS.md task — sets status `in-progress`, appends "picked up" progress note, prints task body. With no arg, picks the next ready task. |
| `/log-progress <task-id> <note>` | Append a timestamped progress note. Use after every commit, snag, direction change, or hand-off. |
| `/complete-task <task-id> [<sha>]` | Verify every acceptance criterion against actual repo state; mark `done` only if all pass. Refuses on unmet criteria. |
| `/inspect-xlsx <file>` | Quick structural dump of a tournament Excel file — sheets, dimensions, first ~25 rows. Use before writing or debugging a parser. |

## Project-local agents

Spawned via the `Agent` tool with `subagent_type=<name>`:

| Agent | Purpose |
|---|---|
| `tennis-data-explorer` | Produces a parser-ready specification for a tournament file or template family. Use before writing/debugging a parser when you need deep structural understanding. |
| `parser-implementer` | Implements a parser from a spec, writes tests, iterates until passing. Use after the spec exists. Ideal for T-P0-004 and Phase 1 parser tasks. |
| `rating-engine-expert` | Domain expert on OpenSkill / Glicko / TrueSkill / UTR-Elo. Consult during T-P0-006 design and tuning, T-P1-009 challenger setup, and any time a ranking looks wrong. |

## Memory

Cross-session project context lives at `~/.claude/projects/-Users-kurtcarabott-WKS-SOCIAL-TENNIS/memory/`. Stack decisions, data-source legal status, and project goals are recorded there. The MEMORY.md index in that folder is auto-loaded each session.
