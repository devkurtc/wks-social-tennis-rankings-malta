# Parser specification — Sports Experience Chosen Doubles 2025

## File(s) analyzed

- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/Sports Experience Chosen Doubles 2025 result sheet.xlsx`

## Format classification

**Format:** VLTC division round-robin doubles, multi-division (M1–M4 + L1–L3) in one workbook, with fixed pairs per division.
**Confidence:** high.

Why: every non-roster sheet uses the exact same "two side-by-side match blocks" layout (left block cols A–N, right block cols P–AC) with a per-row standings panel at cols AE–AN. Header rows (`Players`/`Set Scores`/`Tie`) live at row 7; matches start at row 9 in steps of 4 rows (pair A → `vs.` → pair B → blank). Pair labels are consistently `"First Last/First Last"` strings; no name is split across cells. The "two-group" sheets (Men Div 3, Men Div 4, Lad Div 3) repeat the same template starting at row 39 (group label at row 35, header at row 37, matches start at row 39) and add a `Final` block lower down. This is the *cleaner* of the two known VLTC patterns described in `PLAN.md` §3.

## Sheet map

| Sheet | Role | Notes |
|---|---|---|
| `Players Men` | Roster (men) | Pair list per division/group; `[5,2]` = first division label, then 4 fixed groupings. Source of truth for the 4 men divisions and which sub-group each pair belongs to (Div 3 & Div 4 are split into Group A / Group B). |
| `Men Div 1` | Matches (Div 1, single group, 6 pairs) | 15 matches expected (`C(6,2)`). Two visual blocks per row band; standings block at cols AE–AN. No `Final` block (single group → standings winner is "Division Winner"). |
| `Men Div 2` | Matches (Div 2, single group, 6 pairs) | 15 matches expected. Same shape as Men Div 1. **Note:** rows 26, 30, 34, 38 contain `'vs'` (no period) instead of `'vs.'` — be tolerant. |
| `Men Div 3` | Matches (Div 3, two groups of 5 pairs each) | 10 matches per group expected (`C(5,2)`). Group A rows 9–31, group B rows 39–61. `Final` block starts at row 67; **player names are split across two rows** (row 70 = first player, row 71 = second player + scores; row 73 = first player, row 74 = second player + scores) — different layout from group blocks. Division winner at row 77, runner up at row 81. |
| `Men Div 4` | Matches (Div 4, two groups of 5 pairs each) | Same layout as Men Div 3. **Final block exception:** at rows 70–74 the first row holds the *full pair* string and scores in the same cell range, not split — see edge cases. Winner at row 76, runner-up at row 80 (typo `'Divison'`). |
| `Players Ladies` | Roster (ladies) | 3 divisions; **Lad Div 1 has 6 pairs but rows 10 and 11 both have rank `5.0`** (data quirk — both are valid pairs; treat them as 5th and 6th). |
| `Lad Div 1` | Matches (Lad Div 1, single group, 6 pairs) | 15 matches expected. Same shape as Men Div 1/2 but **many matches have empty score cells** (rows 13, 15, 29, 31, 37, 39 left block; row 21/23 right block, etc.) — these are unplayed/forfeited. See edge cases. |
| `Lad Div 2` | Matches (Lad Div 2, single group, 6 pairs) | 15 matches expected. Clean. |
| `Lad Div 3` | Matches (Lad Div 3, two groups of 6 pairs each) | 15 matches per group expected. Group A rows 9–39, group B rows 47–77. `Final` block at rows 82–88; in this sheet the **player names are pair strings on a single row each** (row 86 and row 88), unlike Men Div 3. Winner row 91, runner-up row 95. |

## Column layout (uniform across all match sheets)

Anchored at row 7 (top header) and row 8 (sub-header). The same column band repeats twice horizontally:

### Left match block (cols A–N)

| Col idx | Letter | Content (row 7/8) |
|---|---|---|
| 1 | A | `Players` (pair name on match rows; `vs.` on the `vs` row) |
| 2 | B | `Set Scores` / `Score` — Set 1 score for the pair on this row |
| 3 | C | `Set 1 Work` (formula helper — `1` if pair won set 1, else `0`) |
| 5 | E | `Score` — Set 2 score |
| 6 | F | `Set 2 Work` (1/0) |
| 8 | H | `Tie` / `Score` — match-tiebreak score (10-point) IF a third tiebreak was played |
| 9 | I | `Tie Work` (1/0) |
| 10 | J | `Game Played` (helper) |
| 11–14 | K–N | per-pair-per-match aggregates (Sets Points / Sets & Tie Points / Games Wins / Sets Wins) |

### Right match block (cols P–AC)

Same structure shifted by 15 columns: `16=Players`, `17=Set 1 Score`, `18=Set 1 Work`, `20=Set 2 Score`, `21=Set 2 Work`, `23=Match-Tiebreak Score`, `24=Tie Work`, `25=Game Played`, `26–29` aggregates.

### Standings panel (cols AE–AN)

| Col idx | Letter | Header (row 7) | Use |
|---|---|---|---|
| 31 | AE | `Player` (= pair name) | Pair label |
| 32 | AF | `Matches Played` | Total matches in division/group |
| 33 | AG | `Points Overall` | Standing points |
| 34 | AH | `Games Won` | Total games won |
| 35 | AI | `Sets Won` | Total sets won |
| 36 | AJ | `Winner Working` | helper |
| 37 | AK | `Total Games Work` *(or `Runner Up Working` on two-group sheets)* | helper |
| 38 | AL | `Winner` *(or `Total Games Work`)* | helper / declared winner |
| 39–40 | AM–AN | only on two-group sheets: `Winner` / `Runner Up` | declared champion strings |

The standings panel duplicates information already derivable from match scores; the parser may use it for cross-validation but must not depend on it for primary extraction.

## Match-row layout (uniform)

For both blocks (left and right), a match occupies **3 rows** with one blank spacer below:

| Row offset | Content |
|---|---|
| `r` | Pair A name + Pair A's set 1 score, set 2 score, optional match-tiebreak score |
| `r+1` | `vs.` (or `vs` in Men Div 2) — divider |
| `r+2` | Pair B name + Pair B's same three score columns |
| `r+3` | (blank — spacer) |

So matches are anchored at rows `9, 13, 17, 21, 25, 29, 33, 37, …` within a group.

## Extraction recipe

Use `openpyxl.load_workbook(path, data_only=True, read_only=True)`. For each sheet:

| Field | Sheet | Row anchor | Col anchor | Notes |
|---|---|---|---|---|
| `tournament.name` | All sheets, cell `[1,1]` (or filename) | `1` | `1` | Literal `"VITTORIOSA LAWN TENNIS CLUB\nSports Experience Chosen Doubles 2025"`. The second line is the tournament name. |
| `tournament.year` | (filename) | — | — | `2025` from filename — there is **no date column anywhere in the file**. Use Jan 1 of year as `played_on` placeholder, or NULL the date and flag "no per-match date". |
| `tournament.format` | constant | — | — | `'doubles_division'` |
| Roster: division name | `Players Men` / `Players Ladies` | first non-blank row of each block (rows 5, 13, 21, 28 men; 5, 13, 21 ladies) | col `B` (col 2) | E.g. `"Men Division 1 - Group A"`, `"Ladies Division 3 - Group B"`. May be a *single* group label (`"Men Division 2 - Group A"` only) or paired with a `Group B` label in col `E` (col 5) on the same row. |
| Roster: pair label | same | every row where col `A`/`D` has an integer rank | col `B` for group A; col `E` for group B (when present) | Pair string format `"FirstA LastA/FirstB LastB"` — verbatim, do not split. |
| Match sheet name → division | sheet name itself | — | — | Map `'Men Div 1'` → `Men Division 1`, etc. The label inside cell `[5,1]` of each match sheet is authoritative when present. |
| Group label (two-group sheets) | match sheet | row `5` for group A; first row containing `'Group B'` in col 1 (typically row `35` for Men Div 3/4; row `43` for Lad Div 3) | col `1` | E.g. `"Men Division 3 - Group A"`. Use to scope which group a match belongs to. |
| Match anchor rows | match sheet | start at `r0 = 9` for group A; `r0 = group_b_label_row + 4` for group B | — | Iterate `r = r0, r0+4, r0+8, …` while `cell(r,1)` looks like a pair string AND `cell(r+1,1)` is `'vs.'`/`'vs'` AND `cell(r+2,1)` is a pair string. Stop when this pattern breaks (or when you hit `Group B` / `Final` / blank tail). For each anchor row, extract the **left block** match (cols 1–14). |
| Right-block match anchor | match sheet | same `r` as left block | col `16` | Same recipe but check `cell(r,16)`, `cell(r+1,16)='vs.'`, `cell(r+2,16)`. Right-block matches are *separate* matches from left-block ones — the two blocks are NOT mirror images; they're two parallel listings of the same round-robin used to fit on one printable page. |
| Pair A label (left) | match sheet | `r` | `1` | string |
| Pair B label (left) | match sheet | `r+2` | `1` | string |
| Pair A label (right) | match sheet | `r` | `16` | string |
| Pair B label (right) | match sheet | `r+2` | `16` | string |
| Set 1 score Pair A (left) | match sheet | `r` | `2` | int (or empty → unplayed) |
| Set 1 score Pair B (left) | match sheet | `r+2` | `2` | int |
| Set 2 score Pair A (left) | match sheet | `r` | `5` | int |
| Set 2 score Pair B (left) | match sheet | `r+2` | `5` | int |
| Match-tiebreak Pair A (left) | match sheet | `r` | `8` | int (only present when match went to a deciding tiebreak — see edge cases) |
| Match-tiebreak Pair B (left) | match sheet | `r+2` | `8` | int |
| Set 1 score Pair A (right) | match sheet | `r` | `17` | |
| Set 1 score Pair B (right) | match sheet | `r+2` | `17` | |
| Set 2 score Pair A (right) | match sheet | `r` | `20` | |
| Set 2 score Pair B (right) | match sheet | `r+2` | `20` | |
| Match-tiebreak Pair A (right) | match sheet | `r` | `23` | |
| Match-tiebreak Pair B (right) | match sheet | `r+2` | `23` | |
| Final block (Div 3/4 + Lad Div 3) | match sheet | row containing `'Final'` in col `16` | `16` | Optional — derive `tournament_round = 'final'`. Layout differs per sheet; see edge cases. May safely be skipped in T-P0-004 first pass and added later as no `tournament_round` column is needed by the schema for ranking. Each Final IS a real match and should be ingested. |
| Declared division winner | match sheet | row after `'Division Winner'`/`'Divison Winner'` (typo) | col `31` (single-group) or col `16` (two-group, under Final) | Used for sanity check only. Not required for parsing. |
| Declared division runner-up | match sheet | row after `'Division Runner Up'`/`'Divison Runner Up'` | col `31` or col `16` | Sanity check only. |

### Splitting a pair label into two players

The `players.py` module (T-P0-005) does normalization. The parser only needs to:

1. Take the verbatim pair string from the sheet.
2. Split on the literal `/` character (only one `/` per pair string in this file — verified).
3. Strip leading/trailing whitespace from each half (one pair has stray space: `"Robert Attard/ Isaac Baldacchino"`).
4. Pass each half *verbatim* to `players.get_or_create_player(...)` for canonicalisation.

Do not lower-case, do not collapse internal spaces, do not normalise apostrophes — that's downstream's job.

### Scoring → schema

For each extracted match:

- `match_set_scores` row for set 1: `(side_a_games = colA_set1, side_b_games = colB_set1, was_tiebreak = (colA_set1==7 or colB_set1==7))` — best-of-3 short-set; treat `7-6 / 6-7` as a tiebroken set. Use the literal cell value as `*_games`.
- `match_set_scores` row for set 2: same with set-2 columns.
- `match_set_scores` row for match-tiebreak (only if either tiebreak cell at col 8 / col 23 is non-blank): `(side_a_games = tiebreak_A, side_b_games = tiebreak_B, was_tiebreak = TRUE)`.
- `match_sides`: `sets_won` = count of sets where this side's games > opponent's; `games_won` = sum of all per-set games (sets only — match-tiebreak is **not** counted as games per `PLAN.md` §5.2 "games won"); `won` = `sets_won > opponent.sets_won` (with match-tiebreak as the tiebreaker if `sets_won == 1`).

## Schema mapping

(Per `PLAN.md` §6.)

| Extracted field | Target table.column | Transform needed |
|---|---|---|
| Workbook filename | `source_files.original_filename` | as-is |
| Workbook SHA-256 | `source_files.sha256` | hash bytes |
| Tournament title (cell `[1,1]` line 2 + filename year) | `tournaments.name` | concat / strip non-breaking spaces (`\xa0`) |
| `2025` | `tournaments.year` | int |
| `'doubles_division'` constant | `tournaments.format` | literal |
| (no per-match date in file) | `matches.played_on` | use `'2025-01-01'` placeholder OR set NULL and flag in ingestion `quality_report_jsonb`. **Decision needed by T-P0-004:** schema requires a date; pick the placeholder and document it. |
| `'doubles'` constant | `matches.match_type` | literal |
| Division label (e.g. `"Men Division 3 - Group A"`) | `matches.division` | from sheet's row-5 / row-35 / row-43 label |
| Group A / Group B sub-label | `matches.division` (combined) or split into separate column | The schema has no `group` column; concat as part of `division` ("Men Division 3 - Group A") OR stop at division and rely on round-robin match graph. |
| `'final'` for Final-block matches, NULL otherwise | `matches.round` | string |
| Pair A name | `match_sides.player1_id`, `match_sides.player2_id` | split on `/` → 2 player lookups |
| Pair B name | `match_sides.player1_id`, `match_sides.player2_id` | same |
| `side='A'` for left-of-`vs.` / first listed pair, `side='B'` for the other | `match_sides.side` | literal |
| Per-set games | `match_set_scores.side_a_games`, `match_set_scores.side_b_games`, `match_set_scores.set_number`, `match_set_scores.was_tiebreak` | per recipe above |
| Sum of per-set games per side | `match_sides.games_won` | sum |
| Sets won per side | `match_sides.sets_won` | count |
| Side won match (boolean) | `match_sides.won` | derived |
| `ingestion_runs.id` of this load | `matches.ingestion_run_id` | populated by T-P0-004 wrapper |

**Fields with no source data in this file:**

- `matches.played_on` — file has no dates anywhere. Flag in quality report.
- `players.gender` — *implicitly* derivable from sheet name (`Men*` vs `Lad*`). The parser SHOULD set `players.gender` to `'M'` for players seen only on Men sheets and `'F'` for players seen only on Ladies sheets. If a player appears on both (shouldn't happen in this file but possible cross-file), defer to a Phase 1 reconciliation.
- `players.dob_year` — not in file.
- `tournaments.start_date` / `end_date` — not in file.

## Edge cases to handle

1. **Two side-by-side match blocks per row band.** Each band (rows `r..r+2`) contains *two distinct* matches, one in cols A–N and one in cols P–AC. The right-block match is NOT a mirror of the left — both must be ingested. The two blocks share only the row-band index for layout; they do not share player pairs.
2. **`vs.` vs `vs`.** Men Div 2 uses `'vs'` (no trailing period) on rows 26, 30, 34, 38. The detector must accept either.
3. **Two-group sheets repeat the template lower down.** Men Div 3 / Men Div 4 / Lad Div 3 have a second division-label cell (`Group B`) at row 35 (Men) / row 43 (Lad), with its own column header at row 37/45 and matches starting at row 39/47. Detect by scanning col 1 for a string matching `"... - Group B"`.
4. **`Final` block layout differs.** Two-group sheets append a 1-match `Final` between the group winners.
   - **Men Div 3 (rows 67–81):** `Final` label at `[67,16]`. Names are split across **two rows** per side: `[70,16]='Dunstan Vella'`, `[71,16]='Cyril Lastimosa'` (set scores live on row 71 — the row of the *second* player); same for the opponent at rows 73–74. This is the only place in the file where pair members are stored on separate rows. Treat as: pair A = `f"{cell[70,16]}/{cell[71,16]}"` (verbatim concat with `/`); scores from row 71. Same shape rows 73–74.
   - **Men Div 4 (rows 67–80):** `Final` label at `[67,16]`. **Different layout** — `[70,16]` holds the *full* pair string `'Steve Gambin/Luke Gambin'` and scores are on row 71 (no name on row 71). Pair B at `[73,16]` full string with scores on row 73 itself. Be defensive — detect both shapes by checking whether the string contains `/`.
   - **Lad Div 3 (rows 82–88):** Same as Men Div 4 (full pair string per single row), at `[86,16]` and `[88,16]` with scores on those same rows.
5. **Empty/unplayed matches in `Lad Div 1`.** Some matches have no scores in the score cells — only the helper "Work" cells contain `0`s (e.g. row 13 left block, row 15 left block, row 21 right block, row 23 right block, rows 29/31 both blocks, rows 37/39). Detect by: if both `set1_A` and `set1_B` are blank/None (and no tiebreak score), treat as `match_played = FALSE` and skip the match (do NOT insert), and surface in the quality report. Do NOT treat `0.0` as blank — `0.0` is a valid bagel set.
6. **Walkover / forfeit detection.** This file does not encode walkovers explicitly (no "WO" or "wo" or coloured cells reachable via `data_only=True`). The "missing scores" pattern in Lad Div 1 is the closest signal. T-P0-006 walkover handling should default to "unknown" for this file; the quality report should list the missing matches for admin review.
7. **Stray whitespace in pair strings.** `"Robert Attard/ Isaac Baldacchino"` (note the space after the slash) appears in `Players Men` and `Men Div 4`. Strip both halves after splitting on `/`. Do not collapse internal whitespace inside a single name (last names like `Treeby Ward` are two-word).
8. **Apostrophe variants.** `"Helga Azzopardi/Angele Pule'"` uses a trailing straight apostrophe in the surname `Pule'`. `"Duncan D'Alessandro"` uses an interior straight apostrophe. Both are stored straight in this file (no curly variants observed). Pass through verbatim.
9. **Non-breaking spaces in titles.** Cell `[1,1]` of every match sheet contains literal `\n` and the `Players Men` title `"Sports\xa0Experience\xa0Chosen\xa0Doubles\xa02025"` uses NBSP between words. Strip / replace NBSP when used in display strings.
10. **Sheet-name typos in headers.** Cell `[5,1]='Men Division 1 '` has a trailing space; `[5,1]='Ladies Division 1'` has none. Cell `[76,16]='Divison Winner'` (typo `'Divison'`) appears in Men Div 3, Men Div 4, Lad Div 3. Match string-prefix tolerantly.
11. **Standings-panel rows misaligned with match rows.** The `[31,…]` standings rows can land on a match-row `r` OR on the spacer row immediately after — they're independent of the match grid (e.g. `[24,31]='Mark Gatt/Manuel Bonello'` lives on a `vs.` row visually). Do not couple match extraction to standings extraction; treat them as independent passes.
12. **Standings panel position varies between single-group and two-group sheets.** Single-group: standings at AE col 31 fill rows 9–19 plus winner/runner-up at rows 22/24. Two-group: standings appear in **both** AE col 31 (group A standings) and again lower (group B standings start row 39+). The parser doesn't NEED standings for matches, so safest is to ignore the standings panel entirely for primary extraction.
13. **Lad Div 1 has 6 pairs but rank column shows two `5.0`s.** Rows 10 and 11 in `Players Ladies` both have rank `5`. This is a roster typo — the second one should be `6`. The parser must not deduplicate by rank.
14. **`Sets Won`/`Games Won` standings totals can verify match parses.** Per the standings panel: `Duncan D'Alessandro/Clayton Zammit Cesare` shows `Matches Played=5`, `Games Won=59`, `Sets Won=10`. After parsing all 5 of their matches, summing per-set games for Side-A across those rows must equal 59 and sets won = 10. Use this as an automated cross-check in the parser test suite.
15. **No per-match date.** The schema's `matches.played_on` is `NOT NULL` in PLAN.md §6 sketch. Either (a) use `'2025-01-01'` as a placeholder for every match in this file and document, or (b) loosen the schema to `played_on NULL`. T-P0-004 must pick one and align with T-P0-002.
16. **Tournament tie-break vs set-tiebreak.** A score of `7-6` or `6-7` in cols 2/5 (set 1/set 2) is a *set-internal* tiebreak (was_tiebreak=TRUE for that set). A score in cols 8/23 (the `Tie` columns) is a *match-deciding* 10-point super-tiebreak played in lieu of a third set; it should be stored as `set_number=3, was_tiebreak=TRUE` and the score values can exceed 10 (observed values: 24, 26 in some matches — these are from extended tiebreaks `e.g. 26-24`).

## Suggested parser test cases

Each test case below uses real data from the file — the parser must reproduce the listed extraction.

### Test case 1 — Clean 2-set win, left block, single-group division

- **Sheet:** `Men Div 1`
- **Anchor row:** `r=9`, **block:** left (col 1)
- **Expected match:**
  - `division = "Men Division 1"`
  - Side A pair: `"Duncan D'Alessandro/Clayton Zammit Cesare"` → players `["Duncan D'Alessandro", "Clayton Zammit Cesare"]`
  - Side B pair: `"Mark Gatt/Manuel Bonello"` → players `["Mark Gatt", "Manuel Bonello"]`
  - Set 1: A=6, B=4 (was_tiebreak=False)
  - Set 2: A=4, B=6 (was_tiebreak=False)
  - Match tiebreak (set 3): A=10, B=3 (was_tiebreak=True)
  - `match_sides[A].sets_won = 1, games_won = 10, won = TRUE` (won the deciding super-tiebreak)
  - `match_sides[B].sets_won = 1, games_won = 10, won = FALSE`
  - **Note:** when match is decided by super-tiebreak, both sides have sets_won=1 from the regular sets; the super-tiebreak resolves it. Encode `won` accordingly.

### Test case 2 — Right-block match, same row band, different opponents

- **Sheet:** `Men Div 1`
- **Anchor row:** `r=9`, **block:** right (col 16)
- **Expected match:**
  - Side A pair: `"Duncan D'Alessandro/Clayton Zammit Cesare"`
  - Side B pair: `"Gabriel Pace/Nikolai Belli"`
  - Set 1: A=6, B=0
  - Set 2: A=6, B=3
  - No match-tiebreak (cells at col 23 are blank for row 9 / col 24 has `0` helper)
  - `match_sides[A].sets_won = 2, games_won = 12, won = TRUE`
  - `match_sides[B].sets_won = 0, games_won = 3, won = FALSE`
  - **Demonstrates:** left and right blocks at the same row-band are *different* matches.

### Test case 3 — Two-group sheet, group B match, with super-tiebreak

- **Sheet:** `Men Div 3`
- **Anchor row:** `r=39`, **block:** left
- **Expected match:**
  - `division = "Men Division 3 - Group B"` (from row 35 label)
  - Side A pair: `"Dunstan Vella/Cyril Lastimosa"`
  - Side B pair: `"Manuel Mifsud/Julian Esposito"`
  - Set 1: A=3, B=6
  - Set 2: A=6, B=3
  - Match tiebreak: A=10, B=3
  - Side A wins.

### Test case 4 — Final block (split-name layout, Men Div 3)

- **Sheet:** `Men Div 3`
- **Anchor:** `'Final'` label at `[67,16]`; pair-A name at `[70,16]+[71,16]`, pair-A scores at row 71; pair-B name at `[73,16]+[74,16]`, pair-B scores at row 73.
- **Expected match:**
  - `round = 'final'`, `division = "Men Division 3"` (drop the group suffix for the final)
  - Side A pair: `"Dunstan Vella/Cyril Lastimosa"` (constructed from rows 70+71)
  - Side B pair: `"Neville Sciriha/Matthias Sciriha"` (constructed from rows 73+74)
  - Set 1: A=6, B=7
  - Set 2: A=0, B=6
  - No match-tiebreak (scores at col 23 are blank/None on rows 71 and 73)
  - Side B wins (`Neville Sciriha/Matthias Sciriha` is `Divison Winner` per `[77,16]`).

### Test case 5 — Lad Div 1 unplayed match (must NOT insert)

- **Sheet:** `Lad Div 1`
- **Anchor row:** `r=13`, **block:** left
- **Expected outcome:** parser detects empty score cells (`[13,2]`, `[13,5]`, `[15,2]`, `[15,5]` all None or blank) and **skips the match** (does not insert into `matches`). Surfaces an entry in the ingestion `quality_report_jsonb` under "missing matches" with `division="Ladies Division 1"`, `pair_A="Renette Magro/Diane Fenech"`, `pair_B="Martina Cuschieri/Elaine Grech"`, `reason="no scores recorded"`.
- **Counter-example same row band:** `r=13`, **block:** right (col 16) IS played: `"Renette Magro/Diane Fenech"` vs `"Kim Fava/Annmarie Mangion"`, set 1 = 6-4, set 2 = 4-6, match-tiebreak = 6-10. Side B wins. The parser must extract this right-block match even though the left-block sibling was skipped.

### Test case 6 (cross-validation) — Standings sum check

- **Sheet:** `Men Div 1`
- **After parsing all 15 matches**, sum the per-set games for `"Duncan D'Alessandro/Clayton Zammit Cesare"` across every row where they appear as side A or side B.
- **Expected sum:** `games_won = 59`, `sets_won = 10`, `matches_played = 5` — matches the standings panel at `[9,33..35]`.
- This is a parser-level integrity check, not a unit test on a single match.

---

## Summary stats (for parser sanity check)

| Sheet | Group A matches | Group B matches | Final | Total expected |
|---|---|---|---|---|
| Men Div 1 | 15 | — | — | 15 |
| Men Div 2 | 15 | — | — | 15 |
| Men Div 3 | 10 | 10 | 1 | 21 |
| Men Div 4 | 10 | 10 | 1 | 21 |
| Lad Div 1 | 15 (incl. several unplayed → fewer inserted) | — | — | ≤15 |
| Lad Div 2 | 15 | — | — | 15 |
| Lad Div 3 | 15 | 15 | 1 | 31 |
| **Total** | | | | **~133** matches expected (minus Lad Div 1 unplayed) |

Player count rough order: ~76 unique players (38 men pairs × 2 + 39 lady pairs × 2 minus a few cross-pair appearances; expect ~70–80).
