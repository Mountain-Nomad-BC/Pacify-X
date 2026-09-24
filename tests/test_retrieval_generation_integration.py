from __future__ import annotations
import pytest
from runtime.retrieval import RetrievalSource, retrieve
from runtime.semantic_index import build_retrieval_generation_binding, validate_retrieval_generation_binding
from runtime.project_map_retrieval import query_project_map
from runtime.project_intelligence import build_project_map

G='a'*64

def test_cross_generation_dense_fusion_is_denied():
    a=RetrievalSource('a','A','query',('public',),'x',dense_score=.8,retrieval_generation_id='a'*64)
    b=RetrievalSource('b','B','query',('public',),'x',dense_score=.9,retrieval_generation_id='b'*64)
    with pytest.raises(ValueError,match='multiple generations'): retrieve('query',[a,b],identity_scope=())

def test_exact_identifier_survives_tiny_context_budget():
    s=RetrievalSource('EXACT-123','Exact','x'*100,('public',),'x')
    d=retrieve('nothing',[s],identity_scope=(),exact_source_ids=['EXACT-123'],max_context_bytes=1)
    assert d.hits[0].source_id=='EXACT-123' and d.hits[0].exact_identifier is True and d.context_bytes<=1

def test_generation_aware_dense_evidence_must_match_requested_generation():
    s=RetrievalSource('a','A','query',('public',),'x',dense_score=.8,retrieval_generation_id='b'*64)
    with pytest.raises(ValueError,match='does not match'): retrieve('query',[s],identity_scope=(),retrieval_generation_id=G)

def test_semantic_binding_is_external_to_canonical_index_bytes():
    idx={'revision':'c'*64,'records':[]}
    b=build_retrieval_generation_binding(idx,retrieval_generation_id=G,embedding_revision='d'*64)
    assert idx=={'revision':'c'*64,'records':[]}
    assert validate_retrieval_generation_binding(idx,b,expected_generation_id=G)['valid'] is True
    assert validate_retrieval_generation_binding(idx,b,expected_generation_id='e'*64)['valid'] is False

def test_project_map_carries_generation_and_rejects_mixing(tmp_path):
    (tmp_path/'a.py').write_text('def health_check():\n    return "ok"\n')
    build_project_map(tmp_path)
    r=query_project_map(tmp_path,'health check',retrieval_generation_id=G,evidence_generation_ids=[G])
    assert r['retrieval_generation_id']==G
    with pytest.raises(ValueError,match='crosses retrieval generations'):
        query_project_map(tmp_path,'health check',retrieval_generation_id=G,evidence_generation_ids=['b'*64])

def test_single_dense_generation_is_inferred_into_decision():
    s=RetrievalSource('a','A','query',('public',),'x',dense_score=.8,retrieval_generation_id=G)
    d=retrieve('query',[s],identity_scope=())
    assert d.retrieval_generation_id==G and d.hits[0].retrieval_generation_id==G


def test_rerank_scores_cannot_name_hidden_or_unknown_sources():
    s=RetrievalSource('a','A','query',('public',),'x')
    with pytest.raises(ValueError,match='visible retrieval sources'):
        retrieve('query',[s],identity_scope=(),rerank_scores={'b':0.9})


def test_benchmark_reducer_is_deterministic_and_sorted():
    from scripts.benchmark_retrieval_pipeline import reduce_cases
    base={'schema_version':'px.retrieval-benchmark-cases/1.0','generation_id':G,
          'readiness':{k:True for k in ('source_manifest_ok','provenance_ok','lexical_ready','vector_ready','graph_ready','calibration_ready')},
          'high_severity_findings':0}
    cases=[
      {'id':'b','lexical_recall':.8,'dense_recall':.9,'fused_recall':1.0,'latency_ms':120,'exact_identifier_pass':True},
      {'id':'a','lexical_recall':.7,'dense_recall':.95,'fused_recall':.96,'latency_ms':80,'exact_identifier_pass':True},
    ]
    one=reduce_cases({**base,'cases':cases}); two=reduce_cases({**base,'cases':list(reversed(cases))})
    assert one==two and one['metrics']['golden_recall']==pytest.approx(.98)


def test_benchmark_reducer_rejects_nonfinite_metrics():
    from scripts.benchmark_retrieval_pipeline import reduce_cases
    payload={'schema_version':'px.retrieval-benchmark-cases/1.0','generation_id':G,
             'readiness':{k:True for k in ('source_manifest_ok','provenance_ok','lexical_ready','vector_ready','graph_ready','calibration_ready')},
             'cases':[{'id':'a','lexical_recall':float('nan'),'dense_recall':1.0,'fused_recall':1.0,'latency_ms':1,'exact_identifier_pass':True}]}
    with pytest.raises(ValueError): reduce_cases(payload)
