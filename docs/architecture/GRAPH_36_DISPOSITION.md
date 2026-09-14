# Original 36 graph requirements - actual delivery and remaining acceptance

Source: retained original completion specification, preserved in reference/ORIGINAL_36_GRAPH_REQUIREMENTS.md. IDs and requirement titles are unchanged. No blanket 36/36 product-acceptance pass is asserted.

| Requirement | Title | Disposition | Evidence / remaining limit |
|---|---|---|---|
| GRAPH-01 | Core Requirement | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-02 | Canonical Data Rule | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-03 | One Note Per Modeled System | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-04 | System Note Structure | PARTIAL / EXTERNAL ACCEPTANCE | Historical typed facts and limitations retained; changed facts are not re-semantically validated. |
| GRAPH-05 | Typed Relationships | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-06 | Relationship Evidence Levels | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-07 | Architecture Layers | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-08 | MOCs and Focused Architecture Maps | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-09 | Global Graph Design Goal | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-10 | Spatial Layout Philosophy | PARTIAL / EXTERNAL ACCEPTANCE | Lifecycle regions, seeded coordinates and bounded attraction implemented. Cognitive/control axes remain heuristic rather than separately validated dimensions. |
| GRAPH-11 | 3D Architecture Model | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-12 | Recommended 3D Spatial Structure | PARTIAL / EXTERNAL ACCEPTANCE | Curved regions and bounded attraction implemented; no separate local-repulsion solver is claimed. |
| GRAPH-13 | Brain-Like Organization | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-14 | Hubs and Architectural Intersections | PARTIAL / EXTERNAL ACCEPTANCE | Degree/in-out/directed betweenness are explicit. Operational critical-path/grant/consumer-reach composite remains unmeasured. |
| GRAPH-15 | Avoiding the Hairball | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-16 | Edge Weighting for Layout | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-17 | Visual Hierarchy | PARTIAL / EXTERNAL ACCEPTANCE | Bounded degree-based symbol size only; full multidimensional operational prominence is not established. |
| GRAPH-18 | Visual Status Encoding | PARTIAL / EXTERNAL ACCEPTANCE | Layer colors, system/file shape and changed-source outlines implemented. Full orthogonal lifecycle/evidence visual grammar remains partial. |
| GRAPH-19 | Required Saved Views | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-20 | Native Obsidian Graph | DELIVERED WITH SOURCE-SCOPE LIMIT | Installed Obsidian 1.12.7 opened the exact repository vault, rendered visible global and local graph canvases, opened the canonical note, recorded no external update attempt, and closed its owned process. See `evidence/obsidian-native-live-3/obsidian_native_qa.json`. |
| GRAPH-21 | Companion 3D Graph | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-22 | 3D Viewpoints | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-23 | Architecture Paths | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-24 | Resource and Hardware Visualization | PARTIAL / EXTERNAL ACCEPTANCE | Resource references/filters supplied; hardware placement/fallback behavior not observed. |
| GRAPH-25 | Budget Visualization | PARTIAL / EXTERNAL ACCEPTANCE | Budget references only; actual reserve/consume/reconcile quantities not populated from live telemetry. |
| GRAPH-26 | Graph Quality Metrics | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-27 | Betweenness Matters | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-28 | Architectural Weak-Point Detection | PARTIAL / EXTERNAL ACCEPTANCE | Historical and current audit records retained separately; structural bottlenecks are hypotheses, not operational SPOF proof. |
| GRAPH-29 | Change Impact Support | PARTIAL / EXTERNAL ACCEPTANCE | Static import/semantic neighborhoods and exact source links supplied; full authority/state/certification-aware transitive impact analysis remains limited. |
| GRAPH-30 | Runtime Reachability Support | PARTIAL / EXTERNAL ACCEPTANCE | Modeled source links kept separate; no fabricated tested/runtime/certified node promotions. |
| GRAPH-31 | Self-Modeling Goal | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-32 | Visual Design Standard | PARTIAL / EXTERNAL ACCEPTANCE | Full/focused generated HTML rendered and inspected; target-host legibility/usability sign-off remains. |
| GRAPH-33 | The "Pretty Graph" Requirement | DELIVERED WITH SOURCE-SCOPE LIMIT | Implemented in complete_graph.json, generator, offline viewer, canonical vault and parity tests. Historical source support is not runtime proof. |
| GRAPH-34 | Deliverables | DELIVERED WITH SOURCE-SCOPE LIMIT | Generator, schemas, canonical data, vault, offline viewer, learning/repair references and validation guidance are integrated under repository `docs/architecture`. |
| GRAPH-35 | Validation Requirements | PARTIAL / EXTERNAL ACCEPTANCE | Fifteen canonical, bounded-shard and vault-link tests pass; 16 fixed node shards reconstruct all 16,101 nodes below the governed per-file limit; consecutive post-registration builds match; browser interaction passes all eight classes. Installed Obsidian global/local navigation passes with owned closure. Full-graph host performance evidence remains. |
| GRAPH-36 | Completion Standard | PARTIAL / EXTERNAL ACCEPTANCE | Complete supplied-snapshot topology and deep notes delivered; exhaustive current/live semantic and installed proof not claimed. |

## Canonical denominators and currentness

1,077 semantic systems, 1,626 directed semantic relationships and 288 flows preserve original IDs. All 15,024 accepted live source files are inventoried. The combined topology has 16,101 nodes and 7,478 relationships (1,626 semantic, 4,413 static imports, 1,439 system/file anchors). The original 1,834 historical findings are retained without auto-opening/closing them.

The retained 4,432 source anchors have 2,927 matching historical file hashes and 1,505 changed-file hashes. Same-file-byte matching does not validate the semantics of a relationship or its installed behavior. Imports are static references, not proof that execution reached a function. External and computed imports are explicitly unresolved rather than guessed.

## Reproducibility and graph scope

Layout uses deterministic ID hashes, eleven curved lifecycle regions, bounded attraction and persisted positions/edge controls. The attraction weights are 1.0/0.6/0.2 according to declared relationship classes, never evidence confidence. No anatomical/neuron claim is made. Exact directed unweighted betweenness uses unique semantic source-target pairs and (n−1)(n−2) normalization with all semantic systems included.

The viewer keeps all nodes/edges in data and supports full semantic, full source, and combined graphs, not a sampled pretty subset. Visible filters intentionally reduce displayed scope and show exact denominators. Runtime Observed and Certified remain empty. The five journeys reference F01/F07/F03/F09/F10; dashed narrative adjacency is distinct from a present semantic relationship.

The generated source inventory excludes newly generated docs/architecture on a live refresh to prevent self-input recursion. Other excluded source directories and bounds are reported explicitly. Snapshot acquisition is per-file with paused-writer expectations, not a cross-file atomic image.
