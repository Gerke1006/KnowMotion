"""Pure text layout helpers shared by generated Manim scenes."""
from __future__ import annotations

import re


def chinese_font_ranges(text: str, font: str) -> dict[str, str]:
    """Pango slice selectors preserve Latin runs in the default Roman font."""
    return {
        f"[{match.start()}:{match.end()}]": font
        for match in re.finditer(r"[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef\u2014\u2026\u2018-\u201d]+", text)
    }


def caption_pages(text: str, max_chars: int = 30) -> list[str]:
    """Keep short spoken clauses together; never discard subtitle characters."""
    text = str(text).replace("\n", " ").strip()
    if not text:
        return []
    pages: list[str] = []
    current = ""
    for clause in re.findall(r"[^，。！？；,! ?;]+[，。！？；,!?;]?|\s+|.", text):
        while len(clause) > max_chars:
            if current:
                pages.append(current)
                current = ""
            pages.append(clause[:max_chars])
            clause = clause[max_chars:]
        if len(current) + len(clause) > max_chars:
            pages.append(current)
            current = ""
        current += clause
    if current:
        pages.append(current)
    # A hard wrap must not leave a standalone punctuation mark on screen.
    for index in range(1, len(pages)):
        if len(pages[index].strip()) < 6 and len(pages[index - 1]) >= 12:
            count = min(6 - len(pages[index]), len(pages[index - 1]) // 2, max_chars - len(pages[index]))
            if count > 0:
                pages[index] = pages[index - 1][-count:] + pages[index]
                pages[index - 1] = pages[index - 1][:-count]
    return pages


def caption_index(pages: list[str], progress: float) -> int:
    total = sum(len(page) for page in pages)
    position = max(0, min(1, progress)) * total
    accumulated = 0
    for index, page in enumerate(pages):
        accumulated += len(page)
        if position < accumulated:
            return index
    return max(0, len(pages) - 1)


def body_lines(text: str, max_units: float = 26) -> list[str]:
    """Wrap CJK characters while keeping ordinary Latin words together."""
    lines = []
    for paragraph in str(text).splitlines():
        line, units = "", 0.0
        for token in re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[^A-Za-z0-9]", paragraph):
            token_units = sum(.52 if ord(char) < 128 else 1 for char in token)
            if line and units + token_units > max_units:
                lines.append(line.rstrip())
                line, units = "", 0.0
            line += token
            units += token_units
        if line.strip():
            lines.append(line.strip())
    return lines
