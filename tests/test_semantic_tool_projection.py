from runtime.semantic_capability_projection import project_capabilities
from runtime.semantic_tool_projection import projected_tools

def test_tool_projection_warns_exposure_is_not_authority():
    tools = projected_tools(project_capabilities("read-only-agent"))
    assert tools and all("authority" in t["authority_note"].lower() for t in tools)
    assert all(t["mutation"] is False for t in tools)
