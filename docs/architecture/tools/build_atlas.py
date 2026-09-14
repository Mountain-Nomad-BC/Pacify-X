#!/usr/bin/env python3
"""Rebuild a source-bound, non-certifying atlas from the current checkout.

No third-party dependencies; no product imports, commands or registry reconciliation.
Historical semantic IDs are preserved. Byte currentness is not behavioral proof.
"""

from __future__ import annotations
import argparse
import ast
import collections
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
SCHEMA = "px.closure-atlas/1"
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".qa",
    ".tmp",
    "quarantine",
    ".next",
    ".engineering-bootstrap",
    "operational_gap_ledger.deltas",
    ".lock-recovery-receipts",
    "evidence",
}
VIEWS = [
    "Full Architecture",
    "Runtime Observed",
    "Certified",
    "Authority",
    "Learning",
    "Knowledge/Memory",
    "Execution",
    "Resources/Budgets",
    "Assurance",
    "Recovery",
    "Unresolved",
]
CAMERAS = [
    "Full Brain",
    "Host to Delivery",
    "Authority Core",
    "Reasoning/Learning",
    "Memory/Knowledge",
    "Execution",
    "Assurance",
    "Recovery",
    "Resources",
    "Runtime",
    "Certified",
]
JOURNEYS = [
    ("Normal Work", "F01"),
    ("Learning", "F07"),
    ("Failure/Recovery", "F03"),
    ("Knowledge Change", "F09"),
    ("Release Proof", "F10"),
]
RESOURCE_TERMS = {
    "CPU": r"\bcpu\b|processor",
    "RAM": r"\bram\b|memory.budget",
    "Disk": r"\bdisk\b|storage|workspace",
    "GPU": r"\bgpu\b|cuda",
    "Workers": r"worker|concurren",
    "Money": r"cost|money|dollar",
    "Tokens": r"\btoken",
    "Calls": r"api.call|request.budget",
    "Duration": r"deadline|timeout|duration",
    "Retries": r"retry|retries|backoff",
}


def canonical(x):
    return json.dumps(
        x, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def digest(x):
    return hashlib.sha256(x).hexdigest()


def write_json(path, x):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(x, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def slug(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:160]


def file_id(path):
    return "file:" + path


def inventory(root: Path, max_files=100000, max_bytes=2 * 1024**3, deadline=300):
    rows = []
    excluded = []
    images = {}
    total = 0
    started = time.monotonic()

    def onerror(exc):
        raise RuntimeError("directory inventory incomplete: " + str(exc))

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        safe = []
        for d in sorted(dirs):
            p = Path(directory) / d
            if (
                p.relative_to(root).as_posix() == "docs/architecture"
                or d.lower() in SKIP_DIRS
                or p.is_symlink()
                or (hasattr(p, "is_junction") and p.is_junction())
            ):
                excluded.append(
                    {
                        "path": p.relative_to(root).as_posix(),
                        "reason": "excluded directory or link",
                    }
                )
            else:
                safe.append(d)
        dirs[:] = safe
        for name in sorted(files):
            p = Path(directory) / name
            rel = p.relative_to(root).as_posix()
            if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
                excluded.append({"path": rel, "reason": "link"})
                continue
            if (
                name.startswith(".env")
                and name not in {".env.example", ".env.sample", ".env.template"}
            ) or p.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".keystore"}:
                excluded.append({"path": rel, "reason": "credential-like file"})
                continue
            if len(rows) >= max_files or time.monotonic() - started > deadline:
                raise RuntimeError(
                    "inventory bound exceeded; no complete atlas emitted"
                )
            before = p.stat()
            total += before.st_size
            if total > max_bytes:
                raise RuntimeError(
                    "inventory byte limit exceeded; narrow explicit source scope, do not silently truncate"
                )
            h = hashlib.sha256()
            raw = (
                bytearray()
                if p.suffix.lower() in {".py", ".js", ".mjs", ".cjs"}
                and before.st_size <= 8 * 1024**2
                else None
            )
            with p.open("rb") as f:
                while block := f.read(1024 * 1024):
                    h.update(block)
                    if raw is not None:
                        raw.extend(block)
            after = p.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ino,
            ):
                raise RuntimeError("source changed during acquisition: " + rel)
            rows.append({"path": rel, "bytes": before.st_size, "sha256": h.hexdigest()})
            if raw is not None:
                images[rel] = bytes(raw)
    rows.sort(key=lambda r: r["path"])
    return rows, excluded, images


def classify_path(path):
    text = path.lower()
    for layer, terms in [
        ("release", ("release", "packag", "install", "store", "vsix")),
        ("durability", ("wal", "recover", "ledger", "lock", "publication", "json_io")),
        (
            "evidence",
            ("tests/", "test_", "verification", "evidence", "audit", "certif"),
        ),
        (
            "governance",
            ("govern", "policy", "authority", "gate", "contract", "approval"),
        ),
        ("memory", ("memory", "knowledge", "semantic", "embedding")),
        ("reasoning", ("cognitive", "learning", "formula", "reasoning", "inference")),
        (
            "execution",
            ("process", "scheduler", "resource", "workgovernor", "runner", "execution"),
        ),
        ("scope", ("coordin", "project", "workspace", "claim")),
        ("acquisition", ("acquisition", "input", "archive", "skill", "intake")),
        ("discovery", ("catalog", "provider", "model", "discover", "router")),
    ]:
        if any(t in text for t in terms):
            return layer
    return "host"


def source_imports(images, paths):
    edges = {}
    unresolved = []
    parses = []

    def resolve(base):
        for p in (
            base + ".py",
            base + "/__init__.py",
            base + ".js",
            base + ".mjs",
            base + ".cjs",
            base + "/index.js",
            base,
        ):
            if p in paths:
                return p
        return None

    def add(src, target, kind, line):
        key = (src, target, kind)
        if key not in edges:
            edges[key] = {
                "id": "I:" + digest(canonical(key))[:24],
                "source": file_id(src),
                "target": file_id(target),
                "kind": kind,
                "verb": "imports (not proof of execution)",
                "evidence_level": "source-supported",
                "currentness": "snapshot-bytes",
                "source_anchor": {"path": src, "line": line},
                "layout_weight": 1.0,
            }

    for path, raw in sorted(images.items()):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError:
            parses.append({"path": path, "error": "non-UTF8"})
            continue
        if path.endswith(".py"):
            try:
                tree = ast.parse(text, filename=path)
            except (SyntaxError, ValueError, RecursionError) as e:
                parses.append({"path": path, "error": str(e)})
                continue
            for n in ast.walk(tree):
                modules = []
                if isinstance(n, ast.Import):
                    modules = [(a.name.replace(".", "/"), None) for a in n.names]
                elif isinstance(n, ast.ImportFrom):
                    base = (n.module or "").replace(".", "/")
                    if n.level:
                        dirs = path.split("/")[:-1]
                        if n.level > len(dirs):
                            unresolved.append(
                                {
                                    "source": path,
                                    "line": n.lineno,
                                    "type": "relative-import-outside-root",
                                }
                            )
                            continue
                        prefix = "/".join(dirs[: len(dirs) - n.level + 1])
                        base = "/".join(x for x in (prefix, base) if x)
                    modules = [(base, a.name) for a in n.names]
                elif isinstance(n, ast.Call) and (
                    (
                        isinstance(n.func, ast.Name)
                        and n.func.id in {"__import__", "import_module"}
                    )
                    or (
                        isinstance(n.func, ast.Attribute)
                        and n.func.attr == "import_module"
                    )
                ):
                    if (
                        n.args
                        and isinstance(n.args[0], ast.Constant)
                        and isinstance(n.args[0].value, str)
                        and not n.args[0].value.startswith(".")
                    ):
                        modules = [(n.args[0].value.replace(".", "/"), None)]
                    else:
                        unresolved.append(
                            {
                                "source": path,
                                "line": n.lineno,
                                "type": "computed-or-relative-dynamic-import",
                            }
                        )
                for base, name in modules:
                    dest = resolve(base + "/" + name) if name and name != "*" else None
                    dest = dest or resolve(base)
                    if dest:
                        add(path, dest, "imports", n.lineno)
                    else:
                        unresolved.append(
                            {
                                "source": path,
                                "line": n.lineno,
                                "import": base.replace("/", "."),
                                "type": "unresolved-local"
                                if base.startswith(
                                    (
                                        "runtime/",
                                        "extension/",
                                        "scripts/",
                                        "tools/",
                                        "tests/",
                                    )
                                )
                                else "external-or-unresolved",
                            }
                        )
        else:
            for m in re.finditer(
                r"""(?:require\s*\(\s*|from\s+|import\s*\(\s*)['"]([^'"]+)['"]""", text
            ):
                spec = m.group(1)
                if not spec.startswith("."):
                    continue
                base = os.path.normpath(str(Path(path).parent / spec)).replace(
                    "\\", "/"
                )
                dest = resolve(base)
                if dest:
                    add(path, dest, "imports", text[: m.start()].count("\n") + 1)
                else:
                    unresolved.append(
                        {
                            "source": path,
                            "line": text[: m.start()].count("\n") + 1,
                            "import": spec,
                            "type": "unresolved-relative-JS",
                        }
                    )
    return list(edges.values()), unresolved, parses


def brandes(ids, edges):
    """Exact directed unweighted betweenness; unique source/target adjacency.
    Normalization 1/((n-1)(n-2)); excludes endpoint credit, includes disconnected nodes.
    """
    adj = {i: set() for i in ids}
    for e in edges:
        if e["source"] in adj and e["target"] in adj and e["source"] != e["target"]:
            adj[e["source"]].add(e["target"])
    score = dict.fromkeys(ids, 0.0)
    for s in ids:
        stack = []
        pred = {}
        sigma = {s: 1.0}
        dist = {s: 0}
        queue = collections.deque([s])
        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in sorted(adj[v]):
                if w not in dist:
                    queue.append(w)
                    dist[w] = dist[v] + 1
                if dist[w] == dist[v] + 1:
                    sigma[w] = sigma.get(w, 0.0) + sigma[v]
                    pred.setdefault(w, []).append(v)
        delta = {}
        while stack:
            w = stack.pop()
            dw = delta.get(w, 0.0)
            for v in pred.get(w, []):
                delta[v] = delta.get(v, 0.0) + (sigma[v] / sigma[w]) * (1 + dw)
            if w != s:
                score[w] += dw
    n = len(ids)
    scale = 1 / ((n - 1) * (n - 2)) if n > 2 else 0
    return {i: round(v * scale, 10) for i, v in score.items()}


def layout(nodes, layers):
    """Versioned geometric heuristic. Deterministic ID seeds, not measured proximity."""
    centers = {}
    count = len(layers)
    for i, layer in enumerate(layers):
        a = -2.6 + i * 5.2 / (count - 1)
        centers[layer["id"]] = [
            math.sin(a) * 420,
            math.cos(a) * 180,
            math.sin(a * 1.4) * 235,
        ]
    centers["governance"] = [0, 35, 0]
    result = {}
    for n in nodes:
        h = hashlib.sha256(n["id"].encode()).digest()
        u = [int.from_bytes(h[i : i + 4], "big") / (2**32 - 1) for i in (0, 4, 8)]
        az = u[0] * 2 * math.pi
        z = 2 * u[1] - 1
        r = (u[2] ** (1 / 3)) * (105 if n["kind"] == "system" else 152)
        c = centers[n["layer"]]
        result[n["id"]] = [
            round(c[0] + r * math.sqrt(1 - z * z) * math.cos(az), 4),
            round(c[1] + r * z, 4),
            round(c[2] + r * math.sqrt(1 - z * z) * math.sin(az), 4),
        ]
    return result, centers


def build(
    repo,
    out,
    reference,
    max_files=100000,
    max_bytes=2 * 1024**3,
    allow_repo_output=False,
):
    started = time.monotonic()
    repo = repo.resolve()
    out = out.resolve()
    if out == repo:
        raise ValueError("atlas output cannot be the repository root")
    if repo in out.parents:
        expected = (repo / "docs" / "architecture").resolve()
        if not allow_repo_output or out != expected:
            raise ValueError(
                "repository output requires --allow-repo-output and the exact docs/architecture target"
            )
    elif out.exists() and any(out.iterdir()):
        raise ValueError("external output must be a new empty directory")
    raw = json.loads(
        (reference / "graph_baseline_architecture.json").read_text(encoding="utf-8-sig")
    )
    em = json.loads(
        (reference / "graph_baseline_evidence-map.json").read_text(encoding="utf-8-sig")
    )
    rows, excluded, images = inventory(repo, max_files, max_bytes)
    by_path = {r["path"]: r for r in rows}
    evidence = []
    emap = {}
    for s in em["sources"]:
        path = s.get("path", "").replace("\\", "/")
        present = by_path.get(path)
        status = (
            "same-file-bytes"
            if present and present["sha256"] == s.get("file_sha256")
            else ("changed-file" if present else "missing-in-snapshot")
        )
        item = {k: v for k, v in s.items() if k != "excerpt"}
        item.update(
            currentness=status,
            current_sha256=present["sha256"] if present else None,
            historical_source=True,
            behavior_revalidated=False,
        )
        evidence.append(item)
        emap[item["id"]] = item
    nodes = []
    system_ids = set()
    file_layers = collections.defaultdict(collections.Counter)
    for source in raw["nodes"]:
        n = dict(source)
        system_ids.add(n["id"])
        n["kind"] = "system"
        n["historical_status"] = n.pop("status", "unknown")
        refs = [emap[r] for r in n.get("evidence_ids", []) if r in emap]
        states = collections.Counter(r["currentness"] for r in refs)
        n["currentness"] = (
            "same-file-bytes"
            if refs and states["same-file-bytes"] == len(refs)
            else (
                "unresolved"
                if not refs or states["missing-in-snapshot"]
                else "changed-file"
            )
        )
        n["evidence_level"] = "source-supported" if refs else "declared"
        n["evidence_scope"] = (
            "historical semantic model; byte currentness checked; behavior not revalidated"
        )
        n["source_currentness_counts"] = dict(states)
        n["note"] = "vault/Systems/" + slug(n["id"]) + ".md"
        n["runtime_observed"] = False
        n["certified"] = False
        n["repair_state"] = "not-reassessed"
        text = " ".join(
            str(n.get(k, "")) for k in ("title", "purpose", "state", "limit", "id")
        ).lower()
        n["resource_tags"] = [
            tag for tag, pat in RESOURCE_TERMS.items() if re.search(pat, text)
        ]
        for r in refs:
            file_layers[r["path"]][n["layer"]] += 1
        nodes.append(n)
    source_nodes = []
    for r in rows:
        path = r["path"]
        votes = file_layers[path]
        layer = (
            sorted(votes, key=lambda k: (-votes[k], k))[0]
            if votes
            else classify_path(path)
        )
        source_nodes.append(
            {
                "id": file_id(path),
                "title": path,
                "path": path,
                "layer": layer,
                "kind": "file",
                "sha256": r["sha256"],
                "bytes": r["bytes"],
                "evidence_level": "source-supported",
                "currentness": "snapshot-bytes",
                "purpose": "Inventoried file; imports are static references, not executed calls.",
                "resource_tags": [],
                "runtime_observed": False,
                "certified": False,
                "note": "vault/Data/Source_Inventory.md",
            }
        )
    edges = []
    for old in raw["edges"]:
        e = dict(old)
        kind = str(e.get("kind", "reference"))
        refs = [emap[i] for i in e.get("evidence_ids", []) if i in emap]
        e["evidence_level"] = "source-supported" if refs else "declared"
        e["currentness"] = (
            "same-file-bytes"
            if refs and all(r["currentness"] == "same-file-bytes" for r in refs)
            else "unresolved-or-changed"
        )
        e["layout_weight"] = (
            1.0
            if kind in {"data", "dependency", "execution", "persistence"}
            else (
                0.6
                if kind in {"control", "authority", "assurance", "observation"}
                else 0.2
            )
        )
        e["runtime_observed"] = False
        e["certified"] = False
        edges.append(e)
    imports, unresolved, parses = source_imports(images, set(by_path))
    source_links = []
    seen = set()
    for n in nodes:
        for ref in n.get("evidence_ids", []):
            s = emap.get(ref)
            if not s or s["path"] not in by_path:
                continue
            pair = (n["id"], s["path"])
            if pair in seen:
                continue
            seen.add(pair)
            source_links.append(
                {
                    "id": "A:" + digest(canonical(pair))[:24],
                    "source": n["id"],
                    "target": file_id(s["path"]),
                    "kind": "anchored-in",
                    "verb": "historical semantic source anchor",
                    "evidence_ids": [ref],
                    "evidence_level": "source-supported",
                    "currentness": s["currentness"],
                    "layout_weight": 0.2,
                }
            )
    all_nodes = nodes + source_nodes
    all_edges = edges + imports + source_links
    overlay_path = PACKAGE / "reference/current_findings.json"
    repair_overlay = (
        json.loads(overlay_path.read_text(encoding="utf-8"))
        if overlay_path.exists()
        else {"findings": []}
    )
    findings_by_path = collections.defaultdict(list)
    for f in repair_overlay["findings"]:
        label = {
            "id": f["id"],
            "title": f["title"],
            "disposition": f["current_disposition"],
            "recipes": f.get("recipe_ids", []),
        }
        for source in f.get("sources", []):
            findings_by_path[source["path"]].append(label)
    for n in all_nodes:
        paths = (
            [n["path"]]
            if n["kind"] == "file"
            else [emap[r]["path"] for r in n.get("evidence_ids", []) if r in emap]
        )
        relevant = {
            f["id"]: f for path in paths for f in findings_by_path.get(path, [])
        }
        n["repair_findings"] = [relevant[k] for k in sorted(relevant)]
    positions, centers = layout(all_nodes, raw["layers"])
    # Twelve bounded attraction passes on system nodes; anchors constrain movement.
    neighbors = collections.defaultdict(list)
    for e in edges:
        if e["source"] in positions and e["target"] in positions:
            neighbors[e["source"]].append((e["target"], e["layout_weight"]))
            neighbors[e["target"]].append((e["source"], e["layout_weight"]))
    origin = {k: list(v) for k, v in positions.items()}
    for _ in range(12):
        changed = {}
        for n in nodes:
            links = neighbors[n["id"]]
            if not links:
                continue
            total = sum(w for _, w in links)
            base = origin[n["id"]]
            changed[n["id"]] = [
                round(
                    0.90 * base[d]
                    + 0.10 * sum(positions[k][d] * w for k, w in links) / total,
                    4,
                )
                for d in range(3)
            ]
        positions.update(changed)
    for e in all_edges:
        if e["source"] in positions and e["target"] in positions:
            a, b = positions[e["source"]], positions[e["target"]]
            e["curve_control"] = [
                round((a[d] + b[d]) / 2 + (18 if d == 1 else 0), 4) for d in range(3)
            ]
    for n in all_nodes:
        n["position"] = positions[n["id"]]
    bc = brandes(sorted(system_ids), edges)
    degree = collections.Counter()
    indeg = collections.Counter()
    outdeg = collections.Counter()
    for e in edges:
        degree.update([e["source"], e["target"]])
        outdeg[e["source"]] += 1
        indeg[e["target"]] += 1
    for n in nodes:
        n["metrics"] = {
            "degree": degree[n["id"]],
            "in_degree": indeg[n["id"]],
            "out_degree": outdeg[n["id"]],
            "directed_betweenness": bc[n["id"]],
        }
        n["visual_size"] = round(3 + min(4, math.log1p(degree[n["id"]]) * 0.65), 3)
    journeys = []
    flowmap = {f["id"]: f for f in raw["flows"]}
    pairs = {(e["source"], e["target"]) for e in edges}
    for name, fid in JOURNEYS:
        f = flowmap[fid]
        steps = f["steps"]
        journeys.append(
            {
                "name": name,
                "flow_id": fid,
                "steps": steps,
                "description": f["description"],
                "limit": f.get("limit"),
                "segments": [
                    {
                        "source": a,
                        "target": b,
                        "relationship_present": (a, b) in pairs,
                        "evidence": "modeled-relationship"
                        if (a, b) in pairs
                        else "narrative-adjacency-only",
                    }
                    for a, b in zip(steps, steps[1:])
                ],
            }
        )
    views = [
        {
            "name": name,
            "runtime_proof_required": name == "Runtime Observed",
            "certification_required": name == "Certified",
        }
        for name in VIEWS
    ]
    cameras = [
        {
            "name": name,
            "yaw": round(-0.7 + i * 0.23, 3),
            "pitch": round(0.18 + (i % 3) * 0.12, 3),
            "zoom": 1.0,
        }
        for i, name in enumerate(CAMERAS)
    ]
    dangling = [
        e["id"]
        for e in all_edges
        if e["source"] not in positions or e["target"] not in positions
    ]
    flow_missing = [
        {"flow": f["id"], "step": s}
        for f in raw["flows"]
        for s in f["steps"]
        if s not in system_ids
    ]
    metrics = {
        "systems": len(nodes),
        "files": len(source_nodes),
        "nodes_total": len(all_nodes),
        "semantic_relationships": len(edges),
        "static_import_relationships": len(imports),
        "system_file_links": len(source_links),
        "edges_total": len(all_edges),
        "flows": len(raw["flows"]),
        "historical_findings": len(raw["findings"]),
        "evidence_anchors": len(evidence),
        "anchor_currentness": dict(
            collections.Counter(e["currentness"] for e in evidence)
        ),
        "source_bytes": sum(r["bytes"] for r in rows),
        "source_exclusions": len(excluded),
        "source_parse_errors": len(parses),
        "unresolved_import_records": len(unresolved),
        "system_isolates": sorted(i for i in system_ids if not degree[i]),
        "systems_without_incoming": sorted(i for i in system_ids if not indeg[i]),
        "systems_without_outgoing": sorted(i for i in system_ids if not outdeg[i]),
        "dangling_edges": dangling,
        "flow_missing_steps": flow_missing,
        "cross_layer_semantic_edges": sum(
            1
            for e in edges
            if e["source"] in system_ids
            and e["target"] in system_ids
            and next(n["layer"] for n in nodes if n["id"] == e["source"])
            != next(n["layer"] for n in nodes if n["id"] == e["target"])
        ),
        "runtime_observed_nodes": 0,
        "certified_nodes": 0,
        "betweenness_definition": "Exact directed unweighted Brandes on unique non-self semantic source-target pairs; normalized by (n-1)(n-2), all 1077 systems included; not an operational importance score.",
        "missing_consumer_caveat": "Zero incoming/outgoing edges is a structural model gap, not proof of a missing implementation or operational failure.",
    }
    graph = {
        "schema_version": SCHEMA,
        "metadata": {
            "basis": "supplied snapshot + preserved historical semantic IDs",
            "source_inventory_sha256": digest(canonical(rows)),
            "baseline_graph_sha256": digest(
                (reference / "graph_baseline_architecture.json").read_bytes()
            ),
            "layout_version": "px-lifecycle-seeded-attraction/1",
            "scope": "Refresh of file bytes/static imports and presentation, not a completed semantic re-audit of every claim or the live repository.",
            "runtime_observed": False,
            "certified": False,
            "historical_metadata": raw["metadata"],
            "concurrent_source_limit": "Per-file stable acquisition with metadata checks; not a cross-file atomic filesystem snapshot. Run with all source writers paused; same-metadata concurrent writes are not proven absent.",
        },
        "layers": raw["layers"],
        "nodes": all_nodes,
        "edges": all_edges,
        "flows": raw["flows"],
        "findings": raw["findings"],
        "views": views,
        "cameras": cameras,
        "journeys": journeys,
        "centers": centers,
        "metrics": metrics,
    }
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "data/complete_graph.json", graph)
    write_json(out / "data/source_inventory.json", rows)
    write_json(out / "data/evidence_currentness.json", evidence)
    write_json(out / "data/source_exclusions.json", excluded)
    write_json(out / "data/unresolved_imports.json", unresolved)
    write_json(out / "data/source_parse_errors.json", parses)
    write_json(out / "data/repair_overlay.json", repair_overlay)
    write_json(out / "data/layout.json", positions)
    write_json(out / "data/metrics.json", metrics)
    write_json(out / "data/views.json", views)
    write_json(out / "data/cameras.json", cameras)
    write_json(out / "data/journeys.json", journeys)
    write_json(out / "data/canonical_systems.json", nodes)
    write_json(out / "data/canonical_relationships.json", edges)
    write_json(out / "data/canonical_flows.json", raw["flows"])
    write_json(out / "data/canonical_findings.json", raw["findings"])
    for name, items in [("nodes", all_nodes), ("edges", all_edges)]:
        (out / "data" / f"{name}.jsonl").write_text(
            "".join(canonical(x).decode() + "\n" for x in items), encoding="utf-8"
        )
    # The combined node export is convenient for local presentation but exceeds
    # the governed 8 MiB single-source boundary. A fixed 16-way ID partition
    # provides the same complete denominator without trusting a self-declared
    # monolith hash or requiring stale-shard deletion when the graph changes.
    node_shards = [[] for _ in range(16)]
    for node in all_nodes:
        partition = int(hashlib.sha256(node["id"].encode("utf-8")).hexdigest()[0], 16)
        node_shards[partition].append(node)
    shard_manifest = []
    for partition, shard in enumerate(node_shards):
        relative = f"data/node_shards/nodes-{partition:02x}.jsonl"
        payload = "".join(canonical(node).decode() + "\n" for node in shard).encode(
            "utf-8"
        )
        if len(payload) > 4 * 1024**2:
            raise RuntimeError(f"node shard exceeds 4 MiB: {relative}")
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        shard_manifest.append(
            {
                "path": relative,
                "partition": f"{partition:x}",
                "records": len(shard),
                "bytes": len(payload),
                "sha256": digest(payload),
            }
        )
    write_json(
        out / "data/node_shards_manifest.json",
        {
            "schema_version": "px.atlas-node-shards/1",
            "partition": "first lowercase hexadecimal digit of SHA-256(canonical node ID)",
            "records": len(all_nodes),
            "shards": shard_manifest,
        },
    )
    browser = {k: v for k, v in graph.items() if k not in {"findings"}}
    # Avoid executable HTML interpolation; JSON is assigned by a static local JS resource.
    (out / "graph_data.js").write_text(
        "window.PX_GRAPH = "
        + json.dumps(browser, separators=(",", ":"), ensure_ascii=True).replace(
            "<", "\\u003c"
        )
        + ";\n",
        encoding="utf-8",
    )
    vault = out / "vault"

    def note(rel, body):
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    for n in nodes:
        refs = "\n".join(
            "- [[Evidence/" + slug(r) + "]] — " + emap[r]["currentness"]
            for r in n.get("evidence_ids", [])
            if r in emap
        )
        links = "\n".join(
            "- [[Systems/"
            + slug(e["target"])
            + "]] — "
            + e.get("verb", e["kind"])
            + " (`"
            + e["id"]
            + "`)"
            for e in edges
            if e["source"] == n["id"] and e["target"] in system_ids
        )
        body = f"---\ncanonical_id: {json.dumps(n['id'])}\nkind: system\nlayer: {n['layer']}\ncurrentness: {n['currentness']}\nruntime_observed: false\ncertified: false\n---\n# {n['title']}\n\n[[Layers/{n['layer']}]] · [[Views/Full_Architecture]]\n\n"
        for label, key in [
            ("Purpose", "purpose"),
            ("Historical source state", "state"),
            ("Limits and unknowns", "limit"),
            ("Historical suggested evolution", "future"),
        ]:
            body += f"## {label}\n\n{n.get(key, 'Not documented')}\n\n"
        body += (
            "## Evidence scope\n\nHistorical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.\n\n"
            + refs
            + "\n\n## Directed relationships\n\n"
            + (
                links
                or "No outgoing semantic relationship recorded. This is not proof there is no consumer."
            )
            + "\n"
        )
        note("Systems/" + slug(n["id"]) + ".md", body)
    for layer in raw["layers"]:
        body = (
            "# "
            + layer["title"]
            + "\n\n"
            + layer["description"]
            + "\n\n"
            + "\n".join(
                "- [[Systems/" + slug(n["id"]) + "]] — " + n["title"]
                for n in nodes
                if n["layer"] == layer["id"]
            )
            + "\n"
        )
        note("Layers/" + layer["id"] + ".md", body)
        note(
            "MOCs/" + layer["id"] + ".md",
            "# Map of content\n\n[[Layers/" + layer["id"] + "]]\n",
        )
    for s in evidence:
        note(
            "Evidence/" + slug(s["id"]) + ".md",
            f"# {s['id']}\n\nSource: `{s.get('path')}` lines {s.get('start')}–{s.get('end')}\n\nHistorical hash: `{s.get('file_sha256')}`\n\nCurrent hash: `{s.get('current_sha256')}`\n\nCurrentness: **{s['currentness']}**\n\nOriginal excerpt is preserved in the package reference/evidence-map. No runtime or certification proof is inferred.\n",
        )
    for f in raw["flows"]:
        note(
            "Paths/" + slug(f["id"]) + ".md",
            "# "
            + f["title"]
            + "\n\n"
            + f["description"]
            + "\n\n"
            + "\n".join(
                f"{i + 1}. [[Systems/{slug(s)}]]" for i, s in enumerate(f["steps"])
            )
            + "\n\nNarrative sequence is not automatically a proven call chain.\n\n"
            + f.get("limit", "")
            + "\n",
        )
    for f in raw["findings"]:
        refs = "\n".join(
            "- [[Evidence/" + slug(s) + "]]"
            for s in f.get("evidence_ids", [])
            if s in emap
        )
        note(
            "Findings/" + slug(f["id"]) + ".md",
            "# "
            + f["title"]
            + "\n\n**Historical finding; current closure not revalidated.**\n\n"
            + f.get("body", "")
            + "\n\n"
            + refs
            + "\n",
        )
    for v in VIEWS:
        note(
            "Views/" + slug(v) + ".md",
            "# "
            + v
            + "\n\nOpen the companion viewer and select this preset. Runtime Observed and Certified remain empty without scoped current proof. Native Obsidian global/local navigation requires local app validation.\n",
        )
    note(
        "Data/Source_Inventory.md",
        "# Complete accepted source inventory\n\nScope, hashes and exclusions: `../../data/source_inventory.json`, `../../data/source_exclusions.json`.\n\n"
        + "\n".join("- `" + r["path"] + "` — `" + r["sha256"] + "`" for r in rows)
        + "\n",
    )
    note(
        "README.md",
        f"# Pacify-X architecture vault\n\n{len(nodes)} canonical system notes; historical IDs preserved. Start at [[Views/Full_Architecture]] or the layer maps.\n\n**Not a certification.** Imported historical findings are not automatically reopened or closed. Source currentness is checked separately.\n\n"
        + "\n".join("- [[Layers/" + layer["id"] + "]]" for layer in raw["layers"])
        + "\n",
    )
    write_json(
        vault / ".obsidian/app.json",
        {"showLineNumber": True, "readableLineLength": True},
    )
    write_json(
        vault / ".obsidian/graph.json",
        {
            "collapse-filter": False,
            "search": 'path:"Systems"',
            "showTags": False,
            "showAttachments": False,
            "hideUnresolved": True,
            "showOrphans": True,
            "localJumps": 1,
        },
    )
    # A package-local viewer template, no CDN or copied browser profile.
    for name in ("index.html", "viewer.js", "viewer.css"):
        template = PACKAGE / "tools/viewer_template" / name
        if template.exists():
            (out / name).write_bytes(template.read_bytes())
    if (out / "index.html").exists():
        html = (out / "index.html").read_text(encoding="utf-8")
        html = html.replace(
            '<link rel="stylesheet" href="viewer.css">',
            "<style>" + (out / "viewer.css").read_text(encoding="utf-8") + "</style>",
        )
        for script in ("graph_data.js", "viewer.js"):
            html = html.replace(
                '<script src="' + script + '"></script>',
                "<script>"
                + (out / script)
                .read_text(encoding="utf-8")
                .replace("</script", "<\\/script")
                + "</script>",
            )
        (out / "ATLAS_OFFLINE.html").write_text(html, encoding="utf-8")
    write_json(
        out / "data/build_measurements.json",
        {
            "wall_seconds": round(time.monotonic() - started, 3),
            "file_bytes_read": sum(r["bytes"] for r in rows),
            "python_platform": os.name,
            "peak_memory": "not measured",
            "source_snapshot_atomic": False,
        },
    )
    if dangling or flow_missing or parses:
        print("ATLAS REVIEW REQUIRED: see metrics/parses; no missing data hidden")
    print(json.dumps(metrics, indent=2))
    return graph


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--reference", type=Path, default=PACKAGE / "reference")
    ap.add_argument("--max-files", type=int, default=100000)
    ap.add_argument("--max-bytes", type=int, default=2 * 1024**3)
    ap.add_argument(
        "--allow-repo-output",
        action="store_true",
        help="update the canonical docs/architecture tree, which is excluded from source inventory",
    )
    a = ap.parse_args()
    if a.max_files <= 0 or a.max_bytes <= 0:
        ap.error("bounds must be positive")
    try:
        build(a.repo, a.out, a.reference, a.max_files, a.max_bytes, a.allow_repo_output)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as e:
        ap.exit(3, f"REFUSED: {e}\n")


if __name__ == "__main__":
    main()
