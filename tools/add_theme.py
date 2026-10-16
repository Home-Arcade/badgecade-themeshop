#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
"""Add themes to BadgeCade's Theme Shop pack: one theme, or a whole collection.

The source is a theme folder or .zip, or a folder/.zip holding many theme
folders. A theme is any folder with body_LZ.bin, preview.png and icon.png or
info.smdh (bgm.bcstm optional): the layout Anemone3DS and ThemePlaza use, and
what tools/make_theme.py makes. For every theme found it:

  1. copies it into themes/added/<name>.zip (preview and icon as plain PNGs),
  2. gives it the next free content index (1-100, no gaps, like Nintendo's
     packs) and its theme ID (pack variation * 1000000 + index, e.g. 09000003),
  3. adds it to the pack spec;

Packs fill in order, like Nintendo's: 8F09 (themes/pack-test-8f09.json),
then 8F08, 8F07, 8F06, 8F05 (themes/pack-8f0N.json, made when needed):
100 themes each, 500 in all. Then for every pack it changed it bumps the
version once, rebuilds the pack (tools/theme_pack.py) and the details pages
(tools/theme_shop_data.py), and sets the shop's stored pack version so
consoles see the update (a new pack is registered in the shop first).

Names, publishers and descriptions come from each theme's name.txt and
info.smdh (or the folder name); --name/--publisher/--description override
them (--name only for a single theme).

    python3 tools/add_theme.py ~/my-theme.zip --name "Space Badges" --publisher "BadgeCade"
    python3 tools/add_theme.py ~/community-themes.zip --dry-run     # list what would be added
    python3 tools/add_theme.py ~/community-themes.zip

Only add themes you made, themes whose creator gave permission, or themes
Nintendo gave away for free. Nintendo's official Theme Shop themes are
refused (tools/official_theme_hashes.txt).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import time
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_theme  # noqa: E402
import theme_pack  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = ROOT / "themes" / "pack-test-8f09.json"
ADDED = ROOT / "themes" / "added"
PERSONAL_THEMES = 3  # personal themes a player can have (they take shop slots)
OFFICIAL = Path(__file__).resolve().parent / "official_theme_hashes.txt"
# Content indexes 1, 2, 3... with no gaps, as in Nintendo's packs (1-100): the Buy
# window (mint) crashed buying content 901 of a 6-content pack (it indexes a table
# sized by the pack's content count with the content index; found in the emulator
# 2026-10-12), and NIM breaks on a pack with ~900 contents. Nintendo's held ~100.
FIRST_INDEX, LAST_INDEX = 1, 100
# Like Nintendo, themes go in several packs: when one is full the next one
# opens. The Theme Shop asks for all ten (8F00-8F09) every time.
# 8F04 (2026-10-13) fills before 8F08-8F05, which are hidden in the shop
PACKS = ["0004008C00008F09", "0004008C00008F04", "0004008C00008F08", "0004008C00008F07", "0004008C00008F06",
         "0004008C00008F05"]
PACK_ITEM_BASE = 7000  # a new pack's own shop item is 7000 + its number (7008 for 8F08)
# Themes' shop items are numbered from 10001, never reused (a deleted theme's goes in
# the spec's "retired_items"). Below that are shopdeck's other items: 4002 is Badge
# Arcade's paid plays, 4001 an old 8F09 theme. Dots & Stripes got 4001 (2026-10-12):
# its purchase was recorded against 8F09, so the 8F08 ticket never granted it and it
# didn't show in Change Theme.
THEME_ITEM_BASE = 10000


def _spec_path(title_id: str) -> Path:
    return DEFAULT_SPEC if title_id == PACKS[0] else ROOT / "themes" / f"pack-{title_id[-4:].lower()}.json"


def _load_packs(spec: Path | None) -> list[tuple[Path, dict]]:
    """(spec path, spec) for every pack, in fill order; packs not made yet start empty."""
    if spec:
        return [(spec, json.loads(spec.read_text()))]
    packs = []
    for title_id in PACKS:
        path = _spec_path(title_id)
        packs.append((path, json.loads(path.read_text()) if path.exists() else {
            "title_id": title_id, "version": 0,
            # each pack its own product code: the Buy flow finds a theme by code + index
            "product_code": "CTR-M-BC%sE" % title_id[-1], "themes": []}))
    return packs


def _proxy_packs() -> set[str] | None:
    """Title ids the proxy serves pack downloads for (.env BADGECADE_CDN_TITLE_IDS), or None if unknown."""
    env = ROOT / ".env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("BADGECADE_CDN_TITLE_IDS="):
            return {item.strip().upper() for item in line.split("=", 1)[1].split(",") if item.strip()}
    return None


def _set_shop_version(spec: dict) -> bool:
    """Set a pack's version in shopdeck for every region it's built for, registering
    the region's pack (copied from 8F09) if it's new."""
    return all(_set_region_shop_version(spec, region) for region in theme_pack.pack_regions(spec))


def _set_region_shop_version(spec: dict, region: str) -> bool:
    title_id, variation = theme_pack.region_title_id(spec["title_id"], region), int(spec["title_id"], 16) & 0xFF
    offset = theme_pack.PACK_REGIONS[region]["items"]  # EUR's items are the USA ones + 100000, JPN's + 200000
    pack_item = PACK_ITEM_BASE + variation + offset // 1000  # 7008, 7108, 7208
    name = f"BadgeCade Themes {variation}" + ("" if region == "USA" else f" ({region})")
    themes = [{"id": th["item_id"] + offset, "code": th["item_code"], "price": int(float(th.get("price", 0))),
               "limit": int(th.get("limit", 0))} for th in spec["themes"] if region in theme_pack.theme_regions(th)]
    code = f"""
from shopdeckdb.models import Title, item
t = Title.objects.filter(tid={title_id!r}).first()
if t is None:
    t = Title.objects.get(tid={PACKS[0]!r})
    t.pk = t.id = None
    t.tid, t.name, t.desc = {title_id!r}, {name!r}, {name!r}
    t.product_code = "CTR-N-BC{variation}H"
    t.save()
    t = Title.objects.get(tid={title_id!r})  # the copy doesn't get its new id back
    item.objects.create(id={pack_item}, title=t, itemcode="CTR-N-BC{variation}T", price=0, limit=0)
for theme in {json.dumps(themes)}:
    it = item.objects.filter(id=theme["id"]).first()
    if it is not None and it.title_id == t.id and it.itemcode == "R" + theme["code"]:
        it.itemcode = theme["code"]  # a deleted theme brought back (admin page Undo)
        it.save()
    if it is not None and (it.title_id != t.id or it.itemcode != theme["code"]):
        raise SystemExit("item %d is %s %s in shopdeck, not this theme (%s): pick another item_id"
                         % (it.id, it.title.tid, it.itemcode, theme["code"]))
    if it is None:
        item.objects.create(id=theme["id"], title=t, itemcode=theme["code"], price=theme["price"], limit=theme["limit"])
    elif it.price != theme["price"]:
        it.price = theme["price"]
        it.save()
# deleted themes' items give up their theme number (a re-used slot's new theme has it;
# download codes look a theme up by number). Purchases of them stay recorded.
keep = {{th["id"] for th in {json.dumps(themes)}}} | {{{pack_item}}}
for it in item.objects.filter(title=t).exclude(id__in=keep).exclude(itemcode__startswith="R"):
    if it.itemcode.isdigit():
        it.itemcode = "R" + it.itemcode
        it.save()
t.version = {spec["version"]}
t.save()
print("version", t.version)
"""
    result = subprocess.run(["docker", "compose", "exec", "-T", "shopdeck", "sh", "-c", "cd /app && python3 manage.py shell"],
                            input=code, cwd=ROOT, capture_output=True, text=True)
    return result.returncode == 0 and f"version {spec['version']}" in result.stdout


def _find_themes(source: Path) -> list[tuple[str, dict[str, bytes]]]:
    """(folder name, files by lowercase name) for every folder holding a body_LZ.bin."""
    folders: dict[str, dict[str, bytes]] = {}
    if source.is_dir():
        for path in sorted(source.rglob("*")):
            if path.is_file():
                folders.setdefault(str(path.parent.relative_to(source)), {})[path.name.lower()] = path.read_bytes()
    else:
        with zipfile.ZipFile(source) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                path = PurePosixPath(info.filename)
                folders.setdefault(str(path.parent), {})[path.name.lower()] = z.read(info)
    found = []
    for folder, files in sorted(folders.items()):
        if "body_lz.bin" not in files or PurePosixPath(folder).name.lower() == "alternative":
            continue
        name = PurePosixPath(folder).name if folder not in ("", ".") else source.stem
        found.append((name, files))
    return found


def _plain_png(data: bytes, width: int | None = None, height: int | None = None) -> bytes:
    """Any PNG as an 8-bit RGBA PNG make_theme can read (optionally resized), via ImageMagick."""
    args = ["convert", "png:-"]
    if width:
        args += ["-resize", f"{width}x{height}!"]
    args += ["-depth", "8", "PNG32:-"]
    return subprocess.run(args, input=data, capture_output=True, check=True).stdout


def _icon_from_smdh(smdh: bytes) -> bytes:
    """The 48x48 icon of an info.smdh (RGB565, 8x8 tiles in Morton order) as a PNG."""
    pixels = smdh[0x24C0:0x24C0 + 48 * 48 * 2]
    image = make_theme.Image(48, 48)
    i = 0
    for ty in range(0, 48, 8):
        for tx in range(0, 48, 8):
            for n in range(64):
                x = sum(((n >> (2 * b)) & 1) << b for b in range(3))
                y = sum(((n >> (2 * b + 1)) & 1) << b for b in range(3))
                value = struct.unpack_from("<H", pixels, i)[0]
                i += 2
                r, g, b = (value >> 11) & 0x1F, (value >> 5) & 0x3F, value & 0x1F
                image.put(tx + x, ty + y, (r * 255 // 31, g * 255 // 63, b * 255 // 31, 255))
    return make_theme.write_png(image)


def _smdh_text(smdh: bytes) -> tuple[str, str, str]:
    """(name, description, publisher) from an info.smdh's English entry."""
    if len(smdh) < 0x8 + 0x200 * 2 or smdh[:4] != b"SMDH":
        return "", "", ""
    entry = 0x8 + 0x200 * 1  # language 1 = English

    def text(offset: int, size: int) -> str:
        return smdh[entry + offset:entry + offset + size].decode("utf-16-le", "ignore").split("\0")[0].strip()

    return text(0, 0x80), text(0x80, 0x100), text(0x180, 0x80)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "theme"


def publish(touched: list[tuple[Path, dict]], set_shop: bool = True) -> tuple[bool, list[str]]:
    """Save each changed pack spec with the next version, rebuild the pack and its
    details pages, and set the shop's pack version. (ok, messages)"""
    lines = []
    for path, spec in touched:
        spec["version"] = int(spec.get("version", 0)) + 1
        backup = path.with_suffix(".json.bak")
        if path.exists():
            shutil.copyfile(path, backup)
        path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
        try:
            for tool in ("theme_pack.py", "theme_shop_data.py"):
                command = [sys.executable, str(ROOT / "tools" / tool)] + (["build"] if tool == "theme_pack.py" else []) + [str(path)]
                subprocess.run(command, check=True, cwd=ROOT, capture_output=True, text=True)
        except subprocess.CalledProcessError as error:
            if backup.exists():
                shutil.copyfile(backup, path)  # leave the spec as it was
            else:
                path.unlink()
            return False, lines + [f"{path.name}: build failed, spec restored:\n{error.stderr or error.stdout}"]
        lines.append(f"pack {spec['title_id'][-4:]}: version {spec['version']}, {len(spec['themes'])} themes")
    if not set_shop:
        return True, lines + ["Shop versions not set (--no-shop)."]
    failed = [spec for _, spec in touched if not _set_shop_version(spec)]
    lines += [f"Could not set pack {spec['title_id'][-4:]}'s shop version; set it to {spec['version']} by hand."
              for spec in failed]
    if not failed:
        lines.append("Shop pack versions set. Open Theme Shop > All Themes on a console to get them.")
    return not failed, lines


def release_scheduled(today: datetime.date | None = None) -> list[str]:
    """Publish the packs holding themes whose day has come ("available_from"),
    once each (run daily by tools/badge_rotation.py). Returns the released names."""
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    released, touched = [], []
    for title_id in PACKS:
        path = _spec_path(title_id)
        if not path.exists():
            continue
        spec = json.loads(path.read_text())
        due = [t for t in spec["themes"] if t.get("available_from") and not t.get("released")
               and datetime.date.fromisoformat(t["available_from"]) <= today]
        for theme in due:
            theme["released"] = True
            released.append(theme)
        if due:
            touched.append((path, spec))
    if touched:
        ok, lines = publish(touched)
        if not ok:
            raise RuntimeError("; ".join(lines))
    return [t["name"] for t in released]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="theme folder or .zip, or a folder/.zip of many themes")
    parser.add_argument("--name", help="name shown in the shop (single theme only)")
    parser.add_argument("--publisher", help="who made it (default: from info.smdh)")
    parser.add_argument("--description", help="text on the details page (default: from info.smdh)")
    parser.add_argument("--bgm-name", help="music name on the details page (default: theme name)")
    parser.add_argument("--price", type=float, default=0, help="price in dollars shown in the shop, e.g. 1.99 (default 0, free)")
    parser.add_argument("--sell", action="store_true",
                        help="players press Buy (free, or --price) instead of owning it already")
    parser.add_argument("--regions", default=",".join(theme_pack.ALL_REGIONS),
                        help="where it's sold: USA,EUR,JPN (default: all; EUR includes Australia)")
    parser.add_argument("--spec", type=Path, help="only this pack spec (default: fill 8F09, then 8F08, 8F07, ...)")
    parser.add_argument("--from", dest="available_from", type=datetime.date.fromisoformat,
                        help="show in the shop from this UTC date (YYYY-MM-DD); its slot is taken now")
    parser.add_argument("--letter-on-release", action="store_true",
                        help="with --from: send the new-theme letter on the release day")
    parser.add_argument("--dry-run", action="store_true", help="only list what would be added")
    parser.add_argument("--no-shop", action="store_true", help="don't set the shop's pack version")
    parser.add_argument("--owner", help="a player's personal theme (BadgeCade username): only their 3DS lists and owns it")
    args = parser.parse_args()

    regions = [r.strip().upper() for r in args.regions.split(",") if r.strip()]
    if not regions or any(r not in theme_pack.ALL_REGIONS for r in regions):
        raise SystemExit(f"--regions: pick from {', '.join(theme_pack.ALL_REGIONS)}")
    found = _find_themes(args.source)
    if not found:
        raise SystemExit(f"{args.source}: no themes found (no folder with a body_LZ.bin)")
    if args.name and len(found) > 1:
        raise SystemExit(f"--name is for one theme, but {args.source} holds {len(found)}")
    official = set()
    if OFFICIAL.exists():
        official = {line.split()[0] for line in OFFICIAL.read_text().splitlines() if line and not line.startswith("#")}
    owner = ""
    if args.owner:
        # personal themes are always checked against the full list of Nintendo's
        # official themes, whatever tools/official_theme_hashes.txt holds
        full = OFFICIAL.with_name("official_theme_hashes.personal.txt")
        if not full.exists():
            raise SystemExit(f"{full} is missing: personal themes can't be checked")
        official |= {line.split()[0] for line in full.read_text().splitlines() if line and not line.startswith("#")}
        owner = hashlib.sha256(b"badgecade-personal:" + args.owner.lower().encode()).hexdigest()[:16]

    packs = _load_packs(args.spec)
    # shop item numbers are unique across every pack, also when adding to one (--spec)
    all_specs = [json.loads(p.read_text()) for p in sorted((ROOT / "themes").glob("pack*.json"))]
    every = [t for spec in all_specs for t in spec.get("themes", [])]
    retired_items = [int(i) for spec in all_specs for i in spec.get("retired_items", [])]
    names = {t["name"].casefold() for t in every}
    # a pack still numbered from 901 takes no new themes until tools/renumber_pack.py has run
    # (its deleted themes' placeholders count too: an emptied 8F09 still has 901-905 installed on consoles)
    old = [spec["title_id"][-4:] for _, spec in packs
           if any(t["index"] > LAST_INDEX for t in spec["themes"]) or any(i > LAST_INDEX for i in spec.get("retired", []))]
    # Make the requested packs available for additions even if their specs
    # currently mark them hidden. The updated specs are published without the
    # hidden flag, so these packs can be made visible in the shop.
    UNHIDE_PACKS = {"8F05", "8F06", "8F07", "8F08"}
    for _, spec in packs:
        if spec["title_id"][-4:].upper() in UNHIDE_PACKS:
            spec.pop("hidden", None)
    packs = [(path, spec) for path, spec in packs if spec["title_id"][-4:] not in old and not spec.get("hidden")]
    # only packs the proxy serves downloads for (.env BADGECADE_CDN_TITLE_IDS)
    served = _proxy_packs()
    if served is not None:
        unserved = [spec["title_id"][-4:] for _, spec in packs if spec["title_id"].upper() not in served]
        packs = [(path, spec) for path, spec in packs if spec["title_id"].upper() in served]
        # each region's copy of a pack needs serving too (EUR 98xx, JPN 82xx)
        missing = sorted({theme_pack.region_title_id(spec["title_id"], r) for _, spec in packs
                          for r in theme_pack.pack_regions(spec)} - served)
        if missing:
            print(f"BADGECADE_CDN_TITLE_IDS (.env) lacks {', '.join(missing)}: those regions' consoles "
                  "can't download these packs until it's added and mitm-proxy and content restart")
        if unserved:
            print(f"pack {', '.join(unserved)}: not in BADGECADE_CDN_TITLE_IDS (.env); add it and restart "
                  "mitm-proxy and content to use it")
    if old:
        print(f"pack {', '.join(old)}: themes numbered from 901; run tools/renumber_pack.py before adding to it")
    # a deleted theme's number can take a new theme (its details page is versioned, so
    # consoles refetch it); its shop item number is never reused
    # each region's copy of a pack has its own slots: a slot can hold a different theme
    # in the US, Europe and Japan (one theme per slot per region)
    used: dict[str, dict[int, set[str]]] = {spec["title_id"]: {} for _, spec in packs}
    for _, spec in packs:
        for t in spec["themes"]:
            used[spec["title_id"]].setdefault(t["index"], set()).update(theme_pack.theme_regions(t, planned=True))
    if owner and sum(1 for t in every if t.get("owner") == owner) + len(found) > PERSONAL_THEMES:
        raise SystemExit(f"{args.owner} can have {PERSONAL_THEMES} personal themes at most")
    next_item_id = max([t.get("item_id", 0) for t in every]
                       + retired_items + [THEME_ITEM_BASE]) + 1
    touched: list[tuple[Path, dict]] = []
    added, skipped = [], []

    for folder, files in found:
        smdh_name, smdh_desc, smdh_pub = _smdh_text(files.get("info.smdh", b""))
        name_txt = files.get("name.txt", b"").decode("utf-8-sig", "ignore").strip()
        name = args.name or name_txt or smdh_name or re.sub(r"^\d+\s*-\s*", "", folder)
        if hashlib.sha1(files["body_lz.bin"]).hexdigest() in official:
            skipped.append((name, "official Nintendo theme (not allowed)"))
            continue
        if name.casefold() in names:
            skipped.append((name, "already in the pack"))
            continue
        if "preview.png" not in files:
            skipped.append((name, "no preview.png"))
            continue
        if "icon.png" not in files and "info.smdh" not in files:
            skipped.append((name, "no icon.png or info.smdh"))
            continue
        slot = next(((path, spec, i) for path, spec in packs for i in range(FIRST_INDEX, LAST_INDEX + 1)
                     if not used[spec["title_id"]].get(i, set()) & set(regions)), None)
        if slot is None:
            skipped.append((name, "no pack can take it (full, or see the notes above)"))
            continue
        path, spec, index = slot
        used[spec["title_id"]].setdefault(index, set()).update(regions)
        names.add(name.casefold())
        if not any(p == path for p, _ in touched):
            touched.append((path, spec))
        theme_id = "%08d" % ((int(spec["title_id"], 16) & 0xFF) * 1000000 + index)
        spec["retired"] = [i for i in spec.get("retired", []) if i != index]  # reused: no placeholder now
        has_bgm = "bgm.bcstm" in files
        added.append((name, spec["title_id"][-4:], index, theme_id, has_bgm))
        if args.dry_run:
            continue

        ADDED.mkdir(parents=True, exist_ok=True)
        slug = _slug(name)
        theme_zip = ADDED / f"{slug}.zip"
        icon_png = ADDED / f"{slug}-icon.png"
        with zipfile.ZipFile(theme_zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("body_LZ.bin", files["body_lz.bin"])
            if has_bgm:
                z.writestr("bgm.bcstm", files["bgm.bcstm"])
            z.writestr("preview.png", _plain_png(files["preview.png"]))
        icon_png.write_bytes(_plain_png(files["icon.png"], 48, 48) if "icon.png" in files
                            else _icon_from_smdh(files["info.smdh"]))
        spec["themes"].append({
            "index": index, "name": name, "description": args.description or smdh_desc,
            "zip": str(theme_zip.relative_to(ROOT)), "icon": str(icon_png.relative_to(ROOT)),
            "item_id": next_item_id,  # unique across all packs
            "item_code": theme_id, "details_id": theme_id,
            "publisher": args.publisher or smdh_pub or ("Personal" if owner else "Community"),
            "bgm": (args.bgm_name or name) if has_bgm else "None", "bgm_type": 1,
            # sold themes (free or priced) are not pre-granted: every console buys them;
            # a personal theme is owned by its player only (shopdeck checks "owner")
            "granted": not (args.sell or args.price > 0) and not owner, "title_included": True,
            **({"owner": owner} if owner else {}),
            "price": round(max(0, args.price), 2),
            "regions": regions,
            # when it went in the shop (ms), the Theme Shop's NewSince: recent themes show as new
            "added": int(time.time() * 1000),
            **({"available_from": args.available_from.isoformat()} if args.available_from else {}),
            **({"letter_on_release": True} if args.available_from and args.letter_on_release else {}),
            **({"price_text": "$%.2f" % args.price} if args.price > 0 else {}),
        })
        next_item_id += 1

    for name, pack, index, theme_id, has_bgm in added:
        print(f"{'would add' if args.dry_run else 'added'}: {name} (pack {pack}, index {index}, ID {theme_id}{', music' if has_bgm else ''})")
    for name, why in skipped:
        print(f"skipped: {name}: {why}")
    free = ", ".join(f"{r} %d" % sum(LAST_INDEX - FIRST_INDEX + 1 - sum(1 for rs in u.values() if r in rs)
                                       for u in used.values()) for r in theme_pack.ALL_REGIONS)
    if args.dry_run or not added:
        print(f"{len(added)} to add, {len(skipped)} skipped, slots left after: {free}"
              + (" (dry run, nothing changed)" if args.dry_run else ""))
        return 0

    ok, lines = publish(touched, set_shop=not args.no_shop)
    print("\n".join(lines))
    print(f"{len(added)} added, {len(skipped)} skipped, slots left: {free}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
