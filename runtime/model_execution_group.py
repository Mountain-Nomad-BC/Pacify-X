"""N-way model execution group - one governed slot in an N-way mesh.

A model execution group is a GOVERNED SLOT in the N-way mesh: a declaration of
how many branches may run, who authorises them, and what happens when they
disagree. It is not the execution itself and it does not pick winners. That is
deliberate - selection is a separate, later decision with its own authority.

Why a governed declaration at all
----------------------------------
Without one, "run three models and see" is indistinguishable from an
unbounded fan-out that multiplies cold-start cost, latency and spend. The group
makes the fan-out explicit, bounded, attributed and replayable.

Two properties this module refuses to give up:

* **The bound is real.** ``branch_count`` is capped by
  :data:`MAX_CHALLENGER_BRANCHES`. A request for more is refused rather than
  clamped, because silently reducing a caller's fan-out would misrepresent what
  was run.
* **Authority is attributed.** ``authority_id`` must be non-empty. An unattributed
  group cannot be audited, and an unauditable mesh is how cost disappears.

Discovery vs calibration vs execution
-------------------------------------
The mesh distinguishes *finding* candidates (discovery), *measuring* them
(calibration) and *running* them (execution). Only the last is claimed here. A
group that declares discovery or calibration makes no claim about outputs, so a
caller cannot mistake a search for a result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence
import hashlib
from .json_io import bounded_canonical_json_bytes

MAX_MODEL_GROUP_MEMBERS = 12

SCHEMA_VERSION = "px.model-execution-group/2.0"

#: What a group is for. Discovery finds candidates, calibration measures them,
#: execution runs them. Only ``execution`` produces outputs.
DISCOVERY = "discovery"
CALIBRATION = "calibration"
EXECUTION = "execution"
PURPOSES = (DISCOVERY, CALIBRATION, EXECUTION)

#: Branch roles within the mesh. A ``proposal`` may answer; a ``challenger``
#: exists to be compared against one. The distinction is what makes convergence
#: meaningful rather than a popularity contest.
PROPOSAL = "proposal"
CHALLENGER = "challenger"
ANCHOR = "anchor"
BRANCH_ROLES = (PROPOSAL, CHALLENGER, ANCHOR)


class ModelExecutionGroupError(ValueError):
    """An execution group is malformed or exceeds its admitted bound."""


@dataclass(frozen=True, slots=True)
class RoleWorkContract:
    deliverable: str
    context_sha256: str
    max_output_bytes: int = 524288

    def __post_init__(self):
        _text(self.deliverable, "deliverable")
        if (type(self.context_sha256) is not str or len(self.context_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.context_sha256)):
            raise ModelExecutionGroupError("context_sha256 must be SHA256")
        if type(self.max_output_bytes) is not int or not 1 <= self.max_output_bytes <= 524288:
            raise ModelExecutionGroupError("invalid branch output budget")


@dataclass(frozen=True, slots=True)
class IndependenceContract:
    commit_before_peer_visibility: bool = True
    peer_input_allowed: bool = False

    def __post_init__(self):
        if self.commit_before_peer_visibility is not True or self.peer_input_allowed is not False:
            raise ModelExecutionGroupError("independent branches must commit before peer visibility")


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise ModelExecutionGroupError(f"{label} must be bounded nonempty text")
    if any(ord(character) < 32 for character in value):
        raise ModelExecutionGroupError(f"{label} contains a control character")
    return value


@dataclass(frozen=True, slots=True)
class BranchAssignment:
    """One branch inside the group: a model and the role it plays."""

    model_id: str
    role: str
    weight: float = 1.0
    work_contract: RoleWorkContract | None = None
    independence_contract: IndependenceContract | None = None
    agent_generation_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.model_id, "branch model_id")
        if self.agent_generation_id is not None:
            _text(self.agent_generation_id, "agent_generation_id")
        if (self.work_contract is None) != (self.independence_contract is None):
            raise ModelExecutionGroupError("both branch contracts must be bound together")
        if self.work_contract is not None:
            if type(self.work_contract) is not RoleWorkContract or type(self.independence_contract) is not IndependenceContract:
                raise ModelExecutionGroupError("branch contracts must be typed")
            if self.agent_generation_id is None:
                raise ModelExecutionGroupError("contracted branch requires agent generation")
        if self.role not in BRANCH_ROLES:
            raise ModelExecutionGroupError(
                f"branch role {self.role!r} is not one of {', '.join(BRANCH_ROLES)}"
            )
        # Weight is a float but must be a REAL number: bool is an int subclass,
        # and True would silently become weight 1.0.
        if type(self.weight) is not float or self.weight < 0.0:
            raise ModelExecutionGroupError("branch weight must be a non-negative float")
        if self.weight != self.weight or self.weight in (float("inf"), float("-inf")):
            raise ModelExecutionGroupError("branch weight must be finite")

    def as_mapping(self) -> dict[str, Any]:
        body = {
            "model_id": self.model_id,
            "role": self.role,
            "weight": self.weight,
        }
        if self.work_contract is not None:
            from dataclasses import asdict
            body.update(work_contract=asdict(self.work_contract), independence_contract=asdict(self.independence_contract),
                        agent_generation_id=self.agent_generation_id)
        elif self.agent_generation_id is not None:
            body["agent_generation_id"] = self.agent_generation_id
        return body


@dataclass(frozen=True, slots=True)
class ModelExecutionGroup:
    """A bounded, attributed N-way mesh declaration.

    Constructing one asserts nothing about model availability; that is a
    placement decision made elsewhere. What it does assert is that the fan-out
    is declared, bounded, attributed, and reproducible from this record alone.
    """

    group_id: str
    purpose: str
    authority_id: str
    branches: tuple[BranchAssignment, ...]
    quorum: str = "any"
    determinism_seed: int | None = None
    minimum_quorum: int | None = None

    def __post_init__(self) -> None:
        _text(self.group_id, "group_id")
        _text(self.authority_id, "authority_id")
        if self.purpose not in PURPOSES:
            raise ModelExecutionGroupError(
                f"purpose {self.purpose!r} is not one of {', '.join(PURPOSES)}"
            )
        if not isinstance(self.branches, tuple) or not self.branches:
            raise ModelExecutionGroupError("an execution group requires at least one branch")
        for branch in self.branches:
            if not isinstance(branch, BranchAssignment):
                raise ModelExecutionGroupError("branches must be BranchAssignment values")
        count = len(self.branches)
        if self.minimum_quorum is not None and (type(self.minimum_quorum) is not int or not 1 <= self.minimum_quorum <= count):
            raise ModelExecutionGroupError("minimum quorum must fit declared membership")
        if count > MAX_MODEL_GROUP_MEMBERS:
            # Refused, not clamped: silently reducing the fan-out would make the
            # record disagree with what the caller believed it requested.
            raise ModelExecutionGroupError(
                f"{count} branches exceeds the admitted bound of "
                f"{MAX_MODEL_GROUP_MEMBERS}; widen MAX_MODEL_GROUP_MEMBERS "
                "deliberately rather than silently running fewer"
            )
        model_ids = [branch.model_id for branch in self.branches]
        if len(set(model_ids)) != len(model_ids):
            raise ModelExecutionGroupError(
                "a branch may not appear twice; duplicate models waste a slot "
                "and make convergence ambiguous"
            )
        if self.quorum not in {"any", "all", "majority"}:
            raise ModelExecutionGroupError(
                "quorum must be one of any, all, majority"
            )
        if self.determinism_seed is not None and (
            type(self.determinism_seed) is not int
            or isinstance(self.determinism_seed, bool)
            or not 0 <= self.determinism_seed < 2**32
        ):
            raise ModelExecutionGroupError(
                "determinism_seed must be a uint32 when supplied"
            )

    # -- derived facts ---------------------------------------------------------

    @property
    def branch_count(self) -> int:
        return len(self.branches)

    @property
    def model_ids(self) -> tuple[str, ...]:
        """Branch order is declaration order, which is the replay order."""
        return tuple(branch.model_id for branch in self.branches)

    @property
    def challengers(self) -> tuple[str, ...]:
        return tuple(b.model_id for b in self.branches if b.role == CHALLENGER)

    @property
    def proposals(self) -> tuple[str, ...]:
        return tuple(b.model_id for b in self.branches if b.role == PROPOSAL)

    @property
    def produces_outputs(self) -> bool:
        """Only an execution group claims outputs.

        Discovery and calibration must not be mistaken for a result, so the
        distinction is queryable rather than implied by a naming convention.
        """
        return self.purpose == EXECUTION

    def quorum_size(self) -> int:
        if self.minimum_quorum is not None:
            return self.minimum_quorum
        if self.quorum == "any":
            return 1
        if self.quorum == "all":
            return self.branch_count
        return self.branch_count // 2 + 1

    def as_mapping(self) -> dict[str, Any]:
        body = {
            "schema_version": SCHEMA_VERSION,
            "group_id": self.group_id,
            "purpose": self.purpose,
            "authority_id": self.authority_id,
            "branch_count": self.branch_count,
            "max_branches": MAX_MODEL_GROUP_MEMBERS,
            "branches": [branch.as_mapping() for branch in self.branches],
            "quorum": self.quorum,
            "quorum_size": self.quorum_size(),
            "produces_outputs": self.produces_outputs,
            "determinism_seed": self.determinism_seed,
        }
        if self.minimum_quorum is not None:
            body["minimum_quorum"] = self.minimum_quorum
        return body

    def digest_input(self) -> dict[str, Any]:
        """The replayable identity of this group.

        Excludes nothing: purpose, authority, branch order and weights all
        affect what actually ran, so a replay must be able to distinguish two
        groups that differ only in one of those.
        """
        body = {
            "group_id": self.group_id,
            "purpose": self.purpose,
            "authority_id": self.authority_id,
            "branches": [branch.as_mapping() for branch in self.branches],
            "quorum": self.quorum,
            "determinism_seed": self.determinism_seed,
        }
        if self.minimum_quorum is not None:
            body["minimum_quorum"] = self.minimum_quorum
        return body

    @property
    def group_sha256(self):
        return hashlib.sha256(bounded_canonical_json_bytes(self.digest_input(), max_bytes=65536)).hexdigest()

    @property
    def contract_set_sha256(self):
        return hashlib.sha256(bounded_canonical_json_bytes([
            {key: value for key, value in branch.as_mapping().items() if key in
             {"model_id", "work_contract", "independence_contract"}} for branch in self.branches], max_bytes=65536)).hexdigest()


def read_execution_group(record):
    """Restore strict canonical metadata, checking all derived values."""
    if type(record) is not dict or type(record.get("branches")) is not list or not 1 <= len(record["branches"]) <= 12:
        raise ModelExecutionGroupError("invalid bounded group record")
    from .generation_bound_verdict import validate_record
    validate_record(record, "model-execution-group")
    try:
        branches = []
        for item in record["branches"]:
            values = dict(item)
            if values.get("work_contract") is not None:
                values["work_contract"] = RoleWorkContract(**values["work_contract"])
                values["independence_contract"] = IndependenceContract(**values["independence_contract"])
            branches.append(BranchAssignment(**values))
        group = ModelExecutionGroup(record["group_id"], record["purpose"], record["authority_id"], tuple(branches),
                                    record["quorum"], record["determinism_seed"], record.get("minimum_quorum"))
        if record != group.as_mapping():
            raise ModelExecutionGroupError("group derived values or fields were changed")
        return group
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelExecutionGroupError("invalid canonical group record") from exc


def build_execution_group(
    group_id: str,
    purpose: str,
    authority_id: str,
    *,
    proposal_models: Sequence[str] = (),
    challenger_models: Sequence[str] = (),
    anchor_models: Sequence[str] = (),
    quorum: str = "any",
    determinism_seed: int | None = None,
    minimum_quorum: int | None = None,
) -> ModelExecutionGroup:
    """Build a group from role-partitioned model lists.

    Proposals come first, then challengers, then anchors. Declaration order is
    replay order, and stabilising it here means a rebuild produces the same
    branch order rather than a set-iteration accident.
    """
    branches: list[BranchAssignment] = []
    for role, models in (
        (PROPOSAL, proposal_models),
        (CHALLENGER, challenger_models),
        (ANCHOR, anchor_models),
    ):
        for model_id in models:
            branches.append(BranchAssignment(model_id=model_id, role=role))
    return ModelExecutionGroup(
        group_id=group_id,
        purpose=purpose,
        authority_id=authority_id,
        branches=tuple(branches),
        quorum=quorum,
        determinism_seed=determinism_seed,
        minimum_quorum=minimum_quorum,
    )
