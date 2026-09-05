from copy import deepcopy
import json
from pathlib import Path

import pytest

from runtime.authority_topology import (
    resolve_effect_authority,
    validate_authority_topology,
)


def _topology(root):
    return json.loads((root / "registry/authority_topology.json").read_text(encoding="utf-8"))


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_live_authority_topology_is_complete():
    repo_root = REPO_ROOT
    report = validate_authority_topology(repo_root)
    assert report["valid"], report["errors"]
    assert resolve_effect_authority(repo_root, "project_transfer")["authoritative_gate"]["symbol"] == "authorize_project_transfer"


@pytest.mark.parametrize("failure", ["missing_gate", "missing_rollback", "missing_bypass", "duplicate", "missing_vectors"])
def test_topology_fails_closed_for_authority_gaps(failure):
    repo_root = REPO_ROOT
    value = deepcopy(_topology(repo_root))
    target = value["effects"][0]
    if failure == "missing_gate":
        target.pop("authoritative_gate")
    elif failure == "missing_rollback":
        target.pop("rollback_owner")
    elif failure == "missing_bypass":
        target.pop("bypass_detector")
    elif failure == "duplicate":
        value["effects"].append(deepcopy(target))
        value["effect_count"] += 1
    else:
        target = next(item for item in value["effects"] if len(item["runtimes"]) > 1)
        target.pop("conformance_vectors")
    assert not validate_authority_topology(repo_root, value)["valid"]
