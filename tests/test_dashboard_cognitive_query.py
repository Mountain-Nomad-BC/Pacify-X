from __future__ import annotations

import json
from pathlib import Path

from runtime import dashboard_api


def _index(root: Path) -> None:
    registry = root / "registry"
    registry.mkdir(parents=True)
    payload = {
        "revision": "commissioned-rev",
        "records": [
            {"key":"skill:alpha", "id":"alpha", "kind":"skill", "title":"Alpha retrieval", "summary":"bounded retrieval skill", "owner":"px", "status":"admitted", "domain":"retrieval", "path":"registry/skills/alpha.json", "implementation_path":"", "aliases":[], "triggers":["retrieval"], "concepts":[], "inputs":[], "outputs":[], "dependencies":[], "formula_refs":[], "relations":[], "source_sha256":"a"*64, "source_provenance":[]},
            {"key":"capability:beta", "id":"beta", "kind":"capability", "title":"Beta retrieval operation", "summary":"retrieval operation", "owner":"px", "status":"active", "domain":"retrieval", "path":"registry/capabilities/beta.json", "implementation_path":"", "aliases":[], "triggers":["retrieval"], "concepts":[], "inputs":[], "outputs":[], "dependencies":[], "formula_refs":[], "relations":[], "source_sha256":"b"*64, "source_provenance":[]},
        ],
        "edges": [],
    }
    (registry / "cognitive_map_index.json").write_text(json.dumps(payload), encoding="utf-8")


def test_dashboard_cognitive_query_is_bounded_metadata_only(tmp_path: Path, capsys):
    _index(tmp_path)
    code = dashboard_api.main([
        "cognitive-query", "--source-root", str(tmp_path), "--query", "retrieval",
        "--project-id", "project-x", "--top-per-category", "2",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "px.cognitive-query-result/1.0"
    assert payload["authority_granted"] is False
    assert payload["top_per_category"] == 2
    assert payload["categories"]["skills"][0]["object_id"] == "alpha"
    assert payload["categories"]["operations"][0]["object_id"] == "beta"
    assert "body" not in json.dumps(payload)


def test_dashboard_cognitive_query_rejects_topk_above_three(tmp_path: Path):
    _index(tmp_path)
    try:
        dashboard_api._parser().parse_args([
            "cognitive-query", "--source-root", str(tmp_path), "--query", "retrieval",
            "--top-per-category", "4",
        ])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("top_per_category > 3 must be rejected")
