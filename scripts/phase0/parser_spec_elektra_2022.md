# Parser spec — `Draws and Results Elektra Mixed Doubles 2022.xlsx`

## File(s) analyzed

- `_DATA_/VLTC/Draws and Results Elektra Mixed Doubles 2022.xlsx`

## Format classification

**Cross-tab matrix (round-robin results table).** Confidence: **high**.

Each Division sheet is a square round-robin matrix:
- Row 4 holds the header column-numbers `1.0, 2.0, ..., N.0` plus `'TOTAL POINTS'`.
- Rows 5..(4+N) are one per pair: col 1 = pair rank (`1.0`..`N.0`), col 2 = pair string `'LastA FirstA/LastB FirstB'`, cols 3..(2+N) = the result cell of "this pair vs opponent of rank (col-2)" as a free-text score string.
- The diagonal (col == row - 2) is empty (no self-match).
- Cells above & below the diagonal are reciprocal (the same match recorded from each side's perspective). To insert each match exactly once, the parser walks **only the upper triangle** (col > row - 2).
- Below the matrix: lines like `'Winner: ...'` / `'Runner Up: ...'` and (for Div 5 A/B only) `'Final: A/B vs C/D 1-6, 6-7'`.

Format string for the schema: `tournaments.format = 'doubles_division'`. Division strings come from the cell at `[3, 1]` (`'Division 1'`, `'Division 5 - Group A'`, ...) or fall back to the sheet name.

## Sheet map

| Sheet | Role | Notes |
|---|---|---|
| `Div 1` | Matrix, 5 pairs | 10 distinct matches |
| `Div 2` | Matrix, 6 pairs | 15 distinct matches |
| `Div 3` | Matrix, 6 pairs | 15 distinct matches; one walkover (`'6-0, 6-0 w/o'`) |
| `Div 4` | Matrix, 6 pairs | 15 distinct matches |
| `Div 5 A` | Matrix, 5 pairs | 10 distinct matches; row 15 holds the cross-group Final |
| `Div 5 B` | Matrix, 5 pairs | 10 distinct matches; row 15 holds the same Final string (DUPLICATE) |

Total expected unique matches: **75 round-robin + 1 final = 76**.

## Extraction recipe

| Field | Sheet | Row anchor | Col anchor | Notes |
|---|---|---|---|---|
| Tournament name | any | row 1 | col 1 | `'Elektra Mixed Doubles 2022'` |
| Division label | any | row 3 | col 1 | e.g. `'Division 1 '`, `'Division 5 - Group A'`. Strip trailing whitespace. |
| Roster column-headers | any | row 4 | cols 3..(max-1) | numeric `1.0..N.0`. Used to discover N and validate matrix width. |
| Pair name (rank R) | any | row `4+R` | col 2 | full pair string with `'/'` separator. |
| Result cell (R vs S) | any | row `4+R` | col `2+S` | only used when S > R (upper triangle); reciprocal cell skipped. |
| TOTAL POINTS | any | row `4+R` | col `3+N` | sanity sum; not stored per match. |
| Cross-group Final | `Div 5 A`, `Div 5 B` | row 15 | col 2 | one shared string `'Final: A/B vs C/D score'`. Parse from `Div 5 A` only to dedupe. |

## Score-string grammar

All score strings parsed by a single regex-driven tokenizer with the following accepted forms (case-insensitive, NBSP-tolerant, newline-tolerant):

| Form | Example | Sets emitted |
|---|---|---|
| 2 sets clean | `'7-5, 6-0'` / `'1-6,3-6'` / `'6-2; 4-6 TB 10-8'` | set 1, set 2 |
| 2 sets + super-tiebreak (`TB`) | `'2-6, 6-0 TB 10-6'` | set 1, set 2, super-tb (`was_tiebreak=1`) |
| 2 sets + super-tiebreak (`T/B`) | `'2-6, 6-7 T/B 9-11'` | set 1, set 2, super-tb |
| 2 sets + bare super-tiebreak | `'6-4, 3-6 4-10'` | set 1, set 2, super-tb (third pair detected as `\d+-\d+` after the second set) |
| Walkover marker | `'6-0, 6-0 w/o'` / `'0-6, 0-6 w/o'` | set 1, set 2; match flagged `walkover=1`. |
| Trailing whitespace / `\n` | `'1-6, 6-4 TB 10-4\n'` | sets emitted as if without it |
| Embedded newline before TB | `'6-3, 4-6\nTB 10-6'` | normalized — newlines collapse to spaces before parsing |
| Empty/None | (diagonal cells, also unfilled) | match skipped — not inserted |

**Separators tolerated between sets**: `,` `;` newline. Comma-without-space (`'1-6,3-6'`) is accepted.

**Match decision rule** (PLAN.md §5.2 follows the same rule for SE/Mixed parsers):
1. Count regular sets (sets 1 + 2). Side with more wins.
2. If tied 1-1 in regular sets and a super-tiebreak set is present, the super-tb winner takes the match.
3. If tied 1-1 with no super-tb, the match is recorded but `won = 0` for both sides (rating engine should skip pathological ties).

This matches the convention already used by `sports_experience_2025._insert_match` and `mixed_doubles._insert_match`. The parser reuses `mixed_doubles._insert_match` so behavior is consistent.

## Schema mapping

| Extracted field | Target table.column | Transform |
|---|---|---|
| Tournament name from `[1,1]` | `tournaments.name` | strip / NBSP-clean |
| Year `2022` | `tournaments.year` | from filename (`r'\b(20\d{2})\b'`) |
| `'doubles_division'` | `tournaments.format` | constant |
| Sha256 of file | `source_files.sha256` | hex |
| Filename basename | `source_files.original_filename` | |
| Division label | `matches.division` | from `[3,1]` cell (or sheet name fallback) |
| `'final'` for the cross-group final | `matches.round` | constant for the `Div 5 A` row-15 final, NULL for round-robin matches |
| Pair string (raw) | passed to `players.get_or_create_player` after `_split_pair` | no normalization here |
| Set games (regular) | `match_set_scores.side_a_games`, `side_b_games`, `was_tiebreak` (set if either side scored 7) | `was_tiebreak` for first/second set when 7-X or X-7 |
| Super-tb games | `match_set_scores` (next set_number, `was_tiebreak=1`) | |
| Walkover marker | `matches.walkover = 1` | when `w/o` token present |

## Edge cases to handle

- **Diagonal cells** (`row - 4 == col - 2`) — always None; skip.
- **Reciprocal cells** — process only `col - 2 > row - 4` (upper triangle).
- **Cross-group Final on `Div 5 A` and `Div 5 B`** — same string, in-row 15, col 2. Process from `Div 5 A` only; skip when sheet is `Div 5 B`. Detected by string prefix `'Final:'` (case-insensitive).
- **Walkover** — set `matches.walkover = 1`. Score still recorded (typically `'6-0, 6-0 w/o'`).
- **Trailing newline / NBSP / extra whitespace inside score strings** — normalized before regex.
- **Semicolon set-separator** — `'6-2; 4-6 TB 10-8'` accepted same as comma.
- **Comma-without-space** — `'1-6,3-6'` accepted.
- **Bare super-tb (no `TB` label)** — `'6-4, 3-6 4-10'` recognized when the third token after the second set is `\d{1,2}-\d{1,2}`. Logged to stderr if heuristic ambiguous.
- **Empty cells in matchup** — match not yet played; skip and log to stderr (counted in `quality_report.unparsed_or_empty`).
- **Unparseable score string** — log to stderr; cell skipped (no match inserted).
- **`Winner:` / `Runner Up:` lines** — never in the matrix region (rows 5..4+N, cols 3..2+N), so they don't interfere.

## Suggested parser test cases

1. **`Div 1` row 5 col 4** (rank 1 vs rank 2): Marc Vella Bonnici/Martina Cuschieri vs Jean Carl Azzopardi/Erika Azzopardi → `'7-5, 6-0'` → 2 sets, A wins 2-0, no super-tb.
2. **`Div 1` row 6 col 6** (rank 2 vs rank 4): Jean Carl Azzopardi/Erika Azzopardi vs Trevor Rutter/Alison Muscat → `'2-6, 6-4 TB 8-10'` → 1-1 in regular sets, super-tb 8-10 → side B wins.
3. **`Div 3` row 5 col 4** (rank 1 vs rank 2): Mavric Sawyer/Alexia Gouder vs Manuel Bonello/Josette D'Alessandro → `'6-0, 6-0 w/o'` → walkover, A wins by walkover, `matches.walkover=1`.
4. **`Div 4` row 8 col 4** (rank 4 vs rank 2): Alain Frendo/Monique Attard vs Lydon Vella/Celeste Zammit Marquette → `'2-6, 6-2 TB 13-11'` → super-tb decides, side A wins.
5. **`Div 5 A` row 15 col 2** Final: Denis Caruana/Jennifer Mifsud vs Clint Agius/Laureen Agius `'1-6, 6-7'` → 0-2 regular sets, side B wins; division `'Division 5'`, round `'final'`.
6. **Smoke**: total active matches >= 76 (75 RR + 1 final). No division-group has 0 matches.
7. **Reprocess / supersede**: second parse on same file creates a NEW `ingestion_runs` row, supersedes prior matches, reuses `source_files`.
