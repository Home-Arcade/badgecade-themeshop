#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
"""Build a 3DS HOME Menu theme (.zip for Anemone3DS) from two pictures.

The zip holds body_LZ.bin (the theme, LZ11-compressed), info.smdh (name,
author and icon shown by theme managers) and preview.png. The top screen is a
static 412x240 picture and the bottom screen a static 320x240 picture, using
the theme layout documented at https://www.3dbrew.org/wiki/Home_Menu/Themes.

    python3 tools/make_theme.py --top top.png --bottom bottom.png --icon icon.png \\
        --name "BadgeCade" --author "BadgeCade" --description "..." -o themes/badgecade.zip
    python3 tools/make_theme.py --sample -o themes/badgecade-sample.zip
"""

from __future__ import annotations

import argparse
import io
import struct
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBSITE = Path("/var/www/html")

TOP_W, TOP_H = 412, 240
BOTTOM_W, BOTTOM_H = 320, 240


# --- pictures: a minimal PNG reader/writer and resizing (no Pillow here) ---

class Image:
    def __init__(self, width: int, height: int, pixels: list[tuple[int, int, int, int]] | None = None):
        self.width, self.height = width, height
        self.pixels = pixels or [(0, 0, 0, 255)] * (width * height)

    def get(self, x: int, y: int) -> tuple[int, int, int, int]:
        return self.pixels[y * self.width + x]

    def put(self, x: int, y: int, rgba: tuple[int, int, int, int]) -> None:
        self.pixels[y * self.width + x] = rgba


def read_png(path: Path) -> Image:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    at, idat, header = 8, b"", None
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        body = data[at + 8:at + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        at += 12 + length
    width, height, depth, color, _, _, interlace = header
    channels = {2: 3, 6: 4, 0: 1, 4: 2}.get(color)
    if depth != 8 or channels is None or interlace:
        raise ValueError(f"{path}: only 8-bit non-interlaced RGB/RGBA/grey PNGs are supported")
    raw = zlib.decompress(idat)
    stride = width * channels
    rows, prev, at = [], bytearray(stride), 0
    for _ in range(height):
        kind, line = raw[at], bytearray(raw[at + 1:at + 1 + stride])
        at += 1 + stride
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b = prev[i]
            c = prev[i - channels] if i >= channels else 0
            if kind == 1:
                line[i] = (line[i] + a) & 255
            elif kind == 2:
                line[i] = (line[i] + b) & 255
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    pixels = []
    for line in rows:
        for x in range(width):
            px = line[x * channels:(x + 1) * channels]
            if channels == 4:
                pixels.append(tuple(px))
            elif channels == 3:
                pixels.append((px[0], px[1], px[2], 255))
            elif channels == 2:
                pixels.append((px[0], px[0], px[0], px[1]))
            else:
                pixels.append((px[0], px[0], px[0], 255))
    return Image(width, height, pixels)


def write_png(image: Image) -> bytes:
    raw = bytearray()
    for y in range(image.height):
        raw.append(0)
        for x in range(image.width):
            raw += bytes(image.get(x, y))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def resize(image: Image, width: int, height: int) -> Image:
    """Box-filter resize (good for shrinking, fine for small enlargements)."""
    out = Image(width, height)
    sx, sy = image.width / width, image.height / height
    for y in range(height):
        y0, y1 = int(y * sy), max(int(y * sy) + 1, int((y + 1) * sy))
        for x in range(width):
            x0, x1 = int(x * sx), max(int(x * sx) + 1, int((x + 1) * sx))
            r = g = b = a = n = 0
            for yy in range(y0, min(y1, image.height)):
                for xx in range(x0, min(x1, image.width)):
                    pr, pg, pb, pa = image.get(xx, yy)
                    r += pr * pa
                    g += pg * pa
                    b += pb * pa
                    a += pa
                    n += 1
            out.put(x, y, (r // a, g // a, b // a, a // n) if a else (0, 0, 0, 0))
    return out


def cover(image: Image, width: int, height: int) -> Image:
    """Scale to fill width x height, cropping the overflow from the middle."""
    scale = max(width / image.width, height / image.height)
    scaled = resize(image, max(width, round(image.width * scale)), max(height, round(image.height * scale)))
    left, top = (scaled.width - width) // 2, (scaled.height - height) // 2
    out = Image(width, height)
    for y in range(height):
        for x in range(width):
            out.put(x, y, scaled.get(left + x, top + y))
    return out


def paste(base: Image, top: Image, left: int, upper: int) -> None:
    for y in range(top.height):
        for x in range(top.width):
            bx, by = left + x, upper + y
            if 0 <= bx < base.width and 0 <= by < base.height:
                r, g, b, a = top.get(x, y)
                br, bg, bb, ba = base.get(bx, by)
                base.put(bx, by, ((r * a + br * (255 - a)) // 255, (g * a + bg * (255 - a)) // 255,
                                  (b * a + bb * (255 - a)) // 255, 255))


def tint(image: Image, rgb: tuple[int, int, int], amount: float) -> Image:
    out = Image(image.width, image.height)
    out.pixels = [(round(r + (rgb[0] - r) * amount), round(g + (rgb[1] - g) * amount),
                   round(b + (rgb[2] - b) * amount), a) for r, g, b, a in image.pixels]
    return out


# --- 3DS formats ---

def _morton(x: int, y: int) -> int:
    return (x & 1) | ((y & 1) << 1) | ((x & 2) << 1) | ((y & 2) << 2) | ((x & 4) << 2) | ((y & 4) << 3)


def rgb565_tiled(image: Image, width: int, height: int) -> bytes:
    """A width x height RGB565 texture in 8x8 Morton tiles; the picture sits top-left."""
    out = bytearray(width * height * 2)
    for y in range(min(image.height, height)):
        for x in range(min(image.width, width)):
            r, g, b, _ = image.get(x, y)
            i = ((y // 8) * (width // 8) + x // 8) * 64 + _morton(x % 8, y % 8)
            struct.pack_into("<H", out, i * 2, ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
    return bytes(out)


def lz11_compress(data: bytes) -> bytes:
    out = bytearray(b"\x11" + struct.pack("<I", len(data))[:3])
    if len(data) > 0xFFFFFF:
        raise ValueError("too big for LZ11")
    heads: dict[bytes, list[int]] = {}
    at = 0
    while at < len(data):
        flag_at = len(out)
        out.append(0)
        for bit in range(8):
            if at >= len(data):
                break
            best_len = best_disp = 0
            key = data[at:at + 3]
            if len(key) == 3:
                for start in reversed(heads.get(key, [])[-64:]):
                    disp = at - start
                    if disp > 0x1000:
                        break
                    length = 3
                    limit = min(0x10110, len(data) - at)
                    while length < limit and data[start + length] == data[at + length]:
                        length += 1
                    if length > best_len:
                        best_len, best_disp = length, disp
                        if length == limit:
                            break
            if best_len >= 3:
                out[flag_at] |= 0x80 >> bit
                d = best_disp - 1
                if best_len <= 0x10:
                    out += bytes((((best_len - 1) << 4) | (d >> 8), d & 0xFF))
                elif best_len <= 0x110:
                    n = best_len - 0x11
                    out += bytes((n >> 4, ((n & 0xF) << 4) | (d >> 8), d & 0xFF))
                else:
                    n = best_len - 0x111
                    out += bytes((0x10 | (n >> 12), (n >> 4) & 0xFF, ((n & 0xF) << 4) | (d >> 8), d & 0xFF))
                step = best_len
            else:
                out.append(data[at])
                step = 1
            for i in range(at, at + step):
                heads.setdefault(data[i:i + 3], []).append(i)
            at += step
    while len(out) % 4:
        out.append(0)
    return bytes(out)


def lz11_decompress(data: bytes) -> bytes:
    size = int.from_bytes(data[1:4], "little")
    out, at = bytearray(), 4
    while len(out) < size:
        flags = data[at]
        at += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                b0 = data[at]
                kind = b0 >> 4
                if kind == 0:
                    length = (((b0 & 0xF) << 4) | (data[at + 1] >> 4)) + 0x11
                    disp = ((data[at + 1] & 0xF) << 8) | data[at + 2]
                    at += 3
                elif kind == 1:
                    length = (((b0 & 0xF) << 12) | (data[at + 1] << 4) | (data[at + 2] >> 4)) + 0x111
                    disp = ((data[at + 2] & 0xF) << 8) | data[at + 3]
                    at += 4
                else:
                    length = kind + 1
                    disp = ((b0 & 0xF) << 8) | data[at + 1]
                    at += 2
                for _ in range(length):
                    out.append(out[-disp - 1])
            else:
                out.append(data[at])
                at += 1
    return bytes(out)


def body(top: Image, bottom: Image) -> bytes:
    """Theme body: static top texture (texture0) and static bottom texture (texture2)."""
    header = bytearray(0xD0)
    top_at = 0xD0
    bottom_at = top_at + 512 * 256 * 2
    struct.pack_into("<I", header, 0x00, 1)          # version
    struct.pack_into("<I", header, 0x0C, 3)          # top: texture
    struct.pack_into("<I", header, 0x10, 1)          # top: no scroll (texture0)
    struct.pack_into("<I", header, 0x18, top_at)
    struct.pack_into("<I", header, 0x20, 3)          # bottom: texture
    struct.pack_into("<I", header, 0x24, 1)          # bottom: no scroll (texture2)
    struct.pack_into("<I", header, 0x28, bottom_at)
    return bytes(header) + rgb565_tiled(top, 512, 256) + rgb565_tiled(bottom, 512, 256)


def smdh(name: str, description: str, author: str, icon: Image) -> bytes:
    out = bytearray(0x36C0)
    out[0:4] = b"SMDH"
    for lang in range(16):
        base = 8 + lang * 0x200
        out[base:base + 0x80] = name.encode("utf-16-le")[:0x7E].ljust(0x80, b"\0")
        out[base + 0x80:base + 0x180] = description.encode("utf-16-le")[:0xFE].ljust(0x100, b"\0")
        out[base + 0x180:base + 0x200] = author.encode("utf-16-le")[:0x7E].ljust(0x80, b"\0")
    small, large = resize(icon, 24, 24), resize(icon, 48, 48)
    flat = lambda img: Image(img.width, img.height, [  # noqa: E731  icons have no alpha
        ((r * a + 255 * (255 - a)) // 255, (g * a + 255 * (255 - a)) // 255, (b * a + 255 * (255 - a)) // 255, 255)
        for r, g, b, a in img.pixels])
    out[0x2040:0x2040 + 0x480] = rgb565_tiled(flat(small), 24, 24)
    out[0x24C0:0x24C0 + 0x1200] = rgb565_tiled(flat(large), 48, 48)
    return bytes(out)


def preview(top: Image, bottom: Image) -> Image:
    out = Image(TOP_W, TOP_H * 2, [(0, 0, 0, 255)] * (TOP_W * TOP_H * 2))
    paste(out, top, 0, 0)
    paste(out, bottom, (TOP_W - BOTTOM_W) // 2, TOP_H)
    return out


def build(top: Image, bottom: Image, icon: Image, name: str, description: str, author: str) -> bytes:
    top, bottom = cover(top, TOP_W, TOP_H), cover(bottom, BOTTOM_W, BOTTOM_H)
    raw = body(top, bottom)
    compressed = lz11_compress(raw)
    if lz11_decompress(compressed) != raw:
        raise RuntimeError("LZ11 round trip failed")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("body_LZ.bin", compressed)
        z.writestr("info.smdh", smdh(name, description, author, icon))
        z.writestr("preview.png", write_png(preview(top, bottom)))
    return buffer.getvalue()


def sample() -> tuple[Image, Image, Image]:
    """BadgeCade's website background with the badge logo."""
    background = read_png(WEBSITE / "background.png")
    logo = read_png(WEBSITE / "badge.png")
    top = cover(background, TOP_W, TOP_H)
    paste(top, resize(logo, 150, 148), (TOP_W - 150) // 2, (TOP_H - 148) // 2)
    bottom = tint(cover(background, BOTTOM_W, BOTTOM_H), (255, 122, 24), 0.45)
    for left, upper in ((14, 14), (262, 14), (14, 182), (262, 182)):
        paste(bottom, resize(logo, 44, 44), left, upper)
    return top, bottom, logo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", action="store_true", help="build the BadgeCade sample theme")
    parser.add_argument("--top", type=Path)
    parser.add_argument("--bottom", type=Path)
    parser.add_argument("--icon", type=Path)
    parser.add_argument("--name", default="BadgeCade")
    parser.add_argument("--description", default="A theme from BadgeCade")
    parser.add_argument("--author", default="BadgeCade")
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    if args.sample:
        top, bottom, icon = sample()
    else:
        if not (args.top and args.bottom and args.icon):
            parser.error("--top, --bottom and --icon are needed (or --sample)")
        top, bottom, icon = read_png(args.top), read_png(args.bottom), read_png(args.icon)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(build(top, bottom, icon, args.name, args.description, args.author))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
