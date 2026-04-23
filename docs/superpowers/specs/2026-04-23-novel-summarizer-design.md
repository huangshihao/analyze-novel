# 小说章节详细摘要分析工具 — 设计文档

日期：2026-04-23
仓库：https://github.com/huangshihao/analyze-novel.git

## 背景

参考项目 `/Users/horace/fanqie/ceshixiaoshuo`（TypeScript/Bun 写的 Novel Forge）有一条 6 阶段 DeepSeek 分析流水线。本项目只需要其中的 **summaries 阶段**，并且把每章摘要从"≤30 字一句话"升级到"100-200 字详细剧情总结"。

交付物是一个 **Windows `.exe`**，双击打开是 tkinter GUI，用户在 UI 里：

1. 选 `.txt` 小说文件
2. 填 DeepSeek API Key
3. 指定分析章节范围（默认 1-100）
4. 点开始/停止
5. 看日志，跑完在输入文件旁边生成 `<小说名>_summaries.md`

作者在 macOS 上开发，用 GitHub Actions 的 `windows-latest` runner 打包 `.exe`。

## 非目标

- 不做参考项目里的 characters / world / rhythm / style / hooks 五个阶段
- 不做断点续传（方案 A：停止即停，不续跑）
- 不做多小说批量分析（一次一本）
- 不做 CLI（只有 GUI）

## 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.11 | tkinter 自带，无需额外 GUI 依赖，PyInstaller 成熟 |
| GUI | tkinter | 标准库，打包体积最小，跨平台 |
| HTTP 客户端 | httpx | 支持同步 + 异步、带超时、比 requests 现代 |
| 打包 | PyInstaller | Python 打包 exe 的事实标准 |
| 构建环境 | GitHub Actions `windows-latest` | 纯正 Windows 环境，避免 Wine tkinter 坑 |

## 代码结构

```
analyze-novel/
├── src/
│   ├── main.py              # 入口，启动 UI
│   ├── ui.py                # tkinter 主窗口
│   ├── analyzer.py          # 后台分析线程 + 停止标志
│   ├── chapter_splitter.py  # txt → 章节列表
│   └── deepseek_client.py   # DeepSeek API 封装
├── tests/
│   ├── test_chapter_splitter.py
│   └── test_deepseek_client.py       # 用 httpx MockTransport
├── .github/workflows/
│   └── build-windows.yml    # PyInstaller on windows-latest
├── build.bat                # Windows 本机打包脚本（兜底）
├── requirements.txt
├── requirements-dev.txt
├── pyinstaller.spec
├── .gitignore
└── README.md
```

**模块边界**：

- `chapter_splitter`：纯函数，输入 str 输出 `list[Chapter]`，无 IO
- `deepseek_client`：只负责一次 API 调用，返回解析后的 dict 或抛异常；不知道 batch/并发
- `analyzer`：编排 batch + 并发 + 停止标志 + 写 Markdown；通过 `queue.Queue` 向上推日志
- `ui`：只管控件 + 线程启停 + 从 queue 消费日志；不知道 DeepSeek 存在

## 数据流

```
用户点"开始分析"
  ↓
ui.py 校验输入 → 启动 analyzer 后台线程 → 禁用"开始"，启用"停止"
  ↓
analyzer:
  1. chapter_splitter.split(txt)  → 全量章节
  2. 按 [start, end] 切片
  3. 按 batch_size=5 分批
  4. ThreadPoolExecutor(max_workers=3) 并发跑 batch
  5. 每个 batch: deepseek_client.summarize(chapters) → dict[chapter_id → summary]
  6. 检查 stop_event.is_set()：True 则不再提交新 batch，等已提交的跑完
  7. 汇总所有结果，排序，写 <小说名>_summaries.md
  8. 通过 queue 推送最终状态
  ↓
ui.py 消费 queue，追加日志 / 更新进度 / 完成后弹窗
```

## 章节切分

沿用参考项目的正则：

```python
CHAPTER_PATTERN = re.compile(r'^[\s　]*(第[一二三四五六七八九十百千零\d]+章[^\n]*)', re.MULTILINE)
```

先做最小清洗：换行符归一、去常见广告水印（"本章未完"、"最新网址"等）、压缩连续空行。然后按正则找所有"第X章"位置，相邻匹配之间的内容就是对应章节正文。正文少于 100 字的章节丢弃（章头页 / 目录干扰）。

返回结构：
```python
@dataclass
class Chapter:
    id: int           # 1-based，按出现顺序编号
    title: str        # "第一章 xxx"
    content: str      # 章节正文
```

**找不到任何章节的兜底**：UI 弹错 "无法识别章节格式，请确认文件包含'第X章'标记"。不做默认"全文作一章"降级（会误导用户）。

## DeepSeek 客户端

```python
class DeepSeekClient:
    def __init__(self, api_key: str, timeout: float = 120.0):
        ...

    def summarize_batch(self, chapters: list[Chapter]) -> dict[int, str]:
        """返回 {chapter_id: summary_text}，失败抛异常"""
```

- 端点：`https://api.deepseek.com/chat/completions`
- 模型：`deepseek-chat`
- `response_format: {"type": "json_object"}`
- `temperature: 0.3`
- 超时：120 秒（详细摘要响应会比较长）
- 重试：429 / 5xx 自动重试 3 次，指数退避（1s / 2s / 4s）
- 每章原文截断到 1500 字（沿用参考项目）

**Prompt 模板**（硬编码在 `deepseek_client.py`，不搞外部文件）：

```
你是一个中文网络小说分析师。下面是若干章原文。请为每一章输出一条详细的剧情摘要。

要求：
1. 每章摘要 100-200 个汉字
2. 必须包含：主要事件、关键人物的具体行动、本章的结果或转折点
3. 用流畅中文叙述，不要列点，不要元评论（不要"本章讲了"这类开头）
4. 严格 JSON 输出，不要任何额外文字：

{
  "chapters": [
    {"chapter_id": 1, "summary": "..."},
    {"chapter_id": 2, "summary": "..."}
  ]
}

章节原文：

{chaptersBlock}
```

**Batch 大小**：5 章 / batch。原因：每章输出 100-200 字，5 章总计 500-1000 字输出 + prompt，单次响应保守安全。

**并发**：3 个 batch 同时跑。DeepSeek 速率限制相对宽松，再高收益边际递减。

## 分析器（Analyzer）

```python
@dataclass
class AnalyzeConfig:
    txt_path: Path
    api_key: str
    chapter_start: int    # 1-based，闭区间
    chapter_end: int

class Analyzer:
    def __init__(self, config, log_queue: Queue, stop_event: Event):
        ...

    def run(self) -> None:
        """在后台线程里跑。异常不抛出，走 log_queue 报告。"""
```

**日志消息类型**（`log_queue` 里的 item）：

```python
LogMessage = dict  # {"level": "info"|"warn"|"error", "text": str}
ProgressMessage = dict  # {"type": "progress", "done": int, "total": int}
DoneMessage = dict  # {"type": "done", "output_path": Path, "failed_chapters": list[int]}
ErrorMessage = dict  # {"type": "error", "reason": str}
```

UI 侧用 `msg.get("type")` 分流。

**停止语义（方案 A）**：

- `stop_event` 是 `threading.Event`
- 主循环每提交新 batch 前检查 `stop_event.is_set()`
- 已提交的 batch 不中断，等它们的 future 完成
- 所有 future 归齐后，写部分结果到 Markdown（已完成的章节），日志里标"已停止，输出 N 章"
- 停止不算错，UI 照常弹完成框，文案区分"已完成"和"已停止"

## UI 布局

tkinter `Tk()` + `ttk`（更好看），固定窗口大小 720×560，禁止缩放（简化布局）。

```
┌─────────────────────────────────────────────────────┐
│  小说文件: [_______________________]  [浏览...]     │
│  API Key:   [●●●●●●●●●●●●●●●●●●●]                  │
│  章节范围:  从 [1   ]  到  [100 ]                  │
│                                                     │
│              [开始分析]       [停止]               │
│  ──────────────────────────────────────────────    │
│  日志：                                             │
│  ┌───────────────────────────────────────────────┐ │
│  │ [12:03:01] 已切分 423 章                     │ │
│  │ [12:03:02] 分析第 1-5 章...                  │ │
│  │ [12:03:08] ✓ 第 1-5 章完成                   │ │
│  │ ...                                           │ │
│  └───────────────────────────────────────────────┘ │
│  状态: 分析中 (23/100)                              │
└─────────────────────────────────────────────────────┘
```

**控件清单**：

| 控件 | 类型 | 初值 | 备注 |
|------|------|------|------|
| 文件路径 | `Entry` (readonly) + `Button` 浏览 | 空 | `filedialog.askopenfilename(filetypes=[("文本文件", "*.txt")])` |
| API Key | `Entry(show="●")` | 空 | 仅内存，不落盘 |
| 起始章 | `Spinbox(from_=1, to=9999)` | 1 | |
| 结束章 | `Spinbox(from_=1, to=9999)` | 100 | |
| 开始 | `Button` | enabled | 点后禁用 |
| 停止 | `Button` | disabled | 分析中 enabled，点后变"停止中..." |
| 日志 | `ScrolledText(state=disabled)` | 空 | 自动滚到底 |
| 状态 | `Label` | "就绪" | 底部状态栏 |

**UI 线程与后台线程通信**：
- UI 用 `after(100, self._poll_queue)` 每 100ms 从 queue 拉消息追加到 Text
- 后台线程从不直接碰 tkinter 控件（tkinter 非线程安全）

## 错误处理

| 场景 | 行为 |
|------|------|
| 未选文件 | "开始"校验，`messagebox.showerror` |
| 未填 API Key | 同上 |
| 起始章 > 结束章 | 同上 |
| 章节范围超过实际总章数 | 自动夹到 `[1, total]`，日志提示"已调整结束章为 X" |
| txt 切不出章节 | `messagebox.showerror("无法识别章节格式...")` |
| DeepSeek API 单 batch 失败（重试后仍失败） | 日志红字 "✗ 第 X-Y 章失败: 原因"，继续下一 batch |
| 累计 ≥ 3 个 batch 失败（并发场景下不要求"连续"） | 终止分析，`messagebox.showerror("网络或 API 异常")` |
| 用户点停止 | 等已提交 batch 完成 → 写部分结果 → 日志"已停止 (完成 N/M)" |
| 正常完成 | 写完整 Markdown，`messagebox.showinfo("分析完成", "输出: <path>")` |

异常不用 try/except 捕获再吞掉，交给 analyzer 顶层 `try/except` 转成 `ErrorMessage` 入队列。

## 输出格式

文件名：`<txt 文件同目录>/<小说名>_summaries.md`（`<小说名>` = txt 文件去扩展名后的 basename）

```markdown
# 《小说名》章节详细摘要

> 共分析 X 章（第 N 章 — 第 M 章）。DeepSeek 生成于 2026-04-23 14:32。

## 第 1 章 · 标题

（100-200 字摘要……）

## 第 2 章 · 标题

（100-200 字摘要……）

...

---

<!-- 若有失败 -->
## 未能生成摘要的章节

- 第 37 章
- 第 82 章
```

## 打包

### GitHub Actions（主路径）

`.github/workflows/build-windows.yml`：

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
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pyinstaller pyinstaller.spec
      - uses: actions/upload-artifact@v4
        with:
          name: analyze-novel-windows
          path: dist/analyze-novel.exe
```

`pyinstaller.spec` 关键选项：
- `onefile = True`（单文件 exe）
- `windowed = True`（不弹黑色控制台）
- `name = 'analyze-novel'`
- `icon = None`（暂不做图标，后期可加）

**交付**：每次 push 到 main，Actions 跑完后在 run 页面下载 `analyze-novel.exe` artifact。

### 本机兜底（Windows 上直接打）

`build.bat`：
```bat
@echo off
pip install -r requirements.txt -r requirements-dev.txt
pyinstaller pyinstaller.spec
echo Build done: dist\analyze-novel.exe
```

## 测试

只测纯逻辑，不测 tkinter：

- `test_chapter_splitter.py`：
  - 标准"第X章"切分
  - 混合中文数字（第一章 / 第十章 / 第一百零三章） + 阿拉伯数字（第 42 章）
  - 无章节标记 → 返回空列表
  - 过短章节（<100 字）过滤
  - 广告水印被清除
- `test_deepseek_client.py`（httpx `MockTransport`）：
  - 正常返回解析成功
  - 400 不重试，直接抛
  - 429 重试 3 次
  - 超时重试
  - 非法 JSON 响应抛异常

Analyzer 和 UI 走手工测试（装好的 exe 跑一本真小说）。

## 初始化步骤

Git 仓库已初始化并接好远端 `origin`（2026-04-23 brainstorming 期间完成），分支 `main`，首个提交为本设计文档。后续：

1. 按 writing-plans 产出的实施计划一步步写代码
2. 本机跑 `pytest` 通过
3. push 到 GitHub，Actions 自动出 `analyze-novel.exe`，从 run 页面下载

## 风险与兜底

| 风险 | 兜底 |
|------|------|
| DeepSeek JSON mode 偶尔返回不合规范 JSON | 捕获 `JSONDecodeError`，该 batch 标失败，其他继续 |
| 超长章节 1500 字截断丢失关键剧情 | 摘要会略糙但不会炸；若用户反馈，未来改成头+尾拼接（参考项目 `clip` 做法） |
| Windows 中文路径 / GBK 编码 txt | 读文件时先按 UTF-8，失败回退 GBK；日志提示编码 |
| PyInstaller 打包后 tkinter 主题异常 | `windows-latest` runner 是纯 Windows，tk 默认主题没问题；真遇到可加 `ttk.Style().theme_use('vista')` |
| API Key 明文内存 | UI 用 `show="●"`；进程退出即清；不写日志、不写文件 |
