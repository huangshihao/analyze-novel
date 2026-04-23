"""DeepSeek chat API wrapper. One call = one batch of chapters → summaries."""

from __future__ import annotations

import json
import time
import random

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
    """DeepSeek API wrapper. Thread-safe for concurrent summarize_batch calls:
    a single instance may be shared across ThreadPoolExecutor workers.
    One HTTP request per summarize_batch() call.
    """

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
            retry_after: float | None = None
            try:
                resp = self._client.post("/chat/completions", json=body)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_err = e
            else:
                if resp.status_code == 200:
                    return self._parse(resp.json())
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    last_err = DeepSeekError(
                        f"HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    if resp.status_code == 429:
                        ra = resp.headers.get("Retry-After")
                        if ra:
                            try:
                                retry_after = float(ra)
                            except ValueError:
                                retry_after = None
                else:
                    # 4xx other than 429: don't retry
                    raise DeepSeekError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            if attempt < _MAX_RETRIES - 1:
                base = retry_after if retry_after is not None else (
                    self._retry_base_delay * (2 ** attempt)
                )
                # Jitter in [0.5, 1.5) to decorrelate concurrent workers.
                jittered = base * (0.5 + random.random())
                time.sleep(jittered)

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
