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

**For human contributors** (or when explaining the project to one), point at:

- `README.md` — project pitch, live link, quickstart.
- `CONTRIBUTING.md` — clone → setup → tests → PR; the hard rules restated for non-Claude users.
- `LICENSE` — AGPL-3.0. Free for community use and self-hosting; modified network services must publish source.

**Workflow when picking up work:**
0. **Reconcile `TASKS.md` with reality first.** Run `git log --since=<last-update-of-TASKS.md>` (or scan since the most recent task was marked `done`). If commits exist that aren't reflected in TASKS.md — i.e. real shipped work isn't recorded — reconcile before picking new work. Either mark existing tasks `done` if they describe what shipped, or add a new section recording the work as done tasks. Never start new work on top of a stale tracker.
1. Read `TASKS.md` "Current focus" section to find what's next.
2. Pick a task whose `Depends on` are all `done`.
3. Set status to `in-progress`, add a progress-log line, follow the task's "Picking up a task" protocol in `TASKS.md`.
4. Read the task's referenced `PLAN.md` sections for context.
5. Work the task; commit in small chunks; append progress notes.
6. On completion: verify all acceptance criteria; mark `done`; final progress note.

**Why step 0 exists:** TASKS.md is the multi-agent coordination point. A cold-pickup agent trusts it to be reality. Drift between TASKS.md and `git log` breaks that trust silently — agents pick up "next" tasks that have already shipped, or build on top of work assumed done that isn't. The cost of a 5-minute reconcile is tiny; the cost of a divergent tracker compounds fast.

## Commit + pull cadence (multi-agent, multi-contributor hygiene)

Several agents and humans work on this repo concurrently. The single biggest source of avoidable friction is **stale local checkouts** and **long-lived uncommitted work**. Treat these as defaults, not optional polish:

- **Pull before you start.** First action of every session: `git pull --rebase origin main`. If it fails, stop and resolve before doing anything else. Cost: ~5 seconds. Saves: a 20-minute merge conflict on a file someone else just touched.
- **Commit small, commit often.** Each logical chunk gets its own commit (one task progress note → one commit; a parser fix → a commit; a separate test addition → a commit). Don't accumulate 8 unrelated changes into a "wip" commit. Small commits are easier to review, easier to revert, and dramatically easier to rebase past someone else's work.
- **Push as soon as the commit is mergeable.** Don't sit on local commits while you "finish the next thing". An unpushed commit is invisible to other agents — they can't rebase past it, can't see it in `git log`, and may duplicate the work. Push, then continue.
- **Pull again before pushing if the session has been long.** If more than ~30 min has passed since your last `git pull`, re-pull (rebase) before pushing. Catches concurrent work cheaply.
- **Conflicts: resolve, don't bypass.** If `git pull --rebase` produces a conflict, read both sides and reconcile. Never `git checkout --theirs` / `--ours` blanket-style or `--no-verify` past a hook failure unless you've understood why. The shortcut destroys someone else's work.

**Why this matters here specifically:** TASKS.md, CLAUDE.md, PLAN.md, and the `.claude/skills/` directory are coordination surfaces every agent reads at session start. If two agents both edit TASKS.md without pulling between them, one set of progress-log entries gets lost in the merge. Frequent commit/push/pull collapses that risk to near-zero.

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

## Shipping user-visible changes

Production is **GitHub Pages**, served from the `gh-pages` branch on `origin`. Live URL: `https://devkurtc.github.io/wks-social-tennis-rankings-malta/`.

A change is not "shipped" until **both** of these have happened in the same session:

1. **Source pushed to `main`** — `git push origin main`. Audit trail + history land on GitHub.
2. **Site deployed to `gh-pages`** — run `./scripts/deploy-site.sh` from project root. The script regenerates `site/` from `phase0.sqlite`, creates an orphan commit on a temp worktree, and force-pushes to `refs/heads/gh-pages`. Idempotent and safe to re-run; never touches your working tree.

Treat "the work is done" and "the work is live" as two distinct milestones. Don't claim done until both have happened, or until the user has explicitly opted into review-only. Be transparent in the end-of-turn summary about what shipped where.

**Exceptions** (don't auto-deploy): destructive changes (player merges that delete data, schema migrations), changes still under user review, anything explicitly marked WIP/draft. When in doubt, ask before pushing or deploying.

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
| `/add-rating-model` | Walk a contributor through adding a new rating-engine variant (sibling of `rating.py`) without breaking the OpenSkill PL champion. Schema is already model-agnostic; this skill enforces the additive-only contract. See PLAN.md §5.7. |

## Project-local agents

Spawned via the `Agent` tool with `subagent_type=<name>`:

| Agent | Purpose |
|---|---|
| `tennis-data-explorer` | Produces a parser-ready specification for a tournament file or template family. Use before writing/debugging a parser when you need deep structural understanding. |
| `parser-implementer` | Implements a parser from a spec, writes tests, iterates until passing. Use after the spec exists. Ideal for T-P0-004 and Phase 1 parser tasks. |
| `rating-engine-expert` | Domain expert on OpenSkill / Glicko / TrueSkill / UTR-Elo. Consult during T-P0-006 design and tuning, T-P1-009 challenger setup, and any time a ranking looks wrong. |

## Memory

Cross-session project context lives at `~/.claude/projects/-Users-kurtcarabott-WKS-SOCIAL-TENNIS/memory/`. Stack decisions, data-source legal status, and project goals are recorded there. The MEMORY.md index in that folder is auto-loaded each session.
