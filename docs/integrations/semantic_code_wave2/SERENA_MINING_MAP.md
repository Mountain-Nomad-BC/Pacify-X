# Serena Mining Map — Wave 2

Serena was treated as a behavior/architecture study source, not as code to port. Wave 2 re-derives the useful mechanics inside PX's own authority and failure model.

| Studied concern | PX Wave 2 realization |
|---|---|
| language backend abstraction | collision-checked LSP adapter/registry plus Wave-1 backend contract |
| multi-language LSP execution | bounded PX-owned stdio process + JSON-RPC transport |
| symbol/reference/implementation lookup | normalized, capability-checked `LspQueryService` |
| document synchronization | immutable-snapshot-aware `LspDocumentManager` |
| diagnostics | bounded, version-aware diagnostic store and normalization |
| position conversions | explicit UTF-8 / UTF-16 / UTF-32 conversion against exact text |
| language-server lifecycle | process-tree custody, health state, restart accounting and quarantine |
| symbolic rename/refactor proposals | contained `WorkspaceEditPlan`, revision identities and PX transaction |
| external tool discovery | registered adapters with discovery only; no auto-install |

PX-specific hardening intentionally goes beyond a normal IDE/LSP client:

- launch argv/environment overrides are denied by default;
- executable launch target must be an absolute existing file/shim;
- one client cannot be silently reused under a different launch/configuration identity;
- request timeout and retry policy are immutable bounded contract data;
- NaN/infinity/boolean timeout values are rejected;
- unsolicited `workspace/applyEdit` is rejected;
- model callers do not inherit subprocess or write authority;
- project containment is fail-closed for source URIs;
- multi-file edits are SHA-bound, lock-protected, staged and rollback-aware;
- owned-process liveness determines whether shutdown actually succeeded.

These changes matter because PX is building toward a resident autonomous tiny model that may invoke this subsystem far more frequently than a human-driven IDE session.
