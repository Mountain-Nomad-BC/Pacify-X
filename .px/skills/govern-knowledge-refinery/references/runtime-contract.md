# Runtime contract

- Canonical owner: `runtime/knowledge_refinery.py`
- Inventory: `portable_inventory`
- Novelty: `classify_novelty`
- Merge planning: `plan_merges`
- Graph control: `audit_graph`
- Project-local proposal staging: `stage_merge_plan`
- Workflow validator: `validate_refinery_orchestration`

Retrieval and dependency-closure behavior remain owned by `runtime/capability_routing.py`. Archive inspection remains owned by `scripts/inventory/build_archive_inventory.py`. Canonical mutation remains owned by the isolated project control plane; the refinery never bypasses those owners.
