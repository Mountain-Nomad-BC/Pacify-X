---
name: repair-corrupted-text
description: Detect, repair, and verify OCR/PDF/encoding corruption with deterministic mappings, bounded heuristics, provenance, and reversible outputs before indexing or model ingestion. Use for garbled text, repeated-character artifacts, broken tokens, encoding substitutions, or large corpora where unconstrained generative correction is unsafe.
---

# Repair Corrupted Text

1. Preserve the original input and compute its hash.
2. Build a reviewed, versioned replacement map from observed corruption pairs.
3. Apply exact token replacements before bounded structural heuristics.
4. Protect URLs, identifiers, code, measurements, and domain tokens from broad substitutions.
5. Emit repaired text separately with counts, changed spans, mapping version, and output hash.
6. Flag unresolved/high-change records for human review instead of guessing.
7. Compare representative samples and downstream retrieval behavior before promotion.
8. Keep generative suggestions outside the automatic path unless individually reviewed and added to the mapping.

Use `scripts/repair_text.py` for deterministic UTF-8 text or JSON-string repair. Preview is the default; writing requires an explicit output path.
