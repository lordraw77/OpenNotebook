"""7z and RAR archives: detection, hardened extraction and limits."""

from __future__ import annotations

import io

import py7zr
import pytest

from opennotebook.ingestion.archives import ArchiveRejected, Limits, Member, Skipped, iter_members
from opennotebook.ingestion.parsers import sniff
from tests.rar_fixture import make_rar5

LIMITS = Limits(10**8, 100, 100, 10**8)
FILES = {"src/radio.c": b"int radio(void) { return 1; }\n", "docs/readme.md": b"# Radio\n\nDriver notes.\n"}


def make_7z(files: dict[str, bytes], **kwargs) -> bytes:
    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, "w", **kwargs) as z:
        for name, data in files.items():
            z.writestr(data, name)
    return buf.getvalue()


def test_7z_is_detected_and_extracted():
    data = make_7z(FILES)
    sniffed = sniff(data, "firmware.7z")
    assert (sniffed.format, sniffed.kind) == ("7z", "archive")
    members = {m.path: m.data for m in iter_members(data, "7z", LIMITS) if isinstance(m, Member)}
    assert members == FILES


def test_rar_is_detected_and_extracted():
    data = make_rar5(FILES)
    sniffed = sniff(data, "firmware.rar")
    assert (sniffed.format, sniffed.kind) == ("rar", "archive")
    members = {m.path: m.data for m in iter_members(data, "rar", LIMITS) if isinstance(m, Member)}
    assert members == FILES


def test_unsafe_names_are_skipped_in_rar():
    data = make_rar5({"ok.txt": b"fine", "../evil.sh": b"rm -rf /", "/etc/passwd": b"x"})
    items = list(iter_members(data, "rar", LIMITS))
    assert [i.path for i in items if isinstance(i, Member)] == ["ok.txt"]
    assert any(isinstance(i, Skipped) and i.reason == "unsafe path" for i in items)


def test_7z_bomb_file_count_and_total_are_rejected():
    bomb = make_7z({"zeros.bin": bytes(30 * 1024 * 1024)})
    with pytest.raises(ArchiveRejected, match="ratio"):
        list(iter_members(bomb, "7z", LIMITS))
    many = make_7z({f"f{i}.txt": b"x" for i in range(5)})
    with pytest.raises(ArchiveRejected, match="more than 3 files"):
        list(iter_members(many, "7z", Limits(10**8, 3, 100, 10**8)))
    with pytest.raises(ArchiveRejected, match="MB uncompressed"):
        list(iter_members(make_7z({"a.txt": b"y" * 5000}), "7z", Limits(1000, 10, 10**6, 10**8)))


@pytest.mark.parametrize(
    "fmt, data", [("7z", b"7z\xbc\xaf\x27\x1c\x00\x04" + b"\x00" * 64), ("rar", b"Rar!\x1a\x07\x01\x00junk")]
)
def test_corrupted_archives_are_rejected(fmt, data):
    with pytest.raises(ArchiveRejected):
        list(iter_members(data, fmt, LIMITS))


def test_encrypted_7z_members_are_not_extracted():
    data = make_7z({"secret.txt": b"classified"}, password="pw")
    items = list(iter_members(data, "7z", LIMITS))
    assert not any(isinstance(i, Member) for i in items)
