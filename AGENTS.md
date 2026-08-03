# Repository engineering contract

- Keep startup bounded: inspect compact metadata before loading detailed skills or policy text.
- Use only admitted capabilities and declare effects before execution.
- Ask for approval before writes, installs, network access, services, migrations, or destructive work.
- Checkpoint material steps and retain evidence for completion claims.
- Run `python -m unittest discover -s tests -v` and `python -m runtime.cli validate` after control-plane changes.
- Never hard-delete source, owned, unknown, generated, failed, superseded, temporary, cache, or bytecode artifacts. Inventory, hash, move to recoverable quarantine, verify, and retain a recovery receipt.
- Treat staged intake as open until the user explicitly closes it. Require two matching full-tree snapshots and an immediate pre-move equality check before sanitization or quarantine.
