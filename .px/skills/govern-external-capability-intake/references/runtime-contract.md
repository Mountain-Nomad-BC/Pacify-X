# External capability runtime contract

Canonical runtime: `runtime.external_capability_provider`.

## Operations

- `load_external_catalog` and `external_catalog_status`: validate the secondary catalog, candidates, bundles, and license metadata.
- `search_external_candidates`: deterministic metadata-only retrieval with no activation or authority.
- `hydrate_external_metadata`: bounded registry-record hydration; source bodies remain unloaded.
- `plan_selective_stage`: hash-bind selected deferred bundle bodies and detect project collisions and unresolved candidate dependencies.
- `apply_selective_stage`: write an inert project-local stage receipt after review; active registry mutation and authority remain false.
- `revoke_selective_stage`: append a revocation receipt without deleting the original stage evidence.
- `govern_hook_invocation`: enforce hook profile, event, authority, recursion, and depth policy without executing a hook.
- `normalize_session_snapshot` and `compare_session_parity`: preserve project/session/agent state and evidence across harness adapters.
- `rank_execution_routes`: reject unsafe, unauthorized, privacy-incompatible, low-quality, over-budget, or over-latency routes before economic preference.

Candidate bundle bodies under `.px/skills/` are intentionally `mapped_deferred`. They may be discovered as metadata but are not selectable active skills until a separate admission changes their canonical lifecycle with tests and evidence.
