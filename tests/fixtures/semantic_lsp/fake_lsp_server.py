#!/usr/bin/env python3
"""Tiny deterministic LSP server used only by Wave-2 tests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import unquote, urlparse


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        name, value = line.decode("ascii").split(":", 1)
        headers[name.casefold().strip()] = value.strip()
    length = int(headers["content-length"])
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def send(payload):
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    sys.stdout.buffer.flush()


def response(request_id, result):
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def error(request_id, code, message):
    send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def units(value):
    return len(value.encode("utf-16-le")) // 2


def line_bounds(text, line):
    lines = text.splitlines(keepends=True)
    if line >= len(lines):
        if line == len(lines) and text.endswith("\n"):
            return len(text), len(text)
        raise ValueError("line")
    start = sum(len(x) for x in lines[:line])
    raw = lines[line]
    content = raw.rstrip("\r\n")
    return start, start + len(content)


def pos_to_offset(text, pos):
    start, end = line_bounds(text, int(pos["line"]))
    target = int(pos["character"])
    total = 0
    for i, ch in enumerate(text[start:end]):
        total += units(ch)
        if total == target:
            return start + i + 1
        if total > target:
            raise ValueError("split surrogate")
    if total == target:
        return end
    raise ValueError("column")


def offset_to_pos(text, offset):
    line = text.count("\n", 0, offset)
    start = text.rfind("\n", 0, offset) + 1
    segment = text[start:offset]
    # CR in a CRLF line ending is not part of the LSP line content.
    if segment.endswith("\r") and offset < len(text) and text[offset:offset + 1] == "\n":
        segment = segment[:-1]
    return {"line": line, "character": units(segment)}


def make_range(text, start, end):
    return {"start": offset_to_pos(text, start), "end": offset_to_pos(text, end)}


def word_at(text, pos):
    offset = pos_to_offset(text, pos)
    left = offset
    right = offset
    while left > 0 and (text[left - 1].isalnum() or text[left - 1] == "_"):
        left -= 1
    while right < len(text) and (text[right].isalnum() or text[right] == "_"):
        right += 1
    return text[left:right], left, right


def uri_to_path(uri):
    parsed = urlparse(uri)
    raw = unquote(parsed.path)
    if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]
    return Path(raw)


def path_to_uri(path):
    return path.resolve().as_uri()


def disk_or_open(uri, docs):
    if uri in docs:
        return docs[uri]["text"]
    return uri_to_path(uri).read_text(encoding="utf-8")


def symbols_for(uri, text):
    result = []
    class_matches = list(re.finditer(r"(?m)^class\s+([A-Za-z_]\w*)", text))
    function_matches = list(re.finditer(r"(?m)^def\s+([A-Za-z_]\w*)", text))
    for match in class_matches:
        name = match.group(1)
        name_start, name_end = match.span(1)
        line_end = text.find("\n", match.start())
        if line_end < 0:
            line_end = len(text)
        result.append({
            "name": name,
            "kind": 5,
            "range": make_range(text, match.start(), line_end),
            "selectionRange": make_range(text, name_start, name_end),
            "children": [],
        })
    for match in function_matches:
        name = match.group(1)
        name_start, name_end = match.span(1)
        line_end = text.find("\n", match.start())
        if line_end < 0:
            line_end = len(text)
        result.append({
            "name": name,
            "kind": 12,
            "range": make_range(text, match.start(), line_end),
            "selectionRange": make_range(text, name_start, name_end),
            "children": [],
        })
    return result


def all_python_files(root):
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def find_occurrences(root, docs, word):
    result = []
    seen = set()
    for path in all_python_files(root):
        uri = path_to_uri(path)
        seen.add(uri)
        text = disk_or_open(uri, docs)
        for match in re.finditer(rf"\b{re.escape(word)}\b", text):
            result.append((uri, text, match.start(), match.end()))
    for uri, doc in docs.items():
        if uri in seen or not uri_to_path(uri).suffix == ".py":
            continue
        text = doc["text"]
        for match in re.finditer(rf"\b{re.escape(word)}\b", text):
            result.append((uri, text, match.start(), match.end()))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--content-modified-once", default="")
    parser.add_argument("--bad-initialize", action="store_true")
    parser.add_argument("--crash-after-initialize", action="store_true")
    args = parser.parse_args()

    docs = {}
    root = None
    modified_once = set()
    next_server_request = 9000
    pending_server_request = None
    pending_original_request = None

    while True:
        message = read_message()
        if message is None:
            return 0

        # response to a server->client request
        if "method" not in message and "id" in message:
            if pending_server_request is not None and message["id"] == pending_server_request:
                response(pending_original_request, message.get("result"))
                pending_server_request = None
                pending_original_request = None
            continue

        method = message.get("method")
        params = message.get("params", {})
        request_id = message.get("id")

        if method == "initialize":
            root = uri_to_path(params["rootUri"])
            if args.bad_initialize:
                response(request_id, {"wrong": True})
                continue
            response(request_id, {
                "capabilities": {
                    "positionEncoding": "utf-16",
                    "textDocumentSync": {"openClose": True, "change": 2},
                    "documentSymbolProvider": {},
                    "definitionProvider": True,
                    "declarationProvider": True,
                    "implementationProvider": True,
                    "referencesProvider": True,
                    "renameProvider": {"prepareProvider": True},
                    "workspace": {"workspaceFolders": {"supported": True}},
                },
                "serverInfo": {"name": "px-wave2-fake", "version": "1"},
            })
            continue
        if method == "initialized":
            if args.crash_after_initialize:
                return 17
            continue
        if method == "shutdown":
            response(request_id, None)
            continue
        if method == "exit":
            return 0
        if method == "$/cancelRequest":
            continue
        if method == "textDocument/didOpen":
            td = params["textDocument"]
            docs[td["uri"]] = {"text": td["text"], "version": td["version"]}
            if "BROKEN_LSP" in td["text"]:
                start = td["text"].index("BROKEN_LSP")
                send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {
                    "uri": td["uri"], "version": td["version"], "diagnostics": [{
                        "range": make_range(td["text"], start, start + len("BROKEN_LSP")),
                        "severity": 1, "source": "fake", "code": "BROKEN", "message": "synthetic diagnostic",
                    }]
                }})
            continue
        if method == "textDocument/didChange":
            td = params["textDocument"]
            doc = docs[td["uri"]]
            text = doc["text"]
            for change in params["contentChanges"]:
                if "range" not in change:
                    text = change["text"]
                else:
                    start = pos_to_offset(text, change["range"]["start"])
                    end = pos_to_offset(text, change["range"]["end"])
                    text = text[:start] + change["text"] + text[end:]
            docs[td["uri"]] = {"text": text, "version": td["version"]}
            continue
        if method == "textDocument/didClose":
            docs.pop(params["textDocument"]["uri"], None)
            continue

        if request_id is None:
            continue

        if args.content_modified_once == method and method not in modified_once:
            modified_once.add(method)
            error(request_id, -32801, "content modified once")
            continue

        if method == "px/test/echo":
            response(request_id, params)
            continue
        if method == "px/test/sleep":
            time.sleep(float(params.get("seconds", 0.2)))
            response(request_id, True)
            continue
        if method == "px/test/getDocument":
            uri = params["uri"]
            response(request_id, docs.get(uri))
            continue
        if method == "px/test/serverRequest":
            pending_server_request = next_server_request
            next_server_request += 1
            pending_original_request = request_id
            send({"jsonrpc": "2.0", "id": pending_server_request, "method": "workspace/configuration", "params": {"items": [{"section": "python.analysis"}]}})
            continue

        if method == "textDocument/documentSymbol":
            uri = params["textDocument"]["uri"]
            if uri not in docs:
                error(request_id, -32002, "document must be open")
                continue
            response(request_id, symbols_for(uri, docs[uri]["text"]))
            continue

        if method in {"textDocument/definition", "textDocument/declaration", "textDocument/implementation", "textDocument/references"}:
            uri = params["textDocument"]["uri"]
            if uri not in docs:
                error(request_id, -32002, "document must be open")
                continue
            text = docs[uri]["text"]
            word, _a, _b = word_at(text, params["position"])
            locations = [
                {"uri": u, "range": make_range(t, a, b)}
                for u, t, a, b in find_occurrences(root, docs, word)
            ]
            if method != "textDocument/references":
                locations = locations[:1]
            response(request_id, locations)
            continue

        if method == "textDocument/prepareRename":
            uri = params["textDocument"]["uri"]
            if uri not in docs:
                error(request_id, -32002, "document must be open")
                continue
            text = docs[uri]["text"]
            word, a, b = word_at(text, params["position"])
            response(request_id, None if not word else {"range": make_range(text, a, b), "placeholder": word})
            continue

        if method == "textDocument/rename":
            uri = params["textDocument"]["uri"]
            if uri not in docs:
                error(request_id, -32002, "document must be open before rename")
                continue
            text = docs[uri]["text"]
            word, _a, _b = word_at(text, params["position"])
            changes = []
            grouped = {}
            for u, t, a, b in find_occurrences(root, docs, word):
                grouped.setdefault(u, [t, []])[1].append({"range": make_range(t, a, b), "newText": params["newName"]})
            for u in sorted(grouped):
                version = docs[u]["version"] if u in docs else None
                changes.append({"textDocument": {"uri": u, "version": version}, "edits": grouped[u][1]})
            response(request_id, {"documentChanges": changes})
            continue

        error(request_id, -32601, f"unknown method: {method}")


if __name__ == "__main__":
    raise SystemExit(main())
