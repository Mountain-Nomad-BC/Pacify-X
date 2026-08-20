---
name: inspect-llm-architecture
description: Inspect an LLM configuration without importing model code, normalize architecture fields, classify attention and model topology, and estimate parameter, weight, and KV-cache requirements with explicit assumptions. Use for unknown model configs, architecture comparisons, VRAM estimates, long-context feasibility, quantization planning, MoE review, or evidence-backed local deployment analysis.
---

# Inspect LLM Architecture

1. Read configuration as hostile data. Never import repository or remote model code to inspect it.
2. Run `scripts/inspect_llm_architecture.py --config CONFIG.json`; add `--workload WORKLOAD.json` for memory estimates.
3. Preserve field-level evidence, inferred defaults, warnings, unresolved fields, and formula version.
4. Reject impossible dimensions, booleans masquerading as integers, excessive allocations, and inconsistent head topology.
5. Treat parameter and memory results as architecture estimates. Require measured runtime peaks before deployment certification.
6. Compare advertised and effective context separately; require task-quality testing across position and depth.
7. Pass the normalized profile to `plan-local-model-deployment` only after compatibility and trust gates are explicit.

Read [architecture-inspection-contract.md](references/architecture-inspection-contract.md) when reviewing formulas, limits, MoE estimates, or long-context evidence.

## Completion

Return the normalized profile, assumptions, warnings, unresolved fields, estimates, security statement, and required runtime validations. Do not claim model support from filenames, marketing labels, or a successful configuration parse.
