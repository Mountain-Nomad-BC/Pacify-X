from __future__ import annotations
from pathlib import Path
import pytest
from runtime.retrieval_model_service import load_retrieval_model_policy, RetrievalModelService
ROOT=Path(__file__).parents[1]

def policy(): return load_retrieval_model_policy(ROOT/'models/retrieval-policy.json')

def test_policy_is_strict_and_bounded():
    p=policy(); assert p.embedding_model_id=='qwen3-embedding-0.6b'; assert p.reranker_candidate_limit==8; assert p.normalization=='l2'

def test_embedding_requires_exact_revision_and_unit_vectors():
    p=policy(); rev='a'*64
    def call(kind,payload,timeout):
        assert kind=='embedding'; return {'model_id':p.embedding_model_id,'revision':rev,'normalization':'l2','dimensions':p.dimensions,'vectors':[[1.0]+[0.0]*(p.dimensions-1)]}
    s=RetrievalModelService(p,call); out=s.embed(['x'],expected_revision=rev); assert len(out[0])==p.dimensions
    with pytest.raises(ValueError,match='identity mismatch'): s.embed(['x'],expected_revision='b'*64)

def test_embedding_rejects_non_unit_vectors():
    p=policy(); rev='a'*64
    def call(*_): return {'model_id':p.embedding_model_id,'revision':rev,'normalization':'l2','dimensions':p.dimensions,'vectors':[[0.5]+[0.0]*(p.dimensions-1)]}
    with pytest.raises(ValueError,match='l2'): RetrievalModelService(p,call).embed(['x'],expected_revision=rev)

def test_reranker_is_bounded_and_indices_are_unique():
    p=policy(); rev='b'*64
    def call(kind,payload,timeout): return {'model_id':p.reranker_model_id,'revision':rev,'ranking':[{'index':1,'score':0.9},{'index':0,'score':0.7}]}
    s=RetrievalModelService(p,call); assert s.rerank('q',['a','b'],expected_revision=rev,limit=2)[0]==(1,0.9)
    with pytest.raises(ValueError,match='over budget'): s.rerank('q',['x']*9,expected_revision=rev,limit=1)

def test_policy_rejects_truthy_string_boolean(tmp_path: Path):
    import json
    raw=json.loads((ROOT/'models/retrieval-policy.json').read_text())
    raw['reranker']['enabled']='false'
    target=tmp_path/'policy.json'; target.write_text(json.dumps(raw))
    with pytest.raises(ValueError,match='literal booleans'):
        load_retrieval_model_policy(target)


def test_policy_rejects_missing_authority_invariant(tmp_path: Path):
    import json
    raw=json.loads((ROOT/'models/retrieval-policy.json').read_text())
    raw['authority_invariants'].remove('retrieval.py_is_canonical_owner')
    target=tmp_path/'policy.json'; target.write_text(json.dumps(raw))
    with pytest.raises(ValueError,match='weakens'):
        load_retrieval_model_policy(target)


def test_embedding_input_bytes_are_bounded():
    p=policy()
    def forbidden(*_): raise AssertionError('request must not execute')
    with pytest.raises(ValueError,match='byte budget'):
        RetrievalModelService(p,forbidden).embed(['x'*(p.input_bytes_limit+1)],expected_revision='a'*64)

def test_local_runtime_retrieval_service_plan_binds_exact_admitted_revisions(tmp_path: Path):
    import struct, hashlib
    from runtime.local_model_runtime import LocalModelRuntime
    def string(value: str) -> bytes:
        raw=value.encode(); return struct.pack('<Q',len(raw))+raw
    def gguf(name: str) -> bytes:
        arch='llama'; values=[
            ('general.architecture',8,string(arch)),('general.name',8,string(name)),
            (f'{arch}.context_length',4,struct.pack('<I',4096)),(f'{arch}.embedding_length',4,struct.pack('<I',1024)),
        ]
        return b'GGUF'+struct.pack('<IQQ',3,1,len(values))+b''.join(string(k)+struct.pack('<I',kind)+v for k,kind,v in values)+b'tensor-placeholder'
    root=tmp_path; models=root/'weights'; runtime_root=root/'bin'; models.mkdir(); runtime_root.mkdir()
    emb=models/'emb.gguf'; rr=models/'rr.gguf'; exe=runtime_root/'llama-server'; emb.write_bytes(gguf('emb')); rr.write_bytes(gguf('rr')+b'x'); exe.write_bytes(b'fixture')
    runtime=LocalModelRuntime(root,allowed_model_roots=[models],allowed_runtime_roots=[runtime_root])
    ea=runtime.inspect_model(emb); ra=runtime.inspect_model(rr)
    plan=runtime.plan_retrieval_model_services(ea,exe,embedding_model_id='embed',embedding_revision=ea.model_sha256,embedding_port=18081,embedding_context_size=2048,retrieval_policy_sha256='c'*64,reranker=ra,reranker_model_id='rerank',reranker_revision=ra.model_sha256,reranker_port=18082)
    assert plan.embedding_revision==ea.model_sha256 and plan.reranker_revision==ra.model_sha256
    assert plan.embedding_server.port != plan.reranker_server.port
    with pytest.raises(ValueError,match='embedding revision'):
        runtime.plan_retrieval_model_services(ea,exe,embedding_model_id='embed',embedding_revision='d'*64,embedding_port=18081,embedding_context_size=2048,retrieval_policy_sha256='c'*64)
