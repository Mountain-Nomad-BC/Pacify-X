"""A current source hash cannot authorize caller-written scan conclusions."""
import json

from runtime.provider_gateway import build_provider_route_index, scan_direct_provider_routes
from tests.test_studio_operation_mirror_custody import native


def _index(tmp_path):
    (tmp_path / "runtime").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "registry").mkdir()
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "runtime/bypass.py").write_text("import openai\nclient.responses.create(model='fixture')\n")
    return build_provider_route_index(tmp_path)


def test_builder_rederives_violations_from_source_not_prior_claims(tmp_path):
    prior = _index(tmp_path)
    prior["records"][0]["violations"] = []
    (tmp_path / "registry/provider_route_scan.json").write_text(json.dumps(prior))
    current = build_provider_route_index(tmp_path)
    assert current["report"]["valid"] is False
    assert current["report"]["violation_count"] == 2


def test_current_index_cannot_replace_native_report_with_success(tmp_path):
    forged = _index(tmp_path)
    forged["report"].update(valid=True, violations=[], violation_count=0)
    (tmp_path / "registry/provider_route_scan.json").write_text(json.dumps(forged))
    result = scan_direct_provider_routes(tmp_path)
    assert result["valid"] is False
    assert result["violations"][0]["kind"] == "index_invalid"


def test_exact_current_negative_report_remains_current_and_negative(tmp_path):
    index = _index(tmp_path)
    (tmp_path / "registry/provider_route_scan.json").write_text(json.dumps(index))
    result = scan_direct_provider_routes(tmp_path)
    assert result["index_current"] is True
    assert result["valid"] is False and result["violation_count"] == 2


def test_stale_source_cannot_be_accepted_by_rediscovery(tmp_path):
    index = _index(tmp_path)
    (tmp_path / "registry/provider_route_scan.json").write_text(json.dumps(index))
    (tmp_path / "runtime/bypass.py").write_text("VALUE = 1\n")
    result = scan_direct_provider_routes(tmp_path)
    assert result["valid"] is False and result["index_current"] is False
    assert result["violations"][0]["kind"] == "index_stale"


def test_real_cli_publishes_actual_scan_through_native_owner(native, monkeypatch):
    import hashlib
    from scripts import build_provider_route_index as cli
    from runtime.effect_intent import EffectIntentLedger
    from runtime.scope_lease import ScopeLeaseStore
    root, admission = native
    (root / "runtime").mkdir()
    (root / "scripts").mkdir()
    (root / "runtime/reader.py").write_text("VALUE = 1\n")
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr("sys.argv", ["provider-index", "--admission-event-id", admission])
    assert cli.main() == 0
    image = (root / "registry/provider_route_scan.json").read_bytes()
    assert json.loads(image) == build_provider_route_index(root)
    committed = EffectIntentLedger(root)._load()["intents"]
    assert any(row["state"] == "committed" and row["result_sha256"] == hashlib.sha256(image).hexdigest()
               for row in committed)
    assert ScopeLeaseStore(root).active(effect="write") == ()
