# Wave 2 Integration Notes

## Dependency boundary

Wave 2 depends on existing PX owners rather than duplicating them:

- `runtime/file_lock.py` — lock authority for write application.
- Wave 1 `runtime/semantic_code_document.py` — immutable source snapshots and revision identity.
- Wave 1 limits, paths, receipts, registry and semantic type modules.
- Wave 1 `runtime/semantic_code_backend.py` — semantic backend contract consumed by `LspSemanticBackend`.

Wave 2 must be installed after Wave 1.

## Runtime ownership

The primary layers are deliberately split:

- `semantic_lsp_adapters.py` / `semantic_lsp_registry.py` — known language-server adapters and collision-checked discovery metadata.
- `semantic_lsp_process.py` — contained process lifecycle and bounded stderr retention.
- `semantic_lsp_framing.py` / `semantic_lsp_protocol.py` / `semantic_lsp_transport.py` — bounded LSP/JSON-RPC transport.
- `semantic_lsp_client.py` — initialize/shutdown, conservative server-request handling, diagnostics and document-manager ownership.
- `semantic_lsp_documents.py` / `semantic_lsp_encoding.py` / `semantic_lsp_uri.py` — snapshot synchronization and position/path conversion.
- `semantic_lsp_queries.py` / `semantic_lsp_normalize.py` — capability-checked semantic queries and normalized results.
- `semantic_lsp_workspace.py` / `semantic_lsp_transaction.py` — revision-bound edit planning, preview and explicit write application.
- `semantic_lsp_manager.py` — bounded project/adapter client custody.
- `semantic_lsp_service.py` — client-neutral facade intended for later orchestration/capability projection.

## Launch authority

`LspClientManager` now defaults to `allow_launch_overrides=False`. With that production-safe default, callers cannot provide their own executable argv or environment through the service surface. PX selects only an executable discovered by the registered adapter from the process environment already governing PX.

Tests and tightly controlled bootstrap code may construct a manager with `allow_launch_overrides=True`. That switch is intentionally visible and explicit so future model/orchestration layers cannot accidentally inherit arbitrary process-launch authority.

The manager also refuses to reuse an existing project/adapter client when requested launch/configuration identity differs. Close the existing client first if an authorized reconfiguration is required.

## Language servers

This wave vendors no language server. Built-in adapters describe Python/Pyright, TypeScript Language Server and PowerShell Editor Services discovery conventions, but the external executables remain separate dependencies. Wave 2 never auto-installs or updates them.

`ManagedLanguageServerProcess` requires the selected argv[0] to resolve to an absolute existing file. Python always receives `shell=False`. Windows command shims can still be interpreted by Windows itself, so discovery/launch authorization remains material even with `shell=False`.

## Internal tiny-model use

The resident tiny PX model is expected to become a frequent consumer of this layer. Its useful jobs include:

- ask for document symbols instead of reading entire files;
- locate definitions, declarations, implementations and references;
- request diagnostic evidence;
- prepare bounded rename/edit plans for a stronger model or governed workflow;
- supply semantic evidence to graph/map, retrieval, knowledge and learning workflows;
- decide that a task needs escalation to the deep model based on contracts and observed evidence.

The tiny model does **not** choose arbitrary language-server binaries, grant itself write permission, accept unsolicited server edits, or bypass revision/containment checks.

## Writes

`SemanticLanguageService` defaults to `allow_writes=False`. A rename is first converted into a `WorkspaceEditPlan` with expected source SHA-256 identities. `write=False` renders a preview and performs validation without modifying project files. `write=True` additionally requires the service write gate and the PX transaction path.

Where a deterministic semantic validation backend exists for a changed file, candidate parse diagnostics are checked before commit. A later integration wave may add further validators; Wave 2 does not pretend that an external LSP response alone is repository authority.

## Configuration contracts

`ServerSpec` owns finite startup/request/shutdown timeouts, per-method request timeout overrides, bounded content-modified retry rules, message/request budgets and environment/initialization data. Mutable input mappings are copied/frozen at the contract boundary so a caller cannot mutate launch policy behind an already-created spec.
