---
name: propose-change-intelligence
description: "Stage proposal-only capabilities for dependency impact, semantic drift, architecture entropy, business-rule collision, and living documentation. Use when repeated change-analysis work suggests a new reusable capability."
---

# Change-intelligence proposals

## Workflow

1. Identify the repeated capability gap and reject overlap with active controls.
2. Require a behavior baseline, validation dataset, false-positive controls, safety effects, and measurable postconditions.
3. Group related needs into change-impact, semantic-drift, architecture-entropy, rule-collision, or living-documentation candidates.
4. Emit a deterministic candidate with `auto_activate: false`.
5. Route the candidate through normal admission, validation, evidence, and approval before registration.

## Completion

This skill never implements or activates its own proposal. Missing candidate fields produce `incomplete`; complete fields produce only `candidate`.
