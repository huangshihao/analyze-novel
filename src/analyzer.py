"""Orchestrates chapter analysis: batch → concurrent DeepSeek calls → Markdown.

This module has two parts:
  1. Pure helpers (batch_chapters, format_output_markdown, read_txt_with_encoding_fallback)
     — unit-tested.
  2. Analyzer class (run on a background thread, emits messages to a queue)
     — exercised via manual UI testing.

Task 4 only contains part 1; Task 5 appends part 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from chapter_splitter import Chapter


@dataclass
class AnalyzeConfig:
    txt_path: Path
    api_key: str
    chapter_start: int  # 1-based, inclusive
    chapter_end: int    # 1-based, inclusive


def batch_chapters(chapters: list[Chapter], size: int) -> list[list[Chapter]]:
    if size <= 0:
        raise ValueError("size must be positive")
    return [chapters[i:i + size] for i in range(0, len(chapters), size)]


def read_txt_with_encoding_fallback(path: Path) -> str:
    """Try UTF-8 first, fall back to GBK (common for Windows-produced .txt files)."""
    data = path.read_bytes()
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # Last resort: replace undecodable bytes so we still get something.
    return data.decode("utf-8", errors="replace")


def format_output_markdown(
    *,
    novel_name: str,
    chapters: list[Chapter],
    summaries: dict[int, str],
    failed_ids: list[int],
    generated_at: str,
    range_start: int,
    range_end: int,
) -> str:
    """Build the final Markdown. Chapters presented in id order; failures listed at end."""
    successful = [c for c in chapters if c.id in summaries]

    lines: list[str] = []
    lines.append(f"# 《{novel_name}》章节详细摘要")
    lines.append("")
    lines.append(
        f"> 共分析 {len(successful)} 章"
        f"（第 {range_start} 章 — 第 {range_end} 章）。"
        f"DeepSeek 生成于 {generated_at}。"
    )
    lines.append("")

    for c in sorted(successful, key=lambda x: x.id):
        lines.append(f"## {c.title}")
        lines.append("")
        lines.append(summaries[c.id].strip())
        lines.append("")

    if failed_ids:
        lines.append("---")
        lines.append("")
        lines.append("## 未能生成摘要的章节")
        lines.append("")
        for cid in sorted(failed_ids):
            lines.append(f"- 第 {cid} 章")
        lines.append("")

    return "\n".join(lines)
