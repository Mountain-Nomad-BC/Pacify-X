from pathlib import Path
import shutil

from runtime.release_preflight import audit_clean_boundary
from tests.release_preflight_testkit import minimal_product


def test_identity_input_excluded_from_clean_export_fails_closed(tmp_path: Path) -> None:
    source = minimal_product(tmp_path / "source")
    ignored = source / ".tmp/runtime-state.json"; ignored.parent.mkdir(); ignored.write_text("{}")
    clean = tmp_path / "clean"; shutil.copytree(source, clean); (clean / ".tmp/runtime-state.json").unlink(); (clean / ".tmp").rmdir()
    result = audit_clean_boundary(source, clean, identity_inputs=["runtime/owner.py", ".tmp/runtime-state.json"])
    assert not result["valid"]
    assert result["failures"][0]["code"] == "RP-BND-001"


def test_matching_clean_boundary_passes(tmp_path: Path) -> None:
    source = minimal_product(tmp_path / "source"); clean = tmp_path / "clean"; shutil.copytree(source, clean)
    assert audit_clean_boundary(source, clean, identity_inputs=["runtime/owner.py"])["valid"]
