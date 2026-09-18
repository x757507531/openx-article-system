# OpenX 文章系统 — 机器读取入口

> 本文件是 **产文系统（写作 skill / agent）唯一的入口规范**。
> 任何要为 OpenX 写新文章、改旧文章、做翻译的流程，**开工前必须先读本文件**。
> 人类可读的总览在 [00-系统说明.md](00-系统说明.md)，本文件只写机器需要的确定性规则。

Vault 根目录（绝对路径，供外部 skill 引用）：

```
<VAULT_ROOT>
```

---

## 1. 这套系统解决什么

两件事，缺一不可：

1. **关键词审核** — 新文章的主关键词是否与已有文章冲突（关键词蚕食 / keyword cannibalization）。
2. **内链设计** — 新文章该在**哪个 H2 下、用什么锚文本**链向哪篇旧文；以及新文发布后，**哪些旧文的哪一段**要补一条链回来。

规则是：**一个主关键词，只能有一篇文章拥有它（同语言内）。** 违反即视为立项失败。

---

## 2. 目录约定（路径写死，不要改名）

| 路径 | 作用 | 谁写 |
|---|---|---|
| `01-索引/关键词登记表.md` | 主/副关键词 → 归属文章的人类可读视图 + 同义词组 | 每次立项/发布后更新 |
| `01-索引/文章总表.md` | 所有文章的 ID / 状态 / 语言 / 主题簇 | 每次状态变更后更新 |
| `01-索引/内链矩阵.md` | 文章间链接关系与插入位置 | 内链设计后更新 |
| `01-索引/术语与锚文本表.md` | 多语言术语统一 + 每篇文章可用锚文本池 | 立项时补 |
| `01-索引/作者资料.md` | 署名作者的完整资料、`Person` 标记草稿、上线待办 | 作者信息变更时 |
| `02-主题簇/` | 每个主题簇一个 MOC（pillar 笔记） | 建簇时 |
| `03-文章/<lang>/` | 正文。lang ∈ `zh-Hant` `zh-Hans` `en` `ja` `ko` `vi` `th` | 写作时 |
| `04-模板/` | 文章 / 审核报告 / 主题簇 模板，`示例/` 下有填好的样例 | 只读 |
| `05-SOP/` | 五份 SOP + 一份真实流程演示（x402） | 只读 |
| `06-工作区/导出/<article_id>/` | docx 导出、行情案例原始数据 `data/` 与制图脚本 | M7／案例写作时 |
| `06-工作区/质检/`、`06-工作区/复盘/` | M8 质检报告、跨篇复盘 | M8 |
| `05-SOP/SOP-5-SEO與GEO檢查清單.md` | 全部 45 项检查的总览与阶段跑法（与 `seo-geo-check/reference/check-items.md` 手工同步） | 规则变更后重新导出 |
| `06-工作区/审核报告/` | 每次审核的输出落盘处 | 审核时 |
| `06-工作区/待导入/` | 存量文章回填的暂存区 | 导入时 |
| `工具/openx_audit.py` | 机械检查脚本（关键词冲突 + 内链候选 + 全库体检） | 只读 |
| `工具/new_article.py` | 立项建档：分配 ID、建 idea 文件、写两张索引表 | 只读 |
| `工具/writeback.py` | 闸 3 回写：frontmatter + 对端 inbound + 三张索引表（幂等，带 diff） | 只读 |

文件命名：`03-文章/<lang>/OX-0001-<slug 或短标题>.md`

### 事实来源的层级（两者冲突时按这个判）

- **`03-文章/` 下的 frontmatter 是机器事实来源。** 脚本的所有冲突判定都读它。
- **`01-索引/` 的三张表是人类可读视图，必须与 frontmatter 保持一致。** 两者不一致时以 frontmatter 为准，并立即修表。
- 唯一的例外：`关键词登记表` 的**同义词 / 变体组**表格只存在于表里，是脚本的额外输入。

推论：**一篇文章在 `03-文章/` 下没有文件，对系统就等于不存在。**
所以立项（`status: idea`）时就要建文件，不能只登记表格——见 [SOP-1 Step 5](05-SOP/SOP-1-选题与关键词审核.md)。

---

## 3. 文章 frontmatter 契约

**所有** `03-文章/` 下的 md 必须带完整 frontmatter。字段缺失 = 不进入索引 = 审核会漏判。

```yaml
---
article_id: OX-0001          # 全局唯一。跨语言共享同一个 ID
title: 標題
lang: zh-Hant                # zh-Hant | zh-Hans | en | ja | ko | vi | th
source_lang: zh-Hant         # 源语言。翻译版本填源语言，源文件填自己
status: idea                 # idea | drafting | review | ready | translated | published
cluster: 交易所入門           # 所属主题簇（内容组织单位），必须是 02-主题簇/ 下已存在的簇
category: 新手入門            # 站点导航栏目，6 选 1。与 cluster 是两套体系，见下方说明
primary_keyword: OpenX 註冊   # 唯一。同语言内不可与他文重复
secondary_keywords:          # 可与他文共享，但必须登记
  - OpenX 開戶
  - 加密貨幣交易所註冊
serp_intent: 信息型           # 信息型 | 导航型 | 商业型 | 交易型
slug: openx-signup           # URL 未定时也先想好，作为文件名后缀
url:                         # 发布后回填真实 URL，未发布留空
publish_date:
updated:
pipeline_stage: M3           # 产文流水线位置 M1…M9 / done，由 seo-writing-openx 维护
outbound_links: []           # 本文链出的 article_id 列表
inbound_links: []            # 链向本文的 article_id 列表
anchor_offers:               # 别人引用本文时可用的锚文本候选（≥3 条，避免全站锚文本雷同）
  - OpenX 註冊教學
  - 如何開通 OpenX 帳戶
  - OpenX 新手開戶流程
author:                      # 署名作者。空 = 未定，检查会判 FAIL
author_credentials:          # 作者资格：学经历／执业资格／擅长领域
author_url:                  # 作者页地址（唯一辨识作者的那一页），上线后回填
---
```

### `cluster` 与 `category` 是两套体系，不要混用

| | `cluster` 主题簇 | `category` 站点栏目 |
|---|---|---|
| 面向 | 内部 | 读者 |
| 作用 | 决定文章属哪个知识群，进而决定内链关系与 pillar 上行链 | 决定文章挂在导航哪个入口 |
| 取值 | 按主题自由建立，须在 `02-主题簇/` 下存在 | 固定 6 选 1：`最新消息` `新手入門` `策略分析` `風險管理` `市場回顧` `工具教學` |
| 是否显示给读者 | **不显示**，纯内部字段 | 显示，且是 `BreadcrumbList` 标记的层级来源 |

一篇文章两个都要有。以前只有 `cluster`，导致作者把栏目也往里填（OX-0001 的「建議分類」写成
「Web3 知識 ／ AI 與加密」，那是簇的思路不是栏目），检查会判 FAIL。

### 作者三字段（`author` / `author_credentials` / `author_url`）

官方把「显示作者、资格、发布与更新日期」列为 **P0**，且要求作者名连向能唯一辨识作者的页面。
这三个字段同时是 `Person` 标记与 `Article.author` 的数据来源——不填，A10 与 E3 都过不了。

**站点署名作者在安装后自行设定**：填 `01-索引/作者资料.md`，并设环境变量 `OPENX_AUTHOR` 与 `OPENX_AUTHOR_CREDENTIALS`（或每次给 `new_article.py --author/--author-credentials`）。

`author_credentials` 存**短版**（一行，机器读），例如「曾任 XX 研究員；XX 官方合作講師」。
完整介绍文案、`Person` 标记草稿与上线待办都在 [01-索引/作者资料.md](01-索引/作者资料.md)。

**这个字段必须填真实内容，不许由脚本或模型代填**——编造学经历、执业资格是伪造 E-E-A-T 信号，
被发现的代价是整站信誉，加密内容属 YMYL 更受不起。

`author_url` 在官网上线、作者页做出来之后回填。

### 字段的硬约束

- `article_id` 跨语言共享。`OX-0001` 的繁中版和日文版是**同一篇文章的两个语言版本**，不是两篇文章。
- `primary_keyword` 的唯一性检查**按 (lang, primary_keyword) 组合**判定。繁中的「OpenX 註冊」和日文的「OpenX 登録」互不冲突。
- `outbound_links` / `inbound_links` 存 `article_id`，**不存文件路径**（路径会变，ID 不会）。
- `url` 未定阶段留空。正文内链一律先用 Obsidian `[[wikilink]]`，发布时由 SOP-2 的映射步骤换成真实 URL。

---

## 4. 产文系统必须执行的闸

任何写 OpenX 新文章的流程，按顺序过这几道，**不允许跳步**：

### 闸 1 — 立项前：关键词冲突审核
执行 [05-SOP/SOP-1-选题与关键词审核.md](05-SOP/SOP-1-选题与关键词审核.md)。
先跑脚本拿机械结论，再做语义判断：

```bash
python3 "工具/openx_audit.py" keyword --lang zh-Hant --primary "新文主关键词" --secondary "副词1,副词2"
```

冲突分四级（L1 致命 / L2 高危 / L3 中危 / L4 低危）。**L1、L2 未解决不得进入写作。**

### 闸 1.5 — 立项后、写大纲前：信息增益

**这是全流程唯一一道朝外看的闸。** 闸 1 查的是新文跟**站内**旧文撞不撞，它从不问
「SERP 前 10 已经写得多好、这篇有什么是他们没有的」。少了这一道，可以一路绿灯产出一篇
结构完美、元数据齐全、而内容 SERP 前 10 全都有的文章。

```bash
mkdir -p "06-工作区/增益/<article_id>"
python3 ~/.claude/skills/seo-writing-orange/scripts/gate.py gain \
  "06-工作区/增益/<article_id>" --min-items 1
```

**至少 1 条**「SERP 前 10 都没有的内容」，每条带一手来源 URL，**并且说得出「读者缺了这条会做错
什么决定、或多花多少时间」**。`--min-items 1` 不能省（脚本默认要 3 条，那是 1000X 口径）。

价值条件脚本判不了，必须人／agent 判：说不出读者的实际损失，这条就不算增益——只数条数会把
没价值的内容硬凑进来，而没人写往往正因为不值得写。

### 闸 2 — 大纲后：内链设计
执行 [05-SOP/SOP-2-内链设计.md](05-SOP/SOP-2-内链设计.md)。
在**大纲阶段**做，不是写完再补。产出必须精确到「H2 名称 + 锚文本 + 方向」。

```bash
python3 "工具/openx_audit.py" links --lang zh-Hant --cluster "主题簇" --keywords "主词,副词1,副词2"
```

输出两张表：**新文 → 旧文**（本次写作时插）、**旧文 → 新文**（发布后回头改旧文，必须真的改）。

### 检查清单（贯穿全流程）

四道闸之外，还有 45 项 SEO/GEO 检查分布在各阶段——正文层由 `seo-geo-check` 判，
元数据／结构化数据／站点技术层由 `check_geo.py` 判。

**M8 先做内容准确性复核，再做文风检查**（2026-09-18 起）：GEO 评审只管结构，结论是否超出来源、案例是否用了事后信息、
案例价位能否逐根核上，要由一个只拿成稿与原始数据的复核 subagent 加 D18／D19／D20 机检另判。
有行情案例的文章，原始 K 线 JSON 与制图脚本必须存进 `06-工作区/导出/<article_id>/`。

总览与各阶段该跑什么：[05-SOP/SOP-5-SEO與GEO檢查清單.md](05-SOP/SOP-5-SEO與GEO檢查清單.md)

### 闸 3 — 发布后：回写索引
结构性部分跑脚本（幂等，先 `--dry-run` 看 diff）：

```bash
python3 "工具/writeback.py" --article OX-xxxx --lang zh-Hant --status published \
  --url "https://..." --publish-date YYYY-MM-DD --outbound "OX-aaaa" --stage done
```

脚本覆盖 frontmatter 六字段、**对端 inbound_links（对称性）**、文章总表三处、关键词登记表主词状态、锚文本池。
内链矩阵的明细行、待补队列勾销、旧文正文插链**仍需人工**——脚本会在结尾逐条列出来，做完才算过闸。
**不回写 = 下一篇文章的审核会基于过期数据做出错误判断。** 这是整套系统最容易烂掉的一环。

---

## 5. 多语言处理原则

- **内链关系只在源语言层设计一次**，各语言版本继承同一套 `outbound_links` / `inbound_links`（因为它们指向 `article_id`）。
- 翻译版本要做的只有一件事：把锚文本换成目标语言的说法 —— 取自该目标文章**对应语言版本**的 `anchor_offers`。
- 术语一致性走 `01-索引/术语与锚文本表.md`，与既有翻译 skill（`web3-zh-en/ja/ko/vi/th-translation`、`1000x-article-translator`）的术语库对齐，不重复造一套。
- 详见 [05-SOP/SOP-4-多语言同步.md](05-SOP/SOP-4-多语言同步.md)。

---

## 6. 与外部 skill 的衔接

本系统是**参考层与审核层**，不负责写正文。

**编排入口是 `seo-writing-openx` skill**（`~/.claude/skills/seo-writing-openx/`）。
它把下面这些环节串成九个模块的流水线，并强制过本系统的三道闸。
用户说「写 OpenX 文章」时应当走它，而不是直接调写作 skill。

分工：

| 环节 | 由谁做 |
|---|---|
| 全流程编排、模块交接 | `seo-writing-openx`（M1–M9） |
| GEO 结构要求（写前）与正文审核（写后） | `seo-geo-check`（M5 前后各一次） |
| 选题、关键词冲突审核、内链设计 | **本系统**（SOP-1 / SOP-2） |
| SERP 分析、大纲 | `seo-writing-openx`（M3） |
| 正文撰写 | `human-writing-AYI`（M5） |
| 去 AI 味、质量审核 | `article-deai-flow`、`article-quality-checker` |
| 元数据／结构化数据／站点技术层检查 | `seo-writing-openx/scripts/check_geo.py`（M6 与站点级） |
| 多语言翻译 | `web3-zh-*-translation`、`1000x-article-translator` |
| 视觉强调、docx 输出 | `article-visual-polish` |
| 发布后回写索引 | **本系统**（闸 3） |

外部 skill 调用本系统时，读取顺序：本文件 → 对应 SOP → 索引表。

---

## 7. 存量文章回填

**「存量」只指 OpenX 自己已发布的文章。** 1000X 旧站不是存量，其文章转换路线已于 2026-09-17 整体放弃，不再作为选题或素材来源。

存量文章由用户后续提供。回填走 [05-SOP/SOP-3-存量文章导入.md](05-SOP/SOP-3-存量文章导入.md)：
文件丢进 `06-工作区/待导入/` → 提取 frontmatter → 分配 `article_id` → 写入索引表 → 跑一次全量冲突扫描（`python3 "工具/openx_audit.py" scan`）清理历史蚕食。

**在存量回填完成之前，闸 1 的审核结论是不完整的**，写新文时要意识到这一点。
