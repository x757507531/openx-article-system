#!/usr/bin/env python3
"""按跨篇记忆决定本篇的稿件档案，避免连续多篇撞同一套路。

两个子命令：

    pick_profile.py pick --genre 教程 --title "x402 協議是什麼" --log <路径>
    pick_profile.py log  --log <路径> --title ... --genre ... --moves a,b,c ...

pick 输出确定性结果：同样的日志加同样的标题，永远得到同一份档案。
随机种子取自标题，不取时间，所以可复现、可回溯。

log 文件是 JSON Lines，一篇一行，放在产出目录旁边，不要放在 skill 目录里。
不同站点、不同栏目各用各的日志，否则会互相污染。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
WEIGHTS = SKILL_DIR / "data/weights.json"

# ── 变体池 ───────────────────────────────────────────────────────────────
OPENINGS = {
    "甩结论": "第一句就是判断，后面全是支撑",
    "甩数字": "用一个具体数字开场，再说这个数字为什么值得停一下",
    "甩反常事实": "一句跟直觉相反、但有出处的事实",
    "立契约": "先讲这篇需要你什么、给你什么、不讲什么",
    "从别人的问题起头": "后台/评论区/朋友反复问的同一个问题",
    "从一句话起头": "一句听来的话或一个词，我第一次看到它的反应",
    "从时间线起头": "某天到某天之间发生了什么",
    "给读者定位": "先点名这篇是写给哪一类人看的",
}

ENDINGS = {
    "集体收尾": "落在「我们」上，带点土气和热乎劲",
    "停在判断": "给完最后一个判断就停，不邀请、不升华",
    "留待办预告": "说清下一篇要接什么，或读者接下来该做什么",
    "邀请对账": "给一个可验证的时间点或方法",
    "功能性收尾": "一句说明这篇写出来是为了让什么少发生",
    "资源收尾": "把链接、仓库、清单摆在最后",
}

METAPHOR_DOMAINS = ["交通物流", "厨房饮食", "农事", "金融银行", "工具五金",
                    "身体医疗", "学校考试", "建筑装修", "家电"]

STANCES = {
    "泼冷水": "肯定价值但重点讲边界",
    "直接推荐": "明确说值得做，给路径",
    "中立拆解": "只讲机制，不给该不该做的判断",
    "纠错打假": "对着一个流行说法逐条对账",
    "纯操作": "不给通用判断，全篇只讲怎么做",
}

SUBTITLE_STYLES = ["陈述句", "编号章节", "序号主题", "命名式", "问句", "不给小标题"]

LENGTH_BANDS = {"短打": (800, 1500), "常规": (1500, 3000), "长文": (3000, 6000)}

# 这两项在权重表里是动作，但在档案里由 ending / opening 维度承担，
# 留在配额池会造成同一件事被抽两次（结尾抽到「停在判断」又抽到动作「集体收尾」）
DIMENSION_OWNED = {"集体收尾": "ending", "开头目录": "opening"}


# ── 日志 ────────────────────────────────────────────────────────────────
def read_log(path: Path | None, limit: int = 5) -> list[dict]:
    if not path or not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def seeded_rng(title: str, salt: str = "") -> random.Random:
    h = hashlib.sha256((title + salt).encode("utf-8")).hexdigest()
    return random.Random(int(h[:16], 16))


def weighted_sample(rng: random.Random, weights: dict[str, float], k: int) -> list[str]:
    """加权无放回抽样。权重为 0 的项不会被抽到。"""
    pool = {m: w for m, w in weights.items() if w > 0}
    picked = []
    for _ in range(min(k, len(pool))):
        total = sum(pool.values())
        if total <= 0:
            break
        r = rng.uniform(0, total)
        acc = 0.0
        for m, w in pool.items():
            acc += w
            if r <= acc:
                picked.append(m)
                del pool[m]
                break
    return picked


def rotate(rng: random.Random, options: list[str], recent: list[str], avoid: int = 3) -> str:
    """LRU 轮换：最近 avoid 篇用过的先排除，全被排除时退回最久没用的那批。"""
    blocked = set(recent[-avoid:])
    free = [o for o in options if o not in blocked]
    if not free:
        oldest = [o for o in options if o not in set(recent[-1:])]
        free = oldest or options
    return rng.choice(free)


# ── 主逻辑 ──────────────────────────────────────────────────────────────
def pick(args) -> dict:
    data = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    genre = args.genre
    if genre not in data["weights"]:
        raise SystemExit(f"未知文体：{genre}。可选：{'、'.join(data['weights'])}")

    base = dict(data["weights"][genre])
    necessity = set(data["necessity_triggered"])
    for m in necessity:
        base.pop(m, None)          # 内容强绑定，需要才写
    for m in DIMENSION_OWNED:
        base.pop(m, None)          # 由 opening / ending 维度决定，不重复抽

    log = read_log(args.log, limit=5)
    rng = seeded_rng(args.title)

    # ── 动作选择：衰减 + 扰动，不用硬轮换 ──
    # 纯 LRU 会产生周期：池子 9 个、锁 2 篇、每篇抽 3，正好切成三组固定分割然后循环。
    # 真正要防的不是某个动作出现多次（AYi 自己每个动作平均用 10 次），
    # 是同一组合反复出现。所以只硬锁上一篇，其余靠衰减和随机扰动拉开。
    last_moves = set(log[-1].get("moves", [])) if log else set()
    tally = {}
    for row in log[-5:]:
        for m in row.get("moves", []):
            tally[m] = tally.get(m, 0) + 1
    over_quota = {m for m, c in tally.items() if c >= 3}   # 五篇内用满三次，本篇停用
    hard_locked = last_moves | over_quota
    soft_locked = {m for m, c in tally.items() if c >= 1} - hard_locked

    # 按距离衰减：越近用过压得越狠。均等衰减会让相对排序不变，
    # 结果是同一组高权重动作隔一篇就整组回来（实测第 3 篇和第 5 篇组合完全相同）。
    DIST_DECAY = [0.15, 0.35, 0.55, 0.75, 0.90]            # 上一篇 → 五篇前

    def candidates(locked: set, r: random.Random | None = None) -> dict:
        r = r or rng
        out = {}
        for m, w in base.items():
            if m in locked or w <= 0:
                continue
            decay = 1.0
            for i, row in enumerate(reversed(log[-5:])):
                if m in row.get("moves", []):
                    decay *= DIST_DECAY[i]
            out[m] = w * decay * r.uniform(0.5, 1.5)       # 扰动，打破周期
        return out

    weights = candidates(hard_locked)
    relax_level = 0
    if len(weights) < 3:
        weights = candidates(over_quota)
        relax_level = 1
    if len(weights) < 3:
        weights = candidates(set())
        relax_level = 2

    quota = min(rng.choice([3, 3, 4, 4, 5]), len(weights))   # 中位 3、均值 3.7 的形状

    # 组合级去重：抽出来的整组若跟最近五篇任一完全相同，换种子重抽
    # 候选被锁到只剩五个、又要抽四个时，可选组合只有五种，光换种子跳不出去。
    # 所以每次重抽都把冲突组里的一个动作临时锁掉，组合必然不同。
    recent_sets = [frozenset(r.get("moves", [])) for r in log[-5:]]
    moves = weighted_sample(rng, weights, quota)
    extra_lock: set[str] = set()
    for attempt in range(1, 12):
        if frozenset(moves) not in recent_sets:
            break
        rng2 = seeded_rng(args.title, salt=f"retry{attempt}")
        extra_lock.add(rng2.choice(sorted(moves)))
        pool = candidates(hard_locked | extra_lock, rng2)
        if len(pool) < 3:                                   # 锁过头就退回上一层
            pool = candidates(hard_locked, rng2) or weights
        moves = weighted_sample(rng2, pool, min(quota, len(pool)))

    # 其余维度走 LRU 轮换
    prof = data["profiles"][genre]
    tempo_pool = list(prof["tempo_dist"].keys())
    voice_pool = list(prof["voice_dist"].keys())
    tempo = rotate(rng, tempo_pool, [r.get("profile", {}).get("节奏", "") for r in log], avoid=2)
    voice = rotate(rng, voice_pool, [r.get("profile", {}).get("人称", "") for r in log], avoid=2)
    opening = rotate(rng, list(OPENINGS), [r.get("opening", "") for r in log])
    ending = rotate(rng, list(ENDINGS), [r.get("ending", "") for r in log])
    subtitle = rotate(rng, SUBTITLE_STYLES, [r.get("subtitle_style", "") for r in log], avoid=2)
    stance = rotate(rng, list(STANCES), [r.get("stance", "") for r in log])

    prev_portable = bool(log and log[-1].get("portable"))
    if prev_portable:                                   # 上一篇结论可移植，本篇换一种立场
        prev_stance = log[-1].get("stance", "")
        if stance == prev_stance:
            stance = rotate(rng, list(STANCES), [prev_stance], avoid=1)

    used_domains = [d for r in log[-2:] for d in r.get("metaphor_domains", [])]
    domains = [d for d in METAPHOR_DOMAINS if d not in used_domains]
    rng.shuffle(domains)
    domains = domains[:3]

    bands = data["bands"]
    tempo_band = bands["tempo"][tempo]
    single_band = bands["single_ratio_by_tempo"][tempo]

    return {
        "title": args.title,
        "genre": genre,
        "profile": {"节奏": tempo, "人称": voice, "篇幅": args.length},
        "bands": {
            "段落中位字数": tempo_band,
            "单句成段比例": single_band,
            "人称密度": bands["voice"][voice],
            "字数区间": list(LENGTH_BANDS[args.length]),
        },
        "moves": moves,
        "necessity_triggered": sorted(necessity),
        "opening": opening,
        "ending": ending,
        "subtitle_style": subtitle,
        "stance": stance,
        "metaphor_domains": domains,
        "relax_level": relax_level,
        "locked": {
            "硬锁动作": sorted(hard_locked),
            "降权动作": sorted(soft_locked),
            "近两篇比喻域": sorted(set(used_domains)),
        },
        "log_depth": len(log),
        "prev_portable": prev_portable,
    }


def render(p: dict) -> str:
    L = []
    L.append(f"\n=== 本篇档案：{p['title']} ===")
    L.append(f"文体 {p['genre']}｜节奏 {p['profile']['节奏']}｜人称 {p['profile']['人称']}"
             f"｜篇幅 {p['profile']['篇幅']}"
             + ("（冷启动，日志为空）" if p["log_depth"] == 0 else f"（参考最近 {p['log_depth']} 篇）"))
    b = p["bands"]
    hi = b["段落中位字数"][1]
    L.append(f"\n目标区间")
    L.append(f"  段落中位字数 {b['段落中位字数'][0]}–{hi if hi else '不限'}")
    L.append(f"  单句成段比例 {b['单句成段比例'][0]:.0%}–{b['单句成段比例'][1]:.0%}")
    L.append(f"  你 {b['人称密度']['you']}／我 {b['人称密度']['wo']}（每万字）")
    L.append(f"  正文字数 {b['字数区间'][0]}–{b['字数区间'][1]}")
    L.append(f"\n本篇只用这 {len(p['moves'])} 个动作，别的一律不上")
    for m in p["moves"]:
        L.append(f"  · {m}")
    L.append(f"  另有必要性触发项（需要才写，不占配额）：{'、'.join(p['necessity_triggered'])}")
    L.append(f"\n开头 {p['opening']}　{OPENINGS[p['opening']]}")
    L.append(f"结尾 {p['ending']}　{ENDINGS[p['ending']]}")
    L.append(f"小标题 {p['subtitle_style']}")
    L.append(f"立场 {p['stance']}　{STANCES[p['stance']]}")
    L.append(f"比喻取材域（挑一到两个，域内现造，别复用语料例子）：{'、'.join(p['metaphor_domains'])}")
    lk = p["locked"]
    if lk["硬锁动作"] or lk["降权动作"] or lk["近两篇比喻域"]:
        L.append("\n被跨篇记忆挡掉的")
        if lk["硬锁动作"]:
            L.append(f"  上一篇用过或五篇内用满三次，本篇禁用：{'、'.join(lk['硬锁动作'])}")
        if lk["降权动作"]:
            L.append(f"  最近五篇用过，权重按次数衰减：{'、'.join(lk['降权动作'])}")
    if p.get("relax_level"):
        L.append(f"  （候选被锁得太紧，已放宽到第 {p['relax_level']} 层）")
        if lk["近两篇比喻域"]:
            L.append(f"  近两篇的比喻域，本篇避开：{'、'.join(lk['近两篇比喻域'])}")
    if p.get("prev_portable"):
        L.append("\n⚠ 上一篇的结论是可移植的（换个主题也成立）。")
        L.append("  本篇结尾那句判断必须绑死这个主题：把主题词挖掉换成别的主题，句子要读不通。")
    L.append("\n写完记得回写日志：pick_profile.py log --log <路径> ...")
    return "\n".join(L) + "\n"


def append_log(args) -> int:
    if not args.log:
        print("必须给 --log 路径", file=sys.stderr)
        return 2
    row = {
        "date": args.date or "",
        "title": args.title,
        "genre": args.genre,
        "profile": {"节奏": args.tempo, "人称": args.voice, "篇幅": args.length},
        "moves": [m.strip() for m in args.moves.split(",") if m.strip()],
        "opening": args.opening,
        "ending": args.ending,
        "subtitle_style": args.subtitle_style,
        "stance": args.stance,
        "metaphor_domains": [d.strip() for d in args.domains.split(",") if d.strip()],
        "thesis": args.thesis,
        "portable": args.portable,
    }
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"已写入 {args.log}")
    if args.portable:
        print("注意：portable=true，这句结论换个主题也成立。下一篇必须换一种结论方式。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="AYi 文风稿件档案生成器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pick", help="生成本篇档案")
    p.add_argument("--genre", required=True, help="教程 / 拆解观点 / 复盘叙事")
    p.add_argument("--title", required=True)
    p.add_argument("--length", default="常规", choices=list(LENGTH_BANDS))
    p.add_argument("--log", type=Path)
    p.add_argument("--json", action="store_true")

    q = sub.add_parser("log", help="写完之后回写一行")
    q.add_argument("--log", type=Path, required=True)
    q.add_argument("--title", required=True)
    q.add_argument("--genre", required=True)
    q.add_argument("--tempo", default="")
    q.add_argument("--voice", default="")
    q.add_argument("--length", default="常规")
    q.add_argument("--moves", default="")
    q.add_argument("--opening", default="")
    q.add_argument("--ending", default="")
    q.add_argument("--subtitle-style", dest="subtitle_style", default="")
    q.add_argument("--stance", default="")
    q.add_argument("--domains", default="")
    q.add_argument("--thesis", default="", help="本篇的核心判断，一句话")
    q.add_argument("--portable", action="store_true",
                   help="这句结论换个主题也成立就加这个标记")
    q.add_argument("--date", default="")

    args = ap.parse_args()
    if args.cmd == "log":
        return append_log(args)

    result = pick(args)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
