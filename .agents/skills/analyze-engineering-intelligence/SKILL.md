---
name: analyze-engineering-intelligence
description: Detect architecture drift, dependency shockwaves, semantic contract changes, knowledge collisions, future debt, code structure changes, engineering health gaps, and refactoring candidates. Use when assessing the impact or fitness of a repository or proposed change from bounded manifests and source excerpts.
---

# Analyze Engineering Intelligence

Use compact manifests before source bodies. Read [analysis-contract.md](references/analysis-contract.md) for accepted inputs and result semantics.

1. Establish the baseline and current snapshot hashes.
2. Select only the analyses relevant to the request.
3. Keep unknown dimensions explicit; do not convert missing telemetry into a passing score.
4. Trace findings to components, contracts, or source hashes.
5. Produce prioritized proposals with validation and rollback needs.
6. Never apply a refactor or architecture change automatically.

For research-derived mechanisms, require a citation and local reproduction plan. Publication and cross-paper convergence may justify a candidate experiment, not production admission.

Fail closed when baselines, ownership, evidence, or effect boundaries are missing.
