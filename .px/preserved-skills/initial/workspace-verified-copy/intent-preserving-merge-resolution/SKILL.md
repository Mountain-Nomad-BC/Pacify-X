---
name: intent-preserving-merge-resolution
description: Resolve merge and rebase conflicts by reconstructing each side’s intent and preserving both valid outcomes.
---

# Intent-Preserving Merge Resolution

Never resolve conflicts by choosing the newer-looking block.

For each hunk:
1. Identify the base and the independent intent of ours and theirs from commits, tests, issues, and neighboring changes.
2. State the invariants each side intended to preserve.
3. Choose: keep one, combine, re-express both, or escalate because intents conflict.
4. Repair tests/contracts to prove the combined result.
5. Search for semantic conflicts outside marked hunks: renamed symbols, changed schemas, duplicated behavior, and mismatched generated files.
6. Finish the merge/rebase only after repository validation. Do not abort unless the user requests abandonment.
