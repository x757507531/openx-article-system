#!/usr/bin/env python3
"""SEO / GEO 必备要素检查（A 元数据 / D GEO / E Schema / J 站点级）。

非黑盒的意思是三件事：
  1. 每一项都打印「实测值」与「判定依据」，不只给结论；
  2. 能机检的绝不写成散文红线（散文红线不会被执行，这是上一版 skill 的病）；
  3. 机器判不了的项，要求人在答案文件里留下书面结论——缺答案照样 exit 1。

用法：
    python3 check_geo.py <文章.md>              # 检查单篇（A / D / E）
    python3 check_geo.py <文章.md> --init       # 生成人工项答案文件模板
    python3 check_geo.py --site                 # 站点级检查（J + 技术层）
    python3 check_geo.py --site --site-base https://example.com   # 指定站点根，启用技术层
    python3 check_geo.py <文章.md> --no-manual  # 只跑机检，人工项降级为提示

    --vault <path>   指定 Vault 根（默认用下方 VAULT 常量）

退出码：0 全通过；1 有 FAIL 或人工项缺答案；2 用法错误 / 文件读不到。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unicodedata

VAULT = os.environ.get("OPENX_VAULT") or os.path.expanduser(
    "<VAULT_ROOT>"
)


def resolve_vault(vault: str, article_path: str | None = None) -> str:
    """Vault 定位顺序：--vault 参数 → OPENX_VAULT 环境变量 → 从文章路径向上找含 01-索引 的目录 → 常量。"""
    if os.path.isdir(os.path.join(vault, "01-索引")):
        return vault
    if article_path:
        d = os.path.dirname(os.path.abspath(article_path))
        while d and d != os.path.dirname(d):
            if os.path.isdir(os.path.join(d, "01-索引")):
                return d
            d = os.path.dirname(d)
    return vault
GATE_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))),
                       "seo-writing-orange", "scripts", "gate.py")

def kw_in(kw: str, text: str) -> bool:
    """主词匹配不分大小写（2026-09-18：frontmatter 写 smc 策略、标题写 SMC 策略曾被判未命中）。"""
    return bool(kw) and kw.lower() in (text or "").lower()


# A6 站点栏目分类。已向主人确认（2026-08-12）：OpenX 站沿用这 6 类，与 1000X 时期一致。
# 站点导航若改版，改这里即可，A6 判定跟着变。
SITE_CATEGORIES = ("最新消息", "新手入門", "策略分析", "風險管理", "市場回顧", "工具教學")

# A1 标题宽度上限（全形字）；A2 描述上限（字元）；A3 摘要区间（字）
TITLE_MAX_WIDTH = 30.0
DESC_MAX_CHARS = 155
ABSTRACT_RANGE = (90, 140)
TAG_RANGE = (6, 10)
# D1 Answer Block：六型字数并集（定义型 60–120、Yes/No 型 50–100、比较型 80–160、
# 方法／风险型 100–180、时效型 60–120）。分型定义见 seo-geo-check/reference/check-items.md
# （唯一事实来源），这里只放机检阈值；audit_d.py 复用本常量，不另抄一份。
ANSWER_BLOCK_RANGE = (50, 180)
# D1：出现这些时效词就必须同时标出日期，否则旧来源会造成旧答案
TIMELY_WORDS = ("目前", "現在", "现在", "最新", "截至", "當前", "当前", "如今", "今年", "至今")

# D8 二手转述黑名单：这类措辞等于没有来源
VAGUE_ATTRIBUTION = (
    "據研究表明", "据研究表明", "業內普遍認為", "业内普遍认为",
    "眾所皆知", "众所周知", "有專家指出", "有专家指出",
    "據悉", "据悉", "相關數據顯示", "相关数据显示", "有消息稱", "有消息称",
)

# A2 卖关子词：description 该一句话给答案，不是勾人点进来
CLICKBAIT = (
    "本文將", "本文将", "一起來看", "一起来看", "讓我們", "让我们",
    "揭秘", "你不知道的", "看下去就知道", "答案就在", "往下看",
)

# D4 / D11 依赖上文的开头词
DEPENDENT_OPENERS = (
    "上述", "這個", "这个", "那個", "那个", "如前所述", "前面提到", "前文",
    "因此", "所以", "於是", "于是", "這樣", "这样", "它", "他們", "他们",
)

# 需要人工书面结论的项（机器判不了的）
MANUAL_ITEMS = {
    "D3": "每个 H2 的首段是否真的先给结论？（脚本已列出各 H2 首句供判断）",
    "D10": "首次出现的专有名词是否都给了一句定义，没有靠上下文推断？",
}
MIN_ANSWER_CHARS = 8

# 在线检查（E3 / E4 / J1 / J7 / J8）：抓已发布页面。抓不到不判 FAIL——网络问题不是文章问题。
HTTP_TIMEOUT = 10
HTTP_UA = "Mozilla/5.0 (compatible; openx-geo-check/1.0)"
# 站点根 URL，例 "https://openx.com"。留空则技术层与 J3 检查跳过并提示配置。
SITE_BASE = ""
# 文章列表页 URL（J3 用）。留空则 J3 转人工。
SITE_LIST_PAGES: tuple[str, ...] = ()
# 想被 AI 引用必须放行的检索爬虫 / 与训练爬虫分开控制
SEARCH_BOTS = ("Googlebot", "Bingbot", "OAI-SearchBot")
TRAINING_BOTS = ("GPTBot", "CCBot", "Google-Extended")

C = {
    "PASS": "\033[32m", "FAIL": "\033[31m", "WARN": "\033[33m",
    "MANUAL": "\033[36m", "INFO": "\033[90m", "SKIP": "\033[90m", "off": "\033[0m",
}


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, list[str]]] = []

    def add(self, verdict: str, item: str, summary: str, detail: list[str] | None = None) -> None:
        self.rows.append((verdict, item, summary, detail or []))

    def section(self, title: str) -> None:
        self.rows.append(("__SEC__", "", title, []))

    def dump(self) -> None:
        use_color = sys.stdout.isatty()
        for verdict, item, summary, detail in self.rows:
            if verdict == "__SEC__":
                print(f"\n{'═' * 4} {summary} {'═' * 4}")
                continue
            tag = f"[{verdict}]".ljust(9)
            if use_color:
                tag = f"{C.get(verdict, '')}{tag}{C['off']}"
            print(f"{tag}{item:<5}{summary}")
            for line in detail:
                print(f"{'':9}{'':5}{line}")

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for verdict, _, _, _ in self.rows:
            if verdict != "__SEC__":
                out[verdict] = out.get(verdict, 0) + 1
        return out

    def failed(self) -> bool:
        return any(v in ("FAIL", "MANUAL") for v, _, _, _ in self.rows)


# ────────────────────────── 解析 ──────────────────────────

def _load_t2s():
    """繁简 + 两岸词汇归一化器。opencc 装了就用，没装则退化为原样返回。

    为什么必须有这一层：OpenX 源语言是 zh-Hant，而 gain.md、词表多用简体记录。
    字面比对不归一化必然对不上——这是 2026-08-08 实测 OX-0002 时确认过的误报源。
    """
    try:
        import opencc
    except Exception:  # noqa: BLE001
        return None
    # tw2sp 优先：它连**词汇**一起转（網路→网络、軟體→软件、程式介面→程序接口），
    # t2s 只转字形（網路→网路），台湾用词与大陆用词仍然对不上。
    # OpenX 源语言是 zh-Hant 台湾用词，而 gain.md 与评审证据常用大陆用词，
    # 只做字形转换照样误判为「证据不在正文中」。
    for cfg in ("tw2sp", "t2s"):
        try:
            return opencc.OpenCC(cfg).convert
        except Exception:  # noqa: BLE001
            continue
    return None


_T2S = _load_t2s()
ZH_NORM_AVAILABLE = _T2S is not None


def zh_norm(s: str) -> str:
    """归一化到简体后再比对。转换器不可用时原样返回。"""
    if not s or _T2S is None:
        return s
    try:
        return _T2S(s)
    except Exception:  # noqa: BLE001
        return s


def width(s: str) -> float:
    """全形字宽：CJK / 全角字符算 1，其余算 0.5。"""
    return sum(1.0 if unicodedata.east_asian_width(c) in ("W", "F") else 0.5 for c in s)


def han_count(s: str) -> int:
    return len(re.findall(r"[一-鿿]", s))


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """返回 (frontmatter dict, 去掉 frontmatter 的正文)。列表值存 list[str]。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4:]
    fm: dict = {}
    key = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_][\w]*):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val in ("", "[]"):
                fm[key] = [] if val == "[]" else ""
            else:
                fm[key] = val
        elif re.match(r"^\s+-\s+", line) and key:
            if not isinstance(fm.get(key), list):
                fm[key] = []
            fm[key].append(re.sub(r"^\s+-\s+", "", line).strip())
    return fm, body


def split_seo_section(body: str) -> tuple[str, str]:
    """按 `## 上稿用 SEO 資訊` 前缀切开正文与上稿信息节。"""
    for m in re.finditer(r"^##\s*上稿用\s*SEO\s*資訊.*$", body, re.M):
        return body[:m.start()], body[m.end():]
    return body, ""


def parse_seo_fields(seo: str) -> dict[str, str]:
    """`**標籤**（注解）` + 后续行 → {标签: 内容}。内容取到下一个粗体标签为止。"""
    fields: dict[str, str] = {}
    labels = list(re.finditer(r"^\*\*(.+?)\*\*(.*)$", seo, re.M))
    for i, m in enumerate(labels):
        name = m.group(1).strip()
        end = labels[i + 1].start() if i + 1 < len(labels) else len(seo)
        chunk = seo[m.end():end]
        lines = [l.strip() for l in chunk.splitlines() if l.strip()]
        fields[name] = "\n".join(lines)
    return fields


def seo_get(fields: dict[str, str], *aliases: str) -> tuple[str, str]:
    """按别名找字段，返回 (命中的标签名, 内容)。"""
    for want in aliases:
        for name, val in fields.items():
            if want.lower() in name.lower().replace(" ", ""):
                return name, val
    return "", ""


def first_line(val: str) -> str:
    """字段内容的第一行（跳过「備選」等附注行）。"""
    for line in val.splitlines():
        if line and not re.match(r"^(備選|备选|備案|其他|替代)", line):
            return line.strip().strip("`")
    return ""


def headings(body: str) -> list[tuple[int, str, int]]:
    """(level, 标题文本, 行号) —— 跳过代码块。"""
    out, in_fence = [], False
    for n, line in enumerate(body.splitlines(), 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,4})\s+(.+)$", line)
        if m:
            out.append((len(m.group(1)), m.group(2).strip(), n))
    return out


def blocks_after_h1(body: str) -> list[str]:
    """H1 之后的段落块（按空行切）。"""
    lines = body.splitlines()
    start = 0
    for n, line in enumerate(lines):
        if re.match(r"^#\s+", line):
            start = n + 1
            break
    chunk, blocks, cur = lines[start:], [], []
    for line in chunk:
        if line.strip():
            cur.append(line)
        elif cur:
            blocks.append("\n".join(cur))
            cur = []
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def section_bodies(body: str) -> list[tuple[str, str]]:
    """按 H2 切段，返回 [(H2 标题, 该节正文)]。"""
    parts = re.split(r"^##\s+(.+)$", body, flags=re.M)
    out = []
    for i in range(1, len(parts), 2):
        out.append((parts[i].strip(), parts[i + 1] if i + 1 < len(parts) else ""))
    return out


def paragraphs(text: str) -> list[str]:
    out, cur = [], []
    for line in text.splitlines():
        if line.strip() and not line.startswith(("|", ">", "#", "---")):
            cur.append(line.strip())
        elif cur:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


# ────────────────────────── A 区 ──────────────────────────

def check_a(r: Report, fm: dict, main: str, seo: str, fields: dict, vault: str) -> None:
    r.section("A · 元数据 / 上稿信息")
    primary = fm.get("primary_keyword", "") or ""

    # A1 Meta Title
    label, val = seo_get(fields, "MetaTitle", "Meta Title")
    title = first_line(val)
    if not title:
        r.add("FAIL", "A1", "找不到 Meta Title 字段", ["在上稿节写 **Meta Title** 后跟标题行"])
    else:
        w = width(title)
        full = sum(1 for c in title if unicodedata.east_asian_width(c) in ("W", "F"))
        half = len(title) - full
        has_kw = kw_in(primary, title)
        detail = [
            f"值: {title}",
            f"宽度: {full} 全角 + {half} 半角×0.5 = {w:.1f} / 上限 {TITLE_MAX_WIDTH:.0f} 全形字",
            f"主词「{primary}」{'命中' if has_kw else '未出现'}",
        ]
        alts = [l for l in val.splitlines() if re.match(r"^(備選|备选)", l)]
        if alts:
            detail.append(f"备选 {len(alts)} 条（不参与判定）")
        if w > TITLE_MAX_WIDTH:
            r.add("FAIL", "A1", f"Meta Title 超宽 {w:.1f} > {TITLE_MAX_WIDTH:.0f}", detail)
        elif not has_kw:
            r.add("FAIL", "A1", "Meta Title 不含主关键词", detail)
        else:
            r.add("PASS", "A1", f"Meta Title 合规（{w:.1f} 全形字）", detail)

    # A2 Meta Description
    label, val = seo_get(fields, "MetaDescription", "Meta Description")
    desc = first_line(val)
    if not desc:
        r.add("FAIL", "A2", "找不到 Meta Description 字段", [])
    else:
        n = len(desc)
        has_kw = kw_in(primary, desc)
        hits = [w_ for w_ in CLICKBAIT if w_ in desc]
        detail = [
            f"值: {desc[:60]}…" if n > 60 else f"值: {desc}",
            f"长度: {n} 字元 / 上限 {DESC_MAX_CHARS}",
            f"主词「{primary}」{'命中' if has_kw else '未出现'}",
            f"卖关子词: {'、'.join(hits) if hits else '无'}",
        ]
        if n > DESC_MAX_CHARS:
            r.add("FAIL", "A2", f"Meta Description 超长 {n} > {DESC_MAX_CHARS}", detail)
        elif not has_kw:
            r.add("FAIL", "A2", "Meta Description 不含主关键词", detail)
        elif hits:
            r.add("FAIL", "A2", "Meta Description 在卖关子，没一句话给答案", detail)
        else:
            r.add("PASS", "A2", f"Meta Description 合规（{n} 字元）", detail)

    # A3 文章摘要
    label, val = seo_get(fields, "文章摘要", "摘要")
    abstract = first_line(val)
    lo, hi = ABSTRACT_RANGE
    if not abstract:
        r.add("FAIL", "A3", "缺【文章摘要】字段",
              [f"要求 {lo}–{hi} 字，独立于 Meta Description"])
    else:
        n = han_count(abstract) or len(abstract)
        detail = [f"值: {abstract[:50]}…", f"长度: {n} 字 / 区间 {lo}–{hi}"]
        if lo <= n <= hi:
            r.add("PASS", "A3", f"文章摘要合规（{n} 字）", detail)
        else:
            r.add("FAIL", "A3", f"文章摘要 {n} 字，超出 {lo}–{hi}", detail)

    # A4 Slug
    slug = (fm.get("slug") or "").strip() or first_line(seo_get(fields, "Slug", "建議Slug")[1])
    slug = slug.strip("`")
    if not slug:
        r.add("FAIL", "A4", "slug 为空", [])
    else:
        ok_shape = bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug))
        year = re.search(r"(?:19|20)\d{2}", slug)
        detail = [
            f"值: {slug}",
            f"形态: {'合规（小写 + 连字符）' if ok_shape else '不合规（含大写/下划线/中文/空格）'}",
            f"年份: {'含 ' + year.group(0) + '，会过期' if year else '无'}",
        ]
        if not ok_shape or year:
            r.add("FAIL", "A4", "slug 不合规", detail)
        else:
            r.add("PASS", "A4", "slug 合规", detail)

    # A5 主题簇
    cluster = (fm.get("cluster") or "").strip()
    cluster_dir = os.path.join(vault, "02-主题簇")
    if not cluster:
        r.add("FAIL", "A5", "frontmatter 缺 cluster", [])
    else:
        exists = os.path.isfile(os.path.join(cluster_dir, f"{cluster}.md"))
        detail = [f"值: {cluster}", f"对应文件: 02-主题簇/{cluster}.md {'存在' if exists else '不存在'}"]
        if exists:
            r.add("PASS", "A5", f"主题簇「{cluster}」已建", detail)
        else:
            r.add("FAIL", "A5", f"主题簇「{cluster}」在 02-主题簇/ 下没有对应文件", detail)

    # A6 站点栏目分类
    cat = (fm.get("category") or "").strip() or first_line(seo_get(fields, "分類", "分类", "建議分類")[1])
    detail = [
        f"值: {cat or '（无）'}",
        f"允许值: {' / '.join(SITE_CATEGORIES)}（OpenX 站导航栏目，6 选 1）",
    ]
    if not cat:
        r.add("FAIL", "A6", "缺站点栏目分类", detail)
    elif any(c in cat for c in SITE_CATEGORIES):
        r.add("PASS", "A6", f"栏目分类「{cat}」合规", detail)
    else:
        r.add("FAIL", "A6", f"栏目分类「{cat}」不是 6 类之一", detail)

    # A7 标签
    label, val = seo_get(fields, "標籤", "标签", "建議標籤")
    tags = [t.strip() for t in re.split(r"[、,，]", first_line(val)) if t.strip()]
    lo, hi = TAG_RANGE
    detail = [f"数量: {len(tags)} / 区间 {lo}–{hi}", f"值: {'、'.join(tags[:12])}"]
    if lo <= len(tags) <= hi:
        r.add("PASS", "A7", f"标签 {len(tags)} 个", detail)
    else:
        r.add("FAIL", "A7", f"标签 {len(tags)} 个，超出 {lo}–{hi}", detail)

    # A8 元数据不进正文
    leaked = [k for k in ("**Meta Title**", "**Meta Description**", "【Meta description】") if k in main]
    if not seo.strip():
        r.add("FAIL", "A8", "找不到「上稿用 SEO 資訊」节", [])
    elif leaked:
        r.add("FAIL", "A8", "元数据标签泄漏进正文", [f"正文中出现: {'、'.join(leaked)}"])
    else:
        r.add("PASS", "A8", "元数据在文末独立节，未进正文",
              [f"上稿节字段数: {len(fields)}"])

    # A9 主词同时进 title 与 description
    in_t = kw_in(primary, title)
    in_d = kw_in(primary, desc)
    detail = [f"主词: {primary or '（frontmatter 未填）'}",
              f"Meta Title: {'✓' if in_t else '✗'}   Meta Description: {'✓' if in_d else '✗'}"]
    if in_t and in_d:
        r.add("PASS", "A9", "主词同时出现在 title 与 description", detail)
    else:
        r.add("FAIL", "A9", "主词未同时覆盖 title 与 description", detail)

    # A10 作者与资格（官方标 P0；同时是 E1 的 Person 标记数据来源）
    author = (fm.get("author") or "").strip() or first_line(seo_get(fields, "作者")[1])
    qual = ((fm.get("author_credentials") or "").strip()
            or first_line(seo_get(fields, "資格", "资格", "作者資格", "作者简介", "作者簡介")[1]))
    aurl = (fm.get("author_url") or "").strip()
    pdate = (fm.get("publish_date") or "").strip()
    udate = (fm.get("updated") or "").strip()
    detail = [
        f"作者: {author or '（无）'}",
        f"资格说明: {qual[:40] if qual else '（无）'}",
        f"发布日期: {pdate or '（未回填）'}　更新日期: {udate or '（无）'}",
        f"作者页: {aurl or '（未回填——官网上线、作者页做出来后补）'}",
    ]
    if not author:
        r.add("FAIL", "A10", "没有作者信息", detail +
              ["官方标 P0：作者、资格、发布与更新日期都要显示，作者名还要连向可唯一辨识的个人页"])
    elif not qual:
        r.add("WARN", "A10", f"有作者「{author}」但没有资格说明", detail +
              ["资格 = 学经历／执业资格／擅长领域，是 AI 判断可信度的主要依据之一"])
    elif not udate:
        r.add("WARN", "A10", "缺更新日期", detail)
    elif not aurl:
        r.add("WARN", "A10", f"作者与资格已填（{author}），缺作者页链接",
              detail + ["官网上线后回填 author_url；E3 的在线检查会查线上 author 是否连向该页"])
    else:
        r.add("PASS", "A10", f"作者、资格、作者页齐全（{author}）", detail)


# ────────────────────────── D 区 ──────────────────────────

def check_d(r: Report, fm: dict, main: str, vault: str, article_id: str) -> None:
    r.section("D · GEO 要素（被 AI 引用的条件）")
    primary = fm.get("primary_keyword", "") or ""

    # D1 Answer Block。D2 内链禁区已并入 D1（2026-09-03）；分型口径（字数并集、时效词标日期）
    # 2026-09-19 与 audit_d.py 统一到这里。「属哪一型、缺了该型哪几段」是语义判断，由 seo-geo-check 评审判。
    blocks = blocks_after_h1(main)
    ablock = blocks[0] if blocks else ""
    is_quote = ablock.startswith(">")
    if not is_quote:
        r.add("FAIL", "D1", "H1 之后第一个块不是独立引用块",
              [f"实际首块: {ablock[:60]}…" if ablock else "H1 之后没有内容"])
    else:
        qlines = [re.sub(r"^>\s?", "", l) for l in ablock.splitlines()]
        content = [l for l in qlines if l.strip() and not re.fullmatch(r"\*\*.+\*\*", l.strip())]
        caption = [l for l in qlines if re.fullmatch(r"\*\*.+\*\*", l.strip())]
        body_txt = " ".join(content)
        n = han_count(body_txt)
        lo, hi = ANSWER_BLOCK_RANGE
        has_kw = any(kw_in(primary, l) for l in qlines)
        links = re.findall(r"\[\[[^\]]+\]\]|\[[^\]]+\]\([^)]+\)", ablock)
        timely = [w for w in TIMELY_WORDS if w in body_txt]
        has_date = bool(re.search(r"\d{4}\s*年|\d{4}-\d{2}|\d{4}/\d{1,2}", body_txt))
        detail = [
            f"caption 行: {caption[0][:40] if caption else '（无）'}",
            f"字数: {n} 中文字 / 六型并集 {lo}–{hi}",
            f"主词{'命中' if has_kw else '未出现'}",
            f"块内链接: {len(links)} 个（内链禁区）",
            f"时效词: {'、'.join(timely) if timely else '无'}；日期: {'有' if has_date else '无'}",
        ]
        if links:
            r.add("FAIL", "D1", f"Answer Block 内有 {len(links)} 个链接（内链禁区）",
                  detail + [f"命中: {l[:40]}" for l in links[:3]])
        elif not (lo <= n <= hi):
            r.add("FAIL", "D1", f"Answer Block 字数 {n} 超出 {lo}–{hi}",
                  detail + ["定义型 60–120、Yes/No 型 50–100、比较型 80–160、方法与风险型 100–180、时效型 60–120，见 check-items.md 分型表"])
        elif timely and not has_date:
            r.add("FAIL", "D1", "Answer Block 用了时效词却没标日期",
                  detail + ["时效型不标日期最危险——旧来源会造成旧答案"])
        elif not has_kw:
            r.add("WARN", "D1", "Answer Block 不含主关键词", detail)
        else:
            r.add("PASS", "D1", f"Answer Block 为独立引用块、无链接、字数与时效标注合规（{n} 字）", detail)

    # D3 每个 H2 首段即结论 → 人工，脚本给素材（FAQ 节不算内容 H2）
    secs = section_bodies(main)
    # FAQ 与工作用节（交付前会删的）都不算内容 H2
    skip_sec = r"常見問題|常见问题|FAQ|內鏈清單|内链清单|發布前自檢|发布前自检|資料來源|资料来源|上稿用"
    content_secs = [(h, b) for h, b in secs if not re.search(skip_sec, h)]
    firsts = []
    for h, b in content_secs:
        ps = paragraphs(b)
        firsts.append(f"{h[:30]} → {ps[0][:46] if ps else '（该节无正文段落）'}…")
    r.add("MANUAL", "D3", f"每个 H2 首段是否先给结论（{len(content_secs)} 个内容节，见下）", firsts)

    # D4 FAQ
    faq = next((b for h, b in secs if re.search(r"常見問題|常见问题|FAQ", h)), None)
    if faq is None:
        r.add("FAIL", "D4", "找不到 FAQ 节（H2 标题需含「常見問題」或 FAQ）", [])
    else:
        qs = re.findall(r"^\*\*(Q\d*[：:.]?\s*.+?)\*\*\s*$", faq, re.M)
        pairs, bad_open = 0, []
        chunks = re.split(r"^\*\*Q\d*[：:.]?\s*.+?\*\*\s*$", faq, flags=re.M)[1:]
        for i, ch in enumerate(chunks):
            ps = paragraphs(ch)
            if ps:
                pairs += 1
                if ps[0].startswith(DEPENDENT_OPENERS):
                    bad_open.append(f"Q{i + 1} 答案以依赖上文的词开头: {ps[0][:30]}…")
        detail = [f"问题数: {len(qs)}", f"有答案的: {pairs}"] + bad_open
        if not qs:
            r.add("FAIL", "D4", "FAQ 节内没有 **Q…** 格式的问题", detail)
        elif pairs < len(qs):
            r.add("FAIL", "D4", f"{len(qs) - pairs} 个问题没有答案段", detail)
        elif bad_open:
            r.add("WARN", "D4", "有答案依赖上文，摘出来会读不懂", detail)
        else:
            r.add("PASS", "D4", f"FAQ {len(qs)} 题一问一答、答案自包含", detail)

    # D5 可查证数字与日期：已删除（2026-09-03）。阈值无依据，且能靠无关数字凑满，拦不住真问题。

    # D6 信息增益（委托 gate.py，不重写逻辑）
    gain_dir = os.path.join(vault, "06-工作区", "增益", article_id) if article_id else ""
    gain_md = os.path.join(gain_dir, "gain.md")
    if not article_id:
        r.add("FAIL", "D6", "frontmatter 无 article_id，定位不到 gain.md", [])
    elif not os.path.isfile(gain_md):
        r.add("FAIL", "D6", "找不到 gain.md（M3 闸 1.5 未过）",
              [f"应在: 06-工作区/增益/{article_id}/gain.md",
               "至少写 1 条「SERP 前 10 都没有的东西」，带一手来源 URL 与读者价值"])
    else:
        try:
            p = subprocess.run([sys.executable, GATE_PY, "gain", gain_dir, "--min-items", "1"],
                               capture_output=True, text=True, timeout=30)
            head = [l for l in p.stdout.splitlines() if l.strip()][:4]
            if p.returncode == 0:
                r.add("PASS", "D6", "gate.py gain 通过（委托判定）", head)
            else:
                r.add("FAIL", "D6", f"gate.py gain 不通过（exit {p.returncode}）", head)
        except Exception as e:  # noqa: BLE001
            r.add("WARN", "D6", f"调用 gate.py 失败：{e}", [f"路径: {GATE_PY}"])

    # D7 增益条目落地：按 6 字滑动窗口比对，命中即视为落地并打印证据。
    # 匹配不上不硬判 FAIL——文本比对本身不可靠（同一件事可以换句话说），
    # 转成人工书面确认，避免误报把流水线堵死。
    if os.path.isfile(gain_md):
        with open(gain_md, encoding="utf-8") as gain_file:
            gain_lines = gain_file.read().splitlines()
        items = [l.strip() for l in gain_lines
                 if re.match(r"^\s*(\d+[.、)]|[-*])\s*\S", l) and han_count(l) >= 8]
        n = 6
        hay = zh_norm(main)
        landed, detail, missing_idx = 0, [], []
        for i, it in enumerate(items, 1):
            grams = set()
            for blk in re.split(r"[^一-鿿]+", zh_norm(it)):
                if len(blk) >= n:
                    grams.update(blk[j:j + n] for j in range(len(blk) - n + 1))
                elif len(blk) >= 4:
                    grams.add(blk)
            hit = sorted(g for g in grams if g in hay)
            if hit:
                landed += 1
                detail.append(f"第 {i} 条 ✓ 正文命中「{hit[0]}」等 {len(hit)} 处")
            else:
                missing_idx.append(i)
                detail.append(f"第 {i} 条 ✗ 无 {n} 字连续重合: {it[:40]}…")
        detail.insert(0, f"落地: {landed}/{len(items)} 条（{n} 字滑动窗口，已做繁简归一化）"
                      if ZH_NORM_AVAILABLE else
                      f"落地: {landed}/{len(items)} 条（{n} 字滑动窗口，"
                      f"⚠️ opencc 未安装，繁简未归一化，繁中稿此项结果不可信）")
        if not items:
            r.add("FAIL", "D7", "gain.md 里没有可识别的增益条目", detail)
        elif landed == len(items):
            r.add("PASS", "D7", f"{landed} 条增益都在正文找到对应内容", detail)
        else:
            MANUAL_ITEMS["D7"] = (f"gain.md 第 {'、'.join(map(str, missing_idx))} 条在正文哪一段？"
                                  "（脚本按字面比对没找到，换了说法就属正常，写明段落即可）")
            r.add("MANUAL", "D7", MANUAL_ITEMS["D7"], detail)
    else:
        r.add("SKIP", "D7", "无 gain.md，跳过落地检查", [])

    # D8 一手源 / 禁二手转述
    vague = [w for w in VAGUE_ATTRIBUTION if w in main]
    domains = set(re.findall(r"https?://([^/\s)]+)", main))
    detail = [f"二手转述措辞: {'、'.join(vague) if vague else '无'}",
              f"外链域名 {len(domains)} 个: {'、'.join(sorted(domains)[:6])}"]
    if vague:
        r.add("FAIL", "D8", "出现无来源的二手转述措辞", detail)
    elif not domains:
        r.add("WARN", "D8", "正文没有任何外部来源链接",
              detail + ["数量不是标准，但一个出处都没有仍需确认：主张是否都属作者第一手观察"])
    else:
        r.add("PASS", "D8", f"无二手转述措辞（外链 {len(domains)} 个域名，仅供参考）",
              detail + ["**数量不是判定标准**——官方反对每篇机械插 n 个链接。"
                        "「重要主张是否就近有来源」由评审判"])

    # D9 承认边界
    edge = re.findall(r"我沒找到|我没找到|查不到|對不上|对不上|口徑不一致|口径不一致|"
                      r"不確定|不确定|以官方.{0,6}為準|以官方.{0,6}为准|還沒|还没", main)
    if edge:
        r.add("PASS", "D9", f"有 {len(edge)} 处承认边界的表述",
              [f"抽样: {'、'.join(sorted(set(edge))[:5])}"])
    else:
        r.add("MANUAL", "D9", "未检出承认边界的表述，请说明本文是否真的没有不确定处", [])

    # D11 段落自包含
    ps = paragraphs(main)
    dep = [p for p in ps if p.startswith(DEPENDENT_OPENERS)]
    ratio = len(dep) / len(ps) if ps else 0
    detail = [f"段落 {len(ps)} 个，其中 {len(dep)} 个以依赖上文的词开头（{ratio:.0%}）"]
    if dep[:3]:
        detail += [f"例: {p[:40]}…" for p in dep[:3]]
    if ratio > 0.2:
        r.add("WARN", "D11", f"{ratio:.0%} 的段落依赖上文，摘出来会读不懂", detail)
    else:
        r.add("PASS", "D11", f"段落自包含度可接受（依赖上文 {ratio:.0%}）", detail)

    # D12 结构化呈现
    tables = len(re.findall(r"^\|.+\|\s*$", main, re.M))
    steps = len(re.findall(r"^\s*\d+[.、)]\s+\S", main, re.M))
    detail = [f"表格行: {tables}", f"编号步骤行: {steps}"]
    if tables >= 3 or steps >= 3:
        r.add("PASS", "D12", "有对照表或编号步骤，利于片段擷取", detail)
    else:
        r.add("WARN", "D12", "没有表格也没有编号步骤，可枚举内容建议结构化", detail)

    # D10 → 人工
    r.add("MANUAL", "D10", MANUAL_ITEMS["D10"], [])


# ────────────────────────── E 区 ──────────────────────────

# E1：Article + BreadcrumbList 必备；实体类至少一个；FAQPage 可选
# （FAQ Rich Result 已从搜索结果移除、官方文件下架，无证据提升 AI 引用）
REQUIRED_SCHEMA = ("Article", "BreadcrumbList")
ENTITY_SCHEMA = ("Organization", "Person", "WebSite")
OPTIONAL_SCHEMA = ("FAQPage",)

CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}


def check_e(r: Report, main: str, fields: dict, url: str) -> int:
    """返回正文 FAQ 题数（在线检查要用它比对线上 FAQPage）。"""
    r.section("E · 结构化数据")
    label, val = seo_get(fields, "Schema", "建議Schema")
    line = val.replace("\n", " ")
    types = set(re.findall(r"\b(?:Article|BlogPosting|BreadcrumbList|Organization|Person|WebSite|FAQPage)\b", line))
    missing = [w for w in REQUIRED_SCHEMA if w not in types
               and not (w == "Article" and "BlogPosting" in types)]
    entity = [w for w in ENTITY_SCHEMA if w in types]
    optional = [w for w in OPTIONAL_SCHEMA if w in types]
    detail = [
        f"值: {line[:80] or '（无）'}",
        "必备: " + "、".join(f"{w}{'✓' if w not in missing else '✗'}" for w in REQUIRED_SCHEMA),
        f"实体类（至少 1 个）: {'、'.join(entity) if entity else '✗ 一个都没有'}"
        f"　可选: {'、'.join(optional) if optional else '无'}",
    ]
    if not line:
        r.add("FAIL", "E1", "上稿节没有 Schema 字段", detail)
    elif missing:
        r.add("FAIL", "E1", f"Schema 缺 {'、'.join(missing)}", detail)
    elif not entity:
        r.add("FAIL", "E1", "缺实体类 Schema（Organization / Person / WebSite 至少一个）",
              detail + ["它们对搜索显示、作者与日期归属、站点名称理解最直接"])
    else:
        r.add("PASS", "E1", f"Schema 合规（必备 2 类 + 实体 {len(entity)} 类）",
              detail + ["FAQPage 已降为可选：问答展示位已从搜索结果移除，且无证据提升 AI 引用"])

    # E2 已并入 E1（2026-09-03）：FAQPage 可选；只有声明了 FAQPage 才核「标记须与可见内容一致」
    faq = next((b for h, b in section_bodies(main) if re.search(r"常見問題|常见问题|FAQ", h)), "")
    actual = len(re.findall(r"^\*\*Q\d*[：:.]?\s*.+?\*\*\s*$", faq, re.M))
    if optional:
        declared = None
        m = re.search(r"([0-9]+|[一二三四五六七八九十]+)\s*[題题]", line)
        if m:
            tok = m.group(1)
            declared = int(tok) if tok.isdigit() else CN_NUM.get(tok)
        detail = [f"正文 FAQ 题数: {actual}",
                  f"Schema 行声明: {declared if declared is not None else '未声明题数'}",
                  "FAQPage 是可选项；保留就必须与可见内容一致（原 E2，已并入 E1）"]
        if declared is None:
            r.add("WARN", "E1", f"声明了 FAQPage 但未写题数，正文有 {actual} 题", detail)
        elif declared != actual:
            r.add("FAIL", "E1", f"FAQPage 题数不一致：正文 {actual}，声明 {declared}", detail)
        else:
            r.add("PASS", "E1", f"FAQPage 与正文一致（{actual} 题）", detail)

    # E3 / E4 需要已发布页面，交给在线检查；未发布就挂着，发布后回来跑
    if not url:
        r.add("SKIP", "E3", "未发布（frontmatter url 为空），发布后由在线检查判定", [])
        r.add("SKIP", "E4", "未发布，发布后由在线检查判定", [])
    return actual


# ────────────────────────── 在线检查（抓已发布页面） ──────────────────────────

def fetch(url: str) -> tuple[str, str]:
    """抓页面，返回 (html, 错误说明)。抓不到不判 FAIL——网络问题不是文章问题。"""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": HTTP_UA})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read()
            enc = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(enc, errors="replace"), ""
    except Exception as e:  # noqa: BLE001
        return "", f"{type(e).__name__}: {e}"


def jsonld_nodes(html: str) -> tuple[list[tuple[str, dict]], list[str]]:
    """提取所有 JSON-LD 节点，返回 ([(type, node)], [解析错误])。展开 @graph。"""
    import json
    nodes, errors = [], []
    pat = r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    for m in re.finditer(pat, html, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except Exception as e:  # noqa: BLE001
            errors.append(f"JSON-LD 块解析失败: {e}")
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            if isinstance(node.get("@graph"), list):
                nodes += [(str(n.get("@type", "")), n) for n in node["@graph"] if isinstance(n, dict)]
            else:
                nodes.append((str(node.get("@type", "")), node))
    return nodes, errors


def visible_text(html: str) -> str:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", t)


def check_online(r: Report, url: str, faq_count: int) -> None:
    """E3 / E4 / J1 / J7 / J8 —— 需要已发布页面才能判的项。"""
    r.section("在线检查（已发布页面）")
    html, err = fetch(url)
    if err:
        r.add("WARN", "—", f"抓不到页面，在线项无法判定：{err}",
              [f"URL: {url}", "网络不通或页面未发布，不计入 FAIL"])
        for i in ("E3", "E4", "J1", "J7", "J8"):
            r.add("SKIP", i, "页面抓取失败，跳过", [])
        return
    r.add("INFO", "—", f"已抓取 {len(html):,} 字节：{url}", [])

    nodes, errors = jsonld_nodes(html)
    types = [t for t, _ in nodes]

    # E3 Article 必填字段
    art = next((n for t, n in nodes if "Article" in t or "BlogPosting" in t), None)
    want = ("headline", "datePublished", "dateModified", "author", "image")
    # author 还要能连到可唯一辨识作者的页面（官方 CH4 要求），这里查有没有 url/sameAs
    if art is None:
        r.add("FAIL", "E3", "页面 JSON-LD 里没有 Article 节点",
              [f"实际类型: {'、'.join(types) or '（无 JSON-LD）'}"])
    else:
        miss = [k for k in want if not art.get(k)]
        au = art.get("author")
        au_linked = isinstance(au, dict) and bool(au.get("url") or au.get("sameAs"))
        detail = [f"字段: " + "、".join(f"{k}{'✓' if not (k in miss) else '✗'}" for k in want)]
        detail.append(f"author 是否连向作者页: {'是' if au_linked else '否'}")
        if miss:
            r.add("FAIL", "E3", f"Article 缺 {'、'.join(miss)}", detail)
        elif not au_linked:
            r.add("WARN", "E3", "五个字段齐全，但 author 没连向可唯一辨识作者的页面",
                  detail + ["官方 CH4：作者文章应连向 ProfilePage，这是 A10 的机器可读那一半"])
        else:
            r.add("PASS", "E3", "Article 五个必填字段齐全、author 已连作者页", detail)

    # E4 JSON-LD 语法与类型（官方 Rich Results Test 仍建议人工过一次）
    faq_node = next((n for t, n in nodes if "FAQPage" in t), None)
    online_qs = len(faq_node.get("mainEntity") or []) if isinstance(faq_node, dict) else 0
    detail = [f"JSON-LD 节点 {len(nodes)} 个: {'、'.join(types) or '无'}",
              f"FAQPage 题数: {online_qs}（正文 {faq_count} 题）"]
    if errors:
        r.add("FAIL", "E4", f"{len(errors)} 个 JSON-LD 块语法错误", errors + detail)
    elif not nodes:
        r.add("FAIL", "E4", "页面没有任何 JSON-LD", detail)
    elif faq_node is not None and online_qs != faq_count:
        r.add("WARN", "E4", f"线上 FAQPage {online_qs} 题 ≠ 正文 {faq_count} 题",
              detail + ["FAQPage 已是可选项；若保留就得与可见内容一致，否则不如删掉"])
    else:
        r.add("PASS", "E4", "JSON-LD 语法合法、类型与题数对得上", detail +
              ["注：官方 Rich Results Test 的渲染结果仍建议人工过一次，脚本只验语法与一致性"])

    # J1 canonical 自指
    m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*>', html, re.I)
    href = re.search(r'href=["\']([^"\']+)["\']', m.group(0), re.I) if m else None
    canon = href.group(1) if href else ""
    norm = lambda u: u.rstrip("/").split("#")[0]  # noqa: E731
    detail = [f"canonical: {canon or '（无）'}", f"页面 URL: {url}"]
    if not canon:
        r.add("FAIL", "J1", "页面没有 canonical 标签", detail)
    elif norm(canon) == norm(url):
        r.add("PASS", "J1", "canonical 自指", detail)
    else:
        r.add("FAIL", "J1", "canonical 指向了别的页面", detail)

    # J7 图片规范
    imgs = re.findall(r"<img[^>]*>", html, re.I)
    no_dim = [t for t in imgs if not (re.search(r"\bwidth=", t, re.I) and re.search(r"\bheight=", t, re.I))]
    webp = [t for t in imgs if re.search(r"\.webp", t, re.I)]
    detail = [f"图片 {len(imgs)} 张；缺 width/height 的 {len(no_dim)} 张；WebP {len(webp)} 张"]
    if not imgs:
        r.add("SKIP", "J7", "页面没有 img 标签", detail)
    elif no_dim:
        r.add("FAIL", "J7", f"{len(no_dim)} 张图缺显式尺寸（会导致布局跳动）",
              detail + [f"例: {t[:70]}" for t in no_dim[:2]])
    elif not webp:
        r.add("WARN", "J7", "有显式尺寸，但没有 WebP 格式图片", detail)
    else:
        r.add("PASS", "J7", f"{len(imgs)} 张图都有显式尺寸，含 {len(webp)} 张 WebP", detail)

    # J2 hreflang 完整性（线上标签，与 --site 的语言矩阵互补）
    alts = re.findall(r'<link[^>]+rel=["\']alternate["\'][^>]*>', html, re.I)
    hl = [m.group(1) for a in alts
          for m in [re.search(r'hreflang=["\']([^"\']+)["\']', a, re.I)] if m]
    detail = [f"alternate 标签 {len(alts)} 个，hreflang 值: {'、'.join(hl) if hl else '无'}",
              f"x-default: {'有' if any(x.lower() == 'x-default' for x in hl) else '无'}"]
    if not hl:
        r.add("FAIL", "J2", "页面没有 hreflang 标签", detail +
              ["多语言版本互指缺失，各语区搜索结果拿不到对应版本"])
    elif not any(x.lower() == "x-default" for x in hl):
        r.add("WARN", "J2", f"有 {len(hl)} 个 hreflang 但缺 x-default", detail)
    else:
        r.add("PASS", "J2", f"hreflang {len(hl)} 个、含 x-default", detail +
              ["注：双向互指要各语言版本都上线后互相抓才能完全确认"])

    # J6 首屏弹窗候选（是否侵入仍是产品判断）
    modal = sorted({m.group(0)[:40] for m in re.finditer(
        r'aria-modal=|class=["\'][^"\']*(?:modal|popup|overlay|lightbox|newsletter)',
        html, re.I)})
    if modal:
        r.add("WARN", "J6", f"检出 {len(modal)} 处弹窗类元素，需人工确认是否首屏侵入",
              [f"命中: {m}" for m in modal[:4]] +
              ["脚本只能定位元素，「算不算侵入」是产品判断"])
    else:
        r.add("PASS", "J6", "未检出弹窗类元素", [])

    # T6 索引控制项误用
    robots_meta = re.findall(r'<meta[^>]+name=["\']robots["\'][^>]*>', html, re.I)
    content = " ".join(robots_meta).lower()
    bad = [k for k in ("noindex", "nofollow", "nosnippet", "noarchive") if k in content]
    detail = [f"robots meta: {'；'.join(robots_meta)[:100] or '（无，默认可索引）'}"]
    if "noindex" in bad:
        r.add("FAIL", "T6", "页面带 noindex——这一页不会被收录",
              detail + ["文章页出现 noindex 通常是模板或插件误设"])
    elif bad:
        r.add("WARN", "T6", f"页面带 {'、'.join(bad)}，确认是否有意为之", detail)
    else:
        r.add("PASS", "T6", "无索引限制标签", detail)

    # J8 更新日期可见
    dm = (art or {}).get("dateModified", "") if art else ""
    day = str(dm)[:10]
    text = visible_text(html)
    variants = []
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        y, mo, d = day.split("-")
        variants = [day, f"{y}/{int(mo)}/{int(d)}", f"{y}/{mo}/{d}",
                    f"{y} 年 {int(mo)} 月 {int(d)} 日", f"{y}年{int(mo)}月{int(d)}日"]
    hit = [v for v in variants if v in text]
    detail = [f"JSON-LD dateModified: {dm or '（无）'}",
              f"页面可见文本中命中: {'、'.join(hit) if hit else '无'}"]
    if not dm:
        r.add("FAIL", "J8", "JSON-LD 没有 dateModified", detail)
    elif hit:
        r.add("PASS", "J8", "更新日期在页面上可见", detail)
    else:
        r.add("WARN", "J8", "有 dateModified 但页面上找不到对应日期文本", detail +
              ["可能是格式差异，也可能真的没渲染出来"])


# ────────────────────────── J 区（站点级） ──────────────────────────


# ────────────────────────── J 区（站点级） ──────────────────────────

def check_tech(r: Report, site_base: str = "") -> None:
    """技术层：爬虫授权 / sitemap 新鲜度 / 语意可存取性 / llms.txt。

    这几项 AI 可见性比传统 SEO 更依赖，且都是站点级一次性配置。
    """
    r.section("技术层（站点级配置）")
    site_base = site_base or SITE_BASE
    if not site_base:
        r.add("MANUAL", "T0", "未配置 SITE_BASE（站点未上线时属正常），技术层全部待检",
              ["站点上线后：把根 URL 填进脚本顶部 SITE_BASE，或用 --site-base 传",
               "以下项目现在既做不了也检查不到，上线时容易整批漏掉——",
               "  T1 放行 OAI-SearchBot / Googlebot / Bingbot；GPTBot 单独决定",
               "  T2 sitemap.xml 每个 URL 带 lastmod",
               "  T3 语意标签（main/nav/article）与 ARIA 标注",
               "  T4 不要建 llms.txt（官方列为不需要）",
               "  T5 主要内容必须在初始 HTML 里，别做成前端渲染后才有内容",
               "另外这些要等文章 url 回填后逐篇跑：E3 / E4 / J1 / J2 / J6 / J7 / J8 / T6"])
        return
    base = site_base.rstrip("/")

    # T1 爬虫授权：检索爬虫要放行，训练爬虫可以另外决定
    robots, err = fetch(f"{base}/robots.txt")
    if err:
        r.add("WARN", "T1", f"抓不到 robots.txt：{err}", [f"URL: {base}/robots.txt"])
    else:
        blocked, unmentioned = [], []
        for bot in SEARCH_BOTS:
            m = re.search(rf"User-agent:\s*{re.escape(bot)}\s*\n((?:(?!User-agent:).*\n)*)",
                          robots, re.I)
            if not m:
                unmentioned.append(bot)
            elif re.search(r"Disallow:\s*/\s*$", m.group(1), re.M):
                blocked.append(bot)
        star = re.search(r"User-agent:\s*\*\s*\n((?:(?!User-agent:).*\n)*)", robots, re.I)
        star_all = bool(star and re.search(r"Disallow:\s*/\s*$", star.group(1), re.M))
        train = [b for b in TRAINING_BOTS if re.search(rf"User-agent:\s*{re.escape(b)}", robots, re.I)]
        detail = [
            f"检索爬虫被明确挡住的: {'、'.join(blocked) if blocked else '无'}",
            f"未出现在 robots.txt 的检索爬虫: {'、'.join(unmentioned) if unmentioned else '无'}（未提及=按 * 规则）",
            f"通用规则 User-agent: * 是否 Disallow /: {'是' if star_all else '否'}",
            f"训练爬虫单独列出的: {'、'.join(train) if train else '无'}",
        ]
        if blocked or star_all:
            r.add("FAIL", "T1", "有检索爬虫被挡住",
                  detail + ["OpenAI 官方：想在 ChatGPT 搜索里被发现、摘要与引用，必须放行 OAI-SearchBot"])
        elif not train:
            r.add("WARN", "T1", "检索爬虫已放行；训练爬虫未单独设定",
                  detail + ["OAI-SearchBot（检索）与 GPTBot（训练）可以分开控制——"
                            "想被引用但不想被训练，就单独给 GPTBot 写规则"])
        else:
            r.add("PASS", "T1", "检索爬虫放行、训练爬虫已单独设定", detail)

    # T2 sitemap lastmod
    sm, err = fetch(f"{base}/sitemap.xml")
    if err:
        r.add("WARN", "T2", f"抓不到 sitemap.xml：{err}", [f"URL: {base}/sitemap.xml"])
    else:
        urls = len(re.findall(r"<loc>", sm, re.I))
        last = len(re.findall(r"<lastmod>", sm, re.I))
        idx = bool(re.search(r"<sitemapindex", sm, re.I))
        detail = [f"{'索引型 sitemap' if idx else '普通 sitemap'}：<loc> {urls} 个，<lastmod> {last} 个"]
        if idx:
            r.add("INFO", "T2", "sitemap 是索引型，子 sitemap 需另外抽查", detail)
        elif urls and last < urls:
            r.add("WARN", "T2", f"{urls - last} 个 URL 没有 lastmod", detail +
                  ["lastmod 是内容新鲜度信号，配合 IndexNow 能加快更新被发现"])
        elif urls:
            r.add("PASS", "T2", f"{urls} 个 URL 都有 lastmod", detail)
        else:
            r.add("WARN", "T2", "sitemap 里没有 <loc>", detail)

    # T3 语意 HTML 与 ARIA（首页抽样）
    home, err = fetch(base)
    if err:
        r.add("WARN", "T3", f"抓不到首页：{err}", [base])
    else:
        aria = len(re.findall(r"\saria-[a-z]+=", home, re.I))
        roles = len(re.findall(r"\srole=", home, re.I))
        sem = [tag for tag in ("<main", "<nav", "<article", "<header", "<footer")
               if re.search(tag, home, re.I)]
        detail = [f"aria-* 属性 {aria} 个，role= {roles} 个",
                  f"语意标签: {'、'.join(sem) if sem else '一个都没有'}"]
        if not sem:
            r.add("FAIL", "T3", "首页没有任何语意标签（main/nav/article…）",
                  detail + ["OpenAI 明确指出 ChatGPT Atlas 用 ARIA 标签理解页面结构与交互元素"])
        elif aria + roles < 5:
            r.add("WARN", "T3", f"语意标签有，但 ARIA 标注很少（{aria + roles} 处）", detail)
        else:
            r.add("PASS", "T3", f"语意标签与 ARIA 标注齐（{len(sem)} 类 / {aria + roles} 处）", detail)

    # T5 渲染可见性：主要内容是否在初始 HTML 里
    if not err:
        text = visible_text(home)
        # 用总可见字符判，不能只数中文——英文站中文字数本来就是 0，那不叫前端渲染
        chars = len(re.sub(r"\s+", "", text))
        han = len(re.findall(r"[一-鿿]", text))
        scripts = len(re.findall(r"<script", home, re.I))
        detail = [f"初始 HTML 可见文本 {chars} 字符（其中中文 {han}），script 标签 {scripts} 个"]
        if chars < 500 and scripts > 5:
            r.add("FAIL", "T5", f"初始 HTML 几乎没有内容（{chars} 字符），疑似前端渲染",
                  detail + ["官方一再提醒 client-side rendering 有可见性限制：",
                            "爬虫拿到的是空壳，AI 检索更不会执行 JS"])
        elif chars < 500:
            r.add("WARN", "T5", f"初始 HTML 可见内容偏少（{chars} 字符）", detail)
        else:
            r.add("PASS", "T5", f"主要内容在初始 HTML 里（{chars} 字符）", detail)

    # T4 llms.txt：官方列为不需要做
    llms, err = fetch(f"{base}/llms.txt")
    if err:
        r.add("PASS", "T4", "没有 llms.txt（正确——官方已把它列为不需要做的事）",
              ["Google 2026 生成式 AI 优化指南把新建 AI text files 纳入迷思查核范围"])
    else:
        r.add("INFO", "T4", f"存在 llms.txt（{len(llms)} 字节）",
              ["官方明确列为不需要：对 Google Search 无正式作用，其他平台也缺乏主流采纳。",
               "留着无害，但不要当成 GEO 手段投入维护"])


def check_j(vault: str, site_base: str = "") -> int:
    r = Report()
    r.section("J · 站点级（跨文章 / 线上）")
    arts = []
    root = os.path.join(vault, "03-文章")
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.endswith(".md"):
                p = os.path.join(dirpath, f)
                try:
                    fm, body = parse_frontmatter(open(p, encoding="utf-8").read())
                except OSError:
                    continue
                main, seo = split_seo_section(body)
                arts.append((p, fm, parse_seo_fields(seo)))

    r.add("INFO", "—", f"扫到 {len(arts)} 篇文章（{root}）", [])

    # J4 title / description 全站唯一
    seen: dict[str, list[str]] = {}
    for p, fm, fields in arts:
        mt = first_line(seo_get(fields, "MetaTitle", "Meta Title")[1]) or (fm.get("title") or "")
        if mt:
            seen.setdefault(mt, []).append(os.path.basename(p))
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    if dup:
        r.add("FAIL", "J4", f"{len(dup)} 个 Meta Title 重复",
              [f"「{k[:34]}」→ {'、'.join(v)}" for k, v in list(dup.items())[:5]])
    else:
        r.add("PASS", "J4", f"{len(seen)} 个 Meta Title 全站唯一", [])

    # J2 语言矩阵
    by_id: dict[str, set[str]] = {}
    for p, fm, _ in arts:
        aid = (fm.get("article_id") or "").strip()
        if aid:
            by_id.setdefault(aid, set()).add((fm.get("lang") or "?").strip())
    langs = ("zh-Hant", "zh-Hans", "en", "ja", "ko", "vi", "th")
    gaps = {aid: [l for l in langs if l not in got] for aid, got in by_id.items()}
    gaps = {k: v for k, v in gaps.items() if v}
    if gaps:
        r.add("WARN", "J2", f"{len(gaps)} 篇未出齐 7 语言（hreflang 只能覆盖已存在的版本）",
              [f"{aid}: 缺 {'、'.join(v)}" for aid, v in list(gaps.items())[:6]])
    else:
        r.add("PASS", "J2", "所有文章 7 语言齐全", [])

    # J5 URL 结构（仅已回填的）
    urls = [(os.path.basename(p), fm.get("url") or "") for p, fm, _ in arts if (fm.get("url") or "").strip()]
    bad = []
    for name, u in urls:
        if re.search(r"[A-Z]", u):
            bad.append(f"{name}: 含大写 {u}")
        elif "?" in u or "&" in u:
            bad.append(f"{name}: 含查询参数 {u}")
    if not urls:
        r.add("SKIP", "J5", "没有已回填 url 的文章，跳过 URL 结构检查", [])
    elif bad:
        r.add("FAIL", "J5", f"{len(bad)} 个 URL 结构有问题", bad[:5])
    else:
        r.add("PASS", "J5", f"{len(urls)} 个 URL 结构合规", [])

    # J3 列表页可爬分页 —— 已确诊的收录瓶颈根因
    if not SITE_LIST_PAGES:
        r.add("MANUAL", "J3", "未配置列表页 URL，无法自动检查",
              ["把文章列表页 URL 填进脚本顶部的 SITE_LIST_PAGES",
               "这是已确诊的收录瓶颈根因，优先级最高"])
    else:
        for page in SITE_LIST_PAGES:
            html, err = fetch(page)
            if err:
                r.add("WARN", "J3", f"抓不到列表页：{err}", [f"URL: {page}"])
                continue
            hrefs = re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', html, re.I)
            pager = sorted({h for h in hrefs
                            if re.search(r"[?&]page[=/]|/page/\d+|[?&]paged?=\d+", h, re.I)})
            detail = [f"URL: {page}", f"链接 {len(hrefs)} 个，其中分页链接 {len(pager)} 个"]
            if pager:
                r.add("PASS", "J3", f"列表页有 {len(pager)} 个可爬分页链接",
                      detail + [f"例: {'、'.join(pager[:3])}"])
            else:
                r.add("FAIL", "J3", "列表页没有可爬的分页链接（第一页之后的文章爬不到）",
                      detail + ["这是孤儿页的直接成因"])

    # 仍需人看的：产品判断，不是技术检测
    r.add("MANUAL", "J6", "首屏是否有侵入式弹窗（算不算侵入是产品判断，脚本不判）", [])

    check_tech(r, site_base)
    r.dump()
    print()
    print("J1 / J7 / J8 已移到单篇在线检查（发布后带 url 跑那篇即可），不在本模式重复。")
    c = r.counts()
    print(f"机检结果：PASS {c.get('PASS', 0)}  FAIL {c.get('FAIL', 0)}  WARN {c.get('WARN', 0)}")
    return 1 if c.get("FAIL", 0) else 0


# ────────────────────────── 人工项答案 ──────────────────────────

def answers_path(vault: str, article_id: str) -> str:
    return os.path.join(vault, "06-工作区", "GEO自检", f"{article_id}.md")


def write_template(path: str, article_id: str, needed: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [f"# GEO 人工项结论 — {article_id}", "",
             "每项写一句你的判断，**不要留空、不要写 ok**（少于 "
             f"{MIN_ANSWER_CHARS} 个字符视为未回答）。", ""]
    for k, q in needed.items():
        lines += [f"## {k}", f"> {q}", "", f"- {k}: ", ""]
    open(path, "w", encoding="utf-8").write("\n".join(lines))


def read_answers(path: str) -> dict[str, str]:
    if not os.path.isfile(path):
        return {}
    out = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^\s*[-*]?\s*([A-J]\d+)\s*[：:]\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


# ────────────────────────── main ──────────────────────────

def check_article(path: str, vault: str, init: bool, use_manual: bool) -> int:
    vault = resolve_vault(vault, path)
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        print(f"读不到文件：{e}")
        return 2

    fm, body = parse_frontmatter(text)
    main, seo = split_seo_section(body)
    fields = parse_seo_fields(seo)
    article_id = (fm.get("article_id") or "").strip()

    r = Report()
    print(f"检查对象：{path}")
    print(f"article_id={article_id or '（无）'}  lang={fm.get('lang', '?')}  "
          f"primary_keyword={fm.get('primary_keyword', '（无）')}")
    print(f"正文 {han_count(main)} 中文字，上稿节 {len(fields)} 个字段")

    url = (fm.get("url") or "").strip()
    check_a(r, fm, main, seo, fields, vault)
    check_d(r, fm, main, vault, article_id)
    faq_count = check_e(r, main, fields, url)
    if url:
        check_online(r, url, faq_count)

    # 人工项对账：MANUAL_ITEMS 里的固定项 + 条件触发的项（如 D9 未检出边界表述）
    needed: dict[str, str] = {}
    for verdict, item, summary, _ in r.rows:
        if verdict == "MANUAL":
            needed[item] = MANUAL_ITEMS.get(item, summary)
    apath = answers_path(vault, article_id or "UNKNOWN")
    if init:
        # 2026-09-18：--init 不再覆盖已有答案。audit_d.py 的 verify 会先写 D1/D3/D4/D8/D9/D10/D15，
        # 再跑 --init 曾把它们清成空模板。现在只补缺的项，已答的原样保留。
        existing = read_answers(apath) if os.path.isfile(apath) else {}
        answered_keys = {k for k, v in existing.items() if len(v.strip()) >= MIN_ANSWER_CHARS}
        todo = {k: v for k, v in needed.items() if k not in answered_keys}
        if os.path.isfile(apath) and answered_keys:
            if todo:
                with open(apath, "a", encoding="utf-8") as fh:
                    for k, q in todo.items():
                        fh.write(f"\n## {k}\n> {q}\n\n- {k}: \n")
            r.dump()
            print(f"\n答案文件已存在，保留 {len(answered_keys)} 项已答；追加 {len(todo)} 项待答：{apath}")
            return 0
        write_template(apath, article_id or "UNKNOWN", needed)
        r.dump()
        print(f"\n已生成人工项模板：{apath}")
        print(f"填完 {len(needed)} 项后重新跑本脚本。")
        return 0

    answered = read_answers(apath)
    r.section("人工项对账")
    if not use_manual:
        r.add("INFO", "—", f"--no-manual：{len(needed)} 个人工项降级为提示，未纳入判定", [])
    else:
        missing = [k for k in needed if len(answered.get(k, "").strip()) < MIN_ANSWER_CHARS]
        r.add("INFO", "—", f"答案文件：{apath}", [])
        for k in needed:
            a = answered.get(k, "")
            if len(a.strip()) >= MIN_ANSWER_CHARS:
                r.add("PASS", k, f"已书面确认：{a[:52]}", [])
        if missing:
            r.add("FAIL", "—", f"{len(missing)} 个人工项没有书面结论：{'、'.join(missing)}",
                  [f"跑 --init 生成模板：python3 {os.path.basename(__file__)} <文章> --init"])

    r.dump()
    c = r.counts()
    print()
    print(f"PASS {c.get('PASS', 0)}  FAIL {c.get('FAIL', 0)}  WARN {c.get('WARN', 0)}  "
          f"MANUAL {c.get('MANUAL', 0)}  SKIP {c.get('SKIP', 0)}")

    if c.get("FAIL", 0):
        print("不通过。FAIL 项逐条修掉再跑；WARN 是提示，自己判断要不要改。")
        return 1
    print("通过。")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:]]
    vault = VAULT
    if "--vault" in args:
        i = args.index("--vault")
        try:
            vault = os.path.expanduser(args[i + 1])
            del args[i:i + 2]
        except IndexError:
            print("--vault 后面要跟路径")
            return 2
    init = "--init" in args
    if init:
        args.remove("--init")
    use_manual = "--no-manual" not in args
    if not use_manual:
        args.remove("--no-manual")
    site_base = ""
    if "--site-base" in args:
        i = args.index("--site-base")
        try:
            site_base = args[i + 1]
            del args[i:i + 2]
        except IndexError:
            print("--site-base 后面要跟站点根 URL")
            return 2
    site = "--site" in args
    if site:
        args.remove("--site")

    if not os.path.isdir(vault):
        print(f"Vault 不存在：{vault}")
        return 2
    if site:
        return check_j(vault, site_base)
    if len(args) != 1:
        print(__doc__)
        return 2
    return check_article(args[0], vault, init, use_manual)


if __name__ == "__main__":
    sys.exit(main())
