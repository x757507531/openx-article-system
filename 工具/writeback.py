#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenX 文章系统 · 闸 3 回写（M9）

发布或完稿后跑这个。它做掉全部**结构性**回写，也就是「照着 ID 就能机械算出结果」的那部分：

  1. 文章 frontmatter：status / url / publish_date / updated / pipeline_stage / outbound_links
     / category（站点栏目）/ author_url（作者页，官网上线后回填）
  2. 对端文章的 inbound_links —— 保证 outbound/inbound 对称（scan 第 4 项查这个）
  3. 01-索引/文章总表.md：主记录状态、语言版本矩阵、已发布 URL 登记
  4. 01-索引/关键词登记表.md：主词表状态列
  5. 01-索引/术语与锚文本表.md：本文锚文本池（给了 --anchors 才动）

它**不做**需要语义判断的那部分，并且会在最后逐条列出来，不静默跳过：

  · 旧文正文里真的插进那条 wikilink（要把锚文本嵌进句子，只有人/写作 skill 能做）
  · 内链矩阵的「已落实链接」明细行（插入位置与锚文本只存在于正文里）
  · 待补链接队列的勾销（得先确认旧文真的改了）

设计约束（照 module-contracts.md M9 的契约）：
  · 幂等 —— 重复跑结果一致。已经是目标值的项直接跳过并说明。
  · 只改目标行 —— 表格操作按表头定位列，不靠硬编码列号；找不到表就报错退出，绝不猜。
  · 改动前打印 diff。加 --dry-run 只看不写。

仅依赖 Python 3 标准库。

用法：
  python3 工具/writeback.py --article OX-0001 --lang zh-Hant \
      --status published --url "https://openx.com/x402" --publish-date 2026-08-08 \
      --outbound "OX-0002" --stage done [--anchors "锚1,锚2,锚3"] [--dry-run]
"""

import argparse
import datetime
import difflib
import io
import os
import re
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTICLES_DIR = os.path.join(VAULT, "03-文章")
TOTAL_TABLE = os.path.join(VAULT, "01-索引", "文章总表.md")
KEYWORD_TABLE = os.path.join(VAULT, "01-索引", "关键词登记表.md")
ANCHOR_TABLE = os.path.join(VAULT, "01-索引", "术语与锚文本表.md")

LANGS = ["zh-Hant", "zh-Hans", "en", "ja", "ko", "vi", "th"]
STATUSES = ["idea", "drafting", "review", "ready", "translated", "published"]
STAGES = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "done"]


def read(p):
    return io.open(p, encoding="utf-8").read()


def die(msg):
    sys.stderr.write("✗ %s\n" % msg)
    sys.exit(2)


# ---------------------------------------------------------------- frontmatter

def split_fm(text):
    """返回 (frontmatter 行列表, 正文)。不是合法 frontmatter 就抛。"""
    if not text.startswith("---"):
        raise ValueError("文件开头不是 frontmatter")
    lines = text.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError("frontmatter 没有结束的 ---")
    return lines[1:end], "\n".join(lines[end + 1:])


def fm_get(fm_lines, key):
    """读标量值；块列表返回 None（调用方自己处理）。"""
    for ln in fm_lines:
        m = re.match(r"^%s\s*:\s*(.*)$" % re.escape(key), ln)
        if m:
            return m.group(1).strip()
    return None


def fm_list(fm_lines, key):
    """读列表值，兼容 flow（[a, b]）与 block（- a）两种写法。"""
    for i, ln in enumerate(fm_lines):
        m = re.match(r"^%s\s*:\s*(.*)$" % re.escape(key), ln)
        if not m:
            continue
        raw = m.group(1).strip()
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
        if raw:
            return [raw.strip("'\"")]
        out = []
        for ln2 in fm_lines[i + 1:]:
            if re.match(r"^\s*-\s+", ln2):
                out.append(re.sub(r"^\s*-\s+", "", ln2).strip().strip("'\""))
            elif ln2.strip() == "":
                continue
            else:
                break
        return out
    return None


def fm_set_scalar(fm_lines, key, value):
    """设标量。key 不存在则在末尾补上。返回 (新行列表, 是否改动)。"""
    want = "%s: %s" % (key, value) if value != "" else "%s:" % key
    for i, ln in enumerate(fm_lines):
        if re.match(r"^%s\s*:" % re.escape(key), ln):
            if ln.rstrip() == want:
                return fm_lines, False
            out = list(fm_lines)
            out[i] = want
            return out, True
    return fm_lines + [want], True


def fm_set_list(fm_lines, key, items):
    """设列表，统一写成 flow style（parse_frontmatter 两种都认，flow 更紧凑）。
    原本是块列表时，把那些 `- xxx` 行一并删掉。"""
    want = "%s: [%s]" % (key, ", ".join(items)) if items else "%s: []" % key
    for i, ln in enumerate(fm_lines):
        if not re.match(r"^%s\s*:" % re.escape(key), ln):
            continue
        j = i + 1
        while j < len(fm_lines) and re.match(r"^\s*-\s+", fm_lines[j]):
            j += 1
        if fm_lines[i].rstrip() == want and j == i + 1:
            return fm_lines, False
        return fm_lines[:i] + [want] + fm_lines[j:], True
    return fm_lines + [want], True


# ---------------------------------------------------------------- 文章定位

def scan_articles():
    """返回 [(article_id, lang, path, fm_lines, body)]。"""
    out = []
    for root, _d, files in os.walk(ARTICLES_DIR):
        for fn in sorted(files):
            if not fn.endswith(".md") or fn.startswith("_"):
                continue
            p = os.path.join(root, fn)
            try:
                fm, body = split_fm(read(p))
            except ValueError:
                continue
            aid, lang = fm_get(fm, "article_id"), fm_get(fm, "lang")
            if aid and lang:
                out.append((aid, lang, p, fm, body))
    return out


def locate(arts, aid, lang):
    hits = [a for a in arts if a[0] == aid and (lang is None or a[1] == lang)]
    if not hits:
        have = sorted({a[1] for a in arts if a[0] == aid})
        if have:
            die("%s 没有 %s 版本。已有语言：%s" % (aid, lang, "、".join(have)))
        die("库里找不到 %s。先确认 article_id 写对了，或用 new_article.py 立项。" % aid)
    if len(hits) > 1:
        die("%s 有多个语言版本（%s），请用 --lang 指定要回写哪一个。"
            % (aid, "、".join(sorted(h[1] for h in hits))))
    return hits[0]


# ---------------------------------------------------------------- 表格操作

def find_table(lines, must_have):
    """按表头单元格定位表格，返回 (表头行号, 列名列表, 数据起始行号, 数据结束行号)。"""
    for i, ln in enumerate(lines):
        if not ln.strip().startswith("|"):
            continue
        cols = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(h in cols for h in must_have):
            j = i + 2
            start = j
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            return i, cols, start, j
    return None


def row_cells(ln):
    return [c.strip() for c in ln.strip().strip("|").split("|")]


def set_cell(lines, table, match_col, match_val, set_col, new_val):
    """在表里找 match_col == match_val 的行，把 set_col 设成 new_val。
    返回 (新 lines, 状态)：状态 ∈ changed / same / no-row / no-col。"""
    hdr_i, cols, start, end = table
    if match_col not in cols or set_col not in cols:
        return lines, "no-col"
    mi, si = cols.index(match_col), cols.index(set_col)
    for k in range(start, end):
        cells = row_cells(lines[k])
        if len(cells) <= max(mi, si):
            continue
        if cells[mi].strip("*_ ") != match_val:
            continue
        if cells[si] == new_val:
            return lines, "same"
        cells[si] = new_val
        out = list(lines)
        out[k] = "| " + " | ".join(cells) + " |"
        return out, "changed"
    return lines, "no-row"


def upsert_row(lines, table, key_cols, key_vals, values):
    """按 key_cols 全部相等找行：找到就更新，没找到就在表末追加。
    values 是 {列名: 值}。返回 (新 lines, changed/same)。"""
    hdr_i, cols, start, end = table
    for c in list(key_cols) + list(values):
        if c not in cols:
            return lines, "no-col"
    kis = [cols.index(c) for c in key_cols]

    def build(cells):
        for c, v in values.items():
            cells[cols.index(c)] = v
        return "| " + " | ".join(cells) + " |"

    for k in range(start, end):
        cells = row_cells(lines[k])
        if len(cells) != len(cols):
            continue
        if all(cells[i] == v for i, v in zip(kis, key_vals)):
            new = build(list(cells))
            if new == lines[k]:
                return lines, "same"
            out = list(lines)
            out[k] = new
            return out, "changed"

    cells = ["—"] * len(cols)
    for c, v in zip(key_cols, key_vals):
        cells[cols.index(c)] = v
    new = build(cells)
    out = list(lines)
    # 占位行（整行都是 — / 空）直接顶掉，否则追加
    for k in range(start, end):
        c2 = row_cells(lines[k])
        if all(x in ("—", "-", "") for x in c2):
            out[k] = new
            return out, "changed"
    out.insert(end, new)
    return out, "changed"


# ---------------------------------------------------------------- diff

class Edit(object):
    def __init__(self, path, before, after, notes):
        self.path, self.before, self.after, self.notes = path, before, after, notes

    @property
    def changed(self):
        return self.before != self.after

    def print_diff(self):
        rel = os.path.relpath(self.path, VAULT)
        if not self.changed:
            print("  ═ %s（无改动）" % rel)
            for n in self.notes:
                print("      %s" % n)
            return
        print("  ✎ %s" % rel)
        for n in self.notes:
            print("      %s" % n)
        d = difflib.unified_diff(self.before.split("\n"), self.after.split("\n"),
                                 lineterm="", n=0)
        for ln in list(d)[2:]:
            if ln.startswith("@@"):
                continue
            print("        %s" % ln)


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="OpenX 闸 3 回写（结构性部分）")
    ap.add_argument("--article", required=True)
    ap.add_argument("--lang", default=None, choices=LANGS)
    ap.add_argument("--status", default=None, choices=STATUSES)
    ap.add_argument("--url", default=None)
    ap.add_argument("--publish-date", default=None)
    ap.add_argument("--outbound", default=None,
                    help="本文链出的 article_id，逗号分隔。会同时补对端 inbound")
    ap.add_argument("--stage", default=None, choices=STAGES)
    ap.add_argument("--anchors", default=None, help="锚文本池，逗号分隔")
    ap.add_argument("--date", default="", help="updated 字段，默认系统当天")
    ap.add_argument("--category", default=None,
                    help="站点导航栏目（6 选 1）。与 cluster 是两套体系")
    ap.add_argument("--author-url", dest="author_url", default=None,
                    help="作者页地址，官网上线、作者页做出来后回填")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.url and not args.publish_date:
        print("提示：给了 --url 但没给 --publish-date，URL 登记表的日期列会留空。\n")

    today = args.date.strip() or datetime.date.today().isoformat()
    arts = scan_articles()
    aid, lang, path, fm, body = locate(arts, args.article, args.lang)
    by_id_lang = {(a[0], a[1]): a for a in arts}

    edits, manual = [], []

    # ---- 1. 本文 frontmatter ----
    new_fm, notes = list(fm), []
    for key, val in (("status", args.status), ("url", args.url),
                     ("publish_date", args.publish_date), ("pipeline_stage", args.stage),
                     ("category", args.category), ("author_url", args.author_url)):
        if val is None:
            continue
        cur = fm_get(new_fm, key)
        new_fm, ch = fm_set_scalar(new_fm, key, val)
        notes.append("%s: %s → %s%s" % (key, cur if cur else "（空）", val,
                                        "" if ch else "（已是目标值）"))

    outbound = None
    if args.outbound is not None:
        outbound = [x.strip() for x in args.outbound.split(",") if x.strip()]
        known = {a[0] for a in arts}
        missing = [o for o in outbound if o not in known]
        if missing:
            die("--outbound 里这些 ID 库里不存在：%s\n"
                "  内链不许指向不存在的文章。先立项，或从列表里去掉。" % "、".join(missing))
        if aid in outbound:
            die("--outbound 含自己（%s），文章不能链向自己。" % aid)
        cur = fm_list(new_fm, "outbound_links") or []
        new_fm, ch = fm_set_list(new_fm, "outbound_links", outbound)
        notes.append("outbound_links: %s → %s%s"
                     % (cur or "[]", outbound, "" if ch else "（已是目标值）"))

    new_fm, _ = fm_set_scalar(new_fm, "updated", today)
    before = read(path)
    # body 原样接回，不做 strip —— 吃掉 frontmatter 后的空行会产生跟目标无关的改动。
    # split_fm 的 body 不含结束 --- 那一行的换行，所以这里补一个。
    after = "---\n" + "\n".join(new_fm) + "\n---\n" + body
    edits.append(Edit(path, before, after, notes))

    # ---- 2. 对端 inbound_links（对称性）----
    if outbound:
        for target in outbound:
            key = (target, lang)
            if key not in by_id_lang:
                have = sorted({a[1] for a in arts if a[0] == target})
                manual.append("%s 没有 %s 版本（现有 %s），它的 inbound_links 没法补。"
                              "等该语言版本上线后补，或按 SOP-4 删掉这条链。"
                              % (target, lang, "、".join(have) or "无"))
                continue
            t_aid, t_lang, t_path, t_fm, t_body = by_id_lang[key]
            cur_in = fm_list(t_fm, "inbound_links") or []
            if aid in cur_in:
                edits.append(Edit(t_path, read(t_path), read(t_path),
                                  ["inbound_links 已含 %s" % aid]))
                continue
            merged = sorted(set(cur_in + [aid]))
            t_new, _ = fm_set_list(list(t_fm), "inbound_links", merged)
            t_new, _ = fm_set_scalar(t_new, "updated", today)
            edits.append(Edit(t_path, read(t_path),
                              "---\n" + "\n".join(t_new) + "\n---" + t_body,
                              ["inbound_links: %s → %s" % (cur_in or "[]", merged)]))

    # ---- 3. 文章总表 ----
    lines = read(TOTAL_TABLE).split("\n")
    t_notes = []
    if args.status:
        tb = find_table(lines, ["article_id", "源语言标题", "整体状态"])
        if tb is None:
            die("文章总表里找不到主记录表（表头需含 article_id / 源语言标题 / 整体状态）。")
        lines, st = set_cell(lines, tb, "article_id", aid, "整体状态", args.status)
        t_notes.append("主记录 整体状态 → %s（%s）" % (args.status, st))

        tb = find_table(lines, ["article_id"] + LANGS)
        if tb is None:
            die("文章总表里找不到语言版本矩阵。")
        lines, st = set_cell(lines, tb, "article_id", aid, lang, args.status)
        t_notes.append("语言矩阵 %s 列 → %s（%s）" % (lang, args.status, st))

    if args.url:
        tb = find_table(lines, ["article_id", "lang", "slug", "url", "publish_date"])
        if tb is None:
            die("文章总表里找不到已发布 URL 登记表。")
        lines, st = upsert_row(lines, tb, ["article_id", "lang"], [aid, lang],
                               {"slug": fm_get(fm, "slug") or "—",
                                "url": args.url,
                                "publish_date": args.publish_date or "—"})
        t_notes.append("URL 登记 → %s（%s）" % (args.url, st))

    if t_notes:
        edits.append(Edit(TOTAL_TABLE, read(TOTAL_TABLE), "\n".join(lines), t_notes))

    # ---- 4. 关键词登记表：主词状态 ----
    if args.status:
        kw_lines = read(KEYWORD_TABLE).split("\n")
        tb = find_table(kw_lines, ["主关键词", "归属文章", "状态"])
        if tb is None:
            die("关键词登记表里找不到主关键词表。")
        kw_lines, st = set_cell(kw_lines, tb, "归属文章", aid, "状态", args.status)
        if st == "no-row":
            manual.append("关键词登记表主词表里没有 %s 的行——立项时可能漏登记，去补一行。" % aid)
        else:
            edits.append(Edit(KEYWORD_TABLE, read(KEYWORD_TABLE), "\n".join(kw_lines),
                              ["主词表 状态 → %s（%s）" % (args.status, st)]))

    # ---- 5. 锚文本池 ----
    if args.anchors:
        anchors = [x.strip() for x in args.anchors.split(",") if x.strip()]
        if len(anchors) < 3:
            print("提示：锚文本只给了 %d 条，契约要求每语言 ≥3 条，"
                  "少于 3 条会导致全站锚文本雷同。\n" % len(anchors))
        a_lines = read(ANCHOR_TABLE).split("\n")
        hdr = None
        for i, ln in enumerate(a_lines):
            if ln.startswith("### ") and aid in ln:
                hdr = i
                break
        if hdr is None:
            manual.append("术语与锚文本表里没有 %s 的小节，锚文本池没写。"
                          "手动加一节 `### %s · <标题>` 再跑一次。" % (aid, aid))
        else:
            tb = find_table(a_lines[hdr:], ["lang", "锚文本候选"])
            if tb is None:
                manual.append("%s 那一节里找不到锚文本表。" % aid)
            else:
                tb = (tb[0] + hdr, tb[1], tb[2] + hdr, tb[3] + hdr)
                a_lines, st = set_cell(a_lines, tb, "lang", lang,
                                       "锚文本候选", " / ".join(anchors))
                edits.append(Edit(ANCHOR_TABLE, read(ANCHOR_TABLE), "\n".join(a_lines),
                                  ["%s 锚文本池 → %d 条（%s）" % (lang, len(anchors), st)]))

    # ---- 报告 ----
    print("闸 3 回写：%s（%s）" % (aid, lang))
    print("  文件：%s" % os.path.relpath(path, VAULT))
    print("-" * 64)
    touched = [e for e in edits if e.changed]
    for e in edits:
        e.print_diff()
    if not touched:
        print("\n所有目标值都已就位，没有需要改的地方（幂等）。")

    if outbound:
        manual.append("旧文正文里真的插进那条 wikilink —— 锚文本要嵌进句子，"
                      "脚本不做。位置用 `openx_audit.py backlink` 查。")
        manual.append("内链矩阵「已落实链接」加明细行 —— 插入位置与锚文本只存在于正文里。")
        manual.append("内链矩阵「待补链接队列」勾销对应行 —— 先确认旧文真的改了。")

    if manual:
        print("\n" + "-" * 64)
        print("以下要人工完成，脚本做不了（不是漏了，是不该由脚本做）：")
        for i, m in enumerate(manual, 1):
            print("  %d. %s" % (i, m))

    if args.dry_run:
        print("\n--dry-run：未写入任何文件。")
        return 0

    for e in edits:
        if e.changed:
            io.open(e.path, "w", encoding="utf-8").write(e.after)

    print("\n✓ 已写入 %d 个文件。" % len(touched))
    print("  收尾必跑：python3 \"工具/openx_audit.py\" scan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
