---
name: data-sort-dry-run-picker
description: Benchmark and select a correct bulk-data sorting strategy without mutating source data; use when JSON, JSONL, CSV, or line data requires a measured algorithm choice or a bounded sample for oversized input.
---

# Data Sort Dry-Run Picker

Use the canonical Pacify-X script `.agents/skills/data-sort-dry-run-picker/scripts/sort_picker.py`.

1. Fingerprint and count the source.
2. Use the full input only within the declared sample budget; otherwise use deterministic reservoir sampling.
3. Pilot every compatible admitted algorithm.
4. Advance the three fastest correct candidates.
5. Benchmark repeatedly and verify reference order, count, multiset, and stability.
6. Select the fastest passing median and retain the receipt.
7. Require an external merge plan when full data does not fit memory.

Never write sorted output during the dry run or benchmark quadratic/novelty sorts on bulk data.
