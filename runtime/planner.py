"""Frozen, resumable work-package planning with explicit requirement coverage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class Requirement:
    requirement_id: str
    text: str
    capability_id: str | None
    state: str = "missing"


@dataclass(frozen=True, slots=True)
class WorkNode:
    node_id: str
    requirement_id: str
    capability_id: str | None
    dependencies: tuple[str, ...]
    tests: tuple[str, ...]
    evidence: tuple[str, ...]
    status: str


@dataclass(frozen=True, slots=True)
class WorkPackage:
    package_id: str
    goal: str
    requirements_hash: str
    nodes: tuple[WorkNode, ...]
    blocked_requirements: tuple[str, ...]
    deferred_discoveries: tuple[str, ...]
    frozen: bool = True


def _fingerprint(requirements: Iterable[Requirement]) -> str:
    payload = json.dumps(
        [asdict(item) for item in requirements], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def build_work_package(
    goal: str,
    requirements: Iterable[Requirement],
    *,
    dependency_map: Mapping[str, tuple[str, ...]] | None = None,
    deferred: Iterable[str] = (),
) -> WorkPackage:
    requirements = tuple(sorted(requirements, key=lambda item: item.requirement_id))
    if not goal.strip() or not requirements:
        raise ValueError("goal and at least one requirement are required")
    if any(
        item.state not in {"existing", "partial", "missing", "blocked"}
        for item in requirements
    ):
        raise ValueError("unknown requirement state")
    dependencies = dependency_map or {}
    nodes = tuple(
        WorkNode(
            "work-" + item.requirement_id,
            item.requirement_id,
            item.capability_id,
            tuple(sorted(dependencies.get(item.requirement_id, ()))),
            ("positive", "negative", "effect-boundary"),
            ("deterministic-summary",),
            "complete"
            if item.state == "existing"
            else (
                "blocked"
                if item.capability_id is None or item.state == "blocked"
                else "pending"
            ),
        )
        for item in requirements
    )
    blocked = tuple(
        item.requirement_id
        for item in requirements
        if item.capability_id is None or item.state == "blocked"
    )
    digest = _fingerprint(requirements)
    return WorkPackage(
        digest[:16], goal, digest, nodes, blocked, tuple(sorted(set(deferred)))
    )


def save_work_package(package: WorkPackage, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(asdict(package), indent=2) + "\n")


def load_work_package(path: Path) -> WorkPackage:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return WorkPackage(
        payload["package_id"],
        payload["goal"],
        payload["requirements_hash"],
        tuple(
            WorkNode(
                **{
                    **item,
                    "dependencies": tuple(item["dependencies"]),
                    "tests": tuple(item["tests"]),
                    "evidence": tuple(item["evidence"]),
                }
            )
            for item in payload["nodes"]
        ),
        tuple(payload["blocked_requirements"]),
        tuple(payload["deferred_discoveries"]),
        payload["frozen"],
    )


def detect_scope_drift(
    package: WorkPackage, requirements: Iterable[Requirement]
) -> bool:
    return package.requirements_hash != _fingerprint(
        tuple(sorted(requirements, key=lambda item: item.requirement_id))
    )
