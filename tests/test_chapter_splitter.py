from chapter_splitter import Chapter, split_chapters


def _body(n: int) -> str:
    """Generate body text longer than the 100-char filter threshold."""
    return "这是章节正文内容。" * 20  # ~160 chars


def test_basic_split_cn_numerals():
    text = f"第一章 起因\n{_body(1)}\n第二章 经过\n{_body(2)}"
    chapters = split_chapters(text)
    assert len(chapters) == 2
    assert chapters[0].id == 1
    assert chapters[0].title == "第一章 起因"
    assert "章节正文内容" in chapters[0].content
    assert chapters[1].id == 2
    assert chapters[1].title == "第二章 经过"


def test_mixed_cn_and_arabic_numerals():
    text = (
        f"第一章 开头\n{_body(1)}\n"
        f"第 42 章 中间\n{_body(2)}\n"
        f"第一百零三章 结尾\n{_body(3)}"
    )
    chapters = split_chapters(text)
    assert len(chapters) == 3
    assert chapters[0].title == "第一章 开头"
    assert chapters[1].title == "第 42 章 中间"
    assert chapters[2].title == "第一百零三章 结尾"


def test_ids_are_sequential_not_parsed_from_title():
    # User expects chapters to be numbered 1, 2, 3 by their order of appearance,
    # not by the numeral in the title.
    text = f"第五章 A\n{_body(1)}\n第七章 B\n{_body(2)}"
    chapters = split_chapters(text)
    assert [c.id for c in chapters] == [1, 2]


def test_no_chapter_markers_returns_empty():
    text = "这是一段没有任何章节标记的长文本。" * 50
    chapters = split_chapters(text)
    assert chapters == []


def test_short_chapters_are_filtered():
    # Chapter with body < 100 chars should be dropped (title page / TOC noise).
    text = f"第一章 目录\n短\n第二章 正文\n{_body(2)}"
    chapters = split_chapters(text)
    assert len(chapters) == 1
    assert chapters[0].title == "第二章 正文"
    assert chapters[0].id == 1  # renumbered after filtering


def test_ads_are_stripped():
    body = _body(1) + "（本章未完，请点击下一页继续阅读）" + "剩余正文" * 10
    text = f"第一章 带广告\n{body}"
    chapters = split_chapters(text)
    assert "本章未完" not in chapters[0].content
    assert "剩余正文" in chapters[0].content


def test_leading_whitespace_before_marker_ok():
    # Full-width ideographic space + normal spaces before 第X章 should not break match.
    text = f"　　第一章 缩进\n{_body(1)}"
    chapters = split_chapters(text)
    assert len(chapters) == 1
    assert chapters[0].title == "第一章 缩进"


def test_crlf_line_endings():
    text = f"第一章 Windows\r\n{_body(1)}\r\n第二章 换行\r\n{_body(2)}"
    chapters = split_chapters(text)
    assert len(chapters) == 2
