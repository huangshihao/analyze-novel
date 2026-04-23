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
        # Window may have been closed while a run is still draining; skip if so.
        if not self.root.winfo_exists():
            return
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
