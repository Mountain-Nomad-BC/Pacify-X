---
name: data-sort-dry-run-picker
description: Benchmark and select a correct bulk-data sorting strategy without mutating source data. Use for JSON, JSONL, NDJSON, CSV, or line-oriented datasets when a sort must be chosen from measured evidence, especially when the full input is too large for an in-memory experiment.
---

# Data Sort Dry-Run Picker

Use `scripts/sort_picker.py` to measure the input, take a deterministic bounded sample when necessary, pilot compatible algorithms, benchmark the three fastest correct candidates, and emit a traceable decision receipt.

## Procedure

1. Identify format, record count, byte size, key path, ordering, stability requirement, memory ceiling, and whether external sorting may be required.
2. Run a dry run. Never overwrite or emit a sorted dataset during selection.
3. Verify the receipt records the input SHA-256, sample SHA-256, sampling policy, candidate compatibility reasons, pilot traces, final traces, correctness, stability, and selected algorithm.
4. Reject every candidate that differs from the reference order, loses/duplicates records, violates a required stability contract, errors, or exceeds the bounded run.
5. Select the fastest remaining candidate by median elapsed time. Treat differences inside measurement noise as ties and prefer the simpler/native/stable option.
6. For data larger than available memory, use the decision only for chunk-local sorting and choose an external merge plan for the full run.
7. Preserve the receipt with the orchestration evidence before executing any real bulk mutation.

```powershell
python scripts/sort_picker.py --input data.jsonl --key customer.id --sample-records 50000 --repeats 5 --output sort-decision.json
```

Read [references/sorting-algorithms.md](references/sorting-algorithms.md) when interpreting candidates, handling external data, or selecting an algorithm not implemented by the dry-run harness.

## Guardrails

- Require homogeneous, total-order keys; fail on missing, mixed, NaN, or non-scalar keys unless an explicit normalization step is separately defined.
- Use a deterministic seed and never claim a sample proves full-data distribution.
- Keep Python's Timsort as the reference implementation, not an automatically guaranteed winner.
- Do not benchmark quadratic algorithms on bulk samples; Bubble, Selection, Insertion, Gnome, Cocktail, and related sorts remain teaching/tiny-input knowledge.
- Do not infer fastest from Big-O alone. Record actual input shape, implementation, runtime, hardware context, repeats, and variance.
- Do not use Counting/Bucket/Radix without bounded numeric-domain evidence.
- Require an external merge/run-generation plan when the source plus working set cannot fit the declared memory budget.

## Completion

Return the selected algorithm, why it was compatible, sample coverage, correctness evidence, median/p95 time, rejected candidates, residual risks, and receipt path. No algorithm is selected if fewer than one candidate passes all correctness gates.
