"""Build the closed-world registry/workflow ownership and reachability inventory."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from .repository_scope import is_external_environment_relative


def _sha(path: Path) -> str:
    return hashlib.sha256(_artifact_image(path, _MAX_IMAGE_BYTES)).hexdigest()


def _load(path: Path) -> dict:
    from .json_io import decode_json_object

    return decode_json_object(_artifact_image(path, _MAX_CONTROL_BYTES), max_bytes=_MAX_CONTROL_BYTES, max_depth=32, max_nodes=100000)



_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_CONTROL_BYTES = 1024 * 1024
_MAX_SELECTED_BYTES = 256 * 1024 * 1024
_STATIC_CYCLE_NAMES = frozenset({
    "artifact_reachability.json", "test_group_index.json", "current_evidence_index.json",
    "completion_status.json", "px_world_state.json", "operational_gap_ledger.head.json",
    "operational_gap_ledger.snapshot.json", "engine_identity.json",
})
_CONTROLS = ("registry/workflow_execution_bindings.json", "registry/project_stream_handlers.json")


def _excluded(relative: str) -> bool:
    return is_external_environment_relative(relative) or any(
        part.casefold() in {"quarantine", ".quarantine", "_quarantine", "repo_quarantine"}
        for part in relative.split("/")
    )


def _selected(relative: str) -> bool:
    path = Path(relative)
    if relative.startswith("registry/") and path.name not in _STATIC_CYCLE_NAMES and path.suffix.casefold() in {".json", ".toml", ".yaml", ".yml"}:
        return True
    return relative.startswith("providers/agency_agents/") or path.match("*.yaml") or path.match("*.yml")


def _artifact_image(path: Path, limit: int) -> bytes:
    from .input_files import cooperative_deadline, independent_file, read_file_image

    deadline = cooperative_deadline()
    original, info = independent_file(path)
    return bytes(read_file_image(original, info, limit=limit, deadline=deadline))


class _ReachabilityCorpus:
    """One bounded metadata pass, two retained control images, one digest per file."""

    def __init__(self, root: Path):
        import unicodedata
        from .bounded_walk import WalkLimits, bounded_walk
        from .input_files import check_deadline, contained_file, cooperative_deadline, directory_root, relative_source_path

        self.deadline = cooperative_deadline()
        self.root = directory_root(root)
        if self.root == Path(self.root.anchor):
            raise ValueError("reachability requires an explicit project root")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("reachability metadata deadline expired")
        walked = bounded_walk(self.root, limits=WalkLimits(
            max_files=30000, max_directories=30000, max_entries=60000,
            max_depth=80, max_bytes=2 * 1024 * 1024 * 1024,
            max_duration_seconds=remaining,
        ), exclude=_excluded)
        self.sources = {}
        self.digests = {}
        self.controls = {}
        aliases = set()
        used = 0
        for entry in walked.entries:
            check_deadline(self.deadline)
            relative_source_path(entry.relative)
            alias = unicodedata.normalize("NFC", entry.relative).casefold()
            if alias in aliases:
                raise ValueError("ambiguous reachability path identity")
            aliases.add(alias)
            if entry.kind != "file" or not _selected(entry.relative):
                continue
            path, info = contained_file(self.root, entry.relative)
            limit = _MAX_CONTROL_BYTES if entry.relative in _CONTROLS else _MAX_IMAGE_BYTES
            if info.st_size != entry.size or info.st_size > limit:
                raise ValueError("reachability source changed or exceeded image budget before acquisition")
            used += info.st_size
            if used > _MAX_SELECTED_BYTES:
                raise ValueError("reachability selected corpus exceeds aggregate byte budget")
            self.sources[entry.relative] = (path, info)
        if not all(relative in self.sources for relative in _CONTROLS):
            raise ValueError("reachability control documents are missing")
        check_deadline(self.deadline)
        for relative in _CONTROLS:
            self.controls[relative] = self._image(relative)
        self.registry_paths = tuple(path for relative, (path, _) in self.sources.items()
                                    if relative.startswith("registry/"))
        self.workflow_paths = tuple(path for relative, (path, _) in self.sources.items()
                                    if relative.startswith("orchestration/workflows/") and path.match("*.yaml"))
        self.provider_paths = tuple(path for relative, (path, _) in self.sources.items()
                                    if relative.startswith("providers/agency_agents/"))
        self.yaml_paths = tuple(path for path, _ in self.sources.values()
                               if path.match("*.yaml") or path.match("*.yml"))

    def _image(self, relative: str) -> bytes:
        from .input_files import read_file_image

        path, info = self.sources[relative]
        limit = _MAX_CONTROL_BYTES if relative in _CONTROLS else _MAX_IMAGE_BYTES
        return bytes(read_file_image(path, info, limit=limit, deadline=self.deadline))

    def load(self, relative: str) -> dict:
        from .json_io import decode_json_object
        from .input_files import check_deadline

        value = decode_json_object(self.controls[relative], max_bytes=_MAX_CONTROL_BYTES, max_depth=32, max_nodes=100000)
        if value.get("schema_version") != "1.0":
            raise ValueError("reachability control schema version is unsupported")
        check_deadline(self.deadline)
        return value

    def sha(self, path: Path) -> str:
        from .input_files import check_deadline

        check_deadline(self.deadline)
        relative = path.relative_to(self.root).as_posix()
        if relative not in self.digests:
            raw = self.controls.get(relative)
            if raw is None:
                raw = self._image(relative)
            self.digests[relative] = hashlib.sha256(raw).hexdigest()
        return self.digests[relative]


def _binding_records(document: dict) -> dict:
    from .archive_io import member_identity
    from .numeric_inputs import bounded_text
    from .workflow_inputs import require_declared_count, unique_declarations

    records = unique_declarations(document.get("bindings"), "path", path_keys=True, minimum=0)
    if len({member_identity(path, allow_directory=False) for path in records}) != len(records):
        raise ValueError("ambiguous workflow binding path identity")
    require_declared_count(document, "count", len(records))
    for relative, item in records.items():
        if not relative.startswith("orchestration/workflows/") or not relative.endswith(".yaml"):
            raise ValueError("reachability workflow binding path is invalid")
        value = bounded_text(item.get("entrypoint"), "workflow entrypoint", maximum=256, strip=False)
        if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", value, re.ASCII) is None:
            raise ValueError("reachability workflow entrypoint is invalid")
        if type(item.get("mode")) is not str or item["mode"] not in {"executable_runtime", "executable_validator"}:
            raise ValueError("reachability workflow binding mode is invalid")
    return records


def _project_binding_records(document: dict) -> dict:
    from .numeric_inputs import bounded_text
    from .workflow_inputs import require_declared_count, unique_declarations

    records = unique_declarations(document.get("workflows"), "orchestration_id", minimum=0)
    for item in records.values():
        value = bounded_text(item.get("handler"), "project-stream handler", maximum=256, strip=False)
        if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", value, re.ASCII) is None:
            raise ValueError("reachability project-stream handler is invalid")
        if type(item.get("status")) is not str or item["status"] not in {"executable", "plan_only"}:
            raise ValueError("reachability project-stream status is invalid")
    require_declared_count(document, "executable_count", sum(item["status"] == "executable" for item in records.values()))
    require_declared_count(document, "plan_only_count", sum(item["status"] == "plan_only" for item in records.values()))
    return records


def build_artifact_reachability(root: Path) -> dict:
    from .input_files import check_deadline

    corpus = _ReachabilityCorpus(root)
    root = corpus.root
    binding_doc = corpus.load("registry/workflow_execution_bindings.json")
    bindings = _binding_records(binding_doc)
    project_stream = corpus.load("registry/project_stream_handlers.json")
    project_bindings = _project_binding_records(project_stream)
    records = []
    recorded_paths: set[str] = set()

    def record(value: dict) -> None:
        path = str(value["path"])
        if is_external_environment_relative(path):
            return
        if path in recorded_paths:
            raise ValueError(f"duplicate artifact reachability record: {path}")
        recorded_paths.add(path)
        records.append(value)

    registry_owners = {
        "artifact_reachability.json": "runtime/artifact_reachability.py",
        "contract_ownership.json": "runtime/contracts.py",
        "corrective_release_ledger.json": "runtime/corrective_release.py",
        "declared_suite_authoritative_tools.json": "runtime/exact_tool_certification.py",
        "effect_surface_ownership.json": "runtime/effect_surface.py",
        "full_repair_ledger.json": "runtime/full_repair.py",
        "integrations.json": "runtime/integration_registry.py",
        "project_stream_handlers.json": "runtime/project_stream_orchestrator.py",
        "project_stream_orchestrations.json": "runtime/project_stream_orchestrator.py",
        "python_surface_ownership.json": "runtime/python_surface_certification.py",
        "registry_envelope_inventory.json": "runtime/registry_envelope.py",
        "semantic_capability_index.json": "runtime/semantic_index.py",
        "skill_catalog.toml": "runtime/registry.py",
        "skill_orchestrations.json": "runtime/skill_navigator.py",
        "test_profiles.json": "runtime/test_profiles.py",
        "workflow_execution_bindings.json": "runtime/structural_integrity.py",
    }
    for path in corpus.registry_paths:
        if (
            path.name == "artifact_reachability.json"
            # This operational index hashes artifact_reachability as a test
            # input. Including it here would create an unsatisfiable digest
            # cycle. Its topology and content are governed independently by
            # runtime.test_profiles and registry-envelope validation.
            or path.name == "test_group_index.json"
            # This live projection hashes the test receipts whose input hashes
            # include artifact_reachability. Indexing it here would create a
            # second unsatisfiable digest cycle. The evidence index remains
            # governed by its own builder and registry-envelope invariants.
            or path.name == "current_evidence_index.json"
            # Completion status is likewise a live projection over current
            # section/group receipts. Hashing it into the static artifact graph
            # would make advancing a receipt invalidate the graph it summarizes.
            or path.name == "completion_status.json"
            # World state binds the final product digest while remaining a
            # mutable, bounded startup projection. Hashing it into the static
            # reachability graph would feed its source revision back into that
            # digest and create an unsatisfiable cycle.
            or path.name == "px_world_state.json"
            # The operational gap ledger head and snapshot are live projections
            # advanced by every mandatory work admission. Hashing either into
            # the static graph would make the admission for a verification run
            # invalidate that graph immediately before the run starts.
            or path.name
            in {
                "operational_gap_ledger.head.json",
                "operational_gap_ledger.snapshot.json",
            }
            # The exact engine manifest hashes artifact_reachability. Including
            # the manifest here would create a two-document digest cycle.
            or path.name == "engine_identity.json"
            or path.suffix.casefold() not in {".json", ".toml", ".yaml", ".yml"}
        ):
            continue
        relative = path.relative_to(root).as_posix()
        owner = registry_owners.get(path.name, "runtime/structural_integrity.py")
        record(
            {
                "path": relative,
                "sha256": corpus.sha(path),
                "kind": "registry",
                "owner": owner,
                "reachability": "release_validated",
            }
        )
    for path in corpus.workflow_paths:
        relative = path.relative_to(root).as_posix()
        if "project_stream" in path.parts:
            binding = project_bindings.get(path.stem)
            if binding is None:
                entrypoint, mode = "", "unbound"
            else:
                dotted = str(binding["handler"])
                module, attribute = dotted.rsplit(".", 1)
                entrypoint, mode = f"{module}:{attribute}", str(binding["status"])
        else:
            binding = bindings.get(relative, {})
            entrypoint, mode = (
                str(binding.get("entrypoint", "")),
                str(binding.get("mode", "unbound")),
            )
        record(
            {
                "path": relative,
                "sha256": corpus.sha(path),
                "kind": "orchestration",
                "owner": "runtime/structural_integrity.py",
                "reachability": mode,
                "entrypoint": entrypoint,
            }
        )

    if corpus.provider_paths:
        for path in corpus.provider_paths:
            relative = path.relative_to(root).as_posix()
            if "/agents/" in f"/{relative}":
                reachability = "lazy_selected_agent_body"
            elif "/manifests/" in f"/{relative}":
                reachability = "lazy_selected_agent_manifest"
            else:
                reachability = "provider_license"
            record(
                {
                    "path": relative,
                    "sha256": corpus.sha(path),
                    "kind": "provider_asset",
                    "owner": "runtime/agent_provider.py",
                    "reachability": reachability,
                }
            )

    # YAML is executable configuration or a user-facing template. Every YAML
    # file therefore needs an explicit owner even when it is not an orchestration.
    yaml_paths = corpus.yaml_paths
    for path in sorted(yaml_paths, key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(root).as_posix()
        if relative in recorded_paths:
            continue
        if relative.startswith(".px/skills/") and relative.endswith(
            "/agents/openai.yaml"
        ):
            skill_id = relative.split("/")[2]
            owner = f".px/skills/{skill_id}/SKILL.md"
            reachability = "lazy_skill_interface"
        elif (
            relative
            == "bootstrap/commissioning/reference/questionnaire_answers.template.yaml"
        ):
            owner = "bootstrap/commissioning/reference/README_START_HERE.md"
            reachability = "documented_commissioning_template"
        elif relative.startswith("templates/project_stream/"):
            owner = "runtime/project_control_plane.py"
            reachability = "runtime_validated_template"
        else:
            owner = "runtime/structural_integrity.py"
            reachability = "unclassified_yaml"
        record(
            {
                "path": relative,
                "sha256": corpus.sha(path),
                "kind": "yaml",
                "owner": owner,
                "reachability": reachability,
            }
        )
    check_deadline(corpus.deadline)
    return {"schema_version": "1.0", "record_count": len(records), "records": records}
