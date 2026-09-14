"""Lean bounded data admission for numeric analysis; no execution authority."""

from __future__ import annotations

import math
import time
from .json_io import validate_json_value

MAX_ANALYSIS_BYTES = 8 * 1024 * 1024
MAX_ANALYSIS_NODES = 100000


def finite_number(
    value: object,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be an actual finite number")
    if type(value) is int and value.bit_length() > 1024:
        raise ValueError(f"{name} exceeds finite numeric representation")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} exceeds finite numeric representation") from error
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if (
        minimum is not None
        and number < minimum
        or maximum is not None
        and number > maximum
    ):
        raise ValueError(f"{name} is outside its declared numeric range")
    return number


def bounded_integer(value: object, name: str, *, minimum: int = 1, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be a bounded integer")
    return value


def bounded_text(
    value: object, name: str, *, maximum: int = 256, strip: bool = True
) -> str:
    if type(value) is not str or len(value) > maximum:
        raise ValueError(f"{name} must be bounded nonempty text")
    result = value.strip() if strip else value
    if (
        not result
        or len(result.encode("utf-8")) > maximum
        or any(ord(c) < 32 for c in result)
    ):
        raise ValueError(f"{name} must be bounded nonempty text")
    return result


def bounded_sequence(
    value: object, name: str, *, maximum: int, minimum: int = 0
) -> list | tuple:
    if type(value) not in (list, tuple) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{name} must be a bounded sequence")
    return value


def bounded_mapping(value: object, name: str, *, maximum: int = 256) -> dict:
    if type(value) is not dict or len(value) > maximum:
        raise ValueError(f"{name} must be a bounded object")
    for key in value:
        bounded_text(key, f"{name} key", strip=False)
    return value


def bounded_json_value(value: object) -> None:
    """Admit shape and conservative ASCII JSON size before sorting or hashing.

    The hash owner's existing ensure_ascii encoding is bounded without first
    allocating its complete serialized representation. Input objects are not
    rewritten, and opaque/custom Python values are never stringified.
    """
    validate_json_value(value, max_depth=32, max_nodes=MAX_ANALYSIS_NODES)
    used = 0

    def visit(item):
        nonlocal used
        used += 3  # separators, brackets and conservative per-node overhead
        kind = type(item)
        if kind is str:
            if len(item) > MAX_ANALYSIS_BYTES:
                raise ValueError("analysis input exceeds its byte budget")
            size = 2
            for char in item:
                code = ord(char)
                size += (
                    12
                    if code > 0xFFFF
                    else 6
                    if code > 127 or code < 32
                    else 2
                    if char in '\\"'
                    else 1
                )
                if used + size > MAX_ANALYSIS_BYTES:
                    raise ValueError("analysis input exceeds its byte budget")
            used += size
        elif kind is int:
            if item.bit_length() > 1024:
                raise ValueError("analysis integer exceeds its representation budget")
            used += len(str(item))
        elif kind is float:
            used += 32
        elif kind in (bool, type(None)):
            used += 5
        elif kind is dict:
            for key, child in item.items():
                visit(key)
                visit(child)
        else:
            for child in item:
                visit(child)
        if used > MAX_ANALYSIS_BYTES:
            raise ValueError("analysis input exceeds its byte budget")

    visit(value)


def analysis_payload(value: object) -> dict:
    result = bounded_mapping(value, "analysis payload", maximum=128)
    bounded_json_value(result)
    return result


def bounded_items(value, name: str, *, maximum: int, max_seconds: float = 60.0):
    """Stream a bounded finite iterable, with one overflow witness.

    Iterator ownership stays with the caller. Deadline checks surround next()
    and exhaustion; they cannot interrupt a blocked user iterator.
    """
    maximum = bounded_integer(maximum, "iterable limit", maximum=100000)
    duration = finite_number(max_seconds, "iterable duration", minimum=0, maximum=60)
    if duration == 0 or isinstance(value, (str, bytes, bytearray, dict)):
        raise ValueError(f"{name} must be a bounded iterable")
    deadline = time.monotonic() + duration
    try:
        iterator = iter(value)
    except TypeError as error:
        raise ValueError(f"{name} must be a bounded iterable") from error

    def check():
        if time.monotonic() >= deadline:
            raise ValueError(f"{name} exceeded its cooperative duration budget")

    check()

    def values():
        for index in range(maximum + 1):
            check()
            try:
                item = next(iterator)
            except StopIteration:
                check()
                return
            check()
            if index == maximum:
                raise ValueError(f"{name} exceeds its raw observation budget")
            yield item

    return values()
