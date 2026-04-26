# Parser specification — VLTC Mixed Doubles + division-template family

## File(s) analyzed

- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/ESS Mixed Tournament Div and Results 2025.xlsx`
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/ESS Mixed Tournament Div and Results 2024.xlsx`
- `/Users/kurtcarabott/WKS-SOCIAL-TENNIS/_DATA_/VLTC/Elektra Mixed Tournament Div and Results 2023.xlsx`

(Plus the existing `Sports Experience Chosen Doubles 2024 result sheet.xlsx` works
with the existing `sports_experience_2025.py` parser as-is — `83 matches, 76 players`.)

## Format classification

**Format:** VLTC division round-robin doubles with **dynamically-positioned**
sub-blocks per sheet. Same template family as `sports_experience_2025.py` —
two side-by-side match blocks (cols A–N and P–AC), `vs.` divider, set scores
in cols 2/5/8 and 17/20/23 — but with sheet names `Division 1`..`Division N`
and sub-block positions that *vary per file/division* (not hard-codable).
**Confidence:** high.

## Sheet map

| Sheet | Role | Notes |
|---|---|---|
| `Players` | Roster | Block per division at increasing rows. Source of pair lists per division. Not required for match extraction (parser uses match sheets directly). |
| `Division 1`..`Division N` | Matches | Same column layout as SE 2025. Row 5 = primary division/group label. May contain additional sub-block labels at variable later rows (e.g. `'Division 6 - Group B'` at row 31 in ESS 2025; `'Division 5 - Group B'` at row 60 in ESS 2024; `'Division 6 - Round 1'` / no label at row 33 for `Round 2` in ESS 2024). May contain a `Final` block in the right-hand column (cell `[r,16]='Final'`) below all groups. |

## Key differences from sports_experience_2025

1. **Sheet names are `Division N`** (no Men/Lad split — these are mixed doubles).
2. **No reliable per-sheet gender** — leave `players.gender` NULL (Phase 1+ resolves cross-file).
3. **Sub-block positions vary per file** — must be dynamically discovered:
   - Scan col 1 (left block) for label rows matching `Division N`, `Group X`,
     `Round X`, or labels containing those substrings.
   - For each label row, the sub-header is typically `label_row + 2`, and the
     first match anchor is `label_row + 4`.
   - Some sub-blocks have *no* label and start with just a header re-emission
     (e.g. ESS 2024 Div 6 Round 2: row 33 has `2='Score'`, row 34 = first
     match). Defensive fallback: treat any cell at col 1 with a pair string
     and a `vs.` divider 1 row below as a match anchor, regardless of
     preceding label.
4. **Pair separator is `' / '`** (space-padded) in these files vs. `'/'` in SE 2025.
   The existing `_split_pair` already strips after splitting on `/`, so this
   works without modification.
5. **Final block layout** — single-row pair-string format only (no split-name
   variant like SE 2025 Men Div 3). Anchor: `[r,16]='Final'`, then 4 rows
   below: `[r+4,16]=Pair A string`, `[r+5,16]='vs.'`, `[r+6,16]=Pair B string`,
   scores on the same rows as the pair names.
6. **`'Divison Winner'` typo** appears in these files too.

## Extraction recipe (delta from sports_experience_2025 spec)

| Field | Source | Transform |
|---|---|---|
| `tournament.name` | Cell `[1,1]` of any match sheet (e.g. `'ESS Mixed Doubles 2025'`) | strip NBSP, take first non-empty line |
| `tournament.year` | filename year (last 4-digit substring) | int |
| `tournament.format` | constant | `'doubles_division'` (per project convention — mixed is still doubles) |
| `matches.played_on` | placeholder | `'<year>-01-01'` (no per-match date in file) |
| `matches.match_type` | constant | `'doubles'` |
| `matches.division` | sub-block label (verbatim) | e.g. `'Division 6 - Group A'` |
| `matches.round` | `'final'` for Final-block matches; NULL otherwise | string |
| `players.gender` | (no source) | leave NULL — can be inferred per-file in a Phase 1 reconciliation |

All other extraction logic is unchanged from `sports_experience_2025.py`.

## Sub-block discovery algorithm

For each `Division N` sheet:

```
walked_anchors = set()
for r in 1..ws.max_row:
    label = ws.cell(r, 1).value
    if isinstance(label, str) and looks_like_division_or_group_label(label):
        # Scan forward for the first match anchor (a row where col 1 is a
        # pair string AND col 1 of row+1 is 'vs.').
        for off in range(1, 8):
            r0 = r + off
            if r0 in walked_anchors:
                break
            if is_pair_string(cell(r0, 1)) and is_vs(cell(r0+1, 1)):
                division_for_block = label
                walk_matches_starting_at(r0, division_for_block)
                break

# Defensive sweep for un-labeled sub-blocks (e.g. "Round 2" with no label):
for r in 1..ws.max_row:
    if r in walked_anchors:
        continue
    if is_pair_string(cell(r, 1)) and is_vs(cell(r+1, 1)) and is_pair_string(cell(r+2, 1)):
        # Inherit the most recent division label seen above this row.
        walk_matches_starting_at(r, last_label_seen)

# Final block:
for r in 1..ws.max_row:
    label = cell(r, 16).value
    if isinstance(label, str) and label.strip().lower() == 'final':
        extract_final_at(r)  # using single-row layout
        break
```

The walker matches `sports_experience_2025._iter_group_matches`: start at
`r0`, step `+4` while `cell(r, 1)` is a pair-string. Each step yields the
left-block match (cols 1–14) and right-block match (cols 16–29) at the same
row band.

## Edge cases

1. **Missing roster gender** — Mixed doubles file has both genders mixed per
   pair. Don't write `players.gender` from this parser.
2. **Pair separator with spaces** — `' / '` vs `'/'`: the existing splitter
   handles this (split on `/`, strip each half). No code change needed.
3. **Sub-block with no label** (ESS 2024 Div 6 row 33+: just a sub-header
   row with `'Score'` cells, no `'Round 2'` text). Defensive sweep catches
   these.
4. **`'Divison Winner'` typo** — same as SE 2025.
5. **Empty score cells** at end of group (last row often has only one
   block populated; right block empty). Same skip logic as SE 2025.
6. **Walkovers represented as score = 0-0 / 0-0** (e.g. ESS 2025 Div 5 row 21
   right block = 0-0 / 4-0 means actual unfinished match). The parser does
   NOT special-case these — `0-0` is a legitimate (if degenerate) set per the
   SE 2025 rule. Surfacing walkovers is a Phase 1 QA task.
7. **Final block missing in some files** — Most ESS/Elektra divisions don't
   have a Final block (only Div 6 in ESS 2025 has one). The parser scans
   for `'Final'` and processes it if present, otherwise skips silently.
8. **'Sports Experience Chosen Doubles 2024'** — has the SAME sheet names
   as SE 2025 (`Men Div 1`, `Lad Div 1`, etc.) and works with the existing
   `sports_experience_2025.py` parser without modification. Dispatch routes
   it there.

## Schema mapping

Same as `sports_experience_2025.py` except `players.gender` is left NULL.

## Suggested parser test cases

Cases drawn from real data:

### Test 1 — ESS 2025 Division 1, first match left block (clean tiebreak)

- Sheet: `Division 1`, anchor `r=13` left block
- Side A: `"Matthew Mifsud / Lara Pule'"` → `["Matthew Mifsud", "Lara Pule'"]`
- Side B: `"Duncan D'alessandro / Renette Magro"` → `["Duncan D'alessandro", "Renette Magro"]`
- Set 1: A=5, B=7 (was_tiebreak=True per the 7 rule)
- Set 2: A=0, B=6
- No super-tb
- Side B wins 0-2

### Test 2 — ESS 2025 Division 6 Group A, sub-block detection

- Sheet: `Division 6`, label at `[5,1]='Division 6 - Group A'`, first match `r=9`
- Side A: `"Dayle Scicluna / Alida Borg"`
- Side B: `"Dunstan Vella / Tiziana Spiteri"`
- Set 1: A=3, B=6 ; Set 2: A=6, B=4 ; Super-tb: A=10, B=5
- Side A wins
- `division == "Division 6 - Group A"`

### Test 3 — ESS 2025 Division 6 Group B match, dynamically-positioned

- Sheet: `Division 6`, label at `[31,1]='Division 6 - Group B'`, first match `r=35`
- Side A: `"Cory Greenland / Sabrina Xuereb"`
- Side B: `"Steve Gambin / Suzanne Gambin"`
- Set 1: A=6, B=2 ; Set 2: A=6, B=3 ; no super-tb
- Side A wins 2-0
- `division == "Division 6 - Group B"`

### Test 4 — ESS 2025 Division 6 Final block (single-row pair string)

- Sheet: `Division 6`, `[58,16]='Final'`, pair A string at `[62,16]`
- Side A: `"Daye Scicluna/Alida Borg"` (note: typo in file — `Daye` not `Dayle`)
- Side B: `"Cory Greenland/Sabrina Xuereb"`
- Set 1: A=7, B=6 (tiebreak) ; Set 2: A=3, B=6 ; super-tb: A=7, B=10
- Side B wins
- `round == "final"`, `division == "Division 6"` (group suffix dropped)

### Test 5 — ESS 2024 Division 5 Group B (label at row 60)

- Sheet: `Division 5`, label at `[60,1]='Division 5 - Group B'`, first match `r=64`
- Side A: `"Juan Sammut / Maria Angela Gambin"`
- Side B: `"Dayle Scicluna / Alida Borg"`
- Set 1: A=6, B=0 ; Set 2: A=6, B=3 ; no super-tb
- Side A wins 2-0
- `division == "Division 5 - Group B"`

### Test 6 — Smoke test: count matches per file

| File | Expected match count (rough) |
|---|---|
| ESS Mixed 2025 | ≥80 |
| ESS Mixed 2024 | ≥80 |
| Elektra Mixed 2023 | ≥60 |

The parser must produce at least these counts (within ±10) given the file
structure. Exact counts are validated by inspection per-load.
