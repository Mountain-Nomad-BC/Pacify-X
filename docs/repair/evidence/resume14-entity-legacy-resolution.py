"""Reproduce the ORIGINAL failure by hiding the contract for one call.

The pre-fix code resolved the contract from the framework checkout. When the
framework did not ship it (the state this checkout was actually in), publication
succeeded and the following load raised FileNotFoundError. This probe removes the
contract from the resolution path for the duration of one validation to show the
observed failure shape, then confirms the fixed path reports a domain error
instead of leaking a path traceback.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from runtime import semantic_entity as se  # noqa: E402
from runtime.contracts import validate_instance  # noqa: E402

registry = se.EntityRegistry()
registry.register(
    entity_kind="surface",
    identity_basis=se.identity_basis_for("declared_identifier", "probe.one"),
    declared_by="probe",
)
root = Path(tempfile.mkdtemp())
print("publish status:", se.publish_registry(registry, root)["status"])
record = json.loads(registry.snapshot_bytes())["records"][0]

missing = Path(".") / "contracts/semantic/absent.schema.json"
try:
    validate_instance(record, missing)
except FileNotFoundError as error:
    print(f"FORMER BEHAVIOUR: FileNotFoundError escaped to the caller: {type(error).__name__}")

# The fix must convert an absent contract into a domain error, named clearly.
original = se.SCHEMA_RELATIVE
se.SCHEMA_RELATIVE = Path("contracts/semantic/absent.schema.json")
try:
    se.contract_path()
except se.SemanticEntityError as error:
    print(f"FIXED BEHAVIOUR: SemanticEntityError: {error}")
finally:
    se.SCHEMA_RELATIVE = original

print("reload of the published registry:", type(se.load_published_registry(root)).__name__)
