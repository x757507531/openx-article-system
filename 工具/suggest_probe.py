#!/usr/bin/env python3
"""SOP-6 闸 C3b 的取词与打分工具：Google 自动完成端点。

两个模式：
  score   <词>    打分——返回 N512（该词在 Google 繁中查询日志里的真实建议条数）
  harvest <词根>  取词——枚举修饰词，汇成一份「实录短语清单」，候选主词从清单里挑

为什么是这个形态：C3b 的正确做法不是给自造的候选词打分，而是**反过来用 Google 的
查询日志生成候选词**。实测 24 个 SOP-6「B 堆」形状的自造候选，16 个 N512=0——
不是它们没需求，是台湾人不用那种句式搜（你写「網格交易風險」，人家搜「網格交易賠錢ptt」）。

N512 = 返回条目的 google:suggestsubtypes 里含 512 的条数。
512 被认为代表「该语言查询日志里真实存在的查询」，30/5 是机器扩展与实体前缀。
**这是观察，不是官方文档**——Google 若停止吐 subtype，降级为「N≥1 且首条建议即词本身」。

## 实测校正（2026-09-12，与设计稿的两条「铁律」不符，以本节为准）

1. **`hl` 的影响取决于查询用什么字符集写**，设计稿称「hl≠zh-TW 时 512 全部消失」**不成立**：
   - **纯繁中词**：`hl=zh-TW` 与 `hl=en` 返回**完全相同**（实测 穩定幣/停損點/冷錢包/合約爆倉/智能合約 5/5 一致）。
     Google 按查询字符集路由，`hl` 管不着。
   - **拉丁字符词**：`hl` **决定返回哪个语言的查询日志**。实测 `fvg` 在 zh-TW 下是
     `fvg是什麼`/`fvg缺口`，在 en 下是 `fvg trading`/`fvg meaning in trading`；
     `bitunix`、`restaking` 同样。N512 数字一样，内容是两个市场。
   - **所以 `hl=zh-TW` 必须固定死**——SMC / FVG / SNR / OB 这类拉丁术语正是本项目技術分析簇的高频词，
     hl 错了会拿到英文市场的查询，整道闸跑偏而且不报错。
   - `hl=zh-CN` 对繁中词也会换库（穩定幣 10→6、停損點 10→1），那是另一个市场。
2. 尾空格**不必然**归零：提幣 3→0 成立，冷錢包 10→10 不变。
   「打分只用裸词」这条操作建议仍然保留（带空格那次是用来枚举修饰词的），但别当成铁律去解释异常。

## 其他实测事实

- `gl` 参数无效，改不改都一样；决定结果的是 `hl`。
- 顶层 subtypes 的位置：`client=firefox` 在 d[3]，`client=chrome` 在 d[4]。本脚本一律全扫，不写死索引。
- **裸 HTTP 抓 Google SERP 不行**（拿回 JS 壳或 sorry 页），所以本端点是唯一能脚本化的。
  但 2026-09-13 验证：**真实浏览器内核读得到 SERP 全文**（Claude 的 Browser 工具，
  `google.com/search?q=<词>&gl=TW&hl=zh-TW&pws=0`），自然结果 + 相關問題 + 其他人也搜尋 全在。
  6 次连续查询、间隔 3 秒未触发拦截。故 C3 的 D5–D8 不必人工，但**必须串行**，遇验证码即停。
"""
import json, sys, time, urllib.parse, urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
SUFFIX = ["是什麼", "怎麼", "推薦", "教學", "風險", "費用", "ptt", "dcard"]
FANOUT = list("怎哪推教風費手爆提出開稅止資買賣安被忘壞跨轉")


def q(word, client="firefox", tries=4):
    """取 512 建议。SSL EOF / 连接重置 = 端点在限速，退避重试（2026-09-13 加）。

    实测：连续跑两轮 harvest（约 124 次 probe / 75 秒）必被切断。
    单轮 62 次 probe @0.9s 没问题。两轮之间隔至少 60 秒。
    """
    url = ("https://suggestqueries.google.com/complete/search?client=%s&hl=zh-TW&gl=tw&q=%s"
           % (client, urllib.parse.quote(word)))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(tries):
        try:
            raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
            break
        except Exception as e:                      # SSLEOFError / URLError / 连接重置
            if attempt == tries - 1:
                sys.exit("端点连续 %d 次拒绝，判定为限速，停手：%r\n  最后一个词：%s"
                         % (tries, e, word))
            back = 5 * (2 ** attempt)               # 5 / 10 / 20 秒
            print("  ! %s → 退避 %ds 重试（%r）" % (word, back, e), file=sys.stderr)
            time.sleep(back)
    if not raw.lstrip().startswith("["):
        sys.exit("非 JSON 返回，已被限速，立刻停手：" + raw[:120])
    d = json.loads(raw)
    subs = []
    for el in d:                        # firefox 档在 d[3]、chrome 档在 d[4]，一律全扫
        if isinstance(el, dict) and "google:suggestsubtypes" in el:
            subs = el["google:suggestsubtypes"]
    return [s for i, s in enumerate(d[1]) if i < len(subs) and 512 in subs[i]]


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__.split("\n\n")[1])
    mode, word = sys.argv[1], sys.argv[2]
    if mode == "score":
        hits = q(word)                  # 裸词
        print("N512=%d  %s" % (len(hits), word))
        print("\n".join("  " + h for h in hits))
        return
    if mode != "harvest":
        sys.exit("mode 只能是 score 或 harvest")
    seen = {}
    probes = [word, word + " "]
    probes += [word + s for s in SUFFIX] + [word + " " + s for s in SUFFIX]
    probes += [word + c for c in FANOUT] + [word + " " + c for c in FANOUT]
    for p in probes:
        for h in q(p, client="chrome"):  # chrome 档一次回 15 条，取词用
            seen.setdefault(h, p)
        time.sleep(0.9)
    print("# 实录短语清单 · 词根=%s · 抓取日期=%s · 共 %d 条"
          % (word, time.strftime("%Y-%m-%d"), len(seen)))
    print("\n".join(sorted(seen)))


if __name__ == "__main__":
    main()
