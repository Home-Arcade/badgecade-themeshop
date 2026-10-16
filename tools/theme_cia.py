#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
"""Pack BadgeCade's theme pack (cdn/<title id>/, built by theme_pack.py) as a
CIA with its themes included, to install with FBI instead of the Theme Shop.

Layout per 3dbrew's CIA page: 0x2020 header (section sizes, content index
bit field), then the certificate chain (CA00000003, XS0000000c,
CP0000000b), the ticket, the TMD and the contents, each 0x40-aligned. The
ticket is shopdeck's base ticket for the pack's title with rights to every
content in the CIA; signatures are dummies (Luma3DS's signature patches).

    python3 tools/theme_cia.py 0004008C00008F09 -o cdn/0004008C00008F09/badgecade.cia
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CERTS = ROOT / "tools" / "certs"
SHOPDECK = ROOT.parent / "shopdeck"


def _align(data: bytes, size: int = 0x40) -> bytes:
    return data + bytes(-len(data) % size)


def cert_chain() -> bytes:
    tmd_chain = (CERTS / "tmd_cert_chain.bin").read_bytes()   # CP0000000b + CA00000003
    cp, ca = tmd_chain[:0x300], tmd_chain[0x300:]
    template = (SHOPDECK / "templates" / "ecs" / "getAccountETickets.xml").read_text()
    xs = next(c for c in (base64.b64decode(v) for v in re.findall(r"<Certs>([^<]+)</Certs>", template)) if b"XS0000000c" in c)
    return ca + xs + cp


def ticket(title_id: int, indexes: list[int]) -> bytes:
    tik = bytearray((SHOPDECK / "basetik.bin").read_bytes())
    struct.pack_into(">Q", tik, 0x1D0, int.from_bytes(b"\x00\x04" + os.urandom(6), "big"))  # ticket id
    struct.pack_into(">I", tik, 0x1D8, 0)              # console id: any console
    struct.pack_into(">Q", tik, 0x1DC, title_id)
    struct.pack_into(">I", tik, 0x21C, 0)              # eShop account id
    rights = bytearray(0x80)                           # one bit per content index, lowest bit first
    for index in indexes:
        rights[index // 8] |= 1 << (index % 8)
    tik[0x2D0:0x350] = rights
    return bytes(tik)


def build(title_id: str) -> bytes:
    folder = ROOT / "cdn" / title_id.upper()
    full_tmd = (folder / "tmd.bin").read_bytes()
    count = struct.unpack_from(">H", full_tmd, 0x1DE)[0]
    tmd = full_tmd[:0xB04 + 0x30 * count]               # without the CDN certificate chain
    records = [struct.unpack_from(">IHHQ", tmd, 0xB04 + 0x30 * n) for n in range(count)]
    contents = b""
    bitmap = bytearray(0x2000)
    for content_id, index, _, size in records:
        data = (folder / f"{content_id:08X}.app").read_bytes()
        if len(data) != size:
            raise RuntimeError(f"content {content_id:08X} size does not match the TMD")
        contents += data
        bitmap[index >> 3] |= 0x80 >> (index & 7)
    certs, tik = cert_chain(), ticket(int(title_id, 16), [index for _, index, _, _ in records])
    header = struct.pack("<IHHIIIIQ", 0x2020, 0, 0, len(certs), len(tik), len(tmd), 0, len(contents)) + bytes(bitmap)
    return _align(header) + _align(certs) + _align(tik) + _align(tmd) + contents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("title_id")
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    data = build(args.title_id)
    args.output.write_bytes(data)
    print(f"{args.output}  {len(data)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
