"""Causal probe: semantic-entity publication durability without its contract.

Reproduces the user-visible failure chain:
  1. publish_registry() writes a registry file and reports PUBLISHED
  2. load_published_registry() then raises FileNotFoundError
  3. the raised path is the *missing contract*, not the project's own file
so a project's registry becomes unreadable by the owner that wrote it.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from runtime import semantic_entity as se  # noqa: E402

print("contract present:", (Path(".") / se.SCHEMA_RELATIVE).is_file())

root = Path(tempfile.mkdtemp())
registry = se.EntityRegistry()
registry.register(
    entity_kind="surface",
    identity_basis=se.identity_basis_for("declared_identifier", "probe.one"),
    declared_by="resume14-probe",
)
receipt = se.publish_registry(registry, root)
target = se.published_registry_path(root)
print("publish status:", receipt["status"], "| file exists:", target.is_file())

try:
    se.load_published_registry(root)
    print("reload: OK")
except Exception as error:  # noqa: BLE001 - the failure is the evidence
    print(f"reload RAISED: {type(error).__name__}: {str(error)[:160]}")
    mentioned = [token for token in ("semantic-entity.schema.json", "entity-registry") if token in str(error)]
    print("raised path names:", mentioned)
