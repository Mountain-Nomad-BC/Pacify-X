"""Resume 9: PX-AUD-008/010 verification on current source.

Builds the native minimal instance for every contract schema and validates it
with the same native validator. This exercises the owner reconciliation for
`maxLength`, `format: uuid`, and generated pattern examples (the three
defect classes named by PX-AUD-008/009/010) across the whole corpus rather
than a hand-picked subset.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import runtime.contracts as C  # noqa: E402

root = Path("contracts")
schemas = sorted(root.rglob("*.schema.json"))
failures = []
for schema in schemas:
    try:
        instance = C.build_minimal_instance(schema)
        C.validate_instance(instance, schema)
    except Exception as error:  # noqa: BLE001 - every failure is evidence
        failures.append((schema.as_posix(), f"{type(error).__name__}: {error}"))
print(f"schemas={len(schemas)} roundtrip_failures={len(failures)}")
for path, detail in failures:
    print(f"FAIL {path} :: {detail}")
sys.exit(1 if failures else 0)
