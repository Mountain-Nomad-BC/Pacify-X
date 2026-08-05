"""Shared deterministic helpers for corpus reduction scripts."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Iterator

_PRIVATE_TERMS = ("r" + "ie", "re" + "my", "rh" + "eem")
_PRIVATE_PATTERN = re.compile(
    rf"(?i)(?:(?<![A-Za-z])({'|'.join(_PRIVATE_TERMS[:2])})(?![A-Za-z])|({_PRIVATE_TERMS[2]}))"
)
_REPLACEMENTS = dict(
    zip(
        _PRIVATE_TERMS,
        (
            "intelligent_integrations_and_engines",
            "governed_retrieval_system_with_deterministic_rails",
            "enterprise",
        ),
    )
)
_LEGACY_TERMS = ("integration" + "_" + "engine", "governed" + "_" + "retrieval")
_LEGACY_REPLACEMENTS = dict(zip(_LEGACY_TERMS, tuple(_REPLACEMENTS.values())[:2]))
_LEGACY_PATTERN = re.compile(
    rf"(?i)({_LEGACY_TERMS[0]}|{_LEGACY_TERMS[1]}(?!_system_with_deterministic_rails))"
)


def sanitize(value: str) -> str:
    cleaned = _PRIVATE_PATTERN.sub(
        lambda match: _REPLACEMENTS[match.group(0).lower()], value
    )
    return _LEGACY_PATTERN.sub(
        lambda match: _LEGACY_REPLACEMENTS[match.group(1).lower()], cleaned
    )


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{path}:{line_number}: invalid JSONL: {error}"
                ) from error


def write_jsonl(path: Path, records: Iterable[dict]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            line = canonical_json(record) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
    return count, digest.hexdigest()


def parse_roots(values: list[str]) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    labels: set[str] = set()
    for value in values:
        if "=" not in value:
            raise ValueError("each --root must be label=path")
        label, raw_path = value.split("=", 1)
        label = re.sub(r"[^a-z0-9_-]+", "-", label.casefold()).strip("-")
        if not label or label in labels:
            raise ValueError(f"invalid or duplicate root label: {label}")
        path = Path(raw_path).resolve()
        if not path.is_dir():
            raise ValueError(f"root is not a directory: {path}")
        labels.add(label)
        roots.append((label, path))
    return sorted(roots, key=lambda item: item[0])


def simhash64(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    weights = [0] * 64
    for token, count in Counter(tokens).items():
        value = int.from_bytes(
            hashlib.sha256(token.encode("utf-8")).digest()[:8], "big"
        )
        for bit in range(64):
            weights[bit] += count if value & (1 << bit) else -count
    result = sum(1 << bit for bit, weight in enumerate(weights) if weight >= 0)
    return f"{result:016x}"


def hamming_hex(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()
