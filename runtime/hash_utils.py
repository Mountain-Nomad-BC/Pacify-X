"""Unbounded legacy hashing variants; never an authority or bounded JSON substitute."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_hash(value, *, ensure_ascii, default):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=ensure_ascii, default=default).encode("utf-8")).hexdigest()


def json_ascii_string_hash(value: object) -> str:
    return _json_hash(value, ensure_ascii=True, default=str)


def json_utf8_hash(value: object) -> str:
    return _json_hash(value, ensure_ascii=False, default=None)


def json_utf8_string_hash(value: object) -> str:
    return _json_hash(value, ensure_ascii=False, default=str)
