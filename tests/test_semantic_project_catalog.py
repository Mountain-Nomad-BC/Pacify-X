from pathlib import Path
import pytest
from runtime.semantic_project_catalog import SemanticProjectCatalog

def test_catalog_binds_id_to_one_root(tmp_path: Path):
    one = tmp_path / "one"; two = tmp_path / "two"; one.mkdir(); two.mkdir()
    catalog = SemanticProjectCatalog()
    assert catalog.register("p", one).project_id == "p"
    assert catalog.register("p", one).root == one.resolve().as_posix()
    with pytest.raises(ValueError): catalog.register("p", two)
    with catalog.borrow("p") as d: assert d.root == one.resolve().as_posix()

def test_catalog_rejects_truthy_read_only_and_duplicate_labels(tmp_path: Path):
    root = tmp_path / "strict"; root.mkdir()
    catalog = SemanticProjectCatalog()
    with pytest.raises(TypeError, match="read_only"):
        catalog.register("p", root, read_only="true")
    with pytest.raises(ValueError, match="unique"):
        catalog.register("p", root, labels=("a", "a"))
