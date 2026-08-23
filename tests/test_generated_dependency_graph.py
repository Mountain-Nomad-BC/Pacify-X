from runtime.release_preflight import generated_dependency_graph


def test_generated_cycle_is_reported_with_stable_code() -> None:
    result = generated_dependency_graph({"a.json": ["b.json"], "b.json": ["a.json"]})
    assert not result["valid"]
    assert result["failures"][0]["code"] == "RP-GEN-002"
    assert result["cycles"] == [["a.json", "b.json"]]


def test_generated_dag_passes() -> None:
    assert generated_dependency_graph({"b.json": ["a.json"], "c.json": ["b.json"]})["valid"]
