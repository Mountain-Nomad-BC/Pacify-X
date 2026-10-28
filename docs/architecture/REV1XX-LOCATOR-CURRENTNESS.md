# Versioned current locators — W1 repair increment

The canonical entity ID remains independent of location. Locator contract
`px.semantic-locator/2.0` binds a locator ID to complete location geometry and
its monotonic revision. The `pxl1:` identity prefix remains unchanged; schema
version and identity prefix are separate contracts. Returning A → B → A creates
three distinct revisions, while repeating an identical observation is idempotent.

`LocatorRegistry` retains immutable observation records in bounded in-memory
history. Exhausting the bound fails before mutation and requires an explicit
archival disposition. This increment does not implement durable history across
process restarts, import prototype v1 observations, or manufacture old records.

Current resolution excludes retired entities and superseded locators. Reverse
reference resolution returns every current matching entity, preserving ambiguity
when multiple symbols share a file. Historical inspection is a separate metadata
API and grants no execution authority. Relocation preserves geometry but clears
the previous timestamp, observer and confidence rather than representing an old
observation as a new fact.

The normal PX Archivist `describe_entity` consumer now exposes `canonical_locator`
as a fresh typed mapping. Its map still contains proposed semantic entities;
locator presence does not establish acceptance, reachability for execution, or
completion of the universal semantic census.

Focused regression tests cover geometry changes, non-recycled IDs, retirement,
reverse ambiguity, provenance, invalid inputs, bounded history and the live native
contract. Campaign receipts under `rev1xx-w1-locator-currentness` retain actual
failures and subsequent verification. W1 remains open for durable ownership,
all remaining consumers, meaningful compact addresses, universal projection
gating, coverage and convergence. Builds, installs and Git reconciliation remain
on hold.

## Snapshot recovery increment

`snapshot_bytes()` exports complete retained history as a bounded canonical JSON
image. `from_snapshot_bytes(current_entities, image)` restores that image only
after native locator-contract validation, content-digest verification, contiguous
revision checks, complete geometry binding and current entity-owner lookup.
Bounds are 10,000 observations and 16 MiB per snapshot, in addition to each
registry's history limit. Duplicate JSON keys, unknown fields, missing entities,
old schema records, invalid observations and incomplete histories fail closed.

The snapshot digest detects content changes; it is not authentication or evidence
of authorization. Recovery cannot create, accept or revive an entity. Retired
history can be inspected, but current resolvers continue to exclude it.

The public registry recovery path is tested through an actual disk roundtrip.
This supplies a recoverable metadata format, not an activated durable store:
production persistence ownership, publication admission, concurrent writer
reconciliation and remaining project-map consumers still require integration.

## Current root and external namespace policy

`LocatorReferencePolicy` is immutable current caller configuration. Its default
allows portable repository-relative paths and no external namespaces. Optional
roots restrict the repository namespace at path-component boundaries. Absolute
paths, traversal, backslashes, alternate streams, unsafe Windows components and
ambiguous spellings fail before a locator or history observation is registered.

URI roots require an exact scheme and authority plus a path-component prefix.
Credentials, malformed authorities and encoded traversal/separator ambiguity are
rejected. Opaque external handles require an explicit colon-terminated namespace.
Configurations are bounded and validated; an empty root list admits no paths.

Snapshot recovery applies the current caller policy to every retained record.
The image cannot declare a wider policy. An incompatible old history blocks
recovery rather than silently dropping observations. Policy migration or archival
disposition is a separate owner action.

These are lexical metadata checks. They do not resolve symlinks, read files,
perform network requests, establish a canonical owner or authorize any effect.
Real reads and execution still require their own current control-plane checks.

## Normal Archivist recovery and exact resolution

`load_semantic_map(root, locator_snapshot=...)` validates supplied history against
the independently reconstructed current entity owner, then records current source
locators through the same registry. The map exports a freshness-checked immutable
snapshot through `locator_snapshot_bytes()`. Snapshot content is part of its
projection identity; repeating unchanged inputs and retained history converges.

`resolve_reference()` accepts exact declared/canonical IDs, explicitly bound
compact aliases and exact current paths. Historical path lookup is opt-in and
returns every canonical candidate, including ambiguity when a path was reused.
`describe_entity()` uses this resolver for path/alias inputs, reports ambiguity
without choosing an owner, and exposes the actual proposed canonical lifecycle
separately from the asset's operational status. Fuzzy search never supplies an
authoritative identity to this path.

Unknown prior entities block recovery rather than dropping their history. A
durable canonical entity owner and explicit tombstone migration remain required
to retain removed entities. Snapshot data is caller-supplied metadata; its digest
does not authenticate historical provenance or grant execution authority. Store
publication/reconciliation and the other project-map/provenance/query consumers
remain open. This increment does not accept W1 as a whole.
