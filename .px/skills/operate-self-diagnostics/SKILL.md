---
name: operate-self-diagnostics
description: Compose existing canonical owners into one bounded diagnosis over a reported condition, classify it into a terminal disposition, and delegate to the specialist that owns it. Use when a failure, anomaly, or degraded reading needs a governed disposition and an owning specialist rather than an improvised repair.
---
# Diagnostic Coordinator (Self Operations)

Compose existing Pacify-X owners into one bounded diagnosis over a reported condition. This is the
**single intentional new capability** the V3 Self Operations model requires; everything it does is
delegation, not new authority.

## What this is

A **composition layer**. It does not own repairs, does not own metrics, does not mutate state, and
does not decide truth. It:

1. observes the reported condition and gathers canonical evidence;
2. challenges the first diagnosis (adversarial pass);
3. classifies the condition into a disposition;
4. selects the **canonical specialist owner** that should handle it and records *why*;
5. returns a bounded recommendation — never an effect.

## Dispositions

Terminal, non-repair dispositions are first-class results, not failures:

| Disposition | Meaning |
|---|---|
| `NO_PRODUCT_DEFECT` | the condition is not a product defect |
| `PRODUCT_DEFECT` | a real defect in PX itself |
| `INTEGRATION_DEFECT` | owners exist but are not wired to each other |
| `CONFIGURATION_DEFECT` | configuration is wrong or missing |
| `GENERATED_STATE_DEFECT` | derived state is stale or inconsistent with its inputs |
| `EVIDENCE_STALE_OR_INVALID` | the evidence a claim rests on is expired or malformed |
| `PROBE_OR_TEST_DEFECT` | the probe or test itself is wrong |
| `ENVIRONMENT_UNAVAILABLE` | an external dependency or environment is absent |
| `EXPECTED_OFFLINE_BOUNDARY` | the condition is the designed offline boundary |
| `AUTHORITY_DENIED` | policy correctly refused the action |
| `OPTIMIZATION_OPPORTUNITY` | working, but improvable |

Reporting `NO_PRODUCT_DEFECT` or `PROBE_OR_TEST_DEFECT` is a **correct outcome**. An environment,
probe, evidence, configuration, or generated-state failure must never be mislabelled as a product
defect.

## Hard rules

- **The coordinator never mutates.** It has no write path. Its output is a recommendation.
- **It never self-approves.** Any repair it recommends requires the normal authority and approval
  boundary, and the coordinator cannot satisfy an independent-review requirement for work it
  authored.
- **It never interprets a failed check as success.** Missing, corrupt, or ambiguous evidence
  yields `EVIDENCE_STALE_OR_INVALID`, not a pass.
- **It selects a canonical owner, or says none exists.** Creating a second owner is forbidden.
- **Observation is not governance.** Observing that something happened outside PX's authority is
  not evidence that PX governed it.

## Procedure

1. **Capture pre-state.** Record the reported condition, the exact scope, and the source/evidence
   identity it rests on.
2. **Gather evidence** from canonical surfaces only — registries, generated-state validation,
   the effect surface, the health surfaces.
3. **Challenge** the diagnosis: look for the competing explanation (probe defect, stale evidence,
   environment, expected boundary) before accepting a product-defect explanation.
4. **Classify** into exactly one disposition.
5. **Bind** to the canonical owner that handles that class, recording the reason.
6. **Recommend** a bounded next step, with the evidence a reviewer needs.
7. **Stop.** The coordinator's run ends at the recommendation. It does not iterate to green.

## Recursion controls

If a caller drives repeated iterations, these bounds apply and any one of them stops the loop:
max iterations, max mutation transactions, max cumulative paths touched, max wall budget, max
compute/model budget, repeated candidate hash, repeated world-state hash, unchanged objective,
no-new-evidence, and fixed-point.

**A recursion budget is not permission to keep changing things until checks turn green.**

## Validation

`tests/test_operate_self_diagnostics.py` proves: `NO_PRODUCT_DEFECT` and `PROBE_OR_TEST_DEFECT` are
reachable; a stale-evidence condition is classified as such rather than as a defect; an
unavailable environment is not reported as a product defect; the coordinator has no mutation path;
and every classification binds to a declared owner or explicitly reports that none exists.
