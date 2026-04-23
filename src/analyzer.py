"""Orchestrates chapter analysis: batch → concurrent DeepSeek calls → Markdown.

This module has two parts:
  1. Pure helpers (batch_chapters, format_output_markdown, read_txt_with_encoding_fallback)
     — unit-tested.
  2. Analyzer class (run on a background thread, emits messages to a queue)
     — exercised via manual UI testing.

Task 4 only contains part 1; Task 5 appends part 2.
"""

from __future__ import annotations

import datetime as _dt
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chapter_splitter import Chapter, split_chapters
from deepseek_client import DeepSeekClient, DeepSeekError


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
    for enc in ("utf-8-sig", "gbk"):
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
                            self._stop.set()
                            # Cancel pending futures synchronously so they don't
                            # sneak in after abort while the watcher is polling.
                            for f in future_to_batch:
                                f.cancel()
                        continue

                    summaries.update(result)
                    missing = [c.id for c in batch if c.id not in result]
                    done_chapters += len(result)  # count actual summaries, not batch size
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

        # 6. Write markdown (skip if aborted before any success — empty file is clutter)
        if aborted and not summaries:
            self._q.put({
                "type": "error",
                "reason": "分析中止：连续失败过多，未产出任何章节摘要",
            })
            return

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
