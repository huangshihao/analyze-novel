from pathlib import Path

from chapter_splitter import Chapter
from analyzer import (
    AnalyzeConfig,
    batch_chapters,
    format_output_markdown,
    read_txt_with_encoding_fallback,
)


def _ch(cid: int, title: str | None = None) -> Chapter:
    return Chapter(id=cid, title=title or f"第{cid}章 标题", content="x" * 300)


def test_batch_chapters_even_division():
    chs = [_ch(i) for i in range(1, 11)]  # 10 chapters
    batches = batch_chapters(chs, size=5)
    assert len(batches) == 2
    assert [c.id for c in batches[0]] == [1, 2, 3, 4, 5]
    assert [c.id for c in batches[1]] == [6, 7, 8, 9, 10]


def test_batch_chapters_remainder():
    chs = [_ch(i) for i in range(1, 8)]  # 7
    batches = batch_chapters(chs, size=5)
    assert len(batches) == 2
    assert len(batches[0]) == 5
    assert len(batches[1]) == 2


def test_batch_chapters_empty():
    assert batch_chapters([], size=5) == []


def test_format_output_markdown_normal():
    chapters = [_ch(1, "第一章 开端"), _ch(2, "第二章 发展")]
    summaries = {1: "主角登场，遇到反派。", 2: "主角奋起反抗。"}
    md = format_output_markdown(
        novel_name="测试小说",
        chapters=chapters,
        summaries=summaries,
        failed_ids=[],
        generated_at="2026-04-23 14:32",
        range_start=1,
        range_end=2,
    )
    assert "# 《测试小说》章节详细摘要" in md
    assert "共分析 2 章" in md
    assert "第 1 章 — 第 2 章" in md
    assert "## 第一章 开端" in md
    assert "主角登场，遇到反派。" in md
    assert "## 第二章 发展" in md
    assert "未能生成摘要的章节" not in md


def test_format_output_markdown_with_failures():
    chapters = [_ch(1), _ch(2), _ch(3)]
    summaries = {1: "成功一", 3: "成功三"}
    md = format_output_markdown(
        novel_name="书",
        chapters=chapters,
        summaries=summaries,
        failed_ids=[2],
        generated_at="2026-04-23 14:32",
        range_start=1,
        range_end=3,
    )
    assert "## 未能生成摘要的章节" in md
    assert "- 第 2 章" in md
    # Successful chapters still appear in order, failures skipped in body.
    s1 = md.index("## 第1章")
    s3 = md.index("## 第3章")
    assert s1 < s3
    assert md.count("第 2 章") >= 1  # appears in failure list


def test_format_output_markdown_preserves_chapter_order():
    chapters = [_ch(i) for i in range(1, 6)]
    # Summaries arrive out of order (concurrent batches)
    summaries = {3: "三", 1: "一", 5: "五", 2: "二", 4: "四"}
    md = format_output_markdown(
        novel_name="x",
        chapters=chapters,
        summaries=summaries,
        failed_ids=[],
        generated_at="t",
        range_start=1,
        range_end=5,
    )
    # Summaries should appear in chapter order
    positions = [md.index(f"## 第{i}章") for i in range(1, 6)]
    assert positions == sorted(positions)


def test_read_txt_utf8(tmp_path: Path):
    p = tmp_path / "novel.txt"
    p.write_text("第一章 正文内容", encoding="utf-8")
    assert read_txt_with_encoding_fallback(p) == "第一章 正文内容"


def test_read_txt_gbk_fallback(tmp_path: Path):
    p = tmp_path / "novel.txt"
    p.write_bytes("第一章 中文".encode("gbk"))
    assert read_txt_with_encoding_fallback(p) == "第一章 中文"


def test_analyze_config_defaults_and_fields():
    cfg = AnalyzeConfig(
        txt_path=Path("/tmp/x.txt"),
        api_key="k",
        chapter_start=1,
        chapter_end=100,
    )
    assert cfg.chapter_start == 1
    assert cfg.chapter_end == 100
