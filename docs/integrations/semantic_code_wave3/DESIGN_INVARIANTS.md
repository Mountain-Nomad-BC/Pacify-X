# Wave 3 Design Invariants

1. **Exposure is not authority.** Capability projection describes what a client may be shown. It never grants execution rights.
2. **The tiny model is an operator, not an authority.** It may query, plan, invoke admitted PX-owned read/process tooling, and later request governed learning/map/graph operations. It does not receive raw write authority.
3. **No global active project.** Every cross-project request names an explicit project ID. The catalog binds that ID to exactly one canonical root.
4. **Wave-3 cross-project execution is read-only.** Mutation operations fail at authorization before a project is borrowed.
5. **Project roots are identity-bound.** A borrowed project root is re-resolved and must still match the registered canonical root.
6. **PX keeps canonical owners.** Wave 3 adapts to existing semantic-code, project-map, evidence, operation-authority, and authority-topology owners rather than cloning them.
7. **Future-wave capability is not falsely advertised.** Wave-4 retrieval/memory/model-context operations remain declared for compatibility but are denied as `integration_module_unavailable` until their modules actually exist.
8. **Semantic evidence is derived evidence.** It carries source ID, project, lineage, locator, revision, bounded scores, and visibility; it never claims source authority.
9. **Scores must be finite and bounded.** NaN, infinity, and out-of-range trust/dense/graph scores are rejected.
10. **Project-map absence is explicit.** Wave 3 does not manufacture a successful Atlas result when the map is absent or rejected. Wave 4 owns typed orchestration-level degradation.
11. **Receipts are deterministic in identity.** Observation time is metadata; operation/request/result identity determines the receipt digest.
12. **Input coercion is forbidden at trust boundaries.** Strings such as `"false"` are not silently converted to `True`; booleans and integers are type-checked.
13. **Everything is bounded.** Projects, modes, operations, query bytes, result counts, context, evidence, receipts, labels, and concurrent borrows have explicit limits.
14. **Wave boundaries are dependency-clean.** Wave 3 imports no Wave-4 runtime at module import time; optional later surfaces are lazy and fail explicitly when absent.
15. **No authoritative registry mutation in this package.** Admission remains a separate governed live-repository step.
