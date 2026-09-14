# Release preflight input contract

Feedback, evidence portability and evidence budget checks share one lazy request
context in `run_preflight`. Callback construction performs no IO. The original
eight-check order is preserved. Separate public diagnostic calls have separate
contexts and do not establish one combined release result.

Feedback accepts at most 1,024 actual string declarations in a list or tuple.
Paths are bounded to 4,096 UTF-8 bytes and 128 components, use portable identities,
and are checked for original traversal, physical containment, links/reparse points,
unsupported parents and hard-linked existing files. Only whole-component
`<release>` and `<run-id>` placeholders are supported. Declarations are not observed
writes, reachability proof or authority to execute an effect.

Consumed classification must explicitly be valid and product-valid with no errors.
Up to 250,000 unique product records are checked for typed nonnegative sizes and
64-character lowercase hexadecimal digests. Product metadata is detached from the
classifier result. This does not attest file contents or repair the classifier's
own acquisition boundary. A zero or unknown source denominator is unevaluated,
with a null amplification ratio; it cannot pass the budget check.

Preflight policy is strict JSON with schema `px.release-preflight-policy/1.0`,
bounded to 1 MiB, depth 32 and 100,000 nodes. Full preflight and feedback/budget CLIs
require it. A standalone portability diagnostic may use the existing default
250 MiB aggregate, 100 MiB per file and 20x amplification limits if it is absent.
Configured aggregate bytes are limited to 1 GiB, single-file bytes to 256 MiB,
and amplification must be finite and nonnegative. Boolean numeric aliases fail.

Evidence selection uses the current version's recursive release directory when
pyproject.toml exists; otherwise it uses shallow evidence files. It also includes
shallow extension/evidence files. It does not descend into historical releases or
quarantine. One metadata inventory admits at most 10,000 files, 10,000 directories,
20,000 entries, depth 128 and 1 GiB of file bytes under a shared cooperative
60-second deadline. Physical aliases and ambiguous portable paths fail closed.
All selected sizes are checked against policy before any selected evidence body
is opened. Non-text files count toward bytes even when not scanned for locators.

The text set is JSON, JSONL, NDJSON, XML, LOG, TXT, MD, SVG, SIG and SHA256SUMS.
Each selected text image is read from one checked handle in chunks of at most
64 KiB. Opening and final metadata, byte count and EOF witness must agree. The
stream must be exhausted before claiming a complete image; early exits close it.
The existing whole-image reader still has its 64 MiB materialization ceiling.
The streaming scanner preserves existing locator rules across UTF-8 and chunk
boundaries, with at most 4,096 UTF-8 bytes per locator and 4,096 findings per
request. Incomplete scans return null counts, never a false clean result.

The three callbacks retain detached declarations and a single selected metadata
inventory. Selected files are rechecked before results are accepted. This is not
an atomic cross-file snapshot: new directory members are not rediscovered,
ancestors are not held open, and same-metadata external rewrites are not excluded.
Cooperative checks cannot interrupt blocked operating-system calls. Source binding,
publication, finalization and installed-system certification remain separate owners.

Verification: tests/test_release_preflight_inputs.py,
tests/test_release_streaming_inputs.py and tests/test_release_preflight_integration.py,
plus the existing feedback, budget and portability diagnostic tests. Changed
sections are runtime-domain-contracts, studio-memory-graph and testing-governance.
Passing focused tests is not a release certification.
