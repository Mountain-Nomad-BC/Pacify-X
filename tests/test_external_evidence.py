import json
from pathlib import Path
import shutil

from runtime.external_evidence import validate_external_evidence


ROOT = Path(__file__).resolve().parents[1]


def copy_external_evidence_fixture(product: Path) -> None:
    bundle = "archive-custody-20260803"
    (product / "evidence/bundles").mkdir(parents=True)
    shutil.copytree(
        ROOT / "evidence/bundles" / bundle,
        product / "evidence/bundles" / bundle,
    )
    shutil.copy2(
        ROOT / "evidence/externalized-payload-index.json",
        product / "evidence/externalized-payload-index.json",
    )
    shutil.copytree(ROOT / "contracts", product / "contracts")


def test_strict_external_evidence_is_portable_inside_product():
    result = validate_external_evidence(ROOT, strict=True)
    assert result["valid"], result["errors"]
    assert result["verified"] == result["references"] == 1


def test_traversal_and_wrong_bundle_hash_fail_closed(tmp_path):
    product = tmp_path / "product"
    copy_external_evidence_fixture(product)
    index_path = product / "evidence/externalized-payload-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["records"][0]["manifest"] = "../outside.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    assert not validate_external_evidence(product, strict=True)["valid"]


def test_strict_verification_does_not_need_parent_temp_directory(tmp_path):
    product = tmp_path / "portable"
    copy_external_evidence_fixture(product)
    assert validate_external_evidence(product, strict=True)["valid"]
