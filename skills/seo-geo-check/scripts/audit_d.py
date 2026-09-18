#!/usr/bin/env python3
"""D 区（GEO 要素）审核：机检 + 独立评审 + 原文回验。

两个阶段，中间必须插一次独立评审 subagent：

    audit_d.py <文章.md> --stage scan      # 机检 D 区，写出评审任务文件
    ... spawn 评审 subagent，它填写评审结果文件 ...
    audit_d.py <文章.md> --stage verify    # 回验证据 → 最终判定 → 写答案文件

设计约束（改代码前先读，这几条是这个脚本存在的理由）：

  1. **不复制 check_geo.py 的逻辑，用 importlib 加载它复用。** D 区机检那部分
     它已经实现了，抄一份必然漂移。本脚本只新增 D13、评审任务与回验。
  2. **不修改 check_geo.py。** 一行都不改。
  3. **回验是硬判定。** 证据核不上 → 判定作废，不是警告。字面比对不可靠的地方
     （D7）走「机检未命中转评审」，不硬判失败。
  4. **本脚本只判 D 区。** A/E/J 归 M6 的 check_geo.py。D6 归 M3 闸 1.5，这里只引用不重判。

退出码：0 通过；1 不通过；2 用法错误 / 文件读不到。
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys

CHECK_GEO = os.path.expanduser(
    "~/.claude/skills/seo-writing-openx/scripts/check_geo.py"
)

# 固定要评审的语义项 / 机检未命中才转评审的项
REVIEW_ITEMS = ("D3", "D8", "D10")
COND_REVIEW = ("D1", "D4", "D7", "D9", "D15", "D16", "D18", "D19")
# D6 由 M3 闸 1.5 负责，本脚本不重判
DELEGATED = ("D6",)
# D2 已并入 D1（2026-09-03）：内链设计本来就跳过速答块，单列一项没有拦截价值
MERGED_INTO_D1 = ("D2",)
# D5 已删除（2026-09-03）：阈值无依据且可被无关数字凑满
REMOVED = ("D5",)

MIN_ANSWER_CHARS = 8
# D12：带序号前缀的内容 H2 占比上限。序号标题不是错，通篇都用才是问题。
NUMBERED_H2_MAX = 0.5
# D14：区域性参照词。命中即不合格——一篇文章有 7 个语言版本，
# 只有单一地区读者才有参照的例子，翻过去等于白写。穷举不了，评审方需补遗漏。
REGIONAL_REFS = (
    "台北", "台中", "台南", "高雄", "新竹", "桃園", "台灣", "台湾", "新台幣", "新台币",
    "中信銀行", "國泰世華", "玉山銀行", "永豐銀行", "郵局", "健保", "統一發票",
    "微信支付", "支付寶", "支付宝", "餘額寶", "余额宝", "身分證", "身份证",
)
# D13：权威来源的域名特征。不在其中的会 WARN——不是不能用，是要意识到死链维护成本。
AUTHORITATIVE_HINTS = (
    "docs.", "developer", "github.com", "gitlab.com", "linuxfoundation.org",
    "ietf.org", "w3.org", "arxiv.org", "schema.org", "google.com", "reuters.com",
    "bloomberg.com", "ft.com", "wsj.com", "coindesk.com", "sec.gov",
)
MIN_EVIDENCE_CHARS = 5
# D3 的证据还必须落在它声称的那一节首段里
NEEDS_LOCATION = ("D3",)

REVIEW_QUESTIONS = {
    "D3": "找出**哪几节「该先给结论却没给」**（不要回答「是否每节都给了」）。"
          "先判断每节属哪种问题类型：定义型／比较型／风险型／Yes-No 型该首句就给结论；"
          "**复杂案例型可以先立情境再给判断，不算违规**。"
          "对每个指认，交出该节名与该节首段的原句。",
    "D1": "先判断这篇 Answer Block 属哪种问题类型（定义／Yes-No／方法流程／比较／风险／时效），"
          "再**指出它缺了该型结构里的哪几段**（不要回答「结构是否完整」）。"
          "分型表见检查项定义。对每个指认，交出 Answer Block 里的原句作为证据。",
    "D16": "挑出**哪些涉及判断／风险／选择的主张缺了反面视角**（不要回答「是否都有反方」）。"
           "反面视角指：反对理由、专家不同意见、什么情况下这个结论不成立。"
           "对确实给了反面的主张，交出那句反方原文。",
    "D15": "判断 CTA 是否抢在主要答案之前、YMYL 主题是否用了风险恐吓或强迫式推销"
           "（不要回答「CTA 是否恰当」）。交出那句 CTA 原文作为证据；若全文无 CTA 写明无。",
    "D4": "指出**哪几题 FAQ 在正文里找不到回答它的段落、或答案加了正文没有的主张**（不要回答「是否都有对应」）。",
    "D18": "指出**哪几处绝对化或排他性表述（沒有一篇／全部／一定／不存在／不成立…）没有对应证据、或结论范围超出了它引用的来源**（不要回答「表述是否都有证据」）。",
    "D19": "对正文里的案例，指出**缺了哪几项：判定规则是否写在标注之前；确认条件、失效条件、放弃条件是否各自写明；标注有没有用到当时还不可知的信息（事后信息）；正文承诺的范围与案例实际示范的范围是否一致**（不要回答「案例是否完整」）。"
          "FAQ 只该补正文没答的延伸问题；重复正文关键答案的题要挑出来。"
          "对每个指认，用 / 分隔交出两条证据：「FAQ 里那句答案」与「正文中对应的原句」。",
    "D8": "挑出**哪些重要主张附近没有来源**（不要回答「是否都有」）。"
          "**不要按外链数量判断——数量不是标准**，官方明确反对每篇机械插 n 个链接。"
          "看的是需要外部证明的主张，在该主张附近能不能就地核实。"
          "对确实有就近来源的主张，交出那句主张原文。",
    "D10": "挑出**哪些**首次出现的专有名词没有给定义（不要回答「是否都给了」）。"
           "对确实有定义的词，交出它的定义句原文。",
    "D7": "脚本按字面比对没在正文找到这些差异化内容。逐条说明它写在正文哪一段，"
          "并交出那一段的原句（换了说法属正常）。",
    "D9": "全文没有检出承认不确定的表述。判断是否存在被抹平的分歧或口径差异；"
          "若确实没有不确定处，说明依据并交出一句支持这个判断的原文。",
}


_CG = None


def load_check_geo():
    global _CG
    """加载 check_geo.py 复用它的解析与 check_d（不修改、不复制）。"""
    if not os.path.isfile(CHECK_GEO):
        print(f"找不到 check_geo.py：{CHECK_GEO}")
        print("本脚本复用它的解析逻辑，请确认 seo-writing-openx skill 完整。")
        sys.exit(2)
    spec = importlib.util.spec_from_file_location("check_geo", CHECK_GEO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _CG = mod
    if not getattr(mod, "ZH_NORM_AVAILABLE", False):
        print("⚠️ opencc 未安装，繁简未归一化。繁中稿的 D4 重合率与证据回验会误判。")
        print("   装上：pip3 install opencc-python-reimplemented")
    return mod


# ────────────────────── D13（check_geo.py 里没有，本脚本新增）──────────────────────

SRC_HEADING = r"(資料來源|资料来源|參考資料|参考资料|參考文獻|参考文献)"


def check_d13(cg, r, main: str) -> None:
    """文末资料来源逐条可点击。宽松口径：没有这一节则跳过，不强制存在。"""
    m = re.search(rf"^##\s+.*{SRC_HEADING}.*$", main, re.M)  # 只认 H2 标题行，正文里出现「資料來源」四字不算节（2026-09-18）
    if not m:
        r.add("SKIP", "D13", "文末没有资料来源节（宽松口径不强制存在）",
              ["若列了来源，每条都必须可点击"])
        return
    tail = main[m.end():]
    # 到下一个 H2 / 分隔线 / 免责声明为止
    stop = re.search(r"^(##\s|---\s*$|\*\*免責|\*\*免责)", tail, re.M)
    block = tail[:stop.start()] if stop else tail
    items = [l.strip() for l in block.splitlines() if re.match(r"^\s*[-*]\s*\S", l)]
    if not items:
        r.add("WARN", "D13", "有资料来源节但没有列表条目",
              [f"节标题: {m.group(0).strip()[:40]}"])
        return
    linked, plain = [], []
    for it in items:
        if re.search(r"\[[^\]]+\]\([^)]+\)|https?://\S+", it):
            linked.append(it)
        else:
            plain.append(it)
    detail = [f"条目 {len(items)} 条，可点击 {len(linked)} 条，纯文本 {len(plain)} 条"]
    detail += [f"纯文本: {p[:50]}" for p in plain[:3]]
    if plain:
        r.add("FAIL", "D13", f"{len(plain)} 条资料来源不可点击", detail)
    else:
        r.add("PASS", "D13", f"{len(items)} 条资料来源全部可点击", detail)


FAQ_OVERLAP_MIN = 0.10   # 2026-09-18 反转：FAQ 从正文提取，答案与正文重合率低于此值才可疑
# D1：六型 Answer Block 的字数并集（定义型 60–120 … 方法/风险型 100–180）
ANSWER_BLOCK_RANGE = (50, 180)
# D1：出现这些时效词就必须同时标出日期，否则旧来源会造成旧答案
TIMELY_WORDS = ("目前", "現在", "现在", "最新", "截至", "當前", "当前", "如今", "今年", "至今")
# D8：只有含量化主张或绝对化断言的段落才算「需要外部证明」，
# 否则任何带数字的段落都进候选，评审方要在噪音里找真问题
CLAIM_SIGNALS = (
    "%", "％", "美元", "美金", "倍", "萬", "万", "億", "亿", "筆", "笔",
    "最", "唯一", "第一", "所有", "全部", "從不", "从不", "永遠", "永远",
    "必然", "一定", "零", "免費", "免费",
)
# D8：段落里有这些词才算就近给了来源出处
SOURCE_HINTS = ("官方", "公告", "文件", "文檔", "文档", "白皮書", "白皮书", "規範", "规范",
                "倉庫", "仓库", "原文", "來源", "来源", "根據", "根据", "實測", "实测")
# D16：反方资料／不同意见的表述。只给单边论证的内容，AI 会当成立场性材料。
COUNTER_MARKS = (
    "也有人認為", "也有人认为", "反對的看法", "反对的看法", "不同意見", "不同意见",
    "批評者", "批评者", "反面來看", "反面来看", "另一種說法", "另一种说法",
    "質疑", "质疑", "爭議", "争议", "反方", "有人不同意", "什麼情況下不成立",
    "什么情况下不成立", "不適用於", "不适用于", "例外是", "但如果", "除非",
)
# D17：来源日期。旧来源会造成旧答案，协议／费率／法规这类内容尤其致命。
DATE_NEAR = r"\d{4}\s*[-/年]|\d{4}\s*(?:年|/)\s*\d{1,2}|V\d+(?:\.\d+)?|v\d+(?:\.\d+)?"
# D12：高风险判断词。把这类判断整条塞进条列，会丢掉限制语境——
# 读者（和 AI）摘到那一条时看不到「什么情况下才成立」。
RISK_WORDS = ("风险", "亏损", "爆仓", "归零", "损失", "被骗", "诈骗", "违规",
              "违法", "罚款", "税务", "杠杆", "清算", "本金", "血本")
# 同一条里有这些词才算带了限制条件
QUALIFIER_WORDS = ("除非", "前提", "仅在", "只在", "取决于", "视情况", "如果", "若",
                   "情况下", "视你", "因人而异", "不一定", "视平台", "以官方")
# D9 第二件事：模糊限定词。承认不确定针对的是数据与口径，
# 通篇「可能／也许」等于没观点——同样不可引用。
HEDGE_WORDS = ("可能", "也许", "或许", "大概", "应该是", "不一定", "视情况",
               "难说", "不好说", "说不准", "有待观察", "不确定")
HEDGE_PER_1K_MAX = 8.0   # 每千中文字。无外部依据，首版经验值，跑几篇后按实际调
# D11 第一件事：一段塞多个概念的信号——同一段里多个并列推进词
MULTI_TOPIC_MARKS = ("另外", "此外", "同时", "再者", "还有一点", "顺带", "顺便说")
# D11 第二件事：限制条件被拆到下一段的信号——段落以限制词开头
ORPHAN_QUALIFIER = ("除非", "但如果", "例外是", "前提是", "不过前提", "有个前提")
# D15：CTA 类表述。出现在第一个内容 H2 之前 = 抢在答案前面
CTA_WORDS = ("立即註冊", "立即注册", "馬上註冊", "马上注册", "點擊", "点击", "開戶", "开户",
             "免費領取", "免费领取", "限時", "限时", "聯繫我們", "联系我们", "加入我們",
             "加入我们", "立即下載", "立即下载", "趕快", "赶快", "不要錯過", "不要错过")


def check_d1_typed(cg, r, main: str) -> None:
    """D1 的分型部分：字数落在六型并集内 + 时效词必须带日期。
    「属哪一型、缺了该型哪几段」是语义判断，交评审。"""
    blocks = cg.blocks_after_h1(main)
    ab = blocks[0] if blocks else ""
    if not ab.startswith(">"):
        r.add("SKIP", "D1", "没有 Answer Block，分型检查跳过", [])
        return
    lines = [re.sub(r"^>\s?", "", l) for l in ab.splitlines()]
    body = " ".join(l for l in lines if l.strip() and not re.fullmatch(r"\*\*.+\*\*", l.strip()))
    n = cg.han_count(body)
    lo, hi = ANSWER_BLOCK_RANGE
    timely = [w for w in TIMELY_WORDS if w in body]
    has_date = bool(re.search(r"\d{4}\s*年|\d{4}-\d{2}|\d{4}/\d{1,2}", body))
    detail = [f"字数 {n} 中文字 / 六型并集 {lo}–{hi}",
              f"时效词: {'、'.join(timely) if timely else '无'}；日期: {'有' if has_date else '无'}"]
    if not (lo <= n <= hi):
        r.add("FAIL", "D1", f"Answer Block 字数 {n} 超出 {lo}–{hi}",
              detail + ["定义型 60–120、Yes/No 型 50–100、方法与风险型 100–180，见分型表"])
    elif timely and not has_date:
        r.add("FAIL", "D1", "用了时效词却没标日期",
              detail + ["时效型 Answer Block 不标日期最危险——旧来源会造成旧答案"])
    else:
        r.add("PASS", "D1", f"字数与时效标注合规（{n} 字）", detail)


def check_d8_proximity(cg, r, main: str) -> None:
    """D8 的机检辅助：带数字的段落有没有就近给出处。只列候选，不判失败。"""
    m = re.search(r"^##\s+.*(?:常見問題|常见问题|FAQ|資料來源|资料来源).*$", main, re.M)
    body = main[:m.start()] if m else main
    naked = []
    for para in [x.strip() for x in body.split("\n\n")]:
        if para.startswith(("|", "#", ">")) or cg.han_count(para) < 20:
            continue
        if not re.search(r"\d", para):
            continue
        if not any(s in para for s in CLAIM_SIGNALS):
            continue
        if re.search(r"https?://", para) or any(h in para for h in SOURCE_HINTS):
            continue
        naked.append(para)
    detail = [f"带量化主张但段内无出处的段落 {len(naked)} 个（候选，非判定）",
              "注：候选里会混入作者第一手观察（那类不需外链），评审方自行排除"]
    detail += [f"例: {p[:52]}…" for p in naked[:3]]
    r.add("INFO", "D8", f"就近举证候选 {len(naked)} 处，交评审判断哪些是需要证明的主张", detail)


def check_d12_table_summary(cg, r, main: str) -> None:
    """D12 的另一面：表格前后要有摘要句，裸表格被摘走时不带语境。"""
    lines = main.splitlines()
    blocks, cur = [], None
    for i, l in enumerate(lines):
        if re.match(r"^\s*\|.+\|\s*$", l):
            if cur is None:
                cur = [i, i]
            else:
                cur[1] = i
        elif cur is not None:
            blocks.append(tuple(cur)); cur = None
    if cur is not None:
        blocks.append(tuple(cur))
    if not blocks:
        r.add("SKIP", "D12", "没有表格，跳过表格摘要检查", [])
        return

    def prose_near(idx: int, step: int) -> bool:
        j = idx + step
        while 0 <= j < len(lines):
            s = lines[j].strip()
            if not s:
                j += step; continue
            return not s.startswith(("|", "#", "-", "*", ">", "---")) and cg.han_count(s) >= 8
        return False

    bad = [b for b in blocks if not (prose_near(b[0], -1) and prose_near(b[1], 1))]
    detail = [f"表格 {len(blocks)} 张，前后缺摘要句的 {len(bad)} 张"]
    detail += [f"行 {b[0]+1}–{b[1]+1}" for b in bad[:3]]
    if bad:
        r.add("WARN", "D12", f"{len(bad)} 张表格前后没有摘要句", detail +
              ["裸表格被摘走时不带语境，前后各补一句说明它在比什么"])
    else:
        r.add("PASS", "D12", f"{len(blocks)} 张表格前后都有摘要", detail)


def check_d9_hedge(cg, r, main: str) -> None:
    """D9 第二件事：核心判断要明确，不许拿「不确定」当挡箭牌。

    D9 的第一件事（有没有承认边界）由 check_geo.py 查。这里查反面：
    通篇模糊限定等于没观点，AI 同样不会引用。
    """
    norm_fn = _CG.zh_norm if _CG is not None else (lambda x: x)
    s = norm_fn(main)
    total = cg.han_count(s)
    if total < 300:
        r.add("SKIP", "D9", "正文太短，跳过模糊限定密度检查", [])
        return
    hits = [w for w in HEDGE_WORDS for _ in range(s.count(w))]
    per1k = len(hits) / total * 1000
    top = sorted({w: s.count(w) for w in HEDGE_WORDS if s.count(w)}.items(),
                 key=lambda x: -x[1])[:5]
    detail = [f"模糊限定词 {len(hits)} 处 / {total} 中文字 = {per1k:.1f} 每千字"
              f"（上限 {HEDGE_PER_1K_MAX}，经验值无外部依据）",
              f"分布: {'、'.join(f'{w}×{c}' for w, c in top) if top else '无'}"]
    if per1k > HEDGE_PER_1K_MAX:
        r.add("WARN", "D9", f"模糊限定密度 {per1k:.1f}/千字，核心判断可能不明确",
              detail + ["承认不确定只该针对具体数据与口径；通篇「可能／也许」等于没观点，"
                        "AI 同样不会引用"])
    else:
        r.add("PASS", "D9", f"模糊限定密度 {per1k:.1f}/千字，判断明确", detail)


def check_d11_extra(cg, r, main: str) -> None:
    """D11 的另两件事：一段一概念、条件与主张不拆段。

    两件都只能做弱信号——「是不是同一个概念」要读懂语义，机检给候选，评审判。
    """
    norm_fn = _CG.zh_norm if _CG is not None else (lambda x: x)
    paras = [p.strip() for p in main.split("\n\n")
             if cg.han_count(p) >= 30 and not p.lstrip().startswith(("|", "#", ">"))]
    multi = [p for p in paras
             if sum(norm_fn(p).count(w) for w in MULTI_TOPIC_MARKS) >= 2]
    orphan = [p for p in paras if norm_fn(p).lstrip().startswith(ORPHAN_QUALIFIER)]
    detail = [f"实质段落 {len(paras)} 个",
              f"含 2 个以上并列推进词（疑似一段多概念）: {len(multi)} 个",
              f"以限制词开头（疑似条件被拆到下一段）: {len(orphan)} 个"]
    detail += [f"多概念候选: {p[:46]}…" for p in multi[:2]]
    detail += [f"孤立限制候选: {p[:46]}…" for p in orphan[:2]]
    if multi or orphan:
        r.add("WARN", "D11", f"{len(multi) + len(orphan)} 个段落疑似违反一段一概念",
              detail + ["摘录以段为单位：一段两个概念，摘出来两边都不完整；",
                        "限制条件被拆到下一段，摘到主张那段就成了绝对化断言"])
    else:
        r.add("PASS", "D11", "未检出一段多概念或条件拆段", detail)


def check_d12_list_risk(cg, r, main: str) -> None:
    """D12 第三件事：条列不承载高风险判断的全部内容。

    风险判断塞进一个 bullet 里，摘出去就只剩结论、没有适用条件——
    这在 YMYL 内容上是实际危害，不只是格式问题。
    """
    norm_fn = _CG.zh_norm if _CG is not None else (lambda x: x)
    bad = []
    for line in main.splitlines():
        if not re.match(r"^\s*(?:[-*]\s+|\d+[.、)]\s*)\S", line):   # 「**Q1：」这类粗体问句不是条列（2026-09-18）
            continue
        s = norm_fn(line)
        if cg.han_count(s) < 10:
            continue
        if any(w in s for w in RISK_WORDS) and not any(q in s for q in QUALIFIER_WORDS):
            bad.append(line.strip())
    detail = [f"含高风险判断但无限制条件的条列项 {len(bad)} 条"]
    detail += [f"例: {b[:56]}…" for b in bad[:3]]
    if bad:
        r.add("WARN", "D12", f"{len(bad)} 条条列把风险判断写成了无条件结论",
              detail + ["摘出去就只剩结论、没有适用条件。把限制写进同一条，"
                        "或者从条列改回段落——高风险判断不适合压成一行"])
    else:
        r.add("PASS", "D12", "条列里没有无限制条件的风险判断", detail)


def check_d16_counter(cg, r, main: str) -> None:
    """D16：有没有给出反面资料或不同意见。扫不到才转评审。"""
    hits = sorted({m for m in COUNTER_MARKS if m in main})
    detail = [f"反方表述命中 {len(hits)} 种：{'、'.join(hits[:6]) if hits else '无'}"]
    if hits:
        r.add("PASS", "D16", f"有 {len(hits)} 种反方／例外表述", detail +
              ["注：命中词表只说明「写了反面」，是否覆盖了真正的争议点由评审判"])
    else:
        r.add("WARN", "D16", "全文没有反面资料或不同意见的表述，转评审",
              detail + ["只给单边论证，AI 引用时会当成立场性材料而非可信来源",
                        "证据帐本要求每个重要主张标注「是否有反方资料」"])


def check_d17_source_date(cg, r, main: str) -> None:
    """D17：引用来源要标日期／版本。逐个外链看它所在段落有没有日期。"""
    m = re.search(r"^##\s+.*(?:常見問題|常见问题|FAQ).*$", main, re.M)
    body = main[:m.start()] if m else main
    paras = [x.strip() for x in body.split("\n\n") if "http" in x]
    if not paras:
        # 不是「没什么可查」，而是「正文里一个引用都没有」——这本身是 D8 的信号
        all_links = len(re.findall(r"https?://", main))
        r.add("WARN", "D17", "正文里没有任何引用（来源都在文末或没有）",
              [f"全文外链 {all_links} 处，但 FAQ 之前的正文段落里 0 处",
               "来源全堆文末时 D13 可能通过、D8 却不合格——读者读到主张时无从核实",
               "就近举证由 D8 判，这里只是把信号传出来"])
        return
    undated = [p for p in paras if not re.search(DATE_NEAR, p)]
    detail = [f"含外链的段落 {len(paras)} 个，其中 {len(undated)} 个附近没有日期或版本号"]
    detail += [f"例: {p[:52]}…" for p in undated[:3]]
    if undated:
        r.add("WARN", "D17", f"{len(undated)} 处引用没标来源日期／版本",
              detail + ["旧来源会造成旧答案；协议、费率、法规这类内容尤其致命",
                        "时效敏感的主张还要写最后核对时间"])
    else:
        r.add("PASS", "D17", f"{len(paras)} 处引用都带日期或版本", detail)


def check_d15_cta(cg, r, main: str) -> None:
    """D15：CTA 不该抢在主要答案之前。"""
    m = re.search(r"^##\s+", main, re.M)
    head = main[:m.start()] if m else main
    early = sorted({w for w in CTA_WORDS if w in head})
    all_hit = sorted({w for w in CTA_WORDS if w in main})
    detail = [f"全文 CTA 表述: {'、'.join(all_hit) if all_hit else '无'}",
              f"出现在第一个 H2 之前的: {'、'.join(early) if early else '无'}"]
    if early:
        r.add("FAIL", "D15", f"CTA 抢在主要答案之前（{'、'.join(early)}）",
              detail + ["转化设计与理解设计要分开：读者还没拿到答案就被推销，可信度直接受损"])
    elif all_hit:
        r.add("PASS", "D15", "CTA 都在主要答案之后", detail)
    else:
        r.add("SKIP", "D15", "全文没有 CTA 表述", detail)





def check_d4_faq_gap(cg, r, main: str) -> None:
    """D4 的另一面：FAQ 必须从正文提取并总结，每题都要能在正文找到回答它的段落。

    机检只做重合度粗筛（6 字窗口）：重合率过低的题疑似正文没有对应内容。
    语义上「正文到底答过没有」「答案有没有加新主张」交评审——换个说法总结正文是允许的，
    那种字面比对判不了。（2026-09-18 反转口径，原为「不许重复正文」）
    """
    secs = cg.section_bodies(main)
    faq = next((b for h, b in secs if re.search(r"常見問題|常见问题|FAQ", h)), None)
    if faq is None:
        r.add("SKIP", "D4", "没有 FAQ 节，跳过缺口检查", [])
        return
    m = re.search(r"^##\s+.*(?:常見問題|常见问题|FAQ).*$", main, re.M)
    body = norm(main[:m.start()]) if m else norm(main)
    qs = re.split(r"^\*\*Q\d*[：:.]?\s*.+?\*\*\s*$", faq, flags=re.M)[1:]
    if not qs:
        r.add("SKIP", "D4", "FAQ 节没有可识别的问答，跳过缺口检查", [])
        return
    n, sus = 6, []
    for i, ans in enumerate(qs, 1):
        s = norm(ans)
        if len(s) < n:
            continue
        grams = {s[j:j + n] for j in range(len(s) - n + 1)}
        hit = [g for g in grams if g in body]
        ratio = len(hit) / len(grams) if grams else 0
        if ratio < FAQ_OVERLAP_MIN:
            sus.append((i, ratio, ans.strip()[:44]))
    detail = [f"FAQ {len(qs)} 题，重合率下限 {FAQ_OVERLAP_MIN:.0%}（6 字窗口比对正文；FAQ 应从正文提取）"]
    detail += [f"Q{i} 与正文重合 {rt:.0%}：{txt}…" for i, rt, txt in sus[:4]]
    if sus:
        r.add("WARN", "D4", f"{len(sus)} 题与正文重合过低，疑似正文无对应段落，转评审确认", detail)
    else:
        r.add("PASS", "D4", f"{len(qs)} 题都与正文有重合，字面层面像是从正文提取", detail)


# ────────────────────── D18 / D19 / D20（2026-09-18，三轮外部复核后新增）──────────────────────
# 三轮复核抓到、而既有 D 区一条都没拦住的三类问题：
#   D18 差异化写过满（「沒有一篇」「不成立」「不存在」），结论超出来源范围；
#   D19 行情案例没有先写规则、缺确认/失效/放弃条件、标注用了事后信息、范围承诺与示范不一致；
#   D20 案例价位没有可复现的原始数据，或正文数字与数据对不上（OX-0032 的「首次收破」就错在这里）。
ABSOLUTE_MARKS = ("沒有一篇", "没有一篇", "沒有任何", "没有任何", "全部都", "一定會", "一定会", "必回補", "必回补",
                  "不可能", "從來沒有", "从来没有", "不存在了", "已不存在", "不成立", "所有人都", "任何人都",
                  "永遠", "永远", "絕對", "绝对", "唯一的", "只有一種", "只有一种")
CASE_MARKS = ("案例", "示例", "實例", "实例", "真實行情", "真实行情")
CASE_RULE_MARKS = {"規則": ("規則", "规则"), "確認條件": ("確認", "确认"), "失效條件": ("失效",),
                   "放棄條件": ("放棄", "放弃", "不做", "不進場", "不进场")}
PRICE_RE = r"(?<![\d.])\d{1,3}(?:,\d{3})+\.\d(?![\d])"


def check_d18_absolute(cg, r, main: str) -> None:
    """D18：绝对化／排他性表述。机检只列候选，是否有证据支撑由评审判。"""
    norm_fn = _CG.zh_norm if _CG is not None else (lambda x: x)
    hits = []
    for para in main.split("\n\n"):
        s = norm_fn(para)
        for w in ABSOLUTE_MARKS:
            if norm_fn(w) in s:
                hits.append((w, para.strip().replace("\n", " ")[:60]))
                break
    detail = [f"绝对化候选 {len(hits)} 处（词表粗筛，评审判其证据范围）"]
    detail += [f"「{w}」→ {t}…" for w, t in hits[:5]]
    if hits:
        r.add("WARN", "D18", f"{len(hits)} 处绝对化表述，转评审核其证据范围", detail)
    else:
        r.add("PASS", "D18", "未检出绝对化表述（词表穷举不了，评审仍需扫一遍）", detail)


def check_d19_case(cg, r, main: str) -> None:
    """D19：行情／操作案例的可执行性。有案例才查；四类要素词面缺哪类就提示，时间顺序交评审。"""
    has_img = bool(re.search(r"^!\[", main, re.M))
    has_case = any(m in main for m in CASE_MARKS)
    if not (has_img or has_case):
        r.add("SKIP", "D19", "正文没有案例或图，跳过案例可执行性检查", [])
        return
    missing = [k for k, ws in CASE_RULE_MARKS.items() if not any(w in main for w in ws)]
    detail = [f"案例要素词面：规则 / 确认 / 失效 / 放弃；缺 {len(missing)} 类" + (f"：{'、'.join(missing)}" if missing else "")]
    detail.append("规则是否先于标注、标注是否用了事后信息、承诺范围与示范范围是否一致 → 评审判")
    if missing:
        r.add("WARN", "D19", f"案例缺 {len(missing)} 类要素词面，转评审", detail)
    else:
        r.add("PASS", "D19", "案例四类要素词面齐备，时间顺序与范围一致性转评审", detail)


def check_d20_case_data(cg, r, main: str, vault: str, aid: str) -> None:
    """D20：行情案例可复现。正文带小数的千分位价位 ≥5 个即视为有行情案例，
    要求 06-工作区/导出/<article_id>/data/*.json 存在，且每个价位都能在 OHLC 里逐字找到。"""
    import glob, json
    prices = set(re.findall(PRICE_RE, main))
    if len(prices) < 5:
        r.add("SKIP", "D20", f"价位型数字 {len(prices)} 个（<5），视为无行情案例", [])
        return
    ddir = os.path.join(vault, "06-工作区", "导出", aid, "data")
    files = sorted(glob.glob(os.path.join(ddir, "*.json")))
    if not files:
        r.add("FAIL", "D20", f"正文含 {len(prices)} 个价位，但 {ddir} 下没有原始 JSON",
              ["用固定 startTime/endTime 抓取原始 K 线存进该目录，并附 README 写明请求参数"])
        return
    vals = set()
    for f in files:
        try:
            for b in json.load(open(f, encoding="utf-8")):
                for v in b[1:5]:
                    vals.add(f"{float(v):,.1f}")
        except Exception as e:  # noqa: BLE001
            r.add("WARN", "D20", f"读不了 {os.path.basename(f)}：{e}", [])
    # 推导值白名单：data/derived.txt 每行「数字 = 算式」，停损距离、目标距离这类算出来的数不在 OHLC 里
    derived = set()
    dpath = os.path.join(ddir, "derived.txt")
    if os.path.isfile(dpath):
        for line in open(dpath, encoding="utf-8"):
            m_ = re.match(r"\s*(\d{1,3}(?:,\d{3})+\.\d)\s*=", line)
            if m_:
                derived.add(m_.group(1))
    miss = sorted(p_ for p_ in prices if p_ not in vals and p_ not in derived)
    detail = [f"正文价位 {len(prices)} 个，原始数据文件 {len(files)} 个，OHLC 值 {len(vals)} 个，"
              f"derived.txt 白名单 {len(derived)} 个"]
    if miss:
        r.add("FAIL", "D20", f"{len(miss)} 个价位在原始数据里找不到", detail + [f"缺: {m}" for m in miss[:8]])
    else:
        r.add("PASS", "D20", f"{len(prices)} 个价位全部存在于原始数据", detail)


def check_d12_restraint(cg, r, main: str) -> None:
    """D12 的另一面：序号式标题不要每节都用。check_geo.py 只查「有没有表格/步骤」，
    这里查「结构化有没有过度」——两面合起来才是 D12 的完整口径。"""
    h2 = [h for h, _ in cg.section_bodies(main) if not re.search(SKIP_SEC, h)]
    if not h2:
        r.add("SKIP", "D12", "没有内容 H2，跳过序号克制检查", [])
        return
    numbered = [h for h in h2
                if re.match(r"^\s*(?:[一二三四五六七八九十]+\s*[、.．]|第[一二三四五六七八九十]+|\d+\s*[、.．])", h)]
    ratio = len(numbered) / len(h2)
    detail = [f"内容 H2 {len(h2)} 个，带序号前缀 {len(numbered)} 个（{ratio:.0%}），上限 {NUMBERED_H2_MAX:.0%}"]
    detail += [f"例: {h[:34]}" for h in numbered[:3]]
    if ratio > NUMBERED_H2_MAX:
        r.add("FAIL", "D12", f"序号式标题过度（{ratio:.0%} 的 H2 都带序号）",
              detail + ["能用散文讲明白的就别套编号，通篇编号会把文章写成填空题"])
    else:
        r.add("PASS", "D12", f"序号标题占比 {ratio:.0%}，未过度", detail)


def check_d13_authority(r, main: str) -> None:
    """D13 的另一面：只外链权威来源。小站链接后期失效会变成维护成本。"""
    domains = sorted(set(re.findall(r"https?://([^/\s)]+)", main)))
    if not domains:
        r.add("SKIP", "D13", "正文没有外链，跳过权威性检查", [])
        return
    weak = [d for d in domains
            if not any(k in d for k in AUTHORITATIVE_HINTS)
            and not re.search(r"\.(org|gov|edu)$", d)]
    detail = [f"外链域名 {len(domains)} 个，其中 {len(weak)} 个不在权威特征内"]
    detail += [f"待确认: {d}" for d in weak[:5]]
    if weak:
        r.add("WARN", "D13", f"{len(weak)} 个来源需确认权威性",
              detail + ["个人博客／小站后期失效要回头维护，能换官方来源就换"])
    else:
        r.add("PASS", "D13", f"{len(domains)} 个外链全部为权威来源", detail)


def check_d14(r, main: str) -> None:
    """D14 举例用国际通用参照。"""
    hits = []
    hay_raw = main
    main = _CG.zh_norm(main) if _CG is not None else main
    for w in REGIONAL_REFS:
        w = _CG.zh_norm(w) if _CG is not None else w
        for m in re.finditer(re.escape(w), main):
            line = main[max(0, m.start() - 30):m.start() + 40].replace("\n", " ")
            hits.append((w, line.strip()))
            break
    if not hits:
        r.add("PASS", "D14", "未检出区域性参照",
              ["注：词表穷举不了，其他地区性例子需评审方判断"])
        return
    r.add("FAIL", "D14", f"检出 {len(hits)} 处区域性参照",
          [f"「{w}」→ …{ctx}…" for w, ctx in hits[:4]]
          + ["改用纽约／伦敦／东京这类国际知名参照，7 个语言版本才都读得懂"])


# ────────────────────── 评审素材抽取 ──────────────────────

SKIP_SEC = r"常見問題|常见问题|FAQ|內鏈清單|内链清单|發布前自檢|发布前自检|資料來源|资料来源|上稿用"
COMMON_UPPER = {
    "AI", "API", "HTTP", "HTTPS", "URL", "URLS", "SEO", "GEO", "FAQ", "CEO", "USD",
    "OK", "PDF", "HTML", "CSS", "JSON", "PC", "IOS", "APP", "KOL", "UI", "UX",
}
# 众所周知的品牌／通用词：出现也不需要在文中给定义，别塞进评审清单当噪音
WELL_KNOWN = {
    "Visa", "Mastercard", "Google", "Apple", "Amazon", "AWS", "Microsoft", "Meta",
    "Stripe", "Shopify", "PayPal", "Twitter", "Telegram", "Discord", "YouTube",
    "GitHub", "Linux", "Windows", "iPhone", "Android", "Chrome", "Excel", "Word",
}


def content_sections(cg, main: str) -> list[tuple[str, str]]:
    return [(h, b) for h, b in cg.section_bodies(main) if not re.search(SKIP_SEC, h)]


def proper_nouns(main: str, limit: int = 14) -> list[str]:
    """粗抽首次出现的专有名词。

    抓完整词组而不是碎片——`Linux Foundation` 不该被切成 Linux + Foundation，
    否则评审方要在噪音里找真问题。抽不全是已知边界，任务文件里明确要求评审方补遗漏。
    """
    pat = (r"\b((?:[a-z]\d{2,4}\s+)?"                          # 可选前缀：x402 Foundation
           r"[A-Z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*"           # Coinbase / EIP-3009
           r"(?:\s+[A-Z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*)*"   # + Linux Foundation
           r"|[a-z]\d{2,4})\b")                                # x402
    seen, out = set(), []
    for m in re.finditer(pat, main):
        w = m.group(1).strip()
        if len(w) < 2 or w.isdigit():
            continue
        words = w.split()
        # 单词形态：过滤通用缩写与知名品牌；词组形态：整体在白名单才过滤
        if len(words) == 1 and (w.upper() in COMMON_UPPER or w in WELL_KNOWN):
            continue
        if len(words) > 1 and all(x in WELL_KNOWN or x.upper() in COMMON_UPPER for x in words):
            continue
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
        if len(out) >= limit:
            break
    return out


# ────────────────────── 文件路径 ──────────────────────

def paths(vault: str, aid: str) -> dict[str, str]:
    base = os.path.join(vault, "06-工作区", "GEO自检")
    return {
        "dir": base,
        "task": os.path.join(base, f"{aid}-评审任务.md"),
        "result": os.path.join(base, f"{aid}-评审结果.md"),
        "answers": os.path.join(base, f"{aid}.md"),
    }


# ────────────────────── scan ──────────────────────

def stage_scan(cg, path: str, vault: str) -> int:
    text = open(path, encoding="utf-8").read()
    fm, body = cg.parse_frontmatter(text)
    main, _ = cg.split_seo_section(body)
    aid = (fm.get("article_id") or "").strip()
    if not aid:
        print("frontmatter 缺 article_id，定位不到评审文件路径")
        return 2

    # 先跑 check_geo.py 的 check_d 并重分类；本脚本自己新增的检查随后再加，
    # 不经过重分类——否则新增行会被 D6/D8 那几个分支重写，覆盖掉自己的结论。
    base = cg.Report()
    cg.check_d(base, fm, main, vault, aid)

    to_review, rows = [], []
    for verdict, item, summary, detail in base.rows:
        if verdict == "__SEC__":
            rows.append((verdict, item, summary, detail))
            continue
        if item in REMOVED:
            rows.append(("INFO", item, f"已删除，不再判定（原判：{verdict}）", []))
            continue
        if item in MERGED_INTO_D1:
            rows.append(("INFO", item, f"已并入 D1，不单独判（原判：{verdict}）", []))
            continue
        if item in DELEGATED:
            rows.append(("INFO", item, f"由 M3 闸 1.5 判定，本模组不重判（原判：{verdict}）", detail))
            continue
        if item == "D8":
            vague_hit = any("二手转述措辞" in d and "无" not in d for d in detail)
            if vague_hit:
                rows.append((verdict, item, summary, detail))   # 无来源措辞是硬错，保留
            else:
                rows.append(("INFO", item,
                             f"数量门槛已取消，脚本结果仅作辅助信号（原判：{verdict}）", detail))
            continue
        if verdict == "MANUAL" and (item in REVIEW_ITEMS or item in COND_REVIEW):
            to_review.append(item)
            rows.append(("REVIEW", item, "转独立评审", detail))
            continue
        rows.append((verdict, item, summary, detail))
    # 本模组新增的检查单独收集，再决定哪些需要语义确认
    extra = cg.Report()
    check_d1_typed(cg, extra, main)
    check_d4_faq_gap(cg, extra, main)
    check_d8_proximity(cg, extra, main)
    check_d12_restraint(cg, extra, main)
    check_d12_table_summary(cg, extra, main)
    check_d12_list_risk(cg, extra, main)
    check_d9_hedge(cg, extra, main)
    check_d11_extra(cg, extra, main)
    check_d13(cg, extra, main)
    check_d13_authority(extra, main)
    check_d14(extra, main)
    check_d15_cta(cg, extra, main)
    check_d16_counter(cg, extra, main)
    check_d17_source_date(cg, extra, main)
    check_d18_absolute(cg, extra, main)
    check_d19_case(cg, extra, main)
    check_d20_case_data(cg, extra, main, vault, aid)

    # 机检结论不等于语义结论：这几项要么本来就要评审判（D1 的分型），
    # 要么机检只能粗筛（D4 的字面重合、D15 的恐吓式推销），一律送评审。
    for verdict, item, _, _ in extra.rows:
        need = ((item == "D1" and verdict != "SKIP")
                or (item == "D4" and verdict in ("WARN", "FAIL"))
                or (item == "D15" and verdict != "SKIP")
                or (item == "D16" and verdict in ("WARN", "FAIL"))
                or (item == "D18" and verdict in ("WARN", "FAIL"))
                or (item == "D19" and verdict != "SKIP"))
        if need and item not in to_review:
            to_review.append(item)

    r = cg.Report()
    r.section("D 区机检（复用 check_geo.py 的 check_d）")
    r.rows.extend(rows)
    r.section("本模组新增的检查")
    r.rows.extend(extra.rows)
    r.dump()

    for it in REVIEW_ITEMS:
        if it not in to_review:
            to_review.append(it)
    order = {k: i for i, k in enumerate(("D1", "D3", "D4", "D7", "D8", "D9", "D10", "D15", "D16", "D18", "D19"))}
    to_review.sort(key=lambda x: order.get(x, 99))

    p = paths(vault, aid)
    os.makedirs(p["dir"], exist_ok=True)
    write_task(cg, p, aid, path, main, to_review)

    c = r.counts()
    print()
    print(f"机检：PASS {c.get('PASS',0)}  FAIL {c.get('FAIL',0)}  WARN {c.get('WARN',0)}  "
          f"SKIP {c.get('SKIP',0)}  转评审 {len(to_review)}")
    print(f"\n评审任务已写入：{p['task']}")
    print("下一步：spawn 独立评审 subagent（只给成稿与任务文件，不给写作上下文），")
    print(f"        它把结论写进 {p['result']}，然后跑 --stage verify。")
    if c.get("FAIL", 0):
        print("\n注意：机检已有 FAIL 项，这些不用等评审，可以先打回改。")
    return 1 if c.get("FAIL", 0) else 0


def write_task(cg, p: dict, aid: str, article_path: str, main: str, items: list[str]) -> None:
    L = [f"# D 区评审任务 — {aid}", "",
         f"成稿：`{article_path}`", "",
         "## 给评审方的三条硬要求", "",
         "1. **你不参与写作。** 只看成稿，不要索取大纲、写作要求或写作过程。",
         "2. **默认判不通过。** 举证责任在你身上。",
         "3. **按下面的问法回答。** 问法是「找出哪几处不合格」，不是「是否都合格」——"
         "不要把它读成后者。", "",
         "**每个判定必须附原文原句作为证据。脚本会回原文核对：句子是否真实存在、"
         "是否在你说的位置。核不上判定作废。**", ""]

    for it in items:
        L += [f"## {it}", "", f"**问法**：{REVIEW_QUESTIONS.get(it, '（见检查项定义）')}", ""]
        if it == "D3":
            secs = content_sections(cg, main)
            L += [f"各内容节首段（共 {len(secs)} 节，FAQ 与工作节已排除）：", ""]
            for h, b in secs:
                ps = cg.paragraphs(b)
                L.append(f"- **{h[:40]}** → {ps[0][:110] if ps else '（该节无正文段落）'}")
            L.append("")
        elif it == "D10":
            nouns = proper_nouns(main)
            L += [f"脚本粗抽的专有名词（{len(nouns)} 个，**抽不全，遗漏的请自行补上**）：", "",
                  "、".join(f"`{n}`" for n in nouns), ""]
        elif it == "D7":
            L += ["机检未命中的差异化条目见 `06-工作区/增益/` 下的 gain.md，逐条核。", ""]
        elif it == "D1":
            blocks = cg.blocks_after_h1(main)
            ab = blocks[0] if blocks else ""
            L += ["Answer Block 原文：", "", "```", ab[:600], "```", "",
                  "六型结构：定义型（定义→适用范围→与相近概念差异→来源）／"
                  "Yes-No 型（结论→前提→例外）／方法流程型（前提→步骤→每步结果→常见错误→何时停手）／"
                  "比较型（比较轴→差异→适合谁→不适合谁）／"
                  "风险型（风险→何时发生→后果→怎么降低→何时找专业）／"
                  "时效型（结论→日期地区→有效范围→更新门槛）。", ""]
        elif it == "D4":
            L += ["脚本已按字面重合率粗筛（重合过低的题见 scan 输出）。字面不重合但**正文确实答过同一件事**"
                  "不算问题；字面重合但**答案里多了正文没有的主张**才是问题，这一层要你判。", "",
                  "判断基准：FAQ 是正文关键答案的问答式摘录。每一题都要能在正文找到回答它的段落，"
                  "答案是那一处结论的独立摘要；找不到对应段落、或答案加了正文没说过的事，判不通过。", ""]
        elif it == "D8":
            domains = sorted(set(re.findall(r"https?://([^/\s)]+)", main)))
            paras = len([x for x in main.split("\n\n") if len(re.findall(r"[一-鿿]", x)) > 20])
            L += [f"正文约 {paras} 个实质段落，外链域名 {len(domains)} 个：",
                  "、".join(f"`{d}`" for d in domains) or "（无）", "",
                  "来源优先级（越前越好）：原始官方 → 同行评审研究 → 专业机构 → "
                  "高质量新闻／产业媒体 → 专家分析 → 一般内容网站。", ""]
        elif it == "D9":
            L += ["全文未检出「查不到 / 对不上 / 口径不一致 / 以官方为准」这类表述。", ""]
        elif it == "D18":
            hits = [para.strip().replace("\n", " ")[:80] for para in main.split("\n\n")
                    if any(w in para for w in ABSOLUTE_MARKS)]
            L += [f"脚本按词表粗筛到 {len(hits)} 处候选（抽不全，请自行补）：", ""]
            L += [f"- {h}…" for h in hits[:10]] + ["",
                  "判断基准：一句绝对化表述要么紧邻有能撑住「全部／没有一篇／不存在」这种范围的证据，"
                  "要么改成有限定的说法。引用了来源但结论比来源说的更大，同样不合格。", ""]
        elif it == "D19":
            L += ["请把案例节从头读到尾，按时间顺序核四件事：", "",
                  "1. 判定规则（用哪个周期的收盘、影线算不算、区间怎么取）是不是写在标注之前；",
                  "2. 确认条件、失效条件、放弃条件是否各自写明，且彼此不混用（收线失效 ≠ 价格止损）；",
                  "3. 每一个标注在它标注的那个时点是否已经可知——用了之后才出现的高点／低点来划区间、选停损，就是事后信息；",
                  "4. 引言或小标题承诺示范什么（多周期？完整进场？），案例实际示范了什么，两者是否一致。", "",
                  "对每个指认交出案例里的原句。", ""]

    L += ["---", "", "## 回答格式（写进评审结果文件）", "",
          "```markdown"]
    for it in items:
        L.append(f"- {it}: <你的判定，一句话说清结论>")
        L.append(f"- {it}.证据: <原文原句；多条用 / 分隔>")
        if it in NEEDS_LOCATION:
            L.append(f"- {it}.位置: <该原句所在的节名>")
    L += ["```", "",
          f"结论少于 {MIN_ANSWER_CHARS} 个字符视为未回答；"
          f"证据原句归一化后少于 {MIN_EVIDENCE_CHARS} 个字符视为无效。", ""]
    open(p["task"], "w", encoding="utf-8").write("\n".join(L))


# ────────────────────── verify ──────────────────────

def norm(s: str) -> str:
    """归一化：先繁简统一（复用 check_geo 的转换器），再去标点空白。

    不归一化的后果：评审用简体写证据、正文是繁中，回验必然核不上，
    判定会被误判为「编造」。这是 2026-08-08 实测确认过的误报源。
    """
    z = _CG.zh_norm(s) if _CG is not None else s
    return re.sub(r"[\s　「」『』（）()【】…—\-·、，,。.：:；;！!？?]+", "", z)


def read_result(path: str) -> dict[str, dict[str, str]]:
    if not os.path.isfile(path):
        return {}
    out: dict[str, dict[str, str]] = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^\s*[-*]?\s*([A-J]\d+)(?:\.(证据|位置|evidence|location))?\s*[：:]\s*(.*)$", line)
        if not m:
            continue
        item, kind, val = m.group(1), m.group(2), m.group(3).strip()
        slot = {"证据": "evidence", "evidence": "evidence",
                "位置": "location", "location": "location"}.get(kind or "", "text")
        rec = out.setdefault(item, {})
        if val or slot not in rec:
            rec[slot] = val
    return out


def verify_one(item: str, rec: dict, main: str, secs: list) -> tuple[bool, str]:
    ev = rec.get("evidence", "").strip().strip("「」\"'")
    parts = [q.strip().strip("「」\"'") for q in re.split(r"\s*/\s*|；|;", ev)]
    parts = [q for q in parts if len(norm(q)) >= MIN_EVIDENCE_CHARS]
    if not parts:
        return False, f"缺证据原句（或太短，至少 {MIN_EVIDENCE_CHARS} 个有效字符）"
    hay = norm(main)
    missing = [q for q in parts if norm(q) not in hay]
    if missing:
        return False, (f"{len(missing)}/{len(parts)} 条证据不在正文中："
                       f"「{missing[0][:32]}…」← 回原文没找到")
    if item not in NEEDS_LOCATION:
        return True, f"{len(parts)} 条证据全部回验通过（首条：「{parts[0][:24]}…」）"
    loc = rec.get("location", "").strip()
    if not loc:
        return False, "缺位置（要写明哪一节）"
    hit = [(h, b) for h, b in secs if norm(loc) in norm(h) or norm(h) in norm(loc)]
    if not hit:
        return False, f"找不到叫「{loc}」的节"
    ps = [p for p in hit[0][1].splitlines() if p.strip() and not p.startswith(("|", ">", "#", "-"))]
    first = ps[0] if ps else ""
    if norm(parts[0]) not in norm(first):
        return False, f"证据不在「{loc}」首段里（该节首段实际是：{first[:28]}…）"
    return True, f"证据已回验，确在「{loc}」首段"


def stage_verify(cg, path: str, vault: str) -> int:
    text = open(path, encoding="utf-8").read()
    fm, body = cg.parse_frontmatter(text)
    main, _ = cg.split_seo_section(body)
    aid = (fm.get("article_id") or "").strip()
    if not aid:
        print("frontmatter 缺 article_id")
        return 2
    p = paths(vault, aid)
    if not os.path.isfile(p["task"]):
        print(f"找不到评审任务文件：{p['task']}\n先跑 --stage scan。")
        return 2

    wanted = re.findall(r"^##\s+([A-J]\d+)\s*$", open(p["task"], encoding="utf-8").read(), re.M)
    got = read_result(p["result"])
    secs = content_sections(cg, main)

    r = cg.Report()
    r.section("独立评审结果回验")
    if not got:
        r.add("FAIL", "—", f"读不到评审结果：{p['result']}",
              ["独立评审这一步没做，或结果没写进文件。两道机制缺一道等于没做。"])
        r.dump()
        return 1

    ok_items, bad = [], []
    for it in wanted:
        rec = got.get(it, {})
        conclusion = rec.get("text", "")
        if len(conclusion.strip()) < MIN_ANSWER_CHARS:
            bad.append(it)
            r.add("FAIL", it, "没有判定结论", [])
            continue
        ok, msg = verify_one(it, rec, main, secs)
        if ok:
            ok_items.append((it, conclusion))
            r.add("PASS", it, conclusion[:44], [msg])
        else:
            bad.append(it)
            r.add("FAIL", it, f"证据回验不通过：{msg}",
                  [f"判定原文: {conclusion[:46]}", "判定作废，退回重判。"])
    r.dump()

    print()
    if bad:
        print(f"不通过：{len(bad)} 项待重判（{'、'.join(bad)}）")
        print("打回 AYI 改稿或退回评审方重判。**上限 2 轮，第 3 轮仍不过就停下来问主人。**")
        return 1

    # 通过 → 写答案文件供 M6 的 check_geo.py 消费
    os.makedirs(p["dir"], exist_ok=True)
    old = read_result(p["answers"])
    merged = {k: v.get("text", "") for k, v in old.items()}
    for it, conclusion in ok_items:
        merged[it] = conclusion
    L = [f"# GEO 人工项结论 — {aid}", "",
         "D 区各项由 seo-geo-check 的独立评审 + 原文回验产出（已回验通过）。",
         "E3 / E4 属上稿后的结构化数据项，**不由本模组填**，M6 前需另外补。", ""]
    for k in sorted(merged, key=lambda x: (x[0], int(x[1:]))):
        L.append(f"- {k}: {merged[k]}")
    L.append("")
    open(p["answers"], "w", encoding="utf-8").write("\n".join(L))
    print(f"通过。答案文件已写入：{p['answers']}")
    print("M6 跑 check_geo.py 时会读它。E3/E4 仍需另外补答案。")
    return 0


# ────────────────────── main ──────────────────────

def main() -> int:
    args = sys.argv[1:]
    cg = load_check_geo()
    vault = cg.resolve_vault(cg.VAULT, args[0]) if hasattr(cg, 'resolve_vault') else cg.VAULT
    if "--vault" in args:
        i = args.index("--vault")
        try:
            vault = os.path.expanduser(args[i + 1])
            del args[i:i + 2]
        except IndexError:
            print("--vault 后面要跟路径")
            return 2
    stage = "scan"
    if "--stage" in args:
        i = args.index("--stage")
        try:
            stage = args[i + 1]
            del args[i:i + 2]
        except IndexError:
            print("--stage 后面要跟 scan 或 verify")
            return 2
    if len(args) != 1 or stage not in ("scan", "verify"):
        print(__doc__)
        return 2
    if not os.path.isfile(args[0]):
        print(f"读不到文章：{args[0]}")
        return 2
    if not os.path.isdir(vault):
        print(f"Vault 不存在：{vault}")
        return 2
    return stage_scan(cg, args[0], vault) if stage == "scan" else stage_verify(cg, args[0], vault)


if __name__ == "__main__":
    sys.exit(main())
