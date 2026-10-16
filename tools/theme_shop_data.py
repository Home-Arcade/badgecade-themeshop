#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
"""The Theme Shop's SpotPass data for BadgeCade's themes (themes/pack.json).

For each theme the shop looks up its details (thmdtls) by the item code that
CAS ListContentSetsEx gives: first in the SpotPass file list
(npfl .../filelist/<task>/thmdtls, served by the content server from
attributes.tsv), then the details file itself. Written to
content/THEMESHOP/thmdtls/ALL/<lang>/:

    <details id>     BOSS file, payload as in Nintendo's archived thmdtls:
                     01 <sfx> <bgm> 01, description @0x10 (UTF-16, 0x100 bytes),
                     publisher @0x110 (0x80), BGM name @0x910 (0x100),
                     @0xA14 top preview size/offset, bottom preview
                     size/offset, then the two JPEGs (240x144 and 192x144)
    attributes.tsv   one line per theme: id, price text (empty = free),
                     id, item code, 1

Each region also gets BadgeCade's own front page (thmtop/ALL/en/top) with
one featured list (thmlist/ALL/en/<LIST_NAME>), a different collection each
day (COLLECTIONS: New Themes, Mario Themes...), newest themes first, with
their names, publishers and icons. Layouts:

    top    01 <lists> 01 00, @0x08 1, @0x10 banner JPEG size/offset (408x176),
           title UTF-16 @0x28, list entries from 0xE8 (16 bytes each: list
           file name, the list's ns_data_id, button JPEG size/offset (64x48))
    list   01 <count>, @0x10 banner JPEG size/offset, records from 0x18
           (0x1368 each: details id, item code, content index, name UTF-16 @0x28
           (0xC0), publisher @0xE8 (0x40), 48x48 RGB565 icon @0x168, the
           record's end; the first number names the details file opened on a tap)

    python3 tools/theme_shop_data.py themes/pack.json
"""

from __future__ import annotations

import json
import struct
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boss3ds  # noqa: E402
import jpeg  # noqa: E402
import make_theme  # noqa: E402
import theme_pack  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "content" / "THEMESHOP" / "thmdtls" / "ALL"
LANGUAGES = ("en",)  # other languages get English (the content server falls back to it)
THEME_SHOP_PROGRAM = "000400100002cd00"
# each region's Theme Shop data (src/badge_arcade_server/content.py THEME_SHOP_TASKS)
# carries that region's Theme Shop program id (HOME Menu's code: 2CC00 / 2CD00 / 2CE00)
REGION_DATA = {
    "USA": (ROOT / "content" / "THEMESHOP", THEME_SHOP_PROGRAM),
    "EUR": (ROOT / "content" / "THEMESHOP-EUR", "000400100002ce00"),
    "JPN": (ROOT / "content" / "THEMESHOP-JPN", "000400100002cc00"),
}
DETAILS_DATATYPE = 0x10004


def _utf16(text: str, size: int) -> bytes:
    return text.encode("utf-16-le")[:size - 2].ljust(size, b"\0")


def previews(theme_zip: Path) -> tuple[bytes, bytes]:
    """Top (240x144) and bottom (192x144) previews from the theme's preview.png."""
    with zipfile.ZipFile(theme_zip) as z:
        png = z.read("preview.png")
    tmp = ROOT / "themes" / ".preview.png"
    tmp.write_bytes(png)
    try:
        image = make_theme.read_png(tmp)
    finally:
        tmp.unlink()
    half = image.height // 2
    top_left = (image.width - 400) // 2
    bottom_left = (image.width - 320) // 2
    top = make_theme.Image(400, 240, [image.get(top_left + x, y) for y in range(240) for x in range(400)])
    bottom = make_theme.Image(320, 240, [image.get(bottom_left + x, half + y) for y in range(240) for x in range(320)])
    return (jpeg.encode(make_theme.resize(top, 240, 144), 90),
            jpeg.encode(make_theme.resize(bottom, 192, 144), 90))


CACHE = ROOT / "themes" / ".details-cache"
# characters per line the Theme Shop fits (measured on a console with a ruler
# theme, 2026-10-13): it wraps longer text mid-word, so the breaks go in here
DESCRIPTION_LINE = 28
TITLE_LINE = 24


def wrap(text: str, width: int) -> str:
    """Line breaks at whole words (by display width: a Japanese character counts twice)."""
    import ja_text
    return "\n".join(ja_text.wrap_ja(line, width) for line in text.split("\n"))


def details(theme: dict) -> bytes:
    """A theme's details page. Encoding the previews takes about a second in
    pure Python, so each page is kept by a hash of everything it is made of
    and only rebuilt when the theme's file or texts change."""
    import hashlib
    zip_path = ROOT / theme["zip"]
    stat = zip_path.stat()
    key = hashlib.sha256(json.dumps([theme["zip"], stat.st_size, stat.st_mtime_ns, theme.get("sfx"),
                                     theme.get("bgm_type", 1), theme.get("description", ""),
                                     theme.get("publisher", "BadgeCade"), theme.get("bgm", "None"),
                                     DESCRIPTION_LINE]).encode()).hexdigest()
    cached = CACHE / f"{key}.bin"
    if cached.is_file():
        return cached.read_bytes()
    page = _details(theme)
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = cached.with_suffix(".tmp")
    tmp.write_bytes(page)
    tmp.replace(cached)
    return page


def _details(theme: dict) -> bytes:
    top, bottom = previews(ROOT / theme["zip"])
    head = bytearray(0xA30)
    # 01, 02 with custom sound effects (else 01), music type (Nintendo's: 01-03), 01
    head[0:4] = bytes([1, 2 if theme.get("sfx") else 1, theme.get("bgm_type", 1), 1])
    head[0x10:0x110] = _utf16(wrap(theme.get("description", ""), DESCRIPTION_LINE), 0x100)
    head[0x110:0x190] = _utf16(theme.get("publisher", "BadgeCade"), 0x80)
    head[0x910:0xA10] = _utf16(theme.get("bgm", "None"), 0x100)
    top_at = 0xA30
    bottom_at = (top_at + len(top) + 15) & ~15
    struct.pack_into("<IIII", head, 0xA14, len(top), top_at, len(bottom), bottom_at)
    out = bytes(head) + top.ljust(bottom_at - top_at, b"\0") + bottom
    return out.ljust((len(out) + 15) & ~15, b"\0")


def _pack_of(theme: dict, spec_path: Path) -> str:
    """The pack title id a theme is in (by its theme ID: variation * 1000000 + index)."""
    return "0004008C00008F%02X" % (int(theme["item_code"]) // 1000000)


def all_themes(spec_path: Path) -> list[dict]:
    """The themes of every Theme Shop pack (themes/pack-*8f0N.json) plus spec_path's."""
    paths = sorted(set((ROOT / "themes").glob("pack-*8f0[0-9].json")) | {spec_path.resolve()})
    return [t for path in paths for t in json.loads(path.read_text())["themes"]]


def write(spec_path: Path) -> list[Path]:
    spec = json.loads(spec_path.read_text())
    written = []
    for region in theme_pack.pack_regions(spec):
        written += _write_region(spec_path, spec, region)
    return written


TOP_DATATYPE, LIST_DATATYPE = 0x10001, 0x10002
WRITE_FRONT_PAGE = False  # see _region_top
TOP_ID = 2000000100      # BadgeCade's front page
# "New Themes": consoles ask for list 5179 whatever the front page says (the
# number stays on the console), so ours goes by that name; its ns_data_id 5190
LIST_NAME = 5179
LIST_ID = 5190
# "Popular": the most bought themes (shopdeck's purchases). Off: a second
# front-page list (9002) was fetched but never shown or asked for on a
# console (2026-10-13); the shop's first screen has one fixed list, 5179
POPULAR_NAME: int | None = None
POPULAR_ID: int | None = None
# Collections: the shop shows one featured list, so it's a different collection
# each day (Nintendo's day, from 10:00 UTC), its name on the list's banner. A
# collection takes the themes whose name or description has one of its words;
# it's used only with at least COLLECTION_MIN themes in the region. New Themes
# is always one of them.
COLLECTIONS = [
    ("newest", "New Themes!", []),
    ("mario", "Mario Themes", ["mario", "luigi", "bowser", "peach", "yoshi", "toad", "wario", "waluigi", "koopa", "goomba"]),
    ("pokemon", "Pokémon Themes", ["pokemon", "pokémon", "pikachu", "eevee", "pokeball", "poké ball"]),
    ("zelda", "Zelda Themes", ["zelda", "hyrule", "triforce", "link's", "ganon"]),
    ("kirby", "Kirby Themes", ["kirby", "dedede", "meta knight", "waddle dee"]),
    ("animal", "Animal Crossing Themes", ["animal crossing", "isabelle", "tom nook", "k.k. slider"]),
    ("splatoon", "Splatoon Themes", ["splatoon", "inkling", "octoling"]),
    ("metroid", "Metroid Themes", ["metroid", "samus"]),
    ("retro", "Retro Themes", ["nes", "famicom", "8-bit", "8 bit", "pixel", "retro", "game boy", "gameboy"]),
    ("sonic", "Sonic Themes", ["sonic", "tails", "knuckles"]),
]
COLLECTION_MIN = 4
LIST_RECORD = 0x1368
LIST_SIZE = 20           # newest themes on the list
TITLE = "Welcome to the BadgeCade Theme Shop!"


def _banner(width: int, height: int, words: str, holiday: str | None = None) -> bytes:
    """Our own artwork (no theme screens): three tilted little HOME Menu
    screens in soft colours under a headline; in a holiday's season, on the
    holiday's colours and motifs, as on the hall posters (tools/holiday_week.py)."""
    import random
    import subprocess
    import tempfile
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        args = ["convert", "-size", f"{width}x{height}", "radial-gradient:#ffffff-#bfe3ff"]
        ink, rim = "#1d4f91", "white"
        if holiday:
            import holiday_week
            (centre, edge), kind, colours, *_ = holiday_week.PALETTES[holiday]
            args = ["convert", "-size", f"{width}x{height}", f"radial-gradient:{centre}-{edge}"]
            rng = random.Random(holiday)
            scale = width / 640
            for n in range(max(6, int(26 * scale))):
                shape = kind[n % len(kind)] if isinstance(kind, tuple) else kind
                primitive = holiday_week._motif(shape, rng.uniform(0, width), rng.uniform(0, height),
                                                rng.uniform(10, 24) * scale, rng.uniform(-0.6, 0.6))
                colour = colours[n % len(colours)]
                args += (["-fill", "none", "-stroke", colour, "-strokewidth", str(max(1, round(3 * scale))), "-draw", primitive]
                         if shape == "snowflake" else ["-stroke", "none", "-fill", colour, "-draw", primitive])
            args += ["-stroke", "none"]
            ink, rim = "#ffffff", "#000000"
        w = width * 2 // 7
        h = w * 3 // 5
        for i, (colour, angle) in enumerate((("#ffb84d", -8), ("#7fd0ff", 5), ("#9be07a", -3))):
            icons = " ".join(f"roundrectangle {8 + c * (w - 16) // 4},{h // 3 + r * h // 4} "
                             f"{8 + c * (w - 16) // 4 + (w - 16) // 5},{h // 3 + r * h // 4 + h // 6} 3,3"
                             for c in range(4) for r in range(2))
            subprocess.run(["convert", "-size", f"{w}x{h}", f"xc:{colour}", "-fill", "#ffffffb0", "-draw", icons,
                            "-fill", "#ffffff60", "-draw", f"rectangle 0,0 {w},{h // 5}",
                            "-bordercolor", "white", "-border", "3",
                            "(", "+clone", "-background", "#00000070", "-shadow", "60x2+2+3", ")", "+swap",
                            "-background", "none", "-layers", "merge", "+repage",
                            "-background", "none", "-rotate", str(angle), f"PNG32:{t / f'c{i}.png'}"], check=True)
            x = (width - 3 * w + 2 * (w // 8)) // 2 + i * (w - w // 8) - w // 20
            y = height * 2 // 5 + (8, -4, 10)[i] * height // 176
            args += [t / f"c{i}.png", "-geometry", f"+{x}+{y}", "-compose", "over", "-composite"]
        if words:
            size = max(10, height // 6)
            args += ["-gravity", "north", "-font", font, "-pointsize", str(size), "-fill", ink,
                     "-stroke", rim, "-strokewidth", str(max(1, size // 7)), "-annotate", f"+0+{height // 14}", words,
                     "-stroke", "none", "-annotate", f"+0+{height // 14}", words]
        args += [f"PNG32:{t / 'banner.png'}"]
        subprocess.run([str(a) for a in args], check=True)
        return jpeg.encode(make_theme.read_png(t / "banner.png"), 90)


def public_packs() -> set[str] | None:
    """Pack title ids the shop lists (shopdeck Title.public); None if shopdeck can't be asked."""
    import subprocess
    code = """
from shopdeckdb.models import Title
print("PUBLIC" + ",".join(t.tid.upper() for t in Title.objects.filter(public=True)))
"""
    try:
        result = subprocess.run(["docker", "compose", "exec", "-T", "shopdeck", "sh", "-c", "cd /app && python3 manage.py shell"],
                                input=code, cwd=ROOT, capture_output=True, text=True, timeout=60)
        line = next(l for l in result.stdout.splitlines() if l.startswith("PUBLIC"))
        return set(filter(None, line[len("PUBLIC"):].split(",")))
    except Exception:
        return None


def purchase_counts() -> dict[int, int]:
    """Purchases per shop item number (themes of every region), from shopdeck."""
    import subprocess
    code = """
import json
from django.db.models import Count
from shopdeckdb.models import ownedTicket
rows = ownedTicket.objects.filter(item__title__tid__istartswith="0004008C").values("item__id").annotate(n=Count("id"))
print("COUNTS" + json.dumps({r["item__id"]: r["n"] for r in rows}))
"""
    try:
        result = subprocess.run(["docker", "compose", "exec", "-T", "shopdeck", "sh", "-c", "cd /app && python3 manage.py shell"],
                                input=code, cwd=ROOT, capture_output=True, text=True, timeout=60)
        line = next(l for l in result.stdout.splitlines() if l.startswith("COUNTS"))
        return {int(k): v for k, v in json.loads(line[len("COUNTS"):]).items()}
    except Exception:  # no ranking is better than no front page
        return {}


def _align(data: bytes) -> bytes:
    return data.ljust((len(data) + 15) & ~15, b"\0")


def theme_list(themes: list[dict], banner: bytes) -> bytes:
    head = bytearray(0x18 + len(themes) * LIST_RECORD)
    head[0], head[1] = 1, len(themes)
    struct.pack_into("<II", head, 0x10, len(banner), len(head))
    for n, theme in enumerate(themes):
        at = 0x18 + n * LIST_RECORD
        # the first number names the details file the console opens when the theme is tapped
        # details file opened on a tap, theme ID (checked against the details), the theme's
        # content index in its pack (anything out of range makes the shop show it as a pack)
        struct.pack_into("<III", head, at, int(theme["details_id"]), int(theme["item_code"]), int(theme["index"]))
        head[at + 0x28:at + 0xE8] = _utf16(wrap(theme["name"], TITLE_LINE), 0xC0)
        head[at + 0xE8:at + 0x128] = _utf16(theme.get("publisher", "BadgeCade"), 0x40)
        icon = make_theme.resize(make_theme.read_png(ROOT / theme["icon"]), 48, 48)
        # the icon fills the end of the record (0x1368 - 0x1200 = 0x168)
        head[at + LIST_RECORD - 0x1200:at + LIST_RECORD] = make_theme.rgb565_tiled(icon, 48, 48)
    return _align(bytes(head) + banner)


def front_page(banner: bytes, lists: list[tuple[int, int, bytes]]) -> bytes:
    """The front page: banner, title and one button per list (name, ns_data_id, 64x48 JPEG)."""
    header = max(0x100, (0xE8 + 16 * len(lists) + 15) & ~15)
    head = bytearray(header)
    head[0:4] = bytes([1, len(lists), 1, 0])
    struct.pack_into("<I", head, 0x08, 1)
    struct.pack_into("<II", head, 0x10, len(banner), header)
    head[0x28:0xE0] = _utf16(TITLE, 0xB8)
    out = _align(bytes(head) + banner)
    entries = []
    for name, list_id, button in lists:
        entries.append((name, list_id, len(button), len(out)))
        out = _align(out + button)
    out = bytearray(out)
    for n, entry in enumerate(entries):
        struct.pack_into("<IIII", out, 0xE8 + 16 * n, *entry)
    return bytes(out)


def _matches(theme: dict, words: list[str]) -> bool:
    import re
    text = " ".join(str(theme.get(k, "")) for k in ("name", "description")).lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text) for w in words)


def todays_collection(themes: list[dict], day=None) -> tuple[str, str, list[dict]]:
    """(key, banner name, themes newest first) for the day: the collections with
    enough themes take turns, one a day."""
    import datetime
    day = day or (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=10)).date()
    newest = sorted(themes, key=lambda t: -int(t.get("item_id", 0)))
    usable = []
    for key, name, words in COLLECTIONS:
        picked = newest if not words else [t for t in newest if _matches(t, words)]
        if not words or len(picked) >= COLLECTION_MIN:
            usable.append((key, name, picked))
    return usable[day.toordinal() % len(usable)]


def _region_top(region: str, key: bytes, spec_path: Path | None = None) -> list[Path]:
    """The region's front page and its "New Themes" list, newest themes first."""
    root, program = REGION_DATA[region]
    # Nintendo's own themes stay off the featured list (only the two it made free at closure, in themes/free/)
    # only packs the shop lists: a theme from a hidden pack on the list gave
    # "unable to obtain data" when tapped (the console couldn't find its pack)
    public = public_packs()
    def listed(t):
        if public is None:
            return True
        return theme_pack.region_title_id(_pack_of(t, spec_path), region).upper() in public
    themes = [t for t in all_themes(spec_path) if region in theme_pack.theme_regions(t) and listed(t)
              and t.get("icon") and (ROOT / t["icon"]).is_file() and (ROOT / t["zip"]).is_file()
              and (t.get("publisher") != "Lintendo" or t["zip"].startswith("themes/free/"))
              and not t.get("owner")] if spec_path else []  # personal themes stay off the featured list
    if not themes:
        return []
    themes.sort(key=lambda t: -int(t.get("item_id", 0)))
    eligible = themes
    collection, title, themes = todays_collection(themes)
    themes = themes[:LIST_SIZE]
    import datetime
    import holiday_week
    holiday = holiday_week.season(region, datetime.datetime.now(datetime.timezone.utc).date())
    words = holiday_week.wishes(holiday, "en") if holiday and collection == "newest" else title
    banner = _banner(408, 176, words, holiday)
    button = _banner(64, 48, "", holiday)
    version = int(time.time()) & 0xFFFFFFFF  # a new version makes consoles fetch it again
    list_id = LIST_ID
    files = [("thmlist", str(LIST_NAME), LIST_DATATYPE, list_id, theme_list(themes, banner))]
    buttons = [(LIST_NAME, list_id, button)]
    if POPULAR_NAME is not None:
        counts = purchase_counts()
        offset = theme_pack.PACK_REGIONS[region]["items"]
        popular = sorted(eligible, key=lambda t: (-counts.get(int(t["item_id"]) + offset, 0), -int(t["item_id"])))[:LIST_SIZE]
        files.append(("thmlist", str(POPULAR_NAME), LIST_DATATYPE, POPULAR_ID,
                      theme_list(popular, _banner(408, 176, "Popular Themes!"))))
        buttons.append((POPULAR_NAME, POPULAR_ID, _banner(64, 48, "")))
    # The front page stays the original one: consoles opening the shop for the first
    # time rejected ours ("unable to obtain data", 2026-10-13); only consoles holding
    # a saved copy of the original got past it. Our list (5179) goes behind it.
    if WRITE_FRONT_PAGE:
        files.append(("thmtop", "top", TOP_DATATYPE, TOP_ID, front_page(banner, buttons)))
    written = []
    for kind, name, datatype, ns_id, content in files:
        container = {"serial": version, "header_14": "0001000000020002", "content_header_magic": "80" + "00" * 15,
                     "payloads": [{"program_id": program, "content_datatype": datatype, "ns_data_id": ns_id,
                                   "version": version, "unknown_08": "00000000", "content": content}]}
        data = boss3ds.encrypt(container, key)
        # every country folder that has its own copy (consoles also ask for country "ZZ"):
        # an old front page left there would point at lists we don't serve (004-3003)
        targets = [root / kind / "ALL" / "en" / name]
        if kind == "thmtop":
            targets += [p for p in (root / kind).glob(f"*/*/{name}") if p not in targets]
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            if kind == "thmtop" and target.exists() and not (target.parent / "top.Nintendo").exists():
                target.rename(target.parent / "top.Nintendo")  # kept, not served
            tmp = target.with_suffix(".new")
            tmp.write_bytes(data)
            tmp.replace(target)
            written.append(target)
    (root / ".season").write_text(f"{holiday or ''}|{collection}\n")
    return written


def refresh_season(region: str) -> str:
    """Rebuild the region's front page when a holiday season starts or ends
    (run daily by tools/badge_rotation.py); otherwise leave it alone, so
    consoles don't fetch it again for nothing."""
    import datetime
    import holiday_week
    root, _ = REGION_DATA[region]
    marker = root / ".season"
    now = holiday_week.season(region, datetime.datetime.now(datetime.timezone.utc).date()) or ""
    specs = sorted((ROOT / "themes").glob("pack-*8f0[0-9].json"))
    # today's collection (it changes every day) is part of the marker
    collection = ""
    if specs:
        themes = [t for t in all_themes(specs[0]) if region in theme_pack.theme_regions(t)]
        collection = todays_collection(themes)[0] if themes else ""
    if marker.exists() and marker.read_text().strip() in (f"{now}|{collection}",):
        return ""
    written = _region_top(region, boss3ds.load_key(), specs[0]) if specs else []
    if not written:
        return ""
    shown = marker.read_text().strip().split("|")[-1] if marker.exists() else ""
    return f"{region}: Theme Shop featured list: {shown or 'new themes'}" + (f" ({now} season)" if now else "")


def _write_region(spec_path: Path, spec: dict, region: str) -> list[Path]:
    root, program = REGION_DATA[region]
    key = boss3ds.load_key()
    written = _region_top(region, key, spec_path)
    for language in LANGUAGES:
        folder = root / "thmdtls" / "ALL" / language
        folder.mkdir(parents=True, exist_ok=True)
        rows = []
        for theme in spec["themes"]:
            if region not in theme_pack.theme_regions(theme):
                continue
            container = {
                "serial": int(time.time()),
                "header_14": "0001000000020002",
                "content_header_magic": "80" + "00" * 15,
                "payloads": [{
                    "program_id": program,
                    "content_datatype": DETAILS_DATATYPE,
                    "ns_data_id": int(theme["item_code"]),
                    # the pack's version: a theme id can get new details (a deleted
                    # theme's number reused), and a console keeps its copy while the
                    # id and version stay the same
                    "version": int(spec.get("version", 1)),
                    "content": details(theme),
                }],
            }
            target = folder / theme["details_id"]
            target.write_bytes(boss3ds.encrypt(container, key))
            written.append(target)
        # the file list covers every pack's themes, not only this one's
        for theme in all_themes(spec_path):
            if region not in theme_pack.theme_regions(theme):
                continue
            rows.append("\t".join([theme["details_id"], theme.get("price_text", ""), theme["details_id"], theme["item_code"], "1"]))
        (folder / "attributes.tsv").write_text("\n".join(rows) + "\n")
        written.append(folder / "attributes.tsv")
    return written


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    for path in write(Path(sys.argv[1])):
        print(f"{path}  {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
