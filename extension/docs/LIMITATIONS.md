# Limitations ledger

- Native transfer of private Codex, Copilot, or editor conversation sessions is unsupported. Continuity uses the portable project handoff, source pointers, receipts, and layered memory.
- Activity observability is event-driven, not OS-wide surveillance. PX sees lifecycle calls routed through the extension or bundled MCP automatically; unmediated external tools are visible only through filesystem/SCM side effects with unknown attribution unless the agent calls `pacify_activity_emit`.
- Activity records deliberately exclude prompt/file/terminal/tool contents and private reasoning. They can show what operation ran, who declared it, where it was scoped, its state/duration, and integrity hashes—not a model's hidden thought process.
- The activity retention setting is a declaration for operators. Automatic destructive expiration is disabled until an admitted reclamation/receipt controller exists.
- Antigravity and other VS Code-compatible IDEs must support VSIX installation and the required VS Code APIs. Hosts without that support can use the bundled stdio MCP server, but the extension cannot guarantee third-party host behavior.
- Live agent processes and workflow executions are not invented when Pacify-X exposes only registry records; the UI labels runtime jobs unavailable.
- TurboVec is detected as a candidate only. It is not authoritative until compatibility, correctness/recall, isolation, benchmark, observability, fallback, and recovery evidence pass.
- Ollama is optional and loopback-only. The extension does not install, start, update, or manage it.
- Cleanup is intentionally limited to `__pycache__`, `.pytest_cache`, and `.ruff_cache` under the admitted engine root. It is not a whole-drive cleaner and never includes evidence or quarantine.
- The knowledge graph surface provides the complete paged record catalog and authoritative edge count, not an unrestricted mutable graph editor.
- System-memory candidates require human/governance review outside the extension; they never become canonical automatically.
- Old evidence profiles in the working directory remain user/evidentiary data. They are excluded from packaging and were not deleted.
- MS+Enterprise currently provides a complete separate catalog, offline project state, controls, readiness diagnosis, and cross-host MCP access. Azure, Foundry, Power Platform, M365, Teams, Dynamics, Business Central, DevSkim, ONNX GenAI, DAP, and TUI external adapters are intentionally disabled or not installed; no cloud connection or tenant mutation is claimed.
- Environment discovery maps extension manifests and fixed local probes; it does not activate arbitrary extensions, guarantee undocumented command/API contracts, admit detected packages for execution, or install/update anything. Those unknowns remain explicit in each lazy contract.
- The billable-provider switch configures policy eligibility only. No billable provider executor or credential store is implemented, so enabling it cannot by itself perform cloud work.
