from runtime.semantic_capability_projection import project_capabilities


def test_projection_is_deterministic_and_mode_bounded():
    a = project_capabilities("chatgpt", ("planning", "query-projects"))
    b = project_capabilities("chatgpt", ("query-projects", "planning"))
    assert a.projection_sha256 == b.projection_sha256
    assert "semantic.symbol.find" in a.operations
    assert "semantic.edit.apply" not in a.operations
    assert "lsp.rename" not in a.operations


def test_local_model_never_exposes_writes():
    projection = project_capabilities("local-model", ("planning",))
    assert not any(
        name in projection.operations
        for name in (
            "semantic.edit.apply",
            "lsp.rename",
            "semantic.memory.apply_relocation",
        )
    )


def test_local_model_can_use_px_owned_read_process_tools_without_write_exposure():
    projection = project_capabilities("local-model", ("planning", "query-projects"))
    assert "lsp.definition" in projection.operations
    assert "lsp.references" in projection.operations
    assert "lsp.rename" not in projection.operations
    assert "semantic.edit.apply" not in projection.operations


def test_wave4_read_and_plan_operations_project_when_modules_are_installed():
    cross_project = project_capabilities("local-model", ("planning", "query-projects"))
    assert "semantic.knowledge.fuse" in cross_project.operations
    assert "semantic.model.context" in cross_project.operations
    assert "semantic.memory.integrity" in cross_project.operations
    # Composing query-projects intentionally intersects away PLAN, so cross-project
    # mode cannot expose relocation planning.  The single-project planning profile can.
    planning = project_capabilities("local-model", ("planning",))
    assert "semantic.memory.plan_relocation" in planning.operations
    assert "semantic.memory.apply_relocation" not in planning.operations
