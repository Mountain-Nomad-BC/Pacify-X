from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).parents[1]


def test_runtime_package_init_blocks_startup_bytecode(tmp_path: Path) -> None:
    package = tmp_path / "probe_package"
    package.mkdir()
    shutil.copy2(ROOT / "runtime/__init__.py", package / "__init__.py")
    environment = dict(os.environ)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment.pop("PYTHONPYCACHEPREFIX", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import probe_package; assert __import__('sys').dont_write_bytecode",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    bytecode = list((package / "__pycache__").glob("*.pyc"))
    assert len(bytecode) <= 1
    assert all(path.name.startswith("__init__.") for path in bytecode)


def test_each_audit_route_previews_recoverable_hygiene_before_inspection() -> None:
    source = (ROOT / "runtime/cli.py").read_text(encoding="utf-8")
    audit_branch = source.split('elif args.command == "audit":', 1)[1].split(
        'elif args.command == "gates":', 1
    )[0]
    assert audit_branch.index("_prepare_certification_hygiene(") < audit_branch.index(
        "audit_structural_integrity(root)"
    )
    assert audit_branch.index("_prepare_certification_hygiene(") < audit_branch.index(
        "audit_framework("
    )
    assert "apply=args.apply_hygiene" in audit_branch
