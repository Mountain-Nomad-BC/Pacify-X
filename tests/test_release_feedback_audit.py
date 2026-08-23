from pathlib import Path

from runtime.release_preflight import feedback_audit
from tests.release_preflight_testkit import minimal_product


def test_certificate_observer_cannot_write_product_input(tmp_path: Path) -> None:
    root = minimal_product(tmp_path)
    result = feedback_audit(root, ["runtime/owner.py"])
    assert not result["valid"]
    assert result["failures"][0]["code"] == "RP-FBK-001"


def test_external_runtime_completion_is_downstream(tmp_path: Path) -> None:
    root = minimal_product(tmp_path)
    assert feedback_audit(root, [".engineering-bootstrap/runtime-core/completion_status.json"])["valid"]
