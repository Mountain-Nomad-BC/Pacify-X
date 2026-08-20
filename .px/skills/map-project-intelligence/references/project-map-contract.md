# Project map contract

Required artifacts:

- project-manifest.json
- file-inventory.jsonl
- file-facts.jsonl
- symbol-index.jsonl
- dependency-graph.json
- call-graph.json
- architecture-graph.json
- runtime-topology.json
- data-flow-map.json
- integration-map.json
- configuration-map.json
- ownership-map.json
- contract-map.json
- test-coverage-map.json
- traceability-map.json
- risk-and-gap-map.json
- retrieval-index.json
- map-summary.md
- map-receipt.json

Acceptance requires deterministic identifiers, bounded traversal, no secret values, hash-bound artifacts, unique retrieval IDs, matching inventory/fact path sets, and a validated receipt. A map is advisory when unresolved edges remain and stale when source inventory changes.
