# Environment capability map

The Environment Map is a separate project-owned discovery data model under `.engineering-bootstrap/environment`. It does not merge installed resources into Pacify-X admission registries, enterprise state, coordination leases, or canonical memory.

The uniform semantic contract is:

`resource → capabilities → interface → requirements → effects → conflicts → policy → state`

On startup, on VS Code extension changes, and on **Workflows → Environment Map → Refresh map + graph**, the extension performs bounded read-only discovery:

- Installed VS Code extension manifests, contribution points, declared commands, activation constraints, dependencies, workspace/virtual-workspace declarations, and duplicate command providers.
- Fixed local version probes for Python, Node, npm, Git, Docker, Ollama, uv, and the VS Code CLI.
- `python -m pip list --format=json`, global `npm ls`, and project `npm ls` when a project package manifest exists.

Arbitrary extensions are never activated. Packages are never installed or updated. Provider API contracts, command arguments/returns, permissions, effects, and conflicts are not inferred when the manifest does not declare them.

## Lazy storage

`current.json` contains only schema, ontology, counts, boundaries, hashes, and dataset descriptors. Immutable content-addressed snapshots contain separate extension indexes, per-extension contracts, tools, Python packages, npm packages, graph nodes, and graph edges. Every lazy read validates its path boundary, size, and SHA-256 digest. `events.jsonl` records added/removed semantic node identities and prior/current hashes.

The dashboard loads only the selected subject tab. MCP exposes bounded `pacify_environment_inventory` subject queries and `pacify_environment_extension_detail` for one extension contract. This lets connected AI clients inspect available resources without loading or treating all detected capabilities as active.
