from runtime.semantic_capability_projection import project_capabilities
from runtime.semantic_tool_projection import projected_tools

def test_writable_context_still_only_describes_tools():
    tools = projected_tools(project_capabilities("codex-host", ("editing",)))
    write = [t for t in tools if t["mutation"]]
    assert write
    assert all("not execution authority" in t["authority_note"].lower() for t in write)
