"""Split raw novel .txt content into per-chapter records.

Pure function: input str → list[Chapter]. No IO.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Matches chapter headings at the start of a line, tolerating leading
# horizontal whitespace (spaces, tabs, ideographic space).
# Captures the full title including the numeric part and any trailing
# title text up to the line break.
_CHAPTER_RE = re.compile(
    r"^[ \t　]*(第[一二三四五六七八九十百千零\d\s]+章[^\n]*)",
    re.MULTILINE,
)

# Common ad / watermark patterns from Chinese web novels.
_AD_PATTERNS = [
    re.compile(r"（本章未完[^）]*）"),
    re.compile(r"本书由[^\n]*?整理"),
    re.compile(r"手机用户请浏览[^\n]*?阅读"),
    re.compile(r"最新网址：[^\n]*\n?"),
]

_MIN_CHAPTER_BODY = 100  # chars; shorter chunks are dropped as TOC/title noise.


@dataclass
class Chapter:
    id: int       # 1-based, sequential after filtering
    title: str    # full matched heading, e.g. "第一章 xxx"
    content: str  # body text (stripped)


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for pat in _AD_PATTERNS:
        text = pat.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_chapters(
    text: str, pattern: re.Pattern[str] | None = None
) -> list[Chapter]:
    """Split text into chapters.

    `pattern` (if given) must have exactly one capture group containing the
    full title. When None, falls back to the built-in `第X章` regex.
    """
    cleaned = _clean(text)
    regex = pattern if pattern is not None else _CHAPTER_RE
    matches = list(regex.finditer(cleaned))
    if not matches:
        return []

    raw: list[tuple[str, str]] = []  # (title, body)
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
        body = cleaned[body_start:body_end].strip()
        if len(body) >= _MIN_CHAPTER_BODY:
            raw.append((title, body))

    return [Chapter(id=i + 1, title=t, content=b) for i, (t, b) in enumerate(raw)]
