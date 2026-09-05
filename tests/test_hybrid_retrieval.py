from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from runtime.retrieval import RetrievalSource, retrieve


ROOT = Path(__file__).resolve().parents[1]


def test_portable_adapter_supports_source_and_installed_package_names() -> None:
    source = (
        ROOT
        / ".px/skills/operate-memory-retrieval-observability/scripts/authoritative_hybrid_retrieval.py"
    ).read_text(encoding="utf-8")
    assert "from engineering_bootstrap.retrieval import RetrievalSource, retrieve" in source
    assert "from runtime.retrieval import RetrievalSource, retrieve" in source


BASE = RetrievalSource(
    "candidate",
    "unrelated",
    "unrelated body",
    ("public",),
    "fixture:1",
    source_revision="sha256:fixture",
)


@pytest.mark.parametrize(
    ("field", "value", "component"),
    (
        ("dense_score", 1.0, "dense_vector"),
        ("metadata", {"topic": "needle"}, "metadata"),
        ("structured", {"entity": "needle"}, "structured"),
        ("graph_score", 1.0, "graph"),
        ("freshness", 1.0, "freshness"),
        ("trust", 1.0, "trust"),
    ),
)
def test_each_optional_signal_independently_affects_score(
    field: str, value: object, component: str
) -> None:
    baseline = retrieve("needle", (BASE,), identity_scope=())
    changed = retrieve("needle", (replace(BASE, **{field: value}),), identity_scope=())
    assert baseline.hits == ()
    assert changed.hits[0].component_scores[component] > 0
    assert changed.hits[0].signal_status[component] == "available"


def test_lexical_signal_and_unavailable_signals_are_truthful() -> None:
    result = retrieve(
        "needle", (replace(BASE, text="needle"),), identity_scope=()
    )
    hit = result.hits[0]
    assert hit.component_scores["lexical"] > 0
    assert result.signal_availability["lexical"] == "available"
    assert result.signal_availability["dense_vector"] == "unavailable"
    assert "dense_vector" not in hit.component_scores
    assert hit.source_revision == "sha256:fixture"
    assert result.canonical_owner == "runtime.retrieval.retrieve"


def test_ranking_is_deterministic_and_rejects_invalid_scores() -> None:
    tied = (replace(BASE, source_id="b", trust=1.0), replace(BASE, source_id="a", trust=1.0))
    assert [hit.source_id for hit in retrieve("needle", tied, identity_scope=()).hits] == [
        "a",
        "b",
    ]
    with pytest.raises(ValueError, match="between 0 and 1"):
        retrieve("needle", (replace(BASE, trust=1.1),), identity_scope=())


def test_advertised_cli_delegates_to_canonical_owner(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.json"
    corpus.write_text(
        json.dumps([{"id": "a", "text": "needle", "metadata": {}}]),
        encoding="utf-8",
    )
    script = Path(__file__).parents[1] / ".px/skills/operate-memory-retrieval-observability/scripts/authoritative_hybrid_retrieval.py"
    completed = subprocess.run(
        [sys.executable, str(script), str(corpus), "needle", "-k", "1"],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["canonical_owner"] == "runtime.retrieval.retrieve"
    assert result["signal_availability"]["dense_vector"] == "unavailable"
