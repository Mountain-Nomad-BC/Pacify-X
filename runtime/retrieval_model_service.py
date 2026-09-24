"""Subordinate embedding/reranker service contracts.

The service validates exact model revisions and bounded payloads.  It has no
retrieval-ranking or model-load authority of its own.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class RetrievalModelPolicy:
    embedding_model_id: str
    embedding_revision_policy: str
    normalization: str
    dimensions: int
    embedding_batch_limit: int
    input_bytes_limit: int
    timeout_seconds: float
    reranker_enabled: bool
    reranker_model_id: str | None
    reranker_revision_policy: str | None
    reranker_candidate_limit: int
    degraded_lexical_allowed: bool


def load_retrieval_model_policy(path: Path) -> RetrievalModelPolicy:
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != "px.retrieval-policy/1.0":
        raise ValueError("unsupported retrieval policy schema")
    invariants=set(data.get("authority_invariants", ()))
    required={"retrieval.py_is_canonical_owner","model_service_has_no_promotion_authority","cross_generation_dense_fusion_denied"}
    if not required.issubset(invariants):
        raise ValueError("retrieval policy weakens required authority invariants")
    emb=data.get("embedding"); rr=data.get("reranker"); limits=data.get("limits"); degraded=data.get("degraded_modes")
    if not all(type(x) is dict for x in (emb,rr,limits,degraded)):
        raise ValueError("retrieval policy sections are invalid")
    if type(rr.get("enabled")) is not bool or type(degraded.get("lexical_only_allowed")) is not bool:
        raise ValueError("retrieval policy booleans must be literal booleans")
    try:
        policy=RetrievalModelPolicy(
            str(emb.get("model_id","")), str(emb.get("revision_policy","")), str(emb.get("normalization","")),
            int(emb.get("dimensions",0)), int(limits.get("embedding_batch",0)), int(limits.get("input_bytes",0)),
            float(limits.get("timeout_seconds",0)), rr["enabled"],
            str(rr.get("model_id")) if rr.get("model_id") is not None else None,
            str(rr.get("revision_policy")) if rr.get("revision_policy") is not None else None,
            int(limits.get("rerank_candidates",0)), degraded["lexical_only_allowed"],
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("retrieval policy numeric limits are invalid") from error
    if not policy.embedding_model_id or policy.embedding_revision_policy != "exact_sha256_at_admission" or policy.normalization != "l2":
        raise ValueError("embedding identity/normalization policy is invalid")
    if not 1 <= policy.dimensions <= 131072 or not 1 <= policy.embedding_batch_limit <= 1024 or not 1 <= policy.input_bytes_limit <= 8*1024*1024:
        raise ValueError("retrieval policy limits are invalid")
    if not math.isfinite(policy.timeout_seconds) or not 0 < policy.timeout_seconds <= 120 or not 1 <= policy.reranker_candidate_limit <= 1000:
        raise ValueError("retrieval policy timeout/candidate bounds are invalid")
    if policy.reranker_enabled and (not policy.reranker_model_id or policy.reranker_revision_policy != "exact_sha256_at_admission"):
        raise ValueError("reranker exact identity policy is required")
    return policy


class RetrievalModelService:
    def __init__(self, policy: RetrievalModelPolicy, request: Callable[[str, Mapping[str, object], float], object]) -> None:
        self.policy=policy; self.request=request

    def _texts(self, texts: Sequence[str], *, maximum: int) -> tuple[str,...]:
        if type(texts) not in (list,tuple) or not 1 <= len(texts) <= maximum:
            raise ValueError("retrieval model request batch is empty or over budget")
        result=[]; total=0
        for text in texts:
            if type(text) is not str or not text:
                raise ValueError("retrieval model inputs must be nonempty text")
            total += len(text.encode("utf-8"))
            if total > self.policy.input_bytes_limit:
                raise ValueError("retrieval model input byte budget exceeded")
            result.append(text)
        return tuple(result)

    @staticmethod
    def _revision(value: object, name: str) -> str:
        if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"{name} must be an exact lowercase SHA-256 revision")
        return value

    def embed(self, texts: Sequence[str], *, expected_revision: str) -> tuple[tuple[float,...], ...]:
        expected=self._revision(expected_revision,"expected embedding revision")
        batch=self._texts(texts, maximum=self.policy.embedding_batch_limit)
        raw=self.request("embedding", {"model_id":self.policy.embedding_model_id,"texts":list(batch)}, self.policy.timeout_seconds)
        if type(raw) is not dict or raw.get("model_id") != self.policy.embedding_model_id or self._revision(raw.get("revision"),"embedding revision") != expected:
            raise ValueError("embedding response identity mismatch")
        if raw.get("normalization") != "l2" or raw.get("dimensions") != self.policy.dimensions:
            raise ValueError("embedding response shape/normalization mismatch")
        vectors=raw.get("vectors")
        if type(vectors) is not list or len(vectors) != len(batch):
            raise ValueError("embedding response batch mismatch")
        out=[]
        for row in vectors:
            if type(row) is not list or len(row) != self.policy.dimensions:
                raise ValueError("embedding vector dimension mismatch")
            values=[]
            for value in row:
                if type(value) not in (int,float) or type(value) is bool or not math.isfinite(float(value)):
                    raise ValueError("embedding vector contains non-finite data")
                values.append(float(value))
            norm=math.sqrt(sum(v*v for v in values))
            if not math.isclose(norm,1.0,rel_tol=1e-4,abs_tol=1e-4):
                raise ValueError("embedding vector violates l2 normalization")
            out.append(tuple(values))
        return tuple(out)

    def rerank(self, query: str, documents: Sequence[str], *, expected_revision: str, limit: int) -> tuple[tuple[int,float], ...]:
        if not self.policy.reranker_enabled:
            raise RuntimeError("reranker is disabled by policy")
        expected=self._revision(expected_revision,"expected reranker revision")
        if type(query) is not str or not query:
            raise ValueError("reranker query must be nonempty")
        docs=self._texts(documents, maximum=self.policy.reranker_candidate_limit)
        if type(limit) is not int or not 1 <= limit <= min(len(docs), self.policy.reranker_candidate_limit):
            raise ValueError("rerank limit is invalid")
        raw=self.request("rerank", {"model_id":self.policy.reranker_model_id,"query":query,"documents":list(docs),"limit":limit}, self.policy.timeout_seconds)
        if type(raw) is not dict or raw.get("model_id") != self.policy.reranker_model_id or self._revision(raw.get("revision"),"reranker revision") != expected:
            raise ValueError("reranker response identity mismatch")
        rows=raw.get("ranking")
        if type(rows) is not list or len(rows) > limit:
            raise ValueError("reranker response is invalid or over budget")
        seen=set(); out=[]
        for row in rows:
            if type(row) is not dict or type(row.get("index")) is not int or row["index"] < 0 or row["index"] >= len(docs) or row["index"] in seen:
                raise ValueError("reranker indices must be unique and in bounds")
            score=row.get("score")
            if type(score) not in (int,float) or type(score) is bool or not math.isfinite(float(score)) or not 0 <= float(score) <= 1:
                raise ValueError("reranker score must be finite in [0,1]")
            seen.add(row["index"]); out.append((row["index"],float(score)))
        return tuple(out)
