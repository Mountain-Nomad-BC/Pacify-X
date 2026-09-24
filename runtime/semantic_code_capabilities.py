"""Non-authoritative capability descriptors for later PX registry admission."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SemanticOperationDescriptor:
    operation: str
    effect: str
    risk: str
    requires_unique_symbol: bool = False
    mutation: bool = False


OPERATIONS: tuple[SemanticOperationDescriptor, ...] = (
    SemanticOperationDescriptor("semantic.project.summary", "read", "R0"),
    SemanticOperationDescriptor("semantic.symbol.find", "read", "R0"),
    SemanticOperationDescriptor("semantic.symbol.overview", "read", "R0"),
    SemanticOperationDescriptor("semantic.reference.find", "read", "R0"),
    SemanticOperationDescriptor("semantic.diagnostics.file", "read", "R0"),
    SemanticOperationDescriptor("semantic.edit.plan_replace", "plan", "R1", True),
    SemanticOperationDescriptor("semantic.edit.plan_insert_before", "plan", "R1", True),
    SemanticOperationDescriptor("semantic.edit.plan_insert_after", "plan", "R1", True),
    SemanticOperationDescriptor("semantic.edit.preview", "read", "R1", True),
    SemanticOperationDescriptor("semantic.edit.apply", "write", "R3", True, True),
)


def operation_descriptor(operation: str) -> SemanticOperationDescriptor:
    for item in OPERATIONS:
        if item.operation == operation:
            return item
    raise KeyError(operation)
