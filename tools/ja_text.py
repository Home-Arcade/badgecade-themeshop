# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
"""Japanese text by display width (a full-width character counts twice): line
wrapping for letters and Theme Shop pages."""

from __future__ import annotations

JA_LINE = 34  # half-width units per line on the letter screen (Nintendo's run to 17 full-width)
_JA_NO_START = "!?！？」』）…、。ー～"


def _ja_width(ch: str) -> int:
    code = ord(ch)
    return 1 if code < 0x1100 or 0xFF61 <= code <= 0xFF9F else 2


def wrap_ja(line: str, width: int = JA_LINE) -> str:
    """Wrap a Japanese line by display width: at a space when there is one
    (English theme names), never starting a line with closing punctuation."""
    out, current = [], ""
    for ch in line:
        if current and sum(map(_ja_width, current + ch)) > width and ch not in _JA_NO_START:
            cut = current.rfind(" ")
            if cut > 0:
                out.append(current[:cut])
                current = current[cut + 1:]
            else:
                out.append(current)
                current = ""
        current += ch
    out.append(current)
    return "\n".join(out)
