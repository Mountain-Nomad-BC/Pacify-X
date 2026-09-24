"""Strict, bounded LSP ``Content-Length`` framing."""
from __future__ import annotations

import json
from typing import Any, BinaryIO


class LspFramingError(ValueError):
    pass


MAX_HEADER_BYTES = 16 * 1024


def encode_message(payload: Any, *, max_message_bytes: int | None = None) -> bytes:
    if not isinstance(payload, dict):
        raise LspFramingError("JSON-RPC payload must be an object")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if max_message_bytes is not None and len(body) > max_message_bytes:
        raise LspFramingError("outbound LSP body exceeds byte budget")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _read_exact(stream: BinaryIO, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        part = stream.read(length - len(chunks))
        if not part:
            raise LspFramingError("EOF inside LSP body")
        chunks.extend(part)
    return bytes(chunks)


def read_message(stream: BinaryIO, *, max_message_bytes: int) -> dict[str, Any]:
    if type(max_message_bytes) is not int or max_message_bytes < 1:
        raise ValueError("max_message_bytes must be a positive integer")
    header = bytearray()
    while True:
        line = stream.readline(MAX_HEADER_BYTES + 1)
        if line == b"":
            if not header:
                raise EOFError("language-server stream closed")
            raise LspFramingError("EOF inside LSP header")
        header.extend(line)
        if len(header) > MAX_HEADER_BYTES:
            raise LspFramingError("LSP header exceeds byte budget")
        if line in (b"\r\n", b"\n"):
            break

    content_lengths: list[int] = []
    for raw in bytes(header).splitlines():
        if not raw:
            continue
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise LspFramingError("LSP header must be ASCII") from exc
        if ":" not in text:
            raise LspFramingError("malformed LSP header field")
        name, value = text.split(":", 1)
        if name.strip().casefold() == "content-length":
            value = value.strip()
            if not value.isdigit():
                raise LspFramingError("invalid Content-Length")
            content_lengths.append(int(value))
    if len(content_lengths) != 1:
        raise LspFramingError("exactly one Content-Length header is required")
    length = content_lengths[0]
    if length > max_message_bytes:
        raise LspFramingError("LSP body exceeds byte budget")
    body = _read_exact(stream, length)
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LspFramingError("invalid UTF-8 JSON-RPC payload") from exc
    if not isinstance(value, dict):
        raise LspFramingError("JSON-RPC payload must be an object")
    return value
