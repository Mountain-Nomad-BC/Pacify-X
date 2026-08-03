from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

from runtime.effect_surface import validate_effect_surfaces


ROOT = Path(__file__).parents[1]


def test_every_executable_effect_surface_is_owned_and_bounded() -> None:
    result = validate_effect_surfaces(ROOT)
    assert result["valid"], result["errors"]
    assert result["counts"]["process"] >= 6
    assert result["counts"]["filesystem_mutation"] > 0


def test_new_shell_execution_fails_closed() -> None:
    root = Path(tempfile.mkdtemp()) / "framework"
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    target = root / "runtime/unsafe_effect.py"
    target.write_text("import subprocess\nsubprocess.run('echo unsafe', shell=True, timeout=1)\n", encoding="utf-8")
    result = validate_effect_surfaces(root)
    assert not result["valid"]
    assert any("unsafe shell" in item for item in result["errors"])


def test_registry_cannot_claim_removed_effect_surface() -> None:
    root = Path(tempfile.mkdtemp()) / "framework"
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    path = root / "registry/effect_surface_ownership.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    registry["records"] = registry["records"][1:]
    path.write_text(json.dumps(registry), encoding="utf-8")
    assert not validate_effect_surfaces(root)["valid"]


def test_popen_without_bounded_communication_fails_closed() -> None:
    root = Path(tempfile.mkdtemp()) / "framework"
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    target = root / "runtime/unbounded_process.py"
    target.write_text(
        "import subprocess\nprocess = subprocess.Popen(['tool'])\nprocess.communicate()\n",
        encoding="utf-8",
    )
    result = validate_effect_surfaces(root)
    assert not result["valid"]
    assert any("process call lacks timeout" in item for item in result["errors"])
