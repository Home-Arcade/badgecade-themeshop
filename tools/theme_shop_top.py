#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
"""The Theme Shop's start page (thmtop) and featured list (thmlist): BadgeCade's own.

The start page we served was Nintendo's archived one: it points at Nintendo's
featured list 5179 (their theme IDs), which we don't serve, so a console
opening the shop for the first time (New Themes) froze waiting for it. This
builds both from our packs, in the layout of Nintendo's archived files
(archive/themeshop/US/en/thmtop/top.boss and thmlist/5179.boss):

  top (BOSS datatype 0x10001, ns data id 2000000000)
    0x00 01 01 01 00, 0x08 1
    0x10 banner size, 0x14 banner offset (0x100)      408x176 JPEG
    0x28 title, UTF-16, up to 0xE8
    0xE8 featured list name, 0xEC its ns data id
    0xF0 thumbnail size, 0xF4 thumbnail offset        64x48 JPEG

  thmlist/<name> (BOSS datatype 0x10002, ns data id from the top page)
    0x00 01 02 00 00
    0x10 banner size, 0x14 banner offset (0x26F0)     408x176 JPEG
    0x18 two entries of 0x1368 bytes:
      0x00 details id, 0x04 theme id (item code), 0x08 content index (numbers)
      0x28 name (UTF-16, 0x80), 0xE8 publisher (UTF-16, 0x80)
      0x168 icon, 48x48 RGB565 tiled (as in the pack)

Both archived lists hold exactly two themes, so the featured list does too:
the themes named in themes/featured.json ({"featured": [<item code>, ...]}),
or else the two most recently added.

    python3 tools/theme_shop_top.py          # writes content/THEMESHOP/thmtop and thmlist
    python3 tools/theme_shop_top.py --test   # start page for the test console only (thmtop/ZZ)
"""

from __future__ import annotations

import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boss3ds  # noqa: E402
import make_theme  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "content" / "THEMESHOP"
FEATURED = ROOT / "themes" / "featured.json"
PROGRAM = "000400100002cd00"  # the Theme Shop
LIST_NAME = 9001              # our featured list's file name (Nintendo's was 5179)
LIST_DATA_ID = 9001
TOP_DATA_ID = 2000000000      # as Nintendo's
ENTRY = 0x1368
# the shop keeps its original look: banner, thumbnail and title come from
# Nintendo's archived start page (kept out of git, like the other Nintendo files)
ORIGINAL_TOP = Path("/opt/badgecade/archive/themeshop/US/en/thmtop/top.boss")
TITLE = "Welcome to the Theme Shop"


def _utf16(text: str, size: int) -> bytes:
    return text.encode("utf-16-le")[:size - 2].ljust(size, b"\0")


def _magick(args: list[str]) -> bytes:
    return subprocess.run(["convert", *args], capture_output=True, check=True).stdout


def original_pictures() -> tuple[bytes, bytes]:
    """(408x176 banner, 64x48 thumbnail) of Nintendo's archived start page."""
    content = boss3ds.decrypt(ORIGINAL_TOP.read_bytes(), boss3ds.load_key())["payloads"][0]["content"]
    size, offset = struct.unpack_from("<II", content, 0x10)
    thumb_size, thumb_offset = struct.unpack_from("<II", content, 0xF0)
    return content[offset:offset + size], content[thumb_offset:thumb_offset + thumb_size]


def _icon(theme: dict) -> bytes:
    image = make_theme.resize(make_theme.read_png(ROOT / theme["icon"]), 48, 48)
    return make_theme.rgb565_tiled(image, 48, 48)


def all_themes() -> list[dict]:
    paths = sorted((ROOT / "themes").glob("pack-*8f0[0-9].json"))
    return [t for path in paths for t in json.loads(path.read_text())["themes"]]


def featured(themes: list[dict]) -> list[dict]:
    by_code = {t["item_code"]: t for t in themes}
    chosen = []
    if FEATURED.exists():
        chosen = [by_code[c] for c in json.loads(FEATURED.read_text()).get("featured", []) if c in by_code]
    for theme in sorted(themes, key=lambda t: t.get("item_id", 0), reverse=True):  # newest first
        if len(chosen) >= 2:
            break
        if theme not in chosen:
            chosen.append(theme)
    return chosen[:2]


def list_payload(themes: list[dict], picture: bytes) -> bytes:
    if len(themes) != 2:
        raise SystemExit("the featured list needs two themes")
    head = bytearray(0x18)
    head[0:4] = bytes([1, 2, 0, 0])
    entries = bytearray()
    for theme in themes:
        entry = bytearray(ENTRY)
        struct.pack_into("<III", entry, 0, int(theme["details_id"]), int(theme["item_code"]), theme["index"])
        entry[0x28:0xA8] = _utf16(theme["name"], 0x80)
        entry[0xE8:0x168] = _utf16(theme.get("publisher", "BadgeCade"), 0x80)
        entry[0x168:0x168 + 0x1200] = _icon(theme)
        entries += entry
    body = bytes(head) + bytes(entries)
    offset = (len(body) + 0xF) & ~0xF  # 0x26F0, as Nintendo's
    struct.pack_into("<II", head, 0x10, len(picture), offset)
    body = (bytes(head) + bytes(entries)).ljust(offset, b"\0")
    return body + picture


def top_payload(picture: bytes, thumb: bytes) -> bytes:
    head = bytearray(0x100)
    head[0:4] = bytes([1, 1, 1, 0])
    struct.pack_into("<I", head, 0x08, 1)
    struct.pack_into("<II", head, 0x10, len(picture), 0x100)
    head[0x28:0xE8] = _utf16(TITLE, 0xC0)
    second = (0x100 + len(picture) + 0xF) & ~0xF
    struct.pack_into("<IIII", head, 0xE8, LIST_NAME, LIST_DATA_ID, len(thumb), second)
    return (bytes(head) + picture).ljust(second, b"\0") + thumb


def _boss(content: bytes, datatype: int, data_id: int, version: int, key: bytes) -> bytes:
    return boss3ds.encrypt({
        "serial": int(time.time()),
        "header_14": "0001000000020002",
        "content_header_magic": "80" + "00" * 15,
        "payloads": [{"program_id": PROGRAM, "content_datatype": datatype, "ns_data_id": data_id,
                      "version": version, "content": content}],
    }, key)


def write(test: bool = False) -> list[Path]:
    """test: the start page goes to thmtop/ZZ/, which the proxy serves only to
    the test console (THEME_TEST_CLIENT_IPS); everyone else keeps thmtop/ALL/."""
    themes = all_themes()
    chosen = featured(themes)
    picture, thumb = original_pictures()
    key = boss3ds.load_key()
    version = int(time.time()) // 60 % 1000000  # newer on every build, so consoles fetch it again
    top = OUT / "thmtop" / ("ZZ" if test else "ALL") / "en" / "top"
    top.parent.mkdir(parents=True, exist_ok=True)
    lst = OUT / "thmlist" / "ALL" / "en" / str(LIST_NAME)
    lst.parent.mkdir(parents=True, exist_ok=True)
    lst.write_bytes(_boss(list_payload(chosen, picture), 0x10002, LIST_DATA_ID, version, key))
    top.write_bytes(_boss(top_payload(picture, thumb), 0x10001, TOP_DATA_ID, version, key))
    return [top, lst]


def main() -> int:
    for path in write(test="--test" in sys.argv[1:]):
        print(f"{path}  {path.stat().st_size} bytes")
    print("featured:", ", ".join(t["name"] for t in featured(all_themes())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
