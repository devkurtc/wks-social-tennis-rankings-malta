# Parser spec — TCK Chosen Tournament Divisions 2024

**Source file:** `_DATA_/VLTC/TCK CHOSEN TOUNAMENT DIVISIONS 2024.xlsx` (note the
typo "TOUNAMENT" in the actual filename — kept verbatim).

Produced for parser-implementer task T-P0-014 sub-deliverable.

## File(s) analyzed

- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/TCK CHOSEN TOUNAMENT DIVISIONS 2024.xlsx`

## Format classification

**Flat-list division round-robin** (one match per row, with explicit
DATE/TIME/COURT/DIV columns). Confidence: high.

This is **not** the side-by-side block layout used by Sports Experience /
ESS / Elektra parsers. Each row is a single match (no left/right blocks).
Pairs are stored as `"PLAYER1 / PLAYER2"` strings in two separate columns
(one per side); the score is a single string in column 8 (and occasionally
column 9 for SCRATCHED override scores).

Tournament format on `tournaments.format` should be `'doubles_division'`
(divisional round-robin, fixed pairs — same family as SE/Mixed even
though the row layout differs).

## Sheet map

| Sheet         | Role                       | Notes                                       |
| ------------- | -------------------------- | ------------------------------------------- |
| `MEN 1ST DIV` | Roster + flat match list   | Roster rows 6–12, header row 15, matches 17+ |
| `MEN 2ND DIV` | Roster + flat match list   | Roster rows 6–12, header row 15, matches 17+ |
| `MEN 3RD DIV` | Roster + flat match list   | Roster rows 6–9,  header row 13, matches 15+ |
| `LDYS 1ST DIV`| Roster + flat match list   | Roster rows 6–12, header row 15, matches 17+ |
| `LDYS 2ND DIV`| Roster + flat match list   | Roster rows 6–9,  header row 13, matches 15+ |

The roster (rows 6–12 / 6–9) lists the entered pairs with rank numbers in
col 4 and pair string in col 5. We do NOT need the roster for parsing —
every pair appears in match rows. The header row is `['DATE', 'TIME',
'COURT', 'DIV', 'TEAM', 'VS', 'TEAM', 'RESULTS']` in cols 1..8.

## Extraction recipe

For each match-data sheet:

| Field         | Sheet | Row anchor                                         | Col anchor | Notes |
| ------------- | ----- | -------------------------------------------------- | ---------- | ----- |
| division      | sheet name → mapped string                         | —          | See sheet→division map below |
| gender        | sheet-name prefix                                  | —          | `'MEN'` → 'M', `'LDYS'` → 'F' |
| date          | from "RESULTS" header row + 2 onwards              | col 1      | Excel datetime — use `datetime.date()` part as ISO |
| pair A string | same row                                           | col 5      | Always contains a `/` separator |
| pair B string | same row                                           | col 7      | Same |
| score string  | same row                                           | col 8      | OR col 9 fallback if col 8 == "SCRATCHED" with col 9 set |
| walkover flag | when score string is `W/O` / `W/0` / `wo` / `SCRATCHED` | — | Set `match.walkover = 1`, use 6-0 placeholder |

**Iteration rule:** find the row with `cell(r, 8) == 'RESULTS'` to locate the
header, then iterate every row from `header_row + 2` to `ws.max_row`. Skip
blank rows (no col-1 date AND no col-5 team). For each non-blank row, attempt
to parse: requires both col 5 and col 7 to be non-empty pair strings.

### Sheet → division/gender map

| Sheet name      | division string         | gender |
| --------------- | ----------------------- | ------ |
| `MEN 1ST DIV`   | `Men Division 1`        | M      |
| `MEN 2ND DIV`   | `Men Division 2`        | M      |
| `MEN 3RD DIV`   | `Men Division 3`        | M      |
| `LDYS 1ST DIV`  | `Ladies Division 1`     | F      |
| `LDYS 2ND DIV`  | `Ladies Division 2`     | F      |

## Score-string parser

Scores are space-separated set tokens, e.g. `"7-5   6-1"`, `"6-4   5-7   10-4"`.
- Each token is `<int>-<int>`.
- 1-2 sets are *normal sets*. A 3rd set with both numbers > 7 is a *match
  super-tiebreak* (10-point) — `was_tiebreak = TRUE` for that set in
  `match_set_scores`.
- A 3rd set with normal-set values (e.g. `7-5`) is also a normal set
  (best-of-3). Heuristic: super-TB iff `set_number == 3` AND `max(a,b) >= 9`.
- A set like `7-6` (or `6-7`) is a *normal-set tiebreak* — set the
  `was_tiebreak` flag for that set as well (matches the SE-parser
  convention `ga == 7 or gb == 7`).
- Walkover tokens: `W/O`, `W/0` (typo), `wo`, `WO`, `SCRATCHED` →
  `match.walkover = 1`, insert one set row `(1, 6, 0, 0)` to side A as
  the placeholder. Side A wins by default — there is no annotation in the
  source file telling us which side took the W/O. **Best the parser can do:
  attribute the walkover win to side A (the listed first team), per the
  hard rule.** This is a known data-quality limitation; rating engine treats
  walkovers with a discounted weight.
- For `SCRATCHED` rows that ALSO have a real score in col 9, prefer the
  col-9 score for the per-set rows but still flag `walkover = 1` and the
  winner is determined from the set score normally.

## Schema mapping

| Extracted field | Target table.column                                                  | Transform |
| --------------- | -------------------------------------------------------------------- | --------- |
| date            | `matches.played_on`                                                  | ISO 8601 |
| division        | `matches.division`                                                   | as-is from map |
| pair A players  | `match_sides` side='A', via `_split_pair` → `get_or_create_player`   | strip + apostrophe normalize via players_mod |
| pair B players  | `match_sides` side='B', same                                         |  |
| set scores      | `match_set_scores` rows                                              | per-set, with `was_tiebreak` for 7-X sets and 10-pt super-TB |
| walkover        | `matches.walkover`                                                   | 0/1 |
| match_type      | `'doubles'` (constant)                                               |  |
| tournament      | `tournaments.name = 'TCK Chosen Tournament 2024'`, year 2024, format `'doubles_division'` | from cell [2,1] of any sheet |
| gender          | `players.gender` (set on first sight if NULL)                        | per-sheet |

## Edge cases to handle

1. **Walkover tokens (`W/O`, `W/0`, `wo`, `WO`)** — `_is_walkover()` should
   match all of these case-insensitively. Default the walkover winner to
   side A.
2. **`SCRATCHED`** — Same as walkover. If col 9 has a score, use it for set
   rows; otherwise insert a placeholder 6-0 first set.
3. **Trailing whitespace in score strings** — `'3-6   7-5   10-5   '` —
   strip trailing whitespace; tolerate variable inner whitespace via `split()`.
4. **Pair strings with leading/inner whitespace** — `' FAVA ANNA /ANDREOZZI LUISA'`
   — `_split_pair` (re-used from sports_experience_2025) already strips per half.
5. **Spaces around `/`** in pair strings — `'BORG RUBEN / MARTINELLI JONATHAN '`
   vs `'ADRIAN MANDUCA /FARRUGIA MELCHIOR'` — same splitter handles both.
6. **Incomplete matches** — e.g. row 39 of MEN 1ST DIV has both teams listed
   but no result in col 8. Log to stderr and skip.
7. **Missing date** — extremely rare but possible (none observed). If date
   is None, fall back to `2024-01-01` and log to stderr.
8. **Unknown sheet names** — be permissive; if `MEN 4TH DIV` ever appears,
   the sheet→division map should fall back to deriving `'Men Division N'`
   from the sheet-name digit. Keep an explicit warning if the prefix isn't
   `MEN` or `LDYS`.
9. **Header may be at row 13 OR row 15** — depends on roster size. Find it
   dynamically by scanning col 8 for `'RESULTS'`.

## Suggested parser test cases

1. **MEN 1ST DIV r17** — Adrian Manduca/Farrugia Melchior vs Magri Gareth/Magri
   Daryl, score `'7-5   6-1'`, date 2024-06-30, division `Men Division 1`. Expect
   2 set rows: (1, 7, 5, 1=tiebreak), (2, 6, 1, 0). Side A wins. Not a walkover.
2. **MEN 1ST DIV r18** — Micallef Nikolai/Borg Mattew vs Schembri David/Attard
   Jean Pierre, score `'W/O'`, date 2024-06-30. Expect `walkover = 1`, one
   placeholder set (1, 6, 0, 0), side A wins.
3. **MEN 1ST DIV r24** — `'W/0'` typo variant — same handling as W/O.
4. **MEN 1ST DIV r26** — score `'6-4   5-7   10-4'` (super-tiebreak match). Expect
   3 set rows: (1, 6, 4, 0), (2, 5, 7, 1=tiebreak), (3, 10, 4, 1=match TB).
   Side A wins (1 normal set + super-TB). Not a walkover.
5. **LDYS 1ST DIV r17** — Score string is `'SCRATCHED'` in col 8 with `'2-6   3-6'`
   in col 9. Expect `walkover = 1`, set rows from col-9 score (1, 2, 6, 0),
   (2, 3, 6, 0). Side B wins per the recorded score.
6. **MEN 3RD DIV r23** — score `'3-6   7-5   10-5   '` (trailing whitespace) —
   parses cleanly to 3 set rows; side A wins.
