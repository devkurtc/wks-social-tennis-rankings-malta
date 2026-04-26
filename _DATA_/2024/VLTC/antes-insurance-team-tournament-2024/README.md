# Antes Insurance Team Tournament 2024

**Source:** Local file upload

## Local file upload

- `Antes Insurance Team Tournament  results sets .xlsx` — local file moved here from `_DATA_/_unsorted/` after the
  reorganization confirmed its year. File mtime: 2025-05-24 23:49 UTC.

The parser dispatcher in `scripts/phase0/cli.py` matches on filename substring
after lowercasing, so this file can be loaded directly with `cli.py load --file <path>`.
