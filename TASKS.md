# RallyRank — Tasks

Living, append-only task tracker for **RallyRank** (multi-club tennis doubles ranking system). Companion to `PLAN.md` (the "why"); this file is the "what's happening now and next."

**Multiple agents can pick up work from this file.** Each task is self-contained with goal, dependencies, references, acceptance criteria, and an append-only progress log — agents joining cold should not need conversation history.

---

## How this file works

### Status values

| Status | Meaning |
|---|---|
| `todo` | Ready to pick up if dependencies are satisfied. |
| `in-progress` | Someone is actively working on it. Look at the progress log for state. |
| `blocked` | Waiting on something external (decision, dependency, info). The blocker is named in the progress log. |
| `done` | Acceptance criteria met; left in place for traceability. Don't delete. |
| `deferred` | Was planned, no longer prioritized for current phase. Reason in progress log. |

### Picking up a task

1. **Verify all dependencies are `done`.** If not, pick a different task or work on a dependency.
2. **Set status to `in-progress`** and add a progress-log line: `YYYY-MM-DD HH:MM — <actor> — picked up; plan: <one-line approach>`.
3. **Read the linked PLAN.md sections** for context — the task body assumes you've read them.
4. **Work the task.** Append progress notes whenever you commit, hit a snag, or change direction.
5. **On completion:** verify every acceptance-criterion checkbox is genuinely met; set status to `done`; add a final progress-log line summarizing what was delivered + any links to commits.
6. **If blocked:** set status to `blocked`, name the blocker explicitly. Don't leave a task `in-progress` while waiting.

### Editing rules

- **Progress log is append-only.** Never edit or delete past entries. If a previous note was wrong, write a new note correcting it.
- **Acceptance criteria are mutable** *only if the goal genuinely changed*. If you change one, log why in the progress log. Sneaky goalpost-moving is the #1 way handoff trust dies.
- **New tasks** go into the appropriate phase section with the next available ID for that phase (e.g., next free `T-P0-NNN`).
- **Don't promote a Phase N+1 stub to a real task before Phase N is done.** Premature elaboration goes stale.

### Actor convention in progress logs

Use one of:
- `Kurt` — for human entries by the project owner
- `Claude (Opus 4.7)` or `Claude (Sonnet 4.6)` etc. — for Claude sessions; include model
- `agent:tennis-data-explorer` — for spawned subagents (use the agent name)

### Multi-agent execution

Tasks are designed to run concurrently when their dependencies allow. The `Depends on` / `Blocks` fields define the DAG; tasks at the same depth are parallel-safe.

**Phase 0 dependency map:**

```
T-P0-001 (scaffold)               ← gate, blocks everything
   │
   ├─► T-P0-002 (schema)          ┐
   ├─► T-P0-003 (parser spec)     ├─ all 3 parallel after T-P0-001
   └─► T-P0-005 (player names)    ┘
            │
            ▼
       T-P0-004 (parser)           ← needs schema (002) AND spec (003)
            │
            ▼
       T-P0-006 (rating)
            │
            ├─► T-P0-007 (rank CLI)         ┐ both parallel after 006
            └─► T-P0-008 (pair recommender) ┘
                          │
                          ▼
                     T-P0-009 (validation, gated by Kurt review)
                          │
                          ▼
                     T-P0-010 (retrospective)
```

**Recommended execution rounds:**

| Round | Parallel work | Drivers |
|---|---|---|
| 1 | T-P0-001 | main session (sequential, blocks all others) |
| 2 | T-P0-002 + T-P0-003 + T-P0-005 | main session + `tennis-data-explorer` subagent (background) + main session |
| 3 | T-P0-004 | `parser-implementer` subagent |
| 4 | T-P0-006 | main session + `rating-engine-expert` for code review |
| 5 | T-P0-007 + T-P0-008 | main session (single-process internal parallelism) |
| 6 | T-P0-009 → T-P0-010 | main + Kurt validation |

**Multi-agent safety rules:**

- **Mutual exclusion on pickup.** Two agents NEVER `in-progress` on the same task. If you see one in-progress, pick something else from the parallel-safe set.
- **Pickup is a commit + push.** Marking `in-progress` only locally is invisible to other agents on other machines. Always commit and push the TASKS.md edit before starting actual work.
- **Cross-task discoveries:** if you spot a problem in a sibling task, log it via `/log-progress` on the sibling and on yours — don't silently fix it.
- **Small, frequent commits** from parallel agents minimize merge conflicts on TASKS.md.
- **Subagents don't need to follow the protocol if their work doesn't change TASKS.md state.** A spawned `tennis-data-explorer` producing a spec file is data-only — the parent task records the work in its own progress log.

### Project skills and agents

Use these to follow protocol consistently — mostly to avoid drift between TASKS.md and reality.

**Skills (slash commands, defined in `.claude/skills/`):**
- `/pickup-task [task-id]` — pick up a task; sets status `in-progress`, appends "picked up" progress note, prints task body. With no arg, picks the next ready task automatically.
- `/log-progress <task-id> <note>` — append a timestamped progress note. Use after every commit, snag, direction change, or hand-off.
- `/complete-task <task-id> [<commit-sha>]` — verify every acceptance criterion against actual repo state, then mark `done` only if all pass. Refuses to mark done on unmet criteria — no goalpost-moving.
- `/inspect-xlsx <file>` — quick structural dump of a tournament Excel file. Use before writing or debugging a parser.

**Subagents (spawned via Agent tool, defined in `.claude/agents/`):**
- `tennis-data-explorer` — produces a parser-ready specification for a tournament file or template family. Use before T-P0-004 / T-P1-003..006 / Phase 3 ingestion design.
- `parser-implementer` — implements a parser from a spec, writes tests, iterates until passing. Use after spec exists. Ideal for T-P0-004 and Phase 1 parser tasks.
- `rating-engine-expert` — domain expert on OpenSkill / Glicko / TrueSkill / UTR-Elo. Consult during T-P0-006 design and tuning, T-P1-009 challenger setup, and any time a ranking looks wrong.

---

## Current focus

**Phase 0.5 — Public-site push (interim, in flight).** Phase 0 closed 2026-04-26; instead of jumping straight to Phase 1 (Postgres port + Modified Glicko-2 challenger), the next session pivoted to building a static public site so non-technical stakeholders can interact with the rankings. See "Phase 0.5" section below for the detail. Phase 1 stubs remain queued.

| State | Tasks |
|---|---|
| `in-progress` | T-P0.5-018 (4-verdict identity triage UI + de-merge + manual reprocess button) |
| `decision pending` | T-P0.5-011 (promote `openskill_pl_decay365` to `CHAMPION_MODEL` or keep vanilla — backtest data already in hand) |
| `up next — site / data hygiene` | T-P0.5-012 (μ-Nσ display-metric tuning); T-P0.5-013 (gh-pages orphan-player-file cleanup); T-P0.5-019 (auto-reprocess daemon, deferred until pair volume justifies it); T-P1-016 (`team_tournament` Final-sheet parser bug); T-P1-018 (v2 rating model: resolve captain-bias + no-team-assignment doubts); T-P1-022 (multi-club separation in site nav) |
| `up next — pre-launch gates` | T-P1-019 (draft trust + legality ADRs 002-006); T-P1-020 (public-launch checklist — privacy notice, takedown channel, robots.txt) |
| `up next — Phase 1 platform` | T-P1-001 (Postgres port); T-P1-008 (fuzzy-match merge CLI); T-P1-009 (Modified Glicko-2 challenger — **harness now ready**, see T-P0.5-010); T-P1-002 (migration tooling) |
| `blocked` | T-P1-020 (public-launch checklist) — depends on T-P1-019 ADR decisions |
| `recently done` | **T-P0.5-017 identity-eval harness** (2026-04-27) — `eval_identity.py` scores the fuzzy `_confidence` function against `manual_aliases.json` (positives) + `known_distinct.json` (negatives) with per-threshold recall/FP-rate/precision; `cli.py eval-identity` exposes it; 15 tests; reveals 91% recall at production T=0.78 with 5 misses (all surname-change cases the algorithm legitimately can't catch from name similarity alone). **T-P0.5-016 site test harness** (2026-04-27) — 222 tests, 80% line coverage across `generate_site.py`/`players.py`/`cli.py`/`eval_identity.py`/`db.py` (was 37% before); end-to-end `gs.main()` test against the real DB exercises ~700 lines in one shot. **T-P0.5-015 per-match impact UI** (2026-04-26 deploy 2026-04-27 record) — `compute_match_impacts(conn)` replays rating_history chronologically to produce per-(match, player) rank/score deltas + bypassed/passed-by lists; All Matches page + per-player match log gain a 2-vs-2 expansion (Side A pair / VS / Side B pair) with proper set scores and rank-at-the-time tags next to every name. **T-P0.5-014 identity-resolution overhaul** (2026-04-26) — typo auto-merger, captain-class confidence dampener, auto-merge on load, mapping-transparency UI at `/aliases.html` with per-merge deeplinks, `cli.py review` (terminal) + `cli.py review-server` (local web UI) + `known_distinct.json` filter; closes T-P1-015 + T-P1-017, substantially advances T-P1-008. Net: 200 → 56 pending fuzzy candidates, 12 → 585 audit-log merges, 837 → 732 active players. **Phase 0.5 prior:** multi-club (TCK), v2 rating (caps removed + captain-class sort + partner weighting), team-selection ingestion, static site generator, Cloudflare-tunnel deployment, design dossier + 5 ADRs proposed, **model-evaluation suite (T-P0.5-010): backtest harness + time-decay challenger + per-player calibration + Model gaps page**. See Phase 0.5 section. **✅ Phase 0** closed 2026-04-26 — see PLAN.md §10.1 |

## ✅ Phase 0 — COMPLETE (2026-04-26)

All 14 Phase 0 tasks done. 32/32 doubles tournaments parsed (3,651 matches, 998 canonical players, 138 tests passing). Champion rating model (OpenSkill PL) tuned and validated with cross-tournament data. Per-tier weighting + ceilings/floors + game-volume K + upset amplification all in place. CLI commands: `load`, `rate`, `rank` (incl. `--by-category`), `recommend-pairs`, `history`, `merge-case-duplicates`. Phase 0 retrospective lives in PLAN.md §10.1.

Tasks closed: T-P0-001 ✓ T-P0-002 ✓ T-P0-003 ✓ T-P0-004 ✓ T-P0-005 ✓ T-P0-006 ✓ T-P0-007 ✓ T-P0-008 ✓ T-P0-009 ✓ T-P0-010 ✓ T-P0-011 ✓ T-P0-012 ✓ T-P0-014 ✓.

(T-P0-013 was reserved as a placeholder for "additional rating issues if any" and never used.)

---

## Phase 0 — Local proof of concept

**Goal of this phase:** validate that the rating model produces sensible doubles rankings on real VLTC data, before investing in any infrastructure. Exit criterion (per `PLAN.md` §7): top-20 list of doubles players from a single tournament looks intuitively correct to a knowledgeable observer.

**Stack for Phase 0:** Python 3 + openpyxl + openskill + SQLite + scipy (for the Hungarian algorithm). No web app, no Postgres, no Docker — just `python scripts/phase0/cli.py <command>`.

---

### T-P0-001 — Phase 0 scaffolding

- **Status:** `done`
- **Phase:** 0
- **Depends on:** none
- **Blocks:** T-P0-002, T-P0-003, T-P0-006
- **Estimated effort:** 30–45 min
- **References:** `PLAN.md` §7 (Phase 0 row); `CLAUDE.md` (conventions section)

**Goal:** Set up the directory structure, dependencies pin file, and a stub CLI entry point so subsequent tasks can hang code off a real skeleton.

**Acceptance criteria:**
- [x] `scripts/phase0/` directory exists with `__init__.py`
- [x] `scripts/phase0/cli.py` exists with subcommand stubs (`load`, `rate`, `rank`, `recommend-pairs`) that print "not implemented" — no logic yet
- [x] `scripts/phase0/README.md` exists with how to install deps, how to run each subcommand, and a pointer to `PLAN.md`
- [x] `requirements-phase0.txt` exists pinning at minimum: `openpyxl`, `openskill`, `scipy`, `python-dateutil`
- [x] `.gitignore` updated to ignore `phase0.sqlite`, `*.sqlite-wal`, `*.sqlite-shm`, `scripts/phase0/.venv/` (sqlite + .venv already covered; WAL/SHM added)
- [x] `python scripts/phase0/cli.py --help` runs without error and shows the four subcommands

**Implementation notes:**
- Use `argparse` (stdlib) — don't pull in click or typer for Phase 0.
- Don't use a `pyproject.toml` for Phase 0; a flat `requirements-phase0.txt` is enough. `pyproject.toml` lands in Phase 1 when we have a real package.
- The `__init__.py` is empty — the module is meant to be run via `python -m` or `python scripts/phase0/cli.py`.

**Progress log:**
- 2026-04-26 00:22 — Claude (Opus 4.7) — picked up; plan: scaffold scripts/phase0/ with empty __init__.py, argparse-based cli.py with four no-op subcommands (`load --init-only --file`, `rate`, `rank --top --active-months --gender`, `recommend-pairs --players`), README with usage + status, requirements-phase0.txt with openpyxl + openskill + scipy + python-dateutil, .gitignore additions for sqlite WAL/SHM. Verify `--help` runs cleanly.
- 2026-04-26 00:30 — Claude (Opus 4.7) — completed; scaffold built, all 6 acceptance criteria verified (`--help` exits 0 and lists 4 subcommands; subcommand `--help` works too). All deps loose-pinned (>=). Committed in this push.

---

### T-P0-002 — SQLite schema (model-agnostic, Phase 0 subset)

- **Status:** `done`
- **Phase:** 0
- **Depends on:** T-P0-001
- **Blocks:** T-P0-004, T-P0-006
- **Estimated effort:** 1–2 hours
- **References:** `PLAN.md` §6 (data model); `PLAN.md` §5.7 (model-agnostic schema rationale)

**Goal:** Create the initial SQLite schema matching `PLAN.md` §6, scaled down to the tables Phase 0 actually needs. **Crucially: the `model_name` discriminator column is included from day one** even though Phase 0 only runs one model — this is settled per §5.7.

**Acceptance criteria:**
- [x] `scripts/phase0/schema.sql` exists with `CREATE TABLE` statements for these tables only: `clubs`, `players`, `player_aliases`, `tournaments`, `source_files`, `ingestion_runs`, `matches`, `match_sides`, `match_set_scores`, `ratings` (with `model_name`), `rating_history` (with `model_name`), `audit_log` — 12 tables total.
- [x] **Skipped** for Phase 0 documented in a section at the bottom of `schema.sql` with reason per table: `model_predictions`, `model_scoreboard`, `champion_history`, `pair_chemistry`, `model_feedback`, `player_club_memberships`, `users`, `user_club_roles`.
- [x] Primary keys correct: composite `(player_id, model_name)` on `ratings`; composite `(match_id, side)` on `match_sides`; composite `(match_id, set_number)` on `match_set_scores`. (Composite on `pair_chemistry` reserved for Phase 4.)
- [x] Active-match index on `matches (tournament_id, played_on) WHERE superseded_by_run_id IS NULL` per §5.3.1.
- [x] `scripts/phase0/db.py` exposes `init_db(path) -> sqlite3.Connection` that creates the file if missing, sets `PRAGMA foreign_keys = ON`, applies `schema.sql`, and is idempotent.
- [x] `python scripts/phase0/cli.py load --init-only` creates a fresh `phase0.sqlite` with all 12 tables; second invocation re-runs cleanly with no error (idempotent).

**Implementation notes:**
- Use `sqlite3` from stdlib.
- Foreign keys: enable with `PRAGMA foreign_keys = ON;` on every connection — SQLite has them off by default.
- Use `INTEGER PRIMARY KEY` for `id` columns (this gets you autoincrement-ish via ROWID).
- For dates: use `TEXT` storing ISO 8601 (`YYYY-MM-DD`). SQLite has no real date type and ISO sorts lexically.
- For `*_jsonb` columns from §6 (e.g., `ingestion_runs.quality_report_jsonb`): use `TEXT` and store JSON; column name keeps the `_jsonb` suffix for clarity even though SQLite has no JSONB type.

**Progress log:**
- 2026-04-26 00:31 — Claude (Opus 4.7) — picked up; plan: write schema.sql with the Phase 0 subset of tables from PLAN.md §6, including model_name discriminator on ratings/rating_history; write db.py with init_db helper (idempotent, foreign keys ON, applies schema). Wire into cli.py `load --init-only`.
- 2026-04-26 00:42 — Claude (Opus 4.7) — completed; schema.sql with 12 tables; db.py with init_db + table_count helpers; cli.py `load --init-only` wired to call init_db and report table count. Verified: fresh init creates all 12 tables; rerun is idempotent (no errors). Skipped tables documented per-row at end of schema.sql.

---

### T-P0-003 — Pick target file & produce parser specification

- **Status:** `done`
- **Phase:** 0
- **Depends on:** T-P0-001
- **Blocks:** T-P0-004
- **Estimated effort:** 30–60 min
- **References:** `_DATA_/VLTC/Sports Experience Chosen Doubles 2025 result sheet.xlsx`; `.claude/agents/tennis-data-explorer.md`; `PLAN.md` §3, §6

**Goal:** Use the `tennis-data-explorer` agent to produce a parser-ready specification for the chosen Phase 0 file. The output is a markdown spec the parser implementer (T-P0-004) follows.

**Acceptance criteria:**
- [x] `tennis-data-explorer` agent invoked on `_DATA_/VLTC/Sports Experience Chosen Doubles 2025 result sheet.xlsx` (used `general-purpose` agent with the agent definition inlined since project-local agents don't auto-load mid-session)
- [x] Output saved as `scripts/phase0/parser_spec_sports_experience_2025.md` (276 lines)
- [x] Spec contains all sections from the agent's output format: file analyzed, format classification (high confidence), sheet map (9 sheets), extraction recipe, schema mapping, edge cases (5), suggested parser test cases
- [x] 6 specific named test cases listed for the parser

**Implementation notes:**
- This is a pure delegation task — invoke the agent with the file path and persist its output. Don't rewrite or summarize.
- If the agent flags ambiguities the parser implementer needs to resolve, surface them in the progress log here so T-P0-004 doesn't stall.

**Progress log:**
- 2026-04-26 00:31 — Claude (Opus 4.7) — picked up; plan: spawn `tennis-data-explorer` agent in background on `_DATA_/VLTC/Sports Experience Chosen Doubles 2025 result sheet.xlsx`; persist its output as `scripts/phase0/parser_spec_sports_experience_2025.md`. Running in parallel with T-P0-002 (schema).
- 2026-04-26 00:46 — Claude (Opus 4.7) — completed; agent returned in 4m37s with 276-line spec. Format: VLTC division round-robin doubles, 9 sheets, ~133 matches across 7 match sheets + 2 roster sheets. Confidence: high. **5 ambiguities flagged for T-P0-004** (recorded on T-P0-004's progress log too): (1) **no per-match dates in the file** — `matches.played_on` is NOT NULL; T-P0-004 should use tournament-year-Jan-1 placeholder and document the limitation; (2) Final-block layout differs across sheets (Men Div 3 splits names across two rows, others use single-row pair string — detect by `'/' in cell_value`); (3) Lad Div 1 has unplayed-match cells (blank vs literal `0.0` — distinguish); (4) `vs` vs `vs.` divider tolerance needed; (5) `Players Ladies` rows 10/11 both rank 5.0 (data quirk; both valid). Spec file is the deliverable; full text not duplicated here.

---

### T-P0-004 — Manual parser for Sports Experience Chosen Doubles 2025

- **Status:** `done`
- **Phase:** 0
- **Depends on:** T-P0-002, T-P0-003
- **Blocks:** T-P0-006, T-P0-009
- **Estimated effort:** 3–5 hours
- **References:** `parser_spec_sports_experience_2025.md` (created in T-P0-003); `PLAN.md` §6 (schema), §3 (data sources), §5.3.1 (`ingestion_run_id`)
- **Recommended agents:** `parser-implementer` (spawn after spec exists; it follows the spec and writes the tests)

**Goal:** Implement a Python parser that reads the chosen file and inserts normalized rows into SQLite using the schema from T-P0-002.

**Acceptance criteria:**
- [x] `scripts/phase0/parsers/sports_experience_2025.py` exposes `parse(xlsx_path, db_conn) -> int (ingestion_run_id)`
- [x] CLI `python scripts/phase0/cli.py load --file <path>` invokes the parser via filename dispatch and reports the run_id
- [x] One `source_files` row + one `ingestion_runs` row created per invocation (verified: re-load → 2 ingestion_runs, 1 source_files)
- [x] One `tournaments` row created with `format = 'doubles_division'` (NOTE: re-load creates a *second* tournament row — flagged for T-P0-010 retrospective; not blocking since rating engine filters by active matches via `superseded_by_run_id IS NULL`)
- [x] `matches`, `match_sides`, `match_set_scores` populated faithfully: 128 matches (= 133 spec estimate − 5 unplayed Lad Div 1), 256 match_sides (= 128×2), 292 match_set_scores
- [x] Each `matches` row has `ingestion_run_id` set
- [x] 110 players inserted via `players.get_or_create_player` (above spec's "~70-80" estimate — expected since each pair has 2 distinct players with little cross-pair sharing across 7 sheets)
- [x] All 6 spec-named test cases pass (parser tests file has 9 total: 6 spec + 3 supporting incl. idempotency)
- [x] Re-running the load creates new run, marks prior matches superseded: verified — after 2nd load, 128 active + 128 superseded

**Implementation notes:**
- Use `openpyxl.load_workbook(path, data_only=True, read_only=True)`.
- Player names recorded as appearing in the file → also captured as `player_aliases` rows pointing at the canonical player record (see T-P0-005).
- Don't try to be clever — match the file's structure 1:1. Cleverness goes into the rating engine, not the parser.
- Wrap the whole load in a single SQLite transaction so a parse failure doesn't leave a half-loaded run.

**Progress log:**
- 2026-04-26 00:46 — Claude (Opus 4.7) — pre-pickup intake of T-P0-003 agent findings. **5 ambiguities the parser implementer must handle** (full detail in `scripts/phase0/parser_spec_sports_experience_2025.md`):
  1. **No per-match dates in the file.** `matches.played_on` is `NOT NULL`. **Decision: use tournament-year-Jan-1 placeholder** (`'2025-01-01'`) for all matches in this file. Phase 0 limitation; revisit when a file with real dates lands. Within-tournament chronological order falls back to `match.id` insertion order (matches the file's row order, which mirrors round order).
  2. Final-block layout differs across sheets: Men Div 3 splits player names across two rows; Men Div 4 / Lad Div 3 use single-row pair strings. Detect by `'/' in cell_value`.
  3. Lad Div 1 has unplayed-match cells: blank vs literal `0.0`. Distinguish — blank = skip + log; `0.0` in both columns = legitimate 6-0 6-0 bagel.
  4. `vs` (Men Div 2) and `vs.` (others) — tolerant divider matcher.
  5. `Players Ladies` rows 10/11 both have rank `5.0`. Both are valid pairs; don't dedupe by rank.
- 2026-04-26 00:55 — Claude (Opus 4.7) — picked up; spawning `parser-implementer` agent in background (general-purpose with agent definition + spec inlined). Main session does pre-T-P0-006 prep concurrently (rating.py skeleton — no data dep so no conflict).
- 2026-04-26 01:04 — Claude (Opus 4.7) — completed; agent returned in 8m56s. Files: `scripts/phase0/parsers/{__init__.py, sports_experience_2025.py, test_sports_experience_2025.py}`; `scripts/phase0/cli.py` modified to dispatch by filename. 9/9 parser tests pass. Real load: 128 active matches, 110 players, 256 match_sides, 292 match_set_scores — counts match spec exactly (133 − 5 unplayed = 128). Idempotent re-load verified: run_id=2, prior 128 matches superseded, source_files row not duplicated. **Findings for T-P0-010 retrospective:** (a) re-load creates a duplicate `tournaments` row — not breaking (matches filter by active) but cleanup candidate; (b) Men Div 3 final block has asymmetric layout (pair A scores on row+1, pair B scores on row+0); agent solved with `_find_score_row` helper that sniffs both rows; (c) Test case 5 spec typo (set 1 = 6-4 vs file's 6-3); parser follows file truth.

---

### T-P0-005 — Player name normalization + alias storage

- **Status:** `done`
- **Phase:** 0
- **Depends on:** T-P0-002
- **Blocks:** T-P0-004
- **Estimated effort:** 1–2 hours
- **References:** `PLAN.md` §5.4 (entity resolution layers)

**Goal:** Implement the Phase 0 minimum-viable player-identity layer: NFKC + apostrophe + whitespace normalization on insert, with a canonical `players` row and one or more `player_aliases` rows tracking each raw form ever seen.

**Acceptance criteria:**
- [x] `scripts/phase0/players.py` exposes `get_or_create_player(db_conn, raw_name: str, source_file_id: int | None = None) -> player_id`
- [x] Normalization rules applied: NFKC, curly apostrophes → straight, whitespace runs collapsed, leading/trailing stripped, casing preserved
- [x] If a player with the same canonical name already exists, returns its ID; new alias added only if raw form is new for that player (UNIQUE(player_id, raw_name) + INSERT OR IGNORE)
- [x] No fuzzy matching in Phase 0 — explicit Phase-1 deferral documented in module docstring
- [x] Unit tests cover all required cases — 13 tests pass: curly/straight collide, whitespace variants collide, casing preserved (and distinguishes), distinct names create distinct players, repeated raw_name doesn't dup alias, source_file_id optional, NFKC composes decomposed chars

**Implementation notes:**
- Use `unicodedata.normalize('NFKC', name)`.
- Apostrophe characters to normalize: `’` (right single quotation mark), `‘` (left single quotation mark) → `'` (apostrophe).
- Don't lowercase. "Duncan D'Alessandro" and "duncan d'alessandro" are technically the same person but Phase 0 will flag them as different — that's a Phase 1 problem.

**Progress log:**
- 2026-04-26 00:42 — Claude (Opus 4.7) — picked up (T-P0-002 just landed, deps satisfied); plan: write players.py with `normalize_name(raw)` (NFKC, curly→straight apostrophes, collapse internal whitespace, strip) and `get_or_create_player(conn, raw, source_file_id) -> player_id` (returns existing or creates new player + alias row); write test_players.py with cases for curly/straight collide, whitespace ignored, casing preserved, distinct names = distinct players.
- 2026-04-26 00:51 — Claude (Opus 4.7) — completed; players.py with `normalize_name` (5 apostrophe variants, regex-based whitespace collapse) and `get_or_create_player` (idempotent via UNIQUE + INSERT OR IGNORE). 13 unit tests pass on in-memory SQLite (run `python -m unittest scripts.phase0.test_players -v`). Phase-0 case-sensitivity trade-off documented in module docstring + test (test_casing_distinguishes_in_phase_0).

---

### T-P0-006 — OpenSkill rating engine integration

- **Status:** `done`
- **Phase:** 0
- **Depends on:** T-P0-001, T-P0-002, T-P0-004
- **Blocks:** T-P0-007, T-P0-008
- **Estimated effort:** 2–4 hours
- **References:** `PLAN.md` §5.2 (algorithm + score margin + time decay); `PLAN.md` §5.7 (model-agnostic — `model_name='openskill_pl'`)
- **Recommended agents:** `rating-engine-expert` (consult for parameter choices — tau, score-margin formula, alpha — and for code review of the rating math before completing the task)

**Goal:** Apply OpenSkill (Plackett-Luce) to all matches in the DB; write per-player `mu`/`sigma` to `ratings` and per-match deltas to `rating_history`.

**Acceptance criteria:**
- [x] `scripts/phase0/rating.py` exposes `recompute_all(db_conn, model_name='openskill_pl', tau=0.0833, rating_period_days=30) -> int`
- [x] CLI `rate` invokes recompute over all matches in `played_on, match.id` chronological order
- [x] Each side modeled as 2-player team via `PlackettLuce.rate([team_a, team_b], scores=[s_a, s_b])`; ratings updated; 4 `rating_history` rows per match appended (verified: 128 matches × 4 = 512 history rows)
- [x] Universal games-won score applied via `universal_score()` helper — used directly as OpenSkill's actual-score input, NOT as a weight multiplier
- [x] Walkover handling via the `matches.walkover` flag → `S=0.90/0.10` (test `test_walkover_uses_dampened_score` verifies the score is dampened vs a real whitewash)
- [x] **Open question answered:** OpenSkill PL apportions updates by each player's *current skill estimate* — stronger players get larger-magnitude updates than weaker partners. Conceptually similar to `_RESEARCH_/...` §7's explicit `Δ × weight × 2` formula (weight = R / (R1+R2)). Definitive comparison deferred to T-P1-009 where Modified Glicko-2 runs alongside OpenSkill PL on the same data; the predictive scoreboard (PLAN.md §5.7) will reveal whether the two diverge meaningfully on this dataset. Empirical observation from SE 2025: with fixed pairs (no roster rotation), partners had identical ratings — expected since identical match histories produce identical OpenSkill updates.
- [x] Sigma drift applied between matches via `_periods_between` + `sigma' = sqrt(σ² + N × τ²)` (Phase 0 with one-tournament data → drift effectively zero, but logic in place for multi-tournament Phase 1+)
- [x] Skips matches where `superseded_by_run_id IS NOT NULL` (test `test_superseded_matches_excluded` verifies)
- [x] After SE 2025: 110 ratings rows, one per player who appeared (= same count as `players` table)

**Implementation notes:**
- `openskill.models.PlackettLuce` is the model class. See https://openskill.me — but pin the version in `requirements-phase0.txt` and document it.
- Don't try to be incremental in Phase 0. `recompute_all` is fine — wipe `ratings` and `rating_history`, replay from earliest match. Incremental updates land in Phase 1.
- For sigma drift: rating period = month (start of). For a player with last match in March 2025 whose new match is in June 2025, N = 3.
- For partner-weighting investigation: spawn `rating-engine-expert` with the question above. Don't add an explicit partner-weight multiplier on top of OpenSkill in Phase 0 — first verify whether it's needed. Either answer is acceptable; the reasoning goes in the progress log so T-P1-009 (Modified Glicko-2 challenger) knows what to do differently.

**Progress log:**
- 2026-04-26 01:15 — Claude (Opus 4.7) — picked up; venv created at `scripts/phase0/.venv`, openskill 6.2.0 + scipy + openpyxl + python-dateutil installed.
- 2026-04-26 01:25 — Claude (Opus 4.7) — completed; rating.py recompute_all + _iter_active_matches + _periods_between filled in. Universal score wired (S directly, not a multiplier). Walkover handled via match.walkover → S=0.90/0.10. Sigma drift: σ' = sqrt(σ² + periods × τ²) with τ=0.0833 default and period=30 days. Real run on SE 2025: 128 matches → 110 ratings, 512 rating_history rows. Top-10 by `mu - 3*sigma` looks coherent (winning fixed pairs at top; identical partner ratings expected since same match history). 19 rating tests pass (incl. integration: 4-player fixture, winner mu↑/loser mu↓, idempotent recompute, superseded skipped, walkover dampens). One self-caught bug: my own `test_three_periods_at_90_days` had wrong arithmetic (asserted 2 instead of 3 for 90-day span); function was right, fixed test. Total Phase 0 tests: 41 passing.

---

### T-P0-007 — CLI: `rank` command

- **Status:** `done`
- **Phase:** 0
- **Depends on:** T-P0-006
- **Blocks:** T-P0-009
- **Estimated effort:** 1–2 hours
- **References:** `PLAN.md` §5.2 (Time decay paragraph — leaderboard active filter); `PLAN.md` §7 (Phase 0 exit criterion)

**Goal:** Implement `python scripts/phase0/cli.py rank` to print the top-N doubles players with their current rating.

**Acceptance criteria:**
- [x] CLI flags: `--top N` (default 20), `--active-months M` (default 12; pass 0 to disable), `--gender {men,ladies,all}` (default `all`)
- [x] Output: tabular text — rank, player name, gender, mu (2dp), sigma (2dp), mu-3σ (2dp), n_matches, last_played
- [x] Players ordered by `mu - 3*sigma` (conservative Bayesian rating)
- [x] Active-months filter applied (Phase 0 SE 2025 uses placeholder dates → use `--active-months 0`; filter logic verified via manual run)
- [x] Gender filter honors `players.gender` (parser populated this; M=64, F=46)
- [x] SE 2025 produces coherent top-10: division-winning fixed pairs at top with identical (paired) ratings — expected for fixed-pair round-robin data

**Implementation notes:**
- The "mu - 3*sigma" ordering matters: a new player with high mu but huge sigma should NOT outrank a proven player. This is the conservative-rating convention.
- Use the stdlib `string.Formatter` or just printf-style padding for the table — no `tabulate` dep for Phase 0.

**Progress log:**
- 2026-04-26 01:30 — Claude (Opus 4.7) — picked up alongside T-P0-008 (parallel, both unblocked by T-P0-006); plan: replace cmd_rank stub with SQL query + filters + tabular print. No new external deps.
- 2026-04-26 01:35 — Claude (Opus 4.7) — completed; manual verification: `rank --top 10 --active-months 0` returns expected top-10 (Maria Angela Gambin & Maria Ellul tied at top, etc.); `rank --top 5 --gender men --active-months 0` filters to men correctly. No unit tests added — CLI integration covered by T-P0-009 end-to-end run.

---

### T-P0-008 — CLI: `recommend-pairs` command

- **Status:** `done`
- **Phase:** 0
- **Depends on:** T-P0-006
- **Blocks:** T-P0-009
- **Estimated effort:** 2–3 hours
- **References:** `PLAN.md` §1 (pair-recommendation goal); `PLAN.md` §5.2 (additive partner model for v1; chemistry residual deferred to Phase 4)

**Goal:** Given a roster of N players (N must be even), output the pairing that maximizes total team strength.

**Acceptance criteria:**
- [x] CLI: `python scripts/phase0/cli.py recommend-pairs --players "Name1,Name2,...,NameN"` (verified for N=6 and N=12)
- [x] N must be even ≥ 4; clear error otherwise
- [x] Did-you-mean fallback on unresolved names via `difflib.get_close_matches` (verified: `"Duncan"` → `"Dunstan Vella"`)
- [x] Pair strength: `mu_a + mu_b - 1.0 × (σ_a + σ_b)` (alpha=1.0 documented in code)
- [x] Brute-force perfect matching enumeration (10395 matchings for N=12 → trivial; networkx fallback documented for larger N but not needed in Phase 0)
- [x] Output: pairs list with per-pair score + total team strength

**Implementation notes:**
- For N ≤ 12, brute-force enumeration is fine: `(2k)! / (2^k * k!)` pairings of 2k players. For 12 players that's 10395 — trivial.
- For larger N, use `networkx.algorithms.matching.max_weight_matching` (it's perfect-matching capable on a complete graph with edge weights = pair strength).
- "Pair strength" in Phase 0 is purely additive — no chemistry residual. Chemistry is Phase 4's `pair_chemistry` table.
- Hungarian algorithm (mentioned in `PLAN.md`) is for assignment problems (m workers to n jobs); for pairing within a single set, the matching approach above is the right one. Don't use `scipy.optimize.linear_sum_assignment` for this — wrong shape.

**Progress log:**
- 2026-04-26 01:30 — Claude (Opus 4.7) — picked up alongside T-P0-007 (parallel, both unblocked by T-P0-006); plan: replace cmd_recommend_pairs stub with brute-force enumeration via `_best_pairing(names, strength_fn)` recursive helper.
- 2026-04-26 01:35 — Claude (Opus 4.7) — completed; manual verification: N=6 (Men Div 1 + Div 2 fixed pairs) returns the natural pairings (Duncan/Clayton, Mark/Manuel, Gabriel/Nikolai); N=12 (broader roster) returns balanced pairings — alpha=1.0 favors balance over max-strength single team. Total time: ~50ms for N=12. Did-you-mean tested via intentionally-wrong "Duncan" → "Dunstan Vella". **Observation for T-P0-010 retro:** alpha=1.0 produced *balanced* (not *strongest single team*) pairings; whether this matches captain intuition is the validation question for T-P0-009.

---

### T-P0-009 — End-to-end validation & user review

- **Status:** `done`
- **Phase:** 0
- **Depends on:** T-P0-004, T-P0-007, T-P0-008
- **Blocks:** T-P0-010
- **Estimated effort:** 30 min run + however long Kurt's review takes
- **References:** `PLAN.md` §7 (Phase 0 exit criterion)

**Goal:** Run the full Phase 0 pipeline end-to-end and capture Kurt's reaction. **This is the gate that unblocks Phase 1.**

**Acceptance criteria:**
- [x] `phase0.sqlite` deleted; pipeline run from scratch (multiple times during the iterations)
- [x] Outputs from `rank` and `recommend-pairs` captured and shared with Kurt
- [x] Kurt confirmed rankings are usable for evaluation after T-P0-014 bulk-load + T-P0-011/012 weighting fixes + tier merge + upset amplification
- [x] Issues flagged were addressed: cross-division ordering (→ T-P0-011), within-division ordering and game weighting (→ T-P0-012), too few tournaments (→ T-P0-014), case duplicates (→ merge-case-duplicates CLI), tier confusion (→ tier merge), Cory Greenland too high (→ team-rubber ceilings), upset amplification

**Implementation notes:**
- The "looks right" judgment is genuinely subjective — Kurt knows these players. We can't automate this gate.
- If a few rankings look obviously wrong but most are right, log specifics and triage in T-P0-010 retrospective rather than blocking.

**Progress log:**
- 2026-04-26 01:38 — Claude (Opus 4.7) — first attempt; ran full pipeline, presented top 20 men + top 15 ladies + 12-player pair-rec to Kurt for review.
- 2026-04-26 01:42 — Kurt — REJECTED: cross-division ordering wrong (Div 2 winners > Div 1 winners); within-division ordering "not very good — model wrong weights"; pair-rec "don't know yet." Direction: "take no of games into consideration" + Q2 option A. File new tasks for the fixes; Phase 0 not done.
- 2026-04-26 01:43 — Claude (Opus 4.7) — filed T-P0-011 (per-division starting μ + K-multipliers per `_RESEARCH_/...` §8) and T-P0-012 (game-volume K-multiplier — option A). Status reverted to in-progress; will re-attempt validation once both fixes land.

---

### T-P0-011 — Per-division starting μ + division K-multipliers

- **Status:** `done`
- **Phase:** 0 (accelerated from Phase 1 after T-P0-009 review)
- **Depends on:** T-P0-006
- **Blocks:** re-attempt of T-P0-009
- **Estimated effort:** 2–3 hours
- **References:** `_RESEARCH_/Doubles_Tennis_Ranking_System.docx` §2.2 (starting ratings) + §8.1, §8.2 (K-multipliers); PLAN.md §5.2.1 (queued enhancements); T-P0-009 review feedback

**Goal:** Encode division strength into the rating math so Div 1 winners outrank Div 2 winners on cross-division comparison, and within-division ordering reflects relative tournament strength.

**Acceptance criteria:**
- [x] `DIVISION_STARTING_MU` dict in `rating.py` — wider 5-unit spacing (M1=35, M2=30, M3=25, M4=20; L1=33, L2=28, L3=23) needed because 3-unit spacing was insufficient: a dominating Div 2 winner's μ growth out-paced the smaller starting gap.
- [x] `DIVISION_K` dict per `_RESEARCH_/...` §8.1, §8.2.
- [x] **Smart `normalize_division`** with regex: handles `"Men Division 1"`, `"Men Div 1"`, `"Men Division 3 - Group A"`, `"Ladies Division 2"`, trailing whitespace. **This was a hidden bug in v1** — my constants used `"Men Div 1"` but parser emits `"Men Division 1"`, so all lookups silently fell back to defaults. Caught only by re-running validation. Added 4 regression tests against actual data strings.
- [x] First-seen division lookup → starting μ (helper `_player_first_division` cached per session in `recompute_all`).
- [x] Per-match K applied as `adjusted_delta = k_combined × openskill_delta` for both μ and σ.
- [x] **Extension beyond original spec:** added `DIVISION_MU_CEILING` + `DIVISION_MU_FLOOR` + `clip_mu_to_division()` per `_RESEARCH_/...` §8.1, §8.2. Strictly enforces "Div 2 player can't exceed Div 1 starting μ" — necessary because pure starting-μ priors get washed out by 5+ matches of dominant within-division play.
- [x] Unit tests: 7 division-helper tests + 2 integration tests (higher-division-larger-Δμ, starting-μ-uses-division). All pass.
- [x] Re-run validation: Div 1 men now ranked #1-6 (Duncan/Clayton at top, Mark/Manuel at #5-6); Fotis/Kristen (Div 2) at #7-8 capped at μ=34.0 (Div 2 ceiling).

**Implementation notes:**
- Division names in the data have inconsistent whitespace (`'Men Div 1 '` with trailing space). Normalize before lookup.
- Apply T-P0-011 and T-P0-012 K-multipliers as a *combined* `K_effective = K_division × K_volume` per the research doc §8.4.
- Don't add a new schema column for `players.starting_division` — derive it on-the-fly from the chronologically-first match. Phase 0 keeps the schema stable.

**Progress log:**
- 2026-04-26 01:43 — Claude (Opus 4.7) — picked up; will implement combined with T-P0-012 (same file, same recompute_all path).
- 2026-04-26 02:05 — Claude (Opus 4.7) — completed (with iteration). First pass with 3-unit μ spacing didn't fix the cross-division ordering. Then I discovered my constants used `"Men Div 1"` while parser emits `"Men Division 1"` — silent fallback bug. Fixed normalize_division with regex; widened spacing to 5 units; added per-division ceilings/floors per friend's research. Re-validation now shows Div 1 men cleanly ranked #1-6 above Div 2 (capped at 34). 60 tests passing.

---

### T-P0-012 — Game-volume K-multiplier

- **Status:** `done`
- **Phase:** 0 (accelerated from Phase 1 after T-P0-009 review)
- **Depends on:** T-P0-006
- **Blocks:** re-attempt of T-P0-009
- **Estimated effort:** 1 hour (combined with T-P0-011)
- **References:** Kurt's T-P0-009 feedback Q2 → option A; `_RESEARCH_/...` §8.4 (combined K-factor)

**Goal:** Match weight scales with total games played so a 12-game blowout (6-0 6-0) carries less weight than a 26-game battle (7-6 7-6) — more rallies = more signal about each player's skill.

**Acceptance criteria:**
- [x] `volume_k_multiplier(total_games, walkover=False) -> float` clamped to `[0.5, 1.5]`.
- [x] `K_combined = K_division × K_volume` applied in `recompute_all`.
- [x] Walkovers use `WALKOVER_VOLUME_K = 0.5` regardless of recorded score.
- [x] Unit tests: 18-game baseline = 1.0; 12-game = 0.667; 26-game = 1.44; clamped at min/max; walkover; zero-game defensive. 7 tests pass.
- [x] Within-division ordering: improved but limited by single-tournament data sparsity (5 matches per pair). Real evaluation needs more tournaments — see T-P0-014.

**Implementation notes:**
- Choice of baseline=18: typical 2-set match length (6-3 6-3 = 18 games is roughly average).
- Clamp [0.5, 1.5] prevents unrealistic short/long matches from dominating.
- Single-application: K_volume goes into K_combined, then scales delta once (don't double-apply).

**Progress log:**
- 2026-04-26 01:43 — Claude (Opus 4.7) — picked up; will implement combined with T-P0-011 (same recompute_all path).
- 2026-04-26 02:05 — Claude (Opus 4.7) — completed alongside T-P0-011. Game-volume helper + walkover handling + 7 unit tests. Combined K landed in `recompute_all` (K_combined = K_division × K_volume scaling the OpenSkill delta).

---

### T-P0-014 — Bulk-load additional VLTC tournaments (accelerated from Phase 1)

- **Status:** `done`
- **Phase:** 0 (accelerated from Phase 1 after Kurt's "1 tournament isn't enough to evaluate" feedback)
- **Depends on:** T-P0-006 (rating engine), T-P0-011 (division weights)
- **Blocks:** re-attempt of T-P0-009
- **Estimated effort:** 4-8 hours (parallel subagents)
- **References:** T-P0-009 review feedback ("we need more data to evaluate if this is working well"); PLAN.md §7 Phase 1 row (T-P1-003..006 originally scoped here)

**Goal:** Load enough additional VLTC tournament data to make the rankings *meaningfully* evaluable. With one tournament, we can validate the rating math but not whether it produces correct rankings — we have no signal on whether a player like Maria Angela Gambin is genuinely top-tier or just dominated one Div 3 event.

**Approach:**
- Identify template families across the 40 files in `_DATA_/VLTC/`
- For each NEW family: spawn `tennis-data-explorer` agent → spec → spawn `parser-implementer` agent → parser
- For SIMILAR-format files: try existing `sports_experience_2025` parser (with light renaming/adaptation)
- Bulk-load everything; re-rate; present to Kurt for re-validation

**Template families identified by filename:**

| Family | Files (approx) | Notes |
|---|---|---|
| Division round-robin doubles (existing parser) | SE 2024, SE 2025 (done), TCK 2024 | Try existing parser first |
| Mixed-doubles division round-robin | ESS 2024/2025, Elektra 2022/2023, Samsung Rennie Tonna 2024/2025 | Likely same shape as SE; adapt parser |
| Team tournament (rotating partners per rubber) | Antes 2024/2025 (3 variants), Tennis Trade 2023/2024/2025, San Michel 2023/2025/2026, PKF 2023/2024 | NEW parser — different schema (Day N sheets) |
| Wilson Autumn/Spring (older format) | Wilson Autumn 2017-2021, Wilson Spring 2018/2019 | NEW parser — possibly very different layout |

**Acceptance criteria:**
- [x] Existing SE 2025 parser tested on SE 2024 — worked as-is (83 matches)
- [x] mixed_doubles parser handles ESS 2024+2025 + Elektra 2023 (306 matches across 3 files); Samsung Rennie Tonna routed to team_tournament parser instead (different format)
- [x] team_tournament parser handles Antes (3) + Tennis Trade post-2024 (4) + San Michel post-2025 (2) + Samsung Rennie Tonna (3)
- [x] team_tournament_legacy parser added for older single-sheet "DAY" format: PKF 2023+2024, Tennis Trade 2023, San Michel 2023+2024+2025 (6 files, 777 matches)
- [x] elektra_2022 parser for cross-tab matrix (1 file, 76 matches)
- [x] tck_chosen_2024 parser for flat-list (1 file, 86 matches)
- [x] Wilson parser handles 2017-2021 series (7 files, 909 matches)
- [x] Filename-based dispatch in cli.py routes all 32 files correctly
- [x] After bulk load: 3,651 active matches across 998 players in 32 tournaments — far exceeds the >1000 / >200 threshold
- [x] Rate recomputed; rankings shared with Kurt; T-P0-009 closed

**Progress log:**
- 2026-04-26 02:08 — Claude (Opus 4.7) — picked up after Kurt confirmed "we need more data to evaluate if this is working well." Plan: commit T-P0-011/T-P0-012 first, then spawn parser-implementer agents for additional template families. Start with the easy ones (test existing parser on SE 2024 + similar-format files) before spawning new-parser work.
- 2026-04-26 02:25 — Claude (Opus 4.7) — first parallel batch landed (Wilson + mixed-doubles + team-tournament). Loaded 24 files, 2712 matches. Skipped 7 files (5 older-team-tournament + Elektra 2022 cross-tab + TCK 2024 flat-list).
- 2026-04-26 02:30 — Claude (Opus 4.7) — Kurt iteration on rating math: T-P0-011/012 with division weights + ceilings/floors + tier merge merged-via-PRIMARY-division.
- 2026-04-26 02:50 — Claude (Opus 4.7) — Kurt asked for case-merge → built `merge-case-duplicates` CLI (96 tests). 102 records collapsed → 711 canonical. Kurt now 41 matches; Duncan D'Alessandro 61.
- 2026-04-26 03:10 — Claude (Opus 4.7) — second parallel batch picked up: 3 new parser-implementer subagents spawned for the remaining 7 files: (a) legacy team-tournament for PKF 2023/24 + Tennis Trade 2023 + San Michel 2023/25 + " Team Tournament 2024" (5+1 files), (b) Elektra Mixed Doubles 2022 cross-tab matrix, (c) TCK Chosen 2024 flat-list.

---

### T-P0-010 — Phase 0 retrospective + plan updates

- **Status:** `done`
- **Phase:** 0
- **Depends on:** T-P0-009
- **Blocks:** Phase 1 kickoff
- **Estimated effort:** 1 hour
- **References:** `PLAN.md` §10 (what we'd change after a week of using it)

**Goal:** Capture what we learned in Phase 0 and update `PLAN.md` so Phase 1 starts from current reality, not the original plan.

**Acceptance criteria:**
- [x] PLAN.md §10.1 retrospective section appended (what worked, what surprised us, tuning landed with all final values, parser quirks for Phase 1)
- [x] Phase 1 follow-ups noted in retrospective (player merge fuzzy-match higher priority than originally scoped; "(pro)/(dem)" name pollution; "Angele Pule" vs "Angele Pule'" fuzzy match)
- [x] All 14 Phase 0 tasks marked `done` in this file
- [x] PLAN.md status header updated to "✅ Phase 0 complete"
- [x] Commit + push

**Progress log:**
- (none yet)

---

## Phase 0.5 — Interim public-site push (post-P0, undocumented work being recorded)

**Why this section exists.** Phase 0 closed 2026-04-26. The retrospective said "next session should do T-P1-001 (Postgres) / T-P1-008 (fuzzy merge) / T-P1-009 (Modified Glicko-2)." In practice the next 15 commits went a different direction — a public-site push so non-technical stakeholders could see and react to rankings. That work is real, shipped, and not previously tracked here. Recording it now so the multi-agent tracker reflects reality.

**The pivot was probably correct** — getting feedback from real users is higher leverage than building Phase 1 platform infra in a vacuum. But it consumed the time budget that PLAN.md §7 allocated to Phase 1, so the queue order in "Current focus" is rebalanced.

### T-P0.5-001 — Multi-club support (TCK)

- **Status:** `done`
- **Phase:** 0.5
- **Commit:** `595dd26`
- **Goal:** Generalize hard-coded `clubs.id = 1 (VLTC)` so a second club (TCK — Tennis Club Kordin) can be loaded.
- **What landed:** Parser dispatch by file path now routes to `(club, tournament)` correctly; `_DATA_/` reorganized by `<year>/<club>/<tournament>/` (commit `c0e9fda`); bulk-load across both clubs hit 4,796 active matches (`bb3cd4d`).
- **Note:** Originally Phase 5 territory — jumped early because TCK data was already available and the abstraction cost was small.

### T-P0.5-002 — Year-organized data layout + bulk re-load

- **Status:** `done`
- **Phase:** 0.5
- **Commit:** `c0e9fda`, `bb3cd4d`
- **Goal:** Reorganize `_DATA_/` from flat per-club to `<year>/<club>/<tournament>/` so cross-club / cross-year navigation is sane.
- **What landed:** 4,796 matches across 2 clubs after re-load.

### T-P0.5-003 — Scrapers for both clubs

- **Status:** `done`
- **Phase:** 0.5
- **Commit:** `c0e9fda`
- **What landed:** `scripts/scraper/{vltc.py, tck.py, organize.py}` so new tournament uploads to the club websites can be auto-fetched.
- **Open:** No CI / scheduled run — scrapers are manual-trigger-only. Promote to Phase 1+ if needed.

### T-P0.5-004 — v2 rating model: caps removed + captain-class display + partner weighting

- **Status:** `done` (with open doubts — see T-P1-018)
- **Phase:** 0.5
- **Commit:** `b1a05ff`
- **References:** `_RESEARCH_/Doubles_Tennis_Ranking_System.docx` §7 (partner weighting); friend's review of v1 leaderboard
- **What landed:**
  - Schema: `player_team_assignments` (tournament_id, player_id, team_letter, captain_name, class_label, tier_letter, slot_number, gender)
  - `team_selection.py` parses Team Selection sheet from team-tournament XLSX (handles both `'A'` and `'TEAM A'` layouts). 9 team tournaments backfilled → 1,134 captain assignments → 259/1006 canonical players have a class.
  - `rank` CLI now sorts by captain-assigned class first (A1, A2, …, ?), μ-3σ secondary. New `--sort raw` flag exposes math-only view.
  - μ ceilings/floors removed (`DIVISION_MU_CEILING={}, DIVISION_MU_FLOOR={}`); tier ordering now preserved by display sort, not math.
  - `DIVISION_K` softened to {1.00, 0.85, 0.70, 0.55} (kept moderate; not aggressive 1/0.75/0.50/0.30).
  - `division_k_multiplier_for_match` looks up gendered-primary tier for mixed-doubles "Division N" matches (per-match K averaged across the 4 players).
  - `apply_partner_weighting(p1_old, p2_old, p1_new, p2_new)` redistributes team's total Δμ by partner-weight ratio per friend's research §7. Net team Δμ preserved.
  - 145 tests passing.
- **Open doubts** (filed as T-P1-018):
  - #1 Captain bias: Karl Debattista (μ=23.67, 15% wins) ranks #13 of A1 because his captain insists; math says way lower.
  - #2 Two scoreboards: class+μ both shown in default; --sort raw exposes math-only. UX may need to make "the official one" clearer.
  - #4 No team assignments: 75% of canonical players have no class → fall back to derived class from primary division (`B?`) or `?` sorts last. Leaderboard for non-team-tournament players is muddled.

### T-P0.5-005 — Static site generator

- **Status:** `done`
- **Phase:** 0.5 (overlaps Phase 2 P2-004 / P2-005)
- **Commit:** `92cdf65`, `ce69fe7`, `53ae2dd`
- **What landed:** `scripts/phase0/generate_site.py` produces:
  - `site/index.html` — sortable leaderboard (men + ladies)
  - `site/players/<id>.html` — per-player page with rating-history chart
  - `site/tournaments/<slug>.html` — pre-tournament roster ranking page (one per `TOURNAMENT_ROSTERS` entry); class assigned by rank (6 captains × 4 slots/tier — see commit `53ae2dd`)
  - `site/matches.html` — chronological filterable match feed (commit `cdeb9e0`)
- **Note:** This was originally Phase 2 territory (`T-P2-004`, `T-P2-005`). Static generator is a cheaper path than Next.js + Postgres for the read-only public view, but it doesn't satisfy Phase 2's auth + admin UI scope. Phase 2 is still required for HITL workflows.

### T-P0.5-006 — Cloudflare-tunnel deployment + content-hash dup detection + manual aliases

- **Status:** `done`
- **Phase:** 0.5
- **Commit:** `d0cbc1f`
- **References:** `DESIGN/adr/014-hosting-cloudflare-tunnel.md`
- **What landed:**
  - `scripts/deploy-site.sh` deploys `site/` behind a Cloudflare Tunnel (no public IP, no inbound port).
  - Token-fingerprint duplicate detection during ingestion (catches re-uploaded files with cosmetic changes).
  - `scripts/phase0/manual_aliases.json` lets humans pin `(raw_name → canonical_player_id)` mappings the parser can't infer.
- **Note:** Hosting is currently runnable but not GDPR-compliant. T-P1-020 lists what's missing before public launch.

### T-P0.5-007 — Design dossier + ADRs

- **Status:** `done` (5 ADRs accepted/proposed; 20 not drafted)
- **Phase:** 0.5
- **Commit:** `c41120c`
- **What landed:** `DESIGN/{repo-layout.md, architecture.md, diagrams.md, README.md}`, `DESIGN/adr/{INDEX, 001 design-first, 007 API as standalone service, 008 FastAPI/Python, 014 Cloudflare Tunnel hosting}` + research dossier.
- **Critical gap:** Trust + legality ADRs 002–006 (consent, visibility, real-name display, takedown, audit/GDPR) are `not drafted`. **These gate any public launch.** Filed as T-P1-019.

### T-P0.5-008 — Captain-Lonia roster ranking analysis

- **Status:** `done`
- **Phase:** 0.5
- **Commit:** `a9092ed`, `5928fe3`
- **What landed:** `_ANALYSIS_/NewTournamentRanking/` with `rank_roster.py`, `Players List.xlsx`, `ranking.html`, `ranking_output.txt`. Plus a fix for indexing captain rankings under name-order rotations (`5928fe3`).
- **Note:** One-off — useful as a template for the per-tournament reports T-P1-021 will systematize.

### T-P0.5-009 — `rank` CLI extras + history command + merge-case-duplicates

- **Status:** `done`
- **Phase:** 0.5
- **Commits:** `b4388a2` (wins/losses/win%), `92b69e8` (n column), `7866f27` (gW-gL + game-win%), `b3a72d8` (`history` CLI), `9daa552` (merge-case-duplicates), `2dab66e` (tier merge), `31f60c8` (team-rubber caps + by-category view), `a219ad4` (team-rubber categories + primary-division column)
- **Note:** These mostly landed before Phase 0 closed but post-T-P0-014; they're fine where they sit on T-P0-007 / T-P0-014's progress logs. Listed here for continuity.

### T-P0.5-010 — Backtest harness + time-decay challenger + per-player calibration + model-gap feed

- **Status:** `done`
- **Phase:** 0.5
- **Commits:** `c685f08` (harness + 4 PL variants), `8a356a5` (production decay model + Lonia validation), `e5fc570` (Decay column on leaderboard), `4c01093` (per-player prediction quality + Pred column on match log), `88b0ea2` (Model gaps page)
- **Goal:** Validate hypotheses raised by Captain Lonia's roster ranking with held-out match data, build a reusable model-evaluation pipeline, and surface the resulting insights in the public site.
- **What landed:**
  - **`scripts/phase0/backtest.py`** — model-agnostic harness (online evaluation, log-loss + Brier + accuracy + 10-decile calibration). Path-anchored via `__file__`.
  - **`OpenSkillPLEngine` (vanilla)** and **`OpenSkillPLDecayEngine` (τ ∈ {180, 365, 730})** in the harness.
  - **`rating.recompute_all`** extended with `decay_tau_days` parameter; full-history `openskill_pl_decay365` ratings exist alongside `openskill_pl` in the production DB via the model-name-keyed schema.
  - **Sortable `Decay #` column** on both the main leaderboard (per-gender) and the tournament-roster page (per-section).
  - **Per-player prediction quality** stat block on every profile page: held-out accuracy + log-loss under each model, plus a "Biggest model disagreement" callout pinpointing the one match where models diverged most for this player.
  - **Pred column** on the match log: shows Decay-365's predicted P(this player wins) at the time of each match (true held-out prediction). Hover shows vanilla PL's prediction.
  - **Model gaps page** (`site/disagreements.html`): top 300 matches across the dataset where the two models predicted most differently, with verdict tally (which model was right). Sortable + filterable. Linked from top nav as "Model gaps".
  - **Per-match prediction CSVs** for both engines under `_ANALYSIS_/model_evaluation/predictions/`.
  - **`_ANALYSIS_/model_evaluation/SUMMARY.md`** — methodology, headline numbers, calibration tables, Lonia validation, and per-player drill-down.
- **Headline findings:**
  - Decay τ=365 cuts log-loss by 5.8% (0.6526 → 0.6147) on 888 held-out matches and nearly eliminates the low-probability miscalibration in vanilla PL.
  - Lonia agreement *worsens* under decay (men ρ 0.704 → 0.600). The captain's ranking encodes long-running impressions more than recent form; both views can be true simultaneously.
  - Per-player evidence shows decay isn't uniformly better — Manuel Bonello's matches are predicted better by vanilla PL (LL 0.419 vs 0.539). The leaderboard Decay # column makes this visible.
  - Top dataset disagreement is a 70% gap (PL said 2%, Decay said 71%); these matches are the highest-leverage targets for captain input.
- **Foreshadows T-P1-009.** Glicko-2 (or any other) challenger now plug-and-play — drop a class into `ENGINES`, run backtest, compare.

### T-P0.5-011 — Decision: promote `openskill_pl_decay365` to `CHAMPION_MODEL`?

- **Status:** `decision pending`
- **Phase:** 0.5
- **Spawned by:** T-P0.5-010
- **Goal:** Decide whether to make Decay-365 the default sort/display model, or leave it as a parallel challenger surfaced via the Decay # columns.
- **Evidence already in hand** (see `_ANALYSIS_/model_evaluation/SUMMARY.md`):
  - Decay-365 log-loss 0.6147 vs vanilla 0.6526 on 888 held-out matches (5.8% improvement).
  - Decay-365 Brier 0.2134 vs vanilla 0.2186; accuracy roughly tied (64.98% vs 65.99%).
  - Vanilla is overconfident at both probability extremes; decay nearly fixes the low extreme.
  - Lonia agreement *worsens* under decay (men ρ 0.704 → 0.600). Captain mental model favours long-running impressions; the data favours recent form.
  - Per-player heterogeneity: Manuel Bonello's matches predicted better by vanilla; Cory Greenland's by decay.
- **What "done" looks like:** either a one-line change in `scripts/phase0/rating.py:32` (`CHAMPION_MODEL = "openskill_pl_decay365"`) + recompute + re-deploy, OR a written rationale in PLAN.md §5.2 for keeping vanilla as champion. Reversible either way via the model-name-keyed schema.
- **What's needed before deciding:**
  - Eyeball the live `Decay #` columns and the Model gaps page for a few days.
  - Spot-check 5-10 specific players where the two models disagree on a profile page; sanity-check whether the decay model's view "feels right" to a tennis-knowledgeable observer.
  - Optionally consult `rating-engine-expert` agent with the per-player heterogeneity data.
- **Acceptance:** Either CHAMPION_MODEL flipped + ADR/PLAN entry, or PLAN.md §5.2 updated to document the deliberate decision to keep vanilla as default and use decay as an exposed challenger.

### T-P0.5-012 — Tune the σ multiplier in the leaderboard display metric

- **Status:** `up next`
- **Phase:** 0.5
- **Spawned by:** T-P0.5-010 (H4 experiment)
- **Goal:** Replace `μ-3σ` with a less aggressive penalty (`μ-2σ`, `μ-σ`, etc.) on the public leaderboard display.
- **Evidence already in hand:**
  - Spearman ρ vs Lonia under each metric (champion model):
    - Men: μ-3σ 0.704, μ-2σ 0.717, μ-σ 0.731, μ-0.5σ **0.745**.
    - Ladies: μ-3σ 0.572, μ-1.5σ **0.587**, μ-σ 0.563, μ-0σ 0.538.
  - Lonia is one captain, not ground truth — but the calibration data from T-P0.5-010 ALSO supports loosening the σ penalty (vanilla PL is overconfident at the low end; the high σ-penalty exaggerates that).
- **Acceptance:** Pick a single multiplier (likely **μ-2σ** as a compromise — beats μ-3σ on both ρ and calibration, not a wild swing). Update display-only logic in `generate_site.py` (the column header, the cell formatting, and any sort key). The DB still stores μ + σ; this is a presentation change only. Validate that the leaderboard order doesn't shift dramatically (top players should be roughly stable).
- **Risk:** None — purely cosmetic, fully reversible, no data changes.

### T-P0.5-013 — Clean up gh-pages orphan player files

- **Status:** `up next` (low priority, ~10 min)
- **Phase:** 0.5
- **Goal:** Stop shipping ~793 stale `site/players/<id>.html` files for player IDs that have been merged out of the active set.
- **What's there now:** `generate_site.py` writes player pages for currently-eligible players but doesn't delete pages for players who are no longer eligible (merged into another canonical record). The orphan files persist on disk and ship to gh-pages on every deploy.
- **What's the user impact:** None today (orphans aren't linked from anywhere live), but they inflate the deployed bundle and a stale URL might surface via Google indexing or saved bookmarks showing pre-merge data.
- **Fix:** Add `shutil.rmtree(OUT_DIR / "players", ignore_errors=True)` before the per-player render loop in `main()`. ~1 line. Run + deploy verifies orphans are gone.

### T-P0.5-014 — Identity-resolution overhaul: typo auto-merger, dampener, mapping-transparency UI, review tools

- **Status:** `done` (2026-04-26 cont., this session)
- **Phase:** 0.5
- **Goal:** Eliminate the long tail of duplicate player records caused by spelling typos, captain-class false-positive merge suggestions, and lack of an interactive triage tool. Make every identity decision auditable from the public site.
- **What shipped:**
  1. **`merge-typo-duplicates`** auto-merger (`players.py:merge_typo_duplicates`) — lopsided typo pairs (≥4-match established + ≤2-match ghost; same gender/club/token-count; ratio ≥0.92 on raw lowercased names; min length 9). Single shared gate `_is_typo_pair` reused by the suggester so the two never drift. Ran twice on the real DB → 105 typo merges across the corpus.
  2. **`_confidence` dampener** (`players.py:_confidence`) — when both records carry a captain-assigned `latest_class`, apply −0.04 (same), −0.08 (different class same tier), or −0.18 (different tier). Plus a +0.02 boost for "lopsided n" so ghost+established pairs rank above same-N ambiguous ones. Result: `Christine Schembri (A1)` vs `Christine Scerri (C3)` dropped from 0.96 VERY HIGH to 0.70 LOW with full reasoning shown.
  3. **Auto-run on `cli.py load`** — case → token → typo → manual aliases run automatically after every successful parse, with one-line summary. Skippable via `--no-merge`. Eliminates the "run merge X manually after load" foot-gun.
  4. **DB path anchoring** — `db.py` / `generate_site.py` / `backtest.py` now resolve `phase0.sqlite` from `__file__` (project root) instead of cwd. Fixes a silent foot-gun where running CLI from `scripts/phase0/` operated on a stale 512KB DB while the real 8.7MB one at root never got touched.
  5. **`/aliases.html` mapping-transparency page** (`generate_site.py:build_aliases_page`) — every audit-log merge listed newest-first, deeplinkable per row (`#m-<audit_id>`), kind-pill colored, filterable (case/token/typo/manual), free-text searchable. Plus a snapshot of pending fuzzy suggestions bucketed VERY HIGH / HIGH / MEDIUM / LOW. Each player page's "Identity & merge history" section now back-links to the global view + per-merge deeplinks.
  6. **`cli.py review`** — terminal triage of pending suggestions (`s`/`d`/`k`/`q` prompts). Phone-friendly via SSH.
  7. **`cli.py review-server`** — local-only HTTP UI on `127.0.0.1:8765` (stdlib `http.server`, no new deps). Three buttons per pair (Same / Different / Defer); inline expandable mini-profile (recent matches, partners, classes, all aliases) so reviewers can decide without leaving the queue.
  8. **`known_distinct.json`** — durable record of "different people" verdicts; `suggest_fuzzy_matches` filters them out so the same false positive doesn't keep getting flagged. Pairs match as unordered sets. Atomic writes (tmpfile + rename).
- **Net effect:** 200 → 56 pending fuzzy candidates after one full pipeline run; 585 total merges in the audit_log (was 12 at session start); 837 → 732 active player records.
- **Tests:** 18 new unit tests covering `_is_typo_pair` boundaries, lopsided-merge end-to-end, the `known_distinct` filter, and the recorder helpers. All 38 player tests pass. Parser/rating tests untouched (still passing).
- **Memory entries written:** `feedback_db_path_anchor.md` (the cwd foot-gun), `project_pending_match_row_enrichment.md` (carried-forward request).

### T-P0.5-015 — Per-match impact UI: rank tags + 2-vs-2 expansion + set scores

- **Status:** `done` (2026-04-26 deploy / 2026-04-27 recorded)
- **Phase:** 0.5
- **Goal:** Make every match in the All Matches feed and per-player match log self-explanatory: show the players' rank-at-the-time, the proper set score, and one click away the per-player rank/score impact (with bypassed/passed-by commentary).
- **What shipped:**
  1. **`compute_match_impacts(conn)`** in `generate_site.py` — replays every active match chronologically, snapshotting per-(match, player) `rank_before` / `rank_after` / `score_before` / `score_after` / `mu_delta` / `score_delta` plus `bypassed` (overtaken on the way up) and `passed_by` (overtaken on the way down) lists. Per-gender bucket. ~2s for 4,891 matches × 19,357 (match, player) impact rows.
  2. **All Matches page** — every player name carries a `#NN` rank-tag reflecting their gender-bucket position immediately AFTER that match; ▶ expander reveals a 2-vs-2 layout (Side A pair on the left, "VS" divider in the middle, Side B pair on the right) with per-player rank and score deltas plus "↑ bypassed X" / "↓ passed by Y" commentary; set-by-set scores in the score column (falls back to total games when set scores missing).
  3. **Per-player match log** — same expansion on every match row; partner/opponent names link to their pages; `μ after` cell carries the player's own rank-tag.
  4. **2-vs-2 CSS** — `grid-template-areas: "a vs b"` desktop / `"a" "vs" "b"` mobile; row heights expand naturally (`white-space: normal` override on the global `td` nowrap rule); cards `word-break: break-word` so long bypassed lists wrap inside.
  5. **CSS cache-busting** — `CSS_VERSION = sha1(CSS).hexdigest()[:10]` appended as `?v=...` to every `<link rel="stylesheet">` so GH Pages serves the new styles immediately.
- **Net effect:** every match is now traceable to its rating impact — no more "why did Player X jump 12 places?" questions. The rank tag also implicitly answers "where did this player stand back then?" historically.

### T-P0.5-016 — Comprehensive site test harness + 80% line coverage

- **Status:** `done` (2026-04-27)
- **Phase:** 0.5
- **Goal:** Give a supporting dev (and future agents) confidence to refactor by anchoring the codebase to a fast, deterministic test suite. Get coverage of the in-tree modules (excluding parsers + .venv) above 80%.
- **What shipped:**
  1. **`scripts/phase0/test_generate_site.py`** — 36 test classes / ~120 tests covering: pure helpers (`esc`, `_delta_span`, `_rank_delta_span`, `player_link`, `CSS_VERSION`); `compute_match_impacts` scenarios (empty DB, single match, bypass + passed-by sequences, gender buckets, singles, superseded matches, walkovers); `render_match_impact_block` structure (2-vs-2 layout, new entries, +N more overflow, win/loss tags, root vs `/players/X.html` link prefix); page builders (`build_matches_page`, `build_player_page`, `build_index`, `build_aliases_page`); statistics (`compute_form` / `compute_streaks` / `compute_yearly_summary` / `compute_swings` / `render_trajectory_svg`); cross-cutting (`fetch_neighbour_index`, `render_neighbours`, `render_partner`, `render_opponents`, `render_score`, `render_identity_section`); a single big-leverage `TestMainEndToEnd` that runs `gs.main()` against the real `phase0.sqlite` in a tempdir; CLI smoke (every subparser `--help`, `load --init-only` against tempfile, `rank` / `history` / `suggest-merges` / `merge-token-duplicates --dry-run` / `apply-manual-aliases --dry-run` / `recommend-pairs` against the real DB); `players.merge_player_into`; `team_selection.store_team_selection` + `player_current_class` + `player_class_history`.
  2. **CLI test fixture** — `_patch_db()` wraps `db.init_db` with a closure that injects a temp DB path. (Naive `db.DEFAULT_DB_PATH = ...` doesn't work because Python freezes default-arg values at function-def time.)
  3. **Coverage report**: `db.py` 100%, `eval_identity.py` 91%, `generate_site.py` 95%, `players.py` 91%, `cli.py` 53%, `rating.py` 86%, `team_selection.py` 28%. Total: **80%** (was 37%).
- **Net effect:** 222 tests, ~7s wall-clock, run via `python -m unittest scripts.phase0.test_generate_site scripts.phase0.test_eval_identity scripts.phase0.test_players scripts.phase0.test_rating scripts.phase0.test_team_selection`.
- **Known gaps:** `cli.py` 53% — the `cmd_load` parser-driven path is hard to unit-test without xlsx fixtures; `team_selection.py` 28% — the openpyxl extractor needs xlsx fixtures too. Both could rise via subprocess-style integration tests against the real `_DATA_/` corpus. Out of scope for this task.

### T-P0.5-017 — Identity-resolution evaluation harness

- **Status:** `done` (2026-04-27)
- **Phase:** 0.5
- **Goal:** Quantify how well the fuzzy `_confidence` scorer covers the labelled ground-truth pairs (`manual_aliases.json` = same person, `known_distinct.json` = different people) so future score-function tweaks are testable, not vibes.
- **What shipped:**
  1. **`scripts/phase0/eval_identity.py`** — `evaluate(conn, aliases, distinct, thresholds)` returns per-threshold {recall, FP-rate, precision, TP/FN/FP/TN}. Uses `players._confidence` and `_token_fingerprint` so the scoring stays in sync. Best-effort enriches each side from the DB (gender, n_matches, latest_class, clubs); falls back to a name-only stub when the loser record was deleted post-merge (flagged `[stub]` in the report).
  2. **`cli.py eval-identity`** — `python scripts/phase0/cli.py eval-identity [--aliases X.json] [--distinct Y.json]`.
  3. **`scripts/phase0/test_eval_identity.py`** — 15 tests including a snapshot regression (`TestProductionDataFile`) that fails if recall@0.78 drops below 50% on the live ground-truth set.
- **Findings against live data (2026-04-27):** 55 positive pairs, 0 negative pairs (known_distinct empty). **91% recall at production T=0.78**; 100% recall at T=0.50. The 5 misses at T=0.78 are all surname-change-after-marriage cases (`Leanne Vassallo` ↔ `SCHEMBRI LEANNE` / `Leanne Schembri`; `Alexia Spiteri Willets` ↔ `Alexia Carabott` / `SPITERI WILLETTS ALEXIA` / `Alexia Spiteri`) — the algorithm legitimately can't catch these from name similarity alone; they require human-only knowledge.
- **Net effect:** every signal-weight tweak in `_confidence` (the `+0.02 / +0.04 / -0.05 / -0.15` constants) can now be measured. The harness IS the optimisation loop. FP-rate is undefined until `known_distinct.json` is populated — the natural feeder is `cli.py review` / `review-server` (and the upcoming T-P0.5-018 4-verdict UI).

### T-P0.5-018 — 4-verdict identity-triage UI (Merge / De-merge / Don't know / Skip) + manual reprocess button

- **Status:** `in-progress` (2026-04-27)
- **Phase:** 0.5
- **Goal:** Give the human reviewer a screen that walks every pending fuzzy pair one-by-one and lets them apply one of four verdicts that the system learns from. The current `cli.py review-server` has 3 verdicts (Same / Different / Defer) and no de-merge action; this task extends it to 4 verdicts plus an explicit de-merge flow plus a manual "Reprocess pending changes" button.
- **What it covers:**
  1. **4-verdict UI** in `cli.py review-server`:
     - **Merge** — same person; appends to `manual_aliases.json` via `players.record_same_person()`; the existing pipeline picks it up at next `apply-manual-aliases` run.
     - **De-merge** — wrong merge; finds the most-recent `audit_log` `player.merged` event for the pair and undoes it: `UPDATE players SET merged_into_id = NULL` on the loser; restore `match_sides.player1_id/player2_id` to the loser's original ID via the `before_jsonb` snapshot; write a new `audit_log` entry of type `player.unmerged` with the operator and reason; remove the entry from `manual_aliases.json` (if present); add to `known_distinct.json` so the suggester won't re-propose the merge.
     - **Don't know** — write to a new `defer.json` with a `revisit_after` timestamp (default: now + 14 days). Suggester filters these out until the timestamp passes.
     - **Skip** — don't persist anything; just move to the next pair in this session. (Different from "Don't know" which permanently defers.)
  2. **Pending-change counter** — every verdict appends a row to a new `scripts/phase0/pending_changes.jsonl` with `{ts, verdict, a_name, b_name, audit_log_id?}`. The reprocess button reads + clears this file.
  3. **"Reprocess pending changes" button** in the UI that runs synchronously: `apply-manual-aliases` → `rate` → `generate_site.main()` → `deploy-site.sh`. Disabled when `pending_changes.jsonl` is empty. After success, the JSONL is moved to a timestamped archive (`pending_changes.<ts>.jsonl`).
  4. **Tests** in `test_eval_identity.py` (or a new `test_review_server.py`):
     - de-merge correctly restores `match_sides.player1_id` from `before_jsonb`
     - de-merge writes `audit_log` `player.unmerged` entry
     - de-merge appends pair to `known_distinct.json`
     - "Don't know" filters the pair from suggester output until `revisit_after`
     - "Reprocess" pipeline is idempotent (running twice with no new changes = no-op)
- **Acceptance criteria:**
  - [ ] `cli.py review-server` UI shows 4 buttons per pair: Merge / De-merge / Don't know / Skip
  - [ ] Each verdict persists to the right file with the right shape
  - [ ] De-merge actually undoes the merge in the DB (verified by reading `players.merged_into_id` and `match_sides`)
  - [ ] `pending_changes.jsonl` accumulates verdicts and the "Reprocess" button consumes + archives it
  - [ ] After reprocess: `eval-identity` shows the new state (recall changed, miss list updated)
  - [ ] At least 6 new unit tests pass; existing tests unaffected
  - [ ] `eval_identity.evaluate()` reflects the new verdicts on next run
- **Out of scope:** the auto-trigger daemon (10-changes-or-30-min) — that's T-P0.5-019.
- **References:** `players.merge_player_into` (the inverse of de-merge), `players.record_same_person` / `record_distinct` (existing recorders), `audit_log.before_jsonb` (the snapshot that makes de-merge safe), T-P0.5-014 (the original review-server), T-P0.5-017 (the eval harness that measures the impact of each verdict).

### T-P0.5-019 — Auto-reprocess daemon (10 changes OR ≥1 change AND 30+ min elapsed)

- **Status:** `todo` (deferred)
- **Phase:** 0.5
- **Goal:** Replace the manual "Reprocess pending changes" button (T-P0.5-018) with a `launchd` daemon that watches `pending_changes.jsonl` and fires automatically when either threshold is hit, so the live site reflects review verdicts within minutes without requiring the operator to remember to click.
- **Trigger logic:** every 60s, if `pending_changes.jsonl` is non-empty: count changes (lines), check the timestamp of the first change. Fire reprocess if `count >= 10` OR `(count >= 1 AND now - first_change >= 30min)`.
- **Reprocess command:** same pipeline as the manual button — `apply-manual-aliases` → `rate` → `generate_site.main()` → `deploy-site.sh`. After success, archive `pending_changes.jsonl` to `pending_changes.<ts>.jsonl`.
- **Operational surface area:** a stuck/crashed daemon = stale rankings until manually restarted. Want a `launchd` plist with `KeepAlive=true` and a small Slack/Pushover error notifier. Adds another process to monitor.
- **Why deferred:** at current pair volume (~55 pairs over months) the manual button (T-P0.5-018) covers 90% of the value. Revisit when batch frequency justifies the operational overhead — likely after the next 100+ reviewed pairs.
- **Acceptance criteria (when picked up):**
  - [ ] `scripts/phase0/reprocess_daemon.py` polls every 60s and fires the pipeline on threshold
  - [ ] `launchd` plist installed under `~/Library/LaunchAgents/com.rallyrank.reprocess.plist`
  - [ ] On pipeline failure: archive `pending_changes.jsonl` to `pending_changes.failed.<ts>.jsonl` so a re-run starts clean; surface error somewhere visible (logfile + optional notification)
  - [ ] Two consecutive failures pause the daemon (require manual `launchctl kickstart` to resume)

Tasks below are intentionally sketchy until Phase 0 lands and we know what concrete shape Phase 1 takes. Don't expand to acceptance-criteria detail before Phase 0's retrospective informs them.

- **T-P1-001** — Postgres schema (port from Phase 0 SQLite, add Phase 1+ tables: model_predictions, model_scoreboard, champion_history, pair_chemistry, model_feedback, player_club_memberships, users, user_club_roles)
- **T-P1-002** — Migration tooling (plain SQL files, versioned)
- **T-P1-003** — Hand-written parser: VLTC team-tournament format (e.g., Antes / Joe Carabott Memorial)
- **T-P1-004** — Hand-written parser: Wilson Autumn/Spring series (older format, 2017–2021)
- **T-P1-005** — Hand-written parser: ESS / Elektra Mixed Doubles
- **T-P1-006** — Hand-written parser: Samsung Rennie Tonna / TCK / San Michel team formats
- **T-P1-007** — Bulk-load all VLTC files
- **T-P1-008** — Player alias / merge CLI (Phase 1 fuzzy-match + propose; admin confirms). **Substantially shipped in Phase 0.5** as `T-P0.5-014` — `cli.py review` (terminal triage), `cli.py review-server` (local-only HTTP UI on `127.0.0.1`), `manual_aliases.json` (same-person verdicts), `known_distinct.json` (different-people verdicts; filters the suggester so already-decided pairs stop re-surfacing), and `merge-typo-duplicates` auto-merger. Full mapping log + pending queue exposed read-only on the public site at `/aliases.html` with per-merge deeplinks. **Phase 1 work remaining:** port to Postgres + admin-role auth + writeable web UI (currently localhost-only).
- **T-P1-009** — Add **Modified Glicko-2** (per `_RESEARCH_/Doubles_Tennis_Ranking_System.docx` §5–9) as the first challenger model. Includes: team rating = avg(R) with RD = sqrt(mean RD²); universal games-won proportion as score `S`; explicit **partner-weighted Δ** per §7 (`ΔR_p1 = Δ × weight_p1 × 2` where `weight_p1 = R_p1 / (R_p1 + R_p2)`); per-division K-multipliers per §8; rating drift toward division mean for long absences per §9.2. `model_name = 'modified_glicko2'`. Use `glicko2` Python package for the base math; layer the modifications on top. **Backtest harness ready** (T-P0.5-010): drop a `Glicko2Engine` class into `scripts/phase0/backtest.py:ENGINES`, run `python3 scripts/phase0/backtest.py --engine modified_glicko2 --cutoff 2025-07-01`, compare log-loss + calibration vs `openskill_pl_vanilla` (0.6526) and `openskill_pl_decay365` (0.6147). The "Model gaps" page becomes a 3-way comparison after a few small tweaks to `build_disagreements_page`.
- **T-P1-010** — HITL: player merge channel (per §5.8)
- **T-P1-011** — Clean up "(pro)" / "(dem)" / "(Dem.)" substitute notations stuck in player canonical names (parser quirk surfaced in Phase 0; e.g. "Rose Falzon (pro) Mary Borg", "Ivan Cassar (pro Andrew Pule')", "Angele Pule(DEM)C.CHETCUTI"). Strip the suffix into a separate `match_sides.substitute_for` reference column or just discard the notation.
- **T-P1-012** — Dedupe `tournaments` rows on re-load (use `source_files.sha256`). Phase 0 created duplicates which the rating engine ignores (filters by active matches), but it's clutter.
- **T-P1-013** — Fix `sports_experience_2025.py` hardcoded `tournament.year=2025` so SE 2024 file shows correct year.
- **T-P1-014** — `tournaments.tier` column for tournament-type K multipliers (championship/standard/friendly/cross-club per `_RESEARCH_/...` §8.3).
- **T-P1-015** — ~~Investigate fuzzy match for variants WITHOUT case difference~~ **Done in Phase 0.5** (T-P0.5-014). The suggester+typo auto-merger handle non-case variants generally; specific apostrophe pairs (Angele Pule / Andrew Pule / Jesmond Pule) live in `manual_aliases.json`.
- **T-P1-016** — `team_tournament` parser misses the **Final** sheet. Surfaced 2026-04-26 loading `_DATA_/VLTC/scraped/San Michel Results 2026 (live gsheet 2026-04-26).xlsx`: Days 1–10 + Semi Final loaded fine (224 matches), but the Final sheet contributes **zero** matches even though it has played fixtures (Men A/B/C/D + Lad C visible). Root cause is the column-offset auto-detect in `_find_sheet_panels` — Day/SF sheets start match panels at column index 1 (col 0 is None padding); the Final sheet starts at column index 0 (no leading None column), and the detector falls through. Fix: extend the heuristic to try (col=0) as a fallback when no panels are found at (col=1..3), or detect by sheet name. Affects every team-tournament file with a Final round (~10 files in `_DATA_/VLTC/`). Add a test on the San Michel 2026 file asserting `round='final'` exists with ≥4 matches.
- **T-P1-017** — ~~Strengthen player-name aliasing for non-case variants~~ **Done in Phase 0.5** (T-P0.5-014). The four named families all now resolve through the auto-merger pipeline (case → token → typo → manual alias) plus the `_confidence` dampener that keeps cross-tier captain-class pairs (Schembri/Scerri-style) out of the auto-merge bucket. Specific Mangion / Christabel / Willem variants are merged in the audit_log; AnnMarie/Ann Marie variants are in `manual_aliases.json`. Result: 200 → 56 pending fuzzy candidates after the new pipeline ran.
- **T-P1-018** — Resolve the v2 rating model open doubts (filed 2026-04-26, commit `b1a05ff`). Three live concerns: (a) **captain bias** — Karl Debattista is ranked A1 by his captain despite μ=23.67 / 15% win-rate; `--sort raw` exposes the math view but the default class-sort lets a captain stamp dominate the leaderboard; need a UX answer (badge? secondary "math-rank" column? "captain says X, math says Y" callout?); (b) **two scoreboards** — class+μ both shown means new readers don't know which is "the official one"; need either a clear primary and a labeled secondary, or a single fused metric; (c) **no-team-assignment fallback** — 75% of canonical players (747/1006) have no class because they only show up in division round-robins, not team tournaments; their ranking falls back to derived class from primary division (e.g. `B?`) or `?` (sorts last). For non-team-tournament players the leaderboard is muddled. **Decisions needed before any public launch.**
- **T-P1-019** — Draft trust + legality ADRs 002–006 (`DESIGN/adr/INDEX.md` lists them as "not drafted"). 002 player-consent model (opt-in / opt-out / public-by-default), 003 visibility matrix (anon / member / captain / admin), 004 player real-name display (full / initials / handle), 005 disagreement / takedown channel, 006 audit retention vs GDPR Art. 17. **Gates everything else** — schema, page specs, takedown SOP, privacy.md all depend on these. Likely needs stakeholder input (committee? external lawyer?) so schedule a longer planning session before drafting.
- **T-P1-020** — Public-launch checklist for the static site at `site/`. **Depends on T-P1-019 ADR decisions.** Acceptance includes: privacy notice page (per PLAN.md §5.9), takedown channel (form? email? Slack?), `robots.txt` (allow vs disallow indexing — depends on consent model), GDPR Art. 17 player-removal SOP wired to `audit_log`, opt-out signal honored in the static generator, hosting decision (current Cloudflare Tunnel from a home Proxmox vs a real provider) reaffirmed in light of legal exposure.
- **T-P1-021** — Per-tournament report infrastructure. `reports/` currently has only `san_michel_2026_team_selection.md` (one-off). Need a generator that produces "what's coming up" / "results recap" reports per tournament — pre-tournament roster grid + post-tournament leaderboard impact. The Captain-Lonia analysis in `_ANALYSIS_/NewTournamentRanking/` is a good template. Folds into the static-site generator pipeline.
- **T-P1-022** — Multi-club separation in the site nav. Currently the leaderboard mixes VLTC + TCK players without distinction; the player page doesn't show club affiliation. Need either a per-club site (two separate static-site builds) or a club-toggle / club-column UI. Cross-references PLAN.md §5.9 (public visibility — per-club opt-out semantics).
- **T-P1-023** — Phase D position-bonus K decision. Was "deliberately skipped per recommendation" in the v2 rating commit (`b1a05ff`); reaffirm whether to leave skipped or implement. Position bonus K = give larger Δ to wins played in higher-tier positions within a team rubber. Trade-off: more accurate rating signal vs adding a new lever Kurt has to explain to non-technical users. Decide and either close as `won't-do` or implement.
- **T-P1-024** — Manual-alias coverage audit. `scripts/phase0/manual_aliases.json` is a JSON file editable by hand; no admin UI yet. Two issues: (1) it's not version-controlled in git (intentional? it currently is ignored?) — confirm; (2) it has no audit trail — adding a manual alias should write `audit_log` like every other mutation per PLAN.md §5.5. Either route through `audit_log` or document why it's exempt.

---

## Phase 2 — Web app skeleton (stubs)

- **T-P2-001** — Next.js project scaffold (`apps/web`)
- **T-P2-002** — NextAuth setup (admin role + viewer)
- **T-P2-003** — Postgres connection + Prisma (or drizzle — decide in Phase 1)
- **T-P2-004** — Public rankings page
- **T-P2-005** — Player profile page with rating-history chart
- **T-P2-006** — Admin player-merge UI
- **T-P2-007** — Multi-model dashboard (side-by-side leaderboards, disagreements, predictive scoreboard)
- **T-P2-008** — HITL: match exclusion UI
- **T-P2-009** — HITL: score correction UI
- **T-P2-010** — Audit log writes wrapper
- **T-P2-011** — docker-compose for self-host on Proxmox (Caddy + Next.js + Postgres + Redis + worker + MinIO)
- **T-P2-012** — Privacy notice page (per §5.9 — covers GDPR Art. 17 path)
- **T-P2-013** — Admin "remove player" action (per §5.9 — for GDPR Art. 17 requests)
- **T-P2-014** — Leaderboard secondary stats per `_RESEARCH_/...` §12: Win%, Game Win%, Average Margin, Consistency Index, Partner Synergy (= our `pair_chemistry`), Upset Rate, Peak Rating, Current Form (Δ over last 3 tournaments), Head-to-Head. Display-only — does not affect the rating math.
- **T-P2-015** — RD-based "Provisional / Reliable" badges per `_RESEARCH_/...` §2.3 thresholds; minimum-activity gates for leaderboard inclusion (≥8 matches lifetime; ≥3 matches in last 12 months for "active" status) per §9.4.

---

## Phase 3 — Agentic ingestion (stubs)

- **T-P3-001** — Upload UI for admins
- **T-P3-002** — MinIO integration
- **T-P3-003** — Redis job queue between web and worker
- **T-P3-004** — Python ingestion agent (Claude API; structured extraction; vision fallback for PDFs/images)
- **T-P3-005** — Quality report generator (per §5.3.1)
- **T-P3-006** — Re-process workflow + supersede semantics
- **T-P3-007** — Dashboard widget: unreviewed reports
- **T-P3-008** — HITL: informal-match upload channel

---

## Phase 4 — Pair recommender (stubs)

- **T-P4-001** — Roster input UI
- **T-P4-002** — Chemistry-residual model training
- **T-P4-003** — Constraint-aware optimization (men/women × division A/B/C/D)
- **T-P4-004** — HITL: pair-rec accept/reject logging

---

## Phase 5 — Multi-club & polish (stubs)

- **T-P5-001** — Onboard second club
- **T-P5-002** — Cross-club player linking flow
- **T-P5-003** — Per-club admin permission isolation
- **T-P5-004** — Manual rating-pin escape hatch (only if a real need emerged by Phase 5)

---

## Cross-cutting / ongoing

These have no phase — they're maintained continuously.

### T-X-001 — Keep PLAN.md in sync with reality

- **Status:** `ongoing`
- **References:** `PLAN.md` §10
- **Goal:** Whenever a decision changes or a new significant discovery happens, update `PLAN.md` in the same commit. Stale `PLAN.md` is worse than no `PLAN.md`.

### T-X-002 — Maintain MEMORY.md (Claude memory)

- **Status:** `ongoing`
- **References:** `~/.claude/projects/-Users-kurtcarabott-WKS-SOCIAL-TENNIS/memory/`
- **Goal:** When stack or design decisions change, update the relevant memory file so future Claude sessions have current context. Don't let memory drift from reality.

### T-X-003 — Document parsing edge cases as they arise

- **Status:** `ongoing`
- **References:** Phase 1 parsers
- **Goal:** Every time a parser hits a "huh, that's weird" data shape, log it in `docs/parsing-edge-cases.md` (file to be created in Phase 1) so the next parser writer doesn't rediscover it.

---

## Done

(empty — first task hasn't been completed yet)
