---
name: context-compactor
description: Compress repeated progress and context within an explicit item budget while preserving failures, uncertainty, authority boundaries, recovery instructions, evidence, goals, and unresolved work. Use at context checkpoints, handoffs, or bounded multi-agent status aggregation.
---

# Context Compactor

1. Classify every message before compression.
2. Preserve every failure, uncertainty, authority boundary, recovery instruction, and evidence record verbatim or by an integrity-bound reference.
3. Group only genuinely repeated optional progress messages.
4. Reject a budget that cannot contain all mandatory records; never make safety information fit by dropping it.
5. Emit retained source identities, explicit dropped identities, the original and retained denominators, and a deterministic receipt hash.
6. Keep the operation read-only and authority-neutral.

Use `runtime.reasoning_controls.compact_communication` for the deterministic implementation. Completion requires positive repetition compression, mandatory-category retention, and budget-insufficient tests.
