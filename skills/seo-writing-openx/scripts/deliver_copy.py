#!/usr/bin/env python3
"""生成交付态副本：去掉「上稿用 SEO 資訊」节与文末工作区（写作前确认／内链清单／发布前自检）。

用法：python3 deliver_copy.py <文章.md> [输出路径]
不给输出路径时写到系统临时目录，打印路径。check_ayi.py 应跑这份副本，
否则上稿节与 FAQ 长答案会把段落中位拉高、把节奏档判错（2026-09-18，OX-0032 实测）。
"""
import os, re, sys, tempfile

def deliver(text: str) -> str:
    cut = len(text)
    for pat in (r"\n## 上稿用 SEO 資訊", r"\n---\n\n\*\*写作前确认\*\*", r"\n---\n\n## 发布前自检",
                r"\n## 内链清单（写完后删除本节）", r"\n## 發布前自檢"):
        m = re.search(pat, text)
        if m:
            cut = min(cut, m.start())
    return text[:cut].rstrip() + "\n"

def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__); return 2
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(tempfile.gettempdir(), os.path.basename(src).replace(".md", "-deliver.md"))
    text = open(src, encoding="utf-8").read()
    open(out, "w", encoding="utf-8").write(deliver(text))
    print(out); return 0

if __name__ == "__main__":
    sys.exit(main())
