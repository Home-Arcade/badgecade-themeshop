#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
"""Decrypt and re-encrypt 3DS SpotPass (BOSS) files.

Follows PretendoNetwork/boss-js (src/3ds.ts). The AES key is keyslot 0x38's
normal key, read from the 3DS boot ROM (boot9.bin offset 0xDBD0); it is never
stored in this file. RSA signatures are left zeroed, as Pretendo does: Luma
skips the console's SpotPass signature check.

    python3 tools/boss3ds.py decrypt data.dat out_dir/
    python3 tools/boss3ds.py encrypt out_dir/ new_data.dat

`decrypt` writes container.json (header fields) and payload_N.bin files;
`encrypt` rebuilds a BOSS file from that directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY_MD5 = "86fbc2bb4cb703b2a4c6cc9961319926"
DEFAULT_KEY_FILE = Path(__file__).resolve().parent.parent / "client-patches/dumps/boss_3ds_aes_key.bin"
BOSS_CTR_VER = 0x10001


def load_key(path: Path = DEFAULT_KEY_FILE) -> bytes:
    key = Path(os.environ.get("BADGECADE_BOSS_KEY_FILE", path)).read_bytes()
    if hashlib.md5(key).hexdigest() != KEY_MD5:
        raise SystemExit("BOSS AES key does not match the expected fingerprint")
    return key


def _ctr(key: bytes, iv12: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv12 + b"\x00\x00\x00\x01"))
    return cipher.decryptor().update(data)


def decrypt(data: bytes, key: bytes) -> dict:
    if data[:4] != b"boss":
        raise ValueError("not a BOSS file")
    if struct.unpack_from(">H", data, 0x18)[0] != 2:
        raise ValueError("unknown hash type")
    serial = struct.unpack_from(">Q", data, 0xC)[0]
    iv = data[0x1C:0x28]
    plain = _ctr(key, iv, data[0x28:])

    content_header = plain[:0x132]
    if hashlib.sha256(content_header[:0x12] + b"\x00\x00").digest() != content_header[0x12:0x32]:
        raise ValueError("content header hash mismatch (wrong key?)")
    count = struct.unpack_from(">H", content_header, 0x10)[0]

    payloads = []
    offset = 0x132
    for _ in range(count):
        header = plain[offset:offset + 0x1C]
        program_id, = struct.unpack_from(">Q", header, 0)
        datatype, size, ns_data_id, version = struct.unpack_from(">IIII", header, 0xC)
        content = plain[offset + 0x13C:offset + 0x13C + size]
        if hashlib.sha256(header + b"\x00\x00" + content).digest() != plain[offset + 0x1C:offset + 0x3C]:
            raise ValueError("payload hash mismatch")
        payloads.append({
            "program_id": f"{program_id:016x}",
            "content_datatype": datatype,
            "ns_data_id": ns_data_id,
            "version": version,
            "unknown_08": header[0x8:0xC].hex(),
            "content": content,
        })
        offset += 0x13C + size

    return {
        "serial": serial,
        "flags_byte": content_header[0],
        "header_14": data[0x14:0x1C].hex(),
        "content_header_magic": content_header[:0x10].hex(),
        "payloads": payloads,
    }


def encrypt(container: dict, key: bytes, iv: bytes | None = None) -> bytes:
    payload_blob = b""
    for p in container["payloads"]:
        content = p["content"]
        header = bytearray(0x1C)
        struct.pack_into(">Q", header, 0, int(p["program_id"], 16))
        header[0x8:0xC] = bytes.fromhex(p.get("unknown_08", "00000000"))
        struct.pack_into(">IIII", header, 0xC, p["content_datatype"], len(content), p["ns_data_id"], p["version"])
        digest = hashlib.sha256(bytes(header) + b"\x00\x00" + content).digest()
        payload_blob += bytes(header) + digest + bytes(0x100) + content

    content_header = bytearray(bytes.fromhex(container["content_header_magic"]) + bytes(2))
    struct.pack_into(">H", content_header, 0x10, len(container["payloads"]))
    digest = hashlib.sha256(bytes(content_header) + b"\x00\x00").digest()
    body = bytes(content_header) + digest + bytes(0x100) + payload_blob

    iv = iv or os.urandom(12)
    header = bytearray(0x28)
    header[0:4] = b"boss"
    struct.pack_into(">I", header, 4, BOSS_CTR_VER)
    struct.pack_into(">I", header, 8, 0x28 + len(body))
    struct.pack_into(">Q", header, 0xC, container["serial"])
    header[0x14:0x1C] = bytes.fromhex(container["header_14"])
    header[0x1C:0x28] = iv
    return bytes(header) + _ctr(key, iv, body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decrypt")
    d.add_argument("boss_file", type=Path)
    d.add_argument("out_dir", type=Path)
    e = sub.add_parser("encrypt")
    e.add_argument("in_dir", type=Path)
    e.add_argument("boss_file", type=Path)
    args = parser.parse_args()
    key = load_key()

    if args.cmd == "decrypt":
        container = decrypt(args.boss_file.read_bytes(), key)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        meta = dict(container)
        meta["payloads"] = []
        for i, p in enumerate(container["payloads"]):
            (args.out_dir / f"payload_{i}.bin").write_bytes(p["content"])
            meta["payloads"].append({k: v for k, v in p.items() if k != "content"} | {"file": f"payload_{i}.bin"})
        (args.out_dir / "container.json").write_text(json.dumps(meta, indent=2) + "\n")
        for i, p in enumerate(meta["payloads"]):
            print(f"payload {i}: program {p['program_id']} type {p['content_datatype']} ns_data_id {p['ns_data_id']} "
                  f"version {p['version']} size {len(container['payloads'][i]['content'])}")
    else:
        meta = json.loads((args.in_dir / "container.json").read_text())
        for p in meta["payloads"]:
            p["content"] = (args.in_dir / p.pop("file")).read_bytes()
        args.boss_file.write_bytes(encrypt(meta, key))
        print(f"wrote {args.boss_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
