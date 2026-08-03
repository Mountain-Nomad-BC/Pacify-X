"""Safely normalize an LLM config and produce bounded architecture estimates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

FORMULA_VERSION = "1.0"
LIMITS = {"dimension": 1_000_000, "layers": 100_000, "heads": 100_000, "vocab": 100_000_000, "tokens": 100_000_000, "batch": 1_000_000, "experts": 1_000_000}
ALIASES = {
    "hidden_size": ("hidden_size", "dim", "d_model", "n_embd"),
    "intermediate_size": ("intermediate_size", "ffn_dim", "d_ff", "n_inner"),
    "layers": ("num_hidden_layers", "n_layers", "num_layers", "n_layer"),
    "query_heads": ("num_attention_heads", "n_heads", "num_heads", "n_head"),
    "kv_heads": ("num_key_value_heads", "n_kv_heads"),
    "context": ("max_position_embeddings", "max_seq_len", "seq_length", "n_positions"),
    "vocab_size": ("vocab_size", "n_vocab"),
    "experts": ("num_local_experts", "num_experts", "n_routed_experts"),
    "experts_per_token": ("num_experts_per_tok", "experts_per_token", "top_k"),
}


def _integer(value: Any, field: str, limit: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < 1 or value > limit:
        raise ValueError(f"{field} is outside bounded limits")
    return value


def _first(config: dict[str, Any], names: tuple[str, ...]) -> tuple[Any, str | None]:
    for name in names:
        if name in config:
            return config[name], name
    return None, None


def kv_cache_bytes(layers: int, kv_heads: int, head_dim: int, tokens: int, batch: int = 1, bytes_per_element: int = 2, beams: int = 1) -> int:
    return layers * 2 * kv_heads * head_dim * tokens * batch * bytes_per_element * beams


def attention_parameters(hidden: int, query_heads: int, kv_heads: int) -> int:
    head_dim = hidden // query_heads
    return hidden * hidden + 2 * hidden * (kv_heads * head_dim) + hidden * hidden


def inspect(config: dict[str, Any], workload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(config, dict) or not isinstance(workload or {}, dict):
        raise ValueError("configuration and workload must be objects")
    workload = workload or {}
    normalized: dict[str, Any] = {}
    evidence: dict[str, str | None] = {}
    warnings: list[str] = []
    limits = {"hidden_size": "dimension", "intermediate_size": "dimension", "layers": "layers", "query_heads": "heads", "kv_heads": "heads", "context": "tokens", "vocab_size": "vocab", "experts": "experts", "experts_per_token": "experts"}
    for field, aliases in ALIASES.items():
        value, source = _first(config, aliases)
        normalized[field] = _integer(value, field, LIMITS[limits[field]])
        evidence[field] = source
    if normalized["kv_heads"] is None and normalized["query_heads"] is not None:
        normalized["kv_heads"] = normalized["query_heads"]
        evidence["kv_heads"] = "inferred-default:query_heads"
        warnings.append("KV heads were inferred as equal to query heads; verify the runtime default.")
    hidden = normalized["hidden_size"]
    query_heads = normalized["query_heads"]
    kv_heads = normalized["kv_heads"]
    if hidden and query_heads:
        if hidden % query_heads:
            raise ValueError("hidden_size must be divisible by query_heads")
        normalized["head_dim"] = hidden // query_heads
    if query_heads and kv_heads:
        if query_heads % kv_heads:
            raise ValueError("query_heads must be divisible by kv_heads")
        normalized["query_to_kv_ratio"] = query_heads // kv_heads
        normalized["attention_variant"] = "MHA" if query_heads == kv_heads else ("MQA" if kv_heads == 1 else "GQA")
    model_type = str(config.get("model_type", "unknown"))
    normalized["model_type"] = model_type
    normalized["position_method"] = str(config.get("position_embedding_type") or ("RoPE-family" if "rope_theta" in config or model_type in {"llama", "mistral", "mixtral", "qwen2"} else "unknown"))
    normalized["normalization"] = str(config.get("norm_type") or ("RMSNorm-like" if "rms_norm_eps" in config else "unknown"))
    normalized["activation"] = str(config.get("hidden_act") or config.get("activation_function") or "unknown")
    estimates: dict[str, Any] = {}
    layers = normalized["layers"]
    intermediate = normalized["intermediate_size"]
    vocab = normalized["vocab_size"]
    if all(value is not None for value in (layers, hidden, query_heads, kv_heads, intermediate, vocab)):
        gated = normalized["activation"].casefold() not in {"relu", "gelu", "gelu_new"}
        attention = attention_parameters(hidden, query_heads, kv_heads)
        ffn = (3 if gated else 2) * hidden * intermediate
        embeddings = (1 if bool(config.get("tie_word_embeddings", False)) else 2) * vocab * hidden
        total = layers * (attention + ffn + 2 * hidden) + embeddings + hidden
        estimates.update({"attention_parameters_per_layer": attention, "ffn_parameters_per_layer": ffn, "embedding_and_output_parameters": embeddings, "estimated_total_parameters": total, "gated_ffn_assumed": gated})
        bits = _integer(workload.get("bits_per_weight"), "bits_per_weight", 64)
        if bits:
            estimates["estimated_weight_bytes"] = (total * bits + 7) // 8
    tokens = _integer(workload.get("tokens"), "tokens", LIMITS["tokens"])
    batch = _integer(workload.get("batch", 1), "batch", LIMITS["batch"])
    beams = _integer(workload.get("beams", 1), "beams", LIMITS["batch"])
    element_bytes = _integer(workload.get("kv_bytes_per_element", 2), "kv_bytes_per_element", 16)
    if all(value is not None for value in (layers, kv_heads, normalized.get("head_dim"), tokens, batch, beams, element_bytes)):
        estimates["kv_cache_bytes"] = kv_cache_bytes(layers, kv_heads, normalized["head_dim"], tokens, batch, element_bytes, beams)
        estimates["kv_cache_bytes_per_token_per_sequence"] = kv_cache_bytes(layers, kv_heads, normalized["head_dim"], 1, 1, element_bytes, 1)
    experts = normalized["experts"]
    active_experts = normalized["experts_per_token"]
    if experts and active_experts:
        if active_experts > experts:
            raise ValueError("experts_per_token cannot exceed experts")
        estimates["routed_expert_active_fraction"] = active_experts / experts
        warnings.append("MoE active fraction excludes shared experts, routing imbalance, capacity factors, and communication overhead.")
    unresolved = sorted(field for field, value in normalized.items() if value is None)
    return {
        "schema_version": "1.0", "formula_version": FORMULA_VERSION,
        "status": "review" if warnings or unresolved else "complete",
        "normalized": normalized, "field_evidence": evidence, "estimates": estimates,
        "warnings": warnings, "unresolved_fields": unresolved,
        "security": {"remote_code_executed": False, "model_imported": False, "network_used": False},
        "required_runtime_validation": ["model/runtime compatibility", "task quality", "effective context", "peak RAM/VRAM", "cold and warm latency", "throughput"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workload", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect(json.loads(args.config.read_text(encoding="utf-8")), json.loads(args.workload.read_text(encoding="utf-8")) if args.workload else None)
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
