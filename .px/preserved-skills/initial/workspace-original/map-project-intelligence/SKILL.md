---
name: map-project-intelligence
description: Build or refresh a complete, evidence-backed project map covering files, symbols, dependencies, calls, runtime services, data flow, integrations, configuration keys, ownership, contracts, tests, traceability, risks, and retrieval. Use when onboarding a project, before broad changes, after architecture drift, or when the AI lacks a dependable model of how the project works.
---

# Map Project Intelligence

Default to read-only discovery. Exclude sensitive files before inventory, hashing, parsing, or retrieval. Never store secret values. Reject symlink traversal, bound every walk, archive previous maps, and promote a new map only after validation.

## Procedure

1. Resolve the project root and confirm scope.
2. Run `scripts/build_project_map.py <project-root>`. For audit custody outside the source tree, add `--output-dir <audit-map-dir>`.
3. Validate the promoted map with `scripts/validate_project_map.py <project-root> --fresh`.
4. Read `project-manifest.json`, `risk-and-gap-map.json`, and `map-summary.md` first.
5. Query `retrieval-index.json` before opening arbitrary source files.
6. Hydrate only source ranges returned by the query plan.
7. Treat unresolved edges and low-confidence facts as gaps, not truths.
8. Refresh incrementally after material source changes and compare revisions.
9. Require the native impact operation before symbol edits; do not rely on a stale external code-intelligence index.

## Required outputs

The canonical map lives at `.engineering-bootstrap/project-map/` and must include all files listed in `references/project-map-contract.md`.

## Boundary

The mapper may infer structural relationships but must label inference confidence. It must not infer secrets, hidden production topology, or ownership unsupported by repository evidence.
