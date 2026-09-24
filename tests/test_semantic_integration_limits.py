import pytest
from runtime.semantic_integration_limits import SemanticIntegrationLimits

def test_limits_validate_positive_and_relations():
    assert SemanticIntegrationLimits().max_results == 50
    with pytest.raises(ValueError): SemanticIntegrationLimits(max_projects=0)
    with pytest.raises(ValueError): SemanticIntegrationLimits(max_results=10, max_sources=5)
