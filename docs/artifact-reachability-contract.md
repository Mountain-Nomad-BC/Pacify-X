# Artifact inventory input contract

`build_artifact_reachability` reports declared ownership and binding labels. A
`release_validated` label, supplied entrypoint or matching generated inventory
is not proof that an operation ran or that its owner is currently authorized.

The builder checks the original physical root before normalization and makes
one bounded metadata traversal. Dependency/custody exclusions and named
quarantine directories are pruned before descent. Existing static/live
projection exclusions remain in place to avoid digest cycles.

Traversal ceilings are 30,000 files, 30,000 directories, 60,000 enumerated
entries, depth 80 and 2 GiB of accepted file metadata sizes. The whole request
has a cooperative 60-second deadline. It cannot interrupt a blocked OS call.
Unselected bodies are not opened; metadata work still counts against limits.

Before opening any selected body, the builder validates portable paths,
normalized path uniqueness, original links, regular-file metadata and the
complete selected size budget. Selected images are at most 8 MiB each and
256 MiB together. The two required control documents are at most 1 MiB each,
with JSON depth 32 and at most 100,000 nodes.

Both controls are validated before other selected files are hashed. Workflow
and project-stream bindings require actual typed unique identities, exact
counts, supported declaration modes and bounded entrypoint strings. The two
control byte images are retained for both parsing and hashing; each other
selected image is acquired once and only its digest is retained. Classification
order, filename owner rules, unbound workflow reporting and valid binding
strings preserve the existing output contract.

These checks do not pin ancestor handles, establish a multi-file snapshot,
authenticate supplied binding labels, resolve every owner or execute entrypoints.
The standalone publisher still needs its separate atomic-publication repair.
Generated root output stays frozen during repair and is regenerated only in the
campaign's single revision/projection reconciliation.
