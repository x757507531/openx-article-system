#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenX 文章系统 · 机械审核工具

只做字面层面的确定性检查，不做语义判断。
语义判断由 SOP-1 / SOP-2 里的人（或 agent）完成——脚本说「无冲突」不等于可以开题。

仅依赖 Python 3 标准库。

用法：
  python3 工具/openx_audit.py keyword  --lang zh-Hant --primary "OpenX 註冊" [--secondary "詞1,詞2"]
  python3 工具/openx_audit.py links    --lang zh-Hant --cluster "交易所入門" --keywords "主詞,副詞1"
  python3 工具/openx_audit.py backlink --lang zh-Hant --target OX-0002 --keyword "新文主詞"
  python3 工具/openx_audit.py langcheck --article OX-0002 --lang ja
  python3 工具/openx_audit.py scan [--lang ja]
"""

import argparse
import os
import re
import sys
from collections import defaultdict

VAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTICLES_DIR = os.path.join(VAULT, "03-文章")
INDEX_DIR = os.path.join(VAULT, "01-索引")
KEYWORD_TABLE = os.path.join(INDEX_DIR, "关键词登记表.md")

LANGS = ["zh-Hant", "zh-Hans", "en", "ja", "ko", "vi", "th"]

REQUIRED_FIELDS = [
    "article_id", "title", "lang", "source_lang", "status",
    "cluster", "primary_keyword", "slug",
]


# --------------------------------------------------------------------------
# frontmatter 解析（简易 YAML 子集：标量、内联列表、块列表）
# --------------------------------------------------------------------------

def parse_frontmatter(text):
    if not text.startswith("---"):
        return None, text
    parts = text.split("\n")
    if parts[0].strip() != "---":
        return None, text
    end = None
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, text

    data, key = {}, None
    for line in parts[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^\s*-\s+", line) and key:
            item = re.sub(r"^\s*-\s+", "", line).strip().strip("'\"")
            if item:
                # `key:` 后接块列表时，上一轮把值记成了空字符串，这里要转成列表
                if not isinstance(data.get(key), list):
                    data[key] = []
                data[key].append(item)
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw == "":
            data[key] = ""
        elif raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            data[key] = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()] if inner else []
        else:
            data[key] = raw.strip("'\"")
    return data, "\n".join(parts[end + 1:])


def load_articles():
    """返回 [(fm, body, path)]，跳过无 frontmatter 与模板文件。"""
    out = []
    if not os.path.isdir(ARTICLES_DIR):
        return out
    for root, _dirs, files in os.walk(ARTICLES_DIR):
        for fn in sorted(files):
            if not fn.endswith(".md") or fn.startswith("_"):
                continue
            path = os.path.join(root, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError as e:
                warn("读取失败 %s: %s" % (rel(path), e))
                continue
            fm, body = parse_frontmatter(text)
            if not fm or not fm.get("article_id"):
                continue
            if str(fm.get("article_id")).upper().startswith("OX-XXXX"):
                continue
            out.append((fm, body, path))
    return out


def rel(path):
    return os.path.relpath(path, VAULT)


def warn(msg):
    sys.stderr.write("  ! %s\n" % msg)


def as_list(fm, key):
    v = fm.get(key, [])
    if isinstance(v, list):
        return [x for x in v if x]
    return [v] if v else []


def norm(s):
    """归一化：小写、去空白与常见分隔符，用于字面比较。"""
    return re.sub(r"[\s\-_·・]+", "", str(s or "").lower())


# --------------------------------------------------------------------------
# 同义词组（从关键词登记表读取）
# --------------------------------------------------------------------------

def load_synonym_groups():
    """解析登记表「已知同义词 / 变体组」表格 → [(lang, {词集})]"""
    groups = []
    if not os.path.exists(KEYWORD_TABLE):
        return groups
    with open(KEYWORD_TABLE, encoding="utf-8") as f:
        lines = f.read().split("\n")
    in_section = False
    for line in lines:
        if line.startswith("## "):
            in_section = "同义词" in line or "變體" in line or "变体" in line
            continue
        if not in_section or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or set(cells[0]) <= set("-: "):
            continue
        if cells[0] in ("组名", "組名") or cells[1] == "lang":
            continue
        lang, words_raw = cells[1], cells[2]
        words = {norm(w) for w in re.split(r"[/／,，]", words_raw) if w.strip()}
        if words and lang in LANGS:
            groups.append((lang, words))
    return groups


# --------------------------------------------------------------------------
# keyword — 闸 1 冲突检查
# --------------------------------------------------------------------------

def cmd_keyword(args):
    arts = load_articles()
    lang = args.lang
    primary = args.primary.strip()
    secondary = [s.strip() for s in (args.secondary or "").split(",") if s.strip()]
    np_ = norm(primary)

    same_lang = [(fm, p) for fm, _b, p in arts if fm.get("lang") == lang]

    print("OpenX 关键词冲突检查")
    print("  语言 : %s" % lang)
    print("  主词 : %s" % primary)
    print("  副词 : %s" % ("、".join(secondary) if secondary else "（未提供）"))
    print("  已入库同语言文章：%d 篇（全库 %d 篇）" % (len(same_lang), len(arts)))
    print("-" * 64)

    hits = {"L1": [], "L2": [], "L3": [], "L3b": [], "L4": []}

    syn_groups = [ws for lg, ws in load_synonym_groups() if lg == lang]

    for fm, path in same_lang:
        aid = fm.get("article_id")
        other_p = str(fm.get("primary_keyword") or "")
        op = norm(other_p)
        if not op:
            continue

        if op == np_:
            hits["L1"].append((aid, other_p, "主词完全相同", rel(path)))
            continue

        reason = None
        if op in np_ or np_ in op:
            reason = "主词互为子串"
        else:
            for ws in syn_groups:
                if np_ in ws and op in ws:
                    reason = "落在同一同义词组"
                    break
        if reason:
            hits["L2"].append((aid, other_p, reason, rel(path)))
            continue

        other_sec_raw = as_list(fm, "secondary_keywords")
        other_sec = [norm(s) for s in other_sec_raw]

        if np_ in other_sec:
            hits["L3"].append((aid, other_p, "本文主词正是该文副词 → 该文必须补内链", rel(path)))
            continue

        # L3b：新文主词与旧文某副词互为子串（如旧文副词「USDC」vs 新文主词「USDC 是什麼」）。
        # 语义上仍是「旧文谈过这个话题、现在有专文了」，但可能同时命中多篇，故列为候选。
        near = [other_sec_raw[i] for i, s in enumerate(other_sec)
                if s and s != np_ and (s in np_ or np_ in s)]
        if near:
            hits["L3b"].append((aid, other_p,
                                "该文副词「%s」与本文主词高度重合 → 候选补链"
                                % "、".join(near[:3]), rel(path)))
            continue

        if secondary:
            overlap = {norm(s) for s in secondary} & set(other_sec)
            if len(overlap) >= 3:
                hits["L4"].append((aid, other_p, "副词重叠 %d 个" % len(overlap), rel(path)))

    labels = {
        "L1": "致命 · 禁止立项（同 lang 主词完全相同）",
        "L2": "高危 · 必须差异化（子串 / 同义组）",
        "L3": "中危 · 可立项，但产生强制内链动作",
        "L3b": "中危候选 · 旧文副词与本文主词高度重合，人工选一篇补链",
        "L4": "低危 · 记录，检查大纲重叠",
    }
    for lv in ("L1", "L2", "L3", "L3b", "L4"):
        rows = hits[lv]
        print("[%s] %s —— %d 条" % (lv, labels[lv], len(rows)))
        for aid, kw, why, p in rows:
            print("    %s  主词「%s」  %s" % (aid, kw, why))
            print("        %s" % p)
        if not rows:
            print("    无")
        print("")

    print("-" * 64)
    if hits["L1"]:
        print("结论：驳回。存在 L1 冲突，按 SOP-1 处置（更新旧文 / 合并 / 改词 / 撤题）。")
        code = 2
    elif hits["L2"]:
        print("结论：有条件通过。必须写出 L2 差异化说明并建立双向内链，否则不得进入写作。")
        code = 1
    else:
        print("结论：字面层面通过。")
        code = 0
    if hits["L3"]:
        print("待办：%d 篇旧文需补内链指向本文，登记进「内链矩阵 → 待补链接队列」。"
              % len(hits["L3"]))
    if hits["L3b"]:
        print("待办：%d 篇旧文是候选补链对象，人工确认后再登记（同一目标只留一篇，"
              "避免多篇旧文都链向本文导致锚文本雷同）。" % len(hits["L3b"]))
        print("      用 backlink 子命令定位确切插入位置：")
        print('      python3 "工具/openx_audit.py" backlink --lang %s --target <本文ID> '
              '--keyword "%s"' % (lang, primary))
    print("提醒：本脚本只做字面判定，语义是否撞车仍需按 SOP-1 Step 3 人工判断。")
    return code


# --------------------------------------------------------------------------
# links — 闸 2 内链候选
# --------------------------------------------------------------------------

def cmd_links(args):
    arts = load_articles()
    lang = args.lang
    cluster = (args.cluster or "").strip()
    kws = [k.strip() for k in (args.keywords or "").split(",") if k.strip()]
    kws_n = {norm(k) for k in kws}

    scored = []
    for fm, _b, path in arts:
        if fm.get("lang") != lang:
            continue
        aid = fm.get("article_id")
        score, why = 0, []
        if cluster and fm.get("cluster") == cluster:
            score += 5
            why.append("同簇")
        own = {norm(fm.get("primary_keyword"))} | {norm(s) for s in as_list(fm, "secondary_keywords")}
        inter = kws_n & own
        if norm(fm.get("primary_keyword")) in kws_n:
            score += 4
            why.append("其主词是本文关键词之一（强候选）")
        if inter:
            score += len(inter)
            why.append("关键词交集 %d" % len(inter))
        if score:
            scored.append((score, aid, fm, why, path))

    scored.sort(key=lambda x: -x[0])

    print("内链候选（lang=%s, cluster=%s）" % (lang, cluster or "—"))
    print("-" * 64)
    if not scored:
        print("无候选。若库中已有文章却无候选，检查 frontmatter 的 cluster 与 secondary_keywords 是否填写。")
    for score, aid, fm, why, path in scored[:20]:
        print("  [%2d] %s  %s" % (score, aid, fm.get("title")))
        print("       主词：%s" % fm.get("primary_keyword"))
        print("       理由：%s" % "、".join(why))
        offers = as_list(fm, "anchor_offers")
        print("       锚文本池：%s" % (" / ".join(offers) if offers
                                   else "（空！需先补 anchor_offers，见 SOP-2 A3）"))
        print("       %s" % rel(path))
        print("")

    print("-" * 64)
    print("三类必链自查（脚本不判定，人工确认）：")
    print("  1. 上行链 → 本簇 pillar，有且仅一条")
    print("  2. 前置知识链 → 概念首次出现处")
    print("  3. 下一步链 → 结语前")
    print("密度：每 800 字 ≤2 条，单篇出链 3–8 条，同一目标全文只链一次。")
    return 0


# --------------------------------------------------------------------------
# backlink — 找旧文里该补链的位置
# --------------------------------------------------------------------------

# 这些区块里不插内链：Answer Block 要保持干净供 AI 摘要引用，
# FAQ / 资料来源 / 免责声明 / 上稿信息属于附录，插链无助于读者动线。
APPENDIX_HEADINGS = ("常見問題", "常见问题", "FAQ", "資料來源", "资料来源",
                     "免責", "免责", "上稿用", "SEO 資訊", "SEO 信息", "結語", "结语")


def zone_of(heading, line):
    """判断某行属于哪个区块：正文 / Answer Block / 附录。"""
    if line.lstrip().startswith(">"):
        return "Answer Block／引用块"
    h = heading or ""
    for kw in APPENDIX_HEADINGS:
        if kw in h:
            return "附录（%s）" % kw
    return "正文"


def cmd_backlink(args):
    arts = load_articles()
    lang, target, kw = args.lang, args.target, args.keyword
    kw_n = norm(kw)

    print("反向补链扫描：在 %s 的旧文中查找「%s」，目标 %s" % (lang, kw, target))
    print("规则：只在**正文**区插链，Answer Block 与附录区跳过；每篇旧文只插一条。")
    print("-" * 64)

    found = 0
    for fm, body, path in arts:
        if fm.get("lang") != lang or fm.get("article_id") == target:
            continue
        if target in as_list(fm, "outbound_links"):
            continue  # 已经链过了

        lines = body.split("\n")
        current_h = "（引言前）"
        cands = []
        for i, line in enumerate(lines):
            if line.startswith("#"):
                current_h = line.strip()
                continue
            if kw in line or (kw_n and kw_n in norm(line)):
                cands.append((i + 1, current_h, line.strip(), zone_of(current_h, line)))
                if len(cands) >= 6:
                    break
        if not cands:
            continue

        found += 1
        print("  %s  %s" % (fm.get("article_id"), fm.get("title")))
        print("     %s" % rel(path))
        recommended = next((c for c in cands if c[3] == "正文"), None)
        for ln, h, text, zone in cands:
            snippet = text if len(text) <= 68 else text[:68] + "…"
            mark = "→ 建议插这里" if (recommended and ln == recommended[0]) else \
                   ("  跳过" if zone != "正文" else "  备选")
            print("     %s  第 %d 行 ｜ %s" % (mark, ln, zone))
            print("            所在 H2：%s" % h)
            print("            原句：%s" % snippet)
        if not recommended:
            print("     ⚠ 全部命中都在 Answer Block 或附录区 —— 这篇旧文不适合插链。")
            print("       要么放弃，要么在正文里补一句自然提及该话题的句子再插。")
        print("")

    if not found:
        print("  无命中。")
    print("-" * 64)
    print("确认后写进「内链矩阵 → 待补链接队列」，锚文本取自 %s 的 anchor_offers。" % target)
    return 0


# --------------------------------------------------------------------------
# langcheck — 某文的某语言版本是否存在
# --------------------------------------------------------------------------

def cmd_langcheck(args):
    arts = load_articles()
    aid = args.article
    versions = {fm.get("lang"): rel(p) for fm, _b, p in arts if fm.get("article_id") == aid}

    print("语言版本检查：%s" % aid)
    print("-" * 64)
    if not versions:
        print("  未找到该 article_id 的任何版本。")
        return 2
    for lg in LANGS:
        mark = "✓" if lg in versions else "—"
        print("  %s %-8s %s" % (mark, lg, versions.get(lg, "")))
    print("-" * 64)

    if args.lang:
        if args.lang in versions:
            print("结论：%s 版本存在 → 翻译时此内链可继承，锚文本取该语言 anchor_offers。" % args.lang)
            return 0
        print("结论：%s 版本不存在 → 翻译时删除指向 %s 的链接（保留句子），"
              "并登记待补队列。" % (args.lang, aid))
        return 1
    return 0


# --------------------------------------------------------------------------
# scan — 全库体检
# --------------------------------------------------------------------------

def cmd_scan(args):
    arts = load_articles()
    if args.lang:
        arts = [a for a in arts if a[0].get("lang") == args.lang]

    print("OpenX 全库体检%s —— 共 %d 个文件"
          % ("（lang=%s）" % args.lang if args.lang else "", len(arts)))
    print("=" * 64)
    problems = 0

    # 1. frontmatter 完整性
    print("\n[1] frontmatter 字段完整性")
    bad = 0
    for fm, _b, path in arts:
        missing = [f for f in REQUIRED_FIELDS if not fm.get(f)]
        if missing:
            bad += 1
            print("    %s 缺：%s" % (rel(path), ", ".join(missing)))
    print("    %s" % ("通过" if not bad else "%d 个文件字段不全" % bad))
    problems += bad

    # 2. 主关键词冲突
    print("\n[2] 主关键词唯一性（按 lang + 主词）")
    owners = defaultdict(list)
    for fm, _b, path in arts:
        key = (fm.get("lang"), norm(fm.get("primary_keyword")))
        if key[1]:
            owners[key].append((fm.get("article_id"), fm.get("primary_keyword"), rel(path)))
    dup = 0
    for (lg, _k), rows in sorted(owners.items()):
        ids = {r[0] for r in rows}
        if len(ids) > 1:
            dup += 1
            print("    [L1] %s 「%s」被 %d 篇占用：" % (lg, rows[0][1], len(ids)))
            for aid, _kw, p in rows:
                print("         %s  %s" % (aid, p))
    print("    %s" % ("通过" if not dup else "%d 组 L1 冲突，登记进「待仲裁冲突」" % dup))
    problems += dup

    # 3. 副词命中他文主词（L3）
    print("\n[3] L3：某文副词 = 他文主词 → 须补内链")
    prim = {}
    for fm, _b, _p in arts:
        prim[(fm.get("lang"), norm(fm.get("primary_keyword")))] = fm.get("article_id")
    l3 = 0
    for fm, _b, path in arts:
        aid, lg = fm.get("article_id"), fm.get("lang")
        outs = as_list(fm, "outbound_links")
        for s in as_list(fm, "secondary_keywords"):
            owner = prim.get((lg, norm(s)))
            if owner and owner != aid and owner not in outs:
                l3 += 1
                print("    %s 的副词「%s」归属 %s，但未链过去 → %s" % (aid, s, owner, rel(path)))
    print("    %s" % ("通过" if not l3 else "%d 条待补内链" % l3))
    problems += l3

    # 4. 链接对称性
    print("\n[4] outbound / inbound 对称性")
    out_map = defaultdict(set)
    in_map = defaultdict(set)
    known = set()
    for fm, _b, _p in arts:
        aid = fm.get("article_id")
        known.add(aid)
        out_map[aid] |= set(as_list(fm, "outbound_links"))
        in_map[aid] |= set(as_list(fm, "inbound_links"))
    asym = 0
    for src, targets in out_map.items():
        for t in targets:
            if t not in known:
                asym += 1
                print("    %s 链向不存在的 %s（死链）" % (src, t))
            elif src not in in_map[t]:
                asym += 1
                print("    %s → %s，但 %s 的 inbound_links 未记录 %s" % (src, t, t, src))
    print("    %s" % ("通过" if not asym else "%d 处不对称" % asym))
    problems += asym

    # 5. 孤儿 / 无出链
    print("\n[5] 孤儿文章与出链数")
    orphan = 0
    for fm, _b, path in arts:
        aid = fm.get("article_id")
        status = fm.get("status")
        n_in, n_out = len(in_map[aid]), len(out_map[aid])
        if status in ("published", "ready", "translated"):
            if n_in == 0:
                orphan += 1
                print("    [孤儿] %s 无入链 → %s" % (aid, rel(path)))
            if n_out == 0:
                orphan += 1
                print("    [无出链] %s → %s" % (aid, rel(path)))
            elif n_out > 8:
                orphan += 1
                print("    [出链过多] %s 有 %d 条（阈值 8）" % (aid, n_out))
    print("    %s" % ("通过" if not orphan else "%d 项" % orphan))
    problems += orphan

    # 6. 簇归属
    print("\n[6] 主题簇归属")
    cluster_dir = os.path.join(VAULT, "02-主题簇")
    existing = set()
    if os.path.isdir(cluster_dir):
        for fn in os.listdir(cluster_dir):
            if fn.endswith(".md") and not fn.startswith("_"):
                existing.add(os.path.splitext(fn)[0])
    badc = 0
    if not existing:
        print("    02-主题簇/ 下尚未建任何簇 → 跳过校验（不代表通过）")
    else:
        for fm, _b, path in arts:
            c = fm.get("cluster")
            if c and c not in existing:
                badc += 1
                print("    %s 的 cluster「%s」在 02-主题簇/ 下无对应文件"
                      % (fm.get("article_id"), c))
        print("    %s" % ("通过" if not badc else "%d 项" % badc))
    problems += badc

    # 7. 语言版本矩阵
    print("\n[7] 语言版本覆盖")
    by_id = defaultdict(set)
    titles = {}
    for fm, _b, _p in arts:
        by_id[fm.get("article_id")].add(fm.get("lang"))
        titles.setdefault(fm.get("article_id"), fm.get("title"))
    for aid in sorted(by_id):
        have = by_id[aid]
        miss = [lg for lg in LANGS if lg not in have]
        print("    %s  已有 %d/%d  缺：%s"
              % (aid, len(have), len(LANGS), ", ".join(miss) if miss else "无"))

    print("\n" + "=" * 64)
    print("体检完成：%d 项待处理。" % problems)
    print("L1 冲突 → 关键词登记表「待仲裁冲突」；待补内链 → 内链矩阵「待补链接队列」。")
    return 0 if problems == 0 else 1


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="OpenX 文章系统 · 机械审核工具（字面检查，不做语义判断）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("keyword", help="闸 1：主/副关键词冲突四级检查")
    p.add_argument("--lang", required=True, choices=LANGS)
    p.add_argument("--primary", required=True)
    p.add_argument("--secondary", default="")
    p.set_defaults(func=cmd_keyword)

    p = sub.add_parser("links", help="闸 2：内链候选与锚文本池")
    p.add_argument("--lang", required=True, choices=LANGS)
    p.add_argument("--cluster", default="")
    p.add_argument("--keywords", default="")
    p.set_defaults(func=cmd_links)

    p = sub.add_parser("backlink", help="闸 2 B 部分：旧文中该补链的位置")
    p.add_argument("--lang", required=True, choices=LANGS)
    p.add_argument("--target", required=True)
    p.add_argument("--keyword", required=True)
    p.set_defaults(func=cmd_backlink)

    p = sub.add_parser("langcheck", help="某文的各语言版本是否存在")
    p.add_argument("--article", required=True)
    p.add_argument("--lang", default="", choices=[""] + LANGS)
    p.set_defaults(func=cmd_langcheck)

    p = sub.add_parser("scan", help="全库体检")
    p.add_argument("--lang", default="", choices=[""] + LANGS)
    p.set_defaults(func=cmd_scan)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
