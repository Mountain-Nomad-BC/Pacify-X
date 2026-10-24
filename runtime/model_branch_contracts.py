"""Per-branch outcome contracts and mesh convergence for the N-way model mesh.

This module owns what a branch PRODUCED and when N branches AGREE. It performs no
model calls and picks no winner: it validates branch results and computes whether
convergence was reached, leaving selection to a separate authority.

The separation matters because convergence and selection are different claims.
``consensus_reached`` is a fact about agreement. ``recommended_model_id`` is a
judgement about quality, and conflating them lets a two-way tie silently become
"the winner won on merit".

Convergence is computed over CANONICALISED digests, not raw text. Two branches
that produce byte-identical output agree exactly. Two that produce text differing
only in whitespace do NOT - agreement here means substantive agreement, and
pretending otherwise would let formatting noise manufacture consensus.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "px.model-branch-contract/1.0"

#: Branch terminal states. ``failed`` is terminal for the branch but does NOT by
#: itself prevent convergence; a quorum may still be met by the survivors.
COMPLETED = "completed"
FAILED = "failed"
SKIPPED = "skipped"
BRANCH_STATES = (COMPLETED, FAILED, SKIPPED)


class BranchContractError(ValueError):
    """A branch result is malformed or inconsistent with its group."""


def canonical_digest(text: str) -> str:
    """Substantive digest of a branch output.

    Line endings are normalised and trailing whitespace stripped, because those
    are transport artifacts rather than content. Interior whitespace and case
    are preserved: two answers differing in wording have NOT converged, and
    collapsing that difference would manufacture agreement.
    """
    if type(text) is not str:
        raise BranchContractError("branch output must be text")
    normalised = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))
    return hashlib.sha256(normalised.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BranchResult:
    """What one branch produced."""

    model_id: str
    state: str
    output: str = ""
    detail: str | None = None

    def __post_init__(self) -> None:
        if type(self.model_id) is not str or not self.model_id.strip() or len(self.model_id) > 256:
            raise BranchContractError("branch result requires a model_id")
        if self.state not in BRANCH_STATES:
            raise BranchContractError(
                f"branch state {self.state!r} is not one of {', '.join(BRANCH_STATES)}"
            )
        if type(self.output) is not str or len(self.output.encode("utf-8")) > 524288:
            raise BranchContractError("branch output must be bounded text")
        if self.state == COMPLETED and not self.output.strip():
            # A "completed" branch with no output is a contradiction, and
            # accepting it would let a silent branch count as agreement.
            raise BranchContractError(
                "a completed branch must carry output; an empty result is failed, "
                "not completed"
            )
        if self.detail is not None and (
            type(self.detail) is not str or len(self.detail) > 512
        ):
            raise BranchContractError("branch detail must be bounded text or null")

    @property
    def usable(self) -> bool:
        return self.state == COMPLETED and bool(self.output)

    def digest(self) -> str | None:
        return canonical_digest(self.output) if self.usable else None

    def as_mapping(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "state": self.state,
            "output_sha256": self.digest(),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class MeshOutcome:
    """The aggregate result of one N-way execution."""

    group_id: str
    quorum: str
    quorum_size: int
    completed: tuple[str, ...]
    failed: tuple[str, ...]
    skipped: tuple[str, ...]
    agreement_buckets: tuple[tuple[str, ...], ...]
    consensus_reached: bool
    largest_agreement: int

    def as_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "group_id": self.group_id,
            "quorum": self.quorum,
            "quorum_size": self.quorum_size,
            "completed": list(self.completed),
            "failed": list(self.failed),
            "skipped": list(self.skipped),
            "agreement_buckets": [list(bucket) for bucket in self.agreement_buckets],
            "consensus_reached": self.consensus_reached,
            "largest_agreement": self.largest_agreement,
            # No recommended model: selection is a separate authority.
            "recommended_model_id": None,
        }


def evaluate_mesh(
    group_id: str,
    branch_count: int,
    quorum: str,
    results: Sequence[BranchResult],
) -> MeshOutcome:
    """Compute convergence across branch results.

    ``consensus_reached`` means a quorum of branches produced the SAME
    substantive output. It does not mean the group succeeded overall: a quorum
    may be met while other branches failed, and both facts are reported.
    """
    if type(branch_count) is not int or not 1 <= branch_count <= 12:
        raise BranchContractError("branch_count must be a positive integer bounded by12")
    if quorum not in {"any", "all", "majority"}:
        raise BranchContractError("quorum must be one of any, all, majority")

    seen: set[str] = set()
    for result in results:
        if not isinstance(result, BranchResult):
            raise BranchContractError("results must be BranchResult values")
        if result.model_id in seen:
            raise BranchContractError(
                f"duplicate branch result for {result.model_id}"
            )
        seen.add(result.model_id)
    if len(results) != branch_count:
        raise BranchContractError(
            f"expected {branch_count} branch results, received {len(results)}"
        )

    buckets: dict[str, list[str]] = {}
    completed: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    for result in results:
        if result.state == FAILED:
            failed.append(result.model_id)
            continue
        if result.state == SKIPPED:
            skipped.append(result.model_id)
            continue
        completed.append(result.model_id)
        digest = result.digest()
        assert digest is not None  # guaranteed by BranchResult validation
        buckets.setdefault(digest, []).append(result.model_id)

    ordered = sorted(buckets.items(), key=lambda kv: (-len(kv[1]), tuple(sorted(kv[1]))))
    agreement = tuple(tuple(sorted(models)) for _, models in ordered)
    largest = max((len(bucket) for bucket in agreement), default=0)

    if quorum == "any":
        required = 1
    elif quorum == "all":
        required = branch_count
    else:
        required = branch_count // 2 + 1

    return MeshOutcome(
        group_id=group_id,
        quorum=quorum,
        quorum_size=required,
        completed=tuple(sorted(completed)),
        failed=tuple(sorted(failed)),
        skipped=tuple(sorted(skipped)),
        agreement_buckets=agreement,
        consensus_reached=largest >= required,
        largest_agreement=largest,
    )
