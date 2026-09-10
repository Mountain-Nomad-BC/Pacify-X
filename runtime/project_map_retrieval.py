"""Fast metadata-first retrieval and bounded hydration plans for project maps."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import math
from pathlib import Path
import re
from typing import Any, Iterable

from .json_io import bounded_json_text, bounded_strings, load_json_object
from .project_intelligence import QUERY_ALIASES, SCHEMA_VERSION, _map_dir

MAX_INDEX_BYTES = 32 * 1024 * 1024
MAX_DOCUMENTS = 50_000
MAX_INDEX_POSTINGS = 500_000
MAX_INDEX_RELATIONS = 200_000

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_./:-]{1,80}")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "what",
    "where",
    "which",
    "with",
}


@lru_cache(maxsize=4)
def _load_json_cached(
    path_text: str, modified_ns: int, size_bytes: int
) -> dict[str, Any]:
    """Bound acquisition and validation per observed stat cache key.

    A matching stat key is a cache hint, not authenticated content freshness.
    """
    del modified_ns, size_bytes
    path = Path(path_text)
    is_index = path.name == "retrieval-index.json"
    payload = load_json_object(path, max_bytes=MAX_INDEX_BYTES if is_index else 1024 * 1024)
    if is_index:
        _validate_index(payload)
    return payload


def _load_map_json(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return _load_json_cached(path.as_posix(), stat.st_mtime_ns, stat.st_size)


def _integer(value: Any, name: str, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}")


def _text(value: Any, name: str, limit: int, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or len(value) > limit or len(value.encode("utf-8")) > limit:
        raise ValueError(f"{name} must be text bounded to {limit} UTF-8 bytes")


def _validate_index(index: dict[str, Any]) -> None:
    """Validate the complete acquired metadata and arithmetic denominator once."""
    if (index.get("schema_version") != SCHEMA_VERSION
            or index.get("algorithm") != "bm25_metadata_plus_relation_expansion"):
        raise ValueError("unsupported retrieval-index schema or algorithm")
    docs = index.get("documents")
    lengths = index.get("document_lengths")
    count = index.get("document_count")
    _integer(count, "document_count", 0, MAX_DOCUMENTS)
    if type(docs) is not list or len(docs) != count:
        raise ValueError("retrieval documents do not match document_count")
    if type(lengths) is not list or len(lengths) != count:
        raise ValueError("retrieval document lengths require complete coverage")
    identifiers = set()
    relations_total = 0
    for doc, length in zip(docs, lengths):
        _integer(length, "document length", 0, 1_000_000)
        if type(doc) is not dict:
            raise ValueError("retrieval document must be an object")
        for field, limit in (("id", 256), ("kind", 64), ("title", 4096),
                             ("role", 256), ("summary", 65536)):
            _text(doc.get(field), field, limit)
        if not doc["id"] or doc["id"] in identifiers:
            raise ValueError("retrieval document IDs must be nonempty and unique")
        identifiers.add(doc["id"])
        if doc["kind"] not in {"file", "symbol", "route", "service", "contract",
                               "configuration", "integration", "risk"}:
            raise ValueError("unsupported retrieval document kind")
        _text(doc.get("language"), "language", 256, nullable=True)
        _text(doc.get("path"), "path", 4096, nullable=True)
        path = doc.get("path")
        if path and (path.startswith("/") or "\\" in path or ":" in path
                     or any(part in ("", ".", "..") for part in path.split("/"))):
            raise ValueError("retrieval source path must be portable and relative")
        for field in ("line_start", "line_end"):
            if doc.get(field) is not None:
                _integer(doc[field], field, 0, 2_147_483_647)
        if (doc.get("line_start") and doc.get("line_end")
                and doc["line_end"] < doc["line_start"]):
            raise ValueError("retrieval source range is inverted")
        relations = doc.get("relations")
        if type(relations) is not list or len(relations) > 10_000:
            raise ValueError("retrieval relations require a bounded list")
        relations_total += len(relations)
        if relations_total > MAX_INDEX_RELATIONS:
            raise ValueError("retrieval index relation budget exceeded")
        previous = None
        for identifier in relations:
            _text(identifier, "relation ID", 256)
            if not identifier or previous is not None and identifier <= previous:
                raise ValueError("retrieval relations must have unique sorted IDs")
            previous = identifier
    for doc in docs:
        if any(identifier not in identifiers for identifier in doc["relations"]):
            raise ValueError("retrieval relation target is not indexed")
    average = index.get("average_document_length")
    expected_average = sum(lengths) / count if count else 0.0
    if (type(average) not in (int, float) or not math.isfinite(average)
            or not math.isclose(average, expected_average, rel_tol=1e-12, abs_tol=1e-12)):
        raise ValueError("retrieval average document length is inconsistent")
    postings = index.get("postings")
    idf = index.get("idf")
    if type(postings) is not dict or type(idf) is not dict or postings.keys() != idf.keys():
        raise ValueError("retrieval postings and IDF must have the same token denominator")
    totals = [0] * count
    posting_count = 0
    for token, rows in postings.items():
        _text(token, "posting token", 256)
        if not token or type(rows) is not list or not 1 <= len(rows) <= count:
            raise ValueError("retrieval posting list must be nonempty and bounded by documents")
        posting_count += len(rows)
        if posting_count > MAX_INDEX_POSTINGS:
            raise ValueError("retrieval index posting budget exceeded")
        previous_index = -1
        for row in rows:
            if type(row) is not list or len(row) != 2:
                raise ValueError("retrieval posting requires document index and frequency")
            doc_index, frequency = row
            _integer(doc_index, "posting document index", 0, count - 1)
            _integer(frequency, "posting frequency", 1, 1_000_000)
            if doc_index <= previous_index:
                raise ValueError("retrieval postings require unique sorted document indices")
            previous_index = doc_index
            totals[doc_index] += frequency
        value = idf[token]
        expected = math.log(1 + (count - len(rows) + 0.5) / (len(rows) + 0.5))
        if (type(value) not in (int, float) or not math.isfinite(value)
                or not math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-12)):
            raise ValueError("retrieval IDF does not match its posting denominator")
    if totals != lengths:
        raise ValueError("retrieval posting frequencies do not match document lengths")


def _tokens(value: str) -> list[str]:
    text = value.casefold().replace("_", "-")
    tokens = TOKEN_RE.findall(text)
    expanded = list(tokens)
    for token in tokens:
        if "/" in token:
            expanded.extend(part for part in token.split("/") if len(part) > 1)
        if "-" in token:
            expanded.extend(part for part in token.split("-") if len(part) > 1)
        if "." in token:
            expanded.extend(part for part in token.split(".") if len(part) > 1)
        expanded.extend(QUERY_ALIASES.get(token, ()))
    seen: set[str] = set()
    return [
        token
        for token in expanded
        if token not in STOP_WORDS and not (token in seen or seen.add(token))
    ]


def _matches_filter(
    doc: dict[str, Any],
    *,
    kinds: set[str],
    languages: set[str],
    path_prefix: str | None,
) -> bool:
    if kinds and str(doc.get("kind")) not in kinds:
        return False
    if languages and str(doc.get("language")) not in languages:
        return False
    if path_prefix and not str(doc.get("path") or "").casefold().startswith(
        path_prefix.casefold()
    ):
        return False
    return True


def query_project_map(
    project_or_map: Path,
    query: str,
    *,
    top_k: int = 10,
    kinds: Iterable[str] = (),
    languages: Iterable[str] = (),
    path_prefix: str | None = None,
    relation_depth: int = 1,
    max_hydration_files: int = 8,
    context_lines: int = 25,
    max_relation_nodes: int = 1000,
    max_relation_edges: int = 2500,
    max_query_postings: int = 100_000,
    max_hydration_lines: int = 2000,
    max_result_bytes: int = 262_144,
) -> dict[str, object]:
    _text(query, "query", 65536)
    if not query.strip():
        raise ValueError("query must be nonempty")
    for value, name, low, high in (
        (top_k, "top_k", 1, 100), (relation_depth, "relation_depth", 0, 3),
        (max_hydration_files, "max_hydration_files", 0, 100),
        (context_lines, "context_lines", 0, 500),
        (max_relation_nodes, "max_relation_nodes", 1, 10_000),
        (max_relation_edges, "max_relation_edges", 1, 20_000),
        (max_query_postings, "max_query_postings", 1, MAX_INDEX_POSTINGS),
        (max_hydration_lines, "max_hydration_lines", 1, 20_000),
        (max_result_bytes, "max_result_bytes", 1, 1024 * 1024),
    ):
        _integer(value, name, low, high)
    if max_relation_nodes < top_k:
        raise ValueError("relation node budget must accommodate top_k seeds")
    _text(path_prefix, "path_prefix", 4096, nullable=True)
    kind_filter = set(bounded_strings(kinds, max_items=64, max_item_bytes=256))
    language_filter = set(bounded_strings(languages, max_items=64, max_item_bytes=256))
    query_tokens = _tokens(query)
    if len(query_tokens) > 128:
        raise ValueError("query expanded token budget exceeded")
    map_dir = _map_dir(project_or_map)
    index = _load_map_json(map_dir / "retrieval-index.json")
    manifest = _load_map_json(map_dir / "project-manifest.json")
    _text(manifest.get("map_revision"), "map_revision", 256)
    if not manifest["map_revision"]:
        raise ValueError("map_revision must be nonempty")
    docs: list[dict[str, Any]] = index["documents"]
    lengths: list[int] = index["document_lengths"]
    avgdl = float(index["average_document_length"] or 1.0)
    postings: dict[str, list[list[int]]] = index["postings"]
    idf: dict[str, float] = index["idf"]
    query_postings = sum(len(postings.get(token, ())) for token in query_tokens)
    if query_postings > max_query_postings:
        raise ValueError("query posting computation budget exceeded")
    scores: dict[int, float] = defaultdict(float)
    reasons: dict[int, list[str]] = defaultdict(list)
    k1 = 1.5
    b = 0.75
    for token in query_tokens:
        for doc_index, frequency in postings.get(token, ()):  # type: ignore[misc]
            doc = docs[doc_index]
            if not _matches_filter(
                doc,
                kinds=kind_filter,
                languages=language_filter,
                path_prefix=path_prefix,
            ):
                continue
            dl = lengths[doc_index]
            tf = float(frequency)
            contribution = (
                float(idf.get(token, 0.0))
                * (tf * (k1 + 1))
                / (tf + k1 * (1 - b + b * dl / avgdl))
            )
            title = str(doc.get("title", "")).casefold()
            path = str(doc.get("path", "")).casefold()
            if token in title:
                contribution *= 1.9
                reasons[doc_index].append(f"title:{token}")
            elif token in path:
                contribution *= 1.35
                reasons[doc_index].append(f"path:{token}")
            else:
                reasons[doc_index].append(f"metadata:{token}")
            scores[doc_index] += contribution
    phrase = query.casefold().strip()
    for doc_index in list(scores):
        doc = docs[doc_index]
        searchable = " ".join(
            str(doc.get(field, "")) for field in ("title", "path", "summary")
        ).casefold()
        if phrase and phrase in searchable:
            scores[doc_index] += 4.0
            reasons[doc_index].append("exact_phrase")
    ranked = sorted(
        scores.items(),
        key=lambda item: (
            -item[1],
            str(docs[item[0]].get("kind")),
            str(docs[item[0]].get("title")),
            docs[item[0]]["id"],
        ),
    )
    by_id = {str(doc.get("id")): index for index, doc in enumerate(docs)}
    expanded_scores = dict(ranked)
    frontier = [index for index, _ in ranked[:top_k]]
    visited = set(frontier)
    examined_edges = 0
    expansion_truncated = False
    for depth in range(relation_depth):
        next_frontier: list[int] = []
        decay = 0.3 / (depth + 1)
        for source_index in frontier:
            source_score = expanded_scores.get(
                source_index, scores.get(source_index, 0.0)
            )
            for relation in docs[source_index].get("relations", ()):  # type: ignore[union-attr]
                if examined_edges >= max_relation_edges:
                    expansion_truncated = True
                    break
                examined_edges += 1
                target_index = by_id.get(str(relation))
                if target_index is None or target_index in visited:
                    continue
                target = docs[target_index]
                if not _matches_filter(
                    target,
                    kinds=kind_filter,
                    languages=language_filter,
                    path_prefix=path_prefix,
                ):
                    continue
                if len(visited) >= max_relation_nodes:
                    expansion_truncated = True
                    break
                expanded_scores[target_index] = max(
                    expanded_scores.get(target_index, 0.0), source_score * decay
                )
                reasons[target_index].append(
                    f"related_to:{docs[source_index].get('id')}"
                )
                visited.add(target_index)
                next_frontier.append(target_index)
            if expansion_truncated:
                break
        if expansion_truncated:
            break
        frontier = next_frontier
        if not frontier:
            break
    final = sorted(
        expanded_scores.items(),
        key=lambda item: (
            -item[1],
            str(docs[item[0]].get("kind")),
            str(docs[item[0]].get("title")),
            docs[item[0]]["id"],
        ),
    )[:top_k]
    hits = []
    for rank, (doc_index, score) in enumerate(final, 1):
        doc = docs[doc_index]
        hits.append(
            {
                "rank": rank,
                "score": round(score, 6),
                "id": doc.get("id"),
                "kind": doc.get("kind"),
                "title": doc.get("title"),
                "path": doc.get("path"),
                "line_start": doc.get("line_start"),
                "line_end": doc.get("line_end"),
                "summary": doc.get("summary"),
                "reasons": sorted(set(reasons.get(doc_index, ()))),
                "relations": list(doc["relations"]),
            }
        )
    hydration: dict[str, dict[str, object]] = {}
    hydration_truncated = False
    for hit in hits:
        path = hit.get("path")
        if not path:
            continue
        if len(hydration) >= max_hydration_files and path not in hydration:
            hydration_truncated = True
            continue
        start = int(hit.get("line_start") or 1)
        end = int(hit.get("line_end") or start)
        requested_start = max(1, start - context_lines)
        requested_end = max(requested_start, end + context_lines)
        record = hydration.setdefault(
            str(path),
            {"path": path, "ranges": [], "reasons": [], "priority": hit["rank"]},
        )
        record["ranges"].append(
            {"start_line": requested_start, "end_line": requested_end}
        )  # type: ignore[union-attr]
        record["reasons"].append(f"{hit['kind']}:{hit['title']}")  # type: ignore[union-attr]
        record["priority"] = min(int(record["priority"]), int(hit["rank"]))
    hydration_plan = []
    remaining_lines = max_hydration_lines
    for record in sorted(
        hydration.values(), key=lambda item: (int(item["priority"]), str(item["path"]))
    ):
        merged = []
        for candidate in sorted(
            record["ranges"],
            key=lambda item: (int(item["start_line"]), int(item["end_line"])),
        ):  # type: ignore[arg-type]
            if (
                merged
                and int(candidate["start_line"]) <= int(merged[-1]["end_line"]) + 1
            ):
                merged[-1]["end_line"] = max(
                    int(merged[-1]["end_line"]), int(candidate["end_line"])
                )
            else:
                merged.append(dict(candidate))
        bounded_ranges = []
        for source_range in merged:
            count = source_range["end_line"] - source_range["start_line"] + 1
            accepted = min(count, remaining_lines)
            if accepted < count:
                hydration_truncated = True
            if accepted:
                bounded_ranges.append({"start_line": source_range["start_line"],
                                       "end_line": source_range["start_line"] + accepted - 1})
                remaining_lines -= accepted
        if not bounded_ranges:
            continue
        hydration_plan.append(
            {
                "path": record["path"],
                "priority": record["priority"],
                "ranges": bounded_ranges,
                "reasons": sorted(set(record["reasons"])),
            }
        )
    result = {
        "valid": bool(hits),
        "query": query,
        "tokens": query_tokens,
        "map_dir": map_dir.as_posix(),
        "map_revision": manifest.get("map_revision"),
        "index_document_count": len(docs),
        "hits": hits,
        "hydration_plan": hydration_plan,
        "hydration_truncated": hydration_truncated,
        "hydration_line_count": max_hydration_lines - remaining_lines,
        "scored_postings": query_postings,
        "relation_expansion": {"visited_nodes": len(visited), "examined_edges": examined_edges,
                               "truncated": expansion_truncated, "requested_depth": relation_depth},
        "loading_rule": "Load the retrieval records first, then only the listed source ranges. Expand relations or source scope only when current evidence is insufficient.",
        "unknown": None if hits else "No indexed project-map record matched the query.",
    }
    bounded_json_text(result, max_bytes=max_result_bytes)
    return result
