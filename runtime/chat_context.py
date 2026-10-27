"""On-demand chat retrieval through existing project/cognitive/NSAI owners.

Optional explicit personal-use materialization consumes native host approval and
maintains lock/lease/audit custody; ordinary retrieval remains read-only.
Only selected source records are hydrated. No external memory vault, model,
MCP server, build, install, promotion or formula execution is started here.
"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

from .archive_io import reject_path_links, portable_member_name
from .json_io import bounded_canonical_json_bytes, load_json_object


def retrieve_chat_context(engine_root, project_root, payload):
    reject_path_links(Path(engine_root)); reject_path_links(Path(project_root))
    engine_root, project_root = Path(engine_root).resolve(strict=True), Path(project_root).resolve(strict=True)
    query = payload.get("query")
    if type(query) is not str or not query.strip() or len(query.encode("utf-8")) > 4096:
        raise ValueError("chat retrieval query must be bounded nonempty text")
    max_bytes = payload.get("max_bytes", 65536)
    if type(max_bytes) is not int or not 4096 <= max_bytes <= 262144:
        raise ValueError("chat retrieval context budget must be 4096..262144 bytes")
    observed = datetime.now(timezone.utc).isoformat()
    refs, unavailable = [], []
    used = 0
    def add(kind, identity, label, source, content, *, provenance_sha256=None):
        nonlocal used
        if len(refs) >= 24: return
        if type(content) is not str: raise TypeError("source context must be text")
        if len(content.encode("utf-8")) > 16384: return
        raw = content.encode("utf-8")
        row = {"refId": "ctx-" + hashlib.sha256((kind + ":" + identity).encode()).hexdigest()[:32],
               "kind": kind, "label": str(label)[:500], "source": source,
               "content": content, "sha256": hashlib.sha256(raw).hexdigest(),
               "authority": "source-reference-no-execution", "freshAt": observed}
        cost = len(bounded_canonical_json_bytes(row, max_bytes=32768))
        if used + cost > max_bytes: return
        refs.append(row); used += cost
    try:
        from .project_map_retrieval import query_project_map
        result = query_project_map(project_root, query, top_k=6, max_hydration_files=0,
                                   relation_depth=0, max_result_bytes=65536)
        for hit in result.get("hits", ()):
            content = bounded_canonical_json_bytes({"source_owner": "runtime.project_map_retrieval",
                "map_revision": result.get("map_revision"), "hit": hit,
                "authority_granted": False}, max_bytes=16384).decode()
            add("project-evidence", str(hit["id"]), hit.get("title") or hit["id"], str(hit.get("path") or "project-map"), content)
    except (FileNotFoundError, OSError, KeyError, ValueError) as error:
        unavailable.append({"source": "project-map", "reason": type(error).__name__})
    try:
        from .cognitive_query import query_repository_index
        result = query_repository_index(engine_root, query, project_id=project_root.name, top_per_category=2)
        for category in ("knowledge", "skills", "operations", "workflows", "orchestrations"):
            for item in result.categories.get(category, ()):
                content = bounded_canonical_json_bytes({"source_owner": "runtime.cognitive_query",
                    "object_id": item.object_id, "revision": item.revision, "summary": item.summary,
                    "lifecycle": item.lifecycle, "evidence_refs": item.evidence_refs,
                    "hydrate_ref": item.hydrate_ref, "authority_granted": False}, max_bytes=16384).decode()
                add("cognitive-reference", item.object_id, item.object_id, "engine:cognitive-map", content)
    except (FileNotFoundError, OSError, KeyError, ValueError) as error:
        unavailable.append({"source": "cognitive-map", "reason": type(error).__name__})
    try:
        from .nsai_knowledge import load_nsai_object, stable_sha256
        library = engine_root / "knowledge/nsai"
        reject_path_links(library)
        index_path = library / "index.json"; reject_path_links(index_path)
        index = load_json_object(index_path, max_bytes=16 * 1024 * 1024)
        records = index.get("records")
        if (index.get("schema_version") != "px.nsai-index/1.0" or index.get("authority") != "derived_navigation_only"
                or type(records) is not list or len(records) > 10000 or index.get("object_count") != len(records)
                or index.get("library_sha256") != stable_sha256({k: v for k, v in index.items() if k != "library_sha256"})):
            raise ValueError("NSAI navigation index is not intact")
        terms = set(re.findall(r"[a-z0-9_]+", query.casefold()))
        ranked = []
        for row in records:
            if type(row) is not dict: raise ValueError("NSAI navigation row is invalid")
            tokens = set(re.findall(r"[a-z0-9_]+", " ".join(str(value) for value in
                (row.get("title"), row.get("object_id"), row.get("terms"), row.get("tags"))).casefold()))
            score = len(terms & tokens)
            if score: ranked.append((score, str(row["object_id"]), row))
        for _, identity, row in sorted(ranked, key=lambda item: (-item[0], item[1]))[:4]:
            relative = portable_member_name(row["path"], allow_directory=False)
            item = load_nsai_object(library / relative, library_root=library, contract_root=engine_root / "contracts")
            if item.sha256 != row["sha256"] or item.payload["object_id"] != identity:
                raise ValueError("NSAI source object changed after its navigation projection")
            content = bounded_canonical_json_bytes({"source_owner": "runtime.nsai_knowledge",
                "object_id": identity, "source_sha256": item.sha256, "object": dict(item.payload),
                "authority_granted": False}, max_bytes=16384).decode()
            add("nsai-source", identity, item.payload["title"], "engine:knowledge/nsai/" + relative, content)
    except (FileNotFoundError, OSError, KeyError, ValueError) as error:
        unavailable.append({"source": "nsai", "reason": type(error).__name__})
    personal = payload.get("personal_use_request")
    if personal is not None:
        # Failure is authoritative: never fall back to previously copied personal refs.
        if type(personal) is not dict or personal.get("operation") != "personal-use":
            raise ValueError("chat personal context requires explicit native personal-use request")
        bounded_canonical_json_bytes(personal, max_bytes=256 * 1024)
        from .personal_record_store import personal_record_request, STORE
        def materialize(snapshot):
            for record in snapshot["records"]:
                provenance = {"source_owner": "runtime.personal_record_store", "source_locator": STORE,
                    "source_generation": snapshot["generation"], "source_image_sha256": snapshot["source_image_sha256"],
                    "subject_id": personal["subject_id"], "purpose": snapshot["authorized_purpose"],
                    "record_id": record["record_id"], "copy_kind": "ephemeral-personal-context",
                    "authority_granted": False, "requires_current_native_use_before_provider_dispatch": True,
                    "content": record["content"]}
                content = bounded_canonical_json_bytes(provenance, max_bytes=16384).decode()
                add("personal-use-context", record["record_id"], "Approved personal context",
                    "personal-store:" + str(snapshot["generation"]) + ":" + str(snapshot["source_image_sha256"]), content)
        personal_record_request(project_root, personal, materialize_use=materialize)
    body = {"schema_version": "px.chat-context-retrieval/1.0", "query": query,
            "project_id": project_root.name, "refs": refs, "unavailable_sources": unavailable,
            "context_bytes": used, "max_bytes": max_bytes, "authority_granted": False}
    return {**body, "receipt_sha256": hashlib.sha256(bounded_canonical_json_bytes(body, max_bytes=524288)).hexdigest()}
