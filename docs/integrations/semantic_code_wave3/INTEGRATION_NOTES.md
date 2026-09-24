# Wave 3 Integration Notes

## Dependency order

Wave 3 requires the current PX base plus completed Waves 1 and 2. Its principal existing-owner dependencies are:

- `runtime/semantic_code_service.py`
- `runtime/semantic_lsp_service.py`
- `runtime/project_map_retrieval.py`
- `runtime/operation_authority.py`
- `runtime/authority_topology.py`
- `runtime/evidence_assembler.py`
- `runtime/file_lock.py`

Wave 4 will add canonical retrieval fusion, model-context materialization, local rerank signal adaptation, and durable memory-reference/relocation support.

## Cross-project semantics

`SemanticProjectCatalog` stores explicit project-id → canonical-root bindings. `CrossProjectSemanticService` accepts an explicit `QueryAuthorization`, validates project and operation scope, borrows only that project's lock, and invokes Wave-1 read semantics. There is no mutable process-wide project switch.

Arguments are parsed strictly: booleans are booleans, result budgets are bounded positive integers, paths/text are byte-bounded, and unsupported operations do not fall through into generic execution.

## Capability projection

Context and mode profiles produce a deterministic client-neutral operation projection. The resident tiny model uses the `local-model` profile:

- allowed effects: `READ`, `PLAN`, `PROCESS`
- maximum projected risk: R1
- no `WRITE` effect
- no automatic authority from projection

`PROCESS` exists so the operator may invoke PX-owned read services such as an admitted language server. It does not allow the model to choose arbitrary executables or bypass process authority.

Wave-4 operations are declared but automatically filtered from active projections until the corresponding runtime modules are installed.

## Project-map / Atlas

`semantic_project_map_bridge.py` calls the existing `runtime.project_map_retrieval.query_project_map` and normalizes hits into `SemanticEvidence`. It never builds, repairs, or rewrites the project map. Missing or invalid map data remains an explicit failure at this layer; Wave 4 may compose that into a typed degraded read while preserving other semantic evidence.

## Evidence and provenance

`semantic_evidence_bridge.py` converts bounded semantic evidence into the existing PX evidence assembler. Duplicate source/revision identities are rejected. `semantic_provenance.py` marks normalized semantic evidence as derived and non-authoritative.

`semantic_query_receipts.py` hashes bounded request/result identity and keeps observation time outside the deterministic identity digest.

## Wave-4 handoff

`SemanticIntegrationService` imports Wave-4 orchestration, local-model context, and memory integrity lazily. In a Wave-3-only installation those methods fail explicitly with `requires Wave 4` rather than breaking module import or silently degrading into a different contract.
