#!/usr/bin/env python3
"""AYi 文风稿件检查器。只报警，不改文。

用法：
    python3 check_ayi.py 稿件路径
    python3 check_ayi.py 稿件路径 --profile 标准:平衡档
    python3 check_ayi.py 稿件路径 --profile 逗号流:自述档 --series ../series-log.jsonl

给了 --profile 就按该档区间判，不给则用全语料点值且只提示不判死。
给了 --series 会做跨篇检查：单篇怎么看都合格，问题只在放一起看时才显形。

注意：不要用通用 human-writing 的 check_prose.py 检查 AYi 稿。
那个脚本会把翻案句、破折号、提示性冒号报成硬违规，
而这三样正是 AYi 文风要保留的东西。
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ZH = r"[一-鿿]"

WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "data/weights.json"


def load_bands() -> dict:
    """读 profile 区间。没有权重表时退回全局点值。"""
    try:
        return json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))["bands"]
    except Exception:
        return {}

# 必须清零：机构腔、商业黑话、AI 味总结腔
HARD_JARGON = (
    "赋能", "抓手", "商业闭环", "价值闭环", "拉通", "降本增效", "全链路",
    "组合拳", "顶层设计", "认知跃迁", "生态位", "效率革命", "占据先发优势",
    "抢占红利", "彻底改变", "大幅提升", "核心竞争力", "深度赋能",
    "开启新篇章", "新的篇章", "保驾护航", "深度融合",
    "助力", "赋予新的内涵", "谱写", "迈上新台阶",
)

# 必须清零：模型腔路标
HARD_SIGNPOST = (
    "值得注意的是", "需要指出的是", "综上所述", "从某种意义上说",
    "更微妙的是", "只说对了一半", "总而言之", "总的来说",
    "随着人工智能的", "随着 AI 技术的",
)

# 需要正则判断的路标（避免误伤「在这个过程中」这类正常用法）
SIGNPOST_RE = (
    (r"在这个[^，。！？\n]{0,10}的时代", "在这个…的时代"),
    (r"在当今[^，。！？\n]{0,10}的时代", "在当今…的时代"),
    (r"随着[^，。！？\n]{0,12}的(?:发展|普及|到来)", "随着…的发展"),
)

# 提示级：不判死，只提醒
SOFT_JARGON = ("未来已来", "拥抱变化", "时代的浪潮", "新纪元")

# 空转比喻：抽象概念配抽象意象
SOFT_METAPHOR = (
    "浪潮", "底座", "星辰大海", "坍塌", "抽屉", "钥匙", "灯塔",
    "涟漪", "航船", "东风", "序章", "画卷", "试金石", "分水岭",
)

# 翻案句式（AYi 版允许，只查密度和空翻）
FLIP_PATTERNS = (
    r"不是[^。！？\n]{0,20}?而是",
    r"并非[^。！？\n]{0,20}?而是",
    r"不在于[^。！？\n]{0,20}?而在于",
    r"与其说[^。！？\n]{0,20}?不如说",
    r"你以为[^。！？\n]{0,25}?其实",
    r"表面[^。！？\n]{0,20}?实际",
    r"看似[^。！？\n]{0,20}?实则",
    r"根本不是",
    r"真正[的地][^。！？\n]{0,12}?不是",
)

# 触发免责要求的题材
DISCLAIM_TRIGGER = (
    "投资建议", "股票", "收益率", "买入", "标的", "仓位", "钱包",
    "私钥", "助记词", "理财", "剂量", "疗效", "确诊", "服药",
    "用药", "补剂", "代币", "炒币", "杠杆", "开仓",
)
DISCLAIM_MARK = (
    "不构成", "非投资建议", "NFA", "仅供学习", "仅作", "以官方",
    "请你去问医生", "咨询医生", "风险自担", "损失全部本金", "不构成任何推荐",
)

NUM_UNIT = r"\d+(?:\.\d+)?\s*(?:%|％|倍|天|小时|分钟|秒|美元|元|块|万|亿|条|篇|个|次|人|月|年|周|美金|\$|¥|[Tt]oken|[Kk]|GB|MB)"


def _load_t2s():
    """繁简 + 两岸词汇归一化器。opencc 装了就用，没装退化为原样返回。

    为什么需要：本文件所有词表与正则都是**简体**，而稿件可能是 zh-Hant。
    不归一化的后果不只是误报，更多是**漏放行**——繁中稿里的「賦能」「值得注意的是」
    「投資建議」一个都匹配不到，机构腔、模型腔、免责触发词全部查不出来，等于放水。

    用 tw2sp 而不是 t2s：后者只转字形（網路→网路），台湾用词与大陆用词仍对不上；
    前者连词汇一起转（網路→网络、軟體→软件、程式介面→程序接口）。

    注：`seo-writing-openx/scripts/check_geo.py` 里有一份同样的实现。**这是有意重复**——
    human-writing-AYI 是通用写作 skill，不该反向依赖某个站点的产文脚本。
    """
    try:
        import opencc
    except Exception:  # noqa: BLE001
        return None
    for cfg in ("tw2sp", "t2s"):
        try:
            return opencc.OpenCC(cfg).convert
        except Exception:  # noqa: BLE001
            continue
    return None


_T2S = _load_t2s()
ZH_NORM_AVAILABLE = _T2S is not None


def zh_norm(s: str) -> str:
    """归一化到简体（含两岸词汇）后再比对。转换器不可用时原样返回。"""
    if not s or _T2S is None:
        return s
    try:
        return _T2S(s)
    except Exception:  # noqa: BLE001
        return s


def load(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"^---\n.*?\n---\n", "", raw, flags=re.S)
    raw = re.sub(r"!\[.*?\]\(.*?\)", "", raw)
    raw = re.sub(r"```.*?```", "", raw, flags=re.S)
    raw = re.sub(r"`[^`\n]*`", "", raw)
    return raw.strip()


def zh_len(s: str) -> int:
    return len(re.findall(ZH, s))


def paragraphs(text: str) -> list[str]:
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith(("http", "|", ">", "![")):
            continue
        line = re.sub(r"^#+\s*", "", line)
        if zh_len(line) >= 4:
            out.append(line)
    return out


def find_parallel(paras: list[str]) -> list[str]:
    """检测四项以上同构排比：同一段内连续短句共享前两字。"""
    hits = []
    for p in paras:
        parts = [x for x in re.split(r"[，,、；;]", p) if zh_len(x) >= 3]
        run, prefix = 0, ""
        for x in parts:
            head = re.sub(r"^\s+", "", x)[:2]
            if head and head == prefix:
                run += 1
            else:
                prefix, run = head, 1
            if run >= 4:
                hits.append(p[:60])
                break
    return hits


def topic_terms(text: str) -> list[str]:
    """抽本篇的主题专名：英文词、含数字的词、书名号内容，全文出现两次以上的才算。"""
    cands = re.findall(r"[A-Za-z][A-Za-z0-9\-\.]{2,}|[A-Za-z]+\d+|《[^》]{2,12}》", text)
    freq = {}
    for c in cands:
        key = c.strip(".-")
        if len(key) < 3:
            continue
        freq[key] = freq.get(key, 0) + 1
    return [w for w, c in sorted(freq.items(), key=lambda x: -x[1]) if c >= 2][:12]


def portable_conclusion(paras: list[str], text: str) -> tuple[bool, list[str], int]:
    """结尾三段里本篇专名出现不到两次，这个结论多半换个主题也成立。"""
    terms = topic_terms(text)
    if not terms:
        return False, [], 0
    tail_pool = [p for p in paras[-8:]
                 if not any(m in p for m in DISCLAIM_MARK)
                 and not p.lstrip().startswith(("#", "$"))]
    tail = "".join(tail_pool[-3:]) if tail_pool else "".join(paras[-3:])
    hits = sum(tail.count(t) for t in terms)
    return hits < 2, terms[:5], hits


def series_check(series: Path, profile: str) -> tuple[list[str], list[str]]:
    """跨篇检查：单篇怎么看都合格，问题只在放一起看时才显形。"""
    warns, info = [], []
    if not series.exists():
        return warns, [f"日志不存在（{series}），本篇按第一篇处理"]
    rows = []
    for line in series.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return warns, ["日志是空的，本篇按第一篇处理"]
    recent = rows[-5:]

    if profile:
        parts = [x.strip() for x in profile.split(":")]
        tempo = parts[0] if parts else ""
        same = [r for r in recent[-2:] if r.get("profile", {}).get("节奏") == tempo]
        if len(same) >= 2:
            warns.append(f"节奏档「{tempo}」连续三篇相同，换一档")

    for field, label, cap in (("opening", "开头类型", 2), ("ending", "结尾类型", 2),
                              ("stance", "立场", 3), ("subtitle_style", "小标题体例", 3)):
        vals = [r.get(field) for r in recent if r.get(field)]
        for v in set(vals):
            if vals.count(v) >= cap:
                warns.append(f"最近 {len(recent)} 篇里{label}「{v}」出现 {vals.count(v)} 次，本篇避开")

    doms = [d for r in recent[-2:] for d in r.get("metaphor_domains", [])]
    if doms:
        info.append(f"近两篇比喻域：{'、'.join(sorted(set(doms)))}，本篇避开")

    if recent[-1].get("portable"):
        warns.append("上一篇的结论是可移植的，本篇结尾必须绑死主题")

    moves = [m for r in recent for m in r.get("moves", [])]
    for m in set(moves):
        if moves.count(m) >= 3:
            warns.append(f"动作「{m}」在最近 {len(recent)} 篇出现 {moves.count(m)} 次，本篇停用")
    return warns, info


def check(path: Path, profile: str = "", series: Path | None = None) -> dict:
    text = load(path)
    # 词表与正则都是简体，比对走归一化副本；原文留着做长度统计与摘录输出
    # （摘录若用归一化版，作者会看到自己句子的简体形，对不上原稿）
    text_n = zh_norm(text)
    paras = paragraphs(text)
    if not paras:
        return {"error": "没有读到正文段落"}

    plens = [zh_len(p) for p in paras]
    total_zh = sum(plens)
    single = sum(1 for p in paras if len(re.findall(r"[。？！]", p)) <= 1)

    sents = [s for s in re.split(r"[。？！\n]", text) if zh_len(s) > 2]
    slens = [zh_len(s) for s in sents] or [0]

    per10k = lambda n: round(n / total_zh * 10000, 1) if total_zh else 0.0
    per1k = lambda n: round(n / total_zh * 1000, 2) if total_zh else 0.0

    # 连续三段过长
    long_runs = []
    run = 0
    for i, n in enumerate(plens):
        run = run + 1 if n > 60 else 0
        if run >= 3:
            long_runs.append(i + 1)
            run = 0

    errors, warns, info = [], [], []

    if not ZH_NORM_AVAILABLE and re.search(r"[覺這說們個為時後們來們]", text):
        warns.append("稿件像繁体但 opencc 未安装，词表比对未做繁简归一化——"
                     "机构腔／模型腔／免责触发词可能全部漏检。"
                     "装：pip3 install opencc-python-reimplemented")

    for w in HARD_JARGON:
        c = text_n.count(w)
        if c:
            errors.append(f"机构腔硬禁词「{w}」出现 {c} 次，必须清零")
    for w in HARD_SIGNPOST:
        c = text_n.count(w)
        if c:
            errors.append(f"模型腔路标「{w}」出现 {c} 次，必须清零")
    for pat, name in SIGNPOST_RE:
        c = len(re.findall(pat, text_n))
        if c:
            errors.append(f"模型腔开场「{name}」出现 {c} 次，必须清零")
    for w in SOFT_JARGON:
        c = text_n.count(w)
        if c:
            warns.append(f"口号词「{w}」{c} 次。语料里只在口语收尾出现过一次，慎用")

    median_p = statistics.median(plens)
    ratio = single / len(paras)
    bands = load_bands()
    tempo = voice = ""
    if profile and bands:
        parts = [x.strip() for x in profile.split(":")]
        tempo = parts[0] if parts else ""
        voice = parts[1] if len(parts) > 1 else ""

    if tempo and tempo in bands.get("tempo", {}):
        lo, hi = bands["tempo"][tempo]
        hi = hi or 10**6
        if not (lo <= median_p < hi):
            errors.append(f"段落中位 {median_p} 字，越出「{tempo}」档区间 {lo}–"
                          f"{hi if hi < 10**5 else '不限'}")
        sl, sh = bands["single_ratio_by_tempo"][tempo]
        if not (sl <= ratio <= sh):
            warns.append(f"单句成段 {ratio:.0%}，「{tempo}」档参考区间 {sl:.0%}–{sh:.0%}")
    else:
        # 没给 profile 就用全语料点值，只作提示，不判死
        if median_p > 60:
            warns.append(f"段落中位 {median_p} 字，远超语料中位 21。没给 --profile 时不判死，"
                         f"但确认是不是该走「逗号流」档")
        elif median_p > 30:
            warns.append(f"段落中位 {median_p} 字，偏长（语料中位 21）")
        if ratio < 0.55:
            warns.append(f"单句成段比例 {ratio:.0%}，语料中位约 88%。段落里塞了太多句子")

    if long_runs:
        warns.append(f"有 {len(long_runs)} 处连续三段以上超过 60 字，段号约 {long_runs[:5]}")

    n_you, n_wo = text.count("你"), text.count("我")
    you_d, wo_d = per10k(n_you), per10k(n_wo)
    if voice and voice in bands.get("voice", {}):
        vb = bands["voice"][voice]
        for label, val, rng_ in (("你", you_d, vb["you"]), ("我", wo_d, vb["wo"])):
            lo = rng_[0] or 0
            hi = rng_[1] if rng_[1] is not None else 10**6
            if not (lo <= val <= hi):
                warns.append(f"「{label}」密度 {val}/万字，越出「{voice}」区间 "
                             f"{lo}–{hi if hi < 10**5 else '不限'}")
    if wo_d < 8:
        errors.append(f"第一人称密度 {wo_d}/万字。通篇没有「我」就是说明书")
    elif wo_d < 25 and voice != "教学档":
        warns.append(f"第一人称密度 {wo_d}/万字，偏低。纯步骤稿也该有作者出场")
    if you_d < 20 and voice != "自述档":
        warns.append(f"第二人称密度 {you_d}/万字，读者不在场")

    n_bang = text.count("！") + text.count("!")
    if per1k(n_bang) > 1.2:
        warns.append(f"感叹号 {per1k(n_bang)}/千字，语料 0.3。正文克制点")

    flips = sum(len(re.findall(p, text_n)) for p in FLIP_PATTERNS)
    if flips > 6:
        warns.append(f"翻案句 {flips} 处，建议压到 2 到 4 处，保留有材料撑住的")
    elif flips == 0 and total_zh > 1200:
        info.append("全文没有翻案句。AYi 的标题和小标题通常至少有一处")

    par = find_parallel(paras)
    if par:
        warns.append(f"疑似四项以上同构排比 {len(par)} 处，砍到三项：{par[0]}…")

    for w in SOFT_METAPHOR:
        c = text_n.count(w)
        if c:
            warns.append(f"空转比喻词「{w}」{c} 次，确认是不是在写实物，不是就删")

    nums = re.findall(NUM_UNIT, text)
    if len(nums) < 3 and total_zh > 800:
        errors.append(f"可核对的数字锚点只有 {len(nums)} 个。AYi 每篇至少一个硬数字")
    elif len(nums) < 6 and total_zh > 2500:
        warns.append(f"数字锚点 {len(nums)} 个，长稿偏少")

    hits = [t for t in DISCLAIM_TRIGGER if t in text_n]
    strong = {"投资建议", "标的", "仓位", "助记词", "私钥", "剂量", "疗效", "杠杆"}
    if (len(hits) >= 2 or strong & set(hits)) and not any(m in text_n for m in DISCLAIM_MARK):
        errors.append(f"涉及钱、投资或健康题材（{ '、'.join(hits[:4]) }），但末尾没有免责段")

    cold = any(k in text_n for k in (
        "泼一盆冷水", "泼冷水", "也有边界", "确实慢", "不适合", "谁不用买",
        "但也得说清", "另一面", "得诚实地说", "不是万能", "一无是处",
        "也不是", "也不全是", "说句公道话", "别神化", "坏处是", "代价是",
    ))
    if not cold and total_zh > 1500:
        warns.append("没找到泼冷水段。提到工具或方法却不讲边界，退回补一段")

    # 结尾看末段，但跳过免责、标签和纯链接行
    tail_pool = [
        p for p in paras[-8:]
        if not any(m in p for m in DISCLAIM_MARK) and not p.lstrip().startswith(("#", "$"))
    ]
    tail = "".join(tail_pool[-3:]) if tail_pool else "".join(paras[-3:])
    if not re.search(r"(我们|咱们|一起|你|评论区|下一篇|对账|见)", tail):
        info.append("结尾没有落在读者身上。若本篇走「停在判断」档这是对的，走其他档要补一句")

    _, terms, hits = portable_conclusion(paras, text)
    if terms:
        if hits == 0:
            warns.append(f"结尾三段一次都没提到本篇专名（{'、'.join(terms)}）。"
                         f"这段结论换个主题照样成立，等于没给判断")
        elif hits < 3:
            info.append(f"结尾三段只出现 {hits} 次本篇专名（{'、'.join(terms)}）。"
                        f"自查一遍：把结论句里的主题词换成上一篇的主题，如果还读得通就重写")
        else:
            info.append(f"结尾三段出现 {hits} 次本篇专名，结论绑得住主题")

    if series:
        sw, si = series_check(series, profile)
        warns.extend(sw)
        info.extend(si)

    return {
        "file": str(path),
        "profile": profile,
        "series": str(series) if series else "",
        "中文字数": total_zh,
        "段落数": len(paras),
        "段落中位字数": median_p,
        "单句成段比例": f"{ratio:.1%}",
        "句子中位长度": statistics.median(slens),
        "你/万字": per10k(n_you),
        "我/万字": per10k(n_wo),
        "感叹号/千字": per1k(n_bang),
        "翻案句": flips,
        "数字锚点": len(nums),
        "errors": errors,
        "warnings": warns,
        "info": info,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="AYi 文风稿件检查器")
    ap.add_argument("path", type=Path)
    ap.add_argument("--profile", default="",
                    help="档案，格式「节奏档:人称档」，例如 标准:平衡档。"
                         "给了就按区间判，不给就用全语料点值且只提示不判死")
    ap.add_argument("--series", type=Path,
                    help="series-log.jsonl 路径，开启跨篇检查")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.path.exists():
        print(f"文件不存在：{args.path}", file=sys.stderr)
        return 2

    r = check(args.path, profile=args.profile, series=args.series)
    if "error" in r:
        print(r["error"], file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 1 if r["errors"] else 0

    print(f"\n=== {r['file']} ===")
    if r.get("profile"):
        print(f"档案 {r['profile']}" + ("｜已开跨篇检查" if r.get("series") else ""))
    print(
        f"中文 {r['中文字数']} 字 / {r['段落数']} 段 | "
        f"段落中位 {r['段落中位字数']} 字 | 单句成段 {r['单句成段比例']}"
    )
    print(
        f"句子中位 {r['句子中位长度']} 字 | "
        f"你 {r['你/万字']}、我 {r['我/万字']} 每万字 | "
        f"感叹号 {r['感叹号/千字']}/千字（语料 0.3）"
    )
    print(f"翻案句 {r['翻案句']} 处（建议 2-4）| 数字锚点 {r['数字锚点']} 个")

    if r["errors"]:
        print("\n必须改：")
        for e in r["errors"]:
            print(f"  ✗ {e}")
    if r["warnings"]:
        print("\n看一眼：")
        for w in r["warnings"]:
            print(f"  · {w}")
    if r["info"]:
        print("\n提示：")
        for i in r["info"]:
            print(f"  - {i}")
    if not r["errors"] and not r["warnings"]:
        print("\n没查出问题。材料真假、比方土不土、泼冷水是不是走流程，还得自己读一遍。")

    print()
    return 1 if r["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
