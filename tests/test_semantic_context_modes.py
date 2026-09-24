import pytest
from runtime.semantic_context_profiles import context_names, context_profile
from runtime.semantic_mode_profiles import validate_modes

def test_builtin_contexts_and_mode_conflict():
    assert "local-model" in context_names()
    assert context_profile("read-only-agent").max_risk == "R0"
    with pytest.raises(ValueError): validate_modes(("planning", "editing"))
    assert [m.name for m in validate_modes(("planning", "query-projects"))] == ["planning", "query-projects"]

def test_local_model_profile_is_process_capable_but_not_write_capable():
    profile = context_profile("local-model")
    values = {effect.value for effect in profile.allowed_effects}
    assert "process" in values
    assert "write" not in values
