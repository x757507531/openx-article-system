#!/usr/bin/env python3
"""从 AYi 语料生成文体权重表，输出 data/weights.json。

语料更新后重跑即可刷新权重：
    python3 build_weights.py --corpus <语料目录> [--out <输出路径>]

只统计成熟期样本。说明书腔的 13 篇（35、39-50）和英文版（17、36）被排除，
理由见 SKILL.md「先说清楚这个 Skill 蒸馏的是哪一段」。
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

ZH = r"[一-鿿]"

# 说明书腔反面样本 + 英文版，不参与统计
EXCLUDE = {"17", "35", "36", "39", "40", "41", "42", "43", "44", "45", "46", "47", "48", "49", "50"}

# 文体标注。人工分类，依据是稿件的主导结构而非题材
GENRE = {
    "教程": {"01", "03", "06", "08", "10", "13", "15", "16", "19", "21",
             "22", "23", "27", "28", "29", "30", "33", "34"},
    "拆解观点": {"02", "04", "05", "07", "09", "14", "18", "20", "24", "25", "31", "32"},
    "复盘叙事": {"11", "12", "26", "37", "38"},
}

# 十三个可测动作。正则是保守下界，宁可漏检不可误报
MOVES = {
    "自曝错误": [r"我错了", r"我一开始.{0,10}以为", r"才发现自己", r"我之前.{0,8}想错",
             r"搞反了", r"回头看.{0,10}太端", r"差点被带偏", r"踩过一模一样",
             r"我当年也信", r"后来想明白", r"后来才发现", r"我本来想", r"我第一反应是", r"我以为是"],
    "泼冷水": [r"泼一盆冷水", r"泼冷水", r"也有边界", r"确实慢", r"谁不用买", r"诚实地说",
            r"不是万能", r"说句公道话", r"别神化", r"一无是处", r"坏处是", r"代价是",
            r"另一面", r"也得说清", r"但也.{0,6}局限"],
    "集体收尾": [r"我们一起", r"咱们下一个", r"一起进发", r"一起往前看", r"一起琢磨", r"咱们回来对账"],
    "承认不确定": [r"没法打包票", r"还在路上", r"我也不确定", r"我不敢说", r"不装会",
              r"还在摸索", r"我也还在", r"不是标准答案", r"我也在想"],
    "邀请对账": [r"回来对账", r"自己验证", r"可复现", r"不用信我", r"自己核一眼", r"你可以自己"],
    "评论区钩子": [r"评论区留言", r"评论告诉我", r"留言告诉我", r"评论区.{0,10}问", r"私信我", r"评论区见"],
    "打土比方": [r"打个比方", r"就像", r"有点像", r"理解成", r"我用一个.{0,10}比", r"好比"],
    "替读者提问": [r"啥意思呢", r"是啥[，,]", r"你可能会想", r"在哪呢", r"怎么判断",
              r"吗？也不是", r"你可以这么理解"],
    "免责披露": [r"不构成", r"NFA", r"仅供学习", r"风险自担", r"不构成任何推荐"],
    "清单验收件": [r"验收", r"红名单", r"铁律", r"毕业", r"速查表", r"\[ \]"],
    "开头目录": [r"▸", r"讲.{0,4}件事", r"这篇会带你", r"核心三部分", r"这篇讲"],
    "口头禅说实话": [r"说实话"],
    "口头禅我一直觉得": [r"我一直觉得|我越来越觉得"],
}

# 内容强绑定，不参与配额抽签，需要就上
NECESSITY_TRIGGERED = ["免责披露", "清单验收件"]

# 节奏档与人称档的边界。取值来自语料实际分布，不是拍的
TEMPO_BANDS = [
    ("短促", 8, 14),
    ("标准", 14, 25),
    ("舒展", 25, 46),
    ("逗号流", 46, 10**6),
]
VOICE_BANDS = [
    ("教学档", lambda you, wo: wo < 70 and you >= 120),
    ("自述档", lambda you, wo: wo >= 150 and you < 110),
    ("平衡档", lambda you, wo: True),
]


def strip_body(raw: str) -> str:
    raw = re.sub(r"^---.*?\n---\n", "", raw, flags=re.S)
    raw = re.sub(r"!\[.*?\]\(.*?\)", "", raw)
    raw = re.sub(r"\[查看 X 原文\]\(.*?\)", "", raw)
    return raw.strip()


def zh_len(s: str) -> int:
    return len(re.findall(ZH, s))


def band_of(value: float, bands) -> str:
    for name, lo, hi in bands:
        if lo <= value < hi:
            return name
    return bands[-1][0]


def voice_band(you: float, wo: float) -> str:
    for name, test in VOICE_BANDS:
        if test(you, wo):
            return name
    return "平衡档"


def analyse(corpus: Path) -> dict:
    docs = []
    for f in sorted(corpus.glob("*.md")):
        if f.name == "INDEX.md":
            continue
        num = f.name[:2]
        if num in EXCLUDE:
            continue
        body = strip_body(f.read_text(encoding="utf-8"))
        n = zh_len(body)
        if n < 300:
            continue
        genre = next((g for g, s in GENRE.items() if num in s), "其他")
        paras = [p.strip() for p in body.split("\n")
                 if p.strip() and not p.startswith("#")]
        plens = [zh_len(p) for p in paras if zh_len(p) >= 4]
        single = sum(1 for p in paras
                     if zh_len(p) >= 4 and len(re.findall(r"[。？！]", p)) <= 1)
        hits = [m for m, pats in MOVES.items() if any(re.search(p, body) for p in pats)]
        docs.append({
            "num": num, "genre": genre, "zh": n,
            "para_median": statistics.median(plens) if plens else 0,
            "single_ratio": single / len(plens) if plens else 0,
            "you": body.count("你") / n * 10000,
            "wo": body.count("我") / n * 10000,
            "moves": hits,
        })

    genres = sorted({d["genre"] for d in docs})
    out = {
        "meta": {
            "corpus": str(corpus),
            "sample_size": len(docs),
            "excluded": sorted(EXCLUDE),
            "note": "覆盖率为篇数占比；正则为保守下界，真实值应更高。配额抽签用相对权重，不用绝对值。",
        },
        "moves_all": list(MOVES.keys()),
        "necessity_triggered": NECESSITY_TRIGGERED,
        "quota": {},
        "weights": {},
        "profiles": {},
    }

    # 每篇命中数，决定配额区间
    counts = sorted(len(d["moves"]) for d in docs)
    out["quota"] = {
        "mean": round(statistics.mean(counts), 2),
        "median": statistics.median(counts),
        "min": min(counts), "max": max(counts),
        "recommend_min": 3, "recommend_max": 5,
    }

    for g in genres:
        sub = [d for d in docs if d["genre"] == g]
        if not sub:
            continue
        out["weights"][g] = {
            m: round(sum(1 for d in sub if m in d["moves"]) / len(sub), 3)
            for m in MOVES
        }
        tempo = [band_of(d["para_median"], TEMPO_BANDS) for d in sub]
        voice = [voice_band(d["you"], d["wo"]) for d in sub]
        out["profiles"][g] = {
            "n": len(sub),
            "para_median": {
                "min": min(d["para_median"] for d in sub),
                "median": statistics.median([d["para_median"] for d in sub]),
                "max": max(d["para_median"] for d in sub),
            },
            "single_ratio": {
                "min": round(min(d["single_ratio"] for d in sub), 3),
                "median": round(statistics.median([d["single_ratio"] for d in sub]), 3),
                "max": round(max(d["single_ratio"] for d in sub), 3),
            },
            "tempo_dist": {b: tempo.count(b) for b, *_ in TEMPO_BANDS if tempo.count(b)},
            "voice_dist": {b: voice.count(b) for b, _ in VOICE_BANDS if voice.count(b)},
        }

    out["bands"] = {
        "tempo": {name: [lo, None if hi > 10**5 else hi] for name, lo, hi in TEMPO_BANDS},
        "voice": {
            "教学档": {"you": [120, None], "wo": [0, 70]},
            "平衡档": {"you": [60, 160], "wo": [60, 160]},
            "自述档": {"you": [0, 110], "wo": [150, None]},
        },
        "single_ratio_by_tempo": {"短促": [0.85, 1.0], "标准": [0.75, 1.0],
                                  "舒展": [0.55, 0.9], "逗号流": [0.3, 0.75]},
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path,
                    default=Path.home() / "Documents/Codex/AYI_AInotes_articles_50")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parent.parent / "data/weights.json")
    args = ap.parse_args()

    if not args.corpus.exists():
        print(f"语料目录不存在：{args.corpus}")
        return 2

    data = analyse(args.corpus)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"样本 {data['meta']['sample_size']} 篇，写入 {args.out}")
    print(f"每篇命中动作数：均值 {data['quota']['mean']}，中位 {data['quota']['median']}，"
          f"区间 {data['quota']['min']}–{data['quota']['max']}")
    for g, w in data["weights"].items():
        top = sorted(w.items(), key=lambda x: -x[1])[:4]
        p = data["profiles"][g]
        print(f"\n[{g}] n={p['n']}  段落中位 {p['para_median']['min']}–{p['para_median']['max']}"
              f"（中位 {p['para_median']['median']}）")
        print("   高频动作：" + "、".join(f"{k} {v:.0%}" for k, v in top))
        print("   节奏分布：" + str(p["tempo_dist"]) + "  人称分布：" + str(p["voice_dist"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
