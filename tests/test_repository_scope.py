from pathlib import Path

from runtime.repository_scope import (
    is_external_environment_relative,
    is_project_source,
)


def test_local_dependency_installations_are_pruned_at_the_root() -> None:
    assert is_external_environment_relative("Python/pythoncore/Lib/json.py")
    assert is_external_environment_relative(".venv-certify/Lib/site-packages/x.py")
    assert is_external_environment_relative("node_modules/pkg/index.js")
    assert is_external_environment_relative("extension/node_modules/pkg/dist/index.js")
    assert is_external_environment_relative(
        "extension/.vscode-test/vscode-win32/resources/app/out/main.js"
    )
    assert is_external_environment_relative("extension/.venv-build/Lib/site-packages/x.py")
    assert is_external_environment_relative(".git/objects/pack/pack.bin")
    assert is_external_environment_relative(".pacify-x/resource-ledger.json.lock")
    assert is_external_environment_relative(".engineering-bootstrap/quarantine/run/file.bin")
    assert is_external_environment_relative(
        ".engineering-bootstrap/.lock-recovery-receipts/release.lock/receipt.json"
    )
    assert is_external_environment_relative(
        ".engineering-bootstrap/operation-bus/wal/committed/operation/after.json"
    )
    assert is_external_environment_relative(".engineering-bootstrap/project-map/index.json")
    assert is_external_environment_relative(".engineering-bootstrap/coordination/state.json")
    assert is_external_environment_relative(".engineering-bootstrap/runtime-core/state.json")
    assert is_external_environment_relative(
        ".engineering-bootstrap/project-map-history-archives/history.zip"
    )
    assert is_external_environment_relative(".engineering-bootstrap/studios/agents/revision.json")
    assert is_external_environment_relative(
        ".engineering-bootstrap/test-evidence/adversarial-repair-gates/structural.json"
    )
    assert is_external_environment_relative(
        ".engineering-bootstrap/test-evidence/github-reconciliation-gates/registry.json"
    )
    assert is_external_environment_relative("projects/pacify-x/runtime/cli.py")
    assert is_external_environment_relative("projects_tracking/project-registry.json")
    assert is_external_environment_relative("repo_quarantine/prj_demo/receipt.json")
    assert is_external_environment_relative("shared_capabilities/catalog.json")
    assert is_external_environment_relative(".px/preserved-skills/initial/user-original/tool.py")
    assert is_external_environment_relative(
        ".px/global-skill-isolation/journal.json"
    )
    assert is_external_environment_relative(
        ".px/preserved-extension-installations/initial/extension/package.json"
    )
    assert not is_external_environment_relative("runtime/hardware_routing.py")
    assert not is_external_environment_relative(
        ".engineering-bootstrap/test-evidence/sections/testing-governance.json"
    )


def test_project_source_boundary_does_not_hide_similar_nested_names(tmp_path: Path) -> None:
    assert not is_project_source(tmp_path / "Python" / "x.py", tmp_path)
    assert not is_project_source(tmp_path / ".venv-a" / "x.py", tmp_path)
    assert not is_project_source(
        tmp_path / ".pacify-x" / "resource-ledger.json.lock", tmp_path
    )
    assert not is_project_source(tmp_path / ".px" / "preserved-skills" / "x.py", tmp_path)
    assert not is_project_source(tmp_path / "projects" / "demo" / "runtime.py", tmp_path)
    assert not is_project_source(tmp_path / "projects_tracking" / "events" / "1.json", tmp_path)
    assert not is_project_source(
        tmp_path / ".engineering-bootstrap" / "studios" / "agents" / "run.json",
        tmp_path,
    )
    assert is_project_source(tmp_path / "runtime" / "Python" / "x.py", tmp_path)
    assert not is_project_source(tmp_path / "extension" / "node_modules" / "x.js", tmp_path)
