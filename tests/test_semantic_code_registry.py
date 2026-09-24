from __future__ import annotations

import pytest

from runtime.semantic_code_backend import NullSemanticBackend
from runtime.semantic_code_registry import BackendRegistrationError, SemanticBackendRegistry


class OtherPython(NullSemanticBackend):
    key = "other-python"
    language = "python"
    suffixes = (".py",)


def test_registry_resolves_builtin_python():
    registry = SemanticBackendRegistry()
    assert registry.for_path("a.py").key == "python-ast"
    assert registry.for_path("README.md") is None


def test_registry_rejects_suffix_collision_without_explicit_replace():
    registry = SemanticBackendRegistry()
    with pytest.raises(BackendRegistrationError):
        registry.register(OtherPython())
