from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from runtime.projection_dependencies import validate_graph_authority_manifest


ROOT = Path(__file__).parents[1]


def test_live_graph_authority_manifest_accounts_for_every_major_graph():
    result = validate_graph_authority_manifest(ROOT)
    assert result["valid"], result["errors"]
    assert result["graph_count"] == 10


def test_duplicate_authority_shape_missing_revision_and_stale_graph_fail():
    payload = json.loads((ROOT / "registry/graph_authority_manifest.json").read_text())
    duplicate = deepcopy(payload)
    duplicate["graphs"][1]["path"] = duplicate["graphs"][0]["path"]
    assert not validate_graph_authority_manifest(ROOT, duplicate)["valid"]
    missing = deepcopy(payload)
    missing["graphs"][0]["source_revisions"] = []
    assert not validate_graph_authority_manifest(ROOT, missing)["valid"]
    stale = deepcopy(payload)
    stale["graphs"][0]["graph_revision"] = "0" * 64
    result = validate_graph_authority_manifest(ROOT, stale)
    assert not result["valid"]
    assert any("consumer graph is stale" in item for item in result["errors"])


def test_distinct_graph_semantics_are_not_collapsed():
    payload = json.loads((ROOT / "registry/graph_authority_manifest.json").read_text())
    purposes = [row["purpose"] for row in payload["graphs"]]
    assert len(purposes) == len(set(purposes))
    assert len({row["path"] for row in payload["graphs"]}) == 10
