"""Fast metadata-first retrieval and bounded hydration plans for project maps."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .project_intelligence import QUERY_ALIASES, _map_dir

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
    """Load immutable promoted-map JSON once per observed file revision."""
    del modified_ns, size_bytes
    return json.loads(Path(path_text).read_text(encoding="utf-8"))


def _load_map_json(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return _load_json_cached(path.as_posix(), stat.st_mtime_ns, stat.st_size)


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
) -> dict[str, object]:
    if not query.strip():
        raise ValueError("query must be nonempty")
    if top_k < 1 or top_k > 100:
        raise ValueError("top_k must be between 1 and 100")
    if relation_depth < 0 or relation_depth > 3:
        raise ValueError("relation_depth must be between 0 and 3")
    map_dir = _map_dir(project_or_map)
    index = _load_map_json(map_dir / "retrieval-index.json")
    manifest = _load_map_json(map_dir / "project-manifest.json")
    docs: list[dict[str, Any]] = index.get("documents", [])
    lengths: list[int] = index.get("document_lengths", [])
    avgdl = float(index.get("average_document_length") or 1.0)
    postings: dict[str, list[list[int]]] = index.get("postings", {})
    idf: dict[str, float] = index.get("idf", {})
    query_tokens = _tokens(query)
    kind_filter = {str(value) for value in kinds}
    language_filter = {str(value) for value in languages}
    scores: dict[int, float] = defaultdict(float)
    reasons: dict[int, list[str]] = defaultdict(list)
    k1 = 1.5
    b = 0.75
    for token in query_tokens:
        for doc_index, frequency in postings.get(token, ()):  # type: ignore[misc]
            if doc_index >= len(docs):
                continue
            doc = docs[doc_index]
            if not _matches_filter(
                doc,
                kinds=kind_filter,
                languages=language_filter,
                path_prefix=path_prefix,
            ):
                continue
            dl = lengths[doc_index] if doc_index < len(lengths) else avgdl
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
        ),
    )
    by_id = {str(doc.get("id")): index for index, doc in enumerate(docs)}
    expanded_scores = dict(ranked)
    frontier = [index for index, _ in ranked[:top_k]]
    visited = set(frontier)
    for depth in range(relation_depth):
        next_frontier: list[int] = []
        decay = 0.3 / (depth + 1)
        for source_index in frontier:
            source_score = expanded_scores.get(
                source_index, scores.get(source_index, 0.0)
            )
            for relation in docs[source_index].get("relations", ()):  # type: ignore[union-attr]
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
                expanded_scores[target_index] = max(
                    expanded_scores.get(target_index, 0.0), source_score * decay
                )
                reasons[target_index].append(
                    f"related_to:{docs[source_index].get('id')}"
                )
                visited.add(target_index)
                next_frontier.append(target_index)
        frontier = next_frontier
    final = sorted(
        expanded_scores.items(),
        key=lambda item: (
            -item[1],
            str(docs[item[0]].get("kind")),
            str(docs[item[0]].get("title")),
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
                "relations": doc.get("relations", ()),
            }
        )
    hydration: dict[str, dict[str, object]] = {}
    for hit in hits:
        path = hit.get("path")
        if not path or len(hydration) >= max_hydration_files and path not in hydration:
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
                and int(candidate["start_line"]) <= int(merged[-1]["end_line"]) + 3
            ):
                merged[-1]["end_line"] = max(
                    int(merged[-1]["end_line"]), int(candidate["end_line"])
                )
            else:
                merged.append(dict(candidate))
        hydration_plan.append(
            {
                "path": record["path"],
                "priority": record["priority"],
                "ranges": merged,
                "reasons": sorted(set(record["reasons"])),
            }
        )
    return {
        "valid": bool(hits),
        "query": query,
        "tokens": query_tokens,
        "map_dir": map_dir.as_posix(),
        "map_revision": manifest.get("map_revision"),
        "index_document_count": len(docs),
        "hits": hits,
        "hydration_plan": hydration_plan,
        "loading_rule": "Load the retrieval records first, then only the listed source ranges. Expand relations or source scope only when current evidence is insufficient.",
        "unknown": None if hits else "No indexed project-map record matched the query.",
    }
