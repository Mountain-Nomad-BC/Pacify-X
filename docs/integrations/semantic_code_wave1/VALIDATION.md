# Wave 1 Validation Record

Validation date: 2026-09-20.

Validation base: exact user-supplied `Pacify-X-main (1).zip` (`SHA-256 ea44d4ba8150b583781eac0fce4c89cfd3808ddf6e2e064fedeb9d688ec88650`) with the reviewed Wave-1 payload overlaid into a disposable copy.

## Focused semantic-code tests

Command:

```text
python -m pytest -q tests/test_semantic_code_*.py
```

Result after Wave-1 hardening:

```text
36 passed
```

The original source payload produced 35/35. The implementation pass added coverage for finite time budgets, incompatible session reuse, and consistent client-facing receipts, producing 36 tests without adding a new repository path.

## PX neighborhood regression

Command:

```text
python -m pytest -q tests/test_bounded_walk.py tests/test_file_lock_contention.py tests/test_project_mapping.py tests/test_semantic_code_*.py
```

Result:

```text
139 passed, 2 skipped
```

## Real PX-tree semantic smoke

The reviewed implementation indexed the disposable current PX tree itself:

```text
analyzed_files:    757
analyzed_bytes:    9,701,959
symbol_count:      13,700
reference_count:   307,665
diagnostic_count:  1
elapsed:            13.42 s
max RSS:            461,220 KiB
```

Representative exact queries correctly located:

- `runtime.file_lock.FileLock`
- `runtime.bounded_walk.bounded_walk`
- `runtime.semantic_code_service.SemanticCodeService`

The one diagnostic is from the intentionally invalid fixture `tests/fixtures/semantic_code/python_project/broken.py` and is expected.

## Implementation-pass hardening

Compared with the source payload, this reviewed Wave 1 additionally:

- rejects `bool`, NaN and infinity for semantic wall-clock budgets and deadlines;
- reads source snapshots through one open file handle and compares file identity/size/mtime before and after acquisition;
- prevents an existing project session from silently being reused under different write authority, limits, or backend registry;
- emits deterministic receipts from project summary, symbol search/overview, reference search, diagnostics, and edit application/preview surfaces.

## Admission note

These checks establish Wave-1 behavior on the supplied snapshot. They do not replace the live repository's own generated-authority reconciliation, source-inventory update, full certification, installed-host verification, or release process after the files are copied into the user's active worktree.
