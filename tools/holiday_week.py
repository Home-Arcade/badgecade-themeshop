#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
"""Holiday weeks: the arcade dressed up for a holiday, as Nintendo's was.

Nintendo's own holiday weeks (2015-2017) were never archived, and the
archived 2022-23 weeks are reruns with no holiday content, so a holiday week
is made here: in the week a holiday falls in (theme_admin.HOLIDAYS dates,
Easter and Thanksgiving worked out each year)
  - the Bunny's greeting ends with the holiday's wishes, in every language;
  - the hall poster (in place of Miiverse's, tools/miiverse_poster.py) is a
    holiday poster of its own: the wishes on a ribbon over the holiday's
    motifs (stars, snowflakes, hearts...), Nintendo's holiday badges as pin badges;
  - the weekly letter opens with the holiday (tools/badge_rotation.py).
Thanksgiving is US only; Japan has no Easter or Thanksgiving week.

    python3 tools/holiday_week.py                    # the coming holiday weeks
    python3 tools/holiday_week.py --region EUR -o /tmp/holiday --holiday christmas   # preview poster
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REGIONS = {
    "newyear": {"USA", "EUR", "JPN"},
    "valentine": {"USA", "EUR", "JPN"},
    "easter": {"USA", "EUR"},
    "halloween": {"USA", "EUR", "JPN"},
    "thanksgiving": {"USA"},
    "christmas": {"USA", "EUR", "JPN"},
}

# poster look per holiday: background (centre, edge), motif and its colours,
# ribbon (face, shade), big lettering (top, bottom), pin badge backs
PALETTES = {
    "newyear": (("#2c43a8", "#141f5c"), "star", ("#ffe066c0", "#ffffffa0", "#ff9ec4a0"), ("#d4202c", "#8c0f18"),
                ("#fff7c2", "#f2b400"), "#fff1c4"),
    "valentine": (("#ff8fb8", "#e0457f"), "heart", ("#ffffffb0", "#ffd0e0c0", "#d81e5bb0"), ("#c8104b", "#7e0730"),
                  ("#ffffff", "#ffc2d8"), "#ffe3ee"),
    "easter": (("#a6eadd", "#4fbfa9"), "egg", ("#fff38ac0", "#d9b8ffc0", "#ffb8d9c0"), ("#8a5cd6", "#563493"),
               ("#fffbd0", "#ffd84a"), "#fff8d8"),
    "halloween": (("#6b3aa0", "#2a1145"), ("moon", "star"), ("#ffd23fc0", "#ff8a00b0", "#ffffff80"), ("#ff7a00", "#a84a00"),
                  ("#fff3a0", "#ffb000"), "#ffe2b8"),
    "thanksgiving": (("#e08a3c", "#9c4412"), "leaf", ("#ffd23fc0", "#d9471bc0", "#8a3a10c0"), ("#7a3b10", "#4a2208"),
                     ("#fff3b0", "#ffb000"), "#ffefd2"),
    "christmas": (("#2fa04a", "#11602a"), ("snowflake", "star"), ("#ffffffc0", "#fff3b0b0", "#ffffff80"), ("#d4202c", "#8c0f18"),
                  ("#ffffff", "#ffe066"), "#fff4f0"),
}

# Nintendo's own holiday badges (from the archived weeks, where they turn up
# at random times of year), shown as pin badges on the poster; Thanksgiving
# never had a set, so it gets harvest food and the arcade's "Thanks!" stamp.
# Copied out once with `holiday_week.py --fetch-badges` (to rotation/holiday-badges).
BADGES = {
    "halloween": ["PokeExt_HalloweenPikachu00", "MdWario_CharaHalloween_Pumpkin00", "PokeExt_HalloweenEievui00",
                  "PokeExt_HalloweenBakeccha00", "MdWario_CharaHalloween_Dracula00"],
    "christmas": ["PokeExt_XmasPikachu00", "MdWario_Item_Xmas00", "PokeExt_XmasEievui00",
                  "MdWario_CharaRabbit_Xmas00", "PokeExt_XmasDelibird00"],
    "newyear": ["PokeExt_NewYearPikachu00", "MdWario_CharaKadomatsu_NewYear", "PokeExt_NewYearKoiking00",
                "MH2_NewYear000", "PokeExt_NewYearMetamon00"],
    "valentine": ["PokeExt_ValentinePikachu00", "MdWario_CharaChocolate_Valentine", "Tomodachi_food219",
                  "PokeExt_ValentinePikachu01", "Tomodachi_food197"],
    "easter": ["PokeExt_EasterPikachu00", "PokeExt_EasterTogepi00", "PokeExt_EasterIbui00",
               "AnimalItem2_int_egg_tableS", "PokeExt_EasterPocchama00"],
    "thanksgiving": ["BTCenter2_Stamp_Thanks00_Sep", "Tomodachi_food117", "Tomodachi_food151",
                     "Rhythm_Ground_apple", "Tomodachi_food062"],
}
BADGE_DIR = Path(__file__).resolve().parent.parent / "rotation" / "holiday-badges"


def holiday_badges(key: str) -> list[bytes]:
    """The holiday's badge pictures (PNG); those not fetched yet are left out."""
    return [path.read_bytes() for name in BADGES[key] if (path := BADGE_DIR / f"{name}.png").exists()]


def fetch_badges() -> str:
    """Copy the holiday badges out of Nintendo's archived weeks (once)."""
    import boss3ds
    import sarc
    import week_page
    import yaz0
    from badge_rotation import ARCHIVE
    wanted = {name for names in BADGES.values() for name in names if not (BADGE_DIR / f"{name}.png").exists()}
    BADGE_DIR.mkdir(parents=True, exist_ok=True)
    key = boss3ds.load_key()
    for path in sorted(ARCHIVE.glob("data_*.enc")):
        if not wanted:
            break
        files, _ = sarc.read(boss3ds.decrypt(path.read_bytes(), key)["payloads"][0]["content"])
        for name, data in files.items():
            if not name.startswith("sharc/"):
                continue
            inner, _ = sarc.read(data)
            for badge in list(wanted):
                prb = inner.get(f"pc/rt/Pr/Pr_{badge}.prb.szs")
                if prb is not None:
                    (BADGE_DIR / f"{badge}.png").write_bytes(week_page.badge_png(yaz0.decompress(prb)))
                    wanted.discard(badge)
    return "all holiday badges fetched" if not wanted else f"not found: {', '.join(sorted(wanted))}"


# the wishes, by poster language suffix ("" = USA) / BossText language
WISHES = {
    "newyear": {"en": ("Happy", "New Year!"), "de": ("Frohes", "neues Jahr!"), "fr": ("Bonne", "année !"),
                "es": ("¡Feliz", "Año Nuevo!"), "it": ("Buon", "anno nuovo!"), "ja": ("", "あけましておめでとうっす!")},
    "valentine": {"en": ("Happy", "Valentine's Day!"), "de": ("Alles Liebe zum", "Valentinstag!"),
                  "fr": ("Joyeuse", "Saint-Valentin !"), "es": ("¡Feliz", "San Valentín!"),
                  "it": ("Buon", "San Valentino!"), "ja": ("", "ハッピーバレンタインっす!")},
    "easter": {"en": ("Happy", "Easter!"), "de": ("Frohe", "Ostern!"), "fr": ("Joyeuses", "Pâques !"),
               "es": ("¡Felices", "Pascuas!"), "it": ("Buona", "Pasqua!")},
    "halloween": {"en": ("Happy", "Halloween!"), "de": ("Fröhliches", "Halloween!"), "fr": ("Joyeux", "Halloween !"),
                  "es": ("¡Feliz", "Halloween!"), "it": ("Buon", "Halloween!"), "ja": ("", "ハッピーハロウィンっす!")},
    "thanksgiving": {"en": ("Happy", "Thanksgiving!")},
    "christmas": {"en": ("Merry", "Christmas!"), "de": ("Frohe", "Weihnachten!"), "fr": ("Joyeux", "Noël !"),
                  "es": ("¡Feliz", "Navidad!"), "it": ("Buon", "Natale!"), "ja": ("", "メリークリスマスっす!")},
}
# the Bunny's last greeting line (DontTouch_008, "Have a great time, all right?")
# becomes the wishes plus a short sign-off
GREETING = "DontTouch_008"
SIGN_OFF = {"en": "Have a great time, all right?", "de": "Amüsier dich gut!", "fr": "Amusez-vous bien !",
            "es": "¡Que te lo pases de lujo!", "it": "Pensa a divertirti!", "ja": "楽しんでいってほしいっす!"}


def _motif(kind: str, cx: float, cy: float, r: float, turn: float) -> str:
    """An ImageMagick draw primitive for one background motif."""
    import math

    def poly(points):
        return "polygon " + " ".join(f"{cx + x * math.cos(turn) - y * math.sin(turn):.1f},"
                                     f"{cy + x * math.sin(turn) + y * math.cos(turn):.1f}" for x, y in points)
    if kind == "star":
        return poly([((r if i % 2 == 0 else r * 0.45) * math.sin(i * math.pi / 5),
                      -(r if i % 2 == 0 else r * 0.45) * math.cos(i * math.pi / 5)) for i in range(10)])
    if kind == "heart":
        return poly([(r * 0.06 * 16 * math.sin(t) ** 3,
                      -r * 0.06 * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
                     for t in [i * math.pi / 18 for i in range(36)]])
    if kind == "egg":
        return poly([(r * 0.72 * math.sin(t), -r * math.cos(t) * (0.85 if math.cos(t) > 0 else 1.0))
                     for t in [i * math.pi / 18 for i in range(36)]])
    if kind == "leaf":
        return poly([(r * math.cos(t), r * 0.42 * math.sin(t) * (1 + 0.3 * math.cos(t)))
                     for t in [i * math.pi / 18 for i in range(36)]])
    if kind == "moon":
        # the lit edge: the outer circle's left side, minus a circle shifted right
        outer = [(r * math.cos(t), r * math.sin(t)) for t in [math.radians(a) for a in range(50, 311, 10)]]
        inner = [(r * 0.35 + r * 0.8 * math.cos(t), r * 0.8 * math.sin(t))
                 for t in [math.radians(a) for a in range(290, 69, -10)]]
        return poly(outer + inner)
    if kind == "snowflake":
        arms = []
        for i in range(6):
            a = turn + i * math.pi / 3
            ex, ey = cx + r * math.cos(a), cy + r * math.sin(a)
            arms.append(f"line {cx:.1f},{cy:.1f} {ex:.1f},{ey:.1f}")
            for side in (-1, 1):
                mx, my = cx + r * 0.6 * math.cos(a), cy + r * 0.6 * math.sin(a)
                b = a + side * math.pi / 4
                arms.append(f"line {mx:.1f},{my:.1f} {mx + r * 0.35 * math.cos(b):.1f},{my + r * 0.35 * math.sin(b):.1f}")
        return " ".join(arms)
    raise ValueError(kind)


def draw(key: str, language: str, badges: list[bytes]):
    """The holiday poster (320x156): the wishes on a ribbon over a pattern of
    the holiday's motifs, this week's badges as round pin badges below."""
    import random
    import subprocess
    import tempfile
    import make_theme as mt
    from miiverse_poster import FONT, H, SCALE, W, _lettering, _magick, pins

    (centre, edge), kind, motif_colours, (ribbon, shade), (big_top, big_bottom), pin_back = PALETTES[key]
    badges = holiday_badges(key) or badges  # the holiday's own badges; the week's if not fetched
    first, second = WISHES[key].get(language, WISHES[key]["en"])
    w, h = W * SCALE, H * SCALE
    rng = random.Random(key)
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        draws = []
        for n in range(26):
            colour = motif_colours[n % len(motif_colours)]
            cx, cy, r = rng.uniform(0, w), rng.uniform(0, h), rng.uniform(10, 24)
            shape = kind[n % len(kind)] if isinstance(kind, tuple) else kind
            primitive = _motif(shape, cx, cy, r, rng.uniform(-0.6, 0.6))
            if shape == "snowflake":
                draws += ["-fill", "none", "-stroke", colour, "-strokewidth", "3", "-draw", primitive]
            else:
                draws += ["-stroke", "none", "-fill", colour, "-draw", primitive]
        _magick("-size", f"{w}x{h}", f"radial-gradient:{centre}-{edge}", *draws, t / "back.png")
        # the ribbon: tails behind, then the band
        top, bottom = 84, 168
        ribbon_draw = [
            "-stroke", "none", "-fill", shade,
            "-draw", f"polygon 14,{top + 20} 78,{top + 20} 78,{bottom + 20} 14,{bottom + 20} 34,{(top + bottom) // 2 + 20}",
            "-draw", f"polygon {w - 14},{top + 20} {w - 78},{top + 20} {w - 78},{bottom + 20} {w - 14},{bottom + 20} {w - 34},{(top + bottom) // 2 + 20}",
            "-fill", "#00000060", "-draw", f"polygon 58,{bottom} 78,{bottom} 78,{bottom + 20}",
            "-draw", f"polygon {w - 58},{bottom} {w - 78},{bottom} {w - 78},{bottom + 20}",
            "-fill", "white", "-draw", f"rectangle 54,{top - 4} {w - 55},{bottom + 4}",
            "-fill", ribbon, "-draw", f"rectangle 58,{top} {w - 59},{bottom}",
            "-fill", "#ffffff30", "-draw", f"rectangle 58,{top} {w - 59},{top + 24}",
        ]
        _lettering(t / "big.png", second, 60, big_top, big_bottom, "black", 5)
        _magick(t / "big.png", "-resize", f"{w - 150}x{bottom - top}>", t / "big.png")
        layers = []
        if first:
            _lettering(t / "first.png", first, 34, "#ffffff", "#fff3b0", "black", 4)
            _magick(t / "first.png", "-resize", "420x60>", t / "first.png")
            layers += [t / "first.png", "+0+18"]
        layers += [t / "big.png", f"+0+{(top + bottom) // 2 - 44}"]
        # pin badges
        count = min(5, len(badges))
        size, gap = 86, 22
        left = (w - count * size - (count - 1) * gap) // 2
        pin_layers = []
        for i, png in enumerate(badges[:count]):
            (t / f"b{i}.png").write_bytes(png)
            _magick("-size", f"{size}x{size}", "xc:none", "-fill", "white", "-draw",
                    f"circle {size // 2},{size // 2} {size // 2},2", "-fill", pin_back, "-draw",
                    f"circle {size // 2},{size // 2} {size // 2},7",
                    "(", t / f"b{i}.png", "-resize", f"{size - 18}x{size - 18}", ")", "-gravity", "center",
                    "-compose", "over", "-composite",
                    "(", "+clone", "-background", "#00000080", "-shadow", "60x2+2+3", ")", "+swap",
                    "-background", "none", "-layers", "merge", "+repage", t / f"pin{i}.png")
            pin_layers += [t / f"pin{i}.png", f"+{left + i * (size + gap)}+{bottom + 28}"]
        args = [t / "back.png", *ribbon_draw, "-gravity", "north"]
        for layer, at in zip(layers[::2], layers[1::2]):
            args += [layer, "-geometry", at, "-compose", "over", "-composite"]
        args += ["-gravity", "northwest"]
        for layer, at in zip(pin_layers[::2], pin_layers[1::2]):
            args += [layer, "-geometry", at, "-compose", "over", "-composite"]
        args += ["-fill", "none", "-stroke", "white", "-strokewidth", "8", "-draw", f"rectangle 4,4 {w - 5},{h - 5}",
                 "-resize", f"{W}x{H}!", t / "poster.png"]
        _magick(*args)
        poster = mt.read_png(t / "poster.png")
    pins(poster)
    return poster


def holiday_day(key: str, year: int) -> datetime.date:
    import theme_admin
    return theme_admin.HOLIDAYS[key][1](year)


def holiday_for_week(region: str, start: datetime.date) -> str | None:
    """The holiday falling in the week starting `start` (its file also covers the day before)."""
    for key, regions in REGIONS.items():
        if region not in regions:
            continue
        for year in (start.year - 1, start.year, start.year + 1):
            if start - datetime.timedelta(days=1) <= holiday_day(key, year) < start + datetime.timedelta(days=7):
                return key
    return None


def season(region: str, day: datetime.date) -> str | None:
    """The holiday whose season (the holiday offers' days, theme_admin.HOLIDAYS)
    includes `day` in this region, for the Theme Shop's seasonal banner."""
    import theme_admin
    for key, regions in REGIONS.items():
        if region not in regions:
            continue
        _, anchor, before, after = theme_admin.HOLIDAYS[key]
        for year in (day.year - 1, day.year, day.year + 1):
            date = anchor(year)
            if date - datetime.timedelta(days=before) <= day <= date + datetime.timedelta(days=after):
                return key
    return None


def wishes(key: str, language: str) -> str:
    """The wishes as one line: "Happy Halloween!", "ハッピーハロウィンっす!"."""
    first, second = WISHES[key].get(language, WISHES[key]["en"])
    return f"{first} {second}".strip()


def set_greeting(files: dict[str, bytes], region: str, key: str) -> int:
    """The Bunny's greeting ends with the holiday's wishes in every language."""
    import msbt
    changed = 0
    for path in [n for n in files if n.startswith(f"message/boss_{region}/") and n.endswith("/BossText.msbt")]:
        language = path.split("/")[2][2:]  # USen -> en, JPja -> ja
        if language not in SIGN_OFF:
            continue
        m = msbt.Msbt(files[path])
        original = m.by_label().get(GREETING)
        if original is None:
            continue
        cut = original.find("{{tag:2:")
        m.set(GREETING, wishes(key, language) + "\n" + SIGN_OFF[language] + (original[cut:] if cut >= 0 else ""))
        files[path] = m.to_bytes()
        changed += 1
    return changed


def apply(files: dict[str, bytes], region: str, start: datetime.date, badges: list[bytes], poster: bool) -> str:
    key = holiday_for_week(region, start)
    if key is None:
        return ""
    import theme_admin
    lines = set_greeting(files, region, key)
    note = f"{region}: {theme_admin.HOLIDAYS[key][0]} week (greeting in {lines} languages"
    if poster:
        import miiverse_poster
        drawn = miiverse_poster.apply(files, region, badges, holiday=key)
        note += ", holiday poster" if drawn else ""
    return note + ")"


def main() -> int:
    import theme_admin
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default="USA")
    parser.add_argument("--holiday", choices=tuple(REGIONS))
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--fetch-badges", action="store_true", help="copy the holiday badges out of the archive")
    args = parser.parse_args()
    if args.fetch_badges:
        print(fetch_badges())
        return 0
    if args.output and args.holiday:
        import ad_pictures
        import badge_rotation
        import boss3ds
        import make_theme as mt
        import miiverse_poster
        data = badge_rotation.RegionData(args.region, boss3ds.load_key())
        today = datetime.datetime.now(datetime.timezone.utc).date()
        badges = ad_pictures.week_badges(data.files, badge_rotation.week_series_codes(data, data.week_start(today)))
        args.output.mkdir(parents=True, exist_ok=True)
        for suffix, language in (("", "en"),) if args.region != "EUR" else miiverse_poster.EUR_LANGUAGES.items():
            image = draw(args.holiday, language, badges)
            (args.output / f"{args.holiday}{suffix}.png").write_bytes(mt.write_png(image))
        print(f"wrote {args.holiday} posters to {args.output}")
        return 0
    today = datetime.datetime.now(datetime.timezone.utc).date()
    for key, regions in REGIONS.items():
        day = holiday_day(key, today.year)
        if day < today - datetime.timedelta(days=7):
            day = holiday_day(key, today.year + 1)
        print(f"{theme_admin.HOLIDAYS[key][0]}: {day} ({', '.join(sorted(regions))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
