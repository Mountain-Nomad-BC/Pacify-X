import pytest

from runtime.semantic_lsp_health import RestartPolicy, ServerHealth, ServerQuarantinedError
from runtime.semantic_lsp_types import ServerState


def test_consecutive_failures_quarantine_server():
    health = ServerHealth("x", RestartPolicy(consecutive_failure_limit=2))
    health.mark_failure("one")
    health.mark_failure("two")
    assert health.snapshot().state == ServerState.QUARANTINED
    with pytest.raises(ServerQuarantinedError):
        health.mark_starting()


def test_restart_budget_is_bounded():
    health = ServerHealth("x", RestartPolicy(max_restarts=1, window_seconds=100))
    health.mark_starting(); health.mark_running(); health.mark_stopped()
    health.mark_starting(); health.mark_running(); health.mark_stopped()
    with pytest.raises(ServerQuarantinedError):
        health.mark_starting()
