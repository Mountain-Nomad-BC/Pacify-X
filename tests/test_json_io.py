"""Acquisition limits and unambiguous JSON at the shared reader boundary."""
import json
import tracemalloc
from pathlib import Path

import pytest

from runtime.json_io import (
    bounded_json_text, bounded_strings, decode_json_object,
    load_json_object, read_bounded_bytes,
)


def test_duplicate_stream_is_bounded_before_deduplication() -> None:
    consumed = []
    def duplicates():
        for index in range(100):
            consumed.append(index)
            yield "same"
    with pytest.raises(ValueError, match="item budget"):
        bounded_strings(duplicates(), max_items=3)
    assert consumed == [0, 1, 2, 3]
    assert bounded_strings(iter(["b", "a", "b"]), max_items=3) == ("b", "a")


def test_string_collection_counts_utf8_and_duplicate_bytes() -> None:
    assert bounded_strings(["é", "é"], max_bytes=4) == ("é",)
    with pytest.raises(ValueError, match="byte budget"):
        bounded_strings(["é", "é"], max_bytes=3)
    with pytest.raises(ValueError, match="byte budget"):
        bounded_strings(["é"], max_item_bytes=1)


@pytest.mark.parametrize("values", ["abc", b"abc", [1], [None], [True]])
def test_string_collection_rejects_coercive_inputs(values) -> None:
    with pytest.raises(ValueError):
        bounded_strings(values)


def test_raw_reader_stops_after_single_oversize_probe(tmp_path, monkeypatch) -> None:
    import io
    class ObservedStream(io.BytesIO):
        consumed = 0
        def read(self, count=-1):
            assert 0 < count <= 65_536
            data = super().read(count)
            self.consumed += len(data)
            return data
    stream = ObservedStream(b"x" * 10000)
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: stream)
    with pytest.raises(ValueError, match="byte budget"):
        read_bounded_bytes(tmp_path / "raw", max_bytes=128)
    assert stream.consumed == 129
    assert stream.closed


def test_json_render_budget_includes_escaping_indentation_and_utf8() -> None:
    value = {"x": ["é", "\x00", "\\\""]}
    expected = json.dumps(value, indent=2, ensure_ascii=False)
    size = len(expected.encode("utf-8"))
    assert bounded_json_text(value, max_bytes=size) == expected
    with pytest.raises(ValueError, match="byte budget"):
        bounded_json_text(value, max_bytes=size - 1)


def test_oversized_string_rejected_before_json_encoder(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("encoder received an unbounded string")
    monkeypatch.setattr(json.JSONEncoder, "iterencode", forbidden)
    with pytest.raises(ValueError, match="byte budget"):
        bounded_json_text({"x": "a" * 1000}, max_bytes=100)


def test_exact_acquired_json_image_uses_strict_decoder() -> None:
    assert decode_json_object(b'{"x":1}', max_bytes=7) == {"x": 1}
    with pytest.raises(ValueError, match="duplicate"):
        decode_json_object(b'{"x":1,"x":2}')


@pytest.mark.parametrize("raw", ['{"a": 1, "a": 2}', '{"x": {"a": 1, "a": 2}}', '{"x": NaN}', '{"x": Infinity}', '{"x": 1e999}'])
def test_reader_rejects_ambiguous_or_nonfinite_json(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "value.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        load_json_object(path)


def test_reader_enforces_exact_byte_boundary(tmp_path: Path) -> None:
    path = tmp_path / "value.json"
    raw = '{"x": "é"}'.encode("utf-8")
    path.write_bytes(raw)
    assert load_json_object(path, max_bytes=len(raw)) == {"x": "é"}
    with pytest.raises(ValueError, match="max_bytes"):
        load_json_object(path, max_bytes=len(raw) - 1)


def test_reader_rejects_depth_before_json_decoder(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "value.json"
    path.write_text('{"x":' + '[' * 2000 + '0' + ']' * 2000 + '}', encoding="utf-8")
    def unexpected_decode(*args, **kwargs):
        pytest.fail("decoder called before checking depth budget")
    monkeypatch.setattr(json, "loads", unexpected_decode)
    with pytest.raises(ValueError, match="max_depth"):
        load_json_object(path, max_depth=8)


def test_reader_ignores_escaped_brackets_inside_strings(tmp_path: Path) -> None:
    path = tmp_path / "value.json"
    value = {"x": '[{\\"}]' * 30}
    path.write_text(json.dumps(value), encoding="utf-8")
    assert load_json_object(path, max_depth=1) == value


@pytest.mark.parametrize("limit", [True, False, 0, -1, 1.5, float("nan"), float("inf"), "8"])
def test_reader_limits_are_strict_positive_integers(tmp_path: Path, limit) -> None:
    path = tmp_path / "value.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="max_bytes"):
        load_json_object(path, max_bytes=limit)
def test_small_document_does_not_allocate_the_entire_read_ceiling(tmp_path: Path) -> None:
    path = tmp_path / "small.json"
    path.write_text('{"x": 1}', encoding="utf-8")
    tracemalloc.start()
    try:
        assert load_json_object(path) == {"x": 1}
        assert tracemalloc.get_traced_memory()[1] < 1024 * 1024
    finally:
        tracemalloc.stop()
