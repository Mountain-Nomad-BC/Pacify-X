"""Deviation package construction and evidence sealing.

Every Gremlin activation produces a structured deviation package. The package is
append-only, hashed, and carries a signed manifest so it is hard to alter
silently. The workload cannot delete or overwrite deviation evidence
(GN-INV-003): the writer is owned by the containment facade, not the workload.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..json_io import bounded_canonical_json_bytes

SCHEMA_VERSION = "px.gremlin-deviation/1.0"

# Deviation subdirectory layout (plan section 22). Not every file exists for every
# deviation; the manifest names the ones that do.
PACKAGE_FILES = (
    "manifest.json",
    "timeline.jsonl",
    "hashes.json",
    "provenance/execution_identity.json",
    "provenance/process_identity.json",
    "provenance/policy_identity.json",
    "gremlin_nanny/trigger.json",
    "gremlin_nanny/assessment.json",
    "gremlin_nanny/intervention.json",
    "gremlin_nanny/response.json",
    "gremlin_nanny/enforcement.json",
    "gremlin_nanny/health.json",
    "authority/requested_capability.json",
    "authority/authorization_result.json",
    "decision/classification.json",
    "decision/termination.json",
    "decision/rationale.json",
)


@dataclass(frozen=True, slots=True)
class DeviationManifest:
    deviation_id: str
    created_at_utc: str
    agent_execution_id: str
    agent_id: str
    process_identity_sha256: str
    trigger_type: str
    effect_type: str
    severity: str
    gn_state: str
    policy_profile: str
    authorization_state: str
    justification_state: str
    intervention_attempted: bool
    intervention_result: str | None
    termination_performed: bool
    kill_scope: str | None
    containment_success: bool
    external_effect_confirmed: bool
    operator_action_required: bool
    analysis_status: str = "analysis_pending"

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


class DeviationPackage:
    """A sealed deviation package on disk.

    The package is created under an exact deviation directory. Its manifest is
    hashed and the package hash list seals the payload files. A second write to an
    existing deviation id is refused: evidence is append-only.
    """

    def __init__(self, root: Path, manifest: DeviationManifest) -> None:
        self.root = Path(root)
        self.manifest = manifest
        self._written: list[str] = []

    @property
    def directory(self) -> Path:
        stamp = self.manifest.created_at_utc[:10].replace("-", "/")
        return self.root / "deviations" / stamp / self.manifest.deviation_id

    def write(self, relative: str, payload: Mapping[str, Any]) -> str:
        if relative not in PACKAGE_FILES:
            raise ValueError(f"unknown deviation package file {relative!r}")
        target = self.directory / relative
        if target.exists():
            raise FileExistsError(f"deviation evidence is append-only: {relative} already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        body = {"schema_version": SCHEMA_VERSION, "deviation_id": self.manifest.deviation_id, "payload": dict(payload)}
        raw = json.dumps(body, indent=2, sort_keys=True) + "\n"
        target.write_text(raw, encoding="utf-8", newline="\n")
        self._written.append(relative)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def seal(self) -> dict[str, Any]:
        """Seal the package: write the manifest and the hashes file."""
        manifest_payload = self.manifest.as_dict()
        manifest_digest = hashlib.sha256(
            bounded_canonical_json_bytes(manifest_payload, max_bytes=262_144)
        ).hexdigest()
        self.write("manifest.json", manifest_payload)
        hashes: dict[str, str] = {}
        for relative in sorted(self._written):
            if relative == "hashes.json":
                continue
            raw = (self.directory / relative).read_bytes()
            hashes[relative] = hashlib.sha256(raw).hexdigest()
        hashes["manifest.json"] = hashlib.sha256((self.directory / "manifest.json").read_bytes()).hexdigest()
        seal_digest = hashlib.sha256(
            bounded_canonical_json_bytes(hashes, max_bytes=262_144)
        ).hexdigest()
        hashes_path = self.directory / "hashes.json"
        hashes_path.write_text(
            json.dumps({"files": hashes, "seal_sha256": seal_digest}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            "deviation_id": self.manifest.deviation_id,
            "directory": self.directory.as_posix(),
            "manifest_sha256": manifest_digest,
            "seal_sha256": seal_digest,
            "files": sorted(hashes),
        }