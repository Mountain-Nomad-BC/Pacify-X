"""File-copy recognizers: qualified copies are writes, collections copies are not.

`MUTATION_NAMES` deliberately omits the bare leaf `copy` because `list.copy`,
`dict.copy` and `array.copy` outnumber file copies. The qualified forms were
meant to arrive as `shutil.copy`, but only the bare leaf survives discovery
(`_call_name` is split on the last dot), and that leaf was missing. Two real
`shutil.copyfile` writes in `scripts/clean_source_export.py` were therefore
absent from the canonical census.
"""
from __future__ import annotations

from pathlib import Path

from runtime.effect_surface import _call_name, discover_effect_surfaces


def _scan(tmp_path: Path, source: str) -> list[dict[str, object]]:
    (tmp_path / "producer.py").write_text(source, encoding="utf-8")
    return discover_effect_surfaces(tmp_path)


def test_qualified_file_copies_are_filesystem_mutations(tmp_path: Path) -> None:
    source = (
        "import shutil\n"
        "shutil.copyfile('a', 'b')\n"
        "shutil.copy('c', 'd')\n"
        "shutil.copy2('e', 'f')\n"
    )
    records = _scan(tmp_path, source)
    assert {record["call"] for record in records} == {
        "shutil.copyfile", "shutil.copy", "shutil.copy2"
    }
    assert all(record["effect"] == "filesystem_mutation" for record in records)
    assert all(not record["destructive"] for record in records)


def test_collection_copies_stay_out_of_the_mutation_census(tmp_path: Path) -> None:
    source = (
        "def act(values):\n"
        "    copy = values.copy()\n"
        "    return copy\n"
        "mapping = {'a': 1}.copy()\n"
    )
    assert _scan(tmp_path, source) == []


def test_shadowed_shutil_name_is_not_proven_a_file_copy(tmp_path: Path) -> None:
    """A shadowed `shutil` receiver is not a proven file operation.

    `_call_name` renders both `shutil.copyfile` (the module) and `shutil.copyfile()` on a
    local object identically, so the census records this as a *candidate* mutation site.
    It is the custody gate, not discovery, that decides whether the destination is
    authorized: discovery stays fail-closed and never drops an unknown receiver.
    """
    source = (
        "import shutil\n"
        "shutil = object()\n"
        "shutil.copyfile()\n"
    )
    records = _scan(tmp_path, source)
    assert [record["call"] for record in records] == ["shutil.copyfile"]


def test_dotted_copy_call_names_are_preserved(tmp_path: Path) -> None:
    """The qualified receiver is what distinguishes a file copy from a collection copy."""
    import ast

    tree = ast.parse("from shutil import copyfile\ncopyfile('a', 'b')\nshutil.copy('a', 'b')\n")
    names = {
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert names == {"copyfile", "shutil.copy"}


def test_shutil_copy_imported_bare_is_still_a_mutation(tmp_path: Path) -> None:
    """`from shutil import copyfile` keeps the bare leaf; `_call_name` is used directly."""
    import ast

    from runtime.effect_surface import _stream_effect_resolver

    tree = ast.parse("copyfile('a', 'b')\n")
    resolver = _stream_effect_resolver(tree)
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    assert _call_name(call) == "copyfile"
    assert resolver(call) is None


def test_owning_producer_records_both_copyfile_writes() -> None:
    root = Path(__file__).resolve().parents[1]
    records = discover_effect_surfaces(root)
    lines = {
        int(record["line"])
        for record in records
        if record["path"] == "scripts/clean_source_export.py" and record["call"] == "shutil.copyfile"
    }
    assert lines == {738, 748}
def test_evidence_tooling_is_outside_the_producer_census(tmp_path: Path) -> None:
    """PX-OS-1067 audit launchers under docs/repair/evidence/ are scaffolding, not producers.

    The exclusion is scoped to that directory. A census launcher inside the scanned tree
    otherwise changes the denominator it measures, so two runs cannot agree.
    """
    evidence = tmp_path / "docs/repair/evidence"
    evidence.mkdir(parents=True)
    (evidence / "run-census.py").write_text(
        "from pathlib import Path\nPath('out.json').write_text('{}')\n",
        encoding="utf-8",
    )
    other = tmp_path / "docs/repair"
    (other / "producer.py").write_text(
        "from pathlib import Path\nPath('out.json').write_text('{}')\n",
        encoding="utf-8",
    )
    paths = {record["path"] for record in discover_effect_surfaces(tmp_path)}
    assert paths == {"docs/repair/producer.py"}
