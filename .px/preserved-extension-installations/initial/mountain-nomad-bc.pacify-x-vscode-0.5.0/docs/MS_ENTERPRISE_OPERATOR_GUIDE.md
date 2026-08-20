# MS+Enterprise operator guide

Open **Skills & Tools → MS+Enterprise**, **Agents → MS+Enterprise**, or **Workflows → MS+Enterprise**. These tabs read the separate canonical catalog through `runtime.dashboard_api`.

The **Settings → Billable execution guardrails** master switch defaults OFF. Turning it on only permits a proposal to reach policy evaluation. It does not create/read credentials, connect to Microsoft or another provider, or authorize spending. Configure cost caps per task/session/day, token budget, local-first routing, provider allowlist, GPU/CPU/RAM ceilings, escalation confidence, cache/reuse level, and per-execution approval in VS Code settings. Zero cost caps and an empty provider list deny execution.

`Enable metadata` enables only the selected pack's offline project metadata. It does not start a service, open network egress, read credentials, authorize mutation, or enable billing.

`Target` records non-secret aliases for a pack, tenant, and environment. Authentication and billing are named as separate namespaces; secrets are never stored in the enterprise state file.

`Run readiness doctor` verifies the separate state root, offline boot, denied egress and mutation, disabled billing, no credential reads on load, connector defaults, provider identity separation, and reviewed-only memory promotion. It writes a receipt under `.engineering-bootstrap/enterprise/evidence`.

The same operations are available to VS Code-compatible hosts through:

- `pacify_enterprise_status`
- `pacify_enterprise_readiness`
- `pacify_enterprise_pack_set`
- `pacify_enterprise_target_configure`

The generic `pacify_catalog_query` accepts the separate enterprise skill, agent, workflow, integration, and model catalog kinds.
