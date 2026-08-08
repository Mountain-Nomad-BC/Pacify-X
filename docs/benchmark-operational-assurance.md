# Benchmark Operational Assurance

PACIFY-X separates measurement from improvement. A benchmark is evidence about a fixed treatment, not an interactive training session.

## Operating lanes

1. **Preflight** validates the harness, oracle, dependencies, permissions, and evidence sink. A failed preflight is not a scored failure.
2. **Cold** executes the frozen treatment without visible protected cases, visible oracles, or benchmark-informed changes.
3. **Control** repeats the same treatment with PACIFY-X disabled. `comparison_hash` must match the enabled profile.
4. **Analysis** begins only after cold artifacts are hashed and sealed.
5. **Improvement** creates candidates. It does not mutate source, prompts, memory, routing, or policy.
6. **Regression** evaluates admitted changes on independent and held-out cases.

## Required profile

Create a JSON execution profile containing `schema_version`, `run_id`, `lane`, and these treatment sections:

- benchmark identity, version, dataset and harness hashes;
- agent identity and version;
- model, provider, reasoning mode, and generation settings;
- PACIFY-X version, commit, enabled state, and admitted capabilities;
- time, context, credit, concurrency, and resource limits;
- permissions, tools, network, and effect grants;
- retry count and retryable failure classes;
- environment, container, cache, memory, and hardware route.

Run `freeze_execution_profile`. Store the returned `frozen_hash` with every attempt. Any treatment change requires a new run identity; it is never a retry.

Cold profiles must declare memory and cache as `disabled`, `empty`, or `ephemeral_empty`. Test-only capabilities are admitted only when the caller explicitly declares `execution_mode=benchmark`; ordinary runtime contexts cannot activate them.

## Preflight and retries

`evaluate_preflight` must return `scoreable: true` before a graded attempt. `decide_benchmark_retry` checks the frozen hash, retry class, sequential attempt count, and original retry budget. Retrying does not expand time, tools, context, permissions, or model access.

## Evidence and attribution

Immediately after execution, call `build_custody_record` over the original artifacts. Keep release-level archives under the existing evidence-custody owner. Classify harness, provider, dependency, container, oracle, contamination, and resource failures as non-graded.

Behavioral component checks require at least one positive control and one negative, boundary, or degradation control. A constant output cannot pass when controls have different oracles. Failure attribution can have multiple contributors and always records uncertainty and a review route.

## Improvement admission

The post-run loop is:

```text
sealed evidence -> attribution -> candidate -> contamination review
-> admission -> held-out validation -> independent outcome verification
-> promotion or quarantine
```

Production queries and generated cases identify a coverage frontier; they are not ground truth. Generated evaluators and cases cannot certify themselves. A multi-axis assurance score passes only when behavior, evaluator calibration, evidence integrity, coverage, regression, and operations each meet the configured threshold.

For repeated matched trials, `summarize_matched_results` reports mean, median, sample standard deviation, minimum, maximum, per-task pass frequency, absolute and relative pass deltas, treatment-only passes, control-only regressions, cost, latency, tokens, and tool calls when provided. It never claims statistical significance from the sample count alone. `result_claim_labels` makes external comparability and publication validity explicit.

## Rollback

These controls are additive and non-mutating. Disable the workflow by removing its caller registration while retaining profiles and custody records. Do not delete evidence. A candidate that fails admission or validation moves through the existing quarantine and recovery process.
