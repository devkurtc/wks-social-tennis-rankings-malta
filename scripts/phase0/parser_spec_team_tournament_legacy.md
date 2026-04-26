# Parser specification — VLTC Team-Tournament (legacy "DAY N" template)

## File(s) analyzed

- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/PKF  Team Tournament 2023.xlsx`
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/ PKF  Team Tournament 2024.xlsx` (note leading space)
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/TENNIS TRADE  Team Tournament 2023.xlsx`
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/SAN MICHEL TEAM TOURNAMENT 2023.xlsx` (single `MATCH RESULTS` sheet)
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/SAN MICHEL TEAM TOURNAMENT 2025.xlsx`
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/ Team Tournament 2024.xlsx` (San Michel 2024 — note leading space; identified by [1,6] header)

These are all **older** team-tournament templates flagged as NOT covered by `parser_spec_team_tournament.md`.

## Format classification

**Format:** VLTC team tournament, legacy single-sheet "DAY" layout. Each "encounter" (TEAM X vs TEAM Y rubber-stack) is a self-contained 21-row block. Each rubber occupies 2 rows (set-1 + set-2 rows). Date is recorded **per-rubber** in column 2.

**Confidence:** high (5 of 6 files use multi-sheet `Day N` layout; 1 file — SAN MICHEL 2023 — stacks all encounters on a single `MATCH RESULTS` sheet; same per-encounter shape).

## Sheet map

| Sheet pattern | Role | Notes |
|---|---|---|
| `Day 1`..`Day N`, `DAY 1`..`DAY N` | Encounter blocks | Multiple encounters stacked vertically (one per court for that day) |
| `Semi Final`, `SEMI FINAL` | Encounter blocks | Same shape |
| `Final`, `FINAL` | Encounter blocks | Same shape |
| `MATCH RESULTS` (San Michel 2023 only) | All encounters in one sheet | DAY N header in col 1 demarcates encounters |
| `Leaderboard`, `LEADERBOARD`, `Daily Results`, `Team Formation`, `ENCOUNTERS PLAYED`, `DATA`, `RULES` | Computed/reference | Ignored by parser |

## Encounter-block layout (21 rows)

Anchored at `enc_row` (row of the `DAY N` / `FINAL` / `SEMI FINAL` label in col 1):

```
Row enc_row+0   col 1  : 'DAY N' / 'FINAL' / 'SEMI FINAL'   col 14 : 'BALLS' (sometimes)
Row enc_row+1   col 6  : 'TEAM A …'   col 7 : 'VS'   col 8 : 'TEAM B …'
Row enc_row+2   col 1  : 'DAY'  col 2 : 'DATE'  col 3 : 'CAT'  col 4 : 'CRT'
                col 5  : 'TIME' col 6 : 'PLAYERS' col 8 : 'PLAYERS' col 10 : 'RESULTS'
Row enc_row+3   col 10 : 'GAMES'  col 12 : 'SETS'
Rows enc_row+4..enc_row+19 : 8 × rubber-blocks of 2 rows each (some may be empty)
Row enc_row+20  col 1  : 'NOTES'   col 10..13 : 'TEAM' (totals header)
Row enc_row+21  col 10..13 : team total games / sets
```

But for legacy DAY-N sheets, the encounter actually starts at sheet row 5 (DAY label), so the FIRST encounter is at `enc_row=5` and subsequent encounters at `enc_row=5+22=27` … actually let's re-anchor: from observation, encounters occur every 23 rows in the multi-sheet DAY layout (rows 5, 28, 51, …) and every 21 rows in the single-sheet MATCH RESULTS layout (rows 7, 28, 49, 70, …). Use scan-for-DAY-label rather than fixed-stride.

### Rubber-block layout (2 rows; rubber `i` of 8 starts at `r = enc_row + 4 + 2*i`)

| Row | Col 1 | Col 2 | Col 3 | Col 4 | Col 5 | Col 6 | Col 7 | Col 8 | Col 9 | Col 10 | Col 11 | Col 12 | Col 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `r`   | day-of-week | date | CAT (rubber type) | CRT (court#) | TIME | side A player 1 | `'VS'`? | side B player 1 | `'SET 1'` | A games set 1 | B games set 1 | A sets won (0/1/2) | B sets won (0/1/2) |
| `r+1` | (blank) | (blank) | (blank) | (blank) | (blank) | side A player 2 | (blank) | side B player 2 | `'SET 2'` | A games set 2 | B games set 2 | (blank) | (blank) |

**Singles rubber:** `[r,3]='SINGLES'` and `[r+1,6]` / `[r+1,8]` are blank — no second player.

**Notes:**
- Col 9 `'SET 1'` / `'SET 2'` is the discriminator — rubber row r has 'SET 1' if a real rubber.
- Col 12 / Col 13 may carry per-rubber sets-won (0 or 1 for each side, summing to the result of that rubber). The parser computes sets_won itself — col 12/13 are confirmation only.
- Col 14 sometimes carries free-text: `' '`, super-tiebreak score (e.g. `6.0` paired with `5.0` on the next row), or walkover annotation. Tennis Trade 2023 row 13 has `'5.0'` at col 14 implying tiebreak details. Parser uses col 14 as a soft hint only when it is numeric.
- **Walkover detection:** check NOTES row `[enc_row+20, 2]` for the substring `walkover` (case-insensitive), or check col 14 of the rubber row for `'w/o'`. PKF 2023 row 25 has `[25,2]='MEN B 1st set walkover against Martinelli'` — applies to that encounter's MEN B rubber. As a Phase-0 trade-off, we set `matches.walkover=1` if `[enc_row+20, 2]` mentions walkover AND we identify a rubber with extreme scores (e.g. 0-12). Otherwise we just store the recorded scores.

### Encounter header parsing

- `[enc_row+1, 6]` → side-A team string e.g. `'TEAM A MARTINELLI JONATHAN'`. Strip `'TEAM <letter>'` prefix to get the captain name; the team letter is inferred but unused (no schema column).
- `[enc_row+1, 8]` → side-B team string. Same handling.
- These are NOT inserted as players (they are the captain references; the actual player names per rubber are in col 6/8 of each rubber row).

## Extraction recipe

| Field | Source | Notes |
|---|---|---|
| `tournament.name` | `[1,3]`/`[1,4]`/`[1,6]` of any Day sheet | E.g. `'PKF TEAM TOURNAMENT 2023'`, `'SAN MICHEL TEAM TOURNAMENT 2024'` |
| `tournament.year` | Filename or first-found year in title | Parse `\b(20\d{2})\b` from filename; for the bare ` Team Tournament 2024.xlsx`, derive from `[1,6]` |
| `tournament.format` | constant | `'doubles_team'` |
| Encounter anchors per sheet | Scan col 1 for cell starting with `'DAY '` (case-insensitive) or equal to `'FINAL'` / `'SEMI FINAL'` | First occurrence at row 5 (multi-sheet) or row 7 (single-sheet MATCH RESULTS); subsequent every ~21–23 rows |
| Rubber anchors within encounter | Iterate rubber slots 0..7 at `r = enc_row + 4 + 2*i` | Skip if `[r,9]` (SET 1 marker) is missing AND `[r,3]` is blank |
| Rubber type (`matches.division`) | `[r,3]` | E.g. `'MEN A'`, `'LAD A'`, `'LDY''S A'`, `'LAD A1'`, `'MIXED B/A'`, `'SINGLES'` — normalized (see below) |
| Side A player 1 | `[r,6]` | Strip whitespace + `\xa0` (NBSP) |
| Side A player 2 | `[r+1,6]` | None for SINGLES |
| Side B player 1 | `[r,8]` | Strip whitespace + NBSP |
| Side B player 2 | `[r+1,8]` | None for SINGLES |
| Set 1 score | `[r,10]` and `[r,11]` | int, float→int |
| Set 2 score | `[r+1,10]` and `[r+1,11]` | int, float→int |
| Date | `[r,2]` | `datetime.datetime` or `datetime.date` from openpyxl; parser converts to ISO `YYYY-MM-DD`; **per-rubber date** (not per-sheet) — supports cross-day encounters |
| `matches.round` | derived from sheet name / encounter label | `'day N'`, `'semi-final'`, `'final'`. For MATCH RESULTS single-sheet, derive from the `'DAY N'` label in col 1 of each encounter |
| `matches.walkover` | NOTES row scan | Set to 1 if `[enc_row+20, 2]` contains `'walkover'` AND the rubber's recorded score is one-sided (sum of any side's games >= 12 vs sum of opposite ≤ 1). Otherwise 0 |

### Division (CAT) normalization

Map raw labels to the same canonical form used by the modern team-tournament parser so they integrate with the existing tier system in `rating.py`:

| Raw label patterns (case-insensitive) | Canonical |
|---|---|
| `MEN A`, `MEN A1`, `MEN A2`, `Men A` | `Men A` |
| `MEN B`, `MEN B1`, `MEN B2`, `Men B` | `Men B` |
| `MEN C`, `MEN C1`, `MEN C2`, `Men C` | `Men C` |
| `MEN D`, `Men D` | `Men D` |
| `LAD A`, `LDY'S A`, `LDYS' A`, `LAD A1`, `LAD A2`, `Ladies A` | `Lad A` |
| `LAD B`, `LDY'S B`, `LDYS' B`, `LAD B1`, `LAD B2`, `Ladies B` | `Lad B` |
| `LAD C`, `LDY'S C`, `LDYS' C`, `Ladies C` | `Lad C` |
| `LAD D`, `LDY'S D`, `LDYS' D` | `Lad D` |
| `MIXED B/A`, `MIXED C/B`, `MIXED A/B`, etc. | passed through with whitespace normalized (e.g. `Mixed B/A`) |
| `SINGLES` | `Singles` |

The sub-tier suffix (`A1`, `A2`, `B1`, etc.) seen in TENNIS TRADE 2023 is collapsed because rating.py only knows whole tiers (A, B, C, D). The sub-tier distinction was a one-off scheduling artifact and has no rating impact.

### Gender derivation

Same as modern parser: `Men*` → `'M'`, `Lad*` / `Ldy's*` / `Ldys'*` → `'F'`, `Mixed*` / `Singles*` → `NULL`.

## Schema mapping

| Extracted field | Target table.column | Transform |
|---|---|---|
| Workbook filename | `source_files.original_filename` | as-is |
| Workbook SHA-256 | `source_files.sha256` | hash bytes |
| Tournament title | `tournaments.name` | from `[1,3]`/`[1,4]`/`[1,6]` first non-empty |
| Year | `tournaments.year` | int from filename or title |
| `'doubles_team'` | `tournaments.format` | literal |
| Per-rubber date | `matches.played_on` | ISO `YYYY-MM-DD` |
| `'doubles'` or `'singles'` | `matches.match_type` | derived from rubber type or null player2 |
| Normalized CAT label | `matches.division` | per table above |
| Sheet → round | `matches.round` | `'day N'`, `'semi-final'`, `'final'` |
| Side A player 1 | `match_sides.player1_id` (side='A') | `get_or_create_player` |
| Side A player 2 | `match_sides.player2_id` (side='A') | `get_or_create_player` (NULL for singles) |
| Side B player 1 | `match_sides.player1_id` (side='B') | `get_or_create_player` |
| Side B player 2 | `match_sides.player2_id` (side='B') | `get_or_create_player` (NULL for singles) |
| Per-set games | `match_set_scores.{side_a,side_b}_games` | per recipe |
| Sum of per-set games per side | `match_sides.games_won` | sum |
| Sets won per side | `match_sides.sets_won` | count |
| Side won (boolean) | `match_sides.won` | derived |
| Walkover flag | `matches.walkover` | per recipe |
| `ingestion_runs.id` of this load | `matches.ingestion_run_id` | populated by parser |

## Edge cases to handle

1. **Date is per-rubber, not per-sheet/encounter.** TENNIS TRADE 2023 Day 1 has rubbers played on `2023-10-19` (Thursday) and `2023-10-21` (Saturday) within the same encounter. Use `[r,2]` for each rubber. If `[r,2]` is missing on a SET-1 row, try `[r+1,2]` or fall back to the previous rubber's date in the same encounter.

2. **NBSP (`\xa0`) suffixes on player names.** Common on SAN MICHEL 2023 — names like `'AZZOPARDI ERIKA\xa0'`. Strip via `str.strip()` (Python's strip handles NBSP).

3. **Sub-tier categories.** Tennis Trade 2023 has `LAD A1` / `LAD A2` (split-A category for the same day's encounter). Collapsed to `Lad A` for rating compatibility.

4. **CAPS vs Title-case.** All legacy files use SCREAMING CAPS; PKF 2024 uses Title Case (`Cassar Tanya`). Parser does NOT correct — `players.normalize_name` preserves casing per its contract; case-only duplicates are merged via `players.merge_case_duplicates`.

5. **Empty rubber slots.** Encounters frequently have only 6-7 rubbers (not always 8). Slot is empty when `[r,9]` is not `'SET 1'`. Skip silently.

6. **Singles rubbers.** `[r,3]='SINGLES'`. Only player at `[r,6]` and `[r,8]`; `[r+1,6]` and `[r+1,8]` empty. `match_sides.player2_id` = NULL. `match_type='singles'`.

7. **Walkover.** PKF 2023 Day 1 NOTES row `[25,2]='MEN B 1st set walkover against Martinelli'`. The MEN B rubber's set 1 is `0-6`. Detection heuristic: NOTES row contains "walkover" AND rubber score has a very lopsided set. Conservative: only set walkover=1 if both NOTES mentions walkover AND we can find a CAT match in NOTES text. Otherwise leave 0 — the rating engine still handles lopsided scores reasonably.

8. **SAN MICHEL 2023 single sheet.** The single `MATCH RESULTS` sheet contains all encounters (rows 7–~400). Round label is the `'DAY N'` text from col 1 at the encounter's anchor row.

9. **Date stored as `datetime.datetime`.** openpyxl returns `datetime.datetime` for date-typed cells. Convert via `.date().isoformat()`.

10. **Trailing-space team labels.** `'TEAM A MARTINELLI JONATHAN'` etc. — only the CAT/player rows matter; the team label is informational and not stored.

11. **Final/Semi Final.** Some files (e.g. PKF 2024) have separate `Final` and `Semi Final` sheets; San Michel 2023 has them inline in MATCH RESULTS. Handle uniformly.

12. **Tournament name across files.** PKF files have `[1,4]='PKF TEAM TOURNAMENT 2023'` or `[1,3]='PKF TEAM TOURNAMENT 2024'`; SAN MICHEL has `[1,4]='SAN MICHEL TEAM TOURNAMENT 2025'`; the bare `Team Tournament 2024.xlsx` has `[1,6]='SAN MICHEL TEAM TOURNAMENT 2024'`. Try `[1,3]`, `[1,4]`, `[1,5]`, `[1,6]` — use the first non-empty.

13. **Multiple encounters per Day sheet.** PKF/Tennis Trade Day-N sheets typically have 3 encounters (~3 courts × 1 day-set), starting at row 5, 28, 51. Detection: scan col 1 for cells starting with the same `'DAY N'` text or `'FINAL'`/`'SEMI FINAL'`. The label repeats once per encounter on the same sheet.

14. **Stale formula cells.** PKF 2023 has `[1,1]='#REF!'` from a broken formula. Ignore.

15. **`[r,7]` may or may not contain `'VS'`.** Tennis Trade 2023 Day 1 has it; San Michel 2023 has it. Don't depend on it.

## Suggested parser test cases

### Test 1 — PKF 2023 Day 1 first encounter, MEN B rubber (walkover scenario)

- **File:** `PKF  Team Tournament 2023.xlsx`, sheet `Day 1`, encounter at row 5, rubber at row 9.
- **Expected:**
  - `matches.played_on = '2023-07-04'`, `matches.division = 'Men B'`, `matches.round = 'day 1'`, `matches.match_type = 'doubles'`.
  - Side A: `'MARTINELLI JONATHAN'`, `'MARCUS GIO'`. Side B: `'CANONCE CHI CHI'`, `'PACE GABRIEL'`.
  - Set 1: A=0, B=6. Set 2: A=3, B=6. (Note `'MEN B 1st set walkover against Martinelli'` in NOTES row 25 — walkover=1 acceptable.)
  - `match_sides[B].sets_won = 2, games_won = 12, won = TRUE`.
  - Players inserted with gender='M'.

### Test 2 — PKF 2023 Day 1 first encounter, LAD A rubber (clean 2-0)

- **File:** `PKF  Team Tournament 2023.xlsx`, sheet `Day 1`, rubber at row 11.
- **Expected:**
  - `matches.played_on = '2023-07-04'`, `matches.division = 'Lad A'`, `matches.round = 'day 1'`.
  - Side A: `'AZZOPARDI ERIKA'`, `'BONETT CHRISTINA'`. Side B: `'MANGION ANNEMARIE'`, `'MAGRI LUCIENNE'`.
  - Set 1: 6-4. Set 2: 6-1.
  - `match_sides[A].sets_won = 2, games_won = 12, won = TRUE`.
  - Players inserted with gender='F'.

### Test 3 — PKF 2023 Day 1, SINGLES rubber

- **File:** `PKF  Team Tournament 2023.xlsx`, sheet `Day 1`, encounter at row 5 area, look for SINGLES rubber (Thursday 2023-07-06 row 19).
- **Expected:**
  - `matches.division = 'Singles'`, `matches.match_type = 'singles'`, `played_on = '2023-07-06'`.
  - Side A player1: `'RUTTER TREVOR'`, player2: NULL. Side B player1: `'AZZOPARDI JEAN KARL'`, player2: NULL.
  - Set 1: 4-6, Set 2: 7-6.
  - `match_sides[A].sets_won = 1, sets_won_b = 1, games_won_a = 11, games_won_b = 12`.

### Test 4 — Tennis Trade 2023 sub-tier collapse (LAD A1 / LAD A2 → Lad A)

- **File:** `TENNIS TRADE  Team Tournament 2023.xlsx`, sheet `Day 1`, rubbers at rows 9 (LAD A1) and 15 (LAD A2).
- **Expected:**
  - Both rubbers are inserted with `matches.division = 'Lad A'`.
  - Row 9: `played_on = '2023-10-19'`, side A `'FENECH ROBERTA'+'ABELA NATALYA'`, side B `'AZZOPARDI ERIKA'+'ZAMMIT CIANTAR NAOMI'`. Sets 2-6, 6-7.
  - Row 15: `played_on = '2023-10-21'`, side A `'ABELA NATALYA'+'FAVA ANNA'`, side B `'BONETT CHRISTINA'+'JULIE SPITERI'`. Sets 5-7, 6-3.

### Test 5 — SAN MICHEL 2023 single MATCH RESULTS sheet, encounter 2

- **File:** `SAN MICHEL TEAM TOURNAMENT 2023.xlsx`, sheet `MATCH RESULTS`, encounter at row 28 (TEAM C vs TEAM D).
- **Expected:**
  - First rubber at row 32 (LDY'S B): `matches.division = 'Lad B'`, `played_on = '2023-03-23'`.
  - Side A: `'CASSAR TANYA'`, `'ABELA ANNABELLE'`. Side B: `'MICALLEF YLENIA'`, `'BUHAGIAR DORIANNE'`.
  - Sets 6-4, 3-6 → 1-1 set tie, no super-tiebreak → won_a = won_b = 0.

### Test 6 — Total match count sanity, PKF 2024

- **File:** `PKF  Team Tournament 2024.xlsx` (with leading space).
- After parsing, expect `matches` row count >= 100 (10 days × ~3 encounters × ~6 rubbers = ~180 plausible).

---

## Summary stats (sanity)

| File | Sheets with rubbers | Expected rubber count |
|---|---|---|
| PKF Team Tournament 2023.xlsx | Day 1-10 + Semi Final + Final | ~150-200 |
| PKF Team Tournament 2024.xlsx | Day 1-10 + Semi Final + Final | ~150-200 |
| TENNIS TRADE Team Tournament 2023.xlsx | Day 1-6 + Final | ~100-150 |
| SAN MICHEL TEAM TOURNAMENT 2023.xlsx | MATCH RESULTS (single sheet) | ~150-200 |
| SAN MICHEL TEAM TOURNAMENT 2025.xlsx | DAY 1-5 + SEMI FINAL + FINAL | ~100-150 |
| Team Tournament 2024.xlsx (San Michel 2024) | Day 1-10 + Semi Final + Final | ~150-200 |
