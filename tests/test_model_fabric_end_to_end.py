from pathlib import Path

from runtime.admitted_fabric_integrations import vscode_model_client_status
from runtime.provider_budget import load_budget_policy
from runtime.vscode_model_bridge import list_models

ROOT = Path(__file__).parents[1]


def test_model_client_is_fail_closed_without_an_admitted_project_router(tmp_path: Path):
    status = vscode_model_client_status(ROOT)
    assert status["authority_granted"] is False
    assert status["certified_profile_count"] == 1
    assert status["stream_adapter_admitted"] is True
    assert list_models(ROOT, tmp_path) == {
        "schema_version": "px.vscode-model-list/1.0",
        "models": [],
        "authority_granted": False,
    }


def test_vscode_local_llama_budget_is_nonbillable_and_does_not_grant_adapter_authority():
    policy = load_budget_policy(ROOT)
    row = next(item for item in policy["budgets"] if item["budget_id"] == "local-vscode-models")
    assert row["actor_id"] == "pacify-x-vscode"
    assert row["provider_id"] == "llama.cpp"
    assert row["hard_limit_microunits"] == 0
    assert row["max_charge_per_request_microunits"] == 0
