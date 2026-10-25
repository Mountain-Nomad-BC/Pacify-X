import pytest

from runtime.capability_scheduler import Resources, Scheduler, Task


@pytest.mark.parametrize("field,value", [
    ("estimated_cost", float("nan")), ("estimated_cost", float("inf")),
    ("estimated_cost", -1), ("estimated_cost", True), ("estimated_cost", "0.1"),
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


def test_native_provider_receipt_is_accepted_by_extension_and_tampering_is_rejected(tmp_path):
    import json
    import shutil
    import subprocess
    from pathlib import Path
    from tests.test_provider_gateway_streaming import _project, _gateway, _request, FakeStreamAdapter

    root = _project(str(tmp_path))
    state = tmp_path / "state"
    state.mkdir()
    receipt = _gateway(root, state).stream(_request(), FakeStreamAdapter(), lambda event: None)
    source = Path(__file__).resolve().parents[1]
    script = r"""
const assert = require('node:assert/strict');
const { verifiedReceipt } = require('./extension/src/agentHarness/adapters/pxProviderGateway');
const receipt = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const worker = { providerId: 'fixture-local', modelId: 'model-1', costClass: 'local' };
const input = { task: { taskId: 'inv-1' }, executionContext: { execution_id: 'inv-1' } };
assert.equal(verifiedReceipt(receipt, worker, input).charge_microunits, 0);
assert.throws(() => verifiedReceipt({ ...receipt, charge_microunits: 1 }, worker, input), /integrity/);
assert.throws(() => verifiedReceipt(receipt, { ...worker, modelId: 'wrong' }, input), /owner-mismatch/);
"""
    node = shutil.which("node")
    assert node, "Node is required for the mandatory cross-runtime settlement contract"
    result = subprocess.run([node, "-e", script], input=json.dumps(receipt), text=True,
                            capture_output=True, cwd=source, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
