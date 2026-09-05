# Punch Cards

The active durable card set is `.engineering-bootstrap/punch-cards/cohesion-closure-20260904/`.

- Denominator: `evidence/commencement-audit-20260905T002921Z/confirmed-denominator.json`
- DAG: `.engineering-bootstrap/punch-cards/cohesion-closure-20260904/dag.json`
- Exact hashes: `.engineering-bootstrap/punch-cards/cohesion-closure-20260904/SHA256SUMS`
- Cards: 43 total; six audit cards closed; 37 repair/integration/proof cards remain
- Graph: 86 edges, zero unknown dependencies, zero cycles
- Active card: `PX-ASSURE-001`

Lifecycle: `planned -> admitted -> in_progress -> focused_green -> downstream_green -> closed`.

A card with downstream consumers cannot close at `focused_green`. During repair, each source-changing card must record its exact changed files/symbols, calculate the full transitive consumer cone, run focused and discriminating negative tests, run all affected downstream tests and governed sections, and prove zero leaked resources.

No full profile, validation certification gate, package, install, installed-operational, preflight, certification, publication, or release identity/tag mutation is permitted until the complete DAG is downstream green and repair-frozen.
