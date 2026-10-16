#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
"""A small baseline JPEG encoder (no libraries), for the Theme Shop's theme
preview pictures. 4:4:4 YCbCr with the standard JPEG (Annex K) quantisation
and Huffman tables.

    import jpeg; data = jpeg.encode(image, quality=90)   # make_theme.Image
"""

from __future__ import annotations

import math
import struct

_ZIGZAG = [
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
]
_LUMA_Q = [
    16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99,
]
_CHROMA_Q = [
    17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99, 47, 66, 99, 99, 99, 99, 99, 99,
] + [99] * 32
# (code lengths 1..16, symbols) for DC/AC, luminance/chrominance
_DC_LUMA = ([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0], list(range(12)))
_DC_CHROMA = ([0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0], list(range(12)))
_AC_LUMA = ([0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D], bytes.fromhex(
    "01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a"
    "434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9"
    "aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9fa"))
_AC_CHROMA = ([0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77], bytes.fromhex(
    "000102031104052131061241510761711322328108144291a1b1c109233352f0156272d10a162434e125f11718191a262728292a35363738"
    "393a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788898a92939495969798999aa2a3a4a5a6"
    "a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9fa"))
_COS = [[math.cos((2 * x + 1) * u * math.pi / 16) * (math.sqrt(0.5) if u == 0 else 1.0) / 2 for x in range(8)] for u in range(8)]


def _codes(table: tuple[list[int], list[int] | bytes]) -> dict[int, tuple[int, int]]:
    lengths, symbols = table
    out, code, k = {}, 0, 0
    for length in range(1, 17):
        for _ in range(lengths[length - 1]):
            out[symbols[k]] = (code, length)
            code += 1
            k += 1
        code <<= 1
    return out


def _scaled(table: list[int], quality: int) -> list[int]:
    scale = 5000 // quality if quality < 50 else 200 - quality * 2
    return [min(255, max(1, (q * scale + 50) // 100)) for q in table]


class _Bits:
    def __init__(self) -> None:
        self.out = bytearray()
        self.acc = 0
        self.n = 0

    def put(self, value: int, length: int) -> None:
        self.acc = (self.acc << length) | (value & ((1 << length) - 1))
        self.n += length
        while self.n >= 8:
            self.n -= 8
            byte = (self.acc >> self.n) & 0xFF
            self.out.append(byte)
            if byte == 0xFF:
                self.out.append(0)

    def flush(self) -> bytes:
        if self.n:
            self.put((1 << (8 - self.n)) - 1, 8 - self.n)
        return bytes(self.out)


def _magnitude(value: int) -> tuple[int, int]:
    size = abs(value).bit_length()
    return size, value if value >= 0 else value + (1 << size) - 1


def _block(bits: _Bits, samples: list[float], quant: list[int], previous_dc: int, dc: dict, ac: dict) -> int:
    rows = [[sum(_COS[u][x] * samples[y * 8 + x] for x in range(8)) for u in range(8)] for y in range(8)]
    coefficients = [sum(_COS[v][y] * rows[y][u] for y in range(8)) for v in range(8) for u in range(8)]
    zz = [int(round(coefficients[_ZIGZAG[i]] / quant[_ZIGZAG[i]])) for i in range(64)]
    size, value = _magnitude(zz[0] - previous_dc)
    bits.put(*dc[size])
    if size:
        bits.put(value, size)
    run = 0
    for coefficient in zz[1:]:
        if coefficient == 0:
            run += 1
            continue
        while run > 15:
            bits.put(*ac[0xF0])
            run -= 16
        size, value = _magnitude(coefficient)
        bits.put(*ac[(run << 4) | size])
        bits.put(value, size)
        run = 0
    if run:
        bits.put(*ac[0x00])
    return zz[0]


def encode(image, quality: int = 90) -> bytes:
    """``image``: make_theme.Image (RGBA pixels; alpha is ignored)."""
    width, height = image.width, image.height
    qy, qc = _scaled(_LUMA_Q, quality), _scaled(_CHROMA_Q, quality)
    dc_l, dc_c, ac_l, ac_c = _codes(_DC_LUMA), _codes(_DC_CHROMA), _codes(_AC_LUMA), _codes(_AC_CHROMA)
    planes = ([], [], [])
    for r, g, b, _ in image.pixels:
        planes[0].append(0.299 * r + 0.587 * g + 0.114 * b - 128)
        planes[1].append(-0.168736 * r - 0.331264 * g + 0.5 * b)
        planes[2].append(0.5 * r - 0.418688 * g - 0.081312 * b)
    bits, previous = _Bits(), [0, 0, 0]
    for by in range(0, height, 8):
        for bx in range(0, width, 8):
            for c in range(3):
                plane = planes[c]
                samples = [plane[min(by + y, height - 1) * width + min(bx + x, width - 1)] for y in range(8) for x in range(8)]
                previous[c] = _block(bits, samples, qy if c == 0 else qc, previous[c],
                                     dc_l if c == 0 else dc_c, ac_l if c == 0 else ac_c)
    out = bytearray(b"\xFF\xD8")
    out += b"\xFF\xE0" + struct.pack(">H5sBBBHHBB", 16, b"JFIF\0", 1, 1, 0, 1, 1, 0, 0)
    for index, table in ((0, qy), (1, qc)):
        out += b"\xFF\xDB" + struct.pack(">HB", 67, index) + bytes(table[_ZIGZAG[i]] for i in range(64))
    out += b"\xFF\xC0" + struct.pack(">HBHHB", 17, 8, height, width, 3)
    out += bytes([1, 0x11, 0, 2, 0x11, 1, 3, 0x11, 1])
    for klass, index, (lengths, symbols) in ((0, 0, _DC_LUMA), (1, 0, _AC_LUMA), (0, 1, _DC_CHROMA), (1, 1, _AC_CHROMA)):
        out += b"\xFF\xC4" + struct.pack(">HB", 3 + 16 + len(symbols), (klass << 4) | index) + bytes(lengths) + bytes(symbols)
    out += b"\xFF\xDA" + struct.pack(">HB", 12, 3) + bytes([1, 0x00, 2, 0x11, 3, 0x11]) + bytes([0, 63, 0])
    out += bits.flush() + b"\xFF\xD9"
    return bytes(out)
