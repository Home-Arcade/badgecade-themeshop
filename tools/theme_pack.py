#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
"""Build BadgeCade's HOME Menu theme pack (DLC) for the Theme Shop.

A theme pack is a DLC title (BadgeCade uses 0004008C00008F09 in the USA,
a slot Nintendo never used, so it can't touch anyone's bought themes):

    content 0   NCCH, RomFS: MetaDataContentHeader.bin,
                ContentInfoArchive_USA_<lang>.bin, icons/<index>.icn
    content N   NCCH, RomFS: body_LZ.bin (+ bgm.bcstm), one theme each

Formats from https://www.3dbrew.org/wiki/Home_Menu/Themes, the RomFS/NCCH/
TMD pages there, and Anemone3DS's theme dumper (how the HOME Menu reads a
pack). Contents are left unencrypted and the TMD carries a dummy signature;
Luma3DS's signature patches let the 3DS install it. Like Nintendo's CDN
TMDs it ends with the CP0000000b + CA00000003 certificate chain
(tools/certs/tmd_cert_chain.bin, taken from a Nintendo CDN TMD); the
console's download stops (009-2901) without it. Output goes to
cdn/<title id>/ (tmd.bin, 00000000.app ...), served by the content server's
CCS download path.

    python3 tools/theme_pack.py build themes/pack.json      # see themes/pack.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_theme  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CDN = ROOT / "cdn"
MEDIA = 0x200
CERT_CHAIN = ROOT / "tools" / "certs" / "tmd_cert_chain.bin"
BLOCK_LOG2 = 12  # 0x1000 hash blocks, like makerom
REGIONS = ("JPN", "USA", "EUR", "AUS", "CHN", "KOR", "TWN")
LANGUAGES = ("ja", "en", "fr", "de", "it", "es", "zh", "ko", "nl", "pt", "ru", "tw")
# Each region's HOME Menu has its own theme packs: HOME Menu 0004003000008202 /
# 8F02 / 9802 (JPN / USA / EUR) uses packs 0004008C000082xx / 8Fxx / 98xx, the
# same theme id (08000001) meaning that region's pack 08. A pack spec is the USA
# pack; build() makes each region's copy: its title id, its index files
# (ContentInfoArchive_<region>_<lang>, Australian consoles run EUR's HOME Menu as
# region AUS) and its own shop item numbers. Language codes from HOME Menu's code.
PACK_REGIONS = {
    "USA": {"base": 0x8F00, "letter": "E", "items": 0, "archives": {"USA": ("en", "es", "fr", "pt")}},
    "EUR": {"base": 0x9800, "letter": "P", "items": 100000,
            "archives": {"EUR": ("en", "fr", "de", "it", "es", "nl", "pt", "ru"), "AUS": ("en",)}},
    "JPN": {"base": 0x8200, "letter": "J", "items": 200000, "archives": {"JPN": ("ja",)}},
}
ALL_REGIONS = tuple(PACK_REGIONS)
# EUR and JPN copies are built only while this file exists (switched on with the
# proxy's BADGECADE_CDN_TITLE_IDS listing them and shopdeck knowing their Theme Shop)
REGIONS_SWITCH = ROOT / "themes" / "regions.on"


def region_title_id(title_id: str, region: str) -> str:
    """The region's copy of a USA pack: 0004008C00008F08 -> 0004008C00009808 (EUR)."""
    value = int(title_id, 16)
    return "%016X" % ((value & ~0xFFFF) | PACK_REGIONS[region]["base"] | (value & 0xFF))


def pack_regions(spec: dict) -> tuple[str, ...]:
    """The regions a pack is built for: every region for a numbered Theme Shop pack
    (8F00-8F09, contents 1-100); only USA for the old ones (8F09's 901-905, 8FB0)."""
    title_id = int(spec["title_id"], 16)
    indexes = [t["index"] for t in spec["themes"]] + [int(i) for i in spec.get("retired", [])]
    if not REGIONS_SWITCH.exists() or title_id & 0xFFFF00 != 0x8F00 or (title_id & 0xFF) > 9 or any(i > 100 for i in indexes):
        return ("USA",)
    return ALL_REGIONS


def theme_regions(theme: dict, planned: bool = False) -> tuple[str, ...]:
    """Where a theme is sold; themes added before region support are USA only.
    A theme scheduled for later ("available_from", a UTC date) is sold nowhere
    until that day, but keeps its slot: slot counting and the admin page ask
    with planned=True for the regions it will be sold in."""
    if not planned and theme.get("available_from"):
        import datetime
        if datetime.date.fromisoformat(theme["available_from"]) > datetime.datetime.now(datetime.timezone.utc).date():
            return ()
    return tuple(theme.get("regions") or ("USA",))


def _align(value: int, to: int) -> int:
    return (value + to - 1) // to * to


# --- RomFS (level 3 file system + IVFC hash tree) ---

def _name_hash(parent: int, name: str) -> int:
    h = parent ^ 123456789
    for unit in struct.unpack(f"<{len(name.encode('utf-16-le')) // 2}H", name.encode("utf-16-le")):
        h = ((h >> 5) | (h << 27)) & 0xFFFFFFFF
        h ^= unit
    return h


def _buckets(count: int) -> int:
    if count < 3:
        return 3
    if count < 19:
        return count | 1
    while any(count % p == 0 for p in (2, 3, 5, 7, 11, 13, 17)):
        count += 1
    return count


def romfs_level3(files: dict[str, bytes]) -> bytes:
    """A RomFS file system holding `files` ({"icons/1.icn": data, ...})."""
    # directory tree
    dirs: dict[str, dict] = {"": {"name": "", "parent": "", "dirs": [], "files": []}}
    for path in sorted(files):
        parts = path.split("/")
        for depth in range(1, len(parts)):
            d = "/".join(parts[:depth])
            if d not in dirs:
                parent = "/".join(parts[:depth - 1])
                dirs[d] = {"name": parts[depth - 1], "parent": parent, "dirs": [], "files": []}
                dirs[parent]["dirs"].append(d)
        dirs["/".join(parts[:-1])]["files"].append(path)

    # lay out directory entries breadth-first, files in directory order
    order, queue = [], [""]
    while queue:
        d = queue.pop(0)
        order.append(d)
        queue.extend(dirs[d]["dirs"])
    dir_off, at = {}, 0
    for d in order:
        dir_off[d] = at
        at += 0x18 + _align(len(dirs[d]["name"].encode("utf-16-le")), 4)
    dir_meta_size = at
    file_order = [f for d in order for f in dirs[d]["files"]]
    file_off, data_off, at, data_at = {}, {}, 0, 0
    for f in file_order:
        file_off[f] = at
        at += 0x20 + _align(len(f.rsplit("/", 1)[-1].encode("utf-16-le")), 4)
        data_off[f] = data_at
        data_at = _align(data_at + len(files[f]), 0x10)
    file_meta_size = at

    dir_buckets, file_buckets = _buckets(len(order)), _buckets(len(file_order))
    dir_table = [0xFFFFFFFF] * dir_buckets
    file_table = [0xFFFFFFFF] * file_buckets
    dir_next: dict[str, int] = {}
    for d in order:
        b = _name_hash(dir_off[dirs[d]["parent"]], dirs[d]["name"]) % dir_buckets
        dir_next[d] = dir_table[b]
        dir_table[b] = dir_off[d]
    file_next: dict[str, int] = {}
    for f in file_order:
        parent = f.rsplit("/", 1)[0] if "/" in f else ""
        b = _name_hash(dir_off[parent], f.rsplit("/", 1)[-1]) % file_buckets
        file_next[f] = file_table[b]
        file_table[b] = file_off[f]

    dir_meta = bytearray()
    for d in order:
        info = dirs[d]
        siblings = dirs[info["parent"]]["dirs"] if d else []
        nxt = siblings[siblings.index(d) + 1] if d and siblings.index(d) + 1 < len(siblings) else None
        name = info["name"].encode("utf-16-le")
        dir_meta += struct.pack(
            "<6I", dir_off[info["parent"]], dir_off[nxt] if nxt is not None else 0xFFFFFFFF,
            dir_off[info["dirs"][0]] if info["dirs"] else 0xFFFFFFFF,
            file_off[info["files"][0]] if info["files"] else 0xFFFFFFFF,
            dir_next[d], len(name)) + name.ljust(_align(len(name), 4), b"\0")
    file_meta = bytearray()
    for f in file_order:
        parent = f.rsplit("/", 1)[0] if "/" in f else ""
        siblings = dirs[parent]["files"]
        nxt = siblings[siblings.index(f) + 1] if siblings.index(f) + 1 < len(siblings) else None
        name = f.rsplit("/", 1)[-1].encode("utf-16-le")
        file_meta += struct.pack(
            "<IIQQII", dir_off[parent], file_off[nxt] if nxt is not None else 0xFFFFFFFF,
            data_off[f], len(files[f]), file_next[f], len(name)) + name.ljust(_align(len(name), 4), b"\0")
    assert len(dir_meta) == dir_meta_size and len(file_meta) == file_meta_size

    header_size = 0x28
    dir_hash_off = header_size
    dir_meta_off = dir_hash_off + dir_buckets * 4
    file_hash_off = dir_meta_off + dir_meta_size
    file_meta_off = file_hash_off + file_buckets * 4
    data_start = _align(file_meta_off + file_meta_size, 0x10)
    header = struct.pack("<10I", header_size, dir_hash_off, dir_buckets * 4, dir_meta_off, dir_meta_size,
                         file_hash_off, file_buckets * 4, file_meta_off, file_meta_size, data_start)
    out = bytearray(header)
    out += struct.pack(f"<{dir_buckets}I", *dir_table) + dir_meta
    out += struct.pack(f"<{file_buckets}I", *file_table) + file_meta
    out += b"\0" * (data_start - len(out))
    for f in file_order:
        out += b"\0" * (data_start + data_off[f] - len(out))
        out += files[f]
    return bytes(out)


def _hash_level(data: bytes) -> bytes:
    block = 1 << BLOCK_LOG2
    return b"".join(hashlib.sha256(data[i:i + block].ljust(block, b"\0")).digest()
                    for i in range(0, max(len(data), 1), block))


def romfs(files: dict[str, bytes]) -> tuple[bytes, int]:
    """IVFC-wrapped RomFS image, and the size of its hashed header region."""
    block = 1 << BLOCK_LOG2
    level3 = romfs_level3(files)
    level2 = _hash_level(level3)
    level1 = _hash_level(level2)
    master = _hash_level(level1)
    l1_off = 0
    l2_off = _align(l1_off + len(level1), block)
    l3_off = _align(l2_off + len(level2), block)
    header = struct.pack(
        "<4sII" + "QQII" * 3 + "II", b"IVFC", 0x10000, len(master),
        l1_off, len(level1), BLOCK_LOG2, 0,
        l2_off, len(level2), BLOCK_LOG2, 0,
        l3_off, len(level3), BLOCK_LOG2, 0,
        0x5C, 0)
    head = header.ljust(0x60, b"\0") + master
    hashed_region = len(head)
    image = bytearray(head)
    image += b"\0" * (_align(len(image), block) - len(image))
    image += level3
    image += b"\0" * (_align(len(image), block) - len(image))
    image += level1
    image += b"\0" * (_align(len(image), block) - len(image))
    image += level2
    image += b"\0" * (_align(len(image), block) - len(image))
    return bytes(image), hashed_region


# --- NCCH (CFA: data only, RomFS, no encryption) ---

def ncch(title_id: int, files: dict[str, bytes], product_code: str = "CTR-N-BCTH") -> bytes:
    image, hashed = romfs(files)
    romfs_offset = 1  # media units, right after the header
    romfs_units = _align(len(image), MEDIA) // MEDIA
    hashed_units = _align(hashed, MEDIA) // MEDIA
    total_units = romfs_offset + romfs_units
    header = bytearray(0x200)
    header[0x100:0x104] = b"NCCH"
    struct.pack_into("<I", header, 0x104, total_units)
    struct.pack_into("<Q", header, 0x108, title_id)          # partition id
    header[0x110:0x112] = b"00"                                # maker code
    struct.pack_into("<H", header, 0x112, 2)                   # NCCH version
    struct.pack_into("<Q", header, 0x118, title_id)          # program id
    header[0x150:0x160] = product_code.encode("ascii").ljust(0x10, b"\0")
    flags = bytearray(8)
    flags[4] = 1     # content platform: CTR
    flags[5] = 0x01  # content type: data
    flags[6] = 0     # content unit size 0x200
    flags[7] = 0x04  # NoCrypto
    header[0x188:0x190] = flags
    struct.pack_into("<IIII", header, 0x1B0, romfs_offset, romfs_units, hashed_units, 0)
    header[0x1E0:0x200] = hashlib.sha256(image[:hashed_units * MEDIA]).digest()
    return bytes(header) + image.ljust(romfs_units * MEDIA, b"\0")


# --- TMD ---

def content_id(index: int, data: bytes) -> int:
    """A content's id follows its data: a theme that didn't change keeps its id
    in a new pack version, so a console updating the pack keeps the installed
    file (a new id for every content removed every downloaded theme, and the
    HOME Menu dropped the theme in use whenever the pack was republished). A
    changed content gets a new id (the console skips a content whose id it
    already has). Top bit set: never an old (version << 16 | index) id, nor a
    by-index file name."""
    digest = hashlib.sha256(index.to_bytes(2, "big") + data).digest()
    return int.from_bytes(digest[:4], "big") | 0x80000000


def tmd(title_id: int, version: int, contents: list[tuple[int, bytes]], required: set[int] = frozenset(),
        flagged: set[int] = frozenset()) -> bytes:
    """contents: [(index, data)], not encrypted. Content 0 (the pack's control
    content) and the contents in ``required`` are required, so the console
    installs them with the pack; other themes are optional (DLC) contents."""
    # ``flagged``: marked encrypted (0x1) without being encrypted, for testing
    chunks = b"".join(struct.pack(">IHHQ", content_id(index, data), index, (0x4000 if index and index not in required else 0) | (1 if index in flagged else 0), len(data)) + hashlib.sha256(data).digest()
                      for index, data in contents)
    info = struct.pack(">HH", 0, len(contents)) + hashlib.sha256(chunks).digest()
    info_records = info + b"\0" * (0x24 * 63)
    header = bytearray(0xC4)
    header[0x00:0x40] = b"Root-CA00000003-CP0000000b".ljust(0x40, b"\0")
    header[0x40] = 1                                  # TMD version
    struct.pack_into(">Q", header, 0x4C, title_id)
    struct.pack_into(">I", header, 0x54, 0x40)        # title type
    struct.pack_into(">H", header, 0x9C, version)
    struct.pack_into(">H", header, 0x9E, len(contents))
    struct.pack_into(">H", header, 0xA0, 0)           # boot content
    header[0xA4:0xC4] = hashlib.sha256(info_records).digest()
    signature = struct.pack(">I", 0x00010004) + b"\0" * 0x100 + b"\0" * 0x3C
    return signature + bytes(header) + info_records + chunks + CERT_CHAIN.read_bytes()


# --- the pack ---

def _ascii(text: str, size: int) -> bytes:
    return text.encode("utf-8")[:size - 1].ljust(size, b"\0")


def control_files(themes: list[dict], region: str = "USA") -> dict[str, bytes]:
    """Laid out like Nintendo's own USA pack content 0 (checked against a
    dump): counts exclude the dummy entry except "total", unused region
    slots are FFFF FFFF."""
    archives = PACK_REGIONS[region]["archives"]
    pairs = [(r, lang) for r, langs in archives.items() for lang in langs]
    meta = bytearray(0x34 + 4 * len(pairs))
    # total: content index slots including the dummy (Nintendo: indexes 1-115 -> 115);
    # the HOME Menu skips themes whose index is past it
    total = max([len(themes)] + [t["index"] for t in themes]) + 1
    # count: the archive's entries (empty slots too), as in Nintendo's dense packs. With
    # the number of themes instead, Dots & Stripes at 8F08 #2 (#1 empty) never showed in
    # Change Theme: count 1 covered only the empty entry (2026-10-12)
    count = total - 1
    struct.pack_into("<IIIII", meta, 0, 1, count, total, 0x300030, 0xDEADBEEF)
    for r in range(len(REGIONS)):  # region slots from 0x14: (region in use, primary language)
        in_use = REGIONS[r] in archives  # primary language: Japanese for JPN, English elsewhere
        struct.pack_into("<HH", meta, 0x14 + 4 * r, *((1, 0 if REGIONS[r] == "JPN" else 1) if in_use else (0xFFFF, 0xFFFF)))
    struct.pack_into("<I", meta, 0x30, len(pairs))
    for i, (r, lang) in enumerate(pairs):
        struct.pack_into("<HH", meta, 0x34 + 4 * i, REGIONS.index(r), LANGUAGES.index(lang))
    files = {"MetaDataContentHeader.bin": bytes(meta)}
    # Entry N must be content index N (Nintendo's is dense: entries 1-115 are
    # indexes 1-115); the HOME Menu looks a theme up by position, so a theme at
    # index 901 needs 900 entries before it. Unused slots are disabled (flag 0).
    by_index = {t["index"]: t for t in themes}
    archive = bytearray(struct.pack("<II", 1, total - 1))
    archive += _ascii("DummyTitle", 0x40) + _ascii("DummyDescription", 0x80) + struct.pack("<II", 0, 0)  # entry 0: unused
    for index in range(1, total):
        theme = by_index.get(index)
        if theme is None:
            archive += bytes(0xC0) + struct.pack("<II", index, 0)
            continue
        archive += _ascii(theme["name"], 0x40) + _ascii(theme.get("description", ""), 0x80)
        archive += struct.pack("<II", theme["index"], 1)
        icon = make_theme.resize(make_theme.read_png(ROOT / theme["icon"]), 48, 48)
        files[f"icons/{theme['index']}.icn"] = make_theme.rgb565_tiled(icon, 48, 48)
    for r, lang in pairs:
        files[f"ContentInfoArchive_{r}_{lang}.bin"] = bytes(archive)
    return files


def build(spec_path: Path, region: str = "USA") -> Path:
    spec = json.loads(spec_path.read_text())
    title_id = int(region_title_id(spec["title_id"], region), 16)
    # the region's themes; the others' contents are placeholders there (same content list in every region)
    themes = [t for t in spec["themes"] if region in theme_regions(t)]
    absent = {t["index"] for t in spec["themes"]} - {t["index"] for t in themes}
    # A theme's ID (item_code: the shop's ITEM_CODE, the thmdtls theme id) is
    # pack variation * 1000000 + content index, the variation being the pack's
    # title id low byte (0004008C00008F09 -> 9): theme 1 of pack 8F09 is 09000001.
    # The HOME Menu finds the pack and content from it; with any other number
    # Download just returns to "Please select a theme" (3dbrew Home_Menu, jump
    # command 0x2; confirmed in the emulator 2026-10-11).
    taken: dict[int, str] = {}
    for theme in themes:
        if theme["index"] in taken:  # a slot holds one theme in each region
            raise SystemExit("themes %r and %r are both slot %d in %s"
                             % (taken[theme["index"]], theme["name"], theme["index"], region))
        taken[theme["index"]] = theme["name"]
        if not 1 <= theme["index"] <= 1023:  # the shop's tickets grant content indexes 0-1023
            raise SystemExit("theme %r: content index must be 1-1023" % theme["name"])
        expected = "%08d" % ((title_id & 0xFF) * 1000000 + theme["index"])
        if theme["item_code"] != expected and title_id & 0xFF <= 9:  # 8F00-8F09: the Theme Shop's packs
            raise SystemExit("theme %r: item_code must be %s (pack %02X, content %d)"
                             % (theme["name"], expected, title_id & 0xFF, theme["index"]))
    # an add-on's product code (CTR-M-xxxx); the shop's sys.ItemCode for each theme is
    # this code without dashes plus the 8-digit content index, as in Nintendo's own
    # ListContentSetsEx answers (CTR-M-AXCE -> CTRMAXCE00000001)
    product_code = spec.get("product_code", "CTR-M-BCTE")
    if region != "USA":  # CTR-M-BC8E -> CTR-M-BC8P (EUR), CTR-M-BC8J (JPN)
        product_code = product_code[:-1] + PACK_REGIONS[region]["letter"]
    contents = [(0, ncch(title_id, control_files(themes, region), product_code))]
    for theme in themes:
        with zipfile.ZipFile(ROOT / theme["zip"]) as z:
            files = {"body_LZ.bin": z.read("body_LZ.bin")}
            if "bgm.bcstm" in z.namelist():
                files["bgm.bcstm"] = z.read("bgm.bcstm")
        contents.append((theme["index"], ncch(title_id, files, product_code)))
    # No gaps in the content list, as in Nintendo's packs: the Buy window (mint)
    # crashes buying a theme whose index is past the pack's content count. A
    # deleted theme's index keeps a small placeholder content (not in the shop,
    # never owned or downloaded) until a new theme takes it.
    # A pack's content list never loses a content: NIM fails updating a console that
    # has a content the new version drops (005-4005; emulator, 2026-10-12). Deleted
    # themes' indexes ("retired" in the spec) keep a placeholder.
    used = {index for index, _ in contents}
    retired = ({int(i) for i in spec.get("retired", [])} | absent) - used
    placeholder = ncch(title_id, {"placeholder": b"BadgeCade"}, product_code)
    contents += [(index, placeholder) for index in sorted(retired)]
    used |= retired
    if max(used) <= 100:  # an old pack numbered from 901 (before tools/renumber_pack.py) stays as it was
        contents += [(index, placeholder) for index in range(1, max(used) + 1) if index not in used]
    contents.sort(key=lambda item: item[0])
    out = CDN / ("%016X" % title_id)
    out.mkdir(parents=True, exist_ok=True)
    for index, data in contents:
        (out / f"{content_id(index, data):08X}.app").write_bytes(data)  # the CDN name
        (out / f"{index:08X}.app").write_bytes(data)  # by content index (shopdeck's sizes)
    # "auto_install" themes come with the pack (the Theme Shop installs the
    # pack's required contents when All Themes opens; its Buy button doesn't
    # work with our server yet)
    auto = {t["index"] for t in themes if t.get("auto_install")}
    flagged = {t["index"] for t in themes if t.get("encrypted_flag")}
    (out / "tmd.bin").write_bytes(tmd(title_id, spec.get("version", 0), contents, auto, flagged))
    # the themes, for shopdeck's ListContentSetsEx answer (and its tickets)
    import theme_shop_data  # the shop's title lines are wrapped at whole words
    sets = [{"index": t["index"], "icon_index": t["index"], "name": theme_shop_data.wrap(t["name"], theme_shop_data.TITLE_LINE),
             "publisher": t.get("publisher", "BadgeCade"),
             "item_id": t["item_id"] + PACK_REGIONS[region]["items"], "item_code": t["item_code"], "auto_install": bool(t.get("auto_install")),
             "product_code": product_code.replace("-", "") + "%08d" % t["index"],
             "granted": bool(t.get("granted") or t.get("auto_install")),
             "limit": int(t.get("limit", 0)),
             "purchase_test": bool(t.get("purchase_test")),
             "title_included": bool(t.get("title_included", True)),
             "description": t.get("description", ""),
             # NewSince: when the theme went in the shop (themes from before this was kept: the old fixed date)
             "new_since": int(t.get("added", 1791504000000)),
             "price": round(float(t.get("price", 0)), 2),
             # a player's personal theme: only their console lists and owns it (tools/add_theme.py --owner)
             "owner": t.get("owner", "")} for t in themes]
    (out / "contentsets.json").write_text(json.dumps(sets, indent=1, ensure_ascii=False) + "\n")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("spec", type=Path)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    outs = [build(args.spec, region) for region in pack_regions(spec)]
    import theme_shop_data  # the Theme Shop's SpotPass details for each theme
    for path in theme_shop_data.write(args.spec):
        print(f"{path}  {path.stat().st_size} bytes")
    for out in outs:
        for path in sorted(out.iterdir()):
            print(f"{path}  {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
