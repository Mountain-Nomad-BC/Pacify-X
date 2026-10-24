# Accountable source census

`runtime.semantic_surfaces.collect_corpus_snapshot` owns extraction for both
`run_full_census` and `run_prefreeze_census`. Their `source_census` fields expose
the same accounting contract. Default collection no longer samples symbols or
surface populations. An explicit surface limit is a whole-file sample budget;
every file that exceeds it retains a `budget_exhausted` disposition.

The canonical source-boundary classifier determines authored inputs. The
canonical bounded walker rejects links, inaccessible trees and exhausted
traversal bounds. Those failures abort collection rather than claiming a full
denominator. Authored files outside the extraction catalog retain an explicit
`unsupported_surface` disposition. Unsupported JSON structure, invalid syntax,
encoding/read failures and source changes during extraction remain visible.
Oversized files cannot be fully hashed within the read budget and say so.

The report binds the extraction generator, taxonomy seed, source-boundary code,
selected owners, exclusions, current source images and extracted entity image.
Runtime evidence may receive an exclusion record but cannot change the authored
source revision. The report is a defensive copy. No timestamp or model inference
creates acceptance, canonical identity or execution authority.

`accounting_complete` means the bounded source inventory remained stable during
collection, including file identity, size and mutation metadata checked after
extraction. `extraction_complete` additionally requires an unsampled scope and
no unresolved extraction dispositions. A complete accounting report can still
contain unsupported files and therefore incomplete extraction. Such a report
cannot satisfy the semantic migration gate.

These consumers remain taxonomy proposals. The existing candidate bucket model
does not satisfy the locked collision-free semantic address acceptance. Frozen
vocabularies, canonical identity admission, remaining file extractors, locator
consumers and W1 acceptance are separate open work. No build, install, source
freeze or migration is authorized by a census result.

Fallback extraction owners cover authored Python, JavaScript, JSON, Markdown,
YAML and TOML outside specialized catalogs. Specialized owners take precedence
and no duplicate extraction is introduced. YAML/TOML expose mapping metadata
only; no workflow execution follows from a parsed document. Existing
entity-worthiness policy records intentional fixture/non-entity exclusions.
An explicitly cataloged skill is observed as a skill proposal even when its
folder name resembles an example; it still receives no execution authority.

## JSONL metadata coverage

Generator `px.semantic-surfaces/2.1` adds one shared JSONL extraction owner.
Every observed file contributes a container proposal; each object record adds a
separate metadata proposal with its actual LF-based source line. Empty journals
therefore contribute zero experience records. Line-shaped proposal keys are
observation locators, not canonical entity IDs or accepted knowledge.

The native JSON decoder rejects duplicate keys, non-finite numbers and malformed
values. Blank interior lines and BOMs fail; non-object records remain explicitly
unsupported. Malformed tails and record-budget failures reject the whole file,
preserving its source hash without publishing a valid-looking prefix. Bounds are
the existing 8 MiB source acquisition limit, 10,000 records per file and bounded
reference metadata. CRLF and Unicode separators inside strings preserve actual
record line geometry. Both taxonomy consumers use this same extraction owner.

The scoped live observation found 36 empty usage containers and one observed
817-record stream. One graph stream exceeds the current record budget; 67 other
files remain unsupported. Complete accounting is not complete extraction, so
these findings cannot unlock W1 migration. The first live observation incorrectly
treated empty streams as parse failures; its actual report remains retained.

The combined regression checks also reproduced a same-size rewrite that kept
its observed timestamps, defeating the earlier final stat-only freshness check.
Final verification now rehashes each bounded authored byte image before issuing
a source revision. Changed or unreadable final content blocks accounting,
extraction and revision claims. The original failure and deterministic
timestamp-preserving reproduction remain retained. This strengthens content
currentness; it is still an observational snapshot, not atomic filesystem pinning.

## Native security graph extraction owner

Generator `px.semantic-surfaces/2.2` assigns the exact
`registry/security_capabilities/graph.jsonl` source to the existing security JSONL
decoder. Its established limits remain 20,000 lines, 64 KiB per line and 16 MiB
total. The shared census retains its stronger 8 MiB source-acquisition bound;
ordinary JSONL files retain the 10,000-record limit. The decoder's source hash
is recorded as a generator dependency, and malformed tails and native budget
failures cannot publish partial metadata.

This owner parses the complete bounded graph stream as source metadata. It does
not validate graph topology, accept semantic identities, admit external skills,
hydrate bodies or grant security execution authority. Those controls remain with
their existing owners and subsequent semantic acceptance gates.

## Traced output ownership

The operational ledger lock and the extension project's resource-lifecycle
custody namespace are runtime state owned by their actual ledger writers.
The exact project `engineering_loop_bootstrap.egg-info/` tree is packaging
metadata from the declared setuptools backend. The exact
`extension/tests/generated/plugin-lifecycle/` tree belongs to the fixture
generator and its UI test consumers. These outputs are excluded from authored
source and engine identity; similarly named authored files remain included.

No preserved output is deleted or regenerated. Packaging and fixture
regenerability remain unverified while builds and installs are on hold.
The boundary registry is published atomically with its temporary path registered
and reconciled through native resource custody. These ownership corrections do
not close the remaining source-format or W1 semantic acceptance requirements.

## Native PowerShell source observations

Generator `px.semantic-surfaces/2.3` observes `.ps1` files through the host's
native PowerShell AST parser. A fixed parser program reads one owned UTF-8
snapshot, binds its actual byte digest, and extracts function/class declarations
with native line and UTF-16 offset geometry. Comments and string contents do
not become declarations; repeated same-line declarations remain distinct
observations. Observed source bodies are never executed.

The source and result bounds are 8 MiB, with at most 4,096 declarations and
512 native name characters. Syntax errors, exceeded budgets, missing native
parsers, failed result binding and timeouts publish no partial declarations.
Unavailable parsing stays explicit in the file denominator and prevents
extraction completeness. The native parser version, executable digest and
source-image digest accompany successful file observations; the extraction
owner's source digest is a generator dependency.

Parser processes and snapshot workspaces use native resource custody and are
reconciled after success, syntax failure and timeout. This is metadata parsing,
not script execution, all command/dependency analysis, canonical identity
acceptance, authentication of the host binary, or build/install validation.
Native positive checks require an available parser; absence is separately
tested as an explicit unavailable state rather than claimed as native proof.

Uncertain process custody retains the image and marks the run recoverable;
it cannot publish successful metadata or delete the retained snapshot. A
negative fixture exercises this branch after reaping its real test child.
Current diagnostics also show that identical authored inputs and proposals
can have different full census result digests as native custody audit files
accumulate. Separating stable source binding from the complete physical audit
remains an explicit W1 fixed-point dependency; no full convergence is claimed.

## Stable source binding with complete audit retained

Generator `px.semantic-surfaces/2.4` adds a separately typed
`px.source-census-binding/1.0` record and digest. It includes every authored
image and disposition, proposal digest/count, chosen owner scope and budget,
exclusion policy, taxonomy/worthiness/source-boundary identities, extraction
owner dependencies and native parser provenance. Its schema digest is bound
too. Acquisition drift or missing source bytes cannot publish a current binding.

The original `result_sha256` still hashes the complete report, including all
observed custody/audit rows. The source binding excludes those traced runtime
rows from its source domain while retaining them in the physical audit. Both
existing taxonomy consumers expose the source binding digest. Unsupported,
sampled or unavailable extraction stays incomplete; this record grants neither
canonical identity nor execution authority. Stable source binding alone does
not satisfy the remaining whole-W1 convergence and semantic acceptance gates.
