
# n8n security, extensions, AI, and MCP

n8n can hold broad credentials, accept public input, execute code, install third-party packages, and call internal systems. Security therefore spans:
- user and role access;
- webhook authentication and replay resistance;
- credential ownership, scope, rotation, and retention;
- outbound network destinations;
- Code nodes and task-runner isolation;
- community/custom node supply chain;
- execution-data retention and log redaction;
- patch and rollback discipline.

Community nodes are executable dependencies. Prefer built-ins or HTTP Request where maintainable. Otherwise quarantine, scan, review dependencies and network behavior, pin, test, allowlist, and document removal.

For AI and MCP, expose only narrow tools, validate schemas, treat retrieved text as untrusted, separate retrieval from authorization, keep production/destructive actions behind human approval, and retain immediate revocation.
