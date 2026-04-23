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
