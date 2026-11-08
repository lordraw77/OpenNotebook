"""Hardened archive extraction (ZIP and TAR, optionally gzip/bzip2/xz compressed).

Defences (threat model: zip bombs, path traversal, links, device files):
  - the archive is read from memory and never extracted to disk;
  - member names are normalized; absolute paths, drive letters and `..` components are rejected;
  - only regular files are read: directories, symlinks, hard links and devices are skipped;
  - actual bytes read are counted (declared sizes may lie) against the total uncompressed limit and the
    compression ratio; exceeding a limit rejects the whole archive;
  - the number of files is limited; nested archives are expanded by their own job, up to a maximum depth.
"""

from __future__ import annotations

import io
import posixpath
import stat
import tarfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass

from opennotebook.ingestion.parsers import UnsupportedContent

READ_BLOCK = 1024 * 1024


class ArchiveRejected(UnsupportedContent):
    """The archive exceeds a safety limit or is malformed; nothing is extracted."""


@dataclass
class Limits:
    max_total_bytes: int
    max_files: int
    max_ratio: int
    max_file_bytes: int


@dataclass
class Member:
    path: str
    data: bytes


@dataclass
class Skipped:
    path: str
    reason: str


def safe_path(name: str) -> str | None:
    """Normalized relative POSIX path, or None when the name is unsafe."""
    name = name.replace("\\", "/")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    if any("\x00" in p for p in parts):
        return None
    return posixpath.join(*parts)


class _Budget:
    def __init__(self, limits: Limits, archive_size: int) -> None:
        self.limits = limits
        self.archive_size = max(1, archive_size)
        self.total = 0
        self.files = 0

    def add_file(self) -> None:
        self.files += 1
        if self.files > self.limits.max_files:
            raise ArchiveRejected(f"Archive rejected: more than {self.limits.max_files} files")

    def read(self, stream: io.BufferedIOBase | object) -> bytes | None:
        """Read one member; None when the member alone is larger than the per-file limit (skipped)."""
        out = bytearray()
        while True:
            block = stream.read(READ_BLOCK)  # type: ignore[attr-defined]
            if not block:
                break
            out += block
            self.total += len(block)
            if self.total > self.limits.max_total_bytes:
                limit_mb = self.limits.max_total_bytes // (1024 * 1024)
                raise ArchiveRejected(f"Archive rejected: more than {limit_mb} MB uncompressed")
            if self.total > self.archive_size * self.limits.max_ratio and self.total > 10 * READ_BLOCK:
                raise ArchiveRejected(
                    f"Archive rejected: compression ratio above {self.limits.max_ratio} (possible zip bomb)"
                )
            if len(out) > self.limits.max_file_bytes:
                # keep counting the rest towards the total, but do not keep it in memory
                while block := stream.read(READ_BLOCK):  # type: ignore[attr-defined]
                    self.total += len(block)
                    if self.total > self.limits.max_total_bytes:
                        raise ArchiveRejected("Archive rejected: uncompressed size limit exceeded")
                return None
        return bytes(out)


def iter_members(data: bytes, fmt: str, limits: Limits) -> Iterator[Member | Skipped]:
    budget = _Budget(limits, len(data))
    if fmt == "zip":
        yield from _zip(data, budget)
    elif fmt == "tar":
        yield from _tar(data, budget)
    else:
        raise ArchiveRejected(f"Unsupported archive format {fmt}")


def _zip(data: bytes, budget: _Budget) -> Iterator[Member | Skipped]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveRejected("Corrupted ZIP archive") from exc
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = safe_path(info.filename)
            if path is None:
                yield Skipped(info.filename[:300], "unsafe path")
                continue
            file_type = stat.S_IFMT(info.external_attr >> 16)  # 0 when the creator stored no Unix mode
            if file_type and file_type != stat.S_IFREG:
                yield Skipped(path, "link or special file")
                continue
            if info.flag_bits & 0x1:
                yield Skipped(path, "encrypted")
                continue
            budget.add_file()
            try:
                with archive.open(info) as stream:
                    content = budget.read(stream)
            except ArchiveRejected:
                raise
            except (zipfile.BadZipFile, NotImplementedError, OSError, EOFError) as exc:
                yield Skipped(path, f"unreadable ({exc.__class__.__name__})")
                continue
            if content is None:
                yield Skipped(path, "file too large")
                continue
            yield Member(path, content)


def _tar(data: bytes, budget: _Budget) -> Iterator[Member | Skipped]:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ArchiveRejected("Corrupted TAR archive") from exc
    with archive:
        try:
            for info in archive:  # streaming: members are read in order
                if info.isdir():
                    continue
                path = safe_path(info.name)
                if path is None:
                    yield Skipped(info.name[:300], "unsafe path")
                    continue
                if not info.isreg():
                    yield Skipped(path, "link or special file")
                    continue
                budget.add_file()
                stream = archive.extractfile(info)
                if stream is None:
                    yield Skipped(path, "unreadable")
                    continue
                content = budget.read(stream)
                if content is None:
                    yield Skipped(path, "file too large")
                    continue
                yield Member(path, content)
        except (tarfile.TarError, EOFError, OSError) as exc:
            raise ArchiveRejected(f"Corrupted TAR archive ({exc.__class__.__name__})") from exc
