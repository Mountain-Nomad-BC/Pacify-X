import builtins
from pathlib import Path
import symtable
import sys
from types import SimpleNamespace
import pytest
from runtime import workflow_worker as worker
from runtime.workflow_group_config import required_group_effect_claims
from tests.test_model_group_preparation import prepared, plan_for
from tests.test_remote_profile_catalog import profile_config
from tests.test_remote_provider_placement import remote_plan


def test_worker_composition_has_no_unbound_owner_names():
    path = Path(worker.__file__)
    table = symtable.symtable(path.read_text(encoding="utf-8"), str(path), "exec")
    known = {symbol.get_name() for symbol in table.get_symbols()} | set(dir(builtins)) | {"__file__", "__name__", "__package__", "__spec__"}
    scope = next(child for child in table.get_children() if child.get_name() == "_run_model_group")
    assert not [symbol.get_name() for symbol in scope.get_symbols() if symbol.is_global() and symbol.is_referenced() and symbol.get_name() not in known]


def test_saved_vector_is_not_an_implicit_live_observer(tmp_path, monkeypatch):
    monkeypatch.delenv("PX_GROUP_GENERATION_OBSERVER", raising=False)
    group, _, _, preparation = prepared(1, tmp_path)
    assert worker._group_generation_observer(plan_for(group, preparation)) is None


def test_host_observer_is_called_again_and_checked_against_project(tmp_path, monkeypatch):
    group, _, _, preparation = prepared(1, tmp_path)
    plan = plan_for(group, preparation)
    values = [plan.context_generation, None]
    calls = []
    def observe(**kwargs):
        calls.append(kwargs)
        return values.pop(0)
    monkeypatch.setitem(sys.modules, "controlled_generation_owner", SimpleNamespace(observe=observe))
    monkeypatch.setenv("PX_GROUP_GENERATION_OBSERVER", "controlled_generation_owner:observe")
    callback = worker._group_generation_observer(plan, project_root=tmp_path)
    assert callback() == plan.context_generation
    with pytest.raises(PermissionError):
        callback()
    assert len(calls) == 2 and calls[0]["project_root"] == tmp_path


def test_host_assessment_returns_reference_not_an_approval_boolean(tmp_path, monkeypatch):
    group, _, _, preparation = prepared(1, tmp_path)
    plan = plan_for(group, preparation)
    monkeypatch.setitem(sys.modules, "controlled_assessment_owner", SimpleNamespace(assess=lambda **kwargs: True))
    monkeypatch.setenv("PX_GROUP_ATTESTATION_PROVIDER", "controlled_assessment_owner:assess")
    with pytest.raises(ValueError):
        worker._group_attestation_provider(tmp_path, plan)("model-0", {"artifact_sha256": "a" * 64})


def test_local_group_declares_loopback_and_shared_gateway_writes(tmp_path):
    from runtime.remote_provider_profiles import ROOT
    group, _, _, preparation = prepared(1, tmp_path)
    claims = required_group_effect_claims(plan_for(group, preparation))
    assert claims == frozenset({("execute", "runtime"), ("network", "loopback"), ("write", ROOT + "/gateway/events"), ("write", ROOT + "/gateway/budget")})


def test_remote_group_declares_its_signed_origin_not_generic_network(profile_config):
    plan, attached = remote_plan(profile_config)
    claims = required_group_effect_claims(plan)
    assert ("network", attached.origin) in claims
    assert ("network", "loopback") not in claims
    assert ("network", "*") not in claims
