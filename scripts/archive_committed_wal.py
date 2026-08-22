"""Hash-seal and reclaim superseded committed JSON-WAL transaction folders."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.archive_project_map_history import (
    _canonical,
    _is_reparse,
    _sha256,
    _verify_archive,
    _write_archive,
)


MAX_HASH_WORKERS = 8


def _hash_inventory(
    committed: Path, transactions: list[Path]
) -> list[dict[str, object]]:
    """Build a deterministic inventory with bounded parallel file hashing."""
    candidates: list[tuple[str, Path, int]] = []
    for transaction in transactions:
        if transaction.resolve().parent != committed:
            raise ValueError("committed WAL transaction escaped its authority root")
        for path in sorted(transaction.rglob("*")):
            if _is_reparse(path):
                raise ValueError("committed WAL contains a reparse point")
            if path.is_file():
                candidates.append(
                    (
                        path.relative_to(committed).as_posix(),
                        path,
                        path.stat().st_size,
                    )
                )
    workers = max(1, min(MAX_HASH_WORKERS, len(candidates) or 1, os.cpu_count() or 1))
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="px-wal-hash"
    ) as pool:
        hashes = list(pool.map(lambda row: _sha256(row[1]), candidates))
    return [
        {"path": relative, "sha256": digest, "size_bytes": size}
        for (relative, _path, size), digest in zip(candidates, hashes, strict=True)
    ]


def plan(
    root: Path,
    *,
    wal_root: Path = Path(".engineering-bootstrap/operation-bus/wal"),
    keep_latest: int = 200,
) -> dict[str, object]:
    root = root.resolve(strict=True)
    supplied = wal_root if wal_root.is_absolute() else root / wal_root
    journal = supplied.resolve(strict=True)
    try:
        relative_journal = journal.relative_to(root)
    except ValueError as error:
        raise ValueError("WAL root is outside the bounded project") from error
    if journal.name != "wal" or ".engineering-bootstrap" not in relative_journal.parts:
        raise ValueError("WAL root is not an admitted PX journal")
    committed = (journal / "committed").resolve(strict=True)
    if committed.parent != journal:
        raise ValueError("committed WAL root escaped its journal")
    if keep_latest < 1 or keep_latest > 10_000:
        raise ValueError("keep_latest must be between 1 and 10000")
    transactions = sorted(path for path in committed.iterdir() if path.is_dir())
    if any(_is_reparse(path) for path in transactions):
        raise ValueError("committed WAL contains a reparse-point transaction")
    selected = transactions[:-keep_latest] if len(transactions) > keep_latest else []
    files = _hash_inventory(committed, selected)
    manifest = {
        "schema_version": "px.committed-wal-archive-manifest/1.0",
        "wal_root": relative_journal.as_posix(),
        "retained_live_transactions": [path.name for path in transactions[-keep_latest:]],
        "archived_transactions": [path.name for path in selected],
        "file_count": len(files),
        "size_bytes": sum(int(row["size_bytes"]) for row in files),
        "files": files,
    }
    digest = hashlib.sha256(_canonical(manifest)).hexdigest()
    return {
        "valid": True,
        "apply": False,
        "manifest": manifest,
        "manifest_sha256": digest,
        "selected_count": len(selected),
    }


def apply(
    root: Path,
    *,
    wal_root: Path = Path(".engineering-bootstrap/operation-bus/wal"),
    keep_latest: int = 200,
) -> dict[str, object]:
    root = root.resolve(strict=True)
    decision = plan(root, wal_root=wal_root, keep_latest=keep_latest)
    manifest = decision["manifest"]
    if not manifest["archived_transactions"]:
        return {**decision, "apply": True, "changed": False}
    journal = (root / str(manifest["wal_root"])).resolve(strict=True)
    committed = (journal / "committed").resolve(strict=True)
    archive_root = journal / "archives"
    archive_root.mkdir(parents=True, exist_ok=True)
    first = manifest["archived_transactions"][0]
    last = manifest["archived_transactions"][-1]
    target = archive_root / f"committed-{first}-{last}-{decision['manifest_sha256'][:16]}.zip"
    if target.exists():
        _verify_archive(target, manifest)
    else:
        _write_archive(committed, target, manifest)
        _verify_archive(target, manifest)
    for name in manifest["archived_transactions"]:
        transaction = (committed / str(name)).resolve(strict=True)
        if transaction.parent != committed or _is_reparse(transaction):
            raise ValueError("committed WAL reclamation target is unsafe")
    for name in manifest["archived_transactions"]:
        shutil.rmtree(committed / str(name))
    receipt = {
        "schema_version": "px.committed-wal-archive-receipt/1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "wal_root": manifest["wal_root"],
        "archive": target.relative_to(root).as_posix(),
        "archive_sha256": _sha256(target),
        "manifest_sha256": decision["manifest_sha256"],
        "archived_transactions": manifest["archived_transactions"],
        "retained_live_transactions": manifest["retained_live_transactions"],
        "file_count": manifest["file_count"],
        "source_size_bytes": manifest["size_bytes"],
        "archive_size_bytes": target.stat().st_size,
        "reclaimed_bytes": int(manifest["size_bytes"]) - target.stat().st_size,
        "recovery": f"Verify archive_sha256, then extract below {manifest['wal_root']}/committed.",
        "hard_delete_without_archive": False,
    }
    receipt_root = root / ".engineering-bootstrap/cleanup-receipts"
    receipt_root.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_root / f"committed-wal-{decision['manifest_sha256'][:16]}.json"
    prepared = receipt_path.with_suffix(".json.prepared")
    prepared.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    os.replace(prepared, receipt_path)
    return {
        **decision,
        "apply": True,
        "changed": True,
        "archive": target.as_posix(),
        "archive_sha256": receipt["archive_sha256"],
        "archive_size_bytes": target.stat().st_size,
        "reclaimed_bytes": receipt["reclaimed_bytes"],
        "receipt": receipt_path.as_posix(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--wal-root", type=Path, default=Path(".engineering-bootstrap/operation-bus/wal")
    )
    parser.add_argument("--keep-latest", type=int, default=200)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = (
        apply(args.root, wal_root=args.wal_root, keep_latest=args.keep_latest)
        if args.apply
        else plan(args.root, wal_root=args.wal_root, keep_latest=args.keep_latest)
    )
    print(json.dumps({key: value for key, value in result.items() if key != "manifest"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
