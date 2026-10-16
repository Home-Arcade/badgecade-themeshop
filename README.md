# BadgeCade Theme Shop

The server side of BadgeCade's revival of the Nintendo 3DS HOME Menu **Theme Shop**: it
builds theme packs the HOME Menu can download, serves the shop's listings and pages, and
lets players buy themes with BadgeCade's free in-game budget through
[shopdeck](https://github.com/Aftendo/shopdeck), a replacement eShop server.

BadgeCade is a fan project. It is not affiliated with or endorsed by Nintendo.

## What's here

| Path | What it does |
|---|---|
| `tools/theme_pack.py` | Builds a theme pack: a DLC title (`0004008C00008Fxx`) with its TMD, content 0 (pack index, icons) and one content per theme. Theme IDs are `pack variation × 1000000 + content index`. |
| `tools/add_theme.py` | Adds a theme (`.zip` or folder with `body_LZ.bin`, `info.smdh`, previews, optional `bgm.bcstm`) to the next free slot of a pack and publishes the pack. Refuses Nintendo's official themes by hash. |
| `tools/make_theme.py` | Makes a theme from two pictures (top and bottom screen), or solid colours. |
| `tools/theme_shop_data.py` | The shop's SpotPass data: each theme's details page, the "New Themes" list, the front page and its featured list (with holiday seasons). |
| `tools/theme_shop_top.py` | The front page's banner and layout. |
| `tools/theme_cia.py` | Packs a built theme pack as a CIA, for installing by hand. |
| `tools/holiday_week.py` | Holiday seasons and colours (used for festive shop banners). |
| `tools/boss3ds.py`, `sarc.py`, `yaz0.py`, `jpeg.py`, `ja_text.py` | File formats: SpotPass (BOSS) containers, SARC archives, Yaz0 compression, JPEG, Japanese text wrapping. |
| `tools/official_theme_hashes.personal.txt` | SHA-1 hashes of Nintendo's official themes, so they are refused. |
| `shopdeck/shopdeck_patches.py` | Changes applied to shopdeck when its image is built: theme purchases, tickets for theme packs, the budget wallet, tax and currencies. |
| `themes/pack.example.json` | An example pack spec. |
| `themes/badgecade-sample.zip` | BadgeCade's own sample theme, for testing. |

## How the Theme Shop works

1. **Packs:** themes live in DLC packs. A pack update keeps already downloaded themes,
   because each theme's content index never changes. Rules learned on real consoles:
   - indexes run `1..N` without gaps in a pack that is sold;
   - a ticket's rights cover indexes `0–1023`;
   - the content info archive is dense (entry N is index N).
2. **Listings:** the HOME Menu reads the shop's pages (details, New Themes, front page) from
   SpotPass data, which `theme_shop_data.py` writes for each region.
3. **Buying:** the shop window talks to the eShop servers (NUS, ECS, CAS, ninja, samurai).
   shopdeck answers, and `shopdeck_patches.py` makes it charge the player's budget, give
   each console one stable ticket per pack, and serve the pack's contents.

## Not included

These are needed to run it but aren't part of this source, because they're Nintendo's or
secret:

- the SpotPass (BOSS) AES key (`boss3ds.py` reads it from a file you supply);
- the TMD certificate chain (`tools/certs/tmd_cert_chain.bin`, from any Nintendo CDN TMD);
- shopdeck's `basetik.bin` (shipped with shopdeck);
- any of Nintendo's themes. **Never add Nintendo's paid themes.**

Players also need the HOME Menu to reach your server (a proxy or DNS that sends the
eShop and CCS hosts to you) and Luma3DS's signature patches, so the console accepts the
packs.

## License

Copyright (C) 2026 BadgeCade (neotechspurts).

This program is free software; you can redistribute it and/or modify it under the terms of
the GNU General Public License as published by the Free Software Foundation; either
**version 2 of the License, or (at your option) any later version**. See `LICENSE`.

`shopdeck/shopdeck_patches.py` modifies shopdeck by Aftendo, which is licensed under the
GNU General Public License version 2.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
