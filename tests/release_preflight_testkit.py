from __future__ import annotations

import json
from pathlib import Path


def minimal_product(root: Path) -> Path:
    (root / "policies").mkdir(parents=True)
    (root / "runtime").mkdir()
    (root / "policies/release-artifact-policy.json").write_text(
        json.dumps(
            {
                "policy_version": "test",
                "product_roots": ["runtime", "policies", "registry"],
                "product_root_files": [],
                "evidence_roots": ["evidence"],
                "audit_roots": [],
                "audit_root_files": [],
                "audit_allowed_suffixes": [".json"],
                "intermediate_names": ["__pycache__", "build", "dist"],
                "intermediate_name_suffixes": [".egg-info"],
                "intermediate_suffixes": [".pyc", ".tmp"],
                "control_output_paths": [],
                "evidence_allowed_suffixes": [".json", ".txt", ".xml"],
            }
        ),
        encoding="utf-8",
    )
    (root / "runtime/owner.py").write_text("value = 1\n", encoding="utf-8")
    return root
