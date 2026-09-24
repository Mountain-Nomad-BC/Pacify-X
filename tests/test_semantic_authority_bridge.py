from runtime.semantic_authority_bridge import inspect_operation_authority

def test_observation_cannot_authorize_write():
    decision = inspect_operation_authority(executor="codex-host", effects=("workspace-write",), observed_only=True)
    assert decision["allowed"] is False
    assert "observation cannot authorize or claim a non-read effect" in decision["reasons"]
