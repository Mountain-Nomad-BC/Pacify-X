from pathlib import Path
import shutil

from runtime.repository_scope import (
    is_external_environment_relative,
    is_project_source,
)
from tests.repository_copy import canonical_copy_ignore


def test_local_dependency_installations_are_pruned_at_the_root() -> None:
    assert is_external_environment_relative("Python/pythoncore/Lib/json.py")
    assert is_external_environment_relative(".venv-certify/Lib/site-packages/x.py")
    assert is_external_environment_relative("node_modules/pkg/index.js")
    assert is_external_environment_relative("extension/node_modules/pkg/dist/index.js")
    assert is_external_environment_relative("extension/dist/pacify-x.vsix")
    assert is_external_environment_relative("extension/build/generated.js")
    assert is_external_environment_relative("extension/evidence/screenshots/view.png")
    assert is_external_environment_relative("runtime/__pycache__/owner.pyc")
    assert is_external_environment_relative("extension/.pytest_cache/state.json")
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
    assert not is_external_environment_relative("runtime/evidence_builder.py")
    assert not is_external_environment_relative("runtime/builders/owner.py")
    assert not is_external_environment_relative("runtime/distribution.py")


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
    assert not is_project_source(tmp_path / "extension" / "dist" / "package.vsix", tmp_path)
    assert not is_project_source(tmp_path / "extension" / "build" / "generated.js", tmp_path)
    assert not is_project_source(tmp_path / "extension" / "evidence" / "view.png", tmp_path)


def test_canonical_fixture_copy_prunes_local_gates_but_retains_current_receipts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    local_gate = (
        source
        / ".engineering-bootstrap/test-evidence/adversarial-repair-gates/gate.json"
    )
    current_receipt = (
        source / ".engineering-bootstrap/test-evidence/sections/dashboard.json"
    )
    for path in (local_gate, current_receipt):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    shutil.copytree(source, destination, ignore=canonical_copy_ignore(source))

    assert not (
        destination
        / ".engineering-bootstrap/test-evidence/adversarial-repair-gates"
    ).exists()
    assert (
        destination / ".engineering-bootstrap/test-evidence/sections/dashboard.json"
    ).is_file()
