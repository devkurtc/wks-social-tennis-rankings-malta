---
name: inspect-xlsx
description: Dump the structure of a tournament Excel file — sheet inventory, dimensions, and the first ~25 rows of each sheet. Use when you need to understand the layout of a file in `_DATA_/` before writing a parser, debugging a parse failure, or making a schema decision. For deeper structural analysis (parser-ready spec, edge cases, schema mapping) use the `tennis-data-explorer` agent instead.
---

# inspect-xlsx

When invoked, take the path(s) provided as arguments and produce a quick structural read of each `.xlsx` / `.xls` file. Goal: enough information to decide what kind of tournament this is and where the data lives, without spending a full agent turn on it.

## Procedure

Use Python with `openpyxl` (already installed system-wide; pandas is NOT installed). Read with `data_only=True` so formula cells return their computed values.

```python
import openpyxl
from pathlib import Path

def inspect(path: str, max_rows: int = 25, max_cols: int = 12) -> None:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    print(f"\n{'='*72}\n{Path(path).name}\n{'='*72}")
    print(f"Sheets ({len(wb.sheetnames)}): {wb.sheetnames}")
    for name in wb.sheetnames:
        ws = wb[name]
        print(f"\n--- {name}  ({ws.max_row} rows × {ws.max_column} cols) ---")
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows:
                break
            populated = [c for c in row if c is not None]
            if populated:
                print(f"  {i:3d}  {row[:max_cols]}")
```

After the dump, give a one-paragraph read-out covering:

1. **Format guess**: division round-robin / team tournament / knockout bracket / unknown
2. **Where the matches are**: which sheet(s), where rows start, how matches are visually separated (blank rows, alternating row colors)
3. **Anything weird**: merged headers, formulas that look like data, mixed apostrophe encodings in player names, sheet-name typos, missing fields

## When NOT to use this skill

- For producing a parser-ready specification (recipe for each field, schema mapping, edge-case enumeration), use the `tennis-data-explorer` agent — that's an exploratory task, not a procedural dump.
- For comparing many files to identify "template families," use the agent — it can read several in one pass and reason about commonalities.
- Don't use this to ingest data into the schema; that's a different job (Phase 1 parsers).

## Notes

- Be careful with player names: VLTC files mix curly (`'`) and straight (`'`) apostrophes for the same player. Quote names verbatim in your output — don't normalize. Normalization is a downstream concern (PLAN.md §5.4).
- `~$*.xlsx` files in `_DATA_/` are Excel lock files; ignore them.
- `data_only=True` requires the file to have been opened in Excel at some point so formulas have cached results. If you see all `None` where you expect values, suspect this.
