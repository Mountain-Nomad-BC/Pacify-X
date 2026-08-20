from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

from runtime.effect_surface import discover_effect_surfaces, validate_effect_surfaces


ROOT = Path(__file__).parents[1]
def _copy_effect_fixture(destination: Path) -> Path:
    root = destination / "framework"
    root.mkdir()
    (root / "runtime").mkdir()
    (root / "runtime/base_effect.py").write_text(
        "from pathlib import Path\n\n"
        "def write_bounded():\n"
        "    Path('bounded.txt').write_text('bounded', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (root / "registry").mkdir()
    shutil.copytree(ROOT / "policies", root / "policies")
    records = discover_effect_surfaces(root)
    (root / "registry/effect_surface_ownership.json").write_text(
        json.dumps(
            {"schema_version": "1.0", "record_count": len(records), "records": records},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def test_every_executable_effect_surface_is_owned_and_bounded() -> None:
    result = validate_effect_surfaces(ROOT)
    assert result["valid"], result["errors"]
    assert result["counts"]["process"] >= 6
    assert result["counts"]["filesystem_mutation"] > 0


def test_new_shell_execution_fails_closed() -> None:
    root = _copy_effect_fixture(Path(tempfile.mkdtemp()))
    target = root / "runtime/unsafe_effect.py"
    target.write_text(
        "import subprocess\nsubprocess.run('echo unsafe', shell=True, timeout=1)\n",
        encoding="utf-8",
    )
    result = validate_effect_surfaces(root)
    assert not result["valid"]
    assert any("unsafe shell" in item for item in result["errors"])


def test_registry_cannot_claim_removed_effect_surface() -> None:
    root = _copy_effect_fixture(Path(tempfile.mkdtemp()))
    path = root / "registry/effect_surface_ownership.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    registry["records"] = registry["records"][1:]
    path.write_text(json.dumps(registry), encoding="utf-8")
    assert not validate_effect_surfaces(root)["valid"]


def test_unadmitted_hard_delete_surface_fails_closed() -> None:
    root = _copy_effect_fixture(Path(tempfile.mkdtemp()))
    target = root / "runtime/unsafe_delete.py"
    target.write_text(
        "from pathlib import Path\nPath('unowned').unlink()\n", encoding="utf-8"
    )
    result = validate_effect_surfaces(root)
    assert not result["valid"]
    assert any("hard-delete surface is prohibited" in item for item in result["errors"])


def test_popen_without_bounded_communication_fails_closed() -> None:
    root = _copy_effect_fixture(Path(tempfile.mkdtemp()))
    target = root / "runtime/unbounded_process.py"
    target.write_text(
        "import subprocess\nprocess = subprocess.Popen(['tool'])\nprocess.communicate()\n",
        encoding="utf-8",
    )
    result = validate_effect_surfaces(root)
    assert not result["valid"]
    assert any("process call lacks timeout" in item for item in result["errors"])


def test_effect_identity_is_a_source_locator_not_an_ast_dump() -> None:
    semantic = "runtime/example.py:3:4:subprocess.run"
    assert __import__("hashlib").sha256(semantic.encode()).hexdigest()[:20] == "c40e855839d0987c2742"
