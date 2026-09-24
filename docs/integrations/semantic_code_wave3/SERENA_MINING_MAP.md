# Serena → PX Wave 3 Mining Map

This is a behavioral mining map, not a code-port map.

| Reference area studied | Useful invariant | PX-native Wave-3 result |
|---|---|---|
| context/mode configuration | different hosts and operating modes need different exposed surfaces | explicit `ContextProfile`, `ModeProfile`, deterministic capability projection |
| tool inclusion/exclusion | optional/editing/project tools must remain separable | operation catalog with effects, risk, source wave, exclusions, and module-availability filtering |
| project server/query-project behavior | project questions require isolation and must not mutate the queried project | explicit project IDs, authorization tokens, per-project borrowing, no mutable active project |
| output plumbing | query results need bounded machine-readable identity | deterministic query receipts and derived provenance |
| project knowledge/navigation | graph/project-map data should augment rather than replace code evidence | PX-native project-map evidence bridge under existing project-map retrieval owner |
| memory reference analysis | stable identity must survive storage movement | documented Wave-4 `pxmem://` contract; implementation intentionally deferred to Wave 4 |
| operator tool surface | an internal assistant needs useful tools without becoming authority | `local-model` profile exposes read/plan/process R1, never write |

Serena source remains external reference material. This payload is a clean-room PX implementation and contains no copied Serena source.
