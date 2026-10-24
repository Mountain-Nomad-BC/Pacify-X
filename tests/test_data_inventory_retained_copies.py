from runtime.data_inventory import build_inventory, erasure_plan

def test_actual_retained_foundry_and_personal_namespaces_refuse_erase(tmp_path):
    candidates = tmp_path / ".agentic_engineering_os_px/runtime-core/knowledge-foundry/candidates"
    bundle = candidates / ("a" * 64)
    bundle.mkdir(parents=True)
    source = bundle / "source-image.json"
    source.write_text('{"knowledge":["fixture personal example"]}')
    custody = candidates.parent / "resources.json"
    custody.write_text('{"fixture":"custody"}')
    personal = tmp_path / ".agentic_engineering_os_px/runtime-core/data-controls"
    personal.mkdir()
    policy = personal / "policy.json"
    policy.write_text('{"subject_id":"explicit-fixture"}')
    receipts = tmp_path / ".agentic_engineering_os_px/runtime-core/tie-migrations/receipts"
    receipts.mkdir(parents=True)
    receipt = receipts / "migration.json"
    receipt.write_text('{"source":"fixture object attribution","source_retained":true}')
    remote = tmp_path / ".agentic_engineering_os_px/runtime-core/remote-models"
    for location in (remote, remote / "gateway/events", remote / "gateway/budget"):
        location.mkdir(parents=True, exist_ok=True)
    inventory = build_inventory(tmp_path)
    expected = {"foundry-retained-candidates", "foundry-resource-custody", "personal-control-namespace", "tie-migration-receipts"}
    expected |= {"remote-provider-configuration", "remote-provider-operation-events", "remote-provider-budget-ledger"}
    stores = {row["store_id"]: row for row in inventory["stores"]}
    for name in expected:
        assert stores[name]["present"] and stores[name]["preservation_required"]
        assert stores[name]["erasable"] is False and stores[name]["may_contain_personal_data"]
        assert stores[name]["subject_record_resolution_required"]
    plan = erasure_plan(inventory, ["explicit-fixture"])
    refused = {row["store_id"] for row in plan["refused_stores"]}
    assert expected <= refused and inventory["coverage_complete"] is False
    assert source.read_text() == '{"knowledge":["fixture personal example"]}'
    assert policy.exists() and custody.exists()
    assert receipt.read_text() == '{"source":"fixture object attribution","source_retained":true}'
