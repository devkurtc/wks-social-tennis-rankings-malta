# Parser specification — Wilson Autumn / Spring Team Tournaments (2017–2021)

## File(s) analyzed

- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/Wilson Autumn Results 2017.xls`
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/Wilson Autumn Results 2018.xls`
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/Wilson Autumn Results 2019.xlsx`
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/Wilson Autumn Results 2020.xlsx` (primary reference)
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/Wilson Autumn Results 2021.xlsx`
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/Wilson Spring Results 2018.xls`
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/Wilson Spring Results 2019.xls`

Templates (NOT data — skip):
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/Wilson Spring Results Template.xls`
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/San Michel Results Template.xls`

## Format classification

**Format:** VLTC team tournament with 6 teams (A–F), each match-day pairing 3 teams against 3 others across 3–4 courts; each court hosts 8 rubbers played by 4-vs-4 between the two teams. Doubles only. Format identical to the 2024 / 2025 Antes / PKF / Tennis Trade team tournaments mentioned in PLAN.md §3 ("Team tournament" pattern).
**Confidence:** high.

Why: every Day-N sheet (and Semi Final / Final) shares the same per-court block layout — `Time | Rubber | Pair-A-Player1 | Pair-A-Player2 | vs | Pair-B-Player1 | Pair-B-Player2 | (set1 games) | (set1 games) | (sets-won totals)`. Each rubber occupies 2 score-rows (set 1 on `r`, set 2 on `r+1`) plus a blank spacer. Subtotals named `Total Day N A` / `Total Day N B` / `Total Day N` mark intra-court boundaries. This template family is consistent across 8 files spanning 5 years and two seasons (Autumn / Spring).

This format is a poor fit for `'doubles_division'` (per `tournaments.format` schema) because it's a team event, not a division round-robin. **Use `'doubles_team'`.**

## Sheet map

| Sheet | Role | Notes |
|---|---|---|
| `Team Selection` (sometimes `Teams`) | Roster | Rows 7–22 (men) and 25–36 (ladies), col 1 = position (`A1`/`A2`/`A3`/`B1`–`B4`/`C1`–`C3`/`D1`–`D3`), cols 2–7 = teams A–F. Cell `[3,2..7]='A'..'F'`, `[4,2..7]` = team captain names. |
| `Encounters played` (sometimes `Encounters Played`) | Per-player Day×Day participation matrix | Day-N columns hold `1` for each day a player played. Useful as a sanity-check denominator; not load-required. |
| `Standings` | Aggregated team totals per day (G = games, S = sets) | Computed totals; not authoritative. **Note:** `Wilson Autumn Results 2020.xlsx` has cell `[2,3]='WILSON TEAM TOURNAMENT 2015'` (typo, copied template). Do NOT rely on the in-cell year — use the filename. |
| `Day 1`–`Day 5` | Per-court rubber matches | The match-bearing sheets. Each contains 3–4 court blocks, each with 8 rubbers split into two halves (`Total Day N A` / `Total Day N B`). |
| `Semi Final` | Knockout semi-final rubbers | Same layout as Day-N. Two courts (one per semi). `round = 'semi-final'`. |
| `Final` | Knockout final rubbers | Same layout. `round = 'final'`. |

## Per-day-sheet column layout (variable per sheet — must auto-detect)

The "Time" header row contains the labels `Time`, `Rubber`, `Team A: <captain>` (cols spanning 3 cells), `vs`, `Team B: <captain>`, `Games`, `Sets`. **The starting column is either 2 or 3, and shifts unpredictably — even within the same workbook.** Examples observed:

| File | Day 1 anchor col | Day 2 anchor col |
|---|---|---|
| `Wilson Autumn Results 2020.xlsx` | 3 | 2 |
| `Wilson Autumn Results 2021.xlsx` | 3 | 3 |
| `Wilson Autumn Results 2020.xlsx` Final | 2 | — |

The parser must scan each sheet for a `'Time'` literal in cols 1–4, rows 1–15, then anchor the column layout from there. Column offsets (0 = the col where `'Time'` was found):

| Offset | Field |
|---|---|
| +0 | Time |
| +1 | Rubber (e.g. `Men A`, `Lad B`, `Mxd BA`, `MXD CB`) |
| +2 | Side A player 1 |
| +3 | Side A player 2 |
| +4 | `vs` divider |
| +5 | Side B player 1 |
| +6 | Side B player 2 |
| +7 | set games (col holds Side A's set 1 on row r, Side A's set 2 on row r+1) |
| +8 | set games (Side B's set 1 on row r, Side B's set 2 on row r+1) |
| +9 | (Sets header label) — Side A sets-won total |
| +10 | Side B sets-won total |

Note that the "Games" header at offset +7 spans two cells (set 1 and set 2 are on consecutive rows for the same side, not separate cells on the same row). Similarly, the "Sets" header at offset +9 spans Side A and Side B sets-won totals.

## Per-rubber row layout

For each court, the "Time" header row is followed (1 row down) by the first rubber. Each rubber is **2 score-rows** plus typically 1 blank spacer (sometimes 2). The first row of a rubber holds:

| Offset | Field on row `r` (rubber start) | Field on row `r+1` |
|---|---|---|
| +0 (col=Time) | Time string (`'6.30 pm'`, `'7.45 pm'`, `'9.00 pm'` — variable spacing/case) | (blank) |
| +1 (Rubber) | Rubber category (`Men A`/`Men B`/`Men C`/`Men D`/`Lad A`/`Lad B`/`Lad C`/`Mxd BA`/`MXD CB`/etc.) | (blank) |
| +2 (A1) | Side A player 1 name (e.g. `'Neville Sciriha'`) | (blank) |
| +3 (A2) | Side A player 2 name (e.g. `'Mariska Steenkamer'`) | (blank) |
| +4 (vs) | `'vs'` (sometimes blank in older Spring files) | (blank) |
| +5 (B1) | Side B player 1 name | (blank) |
| +6 (B2) | Side B player 2 name | (blank) |
| +7 (Set games — A) | Side A set 1 games (int) | Side A set 2 games (int) |
| +8 (Set games — B) | Side B set 1 games (int) | Side B set 2 games (int) |
| +9 (Sets-won — A) | Side A sets-won (0/1/2) | (blank) |
| +10 (Sets-won — B) | Side B sets-won (0/1/2) | (blank) |

Detection: the next rubber starts when a non-blank string appears in col `name_col` (offset +2, the "Side A player 1" column). Stop scanning a court block when a row contains `'Total Day'` in the Time column or 5+ consecutive blank rows.

After a court's 4 rubbers there's a `Total Day N A` row. Then 4 more rubbers (the second half of the court). Then `Total Day N B`. Then `Total Day N` (court grand total). Then a few blank rows. Then `Court 2` (next court). And so on. The parser does NOT need the totals — it can ignore them.

## Match-deciding super-tiebreak

The Wilson tournament uses a 10-point match super-tiebreak when a rubber is tied at one set each. **Unlike Sports Experience 2025, the super-tiebreak score is NOT recorded as a third numeric column** — there's no extra cell for it.

Two observed encodings:
1. **Implicit (most rubbers):** sets-won column shows `1-1`, set-games show e.g. `7-6 / 6-7` (or `6-4 / 4-6`). The super-tiebreak winner is NOT recoverable from the cell values alone in the day sheets — but the per-day team totals (`Total Day N`) include super-tiebreaks as the deciding "set", so the standings DO know. We have no way to recover the per-rubber tiebreak winner from the cells. **Decision (mirrors PLAN.md §5.2 tolerance for tied rubbers):** record the rubber as 1-1 in sets, leave both sides' `won = 0` (undecided), and flag in the quality report. The rating engine will skip tied rubbers.
2. **Explicit (rare — Wilson 2020 Semi Final):** a string like `'T.B. 7-9'` appears in column +11 (one column past sets-won) on the second score-row. When present, parse it: format `'T.B. <A>-<B>'` (case-insensitive `T.B.` / `TB`); record as a 3rd "set" with `was_tiebreak = TRUE`. The winner of that tiebreak resolves the rubber.

The spec implementation should:
- Scan column +11 (and +12 as fallback) for tiebreak strings on score-rows for any rubber where set-1 winner ≠ set-2 winner.
- If a tiebreak string is found, parse it and add a 3rd `match_set_scores` row with `was_tiebreak = 1`.
- If sets are tied 1-1 with no tiebreak string available, record the two sets as-is, BOTH `won = 0`, BOTH `sets_won = 1`, and add an entry to the `quality_report.tied_rubbers_undecided` list.

## Retirements / unplayed rubbers

- **Retirement (`'ret'`)** appears as the literal string in set-2 game columns (rows 32, 35, 38 of Wilson 2017 Final). The set-1 score is real; the player retired during set 2. Treat: set 1 recorded normally, set 2 NOT recorded, `match.walkover = 1` (per `PLAN.md §5.2` walkover handling — closest schema bit), winner = whichever side won set 1. Quality report entry: `retired_rubber`.
- **Empty / unplayed rubber** (sets 0-0, all game cells blank or 0 with sets totals 0-0): skip the rubber, log to `quality_report.unplayed_rubbers`. Do not insert.
- **Walkover** — not encoded explicitly in any observed file. If a rubber row has player names but no scores at all, treat as unplayed.

## Date / day mapping

- Wilson Autumn 2021 has dates in DAY headers: `'DAY 1 - 3/11/2021 & 5/11/2021'`. Parser should regex-extract the first `D/M/YYYY` if present.
- Wilson Autumn 2020 has no per-day dates anywhere. Wilson 2019 likewise.
- Wilson Spring 2018/2019 — no per-day dates observed.

**Decision (mirrors `parser_spec_sports_experience_2025.md` §15):** Use a per-day placeholder date keyed off the file year:
- Day 1 → `<year>-09-01` (Autumn) or `<year>-04-01` (Spring), incrementing by 7 days per Day. (Day 5 = year-09-29 / year-04-29.)
- Semi Final → `<year>-10-15` (Autumn) / `<year>-05-15` (Spring).
- Final → `<year>-10-30` (Autumn) / `<year>-05-30` (Spring).
- If a real date is parseable from the day-header (Autumn 2021), use it instead.
- Document placeholder usage in `ingestion_runs.quality_report_jsonb`.

## Roster / gender inference

Gender per player is inferred from the rubber category:
- `Men A` / `Men B` / `Men C` / `Men D` / `Men A ` (trailing space) → both players male.
- `Lad A` / `Lad B` / `Lad C` (case variants) → both players female.
- `Mxd BA` / `MXD CB` / `Mxd CB` → mixed doubles. Side A player 1 + Side B player 1 are male, side A player 2 + side B player 2 are female (this is the convention observed: men first, women second within a mixed pair, but verify per-rubber). Conservative: do NOT set gender for mixed-doubles players in this parser pass — leave it `NULL` and let later runs infer it from same-player same-club Men/Lad rubber appearances.

## Extraction recipe

Use either:
- `openpyxl.load_workbook(path, data_only=True, read_only=False)` for `.xlsx`, or
- `xlrd.open_workbook(path)` for `.xls`.

Wrap the file in a uniform sheet/cell accessor so the rest of the code is format-agnostic.

| Field | Sheet | Row anchor | Col anchor | Notes |
|---|---|---|---|---|
| `tournament.name` | filename | — | — | `'Wilson Autumn Team Tournament <year>'` or `'Wilson Spring Team Tournament <year>'`. Do NOT trust in-cell title (Wilson 2017 says 2015). |
| `tournament.year` | filename | — | — | Regex: `r'(20\d{2})'`. |
| `tournament.format` | constant | — | — | `'doubles_team'`. |
| Per match: `division` | per-rubber | — | — | The rubber category string verbatim (`'Men A'`, `'Lad B'`, `'Mxd BA'`, etc.) — provides ladder/skill bracket info. |
| Per match: `round` | sheet name | — | — | NULL for Day-N, `'semi-final'` for `Semi Final`, `'final'` for `Final`. |
| Per match: `played_on` | day-header or placeholder | — | — | See "Date / day mapping" above. |
| Per match: pair A | per-rubber | row `r` | cols `name_col`, `name_col+1` | Verbatim. |
| Per match: pair B | per-rubber | row `r` | cols `name_col+3`, `name_col+4` | Verbatim. |
| Per match: set 1 games | per-rubber | row `r` | cols `set1_col`, `set1_col+1` | A and B. |
| Per match: set 2 games | per-rubber | row `r+1` | cols `set1_col`, `set1_col+1` | A and B. |
| Per match: super-tb games | per-rubber | row `r+1` (or sometimes row `r`) | col `set1_col+4` | Parse `'T.B. <A>-<B>'`. Optional. |
| Per match: sets-won-A | per-rubber | row `r` | col `sets_col` | Sanity check; parser computes from sets. |
| Per match: sets-won-B | per-rubber | row `r` | col `sets_col+1` | Sanity check. |

## Schema mapping

(Per `PLAN.md §6`.)

| Extracted field | Target table.column | Transform |
|---|---|---|
| Filename | `source_files.original_filename` | as-is |
| SHA-256 | `source_files.sha256` | hash bytes |
| Tournament name | `tournaments.name` | derived from filename |
| Year | `tournaments.year` | int from filename |
| `'doubles_team'` | `tournaments.format` | literal |
| Day-N / placeholder date | `matches.played_on` | ISO 8601 |
| `'doubles'` | `matches.match_type` | literal |
| Rubber category | `matches.division` | verbatim string |
| `'semi-final'` / `'final'` / NULL | `matches.round` | derived from sheet name |
| Pair A players | `match_sides.player1_id`, `.player2_id` (side='A') | via `get_or_create_player` |
| Pair B players | `match_sides.player1_id`, `.player2_id` (side='B') | via `get_or_create_player` |
| Per-set games | `match_set_scores.side_a_games`/`side_b_games` | int |
| Set 1/Set 2 with `7` in score | `match_set_scores.was_tiebreak` for that set | TRUE if `ga==7 or gb==7` |
| Match-deciding super-tb (when present) | `match_set_scores` row 3 with `was_tiebreak=TRUE` | parsed from `'T.B. <A>-<B>'` cell |
| Sets won per side | `match_sides.sets_won` | count of regular sets won |
| Games won per side | `match_sides.games_won` | sum of regular-set games |
| Won boolean | `match_sides.won` | as in SE 2025 (super-tb breaks 1-1 ties when present; if 1-1 with no tb cell, both `won=0`) |
| Retirement | `matches.walkover` | `1` for retirements |

**Fields with no source data:**
- Per-rubber dates within a day (placeholder used).
- `players.dob_year` / `players.gender` for mixed-doubles players (conservative; defer).

## Edge cases to handle

1. **Column anchor varies per sheet (col 2 vs col 3).** Within the same workbook (Wilson 2020), Day 1 uses col 3 but Day 2 onwards uses col 2. **Solution:** scan rows 1–15, cols 1–5 for the literal `'Time'` cell and use that as the anchor.
2. **Header row varies (rows 8/9/10/11).** Detect dynamically.
3. **Title cell year typo.** Wilson 2017 says "2015". Always use the filename year, never the in-cell year.
4. **`vs` divider missing in older Spring files.** Don't fail if col `vs_col` is empty. Use the player-name presence as the rubber-row detector.
5. **Variable rubber category casing.** `'Men A'`, `'Men A '` (trailing space), `'Mxd BA'`, `'MXD CB'`, `'LAD a'`. Normalize whitespace and capitalize; preserve the rubber slot for `division`.
6. **Time strings vary.** `'6.30 pm'`, `'6.30pm'`, `'7.45 pm '` (trailing space). Not load-relevant; ignore.
7. **Retired rubbers.** `'ret'` strings in the set-2 columns. Set-1 score is the only valid set; treat as a one-set match with `walkover = 1`. Winner = set-1 winner.
8. **Tied 1-1 sets with no super-tb cell.** Most files don't record the super-tb winner. Record both sides as `sets_won=1, won=0`, and add to `quality_report.tied_rubbers_undecided`. Rating engine will skip these.
9. **`'T.B. <A>-<B>'` strings.** Wilson 2020 Semi Final has `'T.B. 7-9'` and `'T.B. 9-7'` patterns in col `set1_col+4` on the set-2 row. Parse with `re.match(r'T\.?B\.?\s*(\d+)\s*[-/]\s*(\d+)', value, re.IGNORECASE)`.
10. **Pro substitutions.** `'Julian Esposito (Pro Frank Camilleri)'` appears in some rosters — record verbatim; `players.py` will treat it as a unique alias. Don't try to split.
11. **Empty rubbers (all 0-0).** Don't insert; log to quality report.
12. **`Final` and `Semi Final` row 11 header omits `vs` cell.** It's the layout convention — the team-level `'vs'` is implied by the title. Per-rubber rows still have `vs` in col offset +4.
13. **`Wilson 2020 Day 4` and `Day 5` use a row-shifted layout.** Day 4 has Time-row at row 9 (instead of 10) — detection by `'Time'` scan handles this naturally.
14. **`.xls` vs `.xlsx`.** `.xls` files (2017, 2018 Autumn, 2018/2019 Spring) need `xlrd`. Wrap in a uniform `Workbook` adapter.
15. **Templates contain stub data — DO NOT parse them.** `Wilson Spring Results Template.xls`, `San Michel Results Template.xls` — skip when name contains `'Template'`.
16. **Apostrophe variants.** `"Twanny Pule'"`, `"Andrew Pule'"`, `"Josette D'Alessandro"` — pass through verbatim; `players.py` normalizes.
17. **Captain rows contain only the team-letter and captain name.** The `Team Selection` sheet has `'A2'`–`'D3'` rows for player slots; only some are populated each season. Don't assume a fixed roster size.
18. **`(pro Roberta Fenech)` sub-pattern.** Wilson 2020 Final row 31 `[31,5]='Julia Barbara (pro) Roberta Fenech'`. Pass verbatim; treat as one player name. The substitute is a real-life replacement, but the spreadsheet doesn't separate them clearly; defer to a later normalization pass.

## Suggested parser test cases

Each test case below uses real data; the parser must reproduce the listed extraction.

### Test case 1 — Clean 2-set win, Day 1 first rubber

- **File:** `Wilson Autumn Results 2020.xlsx`
- **Sheet:** `Day 1`
- **Rubber:** Mxd BA, Court 1, time 6.30 pm
- **Side A:** `Neville Sciriha / Mariska Steenkamer` (Team A)
- **Side B:** `George Grech / Grace Barbara` (Team F)
- **Set 1:** A=1, B=6
- **Set 2:** A=6, B=0
- **Sets:** 1-1 (no `T.B.` cell visible) → tied; both `won=0`, both `sets_won=1`, both `games_won=7`
- **Division:** `'Mxd BA'`, `round=NULL`, `played_on='2020-09-01'` (placeholder)

### Test case 2 — Two-set sweep

- **File:** `Wilson Autumn Results 2020.xlsx`
- **Sheet:** `Day 1`
- **Rubber:** Lad A, Court 1, 7.45 pm
- **Side A:** `Olivia Belli / Nicole Fava`
- **Side B:** `Alexia Spiteri / Elaine Grech`
- **Set 1:** A=7, B=6 (was_tiebreak=TRUE)
- **Set 2:** A=6, B=4
- **Result:** Side A wins; A `sets_won=2, games_won=13, won=1`; B `sets_won=0, games_won=10, won=0`.

### Test case 3 — Explicit super-tiebreak (`T.B. 7-9`)

- **File:** `Wilson Autumn Results 2020.xlsx`
- **Sheet:** `Semi Final`
- **Rubber:** Lad B, Court 1
- **Side A:** `Julia Barbara / Anna Buhagiar`
- **Side B:** `Dominique Francica / Jennifer Mifsud`
- **Set 1:** A=7, B=6 (tb)
- **Set 2:** A=6, B=4 — wait, file says A=6 B=4. Let me re-check.
- **Actually from data:** row 16 → A=7 B=6 (set 1), row 17 → A=6 B=4 (set 2). Sets total: A=2, B=0. Hmm the `T.B.` cell `[17,13]='T.B. 7-9'` indicates tiebreak score, but sets totals are 2-0. That doesn't match.
- **Re-examining:** Looking at row 16/17 again — `[16,11]=2, [16,12]=0` (sets total at offset +9/+10 with anchor=2, that's cols 11/12). So A=2, B=0 in sets. The `T.B. 7-9` might be from a different rubber. **Action for parser test:** use the row-51/52 example instead: `[52,13]='T.B. 9-7'` for Lad B at row 51 (Court 2). Side A `Anabel Borg / Carmen Cuschieri`, Side B `Rowena Caruana / Tanya Cassar`, set 1 A=2 B=6, set 2 A=5 B=7, and `T.B. 9-7` would mean a tiebreak score 9-7 (but the sets are 0-2 already, so this seems contradictory). **Decision:** treat the `T.B.` strings as informational; if the sets-won totals are already decisive (2-0 or 0-2), record them as the source of truth (super-tb is purely cosmetic in those cases) and IGNORE the T.B. cell.
- **Test instead:** assert that the rubber at `Semi Final` row 51 (`Anabel Borg / Carmen Cuschieri` vs `Rowena Caruana / Tanya Cassar`) produces sets `(1, 2, 6, 0), (2, 5, 7, 1)` — was_tiebreak=TRUE on set 2 because game total includes 7. Side B wins.

### Test case 4 — Retirement (`'ret'`)

- **File:** `Wilson Autumn Results 2017.xls`
- **Sheet:** `Final`
- **Rubber:** Men A, Court ?, 9.00 pm, row 31
- **Side A:** `Marcelo Villanueva / Richard Curmi`
- **Side B:** `Suniel Balani / Trevor Rutter`
- **Set 1:** A=7, B=5 (was_tiebreak=FALSE; total<7=12)
- **Set 2:** N/A — `[32,10]='ret', [32,11]='ret'`
- **Result:** Side A wins set 1 → Side A wins rubber; `match.walkover=1`; `match_set_scores` has only set 1; A `sets_won=1, games_won=7, won=1`; B `sets_won=0, games_won=5, won=0`.

### Test case 5 — Column anchor at col 2 (Wilson 2020 Day 2)

- **File:** `Wilson Autumn Results 2020.xlsx`
- **Sheet:** `Day 2` (column anchor=2, NOT 3 — important regression case)
- **Rubber:** Men A, Court 1, 6.30 pm
- **Side A:** `Nicholas Gollcher / Dean Callus`
- **Side B:** `Kurt Carabott / Clive Borg`
- **Set 1:** A=4, B=6
- **Set 2:** A=7, B=6 (was_tiebreak=TRUE)
- **Sets total:** 1-1 (tied; no T.B. cell); both `won=0`, both `sets_won=1`, A `games_won=11`, B `games_won=12`. Quality report logs the tied rubber.

### Test case 6 — Smoke test on multiple Wilson files

- **Files:** `Wilson Autumn Results 2020.xlsx`, `Wilson Autumn Results 2019.xlsx`, `Wilson Autumn Results 2021.xlsx`
- **Assertion:** parser runs to completion (no exceptions), inserts >50 matches per file, every match has 1 or 2 entries in `match_set_scores`, every match has exactly 2 entries in `match_sides`, every player has a non-empty `canonical_name`.

## Summary stats (rough)

Each Day-N sheet has up to 4 courts × 8 rubbers = 32 rubbers per day; 5 days × 32 = ~160 day-stage matches per tournament. Plus 8 semi-final rubbers + 8 final rubbers = ~176 matches per Wilson tournament. Across 7 actually-data files = ~1200 matches total. Players: ~100 unique per tournament; ~150–200 across all 7 files.
