---
name: triage-cross-surface-failures
description: Correlate a failure across browser, API, service health, logs, traces, data state, commits, dependency changes, and resource pressure without silently repairing it. Use for flaky scenarios, multi-service incidents, blocked campaigns, ambiguous ownership, or evidence-backed rerun planning.
---

# Triage Cross-Surface Failures

1. Preserve the original failed state and identify the exact run/scenario.
2. Build a time-ordered evidence set using propagated correlation IDs where available.
3. Locate the first violated contract and its canonical owner before naming a root cause.
4. Distinguish reproducible defect, expected denial, environment blocker, resource failure, flaky behavior, harness defect, and insufficient assertion.
5. Reproduce with the narrowest deterministic scenario and no unrelated mutation.
6. State proven facts, hypotheses, contradictions, and missing visibility separately.
7. Propose the smallest repair and the neighboring rerun set. Implement only if requested.
8. Retain the original failure artifact even after a successful rerun.
