"""Bounded streaming image and locator-parser contract checks."""
from contextlib import closing
from pathlib import Path
import os

import pytest

from runtime import evidence_portability as scanner
from runtime import input_files


def scan(chunks):
    return scanner.stream_portability_findings(chunks, deadline=input_files.cooperative_deadline())


@pytest.mark.parametrize("text", [
    "../other/file.json", "C:/Users/fixture/file.json", r"C:\Users\fixture\file.json",
    r"\\server\share\file.json", "file:///Users/fixture/file.json", "/mnt/c/work/file",
    "/Users/fixture/file", "/home/fixture/file", "/tmp/fixture/file", "/var/tmp/fixture/file",
    "/private/var/fixture/file", "https://example.test/evidence", "/users/policy",
    "aC:/not-a-drive-at-that-position", "ZC:/not-a-drive", "$ARGUMENTS",
    'prefix "C:/one/file" suffix "../two/file", ../two/file.',
    'x\u754c C:/Users/\u754c/file.json " next',
    r"\\" + "a" * 100 + r"\share\file", r"\\server" + chr(92) + "b" * 100,
    'C:/first\r\n../second\nfile:///third',
])
def test_every_byte_split_matches_existing_regex(text):
    raw = text.encode("utf-8")
    expected = scanner.portability_findings(text)
    for cut in range(1, len(raw)):
        assert scan([raw[:cut], raw[cut:]]) == expected, cut
    assert scan([raw[index:index + 1] for index in range(len(raw))]) == expected


def test_many_chunk_boundaries_and_duplicate_locators_preserve_full_match_set():
    raw = (b"a" * 67 + b' "C:/fixture/one" ../fixture/two\n') * 200
    expected = scanner.portability_findings(raw.decode())
    for width in [1, 7, 31, 63, 64, 65, 127, 1024, 65536]:
        assert scan([raw[i:i + width] for i in range(0, len(raw), width)]) == expected


def test_invalid_utf8_replacement_matches_existing_decode_behavior():
    raw = b'"C:/fixture/\xfffile" ../other/\xe7\x95\x8c\n'
    expected = scanner.portability_findings(raw.decode("utf-8", errors="replace"))
    for cut in range(1, len(raw)):
        assert scan([raw[:cut], raw[cut:]]) == expected


def test_unfinished_long_unc_prefix_fails_instead_of_disappearing_at_boundary():
    with pytest.raises(ValueError):
        scan([b"\\\\" + b"a" * 3000, b"a" * 3000, b"\\share"])


def test_oversized_locator_and_unique_denominator_fail_explicitly():
    with pytest.raises(ValueError):
        scan([b"C:/" + b"a" * 5000])
    raw = "\n".join(f"../fixture/{i}" for i in range(4097)).encode()
    with pytest.raises(ValueError):
        scan([raw[i:i + 65536] for i in range(0, len(raw), 65536)])


def test_checked_stream_uses_bounded_reads_and_one_owned_handle(tmp_path, monkeypatch):
    path = tmp_path / "input.txt"
    raw = b"a" * 130000 + b"../fixture/tail\n"
    path.write_bytes(raw)
    info = path.stat()
    original = Path.open
    opened = []
    sizes = []

    class Wrapper:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, amount):
            assert 0 < amount <= 65536
            sizes.append(amount)
            return self.stream.read(amount)

    def tracked(candidate, *args, **kwargs):
        stream = original(candidate, *args, **kwargs)
        if candidate == path:
            opened.append(stream)
            return Wrapper(stream)
        return stream

    monkeypatch.setattr(Path, "open", tracked)
    with closing(input_files.iter_file_image(path, info, limit=len(raw), deadline=input_files.cooperative_deadline())) as chunks:
        assert scan(chunks) == scanner.portability_findings(raw.decode())
    assert len(opened) == 1 and opened[0].closed
    assert len(sizes) >= 3


def test_parser_failure_explicitly_closes_partially_consumed_handle(tmp_path, monkeypatch):
    path = tmp_path / "input.txt"
    path.write_bytes(b"C:/" + b"x" * 65534)
    info = path.stat()
    original = Path.open
    opened = []

    def tracked(candidate, *args, **kwargs):
        stream = original(candidate, *args, **kwargs)
        if candidate == path:
            opened.append(stream)
        return stream

    monkeypatch.setattr(Path, "open", tracked)
    with pytest.raises(ValueError):
        with closing(input_files.iter_file_image(path, info, limit=100000, deadline=input_files.cooperative_deadline())) as chunks:
            scan(chunks)
    assert len(opened) == 1 and opened[0].closed


def test_changed_source_is_refused_before_first_chunk(tmp_path):
    path = tmp_path / "input.txt"
    path.write_bytes(b"original")
    info = path.stat()
    path.write_bytes(b"changed-longer")
    with closing(input_files.iter_file_image(path, info, limit=100, deadline=input_files.cooperative_deadline())) as chunks:
        with pytest.raises(ValueError):
            next(chunks)


def test_same_size_modification_is_refused_after_full_consumption(tmp_path):
    path = tmp_path / "input.txt"
    path.write_bytes(b"x" * 70000)
    info = path.stat()
    with closing(input_files.iter_file_image(path, info, limit=100000, deadline=input_files.cooperative_deadline())) as chunks:
        assert len(next(chunks)) == 65536
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000))
        with pytest.raises(ValueError):
            list(chunks)


def test_streaming_does_not_increase_whole_image_materialization_limit(tmp_path):
    path = tmp_path / "large.txt"
    with path.open("wb") as stream:
        stream.truncate(65 * 1024 * 1024)
        stream.seek(-32, 2)
        stream.write(b'"C:/fixture/near-eof.json"' + b" " * 7)
    info = path.stat()
    with pytest.raises(ValueError):
        input_files.read_file_image(path, info, limit=info.st_size, deadline=input_files.cooperative_deadline())
    with closing(input_files.iter_file_image(path, info, limit=100 * 1024 * 1024, deadline=input_files.cooperative_deadline())) as chunks:
        findings = scan(chunks)
    assert findings == ("C:/fixture/near-eof.json",)
