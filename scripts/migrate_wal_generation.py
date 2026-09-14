"""Explicit legacy WAL activation for admitted, quiescent compatible writers.

Run only inside the operator's exact admitted migration scope after compatible
writer custody is established. A declaration hash binds configuration; it does
not establish quiescence or grant authority. Ordinary startup never calls this.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.archive_io import read_bounded_bytes, reject_path_links  # noqa: E402
from runtime.json_io import decode_json_object  # noqa: E402
from runtime.wal_migration import migrate_legacy_wals  # noqa: E402


def migrate(root, declaration_path, *, expected_declaration_sha256, fault_injector=None):
    if (type(expected_declaration_sha256) is not str
            or re.fullmatch(r'[0-9a-f]{64}', expected_declaration_sha256) is None):
        raise ValueError('migration requires the exact admitted declaration digest')
    declaration_path = Path(declaration_path)
    reject_path_links(declaration_path)
    raw = read_bounded_bytes(declaration_path, max_bytes=1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != expected_declaration_sha256:
        raise ValueError('migration declaration changed before execution')
    declaration = decode_json_object(raw, max_bytes=1024 * 1024)
    if set(declaration) != {'schema_version', 'owners'} or declaration['schema_version'] != 'px.wal-migration-declaration/1.0':
        raise ValueError('invalid migration declaration envelope')
    return migrate_legacy_wals(root, declaration['owners'], fault_injector=fault_injector)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--declaration', type=Path, required=True)
    parser.add_argument('--expected-declaration-sha256', required=True)
    args = parser.parse_args(argv)
    result = migrate(args.root, args.declaration, expected_declaration_sha256=args.expected_declaration_sha256)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
