"""Classify release artifacts and compute deterministic product/harness digests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import os
import stat
import tomllib
from typing import Any, Iterable

from .bounded_walk import FilesystemWalkError, WalkLimits, bounded_walk
from .repository_scope import is_external_environment_relative


POLICY_PATH = "policies/release-artifact-policy.json"


def decode_release_policy(raw: bytes | bytearray) -> dict[str, Any]:
    from .archive_io import portable_member_name
    from .json_io import decode_json_object

    policy = decode_json_object(
        raw, max_bytes=1024 * 1024, max_depth=32, max_nodes=100000
    )
    for field in ("control_output_paths", "control_output_prefixes"):
        values = policy.get(field, [])
        if type(values) is not list or len(values) > 10000:
            raise ValueError("mutable-output policy requires bounded path arrays")
        for value in values:
            if type(value) is not str or not value or len(value.encode("utf-8")) > 4096:
                raise ValueError("mutable-output path must be bounded text")
            if field.endswith("prefixes"):
                if not value.endswith("/"):
                    raise ValueError(
                        "mutable-output prefix must end at a directory boundary"
                    )
                value = value[:-1]
            portable_member_name(value, allow_directory=False)
    return policy


def release_policy_image(root: Path, *, optional: bool = False):
    from .input_files import contained_file, cooperative_deadline, read_file_image

    try:
        path, info = contained_file(root, POLICY_PATH)
    except FileNotFoundError:
        if optional:
            return {}, None
        raise
    raw = read_file_image(
        path, info, limit=1024 * 1024, deadline=cooperative_deadline()
    )
    return decode_release_policy(raw), raw


def _load_policy(root: Path) -> dict[str, Any]:
    return release_policy_image(root)[0]


def _canonical_digest(records: list[dict[str, Any]]) -> str:
    payload = b"".join(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for record in records
    )
    return hashlib.sha256(payload).hexdigest()


def _is_release_walk_excluded(relative: str | Path) -> bool:
    """Prune external custody without hiding policy-governed evidence.

    The repository source boundary intentionally excludes evidence from normal
    source discovery.  Release classification has a different obligation: it
    must see evidence payloads so executable or unapproved files cannot hide in
    that namespace.  Evidence remains non-product and its content is not hashed.
    """
    path = Path(relative)
    folded = tuple(part.casefold() for part in path.parts)
    if len(folded) >= 5 and folded[:3] == (
        "docs",
        "architecture",
        "evidence",
    ):
        run_name = folded[3]
        run_suffix = run_name.removeprefix("obsidian-native-live")
        if (
            run_name.startswith("obsidian-native-live")
            and (
                not run_suffix
                or (run_suffix.startswith("-") and run_suffix[1:].isdigit())
            )
            and folded[4] == "profile"
        ):
            return True
    if any(part.casefold() == "evidence" for part in path.parts):
        return False
    return is_external_environment_relative(path)


def _source_file_in_checked_root(root: Path, relative: str):
    """Acquire metadata below an already canonical, checked root.

    The relative-path contract forbids escapes. Inspect all original components
    before stat; read_file_image independently checks components and the opened
    generation before reading. Re-resolving the same root adds no pinned-handle
    guarantee and is unnecessary for each member of a bounded inventory.
    """
    from .archive_io import reject_path_links
    from .input_files import relative_source_path

    path = root / relative_source_path(relative)
    reject_path_links(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("source input must be a regular file")
    return path, info


def _release_path_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
    )


def _release_path_is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _release_directory_identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, info.st_mode


class _ReleaseImageInventory:
    """Acquire one verified image per path with shared ancestry checks.

    ``bounded_walk`` has already rejected links across the complete tree. This
    request-local reader checks each directory generation once, brackets all
    file reads with exact handle/path identity, and rechecks every directory at
    completion. Rewalking every absolute ancestor for every file adds large
    quadratic metadata work without pinning those ancestors or closing the
    path-to-open race.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        info = root.lstat()
        if _release_path_is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("release source root must be a physical directory")
        self.directories = {root: _release_directory_identity(info)}
        self.files: dict[Path, tuple[int, int, int, int, int]] = {}
        self.modes: dict[str, int] = {}

    def _check_parent(self, parent: Path) -> None:
        try:
            parts = parent.relative_to(self.root).parts
        except ValueError as error:
            raise ValueError("release source path escaped its root") from error
        current = self.root
        for part in parts:
            current /= part
            if current in self.directories:
                continue
            info = current.lstat()
            if _release_path_is_link(info) or not stat.S_ISDIR(info.st_mode):
                raise ValueError("linked or non-directory release source ancestor")
            self.directories[current] = _release_directory_identity(info)

    def acquire(self, relative: str, *, limit: int, deadline: float) -> bytearray:
        from .input_files import check_deadline, relative_source_path

        if type(limit) is not int or not 0 <= limit <= 64 * 1024 * 1024:
            raise ValueError("release source byte budget is invalid")
        path = self.root / relative_source_path(relative)
        self._check_parent(path.parent)
        check_deadline(deadline)
        before = path.lstat()
        if _release_path_is_link(before) or not stat.S_ISREG(before.st_mode):
            raise ValueError("release source input must be a physical regular file")
        if before.st_size > limit:
            raise ValueError("release source input exceeded its byte budget")
        expected = _release_path_identity(before)
        raw = bytearray()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if _release_path_identity(opened) != expected:
                raise ValueError("release source changed before acquisition")
            wanted = before.st_size + 1
            while len(raw) < wanted:
                check_deadline(deadline)
                chunk = stream.read(min(65_536, wanted - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            after = os.fstat(stream.fileno())
        check_deadline(deadline)
        if len(raw) != before.st_size or _release_path_identity(after) != expected:
            raise ValueError("release source changed during acquisition")
        self.files[path] = expected
        self.modes[relative] = stat.S_IMODE(before.st_mode)
        return raw

    def digest_many(
        self,
        requests: list[tuple[str, int]],
        *,
        deadline: float,
        max_workers: int = 8,
    ) -> dict[str, dict[str, object]]:
        """Hash a complete inventory with bounded parallel file handles."""
        from concurrent.futures import ThreadPoolExecutor
        from .input_files import check_deadline, relative_source_path

        if type(max_workers) is not int or not 1 <= max_workers <= 16:
            raise ValueError("release source worker budget is invalid")
        prepared = []
        results: dict[str, dict[str, object]] = {}
        for relative, limit in requests:
            try:
                if type(limit) is not int or not 0 <= limit <= 64 * 1024 * 1024:
                    raise ValueError("release source byte budget is invalid")
                path = self.root / relative_source_path(relative)
                self._check_parent(path.parent)
                check_deadline(deadline)
                before = path.lstat()
                if _release_path_is_link(before) or not stat.S_ISREG(before.st_mode):
                    raise ValueError(
                        "release source input must be a physical regular file"
                    )
                if before.st_size > limit:
                    raise ValueError("release source input exceeded its byte budget")
                prepared.append(
                    (relative, path, before, _release_path_identity(before))
                )
            except (OSError, ValueError) as error:
                results[relative] = {
                    "sha256": None,
                    "size": None,
                    "error": type(error).__name__,
                }

        def digest_one(item):
            relative, path, before, expected = item
            try:
                check_deadline(deadline)
                digest = hashlib.sha256()
                received = 0
                with path.open("rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if _release_path_identity(opened) != expected:
                        raise ValueError("release source changed before acquisition")
                    while received <= before.st_size:
                        check_deadline(deadline)
                        chunk = stream.read(min(65_536, before.st_size + 1 - received))
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > before.st_size:
                            raise ValueError(
                                "release source changed during acquisition"
                            )
                        digest.update(chunk)
                    after = os.fstat(stream.fileno())
                check_deadline(deadline)
                if (
                    received != before.st_size
                    or _release_path_identity(after) != expected
                ):
                    raise ValueError("release source changed during acquisition")
                return relative, {
                    "sha256": digest.hexdigest(),
                    "size": received,
                    "expected": expected,
                    "path": path,
                    "mode": stat.S_IMODE(before.st_mode),
                    "error": None,
                }
            except (OSError, ValueError) as error:
                return relative, {
                    "sha256": None,
                    "size": None,
                    "error": type(error).__name__,
                }

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results.update(dict(executor.map(digest_one, prepared)))
        for relative, fact in results.items():
            if fact["error"] is None:
                self.files[fact["path"]] = fact["expected"]
                self.modes[relative] = fact["mode"]
        return results

    def verify(self) -> None:
        for path, expected in self.files.items():
            current = path.lstat()
            if (
                _release_path_is_link(current)
                or not stat.S_ISREG(current.st_mode)
                or _release_path_identity(current) != expected
            ):
                relative = path.relative_to(self.root).as_posix()
                raise ValueError(
                    "release source file changed during acquisition: " + relative
                )
        for path, expected in self.directories.items():
            current = path.lstat()
            if (
                _release_path_is_link(current)
                or not stat.S_ISDIR(current.st_mode)
                or _release_directory_identity(current) != expected
            ):
                raise ValueError("release source directory changed during acquisition")


def classify_tree(root: Path) -> dict[str, Any]:
    from .input_files import directory_root, cooperative_deadline

    root = directory_root(root)
    deadline = cooperative_deadline()
    policy, policy_raw = release_policy_image(root)
    policy_sha256 = hashlib.sha256(policy_raw).hexdigest()
    product_roots = {item.casefold() for item in policy["product_roots"]}
    product_files = {item.casefold() for item in policy["product_root_files"]}
    evidence_roots = {item.casefold() for item in policy["evidence_roots"]}
    audit_roots = {item.casefold() for item in policy.get("audit_roots", [])}
    audit_root_files = {item.casefold() for item in policy.get("audit_root_files", [])}
    audit_suffixes = {
        item.casefold() for item in policy.get("audit_allowed_suffixes", [])
    }
    intermediate_names = {item.casefold() for item in policy["intermediate_names"]}
    intermediate_name_suffixes = {
        item.casefold() for item in policy.get("intermediate_name_suffixes", [])
    }
    intermediate_suffixes = {
        item.casefold() for item in policy["intermediate_suffixes"]
    }
    control_outputs = {item.casefold() for item in policy["control_output_paths"]}
    control_output_prefixes = tuple(
        item.casefold() for item in policy.get("control_output_prefixes", [])
    )
    evidence_suffixes = {
        item.casefold() for item in policy["evidence_allowed_suffixes"]
    }
    evidence_names = {
        item.casefold() for item in policy.get("evidence_allowed_names", [])
    }
    records: list[dict[str, Any]] = []
    pending_images: list[tuple[int, str, int, str]] = []
    errors: list[str] = []
    product_errors: list[str] = []
    normalized_seen: dict[str, str] = {}
    try:
        walk = bounded_walk(
            root,
            limits=WalkLimits(
                max_files=250_000,
                max_depth=128,
                max_bytes=64 * 1024 * 1024 * 1024,
            ),
            symlink_policy="reject",
            exclude=_is_release_walk_excluded,
        )
    except FilesystemWalkError as error:
        return {
            "schema_version": "1.0",
            "valid": False,
            "product_valid": False,
            "policy_version": policy["policy_version"],
            "policy_sha256": policy_sha256,
            "file_count": 0,
            "counts": {},
            "product_digest": _canonical_digest([]),
            "harness_digest": _canonical_digest([]),
            "product_records": [],
            "records": [],
            "errors": [f"bounded filesystem walk failed: {error.code}"],
        }
    inventory = _ReleaseImageInventory(root)
    for entry in walk.entries:
        relative = entry.relative
        normalized = relative.casefold()
        prior = normalized_seen.get(normalized)
        if prior is not None and prior != relative:
            collision = f"case-fold path collision: {prior} vs {relative}"
            errors.append(collision)
            product_errors.append(collision)
        normalized_seen[normalized] = relative
        if entry.kind == "file":
            path = entry.path
            parts = relative.split("/")
            folded_parts = [item.casefold() for item in parts]
            folded = relative.casefold()
            suffix = path.suffix.casefold()
            if (
                any(item in intermediate_names for item in folded_parts)
                or any(
                    item.endswith(ending)
                    for item in folded_parts
                    for ending in intermediate_name_suffixes
                )
                or suffix in intermediate_suffixes
            ):
                classification = "generated_intermediate"
                reason = "narrow generated-artifact exclusion"
            elif folded in control_outputs or any(
                folded.startswith(prefix) for prefix in control_output_prefixes
            ):
                classification = "control_output"
                reason = "mutable release transaction, governance, or receipt control"
            elif any(part in evidence_roots for part in folded_parts):
                classification = "evidence_output"
                reason = "non-executable evidence namespace"
                if (
                    suffix not in evidence_suffixes
                    and path.name.casefold() not in evidence_names
                ):
                    errors.append(
                        f"executable or unapproved evidence payload: {relative}"
                    )
            elif folded_parts[0] in audit_roots or (
                len(parts) == 1 and folded in audit_root_files
            ):
                classification = "audit_artifact"
                reason = "bounded final audit handoff surface"
                if suffix not in audit_suffixes:
                    errors.append(f"unapproved audit artifact payload: {relative}")
            elif folded_parts[0] in product_roots or (
                len(parts) == 1 and folded in product_files
            ):
                classification = "product_input"
                reason = "declared product surface"
            else:
                classification = "unclassified"
                reason = "no release policy rule"
                errors.append(f"unclassified release artifact: {relative}")
            if path.is_file():
                if classification in {"control_output", "evidence_output"}:
                    content_sha256 = None
                elif relative == POLICY_PATH:
                    if len(policy_raw) != entry.size:
                        content_sha256 = None
                        unreadable = (
                            f"unreadable release artifact: {relative}: ValueError"
                        )
                        errors.append(unreadable)
                        if classification == "product_input":
                            product_errors.append(unreadable)
                    else:
                        content_sha256 = hashlib.sha256(policy_raw).hexdigest()
                else:
                    content_sha256 = None
                records.append(
                    {
                        "path": relative,
                        "classification": classification,
                        "reason": reason,
                        "size": entry.size,
                        "sha256": content_sha256,
                    }
                )
                if (
                    classification not in {"control_output", "evidence_output"}
                    and relative != POLICY_PATH
                ):
                    pending_images.append(
                        (len(records) - 1, relative, entry.size, classification)
                    )
    image_results = inventory.digest_many(
        [(relative, 64 * 1024 * 1024) for _, relative, _, _ in pending_images],
        deadline=deadline,
    )
    for index, relative, expected_size, classification in pending_images:
        fact = image_results[relative]
        if fact["error"] is not None or fact["size"] != expected_size:
            unreadable = (
                f"unreadable release artifact: {relative}: "
                f"{fact['error'] or 'ValueError'}"
            )
            errors.append(unreadable)
            if classification == "product_input":
                product_errors.append(unreadable)
        else:
            records[index]["sha256"] = fact["sha256"]
    try:
        inventory.verify()
    except (OSError, ValueError) as error:
        message = (
            "release source ancestry changed during classification: "
            f"{type(error).__name__}: {error}"
        )
        errors.append(message)
        product_errors.append(message)
    records.sort(key=lambda item: item["path"].casefold())
    product_records = [
        {key: item[key] for key in ("path", "size", "sha256")}
        for item in records
        if item["classification"] == "product_input"
    ]
    harness_paths = {
        "runtime/release_artifacts.py",
        "runtime/release_certification.py",
        "runtime/release_audit.py",
        "runtime/structural_integrity.py",
        "runtime/exact_tool_certification.py",
        "policies/release-artifact-policy.json",
        "registry/test_profiles.json",
    }
    harness_records = [
        item
        for item in product_records
        if item["path"] in harness_paths
        or item["path"].startswith("tests/test_release")
        or item["path"].startswith("tests/test_structural")
    ]
    counts: dict[str, int] = {}
    for item in records:
        counts[item["classification"]] = counts.get(item["classification"], 0) + 1
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "product_valid": not product_errors,
        "policy_version": policy["policy_version"],
        "policy_sha256": policy_sha256,
        "file_count": len(records),
        "counts": dict(sorted(counts.items())),
        "product_digest": _canonical_digest(product_records),
        "harness_digest": _canonical_digest(harness_records),
        "product_records": product_records,
        "records": records,
        "errors": errors,
    }


def verify_frozen_product(root: Path, frozen: dict[str, Any]) -> dict[str, Any]:
    current = classify_tree(root)
    errors = list(current["errors"])
    if current["product_digest"] != frozen.get("product_digest"):
        errors.append("product input digest changed after freeze")
    if current["harness_digest"] != frozen.get("harness_digest"):
        errors.append("certification harness digest changed after freeze")
    return {
        "valid": not errors,
        "product_digest": current["product_digest"],
        "harness_digest": current["harness_digest"],
        "errors": errors,
    }


def _safe_fixture_relative(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe release fixture path: {value}")
    return relative


def _declared_evidence_files(root: Path) -> set[str]:
    configuration = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    data_files = (
        configuration.get("tool", {}).get("setuptools", {}).get("data-files", {})
    )
    declared: set[str] = set()
    for patterns in data_files.values():
        for pattern in patterns:
            relative_pattern = _safe_fixture_relative(str(pattern)).as_posix()
            if not relative_pattern.startswith("evidence/"):
                continue
            for candidate in root.glob(relative_pattern):
                if candidate.is_file():
                    declared.add(candidate.relative_to(root).as_posix())
    return declared


def materialize_release_source(
    source_root: Path,
    destination: Path,
    *,
    extra_paths: Iterable[str] = (),
) -> dict[str, object]:
    """Materialize product inputs and declared packaged evidence for release tests."""

    from .input_files import directory_root
    from .archive_io import reject_path_links

    root = directory_root(source_root)
    reject_path_links(destination)
    target = destination.resolve(strict=False)
    if target.exists():
        raise FileExistsError(f"release fixture destination already exists: {target}")
    try:
        target.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("release fixture destination must be outside the source root")

    classification = classify_tree(root)
    if not classification["valid"] or not classification["product_valid"]:
        raise ValueError(
            f"release source is not classifiable: {classification['errors']}"
        )

    product_paths = {record["path"] for record in classification["product_records"]}
    declared_evidence = _declared_evidence_files(root)
    extras = {_safe_fixture_relative(str(path)).as_posix() for path in extra_paths}
    selected = sorted(product_paths | declared_evidence | extras)

    from .input_files import cooperative_deadline, check_deadline

    expected = {record["path"]: record for record in classification["product_records"]}

    def identity(value):
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns

    copied_bytes = 0
    copied_records = []
    created_paths = []
    directory_creation_attempted = False
    deadline = cooperative_deadline()
    reject_path_links(destination)
    inventory = _ReleaseImageInventory(root)
    try:
        for relative in selected:
            raw = inventory.acquire(relative, limit=64 * 1024 * 1024, deadline=deadline)
            if copied_bytes + len(raw) > 64 * 1024**3:
                raise ValueError(
                    "release fixture aggregate source byte budget exceeded"
                )
            digest = hashlib.sha256(raw).hexdigest()
            if relative in expected and (
                digest != expected[relative]["sha256"]
                or len(raw) != expected[relative]["size"]
            ):
                raise ValueError(
                    "release fixture source changed after classification: " + relative
                )
            output = target / Path(relative)
            reject_path_links(output)
            directory_creation_attempted = True
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x+b") as stream:
                created_paths.append(relative)
                if stream.write(raw) != len(raw):
                    raise OSError("short release materialization write")
                stream.flush()
                written = os.fstat(stream.fileno())
                os.chmod(output, inventory.modes[relative])
                check_deadline(deadline)
                stream.seek(0)
                actual = stream.read(len(raw) + 1)
                checked = os.fstat(stream.fileno())
                # Verify the exclusive creation handle and its still-current
                # pathname. Reopening every ancestor and file adds no snapshot
                # guarantee; neither path supplies pinned ancestor handles.
                reject_path_links(output)
                named = output.stat()
                if (
                    not stat.S_ISREG(checked.st_mode)
                    or identity(written) != identity(checked)
                    or identity(checked) != identity(named)
                    or len(actual) != len(raw)
                    or hashlib.sha256(actual).hexdigest() != digest
                ):
                    raise ValueError(
                        "release materialization destination differs from acquired source: "
                        + relative
                    )
                check_deadline(deadline)
            copied_bytes += len(raw)
            copied_records.append(
                dict(
                    path=relative,
                    sha256=digest,
                    size=len(raw),
                    scope="product_input"
                    if relative in expected
                    else "declared_evidence_or_extra",
                )
            )
        inventory.verify()

    except BaseException as error:
        error.materialization_receipt = {
            "valid": False,
            "publication_state": "partial"
            if created_paths or directory_creation_attempted
            else "not_started",
            "created_paths": created_paths,
            "copied_records": copied_records,
            "copied_bytes": copied_bytes,
            "expected_file_count": len(selected),
            "directory_creation_attempted": directory_creation_attempted,
        }
        raise

    return {
        "schema_version": "px.test-release-source-fixture/1.0",
        "valid": True,
        "file_count": len(selected),
        "copied_bytes": copied_bytes,
        "copied_records": copied_records,
        "product_file_count": len(product_paths),
        "declared_evidence_file_count": len(declared_evidence),
        "extra_file_count": len(extras),
        "product_digest": classification["product_digest"],
        "harness_digest": classification["harness_digest"],
    }
