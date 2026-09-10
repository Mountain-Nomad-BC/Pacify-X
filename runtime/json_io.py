"""Bounded JSON acquisition and consistent JSON value semantics."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any
from collections.abc import Iterable


MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_JSON_DEPTH = 128
MAX_JSON_NODES = 1_000_000
_STRUCTURAL_TOKEN = re.compile(rb'[\[\]{}"\\]')


def _positive_integer(value: int, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def validate_json_value(
    value: Any, *, max_depth: int = MAX_JSON_DEPTH, max_nodes: int = MAX_JSON_NODES
) -> None:
    """Reject non-JSON values even in fields without a domain schema rule.

    Only active ancestors count as cycles: repeated references to the same
    acyclic object are valid and count toward the traversal budget each time.
    Container depth is bounded before recursion; width uses streaming iterators.
    """
    _positive_integer(max_depth, "max_depth")
    _positive_integer(max_nodes, "max_nodes")
    if max_depth > MAX_JSON_DEPTH:
        raise ValueError(f"max_depth must not exceed {MAX_JSON_DEPTH}")
    active: set[int] = set()
    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes:
            raise ValueError("JSON max_nodes exceeded")
        kind = type(item)
        if kind in (str, int, bool, type(None)):
            return
        if kind is float:
            if not math.isfinite(item):
                raise ValueError("non-finite JSON number")
            return
        if kind not in (dict, list):
            raise ValueError(f"non-JSON value type: {kind.__name__}")
        if depth > max_depth:
            raise ValueError("JSON max_depth exceeded")
        if id(item) in active:
            raise ValueError("cyclic JSON value")
        if len(item) > max_nodes - nodes:
            raise ValueError("JSON max_nodes exceeded")
        active.add(id(item))
        try:
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        raise ValueError("JSON object keys must be strings")
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
        finally:
            active.remove(id(item))

    visit(value, 1)


def json_value_key(value: Any) -> tuple:
    """Hashable JSON equality: number values agree; booleans stay distinct."""
    validate_json_value(value)

    def key(item: Any) -> tuple:
        kind = type(item)
        if kind is dict:
            return ("object", frozenset((name, key(child)) for name, child in item.items()))
        if kind is list:
            return ("array", tuple(key(child) for child in item))
        if kind in (int, float):
            return ("number", item)
        return (kind.__name__, item)

    return key(value)


def _check_depth(raw: bytes | bytearray, max_depth: int) -> None:
    depth = 0
    in_string = False
    escaped_position = -1
    # Scan punctuation in C; skip text runs without constructing token lists.
    # An escape covers exactly the next byte, even when it is not punctuation.
    for match in _STRUCTURAL_TOKEN.finditer(raw):
        position = match.start()
        token = raw[position]
        if in_string:
            if position == escaped_position:
                continue
            if token == 92:
                escaped_position = position + 1
            elif token == 34:
                in_string = False
        elif token == 34:
            in_string = True
        elif token in (91, 123):
            depth += 1
            if depth > max_depth:
                raise ValueError("JSON max_depth exceeded before decoding")
        elif token in (93, 125):
            depth -= 1
    # The JSON decoder remains authoritative for syntax, including unbalanced
    # delimiters; this scan only prevents excessive allocation/decoder depth.


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    raise ValueError(f"non-JSON numeric constant: {token}")


def _finite_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def bounded_strings(
    values: Iterable[str], *, max_items: int = 64,
    max_item_bytes: int = 4096, max_bytes: int = 65_536,
) -> tuple[str, ...]:
    """Materialize once; count duplicate inputs before stable deduplication."""
    for name, limit in (("max_items", max_items), ("max_item_bytes", max_item_bytes), ("max_bytes", max_bytes)):
        _positive_integer(limit, name)
    if isinstance(values, (str, bytes)):
        raise ValueError("expected an iterable of strings, not a string")
    selected: dict[str, None] = {}
    used = 0
    for index, value in enumerate(values):
        if index >= max_items:
            raise ValueError("string collection item budget exceeded")
        if type(value) is not str or len(value) > max_item_bytes:
            raise ValueError("string collection item type or byte budget exceeded")
        size = len(value.encode("utf-8"))
        used += size
        if size > max_item_bytes or used > max_bytes:
            raise ValueError("string collection byte budget exceeded")
        selected[value] = None
    return tuple(selected)


def read_bounded_bytes(path: Path, *, max_bytes: int) -> bytearray:
    """Acquire at most the budget plus one oversize probe byte."""
    _positive_integer(max_bytes, "max_bytes")
    raw = bytearray()
    with path.open("rb") as stream:
        while len(raw) <= max_bytes:
            chunk = stream.read(min(64 * 1024, max_bytes + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
    if len(raw) > max_bytes:
        raise ValueError(f"byte budget (max_bytes) exceeded: {path}")
    return raw


def bounded_json_text(value: Any, *, max_bytes: int) -> str:
    """Bound complete UTF-8 output, including JSON escaping and indentation.

    Strings are checked before the encoder can allocate an escaped token.
    The encoder can allocate a token proportional to the bounded input string;
    this does not claim constant-memory streaming JSON serialization.
    """
    _positive_integer(max_bytes, "max_bytes")
    validate_json_value(value, max_nodes=min(MAX_JSON_NODES, max_bytes))
    characters = 0

    def check_strings(item: Any) -> None:
        nonlocal characters
        if type(item) is str:
            characters += len(item)
            if characters > max_bytes:
                raise ValueError("JSON rendering byte budget exceeded")
        elif type(item) is dict:
            for key, child in item.items():
                check_strings(key)
                check_strings(child)
        elif type(item) is list:
            for child in item:
                check_strings(child)

    check_strings(value)
    output = bytearray()
    for token in json.JSONEncoder(indent=2, ensure_ascii=False, allow_nan=False).iterencode(value):
        for offset in range(0, len(token), 16_384):
            chunk = token[offset:offset + 16_384].encode("utf-8")
            if len(output) + len(chunk) > max_bytes:
                raise ValueError("JSON rendering byte budget exceeded")
            output.extend(chunk)
    return output.decode("utf-8")


def bounded_canonical_json_bytes(value: Any, *, max_bytes: int,
                                 max_nodes: int = MAX_JSON_NODES) -> bytes:
    """Preserve canonical JSON wire bytes while bounding traversal and encoding.

    Tuple values retain json.dumps' array semantics for existing WAL callers.
    Unsupported iterables are never materialized. The byte ceiling includes the
    trailing newline; it is not a constant-memory serialization claim.
    """
    _positive_integer(max_bytes, 'max_bytes')
    _positive_integer(max_nodes, 'max_nodes')
    active = set()
    nodes = 0
    characters = 0

    def check(item, depth):
        nonlocal nodes, characters
        nodes += 1
        if nodes > max_nodes or depth > MAX_JSON_DEPTH:
            raise ValueError('canonical JSON structure exceeds budget')
        kind = type(item)
        if kind is str:
            characters += len(item)
            if characters >= max_bytes:
                raise ValueError('canonical JSON string budget exceeded')
        elif kind is int:
            if item.bit_length() > 4096:
                raise ValueError('canonical JSON integer budget exceeded')
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError('non-finite JSON number')
        elif item is None or kind is bool:
            return
        elif kind in (dict, list, tuple):
            if id(item) in active or len(item) > max_nodes - nodes:
                raise ValueError('canonical JSON cycle or node budget exceeded')
            active.add(id(item))
            try:
                if kind is dict:
                    for key, child in item.items():
                        if type(key) is not str:
                            raise ValueError('JSON object keys must be strings')
                        check(key, depth + 1)
                        check(child, depth + 1)
                else:
                    for child in item:
                        check(child, depth + 1)
            finally:
                active.remove(id(item))
        else:
            raise ValueError('unsupported canonical JSON value')

    check(value, 1)
    result = bytearray()
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    for token in encoder.iterencode(value):
        for start in range(0, len(token), 16384):
            fragment = token[start:start + 16384].encode('utf-8')
            if len(result) + len(fragment) + 1 > max_bytes:
                raise ValueError('canonical JSON byte budget exceeded')
            result.extend(fragment)
    result.extend(b'\n')
    return bytes(result)


def decode_json_value(
    raw: bytes | bytearray, *, max_bytes: int = MAX_JSON_BYTES,
    max_depth: int = MAX_JSON_DEPTH, max_nodes: int = MAX_JSON_NODES,
) -> Any:
    """Strictly decode the exact bounded byte image a caller acquired."""
    for name, limit in (("max_bytes", max_bytes), ("max_depth", max_depth), ("max_nodes", max_nodes)):
        _positive_integer(limit, name)
    if max_depth > MAX_JSON_DEPTH:
        raise ValueError(f"max_depth must not exceed {MAX_JSON_DEPTH}")
    if len(raw) > max_bytes:
        raise ValueError("JSON max_bytes exceeded")
    _check_depth(raw, max_depth)
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_pairs,
                       parse_constant=_reject_constant, parse_float=_finite_float)
    validate_json_value(value, max_depth=max_depth, max_nodes=max_nodes)
    return value


def decode_json_object(
    raw: bytes | bytearray, *, max_bytes: int = MAX_JSON_BYTES,
    max_depth: int = MAX_JSON_DEPTH, max_nodes: int = MAX_JSON_NODES,
) -> dict[str, Any]:
    """Strictly decode one bounded JSON object from its acquired byte image."""
    value = decode_json_value(raw, max_bytes=max_bytes, max_depth=max_depth, max_nodes=max_nodes)
    if not isinstance(value, dict):
        raise ValueError('expected JSON object')
    return value


def load_json_object(
    path: Path, *, max_bytes: int = MAX_JSON_BYTES,
    max_depth: int = MAX_JSON_DEPTH, max_nodes: int = MAX_JSON_NODES,
) -> dict[str, Any]:
    """Read at most max_bytes+1 bytes and reject ambiguous representations.

    The byte and depth budgets apply before decoding. The node budget bounds
    subsequent value traversal; it is not a claim of streaming JSON decoding.
    Filesystem authority and path ownership remain the caller's responsibility.
    """
    for name, limit in (("max_bytes", max_bytes), ("max_depth", max_depth), ("max_nodes", max_nodes)):
        _positive_integer(limit, name)
    if max_depth > MAX_JSON_DEPTH:
        raise ValueError(f"max_depth must not exceed {MAX_JSON_DEPTH}")
    raw = read_bounded_bytes(path, max_bytes=max_bytes)
    return decode_json_object(raw, max_bytes=max_bytes, max_depth=max_depth, max_nodes=max_nodes)
