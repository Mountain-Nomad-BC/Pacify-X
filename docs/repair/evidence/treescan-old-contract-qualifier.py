"""Did the ORIGINAL (pre-replacement) contract accept an identity without qualifier?"""
import glob
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from runtime import semantic_entity as se  # noqa: E402
from runtime.contracts import ContractValidationError, validate_instance  # noqa: E402

originals = glob.glob(".audit-handoff/**/untracked/contracts/semantic/semantic-entity.schema.json", recursive=True)
print("found original:", originals)
if not originals:
    raise SystemExit("no pre-change copy to compare")

stage = Path(tempfile.mkdtemp()) / "contracts" / "semantic"
stage.mkdir(parents=True)
shutil.copy2(originals[0], stage / "semantic-entity.schema.json")

registry = se.EntityRegistry()
registry.register(
    entity_kind="surface",
    identity_basis=se.identity_basis_for("intrinsic_name", "probe-name"),
    declared_by="probe",
)
base = json.loads(registry.snapshot_bytes())["records"][0]
omitted = json.loads(json.dumps(base))
omitted["identity_basis"].pop("qualifier", None)

for name, record in (("with qualifier", base), ("qualifier omitted", omitted)):
    try:
        validate_instance(record, stage / "semantic-entity.schema.json")
        print(f"ORIGINAL {name:<20} ACCEPTED")
    except ContractValidationError:
        print(f"ORIGINAL {name:<20} refused")
