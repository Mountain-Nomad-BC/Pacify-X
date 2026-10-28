# Pacify-X stdio MCP host setup

Use this when a host cannot install the VSIX but can launch a local stdio MCP server. No network service or API key is required.

Build once with `npm run build:mcp`, then configure the host using the shape in `px-mcp.example.json`. Replace the absolute paths. `PX_ENGINE_ROOT` points to the Pacify-X source containing `runtime/dashboard_api.py`; `PX_WORKSPACE_ROOT` points to the project whose `.agentic_engineering_os_px/coordination` ledger should be shared. `PX_TEAM_PACK_ROOTS` is an optional path-delimited allowlist for package-preview/stage tools.

The server exposes read-only context/catalog/status/doctor/package-preview/activity-observability tools and explicit project-write tools for plans, claims, renewal, progress, reconciliation, release, memory capture, agent activity emission, and candidate staging. All MCP calls emit local metadata-only start/success/failure observations when enabled. Mutating tools write only below the configured project coordination root and emit receipts/events.

Agents should call `pacify_activity_emit` for important sub-steps that happen outside a PX tool, reusing one `correlation_id` across start/running/terminal-state events and including their actor, session, harness, optional task/claim, effect, and bounded scope references. Do not send prompts, source contents, output, credentials, or private reasoning as metadata; sensitive/content-bearing keys are redacted.

Project-write tools require a signed launch capability issued by the trusted local host. The example configuration supplies read access only; self-asserted actor/session fields cannot authorize writes. Launch-authority version 2 binds the canonical project path and native directory device/file identity, and rechecks that identity and validity time before every write. Removing, replacing, or retargeting the project root denies writes before activity recording. Restart the host to issue a fresh capability after upgrading from version 1; old path-only capabilities are rejected.

The MCP bundle build and `--check` use the extension directory as their fixed working directory, so invoking the build script from the repository root or the extension directory produces the same bytes.
