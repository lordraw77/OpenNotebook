"""Builds minimal RAR5 archives (stored, no compression) for tests: RAR cannot be created with free tools."""

from __future__ import annotations

import zlib

RAR5_SIGNATURE = b"Rar!\x1a\x07\x01\x00"


def _vint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _block(body: bytes, data: bytes = b"") -> bytes:
    size = _vint(len(body))
    crc = zlib.crc32(size + body) & 0xFFFFFFFF
    return crc.to_bytes(4, "little") + size + body + data


def make_rar5(files: dict[str, bytes]) -> bytes:
    out = bytearray(RAR5_SIGNATURE)
    out += _block(_vint(1) + _vint(0) + _vint(0))  # main header, no archive flags
    for name, data in files.items():
        raw_name = name.encode()
        body = (
            _vint(2)  # file header
            + _vint(0x02)  # block flags: data area follows
            + _vint(len(data))  # data size
            + _vint(0x04)  # file flags: CRC32 present
            + _vint(len(data))  # unpacked size
            + _vint(0o100644)  # attributes (Unix regular file)
            + (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "little")
            + _vint(0)  # compression: stored
            + _vint(1)  # host OS: Unix
            + _vint(len(raw_name))
            + raw_name
        )
        out += _block(body, data)
    out += _block(_vint(5) + _vint(0) + _vint(0))  # end of archive
    return bytes(out)
