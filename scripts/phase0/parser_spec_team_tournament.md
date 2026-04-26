# Parser specification — VLTC Team-Tournament (modern "Day N" template)

## File(s) analyzed

Primary:
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/Antes Insurance Team Tournament IMO Joe results 2025.xlsx`

Cross-checked against:
- `Tennis Trade Team Tournament - Results.xlsx` (Tennis Trade 2025) — same template, single-row rubber variant (totals)
- `Results Tennis Trade Team Tournament(1).xlsx` (Tennis Trade 2024) — same template, single-row variant
- `San Michel Results 2025 Results.xlsx` — same template, two-row variant
- `San Michel Results 2026.xlsx` — same template, two-row variant
- `Antes Insurance Team Tournament  results sets .xlsx` — empty template (not parseable; same shape but no data)
- `Antes Insurance Team Tournament results with sets.xlsx` — empty template
- `Tennis Trade Team Tournament - Results(1).xlsx` — empty template
- `Results Tennis Trade Team Tournament.xlsx` — empty template

NOT covered by this spec (need a separate parser, **older "DAY" single-sheet** template):
- `TENNIS TRADE  Team Tournament 2023.xlsx`
- `SAN MICHEL TEAM TOURNAMENT 2023.xlsx` (different layout — single `MATCH RESULTS` sheet)
- `SAN MICHEL TEAM TOURNAMENT 2025.xlsx`
- `PKF  Team Tournament 2023.xlsx`
- ` PKF  Team Tournament 2024.xlsx` (note leading space in filename)

The older template uses one row per rubber with `DAY/DATE/CAT/CRT/TIME/PLAYERS/RESULTS` headers at row 7, set labels (`SET 1`, `SET 2`) in column I, players in cols 6 and 8 — fundamentally different anchor structure. Out of scope here.

## Format classification

**Format:** VLTC team tournament, rotating partners per night (rubber). Teams labeled A–F with captains; players assigned per team in `Team Selection`; matches recorded per `Day N` / `Semi Final` / `Final` sheet, multiple courts per day, multiple rubbers per court, each rubber pairing 2 individual players per side.

**Confidence:** high.

This template family always has:
- A `Team Selection` sheet (or close variant) listing 6 men teams of 9 players + 6 ladies teams of 9 players grouped by tier (A1/A2/A3/B1/B2/B3/C1/C2/C3) per team column.
- One `Encounters played` / `Encounters Played` sheet (matrix; not used by this parser).
- One `Standings` / `Leaderboard` sheet (totals; not used by this parser).
- Multiple `Day N` sheets (also `DAY N`), plus optional `Semi Final` and `Final`.
- Each Day sheet has 1+ `Court N` panels per page; each panel has its own `Time/Rubber/Team … vs Team …/Games[/Sets]` header at row 11; rubbers below in groups separated by `Total Day N A/B/...` summary rows.

## Sheet map

| Sheet | Role | Notes |
|---|---|---|
| `Team Selection` | Roster | Teams A-F captain-led; A1..A3, B1..B3, C1..C3 tiers per team. **Not required by parser** (rubbers list players individually). |
| `Encounters played` | Matrix | Computed totals; ignored. |
| `Standings` | Standings | Computed totals; ignored. |
| `Day 1` … `Day N` | Match rubbers | Primary data. N varies: Antes/Tennis Trade have 5 days, San Michel 2025/2026 have 10 days. |
| `Semi Final` | Match rubbers | Same shape as Day sheets. |
| `Final` | Match rubbers | Same shape as Day sheets. |

## Rubber-row layout (uniform across Day/Semi/Final sheets)

Anchored structure:

```
Row 6 col 3    Sheet header text containing the date(s), e.g. 'DAY 1 - 28/05/2025 & 30/05/2025'
Row 9 col 3    'Court 1' (or 'Court 2', 'Court 3', 'Court 4', etc.)
Row 11 col 3   'Time'        (header)
Row 11 col 4   'Rubber'      (header)
Row 11 col 5   'Team A: …'   (left team name)
Row 11 col 7   'vs'
Row 11 col 8   'Team C: …'   (right team name)
Row 11 col 10  'Games'
Row 11 col 12  'Sets'        (only on Sets-variant sheets; absent in single-row totals variant)
```

Rubbers begin at row 12 in spaced bands of 3 rows (12, 15, 18, 21, …). Each band contains one rubber. Court 2 panel typically at rows 40-71, Court 3 (if any) further down, etc. Detect Court panels by scanning col 3 for `'Court N'` strings; the header row is always 2 rows below `Court` label.

### Two-row variant (Antes 2025, San Michel 2025/2026)

For a rubber anchored at row `r`:

| Row | Col 3 | Col 4 | Col 5 | Col 6 | Col 7 | Col 8 | Col 9 | Col 10 | Col 11 | Col 12 | Col 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `r` | time | rubber-type | side A player 1 | side A player 2 | `'vs'` | side B player 1 | side B player 2 | set 1 A games | set 1 B games | total sets A | total sets B |
| `r+1` | (blank) | (blank) | (blank) | (blank) | (blank) | (blank) | (blank) | set 2 A games | set 2 B games | (blank) | (blank) |

Set 3 / super-tiebreak: Antes 2025 has none observed in Day sheets. Semi Final row 28 has a `T/B 6-8` annotation in col 14 of the same row as the player names — see edge cases.

### Single-row variant (Tennis Trade 2024/2025)

For a rubber anchored at row `r`:

| Row | Col 3 | Col 4 | Col 5 | Col 6 | Col 7 | Col 8 | Col 9 | Col 10 | Col 11 | Col 12 |
|---|---|---|---|---|---|---|---|---|---|---|
| `r` | time | rubber-type | side A player 1 | side A player 2 | `'vs'` | side B player 1 | side B player 2 | total games A | total games B | optional `'w/o'` annotation |

In this variant, only the *combined-games-across-the-match* number is recorded — set-by-set scores are NOT in the file. Cell `[r,12]` may contain a free-text annotation like `'w/o 0-5'` indicating walkover.

The two variants are detected per-sheet by sniffing whether rubber-row `r+1` has any numeric in col 10 or col 11. If yes → two-row variant. If no → single-row variant. (The 'Sets' header at `[11,12]` is also a reliable variant indicator: present → two-row, absent → single-row.)

## Extraction recipe

Use `openpyxl.load_workbook(path, data_only=True, read_only=False)` (need random cell access).

| Field | Source | Notes |
|---|---|---|
| `tournament.name` | Filename or `[2,3]`/`[3,3]` of any Day sheet | Filename is the most reliable across all files in family. |
| `tournament.year` | Filename | Parse the 4-digit year from the filename (e.g. `2025`, `2026`, `2024`). For Tennis Trade and San Michel that have no year in filename, use the earliest extracted match date's year. |
| `tournament.format` | constant | `'doubles_team'` |
| Per-Day-sheet date | Cell `[6,3]` (or `[5,3]`/`[6,2]`/`[5,2]` fallback) of each Day sheet | Free-text like `'DAY 1 - 28/05/2025 & 30/05/2025'`. Parse with regex `\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}`; take the FIRST date as `matches.played_on` for ALL rubbers on that sheet. |
| Court panels | Scan col 3 of each sheet for cells containing `'court'` (case-insensitive) | Each `Court N` label marks the start of a panel; rubbers begin 3 rows below the header (header is 2 rows below the Court label). |
| Match anchor rows | After locating a court panel header, iterate rows in steps of 3 starting at header_row+1 | For each row, check whether col 4 (rubber-type) is non-empty AND col 5 (player A1) non-empty AND col 8 (player B1) non-empty. If ALL absent, stop iteration for this panel. |
| Side A players | `[r,5]` and `[r,6]` | Both required; cell may be missing (singles rubber) — see edge cases. |
| Side B players | `[r,8]` and `[r,9]` | Same. |
| Set 1 score | `[r,10]` and `[r,11]` (two-row variant) | Two-row: `[r,10]/[r,11]` are set 1; `[r+1,10]/[r+1,11]` are set 2. |
| Set 2 score | `[r+1,10]` and `[r+1,11]` | Only present in two-row variant. |
| Total games (single-row) | `[r,10]` and `[r,11]` | Single-row variant only. |
| Walkover marker | `[r,12]` text containing `'w/o'`, `'w / o'`, `'wo'`, `'walkover'` | Set `matches.walkover = 1`. |
| `matches.division` | `[r,4]` (rubber-type label) | E.g. `'Men A'`, `'Men D'`, `'Lad B'`, `'Lad C'`, `'Mixed B/A'`. Stored verbatim with leading/trailing whitespace stripped. Encodes both gender and tier. |
| `matches.round` | derived from sheet name | `'day 1'..'day N'` for Day sheets, `'semi-final'` for Semi Final, `'final'` for Final. |

### Splitting and player creation

For each player cell value (e.g., `[r,5]`):

1. Strip leading/trailing whitespace.
2. Pass *verbatim* to `players.get_or_create_player(conn, raw_name, source_file_id)`.

Do NOT pre-normalize. The names contain quirky variants:
- Backtick apostrophes: `"Jesmond Pule\``", `"Twanny Pule\`"`
- Standard apostrophes: `"Jesmond Pule'"`, `"Duncan D'Alessandro"`
- Mixed casing: `"SEAN CACHIA"` (Day 2/3 Antes), `"Sean Cachia"` (Day 1)
- Trailing whitespace: `"Neville Sciriha "`, `"Spiteri Julie "`
- Pro-substitutes: `"Jade Sammut (pro) Elaine Grech"` (a single cell containing TWO names — see edge cases)

The `players.normalize_name` function handles apostrophe/whitespace normalization; CAPS vs Title-case is a Phase-1 merge problem (per `players.py` docstring) and is NOT corrected here.

### Gender derivation

From the rubber-type label `[r,4]`:

| Label prefix | Gender for both players |
|---|---|
| `Men`, `MEN` | `'M'` |
| `Lad`, `LDY`, `LDS`, `Ladies` | `'F'` |
| `Mixed`, `MIXED` | mixed — leave `players.gender = NULL`; do not infer |
| `Singles`, `SINGLES` | leave `NULL` (no useful gender signal from rubber-type alone) |

Apply the gender update only on first sight of a player (`UPDATE players SET gender = ? WHERE id = ? AND gender IS NULL`) — same convention as the SE 2025 parser.

### Score → schema mapping

#### Two-row variant

For each rubber:

- If both sets 1 and 2 are non-empty: insert `match_set_scores` rows for set 1 and set 2 with `was_tiebreak = (a==7 OR b==7)`.
- `match_sides[A].sets_won` = count of (set 1, set 2) where A's games > B's; similarly for B.
- `match_sides[A].games_won` = sum of A's per-set games (set 1 + set 2).
- `match_sides[A].won` = sets_won_A > sets_won_B.
- Walkover detected → `matches.walkover = 1` AND record set scores literally as they appear (rating engine handles the `S=0.90/0.10` dampening).

If sets are tied 1-1 with no super-tiebreak column populated, leave `won_a = won_b = 0` (rating engine will skip).

#### Single-row variant

Only total games are available — no per-set breakdown.

- Insert ONE `match_set_scores` row with `set_number = 1`, `side_a_games = total_a`, `side_b_games = total_b`, `was_tiebreak = 0`. This is a faithful representation of what's recorded — we do not invent set splits.
- `match_sides[A].sets_won = 1 if total_a > total_b else 0` (and zero if equal).
- `match_sides[A].games_won = total_a`.
- `match_sides[A].won = total_a > total_b`.

This degrades the data slightly (we lose set-level granularity) but the rating engine's universal-score function (`PLAN.md` §5.2) operates on total games anyway, so the loss is tolerable.

If the totals are equal (e.g., the Tennis Trade Day-1 Lad-A `9-9` row, which clearly represents an unfinished match), set both `won` flags to 0. Such rubbers will be filtered by the rating engine.

#### Walkover special case

If `[r,12]` contains a string starting with `'w/o'` (case-insensitive), set `matches.walkover = 1`. The rating engine reads this flag.

If `[r,12]` is `'w/o'` with no other marker, treat the games totals at face value (often `0-5` or similar — that's the score the captain has chosen to record).

## Schema mapping

| Extracted field | Target table.column | Transform |
|---|---|---|
| Workbook filename | `source_files.original_filename` | as-is |
| Workbook SHA-256 | `source_files.sha256` | hash bytes |
| Tournament title | `tournaments.name` | from filename or `[2,3]`/`[3,3]` |
| Year | `tournaments.year` | int from filename |
| `'doubles_team'` | `tournaments.format` | literal |
| First date in `[6,3]` of each Day sheet | `matches.played_on` | ISO 8601 (`YYYY-MM-DD`) |
| `'doubles'` | `matches.match_type` | literal |
| Rubber-type label (e.g. `'Men A'`) | `matches.division` | trimmed |
| Sheet-name → round | `matches.round` | `'day 1'..'day N'`, `'semi-final'`, `'final'` |
| Side A player 1 | `match_sides.player1_id` (side='A') | `get_or_create_player` |
| Side A player 2 | `match_sides.player2_id` (side='A') | same |
| Side B player 1 | `match_sides.player1_id` (side='B') | same |
| Side B player 2 | `match_sides.player2_id` (side='B') | same |
| Per-set games | `match_set_scores.{side_a,side_b}_games` | per recipe |
| Sum of per-set games per side | `match_sides.games_won` | sum (or total in single-row variant) |
| Sets won per side | `match_sides.sets_won` | count (or 1/0 in single-row variant) |
| Side won (boolean) | `match_sides.won` | derived |
| Walkover flag | `matches.walkover` | `1` if `'w/o'` annotation present |
| `ingestion_runs.id` of this load | `matches.ingestion_run_id` | populated by parser |

## Edge cases to handle

1. **Two row-layout variants per template family.** Two-row (set 1 + set 2 as separate rows) vs single-row (totals only). Detect per-sheet, not per-file — although in practice a workbook is consistent.

2. **Court panels per sheet vary in count.** Day 1 Antes has 3 courts; Day 2 has 2; Final has 1 court. Don't hard-code court count — scan col 3 for `Court N` labels.

3. **Pro-substitute cells.** `"Jade Sammut (pro) Elaine Grech"` is a SINGLE cell containing two players because a substitute came in mid-rubber. Parser strategy: if a player cell contains the substring `(pro)` (case-insensitive), split on `(pro)` and use the FIRST half as the player; surface the second half in the quality report. (Alternative strategies — using only the substitute — would arguably be wrong; the original player started the match. Document this as a Phase-0 trade-off.)

4. **Apostrophe variants.** Backtick (`` ` ``), curly right single quote (`'`), and straight ASCII (`'`) all appear for the same surname (`Pule'`). `players.normalize_name` collapses these — but the parser must NOT pre-normalize.

5. **Empty rubber rows in the middle of a panel.** Some rubbers have no players (skipped/cancelled rubbers). Detect by: if `[r,4]` (rubber-type) is empty OR `[r,5]` and `[r,8]` are both empty, skip silently (do NOT advance the iteration prematurely — keep stepping by 3 rows until all panels exhausted).

6. **Walkovers (`w/o`).** Tennis Trade 2024 Day 1 row 11 has `[11,12]='w/o 0-5'` and `[11,10]=6.0, [11,11]=12.0` (the recorded games). Set `walkover=1` and store games as recorded. Rating engine will dampen via `S=0.90/0.10` per the score margin curve (PLAN.md §5.2 walkover handling).

7. **Singles rubber.** Some sheets include a `'Singles'` rubber: `[r,5]` has the side-A player, `[r,6]` is blank, `[r,8]` has the side-B player, `[r,9]` is blank. Schema supports this (`match_sides.player2_id` is nullable). Set `match_type = 'singles'` for these matches.

8. **CAPS vs Title-case discrepancy.** Same player appears as `"SEAN CACHIA"` on Day 2 Antes and `"Sean Cachia"` on Day 1 Antes. `players.normalize_name` does not lowercase, so these become distinct players. This is a known Phase-0 limitation per `players.py` docstring; parser does not attempt to fix.

9. **Date formats vary in `[6,3]`.** Most use `DD/MM/YYYY`; Tennis Trade Final uses `'Final - 22/01/25'` (2-digit year). San Michel 2026 uses `' - '` (em-dash-like) instead of `' & '`. The regex `\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}` matches both; expand 2-digit years assuming 21st century (`+2000`).

10. **Row-band stride is 3 (not 2 or 4).** Rubbers at rows 12, 15, 18, 21, …, 33; then a `Total Day N A` summary row at ~22; the band continues at row 24 on Court 1; Court 2 panel starts further down. Algorithm: walk in steps of 3 starting at header_row+1; stop when both col 5 and col 8 are empty for the current row AND the row is not within 3 rows of a `'Total Day'` row.

11. **Half-empty rubber rows ("vs" only).** Some rows have only `[r,7]='vs'` and totals=0 (placeholder rubbers that didn't get played). Detect by: if both player cells at `[r,5]` and `[r,8]` are blank/empty-string, skip the rubber entirely.

12. **Final-sheet round labels.** `Final` and `Semi Final` sheets are matches like any other Day; the only difference is `matches.round`. The Final's `[6,3]` may be `'FINAL - 11 July 2025'` (only one date); same regex works.

13. **Date is missing on some Day sheets.** Some Day sheets in the family (e.g., the empty templates) have no date at `[6,3]`. Fallback: use the tournament-year + month/day derived from sheet position OR (last resort) tournament-year-Jan-1 placeholder. For Antes 2025 / Tennis Trade 2024-2025 / San Michel 2025-2026, all Day/Semi/Final sheets DO have a parseable date.

14. **Tournament year extraction from filename.** `Antes Insurance Team Tournament IMO Joe results 2025.xlsx` → `2025`. `Tennis Trade Team Tournament - Results.xlsx` → no year in filename; fall back to year from `[6,3]` of Day 1 (`'29/10/2025'` → 2025). Pattern: `\b(20\d{2})\b` first; else year from first parsed match date.

15. **`Antes Insurance Team Tournament results with sets.xlsx` has TWO Team Selection sheets.** Doesn't affect parsing of Day/Semi/Final sheets (Team Selection is unused by this parser).

16. **Empty templates produce zero matches.** Some files in the listed set are unfilled templates (Antes "results sets", "results with sets"; Tennis Trade Results, Results(1) base); the parser will return 0 matches for these — that's expected, not an error.

## Suggested parser test cases

Each test case below uses real data from `Antes Insurance Team Tournament IMO Joe results 2025.xlsx` unless noted.

### Test 1 — Day 1, Court 1, first rubber (men D, 2-set bagel)

- **Sheet:** `Day 1`, court panel `Court 1`, anchor row `r=12`.
- **Expected:**
  - `matches.played_on = '2025-05-28'`, `matches.division = 'Men D'`, `matches.round = 'day 1'`, `matches.match_type = 'doubles'`, `matches.walkover = 0`.
  - Side A player 1: `'Conrad Treeby Ward'` (raw); player 2: `'Daniele Privitera'`.
  - Side B player 1: `'Ray Ciantar'`; player 2: `'Kevin Sciberras'`.
  - Set 1: A=6, B=3. Set 2: A=3, B=6.
  - `match_sides[A].sets_won = 1, games_won = 9, won = FALSE`. `match_sides[B].sets_won = 1, games_won = 9, won = FALSE` (1-1 set tie, no super-tiebreak observed in cells → undecided). NOTE: this is faithful to the file (the file's "Sets" total at `[12,12]=1, [12,13]=1` confirms the 1-1 set tie). The rating engine should skip undecided matches.

### Test 2 — Day 1, Court 1, second rubber (Lad B, clean 2-0)

- **Sheet:** `Day 1`, anchor row `r=15`.
- **Expected:**
  - `matches.division = 'Lad B'`, `played_on = '2025-05-28'`.
  - Side A: `'Romina Gauci'` + `'Mariska Steenkamer'`. Side B: `"Angele Pule'"` + `'Jade Sammut'`.
  - Set 1: A=6, B=2. Set 2: A=6, B=1.
  - `match_sides[A].sets_won = 2, games_won = 12, won = TRUE`. `match_sides[B].sets_won = 0, games_won = 3, won = FALSE`.
  - Players inserted with `gender='F'` (because rubber type is `Lad B`).

### Test 3 — Day 1, Court 4, Lad C with Pro-substitute marker

- **Sheet:** `Day 1`, anchor row `r=30` (Court 2 panel; the row in the file with the `(pro)` annotation).
- Actually the (pro) annotation is at `[30,9]='Jade Sammut (pro) Elaine Grech'`.
- **Expected:**
  - `matches.division = 'Lad A'`, `played_on = '2025-05-28'`, `round='day 1'`.
  - Side A: `'Naomi Zammit Ciantar'`, `'Amanda Falzon'`.
  - Side B: `'Annmarie Mangion'`, `'Jade Sammut'` (taking the FIRST half of the (pro)-split cell).
  - Set 1: A=6, B=2. Set 2: A=7, B=5.
  - `match_sides[A].sets_won = 2, games_won = 13, won = TRUE`.

### Test 4 — Final sheet, single rubber

- **Sheet:** `Final`, anchor row `r=13`.
- **Expected:**
  - `matches.round = 'final'`, `matches.division = 'Men B'`, `played_on = '2025-07-11'`.
  - Side A: `'Nikolai Belli'`, `'Ivan Cachia'`. Side B: `'Kurt Cassar'`, `'Roderick Spiteri'`.
  - Set 1: A=6, B=0. Set 2: A=6, B=2.
  - `match_sides[A].sets_won = 2, games_won = 12, won = TRUE`. `match_sides[B].won = FALSE`.

### Test 5 — Total match count for Antes 2025

- **File:** `Antes Insurance Team Tournament IMO Joe results 2025.xlsx`.
- After parsing, `SELECT COUNT(*) FROM matches WHERE ingestion_run_id = ?` should produce a count between 100 and 150 (the file has ~143 plausible rubbers per the field-counting pre-flight). Actual exact count subject to skip logic for empty/placeholder rubbers — assert `>= 100`.

### Test 6 — Tennis Trade 2024 (single-row variant), walkover detection

- **File:** `Results Tennis Trade Team Tournament(1).xlsx`.
- **Sheet:** `Day 1`, anchor row `r=11` (header at row 10 in this variant; first rubber at row 11).
- **Expected:**
  - `matches.division = 'Men D'`, `matches.walkover = 1`.
  - Side A: `'Joseph Randich'`, `'Chris Vella'`. Side B: `'Matthew Micallef'`, `'Justin Scicluna'`.
  - ONE `match_set_scores` row: set_number=1, side_a_games=6, side_b_games=12, was_tiebreak=0.
  - `match_sides[A].games_won = 6`, `match_sides[B].games_won = 12`, `match_sides[B].won = TRUE`.

---

## Summary stats (sanity)

| File | Variant | Sheets with rubbers | Expected match count |
|---|---|---|---|
| Antes Insurance Team Tournament IMO Joe results 2025.xlsx | two-row | Day 1-5, Semi Final, Final | ~140 |
| San Michel Results 2025 Results.xlsx | two-row | Day 1-10, Semi Final | ~250 |
| San Michel Results 2026.xlsx | two-row | Day 1-10, Semi Final, Final | ~250 |
| Tennis Trade Team Tournament - Results.xlsx | single-row | Day 1-5 | ~140 |
| Results Tennis Trade Team Tournament(1).xlsx | single-row | Day 1-5, Final | ~140 |
| Antes (results sets) / (results with sets) | two-row | empty | 0 |
| Tennis Trade Results / Results(1) (the empty pair) | empty | empty | 0 |
