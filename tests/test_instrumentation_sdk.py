from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from runtime.instrumentation_sdk import build_operation_event, instrument_operation


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"
FIXTURE = ROOT / "tests/fixtures/operation-event-input.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_python_and_node_build_identical_contract_event() -> None:
    node = shutil.which("node")
    assert node is not None, "Node is a required O02 contract-test prerequisite"
    expected = build_operation_event(ROOT, _fixture())
    script = (
        "const fs=require('fs');"
        "const sdk=require(process.argv[1]);"
        "const value=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
        "process.stdout.write(JSON.stringify(sdk.buildOperationEvent(value)));"
    )
    completed = subprocess.run(
        [node, "-e", script, str(EXTENSION / "src/instrumentationSdk.js"), str(FIXTURE)],
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    assert json.loads(completed.stdout) == expected


def test_unknown_sdk_version_is_refused() -> None:
    fixture = _fixture()
    fixture["sdk_version"] = "px.instrumentation-sdk/999"
    with pytest.raises(ValueError, match="unsupported"):
        build_operation_event(ROOT, fixture)


def test_context_emits_started_and_completed_or_failed_without_error_content() -> None:
    events: list[dict[str, object]] = []
    with instrument_operation(ROOT, _fixture(), lambda event: events.append(dict(event))):
        pass
    assert [(event["operation"]["lifecycle"], event["operation"]["result"]) for event in events] == [("started", "pending"), ("completed", "success")]
    events.clear()
    with pytest.raises(RuntimeError, match="secret detail"):
        with instrument_operation(ROOT, _fixture(), lambda event: events.append(dict(event))):
            raise RuntimeError("secret detail")
    assert [(event["operation"]["lifecycle"], event["operation"]["result"]) for event in events] == [("started", "pending"), ("failed", "failure")]
    assert "secret detail" not in json.dumps(events)
