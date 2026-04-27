# Contributing to RallyRank

Thanks for your interest. This file is the practical "I cloned the repo, now what?" guide. For the *why* behind decisions, read [`PLAN.md`](PLAN.md). For the live work tracker, read [`TASKS.md`](TASKS.md). If you're using Claude Code, [`CLAUDE.md`](CLAUDE.md) is your orientation.

## Getting set up

Requires Python 3.11+ (3.12 recommended). No Node, no Docker, no database server during Phase 0 — everything runs locally against SQLite.

```bash
git clone https://github.com/devkurtc/wks-social-tennis-rankings-malta.git
cd wks-social-tennis-rankings-malta

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-phase0.txt
pip install pytest                       # only needed for `pytest`; not in requirements

# Sanity-check the toolchain
python3 -m scripts.phase0.cli --help
```

`.env.example` shows the optional environment variables. Copy to `.env` if you need them; nothing in the public Phase-0 path requires secrets.

## Building and running locally

```bash
# 1. Ingest the source Excels into SQLite
python3 -m scripts.phase0.cli ingest

# 2. Compute OpenSkill ratings (champion model)
python3 -m scripts.phase0.cli rate

# 3. Generate the static site
python3 scripts/phase0/generate_site.py

# 4. Serve it
python3 -m http.server -d site 8000
```

`phase0.sqlite` is gitignored. The ingest step rebuilds it from `_DATA_/`. If something looks off, blow it away (`rm phase0.sqlite`) and re-ingest.

The CLI has more subcommands — `python3 -m scripts.phase0.cli --help` lists them. Useful ones during development: `review`, `review-server`, `eval-identity`, `recompute --model <name>`.

## Running the tests

```bash
pytest scripts/phase0/                    # full suite — ~222 tests
pytest scripts/phase0/test_rating.py      # one file
pytest scripts/phase0/ -k "rating" -v     # filter by name
```

There's no separate integration vs unit split; everything runs against an in-memory SQLite or a temp DB fixture. Tests should pass cleanly on a fresh checkout.

### Coverage policy: ≥80% line coverage

Project policy is **minimum 80% line coverage on `scripts/phase0/`** (the equivalent rule applies to the Phase 1+ app/worker modules when they land). The current baseline was locked in by T-P0.5-016: ~80% across `generate_site.py` / `players.py` / `cli.py` / `eval_identity.py` / `db.py`.

PRs must:

- Hit **≥80% line coverage on any new module** they introduce.
- **Not lower** the project-total coverage. If a refactor makes existing lines unreachable, delete the dead code rather than letting it sit untested.
- Include a coverage report in the PR description (paste the `--cov-report=term` output, or screenshot the HTML).

Measure with:

```bash
pip install pytest-cov                                      # one-time
pytest --cov=scripts.phase0 --cov-report=term-missing scripts/phase0/
pytest --cov=scripts.phase0 --cov-report=html scripts/phase0/   # browse htmlcov/index.html
```

Lines that are genuinely untestable (entry-point glue like `if __name__ == "__main__":`, hard `sys.exit` after a fatal config error) can be excluded with `# pragma: no cover` and a `# Why:` comment explaining why. Don't pad coverage with trivial assertions, don't delete tests to make the number rise, and don't blanket-exclude real production code. The point is regression safety, not the metric.

## Hard rules — read before opening a PR

These come from [`CLAUDE.md`](CLAUDE.md) and are restated here so contributors who aren't using Claude Code see them. Violating any of these will get the PR bounced.

1. **Never modify files inside `_DATA_/`.** They're the authoritative source. Cleanup belongs in the parser, not the source.
2. **Never widen or rename the schema** without first proposing the change in [`PLAN.md`](PLAN.md) §6 and getting it agreed. Multi-model is already supported via the `model_name` discriminator on `ratings` / `rating_history` ([§5.7](PLAN.md)) — no schema change needed to add a new rating algorithm.
3. **Don't deploy directly to `gh-pages`** unless you're a trusted collaborator (see "Trusted collaborators" below). External contributors open a PR to `main`; a maintainer or trusted collaborator regenerates and ships.
4. **Player names are normalised on insert** (NFKC, straight quotes, collapsed whitespace). Use the existing helpers in `scripts/phase0/players.py`. Don't roll your own.
5. **Every mutation goes through the audit-log helper** in the same transaction. Look at how `players.merge_player` or `rating.recompute_all` writes to `audit_log` and match the pattern.
6. **No secrets, no `.env*` files, no DB dumps, no `~$*.xlsx` Excel lock files** in commits. The `.gitignore` covers known cases; extend it before committing anything new and unfamiliar.

## Workflow

We work off [`TASKS.md`](TASKS.md) — each task is self-contained with goal, dependencies, references, acceptance criteria, and an append-only progress log. The "Current focus" section lists what's `in-progress`, `up next`, and `recently done`.

To pick up work:

1. **Reconcile the tracker first.** Skim `git log` since the last `done` task; if shipped commits aren't reflected in `TASKS.md`, fix that before starting new work. (We've been burned by stale trackers — see the memory in `CLAUDE.md`.)
2. Pick a task in the "up next" list whose `Depends on` are all `done`. If you're starting fresh and don't see one that fits, open an issue first to discuss scope.
3. Set the task's status to `in-progress` and add a progress-log line ("picked up by <name> on <date>").
4. Work in small commits. After every commit / direction change / snag, append a progress-log line to the task.
5. On completion: verify each acceptance criterion against actual repo state, mark `done`, append the final progress-log line.
6. Open a PR to `main`. The PR description should reference the task ID (e.g. `T-P0.5-020`) and summarise what shipped.

If you're using Claude Code, the `/pickup-task`, `/log-progress`, and `/complete-task` skills automate steps 3, 4, and 6.

### Commit + pull cadence — please follow this

Several humans and AI agents work on this repo concurrently. The single biggest source of avoidable friction is **stale local checkouts** and **long-lived uncommitted work**. These aren't optional polish; following them keeps merges painless:

- **Pull before you start.** First thing every session: `git pull --rebase origin main`. Five seconds. Saves you 20-minute conflicts on files someone touched while you were away.
- **Commit small, commit often.** One logical chunk per commit (a parser fix → one commit; a test addition → another commit). Don't accumulate eight unrelated changes into a "wip" commit. Small commits review easily, revert cleanly, and rebase past concurrent work without drama.
- **Push as soon as the commit is mergeable.** A local-only commit is invisible to everyone else. They can't rebase past it, can't see it in `git log`, and might duplicate the work. Push, then continue.
- **Pull again before pushing if the session has been long.** More than ~30 min since your last pull? `git pull --rebase` first. Cheap insurance.
- **Conflicts: resolve, don't bypass.** If a rebase produces a conflict, read both sides and reconcile. Don't blanket `--theirs` / `--ours` and don't `--no-verify` past a failing hook. The shortcut deletes someone else's work.

**Why it matters here specifically:** `TASKS.md`, `PLAN.md`, and the `.claude/` coordination files are touched by every agent at session start. Two agents editing `TASKS.md` without pulling between them = lost progress-log entries. Frequent commit/push/pull collapses that risk to near-zero.

## Trusted collaborators (direct-commit + deploy access)

Some contributors are granted Write access on the repo by the maintainer. If you're one of them, the rules differ:

- **Direct commits to `main` are allowed.** No PR required for your own work. Open a PR only if you want a second pair of eyes — never as a procedural hoop.
- **You can run `./scripts/deploy-site.sh`** to publish to `gh-pages`. External contributors cannot.
- **The cadence rule above (`git pull --rebase` first, small commits, push immediately) is mandatory, not optional.** Direct push without pulling is the fastest way to clobber another collaborator's work, especially on `TASKS.md` and the `.claude/` coordination files.
- **Coordinate before deploying.** See "Deploy + DB coordination" below — `deploy-site.sh` publishes whatever's in your local `phase0.sqlite`, so two collaborators deploying from different DB states will publish different leaderboard numbers.

The current trusted-collaborator set lives in the repo's GitHub Collaborators settings (Settings → Collaborators), not in this file — that's the source of truth and what GitHub actually enforces.

#### How the maintainer grants trusted-collaborator access

```bash
# Replace <USERNAME> with the collaborator's GitHub login
gh api -X PUT "repos/devkurtc/wks-social-tennis-rankings-malta/collaborators/<USERNAME>" \
    -F permission=push
```

`push` (Write) is the correct role and is sufficient for the full workflow: direct commits to `main`, force-pushes to `gh-pages`, running `scripts/deploy-site.sh`. **Do not grant `admin`** unless the person is a co-owner — admin includes settings, branch-protection, repo-deletion. **`maintain` is NOT a valid role on personal-account repos** (only on organization-owned repos); the API silently 204s on `permission=maintain` without changing anything, so don't waste time trying it. If you ever need a "trusted but not admin" tier richer than `write`, the workaround is to convert the repo to be owned by an org.

The deploy script (`scripts/deploy-site.sh`) is permission-aware: it probes the caller's admin status and skips the Pages-config refresh call cleanly when the deployer isn't admin. So a `write`-only collaborator gets a clean deploy log with no warnings — Pages is already enabled and the config refresh is a no-op anyway.

### Deploy + DB coordination (trusted collaborators read this)

`scripts/deploy-site.sh` regenerates `site/` from **the local `phase0.sqlite` on the deployer's machine** and force-pushes. So if two collaborators deploy from their own machines, the published leaderboard depends on whose DB was loaded last.

`phase0.sqlite` itself is gitignored (it's a 14MB binary regenerated from `_DATA_/`). The committed identity-resolution sources (`scripts/phase0/manual_aliases.json`, `scripts/phase0/known_distinct.json`) make a fresh re-ingest deterministic. But any interactive identity-resolution work done via `cli.py review` lives only in your DB until you bake it into `manual_aliases.json`.

**Before deploying, run a clean re-ingest** so your local DB matches what any other collaborator would produce:

```bash
rm phase0.sqlite
python3 -m scripts.phase0.cli ingest
python3 -m scripts.phase0.cli rate
./scripts/deploy-site.sh
```

If you have interactive identity-resolution decisions in your DB that aren't yet in `manual_aliases.json`, commit them (or discard them) before re-ingesting. Don't deploy a DB state that nobody else can reproduce.

## Code style

| Layer | Tool | Rule |
|---|---|---|
| Python | `black` + `ruff` | Default config; no exceptions baked in. |
| Python types | type hints on public functions | Don't `# type: ignore` without a `# Why:` comment. |
| Tests | `pytest` | Test names should describe the behaviour, not the function (`test_merged_player_resolves_to_canonical_id`, not `test_get_or_create_player`). |
| SQL | plain SQL files | No ORM. Migrations land in Phase 1 with their own scheme. |
| TypeScript (Phase 1+) | `biome` (or prettier+eslint) | `strict: true`. No `any` without a `// Why:` comment. |

Comments: default to writing none. Only add a `# Why:` comment if the *why* is non-obvious — a hidden constraint, subtle invariant, workaround for a specific bug. Never explain *what* the code does; well-named identifiers handle that.

## What kinds of contributions are welcome

- **New parsers** for additional tournament templates. Use the `tennis-data-explorer` agent (or `/inspect-xlsx` skill) to spec the file, then `parser-implementer` to write it. See `scripts/phase0/parser_spec_*.md` for examples of the spec format.
- **New rating models.** The schema is already model-agnostic; add a sibling `rating_<name>.py` with `recompute_all(conn, model_name=...)` and a unique `model_name` constant. See `prompt-for-df-agent.md` for a worked example. (A reusable `/add-rating-model` skill is on the roadmap.)
- **Identity-resolution improvements** — better fuzzy matching, surname-change handling, captain-class signal weighting. See `scripts/phase0/eval_identity.py` for the existing scoring harness.
- **Site UX** — leaderboard filters, accessibility, mobile, additional explainer pages.
- **Multi-club onboarding** — adding a new club's data to `_DATA_/` (with permission!) and any parser tweaks the new club's templates need.

## What's out of scope right now

- **Stack changes** — Postgres / Next.js / Redis / MinIO are locked in [`PLAN.md`](PLAN.md) §5. Phase 0 stays on SQLite + static site by design.
- **A user-accounts system** — Phase 1+. Authentication and permissions are tracked but not yet built.
- **Real-time match entry** — current model is "captain uploads an Excel, we parse it". Live entry is a Phase 2+ topic.
- **Mobile app** — not on the roadmap. The web app is mobile-friendly.

## Questions

Open a GitHub issue. There's no Slack, no Discord, no mailing list yet — by design until the project grows enough to need them.

## License

By contributing, you agree that your contributions will be licensed under [AGPL-3.0](LICENSE), the project's license. AGPL means anyone can use, modify, and self-host the software, but if they run a modified version as a network service they have to publish their source. This is intentional and not negotiable.
