"""Who actually produces/consumes the 7 contracts with no adjudication owner?

Search runtime/ for schema-id and filename references so 'no owner recorded' is
distinguished from 'no implementation'.
"""
import json
import re
from pathlib import Path

CONTRACTS = [
    "contracts/models/generation-bound-verdict.schema.json",
    "contracts/models/member-execution-input.schema.json",
    "contracts/models/model-branch-artifact.schema.json",
    "contracts/models/model-execution-group.schema.json",
    "contracts/models/model-group-preparation.schema.json",
    "contracts/operations/remote-provider-profile.schema.json",
    "contracts/remote_model_attachment.schema.json",
]
runtime_sources = {p: p.read_text(encoding="utf-8", errors="ignore") for p in Path("runtime").rglob("*.py")}

for rel in CONTRACTS:
    doc = json.loads(Path(rel).read_text(encoding="utf-8"))
    schema_id = doc.get("$id", "")
    stem = Path(rel).name.replace(".schema.json", "")
    title = doc.get("title", "")
    hits = []
    for path, text in runtime_sources.items():
        if schema_id and schema_id in text:
            hits.append((path.as_posix(), "id"))
        elif stem in text:
            hits.append((path.as_posix(), "filename"))
    print(f"{rel}")
    print(f"  title={title!r}")
    print(f"  id_referenced_by={[h for h in hits if h[1] == 'id'] or 'NONE'}")
    print(f"  name_referenced_by={[h[0] for h in hits if h[1] == 'filename'] or 'NONE'}")
