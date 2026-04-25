---
name: log-progress
description: Append a timestamped progress-log line to a TASKS.md task without changing its status. Use whenever you commit, hit a snag, change direction, or want to record context for the next agent or your future self. Append-only — never edits past entries.
---

# log-progress

When invoked with `<task-id> <note>`:

1. Find the task block in `TASKS.md` matching the given task ID.
2. Append a new line to the task's `**Progress log:**` section:
   `- YYYY-MM-DD HH:MM — <actor> — <note>`
   - `<actor>` is the running model (e.g. `Claude (Opus 4.7)`). Read from system context.
   - `<note>` is whatever the caller passed — quoted strings preserved verbatim.
3. Don't change task status. This skill is for *progress*, not state transitions.
   - To mark `done`, use `/complete-task`.
   - To mark `blocked`, edit TASKS.md manually and explain the blocker in the same progress note.
4. Print confirmation showing the new log entry.

## When to log

Log liberally. Cheap to write, expensive to *not* write when an agent picks up your work cold:

- After every commit related to the task: include the SHA
- When you change approach mid-task ("originally planned X; switching to Y because Z")
- When you discover something the task body didn't mention (a parser quirk, a dep version conflict, a flaky test)
- Tuning decisions: parameter values you chose and why
- Hand-off context: "stopping for the day; next step is X; gotcha to watch for is Y"

## Format conventions

- **One-line summaries are fine for routine notes.** Save paragraphs for the rare deep-context note.
- **Reference commits, files, line numbers** when helpful. `committed schema.sql in abc1234` is more useful than `committed`.
- **Don't restate what the task body already says.** Log new information, not boilerplate.

## Examples

```
/log-progress T-P0-002 schema.sql draft committed in abc1234; running validation against fresh sqlite file
```

```
/log-progress T-P0-004 hit unexpected merged cells in row 12 of "Men Div 2"; using inspect-xlsx to investigate before continuing
```

```
/log-progress T-P0-006 picked tau=0.0833 monthly; weight = 1 + 0.5*tanh(games_diff/4); will validate at T-P0-009 against Kurt's intuition
```

```
/log-progress T-P0-005 Phase 0 explicitly skipping fuzzy match; logged trade-off in code comment + here. Two distinct strings = two distinct players in Phase 0.
```
