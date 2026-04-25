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

**Phase 0 — local proof of concept.** See `PLAN.md` §7 for phase definition.

| State | Tasks |
|---|---|
| `in-progress` | (none) |
| `up next` (todo, deps satisfied) | T-P0-001 |
| `blocked` | (none) |
| `recently done` | (none yet — first code commit pending) |

---

## Phase 0 — Local proof of concept

**Goal of this phase:** validate that the rating model produces sensible doubles rankings on real VLTC data, before investing in any infrastructure. Exit criterion (per `PLAN.md` §7): top-20 list of doubles players from a single tournament looks intuitively correct to a knowledgeable observer.

**Stack for Phase 0:** Python 3 + openpyxl + openskill + SQLite + scipy (for the Hungarian algorithm). No web app, no Postgres, no Docker — just `python scripts/phase0/cli.py <command>`.

---

### T-P0-001 — Phase 0 scaffolding

- **Status:** `todo`
- **Phase:** 0
- **Depends on:** none
- **Blocks:** T-P0-002, T-P0-003, T-P0-006
- **Estimated effort:** 30–45 min
- **References:** `PLAN.md` §7 (Phase 0 row); `CLAUDE.md` (conventions section)

**Goal:** Set up the directory structure, dependencies pin file, and a stub CLI entry point so subsequent tasks can hang code off a real skeleton.

**Acceptance criteria:**
- [ ] `scripts/phase0/` directory exists with `__init__.py`
- [ ] `scripts/phase0/cli.py` exists with subcommand stubs (`load`, `rate`, `rank`, `recommend-pairs`) that print "not implemented" — no logic yet
- [ ] `scripts/phase0/README.md` exists with how to install deps, how to run each subcommand, and a pointer to `PLAN.md`
- [ ] `requirements-phase0.txt` exists pinning at minimum: `openpyxl`, `openskill`, `scipy`, `python-dateutil`
- [ ] `.gitignore` updated to ignore `phase0.sqlite`, `*.sqlite-wal`, `*.sqlite-shm`, `scripts/phase0/.venv/`
- [ ] `python scripts/phase0/cli.py --help` runs without error and shows the four subcommands

**Implementation notes:**
- Use `argparse` (stdlib) — don't pull in click or typer for Phase 0.
- Don't use a `pyproject.toml` for Phase 0; a flat `requirements-phase0.txt` is enough. `pyproject.toml` lands in Phase 1 when we have a real package.
- The `__init__.py` is empty — the module is meant to be run via `python -m` or `python scripts/phase0/cli.py`.

**Progress log:**
- (none yet)

---

### T-P0-002 — SQLite schema (model-agnostic, Phase 0 subset)

- **Status:** `todo`
- **Phase:** 0
- **Depends on:** T-P0-001
- **Blocks:** T-P0-004, T-P0-006
- **Estimated effort:** 1–2 hours
- **References:** `PLAN.md` §6 (data model); `PLAN.md` §5.7 (model-agnostic schema rationale)

**Goal:** Create the initial SQLite schema matching `PLAN.md` §6, scaled down to the tables Phase 0 actually needs. **Crucially: the `model_name` discriminator column is included from day one** even though Phase 0 only runs one model — this is settled per §5.7.

**Acceptance criteria:**
- [ ] `scripts/phase0/schema.sql` exists with `CREATE TABLE` statements for these tables only:
  - `clubs`, `players`, `player_aliases`
  - `tournaments`, `source_files`, `ingestion_runs`
  - `matches`, `match_sides`, `match_set_scores`
  - `ratings` (with `model_name`), `rating_history` (with `model_name`)
  - `audit_log`
- [ ] **Skipped** for Phase 0 (will be added in Phase 1+): `model_predictions`, `model_scoreboard`, `champion_history`, `pair_chemistry`, `model_feedback`, `player_club_memberships`, `users`, `user_club_roles`. Comment in the SQL file explains why each is skipped.
- [ ] Primary keys correct, including composite `(player_id, model_name)` on `ratings` and `(player1_id, player2_id, model_name)` on `pair_chemistry` (when added).
- [ ] Index on `matches(superseded_by_run_id) WHERE superseded_by_run_id IS NULL` (the active-match index from §5.3.1).
- [ ] `scripts/phase0/db.py` exposes `init_db(path: str) -> sqlite3.Connection` that creates the file if missing and applies `schema.sql`. Idempotent.
- [ ] Running `python scripts/phase0/cli.py load --init-only` creates a fresh `phase0.sqlite` and applies the schema with no errors.

**Implementation notes:**
- Use `sqlite3` from stdlib.
- Foreign keys: enable with `PRAGMA foreign_keys = ON;` on every connection — SQLite has them off by default.
- Use `INTEGER PRIMARY KEY` for `id` columns (this gets you autoincrement-ish via ROWID).
- For dates: use `TEXT` storing ISO 8601 (`YYYY-MM-DD`). SQLite has no real date type and ISO sorts lexically.
- For `*_jsonb` columns from §6 (e.g., `ingestion_runs.quality_report_jsonb`): use `TEXT` and store JSON; column name keeps the `_jsonb` suffix for clarity even though SQLite has no JSONB type.

**Progress log:**
- (none yet)

---

### T-P0-003 — Pick target file & produce parser specification

- **Status:** `todo`
- **Phase:** 0
- **Depends on:** T-P0-001
- **Blocks:** T-P0-004
- **Estimated effort:** 30–60 min
- **References:** `_DATA_/VLTC/Sports Experience Chosen Doubles 2025 result sheet.xlsx`; `.claude/agents/tennis-data-explorer.md`; `PLAN.md` §3, §6

**Goal:** Use the `tennis-data-explorer` agent to produce a parser-ready specification for the chosen Phase 0 file. The output is a markdown spec the parser implementer (T-P0-004) follows.

**Acceptance criteria:**
- [ ] `tennis-data-explorer` agent invoked on `_DATA_/VLTC/Sports Experience Chosen Doubles 2025 result sheet.xlsx`
- [ ] Output saved as `scripts/phase0/parser_spec_sports_experience_2025.md` (NOT auto-deleted at end of session)
- [ ] Spec contains all sections from the agent's output format: file analyzed, format classification, sheet map, extraction recipe, schema mapping, edge cases, suggested parser test cases
- [ ] At least 3 specific test cases (named matches with expected extracted data) listed for the parser

**Implementation notes:**
- This is a pure delegation task — invoke the agent with the file path and persist its output. Don't rewrite or summarize.
- If the agent flags ambiguities the parser implementer needs to resolve, surface them in the progress log here so T-P0-004 doesn't stall.

**Progress log:**
- (none yet)

---

### T-P0-004 — Manual parser for Sports Experience Chosen Doubles 2025

- **Status:** `todo`
- **Phase:** 0
- **Depends on:** T-P0-002, T-P0-003
- **Blocks:** T-P0-006, T-P0-009
- **Estimated effort:** 3–5 hours
- **References:** `parser_spec_sports_experience_2025.md` (created in T-P0-003); `PLAN.md` §6 (schema), §3 (data sources), §5.3.1 (`ingestion_run_id`)
- **Recommended agents:** `parser-implementer` (spawn after spec exists; it follows the spec and writes the tests)

**Goal:** Implement a Python parser that reads the chosen file and inserts normalized rows into SQLite using the schema from T-P0-002.

**Acceptance criteria:**
- [ ] `scripts/phase0/parsers/sports_experience_2025.py` exists, exposing `parse(xlsx_path, db_conn) -> ingestion_run_id`
- [ ] CLI `python scripts/phase0/cli.py load --file <path>` invokes the parser and reports rows inserted
- [ ] One `source_files` row, one `ingestion_runs` row created per invocation
- [ ] One `tournaments` row created (format `'doubles_division'`)
- [ ] `matches`, `match_sides`, `match_set_scores` populated faithfully — every match in the file has corresponding rows
- [ ] Each `matches` row has `ingestion_run_id` set
- [ ] Players inserted into `players` (via T-P0-005's normalization) — no duplicates within this file
- [ ] All test cases listed in `parser_spec_sports_experience_2025.md` pass (manual verification)
- [ ] Re-running the load on the same file with the same content produces a NEW `ingestion_runs` row, marks the previous run's matches as superseded (this is the re-process path from §5.3.1)

**Implementation notes:**
- Use `openpyxl.load_workbook(path, data_only=True, read_only=True)`.
- Player names recorded as appearing in the file → also captured as `player_aliases` rows pointing at the canonical player record (see T-P0-005).
- Don't try to be clever — match the file's structure 1:1. Cleverness goes into the rating engine, not the parser.
- Wrap the whole load in a single SQLite transaction so a parse failure doesn't leave a half-loaded run.

**Progress log:**
- (none yet)

---

### T-P0-005 — Player name normalization + alias storage

- **Status:** `todo`
- **Phase:** 0
- **Depends on:** T-P0-002
- **Blocks:** T-P0-004
- **Estimated effort:** 1–2 hours
- **References:** `PLAN.md` §5.4 (entity resolution layers)

**Goal:** Implement the Phase 0 minimum-viable player-identity layer: NFKC + apostrophe + whitespace normalization on insert, with a canonical `players` row and one or more `player_aliases` rows tracking each raw form ever seen.

**Acceptance criteria:**
- [ ] `scripts/phase0/players.py` exposes `get_or_create_player(db_conn, raw_name: str, source_file_id: int) -> player_id`
- [ ] Normalization rules applied:
  - NFKC normalize
  - Replace curly apostrophes (`'`, `'`) with straight (`'`)
  - Collapse internal whitespace runs to single space
  - Strip leading/trailing whitespace
  - Casing preserved as-is (don't lowercase — display name matters)
- [ ] If a player with the same canonical name already exists, return its ID and add an alias row only if the raw name differs from any existing alias for that player
- [ ] Phase 0 does NOT do fuzzy matching (Levenshtein, initials) — that's Phase 1's `merge` CLI. Two genuinely-different names → two genuinely-different players, even if obviously the same person. Document this trade-off in the progress log.
- [ ] Unit tests cover: curly vs straight apostrophe collide, surrounding whitespace ignored, casing preserved, distinct names create distinct players

**Implementation notes:**
- Use `unicodedata.normalize('NFKC', name)`.
- Apostrophe characters to normalize: `’` (right single quotation mark), `‘` (left single quotation mark) → `'` (apostrophe).
- Don't lowercase. "Duncan D'Alessandro" and "duncan d'alessandro" are technically the same person but Phase 0 will flag them as different — that's a Phase 1 problem.

**Progress log:**
- (none yet)

---

### T-P0-006 — OpenSkill rating engine integration

- **Status:** `todo`
- **Phase:** 0
- **Depends on:** T-P0-001, T-P0-002, T-P0-004
- **Blocks:** T-P0-007, T-P0-008
- **Estimated effort:** 2–4 hours
- **References:** `PLAN.md` §5.2 (algorithm + score margin + time decay); `PLAN.md` §5.7 (model-agnostic — `model_name='openskill_pl'`)
- **Recommended agents:** `rating-engine-expert` (consult for parameter choices — tau, score-margin formula, alpha — and for code review of the rating math before completing the task)

**Goal:** Apply OpenSkill (Plackett-Luce) to all matches in the DB; write per-player `mu`/`sigma` to `ratings` and per-match deltas to `rating_history`.

**Acceptance criteria:**
- [ ] `scripts/phase0/rating.py` exposes `recompute_all(db_conn, model_name: str = 'openskill_pl')`
- [ ] CLI `python scripts/phase0/cli.py rate` invokes recompute over all matches, processed in `played_on, match.id` chronological order
- [ ] For each match: each side modeled as a 2-player team; OpenSkill `rate()` produces updated mu/sigma per player; `ratings` table updated; one `rating_history` row per player (4 per match) appended
- [ ] **Score margin weighting** applied: each match has a "weight" multiplier in `[0.5, 1.5]` derived from games-won margin. Specific formula left to Phase 0 to tune; document choice in the progress log.
- [ ] **Sigma drift (time decay)** applied between matches: when computing a player's pre-match rating, if their last match was N rating periods ago, apply `sigma' = sqrt(sigma² + N * tau²)`. Default `tau = 0.0833`, rating period = 1 calendar month. Tunable.
- [ ] Skips matches where `superseded_by_run_id IS NOT NULL`
- [ ] After running on the Sports Experience 2025 data, the `ratings` table has one row per player who appeared

**Implementation notes:**
- `openskill.models.PlackettLuce` is the model class. See https://openskill.me — but pin the version in `requirements-phase0.txt` and document it.
- Don't try to be incremental in Phase 0. `recompute_all` is fine — wipe `ratings` and `rating_history`, replay from earliest match. Incremental updates land in Phase 1.
- For score margin: a sensible starter formula is `weight = 1.0 + 0.5 * tanh(games_diff / 4.0)`. Tune it later.
- For sigma drift: rating period = month (start of). For a player with last match in March 2025 whose new match is in June 2025, N = 3.

**Progress log:**
- (none yet)

---

### T-P0-007 — CLI: `rank` command

- **Status:** `todo`
- **Phase:** 0
- **Depends on:** T-P0-006
- **Blocks:** T-P0-009
- **Estimated effort:** 1–2 hours
- **References:** `PLAN.md` §5.2 (Time decay paragraph — leaderboard active filter); `PLAN.md` §7 (Phase 0 exit criterion)

**Goal:** Implement `python scripts/phase0/cli.py rank` to print the top-N doubles players with their current rating.

**Acceptance criteria:**
- [ ] CLI flags: `--top N` (default 20), `--active-months M` (default 12; pass 0 to disable filter), `--gender {men,ladies,all}` (default `all`)
- [ ] Output is a tabular text format with columns: rank, player name, mu (rounded to 2 decimals), sigma (rounded to 2 decimals), n_matches, last_match_date
- [ ] Players ordered by `mu - 3*sigma` (conservative skill estimate — common Bayesian convention)
- [ ] Players whose most recent match is older than `active-months` are filtered out (unless flag = 0)
- [ ] If gender is filterable from the data, honor it; if Phase 0 doesn't have gender info on players, log this and ignore the flag
- [ ] Running on Sports Experience 2025 produces a coherent top-20 list

**Implementation notes:**
- The "mu - 3*sigma" ordering matters: a new player with high mu but huge sigma should NOT outrank a proven player. This is the conservative-rating convention.
- Use the stdlib `string.Formatter` or just printf-style padding for the table — no `tabulate` dep for Phase 0.

**Progress log:**
- (none yet)

---

### T-P0-008 — CLI: `recommend-pairs` command

- **Status:** `todo`
- **Phase:** 0
- **Depends on:** T-P0-006
- **Blocks:** T-P0-009
- **Estimated effort:** 2–3 hours
- **References:** `PLAN.md` §1 (pair-recommendation goal); `PLAN.md` §5.2 (additive partner model for v1; chemistry residual deferred to Phase 4)

**Goal:** Given a roster of N players (N must be even), output the pairing that maximizes total team strength.

**Acceptance criteria:**
- [ ] CLI: `python scripts/phase0/cli.py recommend-pairs --players "Name1,Name2,...,NameN"`
- [ ] N must be even ≥ 4; CLI errors clearly otherwise
- [ ] All N names must be resolvable to existing player IDs; unresolved names error with a list of "did you mean" candidates (use Levenshtein distance on canonical names)
- [ ] Pair strength function: `strength(p_a, p_b) = mu_a + mu_b - alpha * (sigma_a + sigma_b)` with `alpha = 1.0` default. Document choice.
- [ ] Algorithm: enumerate all possible pairings of N players (or use blossom algorithm via `networkx.max_weight_matching` for larger N) and return the assignment maximizing sum of pair strengths
- [ ] Output: list of suggested pairs in order, with each pair's strength score, and total team strength

**Implementation notes:**
- For N ≤ 12, brute-force enumeration is fine: `(2k)! / (2^k * k!)` pairings of 2k players. For 12 players that's 10395 — trivial.
- For larger N, use `networkx.algorithms.matching.max_weight_matching` (it's perfect-matching capable on a complete graph with edge weights = pair strength).
- "Pair strength" in Phase 0 is purely additive — no chemistry residual. Chemistry is Phase 4's `pair_chemistry` table.
- Hungarian algorithm (mentioned in `PLAN.md`) is for assignment problems (m workers to n jobs); for pairing within a single set, the matching approach above is the right one. Don't use `scipy.optimize.linear_sum_assignment` for this — wrong shape.

**Progress log:**
- (none yet)

---

### T-P0-009 — End-to-end validation & user review

- **Status:** `todo`
- **Phase:** 0
- **Depends on:** T-P0-004, T-P0-007, T-P0-008
- **Blocks:** T-P0-010
- **Estimated effort:** 30 min run + however long Kurt's review takes
- **References:** `PLAN.md` §7 (Phase 0 exit criterion)

**Goal:** Run the full Phase 0 pipeline end-to-end and capture Kurt's reaction. **This is the gate that unblocks Phase 1.**

**Acceptance criteria:**
- [ ] `phase0.sqlite` deleted; pipeline run from scratch:
  1. `python scripts/phase0/cli.py load --init-only`
  2. `python scripts/phase0/cli.py load --file _DATA_/VLTC/Sports\ Experience\ Chosen\ Doubles\ 2025\ result\ sheet.xlsx`
  3. `python scripts/phase0/cli.py rate`
  4. `python scripts/phase0/cli.py rank --top 20`
  5. `python scripts/phase0/cli.py recommend-pairs --players "..."` (Kurt picks 6–12 real names)
- [ ] Outputs from steps 4 and 5 captured and shared with Kurt
- [ ] Kurt explicitly says rankings look intuitively correct (or specifies what's off)
- [ ] If rankings are off: file a `T-P0-XXX` task to investigate before declaring Phase 0 done

**Implementation notes:**
- The "looks right" judgment is genuinely subjective — Kurt knows these players. We can't automate this gate.
- If a few rankings look obviously wrong but most are right, log specifics and triage in T-P0-010 retrospective rather than blocking.

**Progress log:**
- (none yet)

---

### T-P0-010 — Phase 0 retrospective + plan updates

- **Status:** `todo`
- **Phase:** 0
- **Depends on:** T-P0-009
- **Blocks:** Phase 1 kickoff
- **Estimated effort:** 1 hour
- **References:** `PLAN.md` §10 (what we'd change after a week of using it)

**Goal:** Capture what we learned in Phase 0 and update `PLAN.md` so Phase 1 starts from current reality, not the original plan.

**Acceptance criteria:**
- [ ] Append a "Phase 0 retrospective" subsection to `PLAN.md` §10 covering: what worked, what surprised us, what tuning landed (tau, weight formula, alpha), parser quirks worth knowing for Phase 1 parsers
- [ ] Open new tasks under Phase 1 for any newly-discovered work
- [ ] Mark Phase 0 tasks `done` in this file
- [ ] Commit + push

**Progress log:**
- (none yet)

---

## Phase 1 — Data foundation (stubs, not yet actionable)

Tasks below are intentionally sketchy until Phase 0 lands and we know what concrete shape Phase 1 takes. Don't expand to acceptance-criteria detail before Phase 0's retrospective informs them.

- **T-P1-001** — Postgres schema (port from Phase 0 SQLite, add Phase 1+ tables: model_predictions, model_scoreboard, champion_history, pair_chemistry, model_feedback, player_club_memberships, users, user_club_roles)
- **T-P1-002** — Migration tooling (plain SQL files, versioned)
- **T-P1-003** — Hand-written parser: VLTC team-tournament format (e.g., Antes / Joe Carabott Memorial)
- **T-P1-004** — Hand-written parser: Wilson Autumn/Spring series (older format, 2017–2021)
- **T-P1-005** — Hand-written parser: ESS / Elektra Mixed Doubles
- **T-P1-006** — Hand-written parser: Samsung Rennie Tonna / TCK / San Michel team formats
- **T-P1-007** — Bulk-load all VLTC files
- **T-P1-008** — Player alias / merge CLI (Phase 1 fuzzy-match + propose; admin confirms)
- **T-P1-009** — Add Glicko-2 as the first challenger model (per §5.7)
- **T-P1-010** — HITL: player merge channel (per §5.8)

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
