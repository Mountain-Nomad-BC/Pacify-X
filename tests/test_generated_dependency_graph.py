from runtime.release_preflight import generated_dependency_graph


def test_generated_cycle_is_reported_with_stable_code() -> None:
    result = generated_dependency_graph({"a.json": ["b.json"], "b.json": ["a.json"]})
    assert not result["valid"]
    assert result["failures"][0]["code"] == "RP-GEN-002"
    assert result["cycles"] == [["a.json", "b.json"]]


def test_generated_dag_passes() -> None:
    assert generated_dependency_graph({"b.json": ["a.json"], "c.json": ["b.json"]})["valid"]


def test_graph_cli_requires_admission_before_any_write(tmp_path, monkeypatch):
    import pytest
    from scripts import generated_dependency_graph as cli
    monkeypatch.setattr('sys.argv', ['graph', '--root', str(tmp_path)])
    with pytest.raises(SystemExit):
        cli.main()
    assert list(tmp_path.iterdir()) == []


def test_graph_cli_delegates_to_existing_owner(tmp_path, monkeypatch):
    import json
    from scripts import generated_dependency_graph as cli
    policy = tmp_path / 'policies'; policy.mkdir()
    (policy / 'release-preflight.json').write_text(json.dumps({'generated_authorities': {'b.json': ['a.json']}}))
    calls = []
    def publish(root, relative, image, *, admission_event_id):
        calls.append((root, relative, image, admission_event_id))
    monkeypatch.setattr(cli, 'publish_guarded_registry_projection', publish)
    monkeypatch.setattr('sys.argv', ['graph', '--root', str(tmp_path), '--admission-event-id', 'explicit-admission'])
    assert cli.main() == 0
    assert len(calls) == 1
    assert calls[0][0] == tmp_path
    assert calls[0][1] == 'registry/generated_dependency_graph.json'
    assert calls[0][2]['valid'] is True
    assert calls[0][3] == 'explicit-admission'
    assert not (tmp_path / 'registry').exists()


def test_invalid_graph_never_calls_publication_owner(tmp_path, monkeypatch):
    import json
    from scripts import generated_dependency_graph as cli
    policy = tmp_path / 'policies'; policy.mkdir()
    (policy / 'release-preflight.json').write_text(json.dumps({'generated_authorities': {'a.json': ['a.json']}}))
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid graph must not publish')
    monkeypatch.setattr(cli, 'publish_guarded_registry_projection', forbidden)
    monkeypatch.setattr('sys.argv', ['graph', '--root', str(tmp_path), '--admission-event-id', 'explicit-admission'])
    assert cli.main() == 2
    assert not (tmp_path / 'registry').exists()


def test_graph_producer_delegation_is_proven_without_granting_review_approval():
    from pathlib import Path
    from runtime.effect_surface import classify_source_file
    from runtime.mutating_producer_registry import default_classification, _delegated_publication_verdict
    root = Path(__file__).resolve().parents[1]
    relative = 'scripts/generated_dependency_graph.py'
    records = classify_source_file((root / relative).read_text(), relative)
    assert _delegated_publication_verdict(root, relative, records) == {
        'classification': 'exempt', 'reason': 'delegated_publication'}
    # A new publication route is not permission to approve a reviewed-table entry.
    assert default_classification(root, relative, ('filesystem_mutation',), records=records) is None
