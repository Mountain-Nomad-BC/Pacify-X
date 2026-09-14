"""CPU-authoritative bounded archive images; never extract archive paths."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import gzip
import io
from pathlib import Path
import stat
import struct
import tarfile
import unicodedata
import zipfile

from .json_io import read_bounded_bytes


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 64 * 1024 * 1024
    max_expanded_bytes: int = 256 * 1024 * 1024
    max_member_bytes: int = 32 * 1024 * 1024
    max_members: int = 20_000
    max_directory_bytes: int = 8 * 1024 * 1024
    max_name_bytes: int = 4096

    def __post_init__(self):
        for name, ceiling in (
            ("max_archive_bytes", 512 * 1024 * 1024),
            ("max_expanded_bytes", 1024 * 1024 * 1024),
            ("max_member_bytes", 256 * 1024 * 1024),
            ("max_members", 100_000),
            ("max_directory_bytes", 32 * 1024 * 1024),
            ("max_name_bytes", 4096),
        ):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(f"invalid archive limit: {name}")


DEFAULT_LIMITS = ArchiveLimits()
_DEVICES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class BoundedArchiveWriter:
    """Bound the highest written offset, including ZIP header rewrites."""

    def __init__(self, stream, max_bytes: int):
        self.stream = stream
        self.max_bytes = max_bytes

    def write(self, data):
        if self.stream.tell() + len(data) > self.max_bytes:
            raise ValueError("compressed archive output byte budget exceeded")
        return self.stream.write(data)

    def tell(self):
        return self.stream.tell()

    def seek(self, offset, whence=0):
        return self.stream.seek(offset, whence)

    def flush(self):
        return self.stream.flush()


def portable_member_name(
    name: str, *, allow_directory: bool = True, max_bytes: int = 4096
) -> str:
    if (
        type(name) is not str
        or not name
        or len(name) > max_bytes
        or len(name.encode("utf-8")) > max_bytes
        or name.startswith("/")
        or any(c in name for c in '\\:<>"|?*')
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("unsafe archive member name")
    value = name[:-1] if allow_directory and name.endswith("/") else name
    for part in value.split("/"):
        if (
            part in ("", ".", "..")
            or part[-1:] in (".", " ")
            or part.split(".", 1)[0].casefold() in _DEVICES
        ):
            raise ValueError("unsafe archive member path")
    return value


def member_identity(name: str, *, allow_directory: bool = True) -> str:
    return unicodedata.normalize(
        "NFC", portable_member_name(name, allow_directory=allow_directory)
    ).casefold()


def reject_path_links(path: Path) -> None:
    """Inspect one image per original component; no pinned-handle claim."""
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except (FileNotFoundError, NotADirectoryError):
            # Missing descendants do not excuse a linked ancestor.
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(
            info, "st_reparse_tag", None
        ) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1):
            raise ValueError("linked archive/source input refused")


def read_archive_bytes(path: Path, limits: ArchiveLimits = DEFAULT_LIMITS) -> bytearray:
    reject_path_links(path)
    if not path.is_file():
        raise ValueError("archive input must be a regular file")
    return read_bounded_bytes(path, max_bytes=limits.max_archive_bytes)


def read_stream_bytes(
    stream, *, max_bytes: int, expected_size: int | None = None
) -> bytearray:
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("stream byte budget must be a nonnegative integer")
    if expected_size is not None and (
        type(expected_size) is not int or not 0 <= expected_size <= max_bytes
    ):
        raise ValueError("declared archive member exceeds byte budget")
    data = bytearray()
    while len(data) <= max_bytes:
        chunk = stream.read(min(65_536, max_bytes + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    if len(data) > max_bytes:
        raise ValueError("archive expanded byte budget exceeded")
    if expected_size is not None and len(data) != expected_size:
        raise ValueError("archive member size differs from declared size")
    return data


def preflight_zip_directory(
    raw: bytes | bytearray,
    *,
    max_members: int = 10_000,
    max_directory_bytes: int = 4 * 1024 * 1024,
    max_name_bytes: int = 4096,
) -> None:
    """Bound the standard single-disk non-ZIP64 directory before ZipFile parsing."""
    for value, ceiling in (
        (max_members, 100_000),
        (max_directory_bytes, 32 * 1024 * 1024),
        (max_name_bytes, 4096),
    ):
        if type(value) is not int or not 1 <= value <= ceiling:
            raise ValueError("invalid ZIP directory budget")
    end = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 65_557))
    if end < 0 or end + 22 > len(raw):
        raise ValueError("ZIP end record missing")
    _, disk, directory_disk, disk_count, count, size, offset, comment = (
        struct.unpack_from("<4s4H2LH", raw, end)
    )
    if (
        disk
        or directory_disk
        or disk_count != count
        or count > max_members
        or count == 0xFFFF
        or size == 0xFFFFFFFF
        or offset == 0xFFFFFFFF
        or offset + size != end
        or size > max_directory_bytes
        or end + 22 + comment != len(raw)
    ):
        raise ValueError("ZIP directory budget or supported format violated")
    position = offset
    observed = 0
    while position < end:
        if (
            observed >= max_members
            or position + 46 > end
            or raw[position : position + 4] != b"PK\x01\x02"
        ):
            raise ValueError("ZIP central directory is malformed or oversized")
        name, extra, note = struct.unpack_from("<3H", raw, position + 28)
        if name > max_name_bytes:
            raise ValueError("ZIP member name budget exceeded")
        position += 46 + name + extra + note
        observed += 1
    if position != end or observed != count:
        raise ValueError("ZIP directory denominator mismatch")


@contextmanager
def validated_zip(raw: bytes | bytearray, limits: ArchiveLimits = DEFAULT_LIMITS):
    if len(raw) > limits.max_archive_bytes:
        raise ValueError("compressed archive byte budget exceeded")
    preflight_zip_directory(
        raw,
        max_members=limits.max_members,
        max_directory_bytes=limits.max_directory_bytes,
        max_name_bytes=limits.max_name_bytes,
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        seen = set()
        expanded = 0
        for info in infos:
            portable_member_name(info.orig_filename, max_bytes=limits.max_name_bytes)
            identity = member_identity(info.orig_filename)
            if identity in seen:
                raise ValueError("duplicate archive member or portable path alias")
            seen.add(identity)
            mode = stat.S_IFMT(info.external_attr >> 16)
            if (
                mode not in (0, stat.S_IFREG, stat.S_IFDIR)
                or (mode == stat.S_IFDIR) != info.is_dir()
                and mode != 0
            ):
                raise ValueError("archive link or unsupported member type")
            if info.flag_bits & 1 or info.compress_type not in (
                zipfile.ZIP_STORED,
                zipfile.ZIP_DEFLATED,
            ):
                raise ValueError("unsupported or encrypted ZIP member")
            if (
                info.file_size > limits.max_member_bytes
                or info.is_dir()
                and info.file_size
            ):
                raise ValueError("archive member byte budget exceeded")
            expanded += info.file_size
            if expanded > limits.max_expanded_bytes:
                raise ValueError("archive aggregate expanded byte budget exceeded")
        yield (
            archive,
            tuple(sorted(infos, key=lambda info: member_identity(info.filename))),
        )


def _pax_metadata(data: bytes | bytearray) -> None:
    """Admit bounded metadata keys that cannot redirect TAR framing or links."""
    position = 0
    records = 0
    allowed = {
        b"path",
        b"mtime",
        b"atime",
        b"ctime",
        b"uid",
        b"gid",
        b"uname",
        b"gname",
    }
    while position < len(data):
        space = data.find(b" ", position, min(len(data), position + 10))
        if space < 0:
            raise ValueError("malformed PAX metadata length")
        digits = data[position:space]
        if not digits or not digits.isdigit():
            raise ValueError("malformed PAX metadata length")
        size = int(digits)
        end = position + size
        if end > len(data) or end <= space + 2 or data[end - 1] != 10:
            raise ValueError("malformed PAX metadata record")
        key, separator, value = data[space + 1 : end - 1].partition(b"=")
        if not separator or bytes(key) not in allowed or len(value) > 4096:
            raise ValueError("unsupported PAX metadata key or value budget")
        if key == b"path":
            portable_member_name(value.decode("utf-8"))
        position = end
        records += 1
        if records > 256:
            raise ValueError("PAX metadata record budget exceeded")


def _preflight_tar(raw: bytes | bytearray, limits: ArchiveLimits) -> None:
    position = 0
    headers = 0
    extension_headers = 0
    while position + 512 <= len(raw):
        header = raw[position : position + 512]
        if not any(header):
            if extension_headers:
                raise ValueError("TAR extension header has no following member")
            if (
                len(raw) - position < 1024
                or raw.count(0, position) != len(raw) - position
            ):
                raise ValueError("TAR end padding is malformed")
            return
        headers += 1
        if headers > limits.max_members:
            raise ValueError("TAR member/header budget exceeded")
        field = header[124:136]
        size = (
            (int.from_bytes(field, "big") & ((1 << 95) - 1))
            if field[0] & 128
            else int(field.rstrip(b"\0 ").lstrip(b" ") or b"0", 8)
        )
        kind = header[156:157]
        if kind not in (b"0", b"\0", b"5", b"x", b"g", b"L"):
            raise ValueError("TAR link or unsupported member type")
        # tarfile processes extension headers recursively. Byte and total-header
        # limits alone cannot bound that parser stack before it is allocated.
        extension_headers = extension_headers + 1 if kind in (b"x", b"g", b"L") else 0
        if extension_headers > 16:
            raise ValueError("TAR extension header nesting budget exceeded")
        ceiling = (
            65536
            if kind in (b"x", b"g")
            else limits.max_name_bytes
            if kind == b"L"
            else limits.max_member_bytes
        )
        if size > ceiling or kind == b"5" and size:
            raise ValueError("TAR member byte budget exceeded")
        end = position + 512 + ((size + 511) // 512) * 512
        if end > len(raw):
            raise ValueError("truncated TAR member")
        if kind in (b"x", b"g"):
            _pax_metadata(raw[position + 512 : position + 512 + size])
        position = end
    raise ValueError("TAR end record missing")


@contextmanager
def validated_sdist(raw: bytes | bytearray, limits: ArchiveLimits = DEFAULT_LIMITS):
    """Bound the entire gzip expansion and TAR headers before metadata parsing."""
    if len(raw) > limits.max_archive_bytes:
        raise ValueError("compressed archive byte budget exceeded")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
        expanded = read_stream_bytes(compressed, max_bytes=limits.max_expanded_bytes)
    _preflight_tar(expanded, limits)
    with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as archive:
        members = []
        seen = set()
        declared = 0
        for member in archive:
            if len(members) >= limits.max_members:
                raise ValueError("TAR member budget exceeded")
            portable_member_name(member.name, max_bytes=limits.max_name_bytes)
            identity = member_identity(member.name)
            if identity in seen:
                raise ValueError("duplicate archive member or portable path alias")
            seen.add(identity)
            if (
                not (member.isfile() or member.isdir())
                or member.issym()
                or member.islnk()
            ):
                raise ValueError("TAR link or unsupported member type")
            if member.size < 0 or member.size > limits.max_member_bytes:
                raise ValueError("TAR member byte budget exceeded")
            declared += member.size
            if declared > limits.max_expanded_bytes:
                raise ValueError("TAR aggregate expanded byte budget exceeded")
            members.append(member)
        yield (
            archive,
            tuple(sorted(members, key=lambda member: member_identity(member.name))),
        )
