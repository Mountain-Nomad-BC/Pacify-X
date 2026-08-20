# Completion punch card

| # | Gap found in full trace | Resolution | Evidence |
|---:|---|---|---|
| 1 | No canonical extension API | Added versioned `runtime.dashboard_api` | Python API tests |
| 2 | Truncated agent/skill/workflow displays | Complete lazy catalogs with search, sort, paging, details | Catalog tests + screenshots |
| 3 | No shared rolling memory | Project-owned events, handoff, task packets, layered memory | Coordination tests + Memory view |
| 4 | No parallel planning controller | DAG, owners, dependencies, claims, leases, dispatch, progress, reconciliation | Six coordination tests + Workflows view |
| 5 | MCP was four read-only summaries | Twenty-seven context/catalog/coordination/environment/guardrail/Team Fabric/MS+Enterprise tools with effect annotations | MCP integration test |
| 6 | Installer/package version drift | Single `0.4.0` source, generated checksum, installed-version verification | Package contract + install smoke |
| 7 | Display-only controls | Control Center and typed modals/actions | Extension contract + visual review |
| 8 | Cleanup lacked full-tree equality | Scan/preflight/immediate hashes, individual/all, recycle/permanent, receipts | Five destructive-boundary fixture tests |
| 9 | Provider/performance claims could overstate reality | Explicit unavailable/candidate states; no billable API fallback | Snapshot/UI contract |
| 10 | Tests were shallow | API cardinality, complete paging, multi-IDE conflicts, MCP mutations, cleanup gates | Full JS + Python suites |
| 11 | Retained evidence/profile privacy and package size | Evidence protected and excluded from VSIX; no user evidence deleted | VSIX content audit |
| 12 | Visual/accessibility/install acceptance missing | Vertical rail, focus trap, responsive/reduced motion, 14 screenshots, VSIX smoke | Screenshot set + build report |
| 13 | Bulk sort selection had no measured controller | Deterministic sample, compatibility pilot, top-three benchmark, correctness trace, selection receipt | Sort-picker tests + skill/orchestration |
| 14 | Team Fabric pack was reference-only | Full source audit; fencing, budgets, adapters, WorkRooms, import staging, diagnostics, lean gate merged into existing owners | Team Fabric tests + disposition receipt |
| 15 | Enterprise capabilities had no separate operating surface | MS+Enterprise tabs in Skills, Agents, and Workflows plus applicable Diagnostics, Assurance, Runtime, and Control Center controls | UI contracts + visual evidence |
| 16 | Enterprise state risked blending with core memory/provider identity | Separate catalog, IDs, schema, state root, event log, target aliases, auth/billing namespaces, and readiness receipts | Enterprise manager tests |
| 17 | First enterprise plan did not cover the current archive drift or all mechanisms | 23-file plan audit, 33-archive/112,905-entry cross-check, second-pass mechanism disposition | MS+Enterprise second-pass punch card |
| 18 | Billable enablement lacked configurable hard boundaries | Default-off master plus cost/task/session/day, token, local-first, provider, GPU/CPU/RAM, confidence, cache/reuse, and approval gates | Enterprise manager + UI contract tests |
| 19 | Other extensions and installed tools were not visible to orchestration | Startup/change/manual Environment Map with lazy subject shards, per-extension contracts, ontology, graph, and MCP queries | Discovery manager + MCP + visual tests |

All implementation cards are closed. Detailed enterprise cards are in `MS_ENTERPRISE_SECOND_PASS_PUNCH_CARD.md`. Release certification commands and hashes are written to `evidence/BUILD_REPORT.md`; if a later source change invalidates them, that report must be regenerated rather than silently reused.
