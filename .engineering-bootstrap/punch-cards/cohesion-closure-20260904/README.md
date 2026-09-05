# Pacify-X cohesion-closure punch cards

This directory is the durable 43-card implementation contract for the source-bound denominator at `19761e2a769885d6df25dc448c673e339eaf9c8c`. Every `PX-*.json` file contains all fields required by Section 6 of the commencement orchestration. `dag.json` is the canonical dependency graph and execution order; `SHA256SUMS` binds exact card bytes.

Current progress: six audit cards are closed; 37 source/proof cards remain. `PX-ASSURE-001` is active and its expanded downstream cone is in progress. Per-card evidence is retained under `evidence/commencement-repair/`.

Wave 0 audit cards are closed because their source-bound evidence was completed before product mutation. The remaining 37 cards begin at `planned`. A card advances through `admitted -> in_progress -> focused_green -> downstream_green -> closed`; no card with consumers closes at focused green.

Dependency order is authoritative. The one intentional cross-wave prerequisite is that `PX-CORE-004` establishes the invalidation service before `PX-ASSURE-003` integrates canonical decay with it. This avoids a temporary duplicate invalidation owner.

During repairs, broad release stages are forbidden. Every source-changing card must record changed files/symbols, recompute its direct and transitive impact cone, run focused and discriminating negative tests, run all affected downstream tests, run each affected governed section once, and verify zero leaked resources. Exactly one successor campaign may be admitted only after the complete DAG is downstream green and repair-frozen.
