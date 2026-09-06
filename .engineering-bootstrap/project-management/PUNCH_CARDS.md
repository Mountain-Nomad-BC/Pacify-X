# Punch Cards

The active durable card set is `.engineering-bootstrap/punch-cards/cohesion-closure-20260904/`.

- Denominator: `evidence/commencement-audit-20260905T002921Z/confirmed-denominator.json`
- DAG: `.engineering-bootstrap/punch-cards/cohesion-closure-20260904/dag.json`
- Exact hashes: `.engineering-bootstrap/punch-cards/cohesion-closure-20260904/SHA256SUMS`
- Cards: 43 total; implementation and focused repair work are complete; canonical lifecycle state is owned by the DAG reconciler
- Graph: 86 edges, zero unknown dependencies, zero cycles
- Current projection: six audit cards are `closed`; all 37 source/proof cards are evidence-backed at `downstream_green`; zero repair cards remain
- Closure boundary: the 37 source/proof cards remain short of `closed` until final100 installed-operational proof succeeds

Lifecycle: `planned -> admitted -> in_progress -> focused_green -> downstream_green -> closed`.

A card with downstream consumers cannot close at `focused_green`. The reconciler must derive every lifecycle transition from retained implementation, focused, downstream, governed-section, and resource evidence; documentation does not grant or substitute card state.

Final99 is terminal and cannot be resumed. Repair12 focused exact-artifact proofs closed its five direct installed-host failure paths, but no final certification or publication is claimed. A successor campaign may begin only after the complete DAG is reconciled, the repair denominator is zero, and repair12 is frozen.
