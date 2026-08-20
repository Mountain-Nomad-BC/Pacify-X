# Authorization and visibility

- Authorize from verified identity claims plus server policy; reject client-supplied privilege assertions.
- Filter sources before scoring or context assembly and surface the lineage of every returned result.
- Permit mutation only through the owning service contract with approval and idempotency.
- Negative tests: forged role, hidden source, cross-tenant identifier, direct storage write, replayed mutation.

Lineage: clean-room generalization of reviewed control patterns; no product-specific implementation is active.
