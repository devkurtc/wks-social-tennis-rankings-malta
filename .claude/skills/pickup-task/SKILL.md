---
name: pickup-task
description: Pick up a task from TASKS.md to start working on. With no argument, finds the next task whose status is `todo` and whose dependencies are all `done`. With a task ID argument (e.g. `T-P0-002`), picks that specific task. Sets the task's status to `in-progress`, appends the standard "picked up" progress-log line with timestamp and actor, updates the "Current focus" table, and prints the full task body so you can act on it. Use this whenever you start work on the project.
---

# pickup-task

When invoked:

1. **Parse arguments.**
   - If a task ID is given (e.g. `T-P0-002`), pick that specific task.
   - Otherwise, read `TASKS.md` and find the first task whose status is `todo` AND whose every `Depends on` task is marked `done`. Prefer the lowest-numbered task ID in the lowest-numbered phase.

2. **Validate** the chosen task can be picked up:
   - Status must currently be `todo` (not `in-progress`, `blocked`, `done`, `deferred`)
   - Every `Depends on` task ID must be marked `done` in TASKS.md
   - If either check fails, abort and tell the user exactly why. Don't silently pick a different task.

3. **Edit TASKS.md** to:
   - Change `**Status:** \`todo\`` to `**Status:** \`in-progress\`` for the chosen task
   - Append a new line to the task's `**Progress log:**` section:
     `- YYYY-MM-DD HH:MM — <actor> — picked up; plan: <one-line approach>`
     - `<actor>` is the running model in the form `Claude (Opus 4.7)` (or whichever model is active). Read it from the system context.
     - `<one-line approach>` is your own one-sentence summary of how you plan to tackle the task — generated from the task body, not boilerplate.
   - Update the `## Current focus` table at the top of `TASKS.md`:
     - Move the task ID from `up next (todo, deps satisfied)` to `in-progress`
     - Re-evaluate which other tasks are now `up next` (their deps may have changed if a sibling task was completed earlier in the session)

4. **Print the full task body** in the conversation so the agent can act on it. Use a clear visual separator above and below.

## Conventions

- **Date format:** `YYYY-MM-DD HH:MM` in local wall-clock time. Use `date '+%Y-%m-%d %H:%M'` via Bash if needed.
- **Append-only progress log:** never edit or delete past entries. The "picked up" line is always a new line.
- **Don't pick up across phases when prior phase is incomplete**, unless dependency check legitimately passes (rare).
- **Don't pick up a task that's already `in-progress`** — someone else (or you in a previous session) is on it. Abort and report.
- **Don't pick up a task that's `blocked`** — read its blocker note and report it.

## Examples

```
/pickup-task
→ Reads TASKS.md, finds T-P0-001 todo, no deps.
→ Edits TASKS.md: status = in-progress; appends progress note:
   "- 2026-04-25 21:15 — Claude (Opus 4.7) — picked up; plan: scaffold
    scripts/phase0/, write requirements-phase0.txt with openpyxl +
    openskill + scipy, add a stub argparse CLI with four subcommands"
→ Prints the T-P0-001 task body
```

```
/pickup-task T-P0-006
→ Validates T-P0-006 is todo and T-P0-001, T-P0-002, T-P0-004 are all done.
→ If any dep is not done, aborts: "Cannot pick up T-P0-006: depends on
   T-P0-004 which is currently `in-progress`."
```
