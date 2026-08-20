---
name: validate-engineering-outcomes
description: Discover repositories, map architecture and contracts, validate calculations and runtime surfaces, test result-aware interfaces, enforce data-readiness and ambient-write gates, validate deployment safety, run focused rebuilds, reconcile evidence, and adapt validation to resource pressure. Use for implementation review, integration testing, or release acceptance.
---

# Validate Engineering Outcomes

1. Inventory the repository read-only and identify canonical owners before proposing changes.
2. Map request to contracts, dependencies, effects, tests, evidence, and rollback.
3. Read only the relevant reference.
4. Run the smallest authoritative validation first; serialize heavy lanes.
5. Reconcile claimed results with postconditions and current evidence. Do not certify interrupted or partial runs.
6. For this bootstrap framework, run `scripts/audit_bootstrap.py --root <framework>` from this skill directory. Add `--strict-external-evidence` only in the source workspace where parent quarantine manifests are expected. Write reports only to explicitly approved paths.

- Repository, architecture, and contracts: [repository-contracts.md](references/repository-contracts.md)
- UI, data readiness, ambient writes: [result-aware-validation.md](references/result-aware-validation.md)
- Deployment, focused testing, evidence, resources: [deployment-evidence.md](references/deployment-evidence.md)
- Containers, services, routes, and interactive surfaces: [runtime-surface-evidence.md](references/runtime-surface-evidence.md)
- Formulas, dimensions, thresholds, and replay cases: [calculation-evidence.md](references/calculation-evidence.md)

Treat check totals as derived data, never fixed requirements. A file-existence pass cannot substitute for contract validation, graph freshness, integration smoke tests, an installed-wheel run, or outcome evidence.

Use a strict total denominator: `passed + failed + blocked + skipped + uncertain = total required checks`. A required blocked, skipped, or uncertain check prevents a completion claim unless an authorized scope decision removes it and records the residual risk.

For deterministic replay, freeze and record the input set, engine/runtime identity, dependency lock, configuration, seed, clock source, and serialization rules. Do not branch on ambient wall-clock time. Persist stable ordered output and ignore only fields explicitly declared volatile before the run. Any unexplained replay difference is a failed or uncertain result, never an automatic tolerance.

For changed behavioral logic, require a discriminating-test check: remove or invert the changed condition in an isolated copy and prove the focused test fails. Equivalent mutants require an explicit reviewed rationale. A test that remains green when the behavior is removed cannot certify the change.

For native or long-running Python work, validate bounded worker pools, GIL release where appropriate, event-loop offload, cancellation checkpoints, partial-progress semantics, mutation serialization or snapshot reads, and post-fork reinitialization. A syntactically async wrapper that blocks the event loop is a failed runtime surface.
