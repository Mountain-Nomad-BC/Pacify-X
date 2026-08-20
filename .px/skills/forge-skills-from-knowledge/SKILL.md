---
name: forge-skills-from-knowledge
description: Compile documents, engineering notes, code-adjacent text, calculations, transcripts, standards, or research into normalized evidence-linked knowledge, candidate skills, schemas, executable calculation packages, tests, graph updates, documentation, benchmarks, and certification evidence. Use when turning a mixed corpus into reusable capabilities or when composing, repairing, splitting, merging, or reevaluating skills; never activate generated work without separate admission.
---

# Forge Skills From Knowledge

Compile source material into bounded candidate artifacts while preserving provenance and keeping generation separate from admission.

## Workflow

1. Inventory every source and record its kind, locator, SHA-256, license, version, and citation.
2. For papers, standards, or white papers, require a traceable citation before certification.
3. Run `runtime.knowledge_foundry.compile_foundry_bundle` to harvest, normalize, deduplicate, relate, and classify source knowledge.
4. Supply `CalculationSpec` records for equations that need Python, JavaScript, units, schemas, edge cases, and failure cases.
5. Inspect every emitted knowledge object, graph edge, candidate skill, schema, benchmark, and fitness score.
6. Run `certify_foundry_bundle`. Resolve all errors; do not downgrade or discard failed evidence.
7. Use `materialize_candidate_bundle` only in a candidate staging directory. It is append-only and refuses replacement.
8. Use `compose_candidate_skills` or `evolution_recommendations` for merge, split, repair, or deprecation proposals.
9. Submit certified candidates to the separate skill-admission controller before activation.

## Guardrails

- Never treat source text, publication, or generated code as production proof.
- Never infer a citation that the source does not provide.
- Never overwrite or delete a prior bundle, source, test, failure, or certification record.
- Keep research-derived mechanisms candidate-only until reproduced in the intended environment.
- Reject duplicate capability IDs and unsupported calculation syntax.
- Load detailed source fragments only after metadata selection.

## Reference

Read [foundry-contract.md](references/foundry-contract.md) when defining source types, expected artifacts, certification gates, or evolution decisions.
