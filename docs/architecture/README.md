# Pacify-X architecture atlas

This directory contains the canonical repository architecture graph, an Obsidian vault, and an offline 3D companion generated from the current Pacify-X checkout.

## Open the graph

- Open [`ATLAS_OFFLINE.html`](ATLAS_OFFLINE.html) in a local browser for the full interactive graph, saved filters, eleven cameras, and five lifecycle journeys.
- Open [`vault`](vault) as an Obsidian vault for global graph, local graph, system notes, layers, maps of content, findings, paths, and evidence navigation.
- Read [`GRAPH_36_DISPOSITION.md`](GRAPH_36_DISPOSITION.md) for the exact implementation and remaining acceptance status of all 36 graph requirements.

## Current canonical denominator

The live build contains 1,077 modeled systems, 15,024 accepted source files, 16,101 total nodes, 1,626 directed semantic relationships, 4,413 static import relationships, 1,439 system-to-file anchors, 7,478 total edges, 288 flows, 1,834 historical findings, and 4,432 evidence anchors. It has no dangling edges, missing flow steps, or source parse errors.

The source inventory excludes generated or operational control output such as `.engineering-bootstrap`, retained `evidence`, ledger deltas, caches, dependencies, quarantine, and this generated atlas tree. Exact exclusions are recorded in [`data/source_exclusions.json`](data/source_exclusions.json). The inventory is stable per file and is not a cross-file atomic filesystem snapshot.

## Evidence semantics

The graph preserves historical semantic IDs and refreshes current file hashes and static imports. Same-file byte identity is not behavioral proof. Source-supported relationships do not populate Runtime Observed or Certified views. Historical findings are retained without automatically reopening or closing them.

Layout weights are documented visual heuristics. Betweenness is exact directed unweighted Brandes centrality over the selected semantic projection; neither is an evidence-confidence or operational-risk score.

## Rebuild and verify

```powershell
python docs/architecture/tools/build_atlas.py --repo . --out docs/architecture --allow-repo-output
python -m pytest -q -p no:cacheprovider tests/test_architecture_atlas.py
python docs/architecture/tools/verify_atlas_browser.py --atlas docs/architecture --out docs/architecture/evidence/browser-qa
```

The browser verifier uses an already installed local Playwright browser and performs no network access. Native Obsidian acceptance is recorded separately because generating a valid vault does not prove the desktop application opened and navigated it. The installed Obsidian 1.12.7 acceptance run opened the exact repository vault, rendered both global and local graph canvases, opened the canonical note, recorded no external update attempt, and closed its owned process. See the [native receipt](evidence/obsidian-native-live-3/obsidian_native_qa.json), [global graph](evidence/obsidian-native-live-3/global-graph.png), and [local graph](evidence/obsidian-native-live-3/local-graph.png).

Current focused evidence is under [`evidence`](evidence): canonical, bounded-shard and vault parity passed 15 tests; all 16 node shards are below 4 MiB and reconstruct 16,101 nodes; the owned browser passed all eight content interaction classes and closed cleanly; and two consecutive post-registration builds matched across eight source-bound presentation and component artifacts.
