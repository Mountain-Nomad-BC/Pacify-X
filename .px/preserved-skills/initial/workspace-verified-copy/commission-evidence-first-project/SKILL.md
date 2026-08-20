---
name: commission-evidence-first-project
description: "Commission a new or existing project from structured facts, assumptions, unknowns, accessibility, security, integration, operations, and acceptance inputs. Use before implementation when project intent or risk boundaries need an evidence-backed brief."
---

# Evidence-first project commissioning

## Workflow

1. Collect the required commissioning sections defined in `contracts/commissioning-questionnaire.schema.json`.
2. Label each statement as a fact, assumption, or unknown. Attach evidence to every fact.
3. Record assumption confidence, risk, confirmation state, and the evidence that could invalidate it.
4. Block implementation for unresolved high/critical-risk assumptions or unknowns unless the user explicitly accepts a bounded exception.
5. Produce the compact dossier: `PROJECT_BLUEPRINT.md`, `ARCHITECTURE_GOVERNANCE_AND_RISK.md`, and `EXECUTION_PLAN_PUNCH_CARDS_AND_ACCEPTANCE.md`; keep it synchronized with `PROJECT_MANAGEMENT.md` and machine-readable state.
6. Never claim legal or regulatory compliance without reviewed jurisdiction-specific evidence.

## Completion

Use `runtime.assurance_controls.run_assurance_control`. Completion requires all questionnaire sections, evidence-backed facts, an assumption ledger, explicit unknowns, and a human acceptance state.
