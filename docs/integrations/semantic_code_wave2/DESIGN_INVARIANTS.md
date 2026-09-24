# Wave 2 Design Invariants — Semantic LSP Runtime

Wave 2 adds language-server sensing and edit planning behind the deterministic semantic substrate from Wave 1. These rules are admission requirements, not suggestions.

1. **PX owns every server process it starts.** A client/transport close may not silently leave an owned language-server process running.
2. **Launch authority is separate from query authority.** The default manager rejects caller-supplied `argv` and environment overrides. Test/bootstrap code must explicitly opt into trusted launch overrides.
3. **PX never requests a Python subprocess shell.** Every launch uses an argv sequence with `shell=False`. On Windows, an admitted `.cmd`/`.bat` executable may still be interpreted by the operating system command processor; therefore only registered/discovered launch targets are admissible.
4. **No automatic installation or downloading.** Discovery reports already-present language servers. It never installs, updates, downloads, or executes package managers.
5. **Executable identity is concrete.** The process launcher requires an absolute existing executable/shim path. Bare command names are not accepted at the launch boundary.
6. **Project containment is the default.** Project-source URIs escaping the canonical project root are rejected unless a read-only caller explicitly requests external location results.
7. **LSP output is evidence, not authority.** Server responses may supply symbols, locations, diagnostics and proposed edits; they cannot redefine PX contracts, permissions, Atlas truth, memory truth, certification state or repository authority.
8. **Unsolicited mutation is rejected.** `workspace/applyEdit` requests from a server are refused. Mutations must return through PX as revision-bound `WorkspaceEditPlan` values.
9. **Writes are opt-in and independently gated.** `SemanticLanguageService` defaults to `allow_writes=False`. Preview stays side-effect free; an actual write requires the write gate plus transaction checks.
10. **Multi-file writes are revision-bound.** Expected SHA-256 values are rechecked under PX `FileLock`; candidate bytes are bounded and analyzed where an admitted deterministic backend exists; writes are staged, atomically replaced and rolled back on partial failure when safe to do so.
11. **Client reuse cannot smuggle configuration changes.** One project/adapter client may be reused only when launch argv, environment, initialization options and server configuration match the existing client's authority identity.
12. **Budgets are finite.** Message bytes, pending requests, request timeouts, server-request workers, stderr retention, clients, restart windows, restart attempts and semantic file sizes are bounded. NaN, infinity and boolean-as-number timeout values are rejected.
13. **Retry behavior is contract-bound.** Per-method timeout overrides and content-modified retry policy come from the immutable `ServerSpec`; retries are method-scoped and bounded.
14. **Position encoding is explicit.** UTF-8, UTF-16 and UTF-32 positions are converted against the exact snapshot being queried or edited.
15. **Late responses do not resurrect stale work.** Timed-out request slots are removed before cancellation; racing responses for removed requests are ignored.
16. **Protocol/server failure is contained.** Malformed frames, bad JSON-RPC shapes, server crashes, worker failures and shutdown failures are isolated from the PX host and reflected in health/error state.
17. **Shutdown is proven by process liveness.** A still-running owned child after bounded termination is an error, not a successful close.
18. **The tiny internal model is a caller, never a bypass.** The resident PX operator may request admitted semantic queries and later invoke admitted orchestration, but it receives no arbitrary subprocess or filesystem authority merely because it runs inside PX.

These invariants are intentionally stricter than a general-purpose IDE client because the intended caller can be an autonomous internal model operating continuously.
