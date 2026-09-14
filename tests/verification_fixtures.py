"""Minimal owned verification project fixtures."""
import json


def fixture(root, count=6):
    (root / "runtime").mkdir()
    (root / "tests").mkdir()
    (root / "registry").mkdir()
    (root / "runtime/shared.py").write_text("VALUE = 1\n", encoding="utf-8")
    members = []
    for index in range(count):
        name = f"tests/test_fixture_{index}.py"
        (root / name).write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        members.append(name)
    policy = {"schema_version": "1.0", "environment": {}, "sections": {"fixture": {
        "source_patterns": ["runtime/shared.py", *members],
        "command": ["python", "-m", "pytest", *members], "cwd": ".",
        "chunk_size": 1, "max_parallel_chunks": 1,
        "chunk_timeout_seconds": 10, "timeout_seconds": 60,
    }}, "certification": {"required_sections": ["fixture"]}}
    (root / "registry/test_profiles.json").write_text(json.dumps(policy), encoding="utf-8")
    return policy
