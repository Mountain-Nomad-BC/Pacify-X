from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def test_minimal_demo_runs_end_to_end_and_retains_evidence() -> None:
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "demo"
        process = subprocess.run(
            [sys.executable, "examples/quickstart/demo.py", "--output", str(output)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=90,
        )
        assert process.returncode == 0, process.stdout + process.stderr
        receipt = json.loads(
            (output / "evidence/demo-receipt.json").read_text(encoding="utf-8")
        )
        assert receipt["valid"]
        assert receipt["steps"]["initialization_preview"]["applied"] is False
        assert receipt["steps"]["initialization"]["applied"] is True
        assert len(receipt["steps"]["selection"]["capability_ids"]) <= 3
        assert len(receipt["steps"]["hydration"]["active_ids"]) == 1
        assert receipt["steps"]["bounded_dry_run"]["applied"] is False
        assert receipt["steps"]["verification"]["valid"]
