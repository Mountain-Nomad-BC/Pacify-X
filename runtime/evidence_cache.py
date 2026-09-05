"""Revision-complete content cache; cached projections never become authority."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping
from uuid import uuid4

from .file_lock import FileLock


SHA = re.compile(r"^[a-f0-9]{64}$")


def _bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _hash(value: object) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


class EvidenceCache:
    """Stores immutable values under keys binding every declared dependency."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.directory = self.root / ".engineering-bootstrap/evidence-cache"
        self.manifest = self.directory / "manifest.json"
        self.lock = self.directory / ".cache.lock"

    @staticmethod
    def key(
        namespace: str,
        *,
        source_revision: str,
        authority_revision: str,
        toolchain_revision: str,
        dependency_revisions: Mapping[str, object],
    ) -> str:
        revisions = {
            "source_revision": source_revision,
            "authority_revision": authority_revision,
            "toolchain_revision": toolchain_revision,
            **{str(key): str(value) for key, value in dependency_revisions.items()},
        }
        if not namespace.strip() or not revisions or any(
            not SHA.fullmatch(value) for value in revisions.values()
        ):
            raise ValueError("evidence cache key requires every exact revision")
        return _hash({"namespace": namespace, "revisions": dict(sorted(revisions.items()))})

    def _load(self) -> dict[str, object]:
        try:
            value = json.loads(self.manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        entries = value.get("entries") if isinstance(value, Mapping) else None
        return {"schema_version": "px.evidence-cache/1.0", "entries": dict(entries or {})}

    def _write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
        prepared.write_bytes(data)
        os.replace(prepared, path)

    def put(self, key: str, value: object) -> dict[str, object]:
        if not SHA.fullmatch(key):
            raise ValueError("evidence cache key is invalid")
        data = _bytes(value)
        content = hashlib.sha256(data).hexdigest()
        blob = self.directory / "blobs" / f"{content}.json"
        self.directory.mkdir(parents=True, exist_ok=True)
        with FileLock(self.lock, timeout_seconds=10):
            if blob.exists() and blob.read_bytes() != data:
                raise RuntimeError("evidence cache content collision")
            if not blob.exists():
                self._write(blob, data)
            manifest = self._load()
            entries = manifest["entries"]
            assert isinstance(entries, dict)
            entries[key] = {"content_sha256": content, "bytes": len(data)}
            self._write(self.manifest, json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")
        return {"key": key, "content_sha256": content, "canonical": False}

    def get(self, key: str) -> object | None:
        if not SHA.fullmatch(key):
            return None
        with FileLock(self.lock, timeout_seconds=10):
            entry = self._load()["entries"].get(key)  # type: ignore[union-attr]
            if not isinstance(entry, Mapping):
                return None
            path = self.directory / "blobs" / f"{entry.get('content_sha256')}.json"
            try:
                data = path.read_bytes()
            except OSError:
                return None
            if len(data) != entry.get("bytes") or hashlib.sha256(data).hexdigest() != entry.get("content_sha256"):
                return None
            return json.loads(data)
