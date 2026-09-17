"""Bounded content captures and static local dependency closure.

Checked content is not an atomic filesystem snapshot or a runtime import trace.
"""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from .archive_io import reject_path_links
from .input_files import (
    check_deadline,
    directory_root,
    read_file_image,
    relative_source_path,
)
from .json_io import decode_json_object
from .test_runner import validate_timeout

POLICY = "registry/test_profiles.json"
MAX_FILES = 20000
MAX_BYTES = 128 * 1024**2
MAX_FILE_BYTES = 8 * 1024**2
MAX_PROBES = 200000
MAX_ENTRIES = 200000
MAX_PATTERNS = 4096
MAX_AST_NODES = 2000000
EXCLUDED = {"quarantine", ".quarantine", "_quarantine", "__pycache__"}


def strings(value, label, *, maximum=MAX_FILES):
    if type(value) not in (list, tuple) or len(value) > maximum:
        raise ValueError(label + " must be a bounded sequence")
    used = 0
    for item in value:
        if type(item) is not str or not item or len(item) > 4096:
            raise ValueError(label + " has an invalid string")
        used += len(item.encode("utf-8"))
    if used > 8 * 1024**2:
        raise ValueError(label + " exceeds its string byte budget")
    return list(value)


def _pattern(value):
    if type(value) is not str or len(value) > 4096:
        raise ValueError("invalid source pattern")
    parts = value.replace("\\", "/").split("/")
    if len(parts) > 128 or any(
        not p or p in {".", ".."} or p.casefold() in EXCLUDED for p in parts
    ):
        raise ValueError("unsafe source pattern")
    for part in parts:
        # Validate the literal portion using the existing portable-path owner.
        masked = "".join("x" if c in "*?[]" else c for c in part)
        relative_source_path(masked)
    return parts


class CapturedInputs:
    """Request-local bytes/digests and negative probes, never an authority cache."""

    def __init__(self, root, *, deadline=None):
        if deadline is not None and (
            type(deadline) not in (int, float) or not math.isfinite(deadline)
        ):
            raise ValueError("deadline must be a finite number")
        # Verification owners already carry supervised stage clocks. A capture
        # without an explicit deadline must not add a shorter hidden timer;
        # byte, file, entry, AST and membership bounds remain mandatory. Callers
        # that need a local clock supply it explicitly and it is preserved.
        self.deadline = float(deadline) if deadline is not None else 1e99
        check_deadline(self.deadline)
        self.root = directory_root(root)
        check_deadline(self.deadline)
        self.probes = {}
        self.directories = {}
        self.digests = {}
        self.edges = {}
        self.unresolved = {}
        self.aliases = {}
        self.physical = {}
        self.total_bytes = 0
        self.entries = 0
        self.ast_nodes = 0
        self.config = None
        self.module_cache = {}
        self.relative_paths = {}
        self.listed_stats = {}
        self.component_states = {}
        self.component_infos = {}
        self._remember_components(self.root)
        self.root_generation_started = False

    def _relative(self, value):
        """Validate each request-local spelling once; cached values remain data only."""
        if type(value) is not str:
            return relative_source_path(value)
        result = self.relative_paths.get(value)
        if result is None:
            result = relative_source_path(value)
            self.relative_paths[value] = result
        return result

    @staticmethod
    def _component_state(info):
        linked = stat.S_ISLNK(info.st_mode) or getattr(
            info, "st_reparse_tag", None
        ) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)
        if linked:
            raise ValueError("linked archive/source input refused")
        return (
            info.st_mode,
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
        )

    def _remember_components(self, path):
        for part in (path, *path.parents):
            if part in self.component_states:
                continue
            try:
                info = part.lstat()
            except (FileNotFoundError, NotADirectoryError):
                continue
            self.component_states[part] = self._component_state(info)
            self.component_infos[part] = info

    def _assert_root_current(self):
        if self.root_generation_started:
            return
        expected = self.component_states[self.root]
        try:
            current = self._component_state(self.root.lstat())
        except (FileNotFoundError, NotADirectoryError):
            current = None
        if current is None or current[:3] != expected[:3]:
            raise ValueError(
                "source membership or path component changed during capture"
            )
        self.root_generation_started = True

    def _current_stat(self, relative):
        path = self.root / self._relative(relative)
        try:
            info = path.stat()
        except FileNotFoundError:
            return None
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError("source probe is not a regular file or directory")
        return (info.st_mode, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

    def _file(self, relative):
        # directory_root established an absolute canonical root, and the
        # relative-path contract forbids escapes. Refusing every original
        # link/junction component preserves containment without resolving the
        # same root/path again for every file. The byte reader independently
        # checks original components and opened identity before/after reading.
        self._assert_root_current()
        path = self.root / self._relative(relative)
        self._remember_components(path)
        info = self.component_infos.get(path)
        if info is None:
            raise FileNotFoundError(path)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("source input must be a regular file")
        return path, info

    def _stat(self, relative):
        self._assert_root_current()
        path = self.root / self._relative(relative)
        self._remember_components(path)
        info = self.component_infos.get(path)
        if info is None:
            return None
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError("source probe is not a regular file or directory")
        return self.component_states[path]

    def _listed_state(self, relative, listed):
        """Bind one listed leaf without repeating its already-checked ancestors."""
        path = self.root / self._relative(relative)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        linked = stat.S_ISLNK(info.st_mode) or getattr(
            info, "st_reparse_tag", None
        ) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)
        if linked or listed[0]:
            raise ValueError("linked archive/source input refused")
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError("source probe is not a regular file or directory")
        listed_mode, listed_size, listed_mtime_ns = listed[1]
        same_kind = stat.S_IFMT(info.st_mode) == stat.S_IFMT(listed_mode)
        same_file_image = not stat.S_ISREG(info.st_mode) or (
            info.st_size == listed_size and info.st_mtime_ns == listed_mtime_ns
        )
        if not same_kind or not same_file_image:
            raise ValueError("source membership or metadata changed during capture")
        self.component_states[path] = self._component_state(info)
        self.component_infos[path] = info
        return (info.st_mode, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

    def probe(self, relative):
        check_deadline(self.deadline)
        relative = self._relative(relative)
        if relative not in self.probes:
            if len(self.probes) >= MAX_PROBES:
                raise ValueError("source probe budget exhausted")
            listed = self.listed_stats.get(relative)
            if listed is not None:
                self.probes[relative] = self._listed_state(relative, listed)
            else:
                self.probes[relative] = self._stat(relative)
        return self.probes[relative]

    def is_file(self, relative):
        info = self.probe(relative)
        return info is not None and stat.S_ISREG(info[0])

    def listing(self, relative):
        check_deadline(self.deadline)
        if relative in self.directories:
            return self.directories[relative]
        if len(self.directories) >= MAX_FILES:
            raise ValueError("source directory budget exhausted")
        self._assert_root_current()
        path = self.root if not relative else self.root / self._relative(relative)
        reject_path_links(path)
        names = []
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    check_deadline(self.deadline)
                    self.entries += 1
                    if self.entries > MAX_ENTRIES:
                        raise ValueError("source entry budget exhausted")
                    # Exclusion is by complete component, before acquisition.
                    if entry.name.casefold() not in EXCLUDED:
                        names.append(entry.name)
                        child = "/".join(filter(None, [relative, entry.name]))
                        info = entry.stat(follow_symlinks=False)
                        linked = stat.S_ISLNK(info.st_mode) or getattr(
                            info, "st_reparse_tag", None
                        ) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)
                        self.listed_stats[child] = (
                            linked,
                            (info.st_mode, info.st_size, info.st_mtime_ns),
                        )
        except FileNotFoundError:
            return ()
        result = tuple(sorted(names))
        self.directories[relative] = result
        return result

    def match(self, patterns):
        matched = set()
        states = set()
        for pattern in strings(patterns, "source patterns", maximum=MAX_PATTERNS):
            parts = _pattern(pattern)
            pending = [("", 0)]
            while pending:
                check_deadline(self.deadline)
                parent, index = pending.pop()
                key = (pattern, parent, index)
                if key in states:
                    continue
                states.add(key)
                if len(states) > MAX_PROBES:
                    raise ValueError("source pattern expansion budget exhausted")
                if len(Path(parent).parts) > 128:
                    raise ValueError("source path depth budget exhausted")
                if index == len(parts):
                    if parent and self.is_file(parent):
                        matched.add(parent)
                    continue
                part = parts[index]
                if part == "**":
                    pending.append((parent, index + 1))
                    for name in self.listing(parent):
                        child = "/".join(filter(None, [parent, name]))
                        info = self.probe(child)
                        if info and stat.S_ISDIR(info[0]):
                            pending.append((child, index))
                        elif index == len(parts) - 1 and info and stat.S_ISREG(info[0]):
                            matched.add(child)
                else:
                    names = (
                        self.listing(parent)
                        if any(c in part for c in "*?[")
                        else (part,)
                    )
                    for name in names:
                        if not fnmatch.fnmatchcase(name, part):
                            continue
                        child = "/".join(filter(None, [parent, name]))
                        info = self.probe(child)
                        if info and (index == len(parts) - 1 or stat.S_ISDIR(info[0])):
                            pending.append((child, index + 1))
            if len(matched) > MAX_FILES:
                raise ValueError("source file budget exhausted")
        return sorted(matched)

    def _module(self, name):
        # Probe exact local paths; never import modules to discover dependencies.
        if type(name) is not str or len(name) > 4096:
            raise ValueError("invalid local import name")
        if name in self.module_cache:
            return self.module_cache[name]
        parts = name.split(".")
        if len(parts) > 128 or any(not p.isidentifier() for p in parts):
            raise ValueError("invalid local import path")
        found = set()
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            package = prefix + "/__init__.py"
            module = prefix + ".py"
            if self.is_file(package):
                found.add(package)
            elif self.is_file(module):
                found.add(module)
            # Deeper local candidates require a directory. Retain this probe
            # so appearance/replacement invalidates the final verification.
            # Existing directories (including namespaces) still traverse fully.
            if index < len(parts):
                info = self.probe(prefix)
                if info is None or not stat.S_ISDIR(info[0]):
                    break
        self.module_cache[name] = frozenset(found)
        return self.module_cache[name]

    def _imports(self, relative, raw):
        try:
            tree = ast.parse(bytes(raw), filename=relative)
        except (SyntaxError, UnicodeError, RecursionError) as error:
            raise ValueError(
                "cannot establish Python dependency closure: " + relative
            ) from error
        nodes = []
        for node in ast.walk(tree):
            self.ast_nodes += 1
            if self.ast_nodes > MAX_AST_NODES:
                raise ValueError("source AST node budget exhausted")
            nodes.append(node)
        modules = set()
        dynamic_aliases = {"__import__"}
        importlib_aliases = {"importlib"}
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name)
                    if alias.name == "importlib":
                        importlib_aliases.add(alias.asname or alias.name)
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module == "importlib"
            ):
                for alias in node.names:
                    if alias.name == "import_module":
                        dynamic_aliases.add(alias.asname or alias.name)
        package = list(Path(relative).parent.parts)
        for node in nodes:
            check_deadline(self.deadline)
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
                isinstance(target, ast.Name) and target.id == "pytest_plugins"
                for target in (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
            ):
                value = node.value
                items = (
                    value.elts if isinstance(value, (ast.Tuple, ast.List)) else [value]
                )
                if all(
                    isinstance(item, ast.Constant) and type(item.value) is str
                    for item in items
                ):
                    modules.update(item.value for item in items)
                else:
                    self.unresolved.setdefault(relative, []).append(node.lineno)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.level > len(package):
                        raise ValueError("relative import escapes local package")
                    base = package[: len(package) - node.level + 1]
                    if node.module:
                        base += node.module.split(".")
                    name = ".".join(base)
                else:
                    name = node.module or ""
                if name:
                    modules.add(name)
                    modules.update(
                        name + "." + alias.name
                        for alias in node.names
                        if alias.name != "*"
                    )
            elif isinstance(node, ast.Call):
                function = node.func
                dynamic = (
                    isinstance(function, ast.Name) and function.id in dynamic_aliases
                ) or (
                    isinstance(function, ast.Attribute)
                    and function.attr == "import_module"
                    and isinstance(function.value, ast.Name)
                    and function.value.id in importlib_aliases
                )
                if dynamic:
                    if (
                        node.args
                        and isinstance(node.args[0], ast.Constant)
                        and type(node.args[0].value) is str
                        and not node.args[0].value.startswith(".")
                    ):
                        modules.add(node.args[0].value)
                    else:
                        self.unresolved.setdefault(relative, []).append(node.lineno)
        found = set()
        for name in sorted(modules):
            found.update(self._module(name))
        # Package initializers and pytest ancestors participate without requiring
        # an explicit import in a test module.
        for index in range(len(package) + 1):
            parent = "/".join(package[:index])
            for leaf in ["conftest.py", "__init__.py"]:
                path = "/".join(filter(None, [parent, leaf]))
                if self.is_file(path):
                    found.add(path)
        return found

    def capture(self, relative):
        relative = self._relative(relative)
        if relative in self.digests:
            return
        if len(self.digests) >= MAX_FILES:
            raise ValueError("captured file budget exhausted")
        identity = relative.casefold()
        if identity in self.aliases and self.aliases[identity] != relative:
            raise ValueError("portable source alias")
        path, info = self._file(relative)
        if info.st_size > MAX_FILE_BYTES or self.total_bytes + info.st_size > MAX_BYTES:
            raise ValueError("captured source byte budget exhausted")
        physical = (info.st_dev, info.st_ino)
        if (
            info.st_nlink > 1
            or physical in self.physical
            and self.physical[physical] != relative
        ):
            raise ValueError("physical source alias")
        self.probe(relative)
        raw = read_file_image(
            path,
            info,
            limit=MAX_FILE_BYTES if relative != POLICY else 1024**2,
            deadline=self.deadline,
            links_checked=True,
        )
        self.total_bytes += len(raw)
        self.aliases[identity] = relative
        self.physical[physical] = relative
        self.digests[relative] = hashlib.sha256(raw).digest()
        if relative == POLICY:
            self.config = decode_json_object(
                raw, max_bytes=1024**2, max_depth=32, max_nodes=100000
            )
        self.edges[relative] = (
            self._imports(relative, raw) if relative.endswith(".py") else set()
        )

    def _capture_nonpython_batch(self, relatives):
        prepared = []
        pending_bytes = 0
        pending_physical = {}
        pending_relatives = set()
        for relative in relatives:
            relative = self._relative(relative)
            if relative in self.digests or relative in pending_relatives:
                continue
            pending_relatives.add(relative)
            if len(self.digests) + len(prepared) >= MAX_FILES:
                raise ValueError("captured file budget exhausted")
            identity = relative.casefold()
            if identity in self.aliases and self.aliases[identity] != relative:
                raise ValueError("portable source alias")
            state = self.probe(relative)
            path = self.root / relative
            info = self.component_infos.get(path)
            if state is None or info is None or not stat.S_ISREG(info.st_mode):
                raise ValueError("source input must be a regular file")
            pending_bytes += info.st_size
            if (
                info.st_size > MAX_FILE_BYTES
                or self.total_bytes + pending_bytes > MAX_BYTES
            ):
                raise ValueError("captured source byte budget exhausted")
            physical = (info.st_dev, info.st_ino)
            if (
                info.st_nlink > 1
                or physical in self.physical
                and self.physical[physical] != relative
                or physical in pending_physical
                and pending_physical[physical] != relative
            ):
                raise ValueError("physical source alias")
            pending_physical[physical] = relative
            prepared.append((relative, identity, path, info, physical))

        def acquire(item):
            relative, _identity, path, info, _physical = item
            raw = read_file_image(
                path,
                info,
                limit=MAX_FILE_BYTES,
                deadline=self.deadline,
                links_checked=True,
            )
            return relative, hashlib.sha256(raw).digest()

        if len(prepared) > 32:
            with ThreadPoolExecutor(max_workers=8) as pool:
                acquired = list(pool.map(acquire, prepared))
        else:
            acquired = [acquire(item) for item in prepared]
        acquired_by_path = dict(acquired)
        for relative, identity, _path, info, physical in prepared:
            self.total_bytes += info.st_size
            self.aliases[identity] = relative
            self.physical[physical] = relative
            self.digests[relative] = acquired_by_path[relative]
            self.edges[relative] = set()

    def closure(self, members):
        pending = strings(members, "dependency members")
        selected = set()
        if all(relative in self.digests for relative in pending):
            while pending:
                relative = pending.pop()
                if relative in selected:
                    continue
                selected.add(relative)
                pending.extend(self.edges[relative] - selected)
            return sorted(selected)
        while pending:
            python = []
            nonpython = []
            while pending:
                relative = pending.pop()
                if relative in selected:
                    continue
                (python if relative.endswith(".py") else nonpython).append(relative)
            self._capture_nonpython_batch(nonpython)
            selected.update(nonpython)
            for relative in python:
                if relative in selected:
                    continue
                self.capture(relative)
                selected.add(relative)
                pending.extend(self.edges[relative] - selected)
        return sorted(selected)

    def fingerprint(self, paths):
        digest = hashlib.sha256()
        for relative in paths:
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(self.digests[relative])
        return digest.hexdigest()

    def verify(self):
        # A second content pass catches same-size/same-mtime changes. This is a
        # checked capture, not a claim of atomic cross-file linearizability.
        component_items = list(self.component_states.items())

        def inspect_component(path):
            check_deadline(self.deadline)
            try:
                info = path.lstat()
                return self._component_state(info), info
            except (FileNotFoundError, NotADirectoryError):
                return None, None

        if len(component_items) > 64:
            with ThreadPoolExecutor(max_workers=8) as pool:
                current_states = list(
                    pool.map(
                        inspect_component,
                        (path for path, _expected in component_items),
                    )
                )
        else:
            current_states = [
                inspect_component(path) for path, _expected in component_items
            ]
        current_components = {}
        current_infos = {}
        for (path, expected), (current, info) in zip(component_items, current_states):
            inside_root = path == self.root or self.root in path.parents
            if inside_root:
                component_changed = current != expected
            else:
                component_changed = current is None or current[:3] != expected[:3]
            if component_changed:
                try:
                    label = path.relative_to(self.root).as_posix() or "."
                except ValueError:
                    label = "root-ancestor"
                raise ValueError(
                    "source membership or path component changed during capture: "
                    + label
                )
            current_components[path] = current
            current_infos[path] = info

        digest_items = list(self.digests.items())
        verified_bytes = sum(self.probes[relative][3] for relative, _ in digest_items)
        if verified_bytes > MAX_BYTES or any(
            self.probes[relative][3] > MAX_FILE_BYTES for relative, _ in digest_items
        ):
            raise ValueError("source recheck byte budget exhausted")

        def recheck_content(item):
            relative, expected = item
            check_deadline(self.deadline)
            path = self.root / self._relative(relative)
            info = current_infos[path]
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("source recheck byte budget exhausted")
            raw = read_file_image(
                path,
                info,
                limit=MAX_FILE_BYTES,
                deadline=self.deadline,
                links_checked=True,
            )
            return relative, expected, hashlib.sha256(raw).digest()

        if len(digest_items) > 32:
            with ThreadPoolExecutor(max_workers=8) as pool:
                content_results = list(pool.map(recheck_content, digest_items))
        else:
            content_results = [recheck_content(item) for item in digest_items]
        for _relative, expected, current in content_results:
            if current != expected:
                raise ValueError("source content changed during capture")

        for relative, expected in self.probes.items():
            check_deadline(self.deadline)
            current = current_components.get(self.root / relative)
            if current is None and expected is None:
                current = self._current_stat(relative)
            if current != expected:
                raise ValueError("source membership or metadata changed during capture")
        directory_items = list(self.directories.items())

        def recheck_directory(item):
            relative, expected = item
            check_deadline(self.deadline)
            path = self.root / relative
            names = []
            count = 0
            with os.scandir(path) as entries:
                for entry in entries:
                    check_deadline(self.deadline)
                    count += 1
                    if entry.name.casefold() not in EXCLUDED:
                        names.append(entry.name)
            return relative, expected, tuple(sorted(names)), count

        if len(directory_items) > 16:
            with ThreadPoolExecutor(max_workers=8) as pool:
                directory_results = list(pool.map(recheck_directory, directory_items))
        else:
            directory_results = [recheck_directory(item) for item in directory_items]
        verified_entries = 0
        for _relative, expected, current, count in directory_results:
            verified_entries += count
            if verified_entries > MAX_ENTRIES:
                raise ValueError("source recheck entry budget exhausted")
            if current != expected:
                raise ValueError("source directory membership changed during capture")


def resolve_test_section(root, name, *, capture=None):
    owned = capture is None
    capture = capture if capture is not None else CapturedInputs(root)
    capture.capture(POLICY)
    config = capture.config
    sections = config.get("sections")
    if (
        type(sections) is not dict
        or type(name) is not str
        or type(sections.get(name)) is not dict
    ):
        raise ValueError("unknown test section")
    identity(name, "section")
    section = sections[name]
    matched = capture.match(section.get("source_patterns", []))
    if not matched:
        raise ValueError("test section has no current inputs")
    command = strings(section.get("command", []), "command")
    if not command:
        raise ValueError("test section has no command")
    cwd_value = section.get("cwd", ".")
    if cwd_value != ".":
        cwd_value = relative_source_path(cwd_value)
    cwd = directory_root(capture.root / cwd_value)
    if not cwd.is_relative_to(capture.root):
        raise ValueError("test section cwd escapes root")
    timeout = validate_timeout(section.get("timeout_seconds"))
    members, member_indices, plugins = command_members(
        capture, cwd, command, details=True
    )
    inputs = capture.closure(
        sorted(
            {
                *matched,
                POLICY,
                *plugins,
                *(
                    (cwd.relative_to(capture.root) / value).as_posix()
                    for value in members
                ),
            }
        )
    )
    size = section.get("chunk_size", 0)
    workers = section.get("max_parallel_chunks", 1)
    if (
        type(size) is not int
        or not 0 <= size <= 20
        or type(workers) is not int
        or not 1 <= workers <= 8
    ):
        raise ValueError("invalid chunk bounds")
    chunks = []
    if size:
        if len(members) < 2 or len(members) != len(set(members)):
            raise ValueError("chunked section needs distinct file members")
        chunk_timeout = validate_timeout(section.get("chunk_timeout_seconds"))
        member_paths = {
            (cwd.relative_to(capture.root) / value).as_posix() for value in members
        }
        shared = set(inputs) - member_paths
        base = [
            value for index, value in enumerate(command) if index not in member_indices
        ]
        for index in range(0, len(members), size):
            selected = members[index : index + size]
            chunk_id = f"chunk-{index // size + 1:02d}"
            chunk_inputs = capture.closure(
                sorted(
                    shared
                    | {
                        (cwd.relative_to(capture.root) / value).as_posix()
                        for value in selected
                    }
                )
            )
            chunk_command = [*base, *selected]
            chunk_identity = hashlib.sha256(
                json.dumps(
                    {
                        "content_sha256": capture.fingerprint(chunk_inputs),
                        "chunk_id": chunk_id,
                        "command": chunk_command,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "members": selected,
                    "member_count": len(selected),
                    "inputs": chunk_inputs,
                    "command": chunk_command,
                    "input_sha256": chunk_identity,
                    "timeout_seconds": chunk_timeout,
                }
            )
    if owned:
        capture.verify()
    return {
        "schema_version": "px.test-section/1.0",
        "valid": True,
        "section": name,
        "description": description(section.get("description", "")),
        "dependencies": dependencies(section.get("dependencies", []), sections, name),
        "inputs": inputs,
        "input_sha256": capture.fingerprint(inputs),
        "command": command,
        "cwd": str(cwd),
        "cwd_relative": cwd.relative_to(capture.root).as_posix(),
        "timeout_seconds": timeout,
        "chunks": chunks,
        "max_parallel_chunks": workers if chunks else 1,
        "environment": {
            **environment(config.get("environment", {})),
            **environment(section.get("environment", {})),
        },
        "dependency_analysis": {
            "kind": "static-local-python-plus-declared-assets",
            "unresolved_dynamic_imports": capture.unresolved,
            "runtime_coverage_complete": False,
        },
    }


def local_python_dependencies(root, members, module_paths=None):
    # Stored mappings are hints only. Never let stale imported edges omit a
    # freshly discoverable dependency or a negative-probe change.
    if module_paths is not None:
        if type(module_paths) is not dict or len(module_paths) > MAX_FILES:
            raise ValueError("invalid stored module mapping")
        for name, path in module_paths.items():
            if type(name) is not str or len(name) > 4096:
                raise ValueError("invalid stored module name")
            relative_source_path(path)
    capture = CapturedInputs(root)
    result = capture.closure([*members, POLICY])
    capture.verify()
    return result


def identity(value, label):
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in value)
    ):
        raise ValueError(label + " identity is invalid")
    return value


def description(value):
    if type(value) is not str or len(value) > 8192:
        raise ValueError("description must be bounded text")
    return value


def environment(value):
    if type(value) is not dict or len(value) > 256:
        raise ValueError("environment must be a bounded object")
    for key, item in value.items():
        if (
            type(key) is not str
            or not key
            or len(key) > 256
            or "=" in key
            or "\0" in key
            or type(item) is not str
            or len(item) > 32768
            or "\0" in item
        ):
            raise ValueError(
                "environment keys and values must be valid bounded strings"
            )
    if (
        sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k, v in value.items())
        > 1024**2
    ):
        raise ValueError("environment byte budget exhausted")
    return dict(value)


def dependencies(value, sections, owner):
    result = strings(value, "section dependencies", maximum=128)
    if len(result) != len(set(result)):
        raise ValueError("duplicate section dependency")
    for name in result:
        identity(name, "dependency")
        if name == owner or name not in sections:
            raise ValueError("unknown or self-referential section dependency")
    return sorted(result)


def command_members(capture, cwd, command, *, details=False):
    """Parse only registered runner forms; options cannot become file members."""
    executable = Path(command[0]).name.casefold()
    if executable in {
        "python",
        "python.exe",
        "python3",
        "python3.exe",
    } or executable.startswith("python3."):
        if command[1:3] != ["-m", "pytest"]:
            raise ValueError(
                "section Python command must use the governed pytest module"
            )
        tokens, suffixes = command[3:], {".py"}
        offset = 3
        value_options = {
            "-p",
            "-k",
            "-m",
            "-c",
            "--rootdir",
            "--override-ini",
            "-o",
            "--durations",
            "--maxfail",
            "--tb",
            "--capture",
            "--color",
        }
    elif executable in {"node", "node.exe"} and "--test" in command[1:]:
        tokens, suffixes = command[1:], {".js", ".mjs", ".cjs"}
        offset = 1
        value_options = {
            "--test-concurrency",
            "--test-name-pattern",
            "--test-reporter",
            "--test-reporter-destination",
            "--test-timeout",
        }
    else:
        raise ValueError("unsupported governed section command")
    members = []
    member_indices = set()
    plugins = set()
    if suffixes == {".py"}:
        # The governed runner loads this local plugin even outside conftest's
        # discovery tree. Probe without executing it, including absent paths.
        plugins.update(capture._module("tests.pytest_guards"))
    consume = None
    positional_only = False
    for token_index, token in enumerate(tokens, start=offset):
        if consume:
            if consume == "-p" and not token.startswith("no:"):
                plugins.update(capture._module(token))
            consume = None
            continue
        if not positional_only and token == "--":
            positional_only = True
            continue
        if not positional_only and token.startswith("-"):
            if suffixes == {".py"} and token.startswith("-p") and token != "-p":
                plugin = token[2:]
                if not plugin.startswith("no:"):
                    plugins.update(capture._module(plugin))
            consume = token if token in value_options else None
            continue
        if "::" in token:
            raise ValueError("file selectors require a separate focused test lane")
        relative = relative_source_path(token)
        if Path(relative).suffix not in suffixes:
            raise ValueError("section member must be an exact test file")
        rooted = (cwd.relative_to(capture.root) / relative).as_posix()
        if not capture.is_file(rooted):
            raise ValueError("section member is missing")
        if relative in members:
            raise ValueError("duplicate section member")
        members.append(relative)
        member_indices.add(token_index)
    if consume or not members:
        raise ValueError("incomplete section command")
    return (members, member_indices, plugins) if details else members
