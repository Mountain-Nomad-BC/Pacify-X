# Skill Foundry contract

## Inputs

- Documents, transcripts, engineering notes, code-adjacent text, calculations, standards, or papers.
- Stable source ID, locator, SHA-256, source kind, license, version, and citation when research-derived.
- Optional calculation specifications with declared variables, units, dependencies, and equation.
- Current capability IDs for duplicate detection.

## Required outputs

- Canonical deduplicated knowledge objects with evidence references.
- Explicit relationship graph edges.
- Candidate skill packages with inputs, outputs, triggers, dependencies, examples, tests, failure cases, confidence, and references.
- Machine-readable schemas.
- Executable Python and JavaScript only for validated bounded calculations.
- Positive, negative, missing-evidence, and effect-boundary tests.
- Benchmark prompts, fitness metrics, and candidate certification record.
- Append-only receipt for every materialized file.

## Lifecycle

`source -> harvested -> normalized -> related -> candidate capability -> generated candidate -> certified candidate -> separately admitted`

Generation never implies admission. Composition and evolution emit review proposals only. Missing research citation, source hash mismatch, missing license, duplicate capability, incomplete contract, or invalid executable syntax blocks certification.
