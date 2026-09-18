#!/usr/bin/env python3
"""闸 1（信息增益）与闸 2（大纲反套路 + 关键词自蚕食）。

前一版 skill 的失败模式是把红线写成 prose 让模型自觉执行，结果不执行。
这个脚本把两道闸做成可以失败的命令：过不了就 exit 1，不许进下一阶段。

用法：
    python3 gate.py gain    <主题目录>     # 闸 1，读 gain.md
    python3 gate.py gain    <主题目录> --min-items 1   # 放宽到至少 1 条（OpenX 口径）
    python3 gate.py outline <主题目录>     # 闸 2，读 outline.md
    python3 gate.py outline <主题目录> --min-h2 0      # 关掉 H2 数量门槛（OpenX 口径）
    python3 gate.py outline <主题目录> --skip-cannibal   # 显式跳过自蚕食检查
"""

from __future__ import annotations

import os
import re
import sys

URL_TABLE = os.path.expanduser(
    "~/Documents/1000X 文章上架/SEO 文章優化/_全站29篇_7語言URL對照表.md"
)

# 纯功能标题：没有判断、没有发现，填空题式的 H2
GENERIC_H2 = (
    "是什麼", "是什么", "怎麼運作", "怎么运作", "如何運作", "運作原理",
    "優缺點", "优缺点", "優點與缺點", "常見誤解", "常见误解",
    "該怎麼判斷", "该怎么判断", "怎麼選", "怎么选", "注意事項", "注意事项",
    "總結", "总结", "未來展望", "未来展望", "發展前景",
)
FAQ_TITLES = ("常見問題", "常见问题", "FAQ")

# 自证型来源的标记。差异化内容有三类，出处形态不同：
#   ① 一手源里有但没人写 → 有外部 URL
#   ② 作者自己实测／踩坑得到 → 没有外链，出处是自己的日志、截图、交易记录
#   ③ 作者的判断 → 支撑事实有出处，判断本身是原创
# 只认 http URL 会把第 ② 类挤掉——那恰恰是别人最抄不走的一类。
SELF_EVIDENCE = (
    "实测", "實測", "亲测", "親測", "日志", "日誌", "截图", "截圖",
    "存档", "存檔", "记录", "紀錄", "自己跑", "自己接", "本机", "本機", "对账", "對帳",
)
# 但光写「实测」不够——那两个字谁都能写。必须同时有日期或具体次数，
# 否则这道闸又变成一句空话。
SELF_EVIDENCE_ANCHOR = r"\d{4}\s*[-/年]\s*\d{1,2}|\d+\s*(?:次|筆|笔|篇|條|条|天|小時|小时)"


def han(s: str) -> int:
    return len(re.findall(r"[一-鿿]", s))


def read(path: str) -> str | None:
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return None


def gate_gain(topic_dir: str, min_items: int = 3) -> int:
    """闸 1：信息增益，每条要有来源 URL。

    条数默认 3（1000X 口径）。OpenX 侧 2026-09-03 起改为至少 1 条 + 价值条件：
    只数条数会逼人硬凑没价值的内容——「说不出读者缺了这条会怎样」才是真门槛。
    价值条件不在本脚本判定范围（判不了），由 M3 的人／agent 判，见 openx 的 M3 契约。
    """
    path = os.path.join(topic_dir, "gain.md")
    text = read(path)
    if text is None:
        print(f"闸 1 不通过：找不到 {path}")
        print(f"先在这个文件里列出至少 {min_items} 条「这篇能提供而 SERP 前 10 都没有的东西」，"
              "每条写明出处——外部 URL，或自己的实测记录（要带日期／次数）。")
        return 1

    # 编号条目或 markdown 列表项
    items = [
        l.strip() for l in text.splitlines()
        if re.match(r"^\s*(\d+[.、)]|[-*])\s*\S", l) and han(l) >= 8
    ]

    def trace(it: str) -> str:
        """返回这条的出处形态：URL / 自证 / 空字符串（没有可追溯出处）。"""
        if re.search(r"https?://\S+", it):
            return "URL"
        if any(m in it for m in SELF_EVIDENCE) and re.search(SELF_EVIDENCE_ANCHOR, it):
            return "自证"
        return ""

    traced = [i for i in items if trace(i)]

    print(f"闸 1 信息增益：条目 {len(items)} 条，其中可追溯出处的 {len(traced)} 条")
    for i, it in enumerate(items, 1):
        kind = trace(it)
        mark = f"✓ {kind}" if kind else "✗ 无可追溯出处"
        print(f"  {i}. {mark}  {it[:60]}")

    if len(items) < min_items:
        print()
        print(f"闸 1 不通过：只有 {len(items)} 条，需要 {min_items} 条。")
        print("三个选择，不许凑数硬写：")
        print("  1. 回 S1 补研究（一手源优先：官方文档、GitHub、公告原文），再重新计数。")
        print("  2. 缩题——换一个更窄、确实有东西可说的角度，H1 一起改。")
        print("  3. 明确告诉主人这篇现在不建议写。")
        return 1
    if len(traced) < len(items):
        print()
        print(f"闸 1 不通过：{len(items) - len(traced)} 条没有可追溯出处。")
        print("两种形态任选：")
        print("  · 外部一手源 —— 官方文档 / GitHub / 公告原文的 URL")
        print("  · 自己的记录 —— 写明实测／日志／截图／对账，**并带上日期或次数**")
        print("    （「我实测过」四个字不算，那谁都能写。要写成「实测 47 次，2026-08-20 日志」）")
        print("差异化不等于凭空——它在于组合、翻译、验证、判断，不在于造事实。")
        print("「据研究表明」「业内普遍认为」两种都不算。")
        return 1

    print()
    print(f"闸 1 通过。写完正文后回头核对：这 {len(items)} 条是否每条都能在成稿里找到对应段落，")
    print("且来路写进了正文（seo-adapt.md 第 3 条）。找不到就是这道闸白列了。")
    return 0


def gate_outline(topic_dir: str, skip_cannibal: bool = False, min_h2: int = 4) -> int:
    """闸 2：H2 不是通用模板 + 主关键词不撞已上线文章。

    `min_h2` 默认 4（1000X 口径）。传 0 关掉数量门槛——Google 从未提供
    「一定几个 H2」的固定配方，OpenX 侧 2026-09-03 起改按「一个 H2 对应一个任务／
    决策点／比较轴／高价值子问题」判断，数量交给主题复杂度决定。
    """
    path = os.path.join(topic_dir, "outline.md")
    text = read(path)
    if text is None:
        print(f"闸 2 不通过：找不到 {path}")
        print("先把 H1 / H2 / H3 大纲写进这个文件。")
        return 1

    h1 = [l.strip() for l in text.splitlines() if re.match(r"^\s*#\s|^H1", l)]
    h2 = [
        re.sub(r"^\s*(##\s|H2\s*-?\s*\d*\s*[：:]|🟧\s*)", "", l).strip()
        for l in text.splitlines()
        if re.match(r"^\s*##\s|^\s*H2\s*-?\s*\d*\s*[：:]|^\s*🟧", l)
    ]
    h3 = [l for l in text.splitlines() if re.match(r"^\s*###\s|^\s*H3\s*-?\s*\d*\s*[：:]", l)]

    print(f"闸 2 大纲：H2 {len(h2)} 个，H3 {len(h3)} 个")

    fail = False

    # a) 功能标题数量
    # 只有「几乎只剩功能词 + 关键词」才算纯功能标题。
    # SEO 需要 H2 带主关键词，「X 是什麼，它撿了一個空置三十年的狀態碼」是好标题：
    # 功能词后面还挂着一个具体发现，读者扫一眼就知道有东西。
    generic = []
    for t in h2:
        if any(f in t for f in FAQ_TITLES):
            continue
        hit = next((g for g in GENERIC_H2 if g in t), None)
        if not hit:
            continue
        rest = han(re.sub(r"[^一-鿿]", "", t.replace(hit, "")))
        if rest < 8:          # 去掉功能词后剩不到 8 个中文字 = 填空题式标题
            generic.append(t)
    if generic:
        print(f"\n  纯功能标题 {len(generic)} 个：")
        for t in generic:
            print(f"    ✗ {t}")
    if len(generic) > 2:
        print(f"  → 不通过：功能标题 {len(generic)} 个，超过 2 个。")
        print("    每个 H2 该自带一个判断或一个具体发现，不是填空题。见 references/anti-template.md。")
        fail = True

    # b) H2 / H3 数量（站点要求）
    if not min_h2:
        print(f"\n  → H2 数量门槛已按 --min-h2 0 关闭（现有 {len(h2)} 个）。")
        print("    改按「一个 H2 对应一个任务／决策点／比较轴／高价值子问题」自行判断。")
    elif len(h2) < min_h2:
        print(f"\n  → 不通过：H2 只有 {len(h2)} 个，要求 ≥{min_h2}。")
        fail = True
    if h2 and len(h3) < len(h2) * 2:
        print(f"\n  → 提示：H3 共 {len(h3)} 个，标配是每个 H2 下 2~3 个（当前 H2 {len(h2)} 个）。")

    # c) 关键词自蚕食
    table = read(URL_TABLE)
    if table is None and not skip_cannibal:
        # 静默跳过就是「规则存在但不执行」，那正是前一版的病。宁可硬失败。
        print(f"\n  → 不通过：读不到关键词对照表，自蚕食检查无法执行。")
        print(f"    路径：{URL_TABLE}")
        print("    确认路径，或者明知没有冲突风险时显式加 --skip-cannibal 跳过。")
        fail = True
    elif table is None:
        print(f"\n  → 自蚕食检查已按 --skip-cannibal 显式跳过。")
    elif h1:
        title = h1[0]
        # 取 H1 里的中文词块做粗比对
        chunks = [c for c in re.split(r"[^一-鿿]+", title) if len(c) >= 3]
        hits = []
        for line in table.splitlines():
            for c in chunks:
                if c in line and han(line) >= 6:
                    hits.append((c, line.strip()[:70]))
                    break
        if hits:
            print(f"\n  关键词与已上线文章重合 {len(hits)} 处：")
            for c, line in hits[:5]:
                print(f"    ⚠ 「{c}」 → {line}")
            print("  → 确认这篇是填主文真空，不是自相蚕食。是支撑文就砍掉主文已覆盖的 H2。")

    if fail:
        return 1
    print("\n闸 2 通过。")
    return 0


def main() -> int:
    args = sys.argv[1:]
    min_items = 3
    if "--min-items" in args:
        i = args.index("--min-items")
        try:
            min_items = int(args[i + 1])
            del args[i:i + 2]
        except (IndexError, ValueError):
            print("--min-items 后面要跟一个整数")
            return 2
    skip_cannibal = False
    min_h2 = 4
    if "--min-h2" in args:
        i = args.index("--min-h2")
        try:
            min_h2 = int(args[i + 1])
            del args[i:i + 2]
        except (IndexError, ValueError):
            print("--min-h2 后面要跟一个整数（0 = 关闭数量门槛）")
            return 2
    if "--skip-cannibal" in args:
        skip_cannibal = True
        args.remove("--skip-cannibal")
    if len(args) != 2 or args[0] not in ("gain", "outline"):
        print(__doc__)
        return 2
    which, topic_dir = args[0], args[1]
    if not os.path.isdir(topic_dir):
        print(f"目录不存在：{topic_dir}")
        return 2
    if which == "gain":
        return gate_gain(topic_dir, min_items)
    return gate_outline(topic_dir, skip_cannibal, min_h2)


if __name__ == "__main__":
    sys.exit(main())
