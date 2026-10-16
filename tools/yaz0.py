# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
"""Yaz0 (Nintendo .szs) decompression."""


def decompress(data: bytes) -> bytes:
    if data[:4] != b"Yaz0":
        raise ValueError("not Yaz0 data")
    size = int.from_bytes(data[4:8], "big")
    out = bytearray()
    src = 16
    while len(out) < size:
        header = data[src]
        src += 1
        for bit in range(7, -1, -1):
            if len(out) >= size:
                break
            if header & (1 << bit):
                out.append(data[src])
                src += 1
            else:
                b1, b2 = data[src], data[src + 1]
                src += 2
                distance = ((b1 & 0x0F) << 8 | b2) + 1
                length = b1 >> 4
                if length == 0:
                    length = data[src] + 0x12
                    src += 1
                else:
                    length += 2
                for _ in range(length):
                    out.append(out[-distance])
    return bytes(out)


def compress(data: bytes) -> bytes:
    """Yaz0 compression (greedy matching over the last 4 KB), readable by
    decompress() above and by the game."""
    out = bytearray(b"Yaz0" + len(data).to_bytes(4, "big") + bytes(8))
    heads: dict[bytes, list[int]] = {}
    pos, size = 0, len(data)
    while pos < size:
        flags_at = len(out)
        out.append(0)
        flags = 0
        for bit in range(7, -1, -1):
            if pos >= size:
                break
            best_len, best_dist = 0, 0
            key = data[pos:pos + 3]
            if len(key) == 3:
                for start in reversed(heads.get(key, [])[-64:]):
                    dist = pos - start
                    if dist > 0x1000:
                        break
                    length = 3
                    limit = min(0x111, size - pos)
                    while length < limit and data[start + length] == data[pos + length]:
                        length += 1
                    if length > best_len:
                        best_len, best_dist = length, dist
                        if length == limit:
                            break
            if best_len >= 3:
                d = best_dist - 1
                if best_len >= 0x12:
                    out += bytes((d >> 8, d & 0xFF, best_len - 0x12))
                else:
                    out += bytes((((best_len - 2) << 4) | (d >> 8), d & 0xFF))
                for p in range(pos, pos + best_len):
                    heads.setdefault(data[p:p + 3], []).append(p)
                pos += best_len
            else:
                flags |= 1 << bit
                out.append(data[pos])
                heads.setdefault(key, []).append(pos)
                pos += 1
        out[flags_at] = flags
    return bytes(out)
