# Diagnostic Dispositions and Delegation

## Why the coordinator exists

Self Operations already owns ten canonical slots. The composition layer needs exactly one
more: something that *classifies a condition* and *names the specialist that owns it*. It
must never become a second optimizer, a second repair engine, or a second source of truth.

## Disposition vocabulary

| Disposition | Meaning | Escalation |
|---|---|---|
| `NO_PRODUCT_DEFECT` | Environment, probe, config, or generated-state condition | Never escalated into a product defect |
| `PROBE_OR_TEST_DEFECT` | The measuring instrument is wrong, not the product | Fix the probe, not the owner |
| `EVIDENCE_STALE_OR_INVALID` | A check failed without usable evidence | Re-acquire evidence; never a pass |
| `KNOWN_OWNER` | A declared specialist capability owns this | Delegate; record why |
| `UNOWNED` | No declared owner matches | Report the miss; do not create an owner |
| `REPAIR_REQUIRED` | A real product defect | `requires_authority: True` |

## Ordering rule

An environment, probe, evidence, configuration, or generated-state condition **outranks** a
behaviour signal. That ordering is what stops a flaky probe from being reported as a
product failure.

## Bounded recursion

The planner declares maximum iterations, maximum mutation transactions, maximum cumulative
paths, maximum wall budget, repeated candidate/world-state hash, unchanged objective,
no-new-evidence, and fixed point. Hitting any bound terminates with a disposition rather
than continuing.

## Authority boundary

`coordinator_may_execute` is always `False`. `select_specialist` returns
`may_create_owner: False`. The coordinator observes, challenges its own first diagnosis,
classifies, delegates, and records. It does not write.