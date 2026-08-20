---
name: dual-axis-code-review
description: Review changes independently for repository standards and specification fidelity, then reconcile findings.
---

# Dual-Axis Code Review

Freeze a comparison point first. Review only the intended diff.

Run two independent passes:
1. Standards: repository rules, architecture, security, maintainability, tests, and code smells.
2. Specification: required behavior, acceptance criteria, edge cases, and explicit non-goals.

Neither pass may use the other pass's conclusions. Reconcile afterward, deduplicate by root cause, and classify findings as blocking, corrective, advisory, or false positive. Every finding needs exact evidence and a minimally sufficient repair.
