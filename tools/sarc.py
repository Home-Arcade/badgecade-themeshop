#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
"""Read and write Nintendo SARC archives (little-endian, as Badge Arcade uses)."""

from __future__ import annotations

import struct

HASH_MULTIPLIER = 0x65


def name_hash(name: str, multiplier: int = HASH_MULTIPLIER) -> int:
    value = 0
    for byte in name.encode("utf-8"):
        value = (value * multiplier + (byte if byte < 0x80 else byte - 0x100)) & 0xFFFFFFFF
    return value


def read(data: bytes) -> tuple[dict[str, bytes], dict[str, int]]:
    """Return {name: contents} plus each file's original start alignment."""
    if data[:4] != b"SARC":
        raise ValueError("not a SARC archive")
    header_len, bom = struct.unpack_from("<HH", data, 4)
    if bom != 0xFEFF:
        raise ValueError("only little-endian SARC is supported")
    data_offset = struct.unpack_from("<I", data, 0xC)[0]
    sfat = header_len
    count = struct.unpack_from("<H", data, sfat + 6)[0]
    names_base = sfat + 12 + count * 16 + 8
    files: dict[str, bytes] = {}
    alignment: dict[str, int] = {}
    for i in range(count):
        _, attr, start, end = struct.unpack_from("<IIII", data, sfat + 12 + i * 16)
        offset = names_base + (attr & 0xFFFFFF) * 4  # 24 bits: a big archive (allbadge) has names past 0xFFFF * 4
        name = data[offset:data.index(b"\0", offset)].decode("utf-8")
        files[name] = data[data_offset + start:data_offset + end]
        alignment[name] = next(a for a in (0x2000, 0x1000, 0x800, 0x400, 0x200, 0x100, 0x80, 0x40, 0x20, 0x10, 8, 4) if (data_offset + start) % a == 0)
    return files, alignment


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def write(files: dict[str, bytes], alignment: dict[str, int] | None = None) -> bytes:
    """Build a SARC; each file keeps its given alignment (default 4)."""
    alignment = alignment or {}
    entries = sorted(files, key=name_hash)
    names = b""
    name_offsets = {}
    for name in entries:
        name_offsets[name] = len(names) // 4
        names += name.encode("utf-8") + b"\0"
        names += b"\0" * (-len(names) % 4)

    count = len(entries)
    header_size = 0x14 + 0x0C + count * 0x10 + 0x08 + len(names)
    # absolute positions so each file lands on its original alignment
    position = _align(header_size, max([alignment.get(n, 4) for n in entries] + [4]))
    data_offset = position
    layout = []
    for name in entries:
        position = _align(position, alignment.get(name, 4))
        layout.append((name, position - data_offset, position - data_offset + len(files[name])))
        position += len(files[name])

    out = bytearray(position)
    struct.pack_into("<4sHHIIHH", out, 0, b"SARC", 0x14, 0xFEFF, position, data_offset, 0x0100, 0)
    struct.pack_into("<4sHHI", out, 0x14, b"SFAT", 0x0C, count, HASH_MULTIPLIER)
    for i, (name, start, end) in enumerate(layout):
        struct.pack_into("<IIII", out, 0x20 + i * 16, name_hash(name), 0x01000000 | name_offsets[name], start, end)
    sfnt = 0x20 + count * 16
    struct.pack_into("<4sHH", out, sfnt, b"SFNT", 0x08, 0)
    out[sfnt + 8:sfnt + 8 + len(names)] = names
    for name, start, end in layout:
        out[data_offset + start:data_offset + end] = files[name]
    return bytes(out)
