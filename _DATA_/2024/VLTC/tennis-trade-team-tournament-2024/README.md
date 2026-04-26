# Tennis Trade Team Tournament 2024

**Source:** Local file upload

## Local file upload

- `Results Tennis Trade Team Tournament(1).xlsx` — local file moved here from `_DATA_/_unsorted/` after the
  reorganization confirmed its year. File mtime: 2025-02-03 02:36 UTC.

The parser dispatcher in `scripts/phase0/cli.py` matches on filename substring
after lowercasing, so this file can be loaded directly with `cli.py load --file <path>`.
