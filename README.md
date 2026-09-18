---
type: readme
name: OpenX 文章系统 README
updated: 2026-09-18
---

# OpenX 文章系统 README

> 给第一次接手的人看的总览：这套系统是什么、文章怎么从一个词变成一篇可上线的稿、每一步谁负责、哪里最容易出错。
> 机器读取入口是 [CLAUDE.md](CLAUDE.md)，写作 skill 开工前先读它；本文不重复那里的确定性规则，只讲逻辑与全貌。

---

## 一、这套系统是什么

一个 Obsidian Vault 形态的**内容中枢**，配三个外部 skill 组成的产文流水线。它管三件事：

| 职责 | 解决什么问题 | 在哪 |
|---|---|---|
| 关键词审核 | 新文章的主关键词会不会和站内旧文抢同一个搜索位（蚕食） | Vault 索引表 + `工具/openx_audit.py` |
| 内链设计 | 新文该在哪个 H2、用什么锚文本链向哪篇；发布后哪些旧文要补链回来 | Vault 内链矩阵 + SOP-2 |
| 产文编排与质量闸 | 从选题到交付的九个模块，每个交接点该产出什么、什么条件才能往下走 | `seo-writing-openx` + `seo-geo-check` + `human-writing-AYI` |

**铁律只有一条**：一个主关键词，同一语言内只能有一篇文章拥有它。其余规则都从这条派生。

**两个边界**：
- 本系统**不负责写正文**，正文由 `human-writing-AYI` 写；本系统负责选题合法性、内链、审核、索引。
- 1000X 旧站**不是**本站的存量或素材来源（2026-09-17 决定），OpenX 只做新文章。旧站取词时得到的台湾繁中 SERP 数据仍可作选题输入，存 `06-工作区/C3-取词/`。

---

## 二、目录地图

```
CLAUDE.md                  机器入口，产文 skill 开工必读
README.md                  本文
00-系统说明.md              早期人类总览（2026-08）
00-流程图.md                mermaid 流程图
01-索引/                    系统的心脏
   关键词登记表.md            主词排他占用 + 副词登记 + 同义词组 + 待仲裁冲突
   文章总表.md                ID 台账 / 状态 / 语言矩阵 / 已发布 URL
   内链矩阵.md                已落实链接 + 待补链接队列 + 密度阈值
   术语与锚文本表.md          六语术语对照 + 每篇文章的锚文本池
   作者资料.md                署名作者资料模板与 Person 标记草稿
   series-log.jsonl           AYI 文风日志（每篇一行，防 50 篇长得一样）
02-主题簇/                  每簇一个 MOC：覆盖范围、边界、pillar、子文、选题池、健康度
03-文章/<lang>/             正文，frontmatter 是机器事实来源；imgs/ 放配图
04-模板/                    文章 / 审核报告 / 主题簇 模板
05-SOP/                     SOP-1 选题审核 · SOP-2 内链 · SOP-3 存量导入 · SOP-4 多语言 · SOP-5 检查清单总览
06-工作区/
   审核报告/                 每篇立项审核 + 外部 SEO 审阅报告
   增益/<id>/                闸 1.5 的 gain.md 与大纲 outline.md
   GEO自检/                  评审任务、评审结果、人工项答案
   导出/<id>/                docx、案例原始数据 data/*.json + README + derived.txt、制图脚本
   质检/                     M8 质检报告
   复盘/                     跨篇流程复盘
   C3-取词/                  台湾繁中取词与 SERP 记录卡（市场证据）
   归档来源/                 已放弃路线与历史批次的留档，不再读
工具/
   openx_audit.py           keyword 冲突审核 / links 内链候选 / backlink 回链定位 / scan 全库体检 / langcheck
   new_article.py           立项建档：分配 ID、建 idea 文件、写两张索引表
   writeback.py             闸 3 回写：frontmatter + 对端 inbound + 三张索引表（幂等，带 diff）
   suggest_probe.py         Google 自动完成取词（N512 打分）
```

**事实来源的层级**：`03-文章/` 的 frontmatter 是机器事实来源；`01-索引/` 三张表是人类视图，不一致时以 frontmatter 为准并立即修表。一篇文章在 `03-文章/` 下没有文件，对系统就等于不存在。

---

## 三、文章的产出逻辑

### 3.1 先有簇，再有文

文章不单独存在，先属于一个**主题簇**。簇是内部内容组织单位，决定内链关系与 pillar 上行链；与读者看到的站点**栏目**（`category`，6 选 1）是两套体系，一篇文章两个都要有。

一个簇有且仅有一篇 **pillar**，pillar 必须链到簇内每篇子文，每篇子文有且仅有一条链回 pillar。**没有 pillar 的簇不许开子文**。

建簇前先取词：用 `suggest_probe.py` 打词根 N512、看 SERP 前 10 的权威墙与意图纯度，判断这个词在台湾繁中到底是谁的地盘。技術分析簇的经验：布林通道、波浪理論、葛蘭碧、均線这类词有量但属台股散户，加密限定形式归零，OpenX 抢到也是错的受众；SMC 词族（訂單塊、FVG、破壞塊）才是加密原生的独立查询空间。

### 3.2 九个模块，四道闸

编排入口是 `seo-writing-openx` skill。用户说「写 OpenX 文章」走它，不直接调写作 skill。流程位置记在文章 frontmatter 的 `pipeline_stage`（M1…M9 / done），断点续跑从这里读。

| 阶段 | 模块 | 做什么 | 谁做 | 产出落在哪 |
|---|---|---|---|---|
| 选题 | M1 | 选题输入：优先查簇 MOC 的待写选题池 | seo-writing-openx | — |
| | **M2 · 闸 1** | 关键词四级冲突审核（L1 致命／L2 高危／L3 中危／L4 低危），L1、L2 未解决不许写；过闸后 `new_article.py` 建 idea 文件 | Vault SOP-1 | `03-文章/`、两张索引表、审核报告 |
| | **M3 · 闸 1.5** | 信息增益：至少 1 条「SERP 前 10 都没有」且带一手来源、说得出读者缺了会怎样；然后 SERP 分析、H2/H3 大纲、每个 H2 一句话结论、**案例计划** | seo-writing-openx + `gate.py` | `06-工作区/增益/<id>/gain.md`、文章文件 |
| 写作 | **M4 · 闸 2** | 内链设计：新文→旧文精确到 H2 + 触发词 + 锚文本；旧文→新文进待补队列。密度每 800 字 ≤2 条、单篇 3–8 条、同一目标只链一次 | Vault SOP-2 | 文章文件「内链清单」、内链矩阵 |
| | M5 | 先 `pick_profile.py` 取本篇稿件档案（节奏／人称／动作／开头结尾），再取 `seo-geo-check` 的 GEO 结构要求，交给 `human-writing-AYI` 写正文；写完 `audit_d.py` 机检 + 独立评审 + 原文回验 | AYI + seo-geo-check | 文章正文、`GEO自检/` |
| | M6 | Meta Title / Description / 摘要 / slug / 标签 / Schema 建议 / 关键词布局，`check_geo.py` 退出码 0 | seo-writing-openx | 文章文末「上稿用 SEO 資訊」 |
| 整理 | M7 | 视觉强调三层（专名加粗／论点句黄底／钩子词加粗加黄底）导出 docx；多语言版本 | article-visual-polish、翻译 skill | `06-工作区/导出/<id>/` |
| | M8 | **内容准确性复核**（先）→ GEO 评审 → 交付态文风检查 → 四维质检 → 回写文风日志 | 复核 subagent + check_ayi + article-quality-checker | `06-工作区/质检/`、`series-log.jsonl` |
| | **M9 · 闸 3** | 发布后 `writeback.py` 回写 frontmatter、对端 inbound、三张索引表；人工补旧文正文链、勾销待补队列；`scan` 体检 | Vault | 全部索引表 |

**红线**：不许跳闸；M2 未过不写大纲，闸 1.5 未过不写大纲，M4 未做不写正文，M8 未回写日志不进 M9，M9 未做不算交付。

### 3.3 三层审核，各管一件事

| 层 | 管什么 | 不管什么 | 工具 |
|---|---|---|---|
| 关键词与内链 | 站内会不会自己撞、链有没有接上 | 内容对不对 | `openx_audit.py` |
| GEO 结构（45 项检查） | 开头速答块、每节首句结论、FAQ 从正文提取、来源就近、术语定义、绝对化表述、案例可执行、行情数据可复现、元数据、Schema | 文风 | `audit_d.py`（D 区，独立评审 + 原文回验）、`check_geo.py`（A／E／J 区） |
| 内容准确性 | 结论是否超出来源、读者能否完成任务、案例是否用了事后信息、价位与时序能否逐根核上 | 结构与文风 | M8 复核 subagent + D18／D19／D20 |
| 文风 | 段落节奏、人称密度、动作轮换、AI 味 | 事实 | `check_ayi.py`（跑交付态副本）、article-quality-checker |

**为什么要第三层**：2026-09-18 三轮外部 SEO 复核证明，前两层全绿的稿子仍可能案例日期写错、结论超出来源、把解释写成事实。GEO 评审只判结构，不判真假。复盘见 `06-工作区/复盘/`。

### 3.4 有行情案例的文章，多三条纪律

1. **数据先落盘**：用固定 `startTime/endTime` 抓原始 K 线，存 `06-工作区/导出/<id>/data/`，附 README 写请求参数，推导值（停损距离等）写 `derived.txt` 附算式。
2. **规则先于标注**：用哪个周期的收盘判结构、影线算不算、区间怎么取、确认／收线失效／价格停损／放弃四类条件，先写在案例开头，再按规则逐根核 OHLC 标注。每个标注只能用它那个时点之前的信息。
3. **价位逐字可核**：正文每个带小数的价位必须能在 JSON 里找到，D20 会机检。

### 3.5 多语言

`article_id` 跨语言共享，冲突按 (lang, primary_keyword) 判。内链关系只在源语言设计一次，各语言版本继承，只换锚文本（取目标文章该语言版本的 `anchor_offers`）；目标语言版本不存在就删链进待补队列，不硬翻。见 SOP-4。

---

## 四、脚本速查

```bash
# 闸 1：关键词冲突
python3 "工具/openx_audit.py" keyword --lang zh-Hant --primary "主词" --secondary "副1,副2"
# 立项建档
python3 "工具/new_article.py" --lang zh-Hant --title "…" --primary "…" --secondary "…" --cluster "簇" --category "栏目" --slug "…" --intent 信息型 --anchors "锚1,锚2,锚3"
# 闸 1.5
python3 ~/.claude/skills/seo-writing-orange/scripts/gate.py gain "06-工作区/增益/OX-xxxx" --min-items 1
python3 ~/.claude/skills/seo-writing-orange/scripts/gate.py outline "06-工作区/增益/OX-xxxx" --min-h2 0
# 闸 2
python3 "工具/openx_audit.py" links --lang zh-Hant --cluster "簇" --keywords "主词,副词"
python3 "工具/openx_audit.py" backlink --lang zh-Hant --target OX-xxxx --keyword "主词"
# M5 前后
python3 ~/.claude/skills/human-writing-AYI/scripts/pick_profile.py pick --genre 教程 --title "…" --length 长文 --log "01-索引/series-log.jsonl"
python3 ~/.claude/skills/seo-geo-check/scripts/audit_d.py "<文章.md>" --stage scan      # 然后 spawn 独立评审
python3 ~/.claude/skills/seo-geo-check/scripts/audit_d.py "<文章.md>" --stage verify
# M6
python3 ~/.claude/skills/seo-writing-openx/scripts/check_geo.py "<文章.md>"
# M8
python3 ~/.claude/skills/seo-writing-openx/scripts/deliver_copy.py "<文章.md>"           # 交付态副本
python3 ~/.claude/skills/human-writing-AYI/scripts/check_ayi.py "<副本>" --profile <节奏>:<人称> --series "01-索引/series-log.jsonl"
python3 ~/.claude/skills/human-writing-AYI/scripts/pick_profile.py log --log "01-索引/series-log.jsonl" …
# M9
python3 "工具/writeback.py" --article OX-xxxx --lang zh-Hant --status published --url "…" --publish-date YYYY-MM-DD --outbound "OX-a,OX-b" --stage done --dry-run
python3 "工具/openx_audit.py" scan
```

---

## 五、安装与初始化

```bash
git clone https://github.com/x757507531/openx-article-system.git
cd openx-article-system
./install.sh            # 复制 skills/ 下四个 skill 到 ~/.claude/skills（已存在的不覆盖，--force 才覆盖），并把本仓库路径写进 CLAUDE.md / AGENTS.md / skill 引用处
```

安装后三件事：

1. 填 `01-索引/作者资料.md`，并 `export OPENX_AUTHOR="…"`、`export OPENX_AUTHOR_CREDENTIALS="…"`（或每次立项时给 `new_article.py --author`）。作者资格必须真实。
2. 站点栏目（`category` 6 选 1）与品牌名若与 OpenX 不同，改 `CLAUDE.md` 第 3 节与 `skills/seo-writing-openx/scripts/check_geo.py` 顶部的 `SITE_CATEGORIES`。
3. `pip3 install opencc-python-reimplemented`（繁中稿字面比对需要）；画行情案例图另需 `matplotlib`。Python 3.10+。Obsidian 可选，脚本不依赖它。

可选依赖（M7／M8 会调、不在本仓库）：`article-visual-polish`、`article-quality-checker`、各语言 `web3-zh-*-translation`。缺了它们流程仍能跑到 M8 的机检与评审。

出厂状态：索引表全空、`02-主题簇/` 与 `03-文章/` 为空、下一个 ID 为 OX-0001、`series-log.jsonl` 为空。写第一篇的最短路径：读 CLAUDE.md → 用 `04-模板/主题簇模板.md` 建第一个簇并定 pillar → 跑闸 1 → `new_article.py` → 调 `seo-writing-openx` 从 M3 续跑。

## 六、最容易烂掉的四个地方

1. **闸 3 不回写**。下一篇的审核就基于过期数据。
2. **只登记表格不建文件**。脚本读的是 frontmatter，表格里的文章对系统不存在。
3. **全绿不等于正确**。三层审核缺一层，稿子就会带着结构完美的错误上线。
4. **改了规则不 grep 旧措辞**。案例规则一换，散在各节的旧口径句子会留下来。
