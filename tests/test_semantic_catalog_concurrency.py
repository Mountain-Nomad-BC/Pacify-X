from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from runtime.semantic_project_catalog import SemanticProjectCatalog

def test_project_borrow_is_stable_under_concurrency(tmp_path: Path):
    root = tmp_path / "p"; root.mkdir()
    catalog = SemanticProjectCatalog(); catalog.register("p", root)
    def borrow(_):
        with catalog.borrow("p") as d: return d.root
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(borrow, range(20)))
    assert set(values) == {root.resolve().as_posix()}
