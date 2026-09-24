from pathlib import Path
import runtime.semantic_project_map_bridge as bridge

def test_project_map_normalization(monkeypatch, tmp_path: Path):
    def fake(root, query, **kwargs):
        return {"map_revision":"r1", "hits":[{"rank":1,"score":3.0,"id":"s1","kind":"symbol","title":"Engine.run","path":"alpha.py","line_start":2,"line_end":3,"summary":"run engine","reasons":["title:run"],"relations":["s2"]}]}
    monkeypatch.setattr(bridge, "query_project_map", fake)
    raw, evidence = bridge.query_project_map_evidence("p1", tmp_path, "run")
    assert raw["map_revision"] == "r1"
    assert evidence[0].locator == "alpha.py#L2-L3"
    assert evidence[0].source_kind == "project_map"

import pytest


def test_project_map_rejects_nonfinite_scores(monkeypatch, tmp_path: Path):
    def fake(root, query, **kwargs):
        return {"map_revision":"r1", "hits":[{"rank":1,"score":float("nan"),"id":"s1","kind":"symbol","title":"Engine.run","path":"alpha.py","line_start":2,"line_end":3,"summary":"run engine","reasons":[],"relations":[]}]}
    monkeypatch.setattr(bridge, "query_project_map", fake)
    with pytest.raises(ValueError, match="finite"):
        bridge.query_project_map_evidence("p1", tmp_path, "run")
