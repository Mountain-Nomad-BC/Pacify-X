import importlib.util
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents/skills/govern-operating-kernel/scripts/authoritative_skill_compiler.py"
SPEC = importlib.util.spec_from_file_location("authoritative_skill_compiler", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def run_compiler(tmp_path, text):
    contract = tmp_path / "contract.yaml"
    contract.write_text(text, encoding="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT), str(contract), "--out", str(tmp_path / "out")], text=True, capture_output=True)


def test_nested_permissions_are_preserved_and_schema_validated(tmp_path):
    result = run_compiler(tmp_path, """id: fixture-skill
name: Fixture Skill
summary: Bounded fixture
version: 1.0.0
security_class: high
permissions:
  filesystem_read:
    - workspace/**
  filesystem_write: []
  network: []
  process:
    - python
""")
    assert result.returncode == 0, result.stdout + result.stderr
    import json
    permissions = json.loads((tmp_path / "out/permission_manifest.json").read_text(encoding="utf-8"))
    assert permissions == {"filesystem_read": ["workspace/**"], "filesystem_write": [], "network": [], "process": ["python"]}


def test_malformed_duplicate_alias_tag_and_unknown_field_fail_closed(tmp_path):
    cases = [
        "id: a\nid: b\nname: A\nsummary: A\nversion: 1.0.0\n",
        "id: a\nname: A\nsummary: *alias\nversion: 1.0.0\n",
        "id: a\nname: A\nsummary: !python bad\nversion: 1.0.0\n",
        "id: a\n name: bad-indent\nsummary: A\nversion: 1.0.0\n",
        "id: a\nname: A\nsummary: A\nversion: 1.0.0\nunknown: value\n",
    ]
    for index, text in enumerate(cases):
        case = tmp_path / str(index)
        case.mkdir()
        result = run_compiler(case, text)
        assert result.returncode == 2, (index, result.stdout, result.stderr)
        assert not (case / "out").exists()


def test_alias_expansion_and_depth_are_bounded(tmp_path):
    deep = "id: a\nname: A\nsummary: A\nversion: 1.0.0\npermissions:\n" + "  " * 14 + "network: []\n"
    result = run_compiler(tmp_path, deep)
    assert result.returncode == 2
