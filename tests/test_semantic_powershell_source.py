from pathlib import Path

import pytest

from runtime import semantic_powershell_source as parser
from runtime.resource_lifecycle import ResourceManager


@pytest.fixture
def native_parser():
    if parser.discover_parser() is None:
        pytest.skip("Native PowerShell unavailable; not verified on this host")


def assert_custody_closed(root):
    records = ResourceManager(root / ".agentic_engineering_os_px/resource-lifecycle/ledger.json").ledger.load()
    assert records
    assert all(not r.active and r.status == "reclaimed" for r in records)
    assert not list((root / ".agentic_engineering_os_px/test-evidence/source-observation").iterdir())


def test_native_source_image_and_utf16_geometry(tmp_path, native_parser):
    import hashlib
    prefix = "$text = '😀'\n"
    source = prefix + "function Actual {}\n"
    report = parser.parse_powershell_source(tmp_path, source)
    assert report["source_sha256"] == hashlib.sha256(source.encode("utf-8")).hexdigest()
    symbol, = report["symbols"]
    assert symbol["name"] == "Actual" and symbol["line"] == 2
    assert symbol["start_offset"] == len(prefix.encode("utf-16-le")) // 2
    assert len(report["parser_executable_sha256"]) == 64
    assert report["parser_version"]
    assert_custody_closed(tmp_path)


def test_native_syntax_failure_closes_custody(tmp_path, native_parser):
    with pytest.raises(parser.PowerShellSyntaxError):
        parser.parse_powershell_source(tmp_path, "function Good {}\nfunction Broken {")
    assert_custody_closed(tmp_path)


def test_native_declaration_budget_rejects_whole_image(tmp_path, native_parser):
    source = "\n".join(f"function F{i} {{}}" for i in range(parser.MAX_SYMBOLS + 1))
    with pytest.raises(parser.PowerShellBudgetError):
        parser.parse_powershell_source(tmp_path, source)
    assert_custody_closed(tmp_path)


def test_name_budget_is_not_silent_truncation(tmp_path, native_parser):
    with pytest.raises(parser.PowerShellBudgetError):
        parser.parse_powershell_source(tmp_path, "function " + "F" * (parser.MAX_NAME_CHARS + 1) + " {}")
    assert_custody_closed(tmp_path)


def test_byte_budget_precedes_process_creation(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError("must not discover or spawn a parser")
    monkeypatch.setattr(parser, "discover_parser", forbidden)
    with pytest.raises(parser.PowerShellBudgetError):
        parser.parse_powershell_source(tmp_path, " " * (parser.MAX_SOURCE_BYTES + 1))
    assert not (tmp_path / ".agentic_engineering_os_px").exists()


def test_missing_native_parser_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(parser, "discover_parser", lambda: None)
    with pytest.raises(parser.PowerShellUnavailable):
        parser.parse_powershell_source(tmp_path, "function Actual {}")
    assert not (tmp_path / ".agentic_engineering_os_px").exists()


def test_actual_native_timeout_closes_process_and_workspace(tmp_path, native_parser):
    with pytest.raises(parser.PowerShellBudgetError, match="duration"):
        parser.parse_powershell_source(tmp_path, "function Actual {}", timeout_seconds=0.001)
    assert_custody_closed(tmp_path)


def test_owned_input_path_is_literal_even_with_shell_characters(tmp_path, native_parser):
    root = tmp_path / "__MAX_SYMBOLS__ quote' $() workspace"
    root.mkdir()
    report = parser.parse_powershell_source(root, "function Literal {}")
    assert report["symbols"][0]["name"] == "Literal"
    assert_custody_closed(root)


def test_uncertain_process_custody_retains_image_for_recovery(tmp_path, native_parser, monkeypatch):
    from dataclasses import replace
    actual_terminate = ResourceManager.terminate_owned_process
    terminated = []

    def uncertain_receipt(manager, resource_id, **options):
        # Reap the actual child, then inject uncertainty in the reported outcome.
        receipt = actual_terminate(manager, resource_id, **options)
        assert not receipt.errors
        terminated.append(receipt)
        return replace(receipt, errors=("injected custody uncertainty",))

    monkeypatch.setattr(ResourceManager, "terminate_owned_process", uncertain_receipt)
    manager = ResourceManager(tmp_path / ".agentic_engineering_os_px/resource-lifecycle/ledger.json")
    source = "function Actual {}"
    try:
        with pytest.raises(parser.PowerShellSourceError, match="custody"):
            parser.parse_powershell_source(tmp_path, source, timeout_seconds=0.001)
        workspace, = [r for r in manager.ledger.load() if r.resource_type == "path"]
        assert not workspace.active and workspace.status == "retained"
        assert workspace.run_state == "recoverable"
        assert (Path(workspace.path) / "source.txt").read_text(encoding="utf-8") == source
    finally:
        # The real termination receipt proves this test's child tree closed.
        if terminated:
            for workspace in [r for r in manager.ledger.load() if r.resource_type == "path"]:
                manager.update(workspace.resource_id, retained_reason=None)
                manager.reclaim_ephemeral_path(workspace.resource_id, reason="Injected uncertainty fixture ended")


@pytest.mark.parametrize("timeout", [True, 0, -1, float("nan"), float("inf"), 31])
def test_timeout_must_be_bounded_before_process_creation(tmp_path, timeout):
    with pytest.raises(ValueError):
        parser.parse_powershell_source(tmp_path, "", timeout_seconds=timeout)
    assert not (tmp_path / ".agentic_engineering_os_px").exists()
