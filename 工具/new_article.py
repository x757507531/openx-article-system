#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenX 文章系统 · 立项建档

过完闸 1 之后跑这个。它机械地做掉四件事，堵住「只登记表格、不建文件」这个绕过点
——文章在 03-文章/ 下没有文件，对审核脚本就等于不存在，下一篇会漏判。

  1. 从 文章总表 取下一个可用 article_id，用掉后递增写回
  2. 用 04-模板/文章模板.md 建出 idea 文件，frontmatter 填好
  3. 在 文章总表 的主记录 + 语言版本矩阵各加一行
  4. 在 关键词登记表 的主词表 + 副词表加行

幂等性：同一个 (lang, primary) 已存在时拒绝执行并提示（避免重复建档）。
所有写操作前会打印将要做的改动；加 --dry-run 只看不写。

仅依赖 Python 3 标准库。

用法：
  python3 工具/new_article.py --lang zh-Hant --title "標題" --primary "主關鍵詞" \
      --secondary "副詞1,副詞2" --cluster "簇名" --slug "url-slug" [--intent 信息型] \
      [--anchors "錨文本1,錨文本2,錨文本3"] [--source-lang zh-Hant] [--dry-run]
"""

import argparse
import datetime
import io
import os
import re
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTICLES_DIR = os.path.join(VAULT, "03-文章")
CLUSTER_DIR = os.path.join(VAULT, "02-主题簇")
TEMPLATE = os.path.join(VAULT, "04-模板", "文章模板.md")
TOTAL_TABLE = os.path.join(VAULT, "01-索引", "文章总表.md")
KEYWORD_TABLE = os.path.join(VAULT, "01-索引", "关键词登记表.md")

LANGS = ["zh-Hant", "zh-Hans", "en", "ja", "ko", "vi", "th"]
# 站点导航栏目（A6）。与 cluster 是两套体系：簇管内容与内链，栏目管读者从哪个入口找到文章。
SITE_CATEGORIES = ("最新消息", "新手入門", "策略分析", "風險管理", "市場回顧", "工具教學")

# 站点署名作者。资格说明（author_credentials）必须填真实内容——
# 编造学经历／执业资格是伪造 E-E-A-T 信号，不许由脚本或模型代填。
DEFAULT_AUTHOR = os.environ.get("OPENX_AUTHOR", "")
# 短版资格（frontmatter 单行用）。完整 bio 见 01-索引/作者资料.md
DEFAULT_CREDENTIALS = os.environ.get("OPENX_AUTHOR_CREDENTIALS", "")

INTENTS = ["信息型", "导航型", "商业型", "交易型"]

TODAY_FIELD = "updated"


def read(path):
    return io.open(path, encoding="utf-8").read()


def write(path, text):
    io.open(path, "w", encoding="utf-8").write(text)


def die(msg):
    sys.stderr.write("✗ %s\n" % msg)
    sys.exit(2)


def norm(s):
    return re.sub(r"[\s\-_·・]+", "", str(s or "").lower())


# --------------------------------------------------------------------------

def next_article_id(total_md):
    m = re.search(r"下一个可用 ID：\*\*(OX-\d{4})\*\*", total_md)
    if not m:
        die("文章总表 里找不到「下一个可用 ID」行，无法分配 ID。")
    return m.group(1)


def bump_article_id(total_md, current):
    nxt = "OX-%04d" % (int(current.split("-")[1]) + 1)
    return total_md.replace("下一个可用 ID：**%s**" % current,
                            "下一个可用 ID：**%s**" % nxt), nxt


def existing_primaries(lang):
    """扫 03-文章/ 下同语言文章的主词，用于幂等检查。"""
    out = {}
    if not os.path.isdir(ARTICLES_DIR):
        return out
    for root, _d, files in os.walk(ARTICLES_DIR):
        for fn in files:
            if not fn.endswith(".md") or fn.startswith("_"):
                continue
            text = read(os.path.join(root, fn))
            if not text.startswith("---"):
                continue
            head = text.split("---")[1] if text.count("---") >= 2 else ""
            lg = re.search(r"^lang:\s*(\S+)", head, re.M)
            pk = re.search(r"^primary_keyword:\s*(.+)$", head, re.M)
            aid = re.search(r"^article_id:\s*(\S+)", head, re.M)
            if lg and pk and aid and lg.group(1).strip() == lang:
                out[norm(pk.group(1))] = (aid.group(1).strip(),
                                          pk.group(1).strip(), fn)
    return out


def insert_table_row(md, header_cells, new_row, drop_placeholder=True):
    """在匹配 header_cells 的 markdown 表格末尾插入一行。

    找不到表格时抛 ValueError——宁可失败也不要写到错误的位置。
    """
    lines = md.split("\n")
    hdr_idx = None
    for i, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(h in cells for h in header_cells):
            hdr_idx = i
            break
    if hdr_idx is None:
        raise ValueError("找不到表头包含 %s 的表格" % header_cells)

    # 从分隔行之后往下找表格结束位置
    i = hdr_idx + 2
    last = i
    while i < len(lines) and lines[i].strip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        # 占位行（全是 — 或以 _（示例 开头）可以直接顶掉
        placeholder = all(c in ("—", "-", "") for c in cells) or \
            cells[0].startswith("_（示例")
        if drop_placeholder and placeholder:
            lines[i] = new_row
            return "\n".join(lines)
        last = i
        i += 1
    lines.insert(last + 1, new_row)
    return "\n".join(lines)


def build_frontmatter(args, aid, today):
    sec = [s.strip() for s in (args.secondary or "").split(",") if s.strip()]
    anchors = [s.strip() for s in (args.anchors or "").split(",") if s.strip()]
    if not anchors:
        anchors = [args.title, "%s（完整解析）" % args.primary]

    def block(key, items):
        if not items:
            return "%s: []" % key
        return "%s:\n%s" % (key, "\n".join("  - %s" % x for x in items))

    return "\n".join([
        "---",
        "article_id: %s" % aid,
        "title: %s" % args.title,
        "lang: %s" % args.lang,
        "source_lang: %s" % (args.source_lang or args.lang),
        "status: idea",
        "cluster: %s" % args.cluster,
        "category: %s" % (args.category or ""),
        "primary_keyword: %s" % args.primary,
        block("secondary_keywords", sec),
        "serp_intent: %s" % args.intent,
        "slug: %s" % args.slug,
        "url:",
        "publish_date:",
        "updated: %s" % today,
        "pipeline_stage: M3",
        "outbound_links: []",
        "inbound_links: []",
        block("anchor_offers", anchors),
        "author: %s" % (args.author or ""),
        "author_credentials: %s" % (args.author_credentials or ""),
        "author_url:",
        "written_by: human-writing-AYI",
        "---",
        "",
    ])


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="OpenX 立项建档（闸 1 通过后执行）")
    ap.add_argument("--lang", required=True, choices=LANGS)
    ap.add_argument("--title", required=True)
    ap.add_argument("--primary", required=True)
    ap.add_argument("--secondary", default="")
    ap.add_argument("--cluster", required=True,
                    help="主题簇（内容组织单位），须在 02-主题簇/ 下存在")
    ap.add_argument("--category", default="", choices=[""] + list(SITE_CATEGORIES),
                    help="站点导航栏目，6 选 1。与 cluster 是两套体系")
    ap.add_argument("--author", default=DEFAULT_AUTHOR,
                    help="署名作者（官方标 P0）。默认 %(default)s")
    ap.add_argument("--author-credentials", dest="author_credentials",
                    default=DEFAULT_CREDENTIALS,
                    help="作者资格：学经历／执业资格／擅长领域。默认 %(default)s")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--intent", default="信息型", choices=INTENTS)
    ap.add_argument("--anchors", default="")
    ap.add_argument("--source-lang", default="")
    ap.add_argument("--date", default="", help="建档日期 YYYY-MM-DD，默认取系统当天")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(TEMPLATE):
        die("找不到文章模板：%s" % TEMPLATE)

    today = args.date.strip() or datetime.date.today().isoformat()

    # --- 前置检查 ---
    cluster_file = os.path.join(CLUSTER_DIR, args.cluster + ".md")
    if not os.path.exists(cluster_file):
        die("主题簇「%s」不存在（应有 %s）。\n"
            "  先用 04-模板/主题簇模板.md 建簇——没有 pillar 的簇不许开子文。"
            % (args.cluster, os.path.relpath(cluster_file, VAULT)))

    prims = existing_primaries(args.lang)
    if norm(args.primary) in prims:
        aid, kw, fn = prims[norm(args.primary)]
        die("L1 冲突：主词「%s」已被 %s 占用（%s）。\n"
            "  同一语言内一个主词只能有一篇文章。按 SOP-1 处置："
            "更新旧文 / 合并 / 改词 / 撤题。" % (kw, aid, fn))

    total_md = read(TOTAL_TABLE)
    aid = next_article_id(total_md)

    out_dir = os.path.join(ARTICLES_DIR, args.lang)
    out_path = os.path.join(out_dir, "%s-%s.md" % (aid, args.slug))
    if os.path.exists(out_path):
        die("文件已存在：%s" % os.path.relpath(out_path, VAULT))

    # --- 构造内容 ---
    body = read(TEMPLATE)
    body = body.split("---", 2)[2].lstrip("\n") if body.count("---") >= 2 else body
    body = body.replace("# H1 标题", "# %s" % args.title, 1)
    # 模板在 04-模板/（一层深），文章在 03-文章/<lang>/（两层深），相对链接要多退一级
    body = body.replace("](../0", "](../../0")
    article_text = build_frontmatter(args, aid, today) + body

    total_md, nxt = bump_article_id(total_md, aid)
    try:
        total_md = insert_table_row(
            total_md, ["article_id", "源语言标题", "整体状态"],
            "| %s | %s | %s | %s | %s | idea | %s |"
            % (aid, args.title, args.source_lang or args.lang, args.cluster,
               args.primary, today))
        matrix = ["| %s |" % aid] + \
                 [" idea |" if lg == args.lang else " — |" for lg in LANGS]
        total_md = insert_table_row(total_md, ["article_id"] + LANGS,
                                    "".join(matrix))
    except ValueError as e:
        die("写 文章总表 失败：%s" % e)

    kw_md = read(KEYWORD_TABLE)
    try:
        kw_md = insert_table_row(
            kw_md, ["主关键词", "归属文章", "搜索意图"],
            "| %s | %s | %s | idea | %s | %s | %s |"
            % (args.primary, args.lang, aid, args.cluster, args.intent, today))
        for s in [x.strip() for x in args.secondary.split(",") if x.strip()]:
            kw_md = insert_table_row(
                kw_md, ["副关键词", "出现于文章", "是否为他文主词"],
                "| %s | %s | %s | 否 | — |" % (s, args.lang, aid))
    except ValueError as e:
        die("写 关键词登记表 失败：%s" % e)

    # --- 报告 ---
    print("将执行以下改动：")
    print("  1. 新建  %s" % os.path.relpath(out_path, VAULT))
    print("           article_id=%s  status=idea  pipeline_stage=M3" % aid)
    print("  2. 更新  01-索引/文章总表.md（主记录 + 语言矩阵，下一个可用 ID → %s）" % nxt)
    print("  3. 更新  01-索引/关键词登记表.md（主词 1 行 + 副词 %d 行）"
          % len([x for x in args.secondary.split(",") if x.strip()]))

    if args.dry_run:
        print("\n--dry-run：未写入任何文件。")
        return 0

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    write(out_path, article_text)
    write(TOTAL_TABLE, total_md)
    write(KEYWORD_TABLE, kw_md)

    print("\n✓ 完成。article_id = %s" % aid)
    print("  文件：%s" % os.path.relpath(out_path, VAULT))
    print("\n下一步（M3）：SERP 分析与大纲。大纲定稿后立刻走 M4 内链设计，不要直接写正文。")
    print("  锚文本池是自动生成的占位值，写完正文后回 01-索引/术语与锚文本表.md 补成 ≥3 条。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
