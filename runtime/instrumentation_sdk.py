"""Versioned producer SDK for canonical operational events."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Callable, Iterator, Mapping

from .operational_visibility import validate_operation_event


SDK_VERSION = "px.instrumentation-sdk/1"
EVENT_VERSION = "px.operation-event/1"
Emitter = Callable[[Mapping[str, object]], object]


def build_operation_event(root: Path, payload: Mapping[str, object]) -> dict[str, object]:
    """Build and validate one event while refusing unknown SDK versions."""
    source = deepcopy(dict(payload))
    sdk_version = source.pop("sdk_version", None)
    if sdk_version != SDK_VERSION:
        raise ValueError(f"unsupported instrumentation SDK version: {sdk_version}")
    source.setdefault("schema_version", EVENT_VERSION)
    validation = validate_operation_event(root, source)
    if not validation["valid"]:
        raise ValueError("invalid operation event: " + "; ".join(validation["errors"]))
    return source


def lifecycle_event(
    root: Path,
    base: Mapping[str, object],
    *,
    lifecycle: str,
    result: str,
) -> dict[str, object]:
    """Create one immutable lifecycle variation from an admitted base payload."""
    payload = deepcopy(dict(base))
    operation = payload.get("operation")
    if not isinstance(operation, dict):
        raise ValueError("operation must be an object")
    operation["lifecycle"] = lifecycle
    operation["result"] = result
    return build_operation_event(root, payload)


@contextmanager
def instrument_operation(
    root: Path, base: Mapping[str, object], emit: Emitter
) -> Iterator[None]:
    """Emit started then completed/failed without capturing exception content."""
    emit(lifecycle_event(root, base, lifecycle="started", result="pending"))
    try:
        yield
    except BaseException:
        emit(lifecycle_event(root, base, lifecycle="failed", result="failure"))
        raise
    else:
        emit(lifecycle_event(root, base, lifecycle="completed", result="success"))

