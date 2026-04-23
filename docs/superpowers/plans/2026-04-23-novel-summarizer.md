# 小说摘要分析工具 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 做一个 Windows `.exe`，用户在 tkinter GUI 里选 .txt 小说 + 填 DeepSeek API Key + 选章节范围，跑出每章 100-200 字详细剧情摘要的 Markdown。

**Architecture:** 四层解耦：`chapter_splitter`（纯函数切章节）→ `deepseek_client`（单 batch API 调用 + 重试）→ `analyzer`（编排 + 并发 + 停止 + 写 MD）→ `ui`（tkinter）。后台线程用 `queue.Queue` 推消息给 UI，UI 用 `after(100)` 轮询；停止用 `threading.Event` 信号。GitHub Actions `windows-latest` 跑 PyInstaller 打包 exe。

**Tech Stack:** Python 3.11 · tkinter · httpx · pytest · PyInstaller · GitHub Actions

---

## 文件总览

**新增文件：**
| 路径 | 职责 |
|------|------|
| `src/chapter_splitter.py` | txt 字符串 → `list[Chapter]`，纯函数 |
| `src/deepseek_client.py` | 单次 summarize_batch 调用，带重试 |
| `src/analyzer.py` | Analyzer 类：编排 + 并发 + 停止 + 写 MD |
| `src/ui.py` | tkinter 主窗口 |
| `src/main.py` | 入口：启动 UI |
| `src/__init__.py` | 标记包 |
| `tests/test_chapter_splitter.py` | 切章节单测 |
| `tests/test_deepseek_client.py` | API 封装单测（httpx MockTransport） |
| `tests/test_analyzer.py` | 纯逻辑部分（batching / MD format / encoding） |
| `tests/__init__.py` | 空 |
| `tests/conftest.py` | 添加 `src` 到 sys.path |
| `requirements.txt` | 运行时依赖 |
| `requirements-dev.txt` | 测试 + 打包依赖 |
| `.gitignore` | Python + build artifact |
| `pyinstaller.spec` | 单文件 exe 配置 |
| `build.bat` | Windows 本机打包脚本 |
| `.github/workflows/build-windows.yml` | GitHub Actions 打包 |
| `README.md` | 用法 + 下载 exe 指南 |

---

## Task 1: 项目脚手架

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.gitignore`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 写 `requirements.txt`**

```
httpx==0.27.2
```

- [ ] **Step 2: 写 `requirements-dev.txt`**

```
-r requirements.txt
pytest==8.3.3
pyinstaller==6.11.1
```

- [ ] **Step 3: 写 `.gitignore`**

```
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.pytest_cache/
build/
dist/
*.spec.bak
.DS_Store
```

- [ ] **Step 4: 写 `src/__init__.py`**

空文件。

- [ ] **Step 5: 写 `tests/__init__.py`**

空文件。

- [ ] **Step 6: 写 `tests/conftest.py`**

```python
"""Add src/ to sys.path so tests can import without install."""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
```

- [ ] **Step 7: 建虚拟环境 + 装依赖**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Expected: 依赖安装成功，`pytest --version` 能运行。

- [ ] **Step 8: 验证 pytest 能发现空测试目录**

```bash
.venv/bin/pytest tests/ -v
```

Expected: `no tests ran in ...`（退出码 5，符合预期）。

- [ ] **Step 9: 把 `.venv` 加进 `.gitignore`（已经加过，再次确认）并 commit**

```bash
git add requirements.txt requirements-dev.txt .gitignore src/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: project scaffolding (deps, gitignore, pytest layout)"
```

---

## Task 2: 章节切分器

**Files:**
- Create: `src/chapter_splitter.py`
- Create: `tests/test_chapter_splitter.py`

- [ ] **Step 1: 写测试**

```python
# tests/test_chapter_splitter.py
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
```

- [ ] **Step 2: 跑测试看到失败**

Run: `.venv/bin/pytest tests/test_chapter_splitter.py -v`
Expected: 全部 FAIL，`ModuleNotFoundError: No module named 'chapter_splitter'`

- [ ] **Step 3: 写实现**

```python
# src/chapter_splitter.py
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


def split_chapters(text: str) -> list[Chapter]:
    cleaned = _clean(text)
    matches = list(_CHAPTER_RE.finditer(cleaned))
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
```

- [ ] **Step 4: 跑测试看到通过**

Run: `.venv/bin/pytest tests/test_chapter_splitter.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/chapter_splitter.py tests/test_chapter_splitter.py
git commit -m "feat: chapter splitter with cn/arabic numeral support"
```

---

## Task 3: DeepSeek 客户端

**Files:**
- Create: `src/deepseek_client.py`
- Create: `tests/test_deepseek_client.py`

- [ ] **Step 1: 写测试**

```python
# tests/test_deepseek_client.py
import json
import httpx
import pytest

from chapter_splitter import Chapter
from deepseek_client import DeepSeekClient, DeepSeekError


def _chapter(cid: int) -> Chapter:
    return Chapter(id=cid, title=f"第{cid}章", content="章节内容" * 50)


def _ok_response(summaries: dict[int, str]) -> httpx.Response:
    payload = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "chapters": [
                        {"chapter_id": cid, "summary": s}
                        for cid, s in summaries.items()
                    ]
                }, ensure_ascii=False),
            },
        }],
    }
    return httpx.Response(200, json=payload)


def test_summarize_batch_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "deepseek-chat"
        assert body["response_format"] == {"type": "json_object"}
        return _ok_response({1: "摘要一", 2: "摘要二"})

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport)
    result = client.summarize_batch([_chapter(1), _chapter(2)])
    assert result == {1: "摘要一", 2: "摘要二"}


def test_summarize_batch_400_no_retry():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport, _retry_base_delay=0)
    with pytest.raises(DeepSeekError):
        client.summarize_batch([_chapter(1)])
    assert call_count == 1  # no retry on 4xx


def test_summarize_batch_429_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return _ok_response({1: "成功了"})

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport, _retry_base_delay=0)
    result = client.summarize_batch([_chapter(1)])
    assert result == {1: "成功了"}
    assert calls["n"] == 3


def test_summarize_batch_429_exhausts_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport, _retry_base_delay=0)
    with pytest.raises(DeepSeekError) as exc_info:
        client.summarize_batch([_chapter(1)])
    assert "429" in str(exc_info.value) or "rate" in str(exc_info.value).lower()


def test_summarize_batch_timeout_retries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("timeout", request=request)
        return _ok_response({1: "终于"})

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport, _retry_base_delay=0)
    result = client.summarize_batch([_chapter(1)])
    assert result == {1: "终于"}
    assert calls["n"] == 2


def test_summarize_batch_invalid_json_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "not valid json {{"}}]
        })

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport, _retry_base_delay=0)
    with pytest.raises(DeepSeekError):
        client.summarize_batch([_chapter(1)])


def test_summarize_batch_missing_chapter_in_response():
    # Model returned 2 entries when we asked for 3 — result dict only contains
    # what the model returned. Caller (analyzer) is responsible for detecting
    # missing chapters.
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok_response({1: "a", 3: "c"})  # ch 2 missing

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport, _retry_base_delay=0)
    result = client.summarize_batch([_chapter(1), _chapter(2), _chapter(3)])
    assert result == {1: "a", 3: "c"}
```

- [ ] **Step 2: 跑测试看到失败**

Run: `.venv/bin/pytest tests/test_deepseek_client.py -v`
Expected: 全部 FAIL，`ModuleNotFoundError: No module named 'deepseek_client'`

- [ ] **Step 3: 写实现**

```python
# src/deepseek_client.py
"""DeepSeek chat API wrapper. One call = one batch of chapters → summaries."""

from __future__ import annotations

import json
import time

import httpx

from chapter_splitter import Chapter


_BASE_URL = "https://api.deepseek.com"
_MODEL = "deepseek-chat"
_MAX_CHAPTER_CHARS = 1500  # truncate long chapters before sending
_MAX_RETRIES = 3
_DEFAULT_TIMEOUT = 120.0

_PROMPT = """你是一个中文网络小说分析师。下面是若干章原文。请为每一章输出一条详细的剧情摘要。

要求：
1. 每章摘要 100-200 个汉字
2. 必须包含：主要事件、关键人物的具体行动、本章的结果或转折点
3. 用流畅中文叙述，不要列点，不要元评论（不要"本章讲了"这类开头）
4. 严格 JSON 输出，不要任何额外文字：

{{
  "chapters": [
    {{"chapter_id": 1, "summary": "..."}},
    {{"chapter_id": 2, "summary": "..."}}
  ]
}}

章节原文（每章独立一段）：

{chapters_block}
"""


class DeepSeekError(Exception):
    """Raised when the API call ultimately fails (after retries)."""


def _clip(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.7)
    tail = max_chars - head - 8
    return text[:head] + "\n……\n" + text[-tail:]


def _build_block(chapters: list[Chapter]) -> str:
    parts = []
    for c in chapters:
        parts.append(
            f"【第{c.id}章】标题：{c.title}\n{_clip(c.content, _MAX_CHAPTER_CHARS)}"
        )
    return "\n\n---\n\n".join(parts)


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        timeout: float = _DEFAULT_TIMEOUT,
        *,
        _transport: httpx.BaseTransport | None = None,
        _retry_base_delay: float = 1.0,
    ):
        self._client = httpx.Client(
            base_url=_BASE_URL,
            timeout=timeout,
            transport=_transport,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        self._retry_base_delay = _retry_base_delay

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "DeepSeekClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def summarize_batch(self, chapters: list[Chapter]) -> dict[int, str]:
        """Call DeepSeek once, return {chapter_id: summary}.

        Raises DeepSeekError after exhausting retries or on unrecoverable errors
        (4xx non-429, malformed JSON).
        """
        if not chapters:
            return {}

        prompt = _PROMPT.format(chapters_block=_build_block(chapters))
        body = {
            "model": _MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "top_p": 0.9,
            "stream": False,
            "response_format": {"type": "json_object"},
        }

        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._client.post("/chat/completions", json=body)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_err = e
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(self._retry_base_delay * (2 ** attempt))
                continue

            if resp.status_code == 200:
                return self._parse(resp.json())

            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last_err = DeepSeekError(
                    f"HTTP {resp.status_code}: {resp.text[:200]}"
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(self._retry_base_delay * (2 ** attempt))
                continue

            # 4xx other than 429: don't retry
            raise DeepSeekError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        raise DeepSeekError(f"exhausted retries: {last_err}")

    @staticmethod
    def _parse(payload: dict) -> dict[int, str]:
        try:
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            entries = parsed.get("chapters", [])
            result: dict[int, str] = {}
            for e in entries:
                cid = int(e.get("chapter_id", 0))
                summary = str(e.get("summary", "")).strip()
                if cid and summary:
                    result[cid] = summary
            return result
        except (KeyError, IndexError, json.JSONDecodeError, ValueError, TypeError) as e:
            raise DeepSeekError(f"bad response: {e}") from e
```

- [ ] **Step 4: 跑测试看到通过**

Run: `.venv/bin/pytest tests/test_deepseek_client.py -v`
Expected: 全部 7 个 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/deepseek_client.py tests/test_deepseek_client.py
git commit -m "feat: deepseek client with retry on 429/5xx/timeout"
```

---

## Task 4: Analyzer — 纯逻辑部分

这个 task 先写可测试的纯函数（batch 切分、Markdown 格式化、txt 读取 + 编码检测）。下个 task 再加上线程编排（手动测）。

**Files:**
- Create: `src/analyzer.py`（仅纯函数 + `AnalyzeConfig` 数据类，先不写线程部分）
- Create: `tests/test_analyzer.py`

- [ ] **Step 1: 写测试**

```python
# tests/test_analyzer.py
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
```

- [ ] **Step 2: 跑测试看到失败**

Run: `.venv/bin/pytest tests/test_analyzer.py -v`
Expected: `ModuleNotFoundError: No module named 'analyzer'`

- [ ] **Step 3: 写 analyzer.py（纯函数部分 + 数据类，先不写线程编排）**

```python
# src/analyzer.py
"""Orchestrates chapter analysis: batch → concurrent DeepSeek calls → Markdown.

This module has two parts:
  1. Pure helpers (batch_chapters, format_output_markdown, read_txt_with_encoding_fallback)
     — unit-tested.
  2. Analyzer class (run on a background thread, emits messages to a queue)
     — exercised via manual UI testing.
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
```

- [ ] **Step 4: 跑测试看到通过**

Run: `.venv/bin/pytest tests/test_analyzer.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 跑全部测试确认没回归**

Run: `.venv/bin/pytest tests/ -v`
Expected: 所有 task 1-4 的测试 PASS。

- [ ] **Step 6: Commit**

```bash
git add src/analyzer.py tests/test_analyzer.py
git commit -m "feat: analyzer pure helpers (batching, markdown, encoding fallback)"
```

---

## Task 5: Analyzer — 线程编排

把并发执行 + 停止 + 日志队列的部分加到 `analyzer.py`。这部分不单测（线程 + 真 API），通过 UI 手动验证。

**Files:**
- Modify: `src/analyzer.py`（在现有代码基础上追加）

- [ ] **Step 1: 追加 Analyzer 类 + 消息类型**

在 `src/analyzer.py` 末尾追加以下内容（`from __future__ import annotations` 已在文件顶部，不用重加；但要补加缺的 import 到文件顶部 import 区）。

文件顶部 import 区追加（放在已有 `from chapter_splitter import Chapter` 后面）：

```python
import datetime as _dt
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from chapter_splitter import split_chapters
from deepseek_client import DeepSeekClient, DeepSeekError
```

文件末尾追加：

```python
_BATCH_SIZE = 5
_MAX_WORKERS = 3
_MAX_FAILED_BATCHES = 3


class Analyzer:
    """Runs on a background thread. Emits dicts to `log_queue`.

    Message shapes consumed by the UI:
      {"type": "log", "level": "info"|"warn"|"error", "text": str}
      {"type": "progress", "done": int, "total": int}
      {"type": "done", "output_path": str, "failed_chapters": list[int],
       "reason": "completed"|"stopped"|"aborted"}
      {"type": "error", "reason": str}      # fatal, no output produced
    """

    def __init__(
        self,
        config: AnalyzeConfig,
        log_queue: "queue.Queue[dict[str, Any]]",
        stop_event: threading.Event,
    ):
        self._cfg = config
        self._q = log_queue
        self._stop = stop_event

    def run(self) -> None:
        try:
            self._run_inner()
        except Exception as e:  # noqa: BLE001 — top-level safety net
            self._q.put({"type": "error", "reason": f"未预期错误: {e}"})

    # ── internals ──────────────────────────────────────────────────────────

    def _log(self, level: str, text: str) -> None:
        self._q.put({"type": "log", "level": level, "text": text})

    def _run_inner(self) -> None:
        # 1. Read file
        try:
            raw = read_txt_with_encoding_fallback(self._cfg.txt_path)
        except OSError as e:
            self._q.put({"type": "error", "reason": f"读文件失败: {e}"})
            return

        # 2. Split chapters
        all_chapters = split_chapters(raw)
        if not all_chapters:
            self._q.put({
                "type": "error",
                "reason": "无法识别章节格式，请确认文件包含'第X章'标记",
            })
            return
        self._log("info", f"已切分 {len(all_chapters)} 章")

        # 3. Clamp range
        start = max(1, self._cfg.chapter_start)
        end = min(len(all_chapters), self._cfg.chapter_end)
        if start > end:
            self._q.put({
                "type": "error",
                "reason": f"起始章 {start} 大于结束章 {end}（总章数 {len(all_chapters)}）",
            })
            return
        if end != self._cfg.chapter_end:
            self._log("warn", f"结束章 {self._cfg.chapter_end} 超过总章数，已调整为 {end}")

        target = all_chapters[start - 1:end]  # inclusive
        total = len(target)
        self._log("info", f"准备分析第 {start}-{end} 章，共 {total} 章")

        # 4. Batch + concurrent calls
        batches = batch_chapters(target, _BATCH_SIZE)
        summaries: dict[int, str] = {}
        failed_batch_count = 0
        done_chapters = 0

        client = DeepSeekClient(api_key=self._cfg.api_key)
        aborted = False
        # Local flag so the watcher can exit cleanly on normal completion
        # (otherwise it'd block on stop_event forever and leak a daemon thread
        # per analysis run).
        analysis_done = threading.Event()
        try:
            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
                # Submit all batches upfront; stop_event will cancel pending ones.
                future_to_batch: dict[Any, list[Chapter]] = {
                    executor.submit(client.summarize_batch, b): b
                    for b in batches
                }

                # Watcher thread: cancels not-yet-started futures when stop is
                # set; wakes periodically to check analysis_done so it exits
                # cleanly on normal completion.
                def _cancel_pending() -> None:
                    while not analysis_done.is_set():
                        if self._stop.wait(timeout=0.5):
                            for f in future_to_batch:
                                f.cancel()
                            return

                threading.Thread(target=_cancel_pending, daemon=True).start()

                for fut in as_completed(future_to_batch):
                    batch = future_to_batch[fut]
                    batch_range = f"第 {batch[0].id}-{batch[-1].id} 章"

                    if fut.cancelled():
                        self._log("info", f"⏭  跳过 {batch_range}（已停止）")
                        continue

                    try:
                        result = fut.result()
                    except DeepSeekError as e:
                        failed_batch_count += 1
                        self._log("error", f"✗ {batch_range} 失败: {e}")
                        if failed_batch_count >= _MAX_FAILED_BATCHES:
                            aborted = True
                            self._stop.set()  # cancel remaining via watcher
                        continue

                    summaries.update(result)
                    missing = [c.id for c in batch if c.id not in result]
                    done_chapters += len(batch)
                    self._q.put({
                        "type": "progress",
                        "done": done_chapters,
                        "total": total,
                    })
                    if missing:
                        self._log(
                            "warn",
                            f"✓ {batch_range}（其中 {missing} 未返回摘要）",
                        )
                    else:
                        self._log("info", f"✓ {batch_range} 完成")
        finally:
            analysis_done.set()  # wake watcher thread if still polling
            client.close()

        # 5. Determine outcome
        failed_ids = [c.id for c in target if c.id not in summaries]
        if aborted:
            reason = "aborted"
        elif self._stop.is_set():
            reason = "stopped"
        else:
            reason = "completed"

        # 6. Write markdown
        novel_name = self._cfg.txt_path.stem
        generated_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        md = format_output_markdown(
            novel_name=novel_name,
            chapters=target,
            summaries=summaries,
            failed_ids=failed_ids,
            generated_at=generated_at,
            range_start=start,
            range_end=end,
        )
        output_path = self._cfg.txt_path.parent / f"{novel_name}_summaries.md"
        try:
            output_path.write_text(md, encoding="utf-8")
        except OSError as e:
            self._q.put({"type": "error", "reason": f"写输出文件失败: {e}"})
            return

        self._q.put({
            "type": "done",
            "output_path": str(output_path),
            "failed_chapters": failed_ids,
            "reason": reason,
        })
```

- [ ] **Step 2: 跑全部测试确认纯函数部分没被破坏**

Run: `.venv/bin/pytest tests/ -v`
Expected: 之前的 analyzer 纯函数测试仍 PASS（线程部分没测试，但至少 import 不爆）。

- [ ] **Step 3: 快速烟测 — import 不报错**

Run: `.venv/bin/python -c "from analyzer import Analyzer, AnalyzeConfig; print('ok')"`
（注意：需要先 `cd` 到项目根 + 设 PYTHONPATH）

```bash
PYTHONPATH=src .venv/bin/python -c "from analyzer import Analyzer, AnalyzeConfig; print('ok')"
```

Expected: 输出 `ok`。

- [ ] **Step 4: Commit**

```bash
git add src/analyzer.py
git commit -m "feat: analyzer orchestration (concurrent batches, stop via event)"
```

---

## Task 6: tkinter UI

**Files:**
- Create: `src/ui.py`
- Create: `src/main.py`

- [ ] **Step 1: 写 `src/ui.py`**

```python
# src/ui.py
"""tkinter main window. Owns UI state + background analyzer thread lifecycle."""

from __future__ import annotations

import datetime as _dt
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any

from analyzer import AnalyzeConfig, Analyzer


_POLL_MS = 100


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("小说章节摘要分析器")
        self.root.geometry("720x560")
        self.root.resizable(False, False)

        self._log_queue: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None

        self._build_widgets()
        self._poll_queue()

    # ── layout ─────────────────────────────────────────────────────────────

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}
        form = ttk.Frame(self.root, padding=(12, 12, 12, 0))
        form.pack(fill="x")

        # Row 0: file
        ttk.Label(form, text="小说文件:").grid(row=0, column=0, sticky="w", **pad)
        self.file_var = tk.StringVar()
        entry_file = ttk.Entry(form, textvariable=self.file_var, width=60, state="readonly")
        entry_file.grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(form, text="浏览...", command=self._on_browse).grid(row=0, column=2, **pad)

        # Row 1: API key
        ttk.Label(form, text="API Key:").grid(row=1, column=0, sticky="w", **pad)
        self.key_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.key_var, show="●", width=60).grid(
            row=1, column=1, columnspan=2, sticky="we", **pad
        )

        # Row 2: chapter range
        ttk.Label(form, text="章节范围:").grid(row=2, column=0, sticky="w", **pad)
        range_frame = ttk.Frame(form)
        range_frame.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        ttk.Label(range_frame, text="从").pack(side="left")
        self.start_var = tk.IntVar(value=1)
        ttk.Spinbox(range_frame, from_=1, to=9999, textvariable=self.start_var, width=8).pack(
            side="left", padx=4
        )
        ttk.Label(range_frame, text="到").pack(side="left")
        self.end_var = tk.IntVar(value=100)
        ttk.Spinbox(range_frame, from_=1, to=9999, textvariable=self.end_var, width=8).pack(
            side="left", padx=4
        )

        form.columnconfigure(1, weight=1)

        # Buttons
        btns = ttk.Frame(self.root, padding=(12, 8, 12, 8))
        btns.pack(fill="x")
        self.start_btn = ttk.Button(btns, text="开始分析", command=self._on_start)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(btns, text="停止", command=self._on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)

        # Log area
        log_frame = ttk.Frame(self.root, padding=(12, 0, 12, 4))
        log_frame.pack(fill="both", expand=True)
        ttk.Label(log_frame, text="日志：").pack(anchor="w")
        self.log_widget = scrolledtext.ScrolledText(
            log_frame, height=18, state="disabled", wrap="word"
        )
        self.log_widget.pack(fill="both", expand=True)
        self.log_widget.tag_config("info", foreground="black")
        self.log_widget.tag_config("warn", foreground="#b8860b")
        self.log_widget.tag_config("error", foreground="red")

        # Status bar
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status_var, anchor="w", padding=(12, 4)).pack(
            fill="x"
        )

    # ── handlers ───────────────────────────────────────────────────────────

    def _on_browse(self) -> None:
        path = filedialog.askopenfilename(
            title="选择小说 txt 文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if path:
            self.file_var.set(path)

    def _on_start(self) -> None:
        txt_path = self.file_var.get().strip()
        api_key = self.key_var.get().strip()
        try:
            start = int(self.start_var.get())
            end = int(self.end_var.get())
        except (ValueError, tk.TclError):
            messagebox.showerror("输入错误", "章节范围必须是整数")
            return

        if not txt_path:
            messagebox.showerror("输入错误", "请先选择小说 txt 文件")
            return
        if not Path(txt_path).is_file():
            messagebox.showerror("输入错误", f"文件不存在: {txt_path}")
            return
        if not api_key:
            messagebox.showerror("输入错误", "请填入 DeepSeek API Key")
            return
        if start < 1 or end < 1:
            messagebox.showerror("输入错误", "章节号必须 ≥ 1")
            return
        if start > end:
            messagebox.showerror("输入错误", f"起始章 {start} 不能大于结束章 {end}")
            return

        cfg = AnalyzeConfig(
            txt_path=Path(txt_path),
            api_key=api_key,
            chapter_start=start,
            chapter_end=end,
        )

        # Reset state
        self._stop_event = threading.Event()
        self._clear_log()
        ts = _dt.datetime.now().strftime("%H:%M:%S")
        self._append_log("info", f"[{ts}] 开始分析...")
        self.status_var.set("分析中...")
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal", text="停止")

        analyzer = Analyzer(cfg, self._log_queue, self._stop_event)
        self._worker = threading.Thread(target=analyzer.run, daemon=True)
        self._worker.start()

    def _on_stop(self) -> None:
        self._stop_event.set()
        self.stop_btn.config(state="disabled", text="停止中...")
        self.status_var.set("停止中（等待已提交批次完成）...")
        self._append_log("warn", "⏸  用户请求停止")

    # ── log queue polling ──────────────────────────────────────────────────

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass
        self.root.after(_POLL_MS, self._poll_queue)

    def _handle_message(self, msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype == "log":
            ts = _dt.datetime.now().strftime("%H:%M:%S")
            self._append_log(msg.get("level", "info"), f"[{ts}] {msg.get('text', '')}")
        elif mtype == "progress":
            done = msg["done"]
            total = msg["total"]
            self.status_var.set(f"分析中 ({done}/{total})")
        elif mtype == "done":
            self._on_done(msg)
        elif mtype == "error":
            self._on_error(msg.get("reason", "未知错误"))

    def _on_done(self, msg: dict[str, Any]) -> None:
        reason = msg.get("reason", "completed")
        output = msg.get("output_path", "")
        failed = msg.get("failed_chapters", []) or []

        if reason == "completed":
            title = "分析完成"
            body = f"输出已保存到:\n{output}"
            if failed:
                body += f"\n\n其中 {len(failed)} 章失败，详见输出文件末尾。"
            messagebox.showinfo(title, body)
            self.status_var.set("已完成")
        elif reason == "stopped":
            messagebox.showinfo(
                "已停止",
                f"用户请求停止，已完成章节写入:\n{output}",
            )
            self.status_var.set("已停止")
        elif reason == "aborted":
            messagebox.showerror(
                "网络或 API 异常",
                f"连续失败过多已中止。已完成章节仍写入:\n{output}",
            )
            self.status_var.set("已中止")

        self._reset_buttons()

    def _on_error(self, reason: str) -> None:
        messagebox.showerror("错误", reason)
        self._append_log("error", f"✗ {reason}")
        self.status_var.set("出错")
        self._reset_buttons()

    def _reset_buttons(self) -> None:
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled", text="停止")

    # ── log widget helpers ─────────────────────────────────────────────────

    def _append_log(self, level: str, text: str) -> None:
        self.log_widget.config(state="normal")
        self.log_widget.insert("end", text + "\n", level)
        self.log_widget.see("end")
        self.log_widget.config(state="disabled")

    def _clear_log(self) -> None:
        self.log_widget.config(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.config(state="disabled")


def launch() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
```

- [ ] **Step 2: 写 `src/main.py`**

```python
# src/main.py
"""Entry point for both `python src/main.py` and the PyInstaller-bundled exe."""

from ui import launch


if __name__ == "__main__":
    launch()
```

- [ ] **Step 3: 本机烟测（macOS 上打开 UI）**

```bash
PYTHONPATH=src .venv/bin/python src/main.py
```

Expected: 弹出 tkinter 窗口，控件齐全，点"浏览"可以弹文件选择框。因为是 macOS 开发机，UI 能打开即可；实际分析流程在 Windows 端 exe 里验证。关掉窗口。

- [ ] **Step 4: Commit**

```bash
git add src/ui.py src/main.py
git commit -m "feat: tkinter UI + main entry point"
```

---

## Task 7: PyInstaller 配置 + GitHub Actions + README

**Files:**
- Create: `pyinstaller.spec`
- Create: `build.bat`
- Create: `.github/workflows/build-windows.yml`
- Create: `README.md`

- [ ] **Step 1: 写 `pyinstaller.spec`**

```python
# pyinstaller.spec
# Build config for single-file Windows exe.
# Run: pyinstaller pyinstaller.spec

block_cipher = None


a = Analysis(
    ["src/main.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="analyze-novel",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # windowed — no console popup
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

- [ ] **Step 2: 写 `build.bat`**

```bat
@echo off
setlocal
echo Installing dependencies...
pip install -r requirements.txt -r requirements-dev.txt || goto :err
echo Building exe...
pyinstaller --clean pyinstaller.spec || goto :err
echo.
echo ========================================
echo Build OK: dist\analyze-novel.exe
echo ========================================
exit /b 0

:err
echo Build FAILED
exit /b 1
```

- [ ] **Step 3: 写 `.github/workflows/build-windows.yml`**

```yaml
name: Build Windows exe

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  build:
    runs-on: windows-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt -r requirements-dev.txt

      - name: Run tests
        run: pytest tests/ -v

      - name: Build exe
        run: pyinstaller --clean pyinstaller.spec

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: analyze-novel-windows
          path: dist/analyze-novel.exe
          if-no-files-found: error
          retention-days: 30
```

- [ ] **Step 4: 写 `README.md`**

```markdown
# analyze-novel

一个带 GUI 的 Windows 小工具，用 DeepSeek 为中文网络小说生成每章 100-200 字的详细剧情摘要。

## 使用方式

1. 去 [Actions](https://github.com/huangshihao/analyze-novel/actions) 页面下载最新的 `analyze-novel-windows` artifact，解压得到 `analyze-novel.exe`
2. 双击打开
3. 选 .txt 小说文件（文件名里用"第X章"标记章节）
4. 填入 DeepSeek API Key（https://platform.deepseek.com 申请）
5. 选章节范围（默认 1-100）
6. 点"开始分析"，等完成，同目录会生成 `<小说名>_summaries.md`

## 本地开发（macOS / Linux）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 跑测试
pytest tests/ -v

# 本机开 UI
PYTHONPATH=src python src/main.py
```

## 本地打包（Windows）

在 Windows 机器上执行：

```cmd
build.bat
```

产出在 `dist\analyze-novel.exe`。

## 许可

Private.
```

- [ ] **Step 5: Commit**

```bash
git add pyinstaller.spec build.bat .github/workflows/build-windows.yml README.md
git commit -m "build: pyinstaller spec + github actions + readme"
```

---

## Task 8: 首次推送 GitHub + 验证 CI

**Files:** 无新文件，验证步骤。

- [ ] **Step 1: 推送到 GitHub**

```bash
git push -u origin main
```

Expected: 远端 `huangshihao/analyze-novel` 有代码。

- [ ] **Step 2: 看 Actions 跑通**

去 https://github.com/huangshihao/analyze-novel/actions，等 "Build Windows exe" 工作流跑完。

Expected: 绿色勾，artifact `analyze-novel-windows` 在 run 页面可下载。

- [ ] **Step 3: 下载 exe 给用户**

从 Actions run 页面下载 `analyze-novel-windows.zip`，解压得到 `analyze-novel.exe`，交给用户在 Windows 上测试。

- [ ] **Step 4: 用户真机验证（人手测）**

用户在 Windows 上：
1. 双击 `analyze-novel.exe`，UI 能打开
2. 选一本小说 .txt，填 API Key，跑 1-3 章（省 token）
3. 跑完生成 `<小说名>_summaries.md`，摘要在 100-200 字区间
4. 再跑一次 1-10 章，中途点"停止"，确认弹"已停止"框并写了部分结果

若有问题回到对应 task 修，再推 CI 重打包。

---

## 备注

- 章节范围 input 类型是 `Spinbox` 的 `IntVar`。如果用户清空输入或输入非数字，`IntVar.get()` 会抛 `TclError` — UI 已兜住。
- `DeepSeek` API Key 只存内存里，不 log、不持久化。
- 日志时间戳用本机时间（`datetime.now()`），不用 UTC — 一般用户看本地时间更直观。
- 若后期需要图标、打开即带默认配置等，改 `pyinstaller.spec` 加 `icon=` 和 `datas=`。
