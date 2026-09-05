#!/usr/bin/env python3
"""CLI adapter for the canonical Pacify-X hybrid retrieval owner."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


try:
    from engineering_bootstrap.retrieval import RetrievalSource, retrieve
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[4]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from runtime.retrieval import RetrievalSource, retrieve  # noqa: E402


def _optional_score(record: dict[str, object], *names: str) -> float | None:
    for name in names:
        if name in record and record[name] is not None:
            return float(record[name])
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus")
    parser.add_argument("query")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--scope", action="append", default=[])
    args = parser.parse_args()
    payload = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("corpus must be a JSON list")
    sources = []
    for raw in payload:
        if not isinstance(raw, dict) or not str(raw.get("id", "")).strip():
            raise ValueError("each corpus record requires an id")
        source_id = str(raw["id"])
        sources.append(
            RetrievalSource(
                source_id=source_id,
                title=str(raw.get("title", source_id)),
                text=str(raw.get("text", "")),
                visibility=tuple(map(str, raw.get("visibility", ("public",)))),
                lineage=str(raw.get("lineage", f"corpus:{source_id}")),
                kind=str(raw.get("kind", "document")),
                links=tuple(map(str, raw.get("links", ()))),
                metadata=dict(raw.get("metadata", {})),
                structured=dict(raw.get("structured", {})),
                dense_score=_optional_score(raw, "dense_score", "vector_score"),
                graph_score=_optional_score(raw, "graph_score"),
                freshness=_optional_score(raw, "freshness"),
                trust=_optional_score(raw, "trust"),
                source_revision=(
                    str(raw["revision"]) if raw.get("revision") is not None else None
                ),
            )
        )
    decision = retrieve(
        args.query,
        sources,
        identity_scope=tuple(args.scope),
        max_results=args.k,
    )
    print(json.dumps(asdict(decision), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
