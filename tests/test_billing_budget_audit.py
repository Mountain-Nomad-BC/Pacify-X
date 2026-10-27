import pytest

from runtime.capability_scheduler import Resources, Scheduler, Task


@pytest.mark.parametrize("field,value", [
    ("estimated_cost", float("nan")), ("estimated_cost", float("inf")),
    ("estimated_cost", -1), ("estimated_cost", True), ("estimated_cost", "0.1"), ("estimated_cost", 10**400),
    ("maximum_cost", float("nan")), ("maximum_cost", float("inf")),
    ("maximum_cost", -1), ("maximum_cost", True), ("maximum_cost", "1"),
])
def test_observe_only_scheduler_denies_invalid_budget_numbers(field, value):
    budget = {"maximum_cost": 1, "estimated_cost": 0.5, field: value}
    scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 1}))
    task = Task(id="task", capability="noop", resources=Resources.from_mapping({"cpu_cores": 1}), budget=budget)
    scheduler.add(task)
    allowed, reasons = scheduler.eligible(task)
    assert allowed is False
    assert "budget_exhausted" in reasons


@pytest.mark.parametrize("budget,expected", [({}, True), ({"maximum_cost": 0, "estimated_cost": 0}, True),
    ({"maximum_cost": 0, "estimated_cost": 0.1}, False),
    ({"maximum_cost": 1, "estimated_cost": 1}, True),
    ({"maximum_cost": 1}, False), ({"estimated_cost": 1}, False)])
def test_observe_only_budget_admission_preserves_zero_and_rejects_incomplete_bounds(budget, expected):
    scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 1}))
    task = Task(id="task", capability="noop", resources=Resources.from_mapping({"cpu_cores": 1}), budget=budget)
    scheduler.add(task)
    assert scheduler.eligible(task)[0] is expected


def test_native_provider_receipt_crosses_owned_node_boundary_and_rejects_tampering():
    import json
    import shutil
    from pathlib import Path
    from runtime.process_supervisor import ProcessSupervisor
    from runtime.resource_lifecycle import ResourceManager
    from tests.test_provider_gateway_streaming import _project, _gateway, _request, FakeStreamAdapter

    source = Path(__file__).resolve().parents[1]
    owned = source / '.tmp/provider-receipt-operating'
    owned.mkdir(parents=True, exist_ok=True)
    manager = ResourceManager(owned / 'resources.json')
    registered = manager.create_workspace(owned, project_id='provider-receipt', run_id='cross-runtime',
        lane_id='contract-proof', creator='codex', retention_required=True)
    workspace = Path(registered.path)
    root = _project(str(workspace))
    state = workspace / 'provider-state'
    state.mkdir()
    receipt = _gateway(root, state).stream(_request(), FakeStreamAdapter(), lambda event: None)
    receipt_path = workspace / 'native-receipt.json'
    receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
    worker = workspace / 'verify-receipt.js'
    worker.write_text("const assert = require('node:assert/strict');\n"
        f"const {{ verifiedReceipt }} = require({json.dumps(str(source / 'extension/src/agentHarness/adapters/pxProviderGateway.js'))});\n"
        "const receipt = JSON.parse(require('node:fs').readFileSync(process.argv[2], 'utf8'));\n"
        "const worker = { providerId:'fixture-local', modelId:'model-1', costClass:'local' };\n"
        "const input = { task:{taskId:'inv-1'}, executionContext:{execution_id:'inv-1'} };\n"
        "assert.equal(verifiedReceipt(receipt, worker, input).charge_microunits, 0);\n"
        "assert.throws(() => verifiedReceipt({...receipt, charge_microunits:1}, worker, input), /integrity/);\n"
        "assert.throws(() => verifiedReceipt(receipt, {...worker, modelId:'wrong'}, input), /owner-mismatch/);\n"
        "console.log('native receipt accepted; tampered and wrong-owner receipts rejected');\n", encoding='utf-8')
    node = shutil.which('node')
    assert node, 'Node is required for the mandatory cross-runtime receipt boundary'
    budget = dict(startup_timeout_seconds=10, idle_timeout_seconds=10, total_timeout_seconds=30,
        graceful_shutdown_seconds=1, force_shutdown_seconds=5, stdout_limit_bytes=4096, stderr_limit_bytes=4096)
    action = dict(action_id='provider-receipt-cross-runtime', effects=['process'], allowed_effects=['process'],
        owned_paths=[str(workspace)], target_paths=[str(workspace)], budget=budget, limits=budget,
        approval=True, policy_override_requested=False)
    result = ProcessSupervisor(manager).run([node, str(worker), str(receipt_path)], cwd=workspace,
        action=action, project_id='provider-receipt', run_id='cross-runtime', lane_id='contract-proof', creator='codex')
    assert result.exit_code == 0, result.stdout.text + result.stderr.text
    assert result.tree_closed is True and not manager.ledger.get(result.resource_id).active
    assert 'native receipt accepted' in result.stdout.text

