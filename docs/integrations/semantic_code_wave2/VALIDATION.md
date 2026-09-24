# Wave 2 Validation — 2026-09-20 Implementation Pass

This file records validation performed against the supplied `Pacify-X-main (1).zip` baseline **after applying the finished Wave 1 package**, not historical results from the earlier Wave 2 source bundle.

## Payload boundary

- Planned Wave 2 repository payload: **49 files**.
- Source Wave 2 payload located and matched: **49/49 files**.
- Wave 2 is additive at the supplied pre-Wave-2 PX snapshot; install destinations are recorded in the package-level `01_INSTALL_MAP.md`.

## Python / dedicated tests

- Runtime/test compilation: **PASS**.
- Hardened Wave 2 dedicated suite: **63 passed**.
- Wave 1 + Wave 2 semantic suites together: **117 passed**.
- Neighbor regression (`file_lock`, runtime lifecycle/WAL, platform support, workspace manager): **72 passed, 1 skipped**.

The skipped case is inherited from the baseline's platform-dependent neighborhood suite; Wave 2 did not convert a pass into that skip.

## Behaviors exercised

The dedicated suite covers:

- initialization, shutdown and unexpected process exit;
- bounded framing and JSON-RPC request/notification/server-request flow;
- request timeout cancellation and late-response isolation;
- pending-request budget enforcement;
- process-tree termination and bounded stderr retention;
- capability and position-encoding negotiation;
- didOpen/didChange/didClose synchronization;
- diagnostics version filtering and normalization;
- document symbols, definitions, declarations, implementations and references;
- rename planning, side-effect-free preview and explicit write gate;
- stale revision rejection and rollback after a partial multi-file commit failure;
- project URI containment and resource-operation rejection;
- adapter discovery without auto-install;
- manager client reuse and health behavior.

## Hardening added during this implementation pass

The source payload was already green at **54/54**. Review still found policy/edge conditions that mattered for autonomous use. The finished wave adds tests and implementation repairs for:

1. **Trusted launch authority.** Default manager instances reject caller-provided argv/environment overrides. Explicit launch overrides are available only when a trusted caller opts in.
2. **Configuration identity on reuse.** An existing project/adapter client cannot be silently reused with different argv, environment, initialization options or server configuration.
3. **Concrete executable admission.** The process launcher rejects bare/non-absolute executable names; the launch target must be an absolute existing file/shim.
4. **Finite numeric policy.** NaN, infinity, booleans, zero and invalid bounded timeout values are rejected before they reach blocking primitives.
5. **Per-method timeout policy.** `ServerSpec.request_timeout_overrides` is now enforced by `LspClient`.
6. **Retry policy wiring.** `ServerSpec.content_modified_retry_methods` and `content_modified_max_attempts` now control the actual transport rather than existing as unused contract fields.
7. **Immutable launch-policy inputs.** Environment, initialization options and timeout-override mappings are copied/frozen at spec construction; ambiguous container types are rejected.

## Scope limits

- No real external Pyright, TypeScript Language Server or PowerShell Editor Services executable was installed or invoked in this container. Protocol/lifecycle integration uses the deterministic fake LSP server shipped in the test fixture.
- Windows-specific process-tree behavior is implemented but cannot be executed from this Linux validation environment. The code uses Windows process groups plus bounded `taskkill /T` fallback and must still be exercised on the live Windows PX machine before final certification.
- This wave does not claim whole-repository certification. After transfer, PX's current reconciliation/certification authority remains the source of truth.

## Admission conclusion

Within the uploaded baseline + finished Wave 1 environment, Wave 2's bounded LSP layer is internally coherent and focused/neighborhood-green. It is suitable as a **transfer-ready implementation candidate**, subject to live Windows integration and the repository's normal certification flow.
